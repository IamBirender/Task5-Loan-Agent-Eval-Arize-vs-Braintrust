"""Run one test case. Supervisor is Strands here; specialists are AgentCore apps."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable

from . import agents, context, models, telemetry, tools
from .aws_config import SPECIALISTS

DEFAULT_WORKERS = 8


def _case_payload(case: dict, session_id: str) -> dict:
    return {
        "case_id": case["id"],
        "gate": case.get("gate"),
        "method": case.get("method"),
        "expected": case.get("expected"),
        "guidelines": case.get("guidelines") or [],
        "expected_tools": case.get("expected_tools") or [],
        "forbidden": case.get("forbidden") or [],
        "fault": case.get("fault"),
        "session_id": session_id,
    }


def worker_count(requested: int | None = None) -> int:
    if requested is not None:
        return max(1, requested)
    raw = os.getenv("LOAN_EVAL_WORKERS", str(DEFAULT_WORKERS)).strip() or str(DEFAULT_WORKERS)
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_WORKERS


def run_case(case: dict) -> dict:
    tools.CALLS.clear()
    models.RUN_AGENTS.clear()
    session_id = context.pad_session_id(case.get("session_id"), case["id"])
    context.session_id.set(session_id)
    context.case_id.set(case["id"])
    context.fault.set(case.get("fault"))
    telemetry.setup_tracing()
    t0, answers, error = time.time(), [], ""
    tables_intact = True
    usage = {"input_tokens": 0, "output_tokens": 0, "tokens": 0, "est_cost_usd": None}
    agent_name = agents.CASE_AGENT[case["agent"]]
    payload = _case_payload(case, session_id)
    token = None
    span_cm = telemetry.tracer().start_as_current_span(f"loan.eval.{case['id']}")
    span = span_cm.__enter__()
    telemetry.set_span_case_attributes(span, payload)
    try:
        if models.PROVIDER == "dryrun":
            answers = [f"(dry run - no AI model was called for {case['id']})"]
        elif models.PROVIDER == "agentcore" and agent_name in SPECIALISTS:
            from . import client

            for turn in case.get("turns") or [case["input"]]:
                result = client.invoke_specialist(
                    agent_name,
                    turn,
                    session_id,
                    payload=payload,
                    traceparent=telemetry.current_traceparent(),
                )
                answers.append(result.get("answer") or result.get("text") or "")
                error = result.get("error") or error
                tables_intact = bool(result.get("tables_intact", True)) and tables_intact
                for call in result.get("tool_calls") or []:
                    if isinstance(call, dict):
                        tools.CALLS.append(call)
                usage = {
                    "input_tokens": usage["input_tokens"] + int(result.get("input_tokens") or 0),
                    "output_tokens": usage["output_tokens"] + int(result.get("output_tokens") or 0),
                    "tokens": usage["tokens"] + int(result.get("tokens") or 0),
                    "est_cost_usd": result.get("est_cost_usd"),
                }
        else:
            agent = agents.build(agent_name)
            for turn in case.get("turns") or [case["input"]]:
                answers.append(str(agent(turn)))
            usage = models.usage_and_cost()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:500]
    finally:
        context.fault.set(None)
        if token is not None:
            from opentelemetry import context as otel_context

            otel_context.detach(token)
    rec = {
        "id": case["id"],
        "agent": case["agent"],
        "model": models.agent_model_name(),
        "provider": models.PROVIDER,
        "seconds": round(time.time() - t0, 1),
        "answer": answers[-1] if answers else "",
        "turn_answers": answers if len(answers) > 1 else None,
        **usage,
        "tool_calls": list(tools.CALLS),
        "tables_intact": bool(tables_intact),
        "error": error,
        "session_id": session_id,
        "arize_trace_id": telemetry.current_traceparent(),
        "braintrust_trace_id": telemetry.current_traceparent(),
    }
    telemetry.set_span_case_attributes(span, payload, rec)
    span_cm.__exit__(None, None, None)
    return rec


def run_cases(
    cases: list[dict],
    workers: int = 1,
    on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Run cases, optionally in parallel. Local stand-ins stay in-process."""
    workers = max(1, workers)
    if workers == 1 or len(cases) <= 1:
        recs = []
        for case in cases:
            rec = run_case(case)
            recs.append(rec)
            if on_result:
                on_result(rec)
        return recs
    recs: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_case, case) for case in cases]
        for fut in as_completed(futures):
            rec = fut.result()
            recs.append(rec)
            if on_result:
                on_result(rec)
    return recs
