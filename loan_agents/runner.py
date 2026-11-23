"""Run one test case. Supervisor is Strands here; specialists are AgentCore apps."""
from __future__ import annotations

import time

from . import agents, context, models, telemetry, tools
from .aws_config import SPECIALISTS


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


def run_case(case: dict) -> dict:
    tools.CALLS.clear()
    models.RUN_AGENTS.clear()
    tools.FAULT = case.get("fault")
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
        tools.FAULT = None
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
