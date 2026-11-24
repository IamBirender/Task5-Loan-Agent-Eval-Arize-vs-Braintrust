"""Generate platform evaluator source from scoring/checks.py so Arize and Braintrust cannot drift."""
from __future__ import annotations

from pathlib import Path

CHECKS = Path(__file__).resolve().parent / "checks.py"


def checks_source() -> str:
    return CHECKS.read_text(encoding="utf-8")


def arize_evaluator_source() -> str:
    return (
        checks_source()
        + """

def _run_from_output(output, dataset_row=None):
    import json
    attrs = output if isinstance(output, dict) else {}
    if "answer" not in attrs and hasattr(output, "attributes"):
        attrs = dict(getattr(output, "attributes") or {})
    from loan_agents.telemetry import run_from_span_attrs
    run = run_from_span_attrs(attrs) if "loan.case_id" in attrs or "output.value" in attrs else {
        "answer": attrs.get("answer") or "",
        "tool_calls": attrs.get("tool_calls") or [],
        "error": attrs.get("error") or "",
        "seconds": attrs.get("seconds") or 0,
        "tokens": attrs.get("tokens") or 0,
        "tables_intact": attrs.get("tables_intact", True),
    }
    case = dataset_row or attrs.get("case") or {}
    return case, run


def eval_tool_check(output, dataset_row=None, **_):
    case, run = _run_from_output(output, dataset_row)
    return tool_check(case, run.get("tool_calls") or [])


def eval_facts_check(output, dataset_row=None, **_):
    case, run = _run_from_output(output, dataset_row)
    return facts_check(case, run.get("answer") or "")


def eval_policy_check(output, dataset_row=None, **_):
    case, run = _run_from_output(output, dataset_row)
    return policy_check(case, run)


def eval_verdict(output, dataset_row=None, **_):
    case, run = _run_from_output(output, dataset_row)
    tool = tool_check(case, run.get("tool_calls") or [])
    facts = facts_check(case, run.get("answer") or "")
    policy = policy_check(case, run)
    judged = {"score": 1.0, "reason": "online judge placeholder"}
    return {"verdict": case_verdict(case, tool, facts, judged, policy)}
"""
    )


def braintrust_scorer_source() -> str:
    return arize_evaluator_source()


def braintrust_handler_source(entry: str) -> str:
    """Self-contained Python scorer for Braintrust hosted functions (must define handler)."""
    checks = checks_source().replace("from loan_agents import models\n", "def judge_complete(prompt):\n    return '{}'\n\n")
    return (
        checks
        + '''

def _json_maybe(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
        return parsed
    return value


def _pick(meta, *keys, default=""):
    for key in keys:
        if meta.get(key) not in (None, ""):
            return meta[key]
    return default


def _case_and_run(inp, output, expected, metadata):
    meta = dict(metadata or {})
    if isinstance(inp, dict):
        meta = {**inp, **meta}
    if isinstance(output, dict):
        meta = {**output, **meta}
        answer = str(output.get("output.value") or output.get("answer") or output.get("text") or "")
    else:
        answer = str(output or "")
    expected_tools = _json_maybe(_pick(meta, "expected_tools", "loan.expected_tools", default=[])) or []
    if isinstance(expected_tools, list) and expected_tools and isinstance(expected_tools[0], str):
        expected_tools = [{"name": t} for t in expected_tools]
    guidelines = _json_maybe(_pick(meta, "guidelines", "loan.guidelines", default=[])) or []
    forbidden = _json_maybe(_pick(meta, "forbidden", "loan.forbidden", default=[])) or []
    patterns = _json_maybe(_pick(meta, "forbidden_patterns", "loan.forbidden_patterns", default=[])) or []
    limits = _json_maybe(_pick(meta, "limits", "loan.limits", default={})) or {}
    gate = str(_pick(meta, "gate", "loan.gate", default="G1"))
    case = {
        "id": _pick(meta, "case_id", "loan.case_id"),
        "expected": _pick(meta, "expected", "loan.expected") or (expected or ""),
        "guidelines": guidelines if isinstance(guidelines, list) else [],
        "expected_tools": expected_tools if isinstance(expected_tools, list) else [],
        "forbidden": forbidden if isinstance(forbidden, list) else [],
        "forbidden_patterns": patterns if isinstance(patterns, list) else [],
        "method": _pick(meta, "method", "loan.method", default="Deterministic"),
        "gate": gate,
        "gate_code": gate.split()[0] if gate else "G1",
        "limits": limits if isinstance(limits, dict) else {},
        "input": str(_pick(meta, "input", "UserInput") or inp or ""),
    }
    tool_calls = _json_maybe(_pick(meta, "tool_calls", "loan.tool_calls", default=[])) or []
    run = {
        "answer": answer,
        "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
        "error": str(_pick(meta, "error", "loan.error")),
        "seconds": float(_pick(meta, "seconds", "loan.seconds", default=0) or 0),
        "tokens": int(_pick(meta, "tokens", "llm.token_count.total", default=0) or 0),
        "tables_intact": bool(meta.get("tables_intact", meta.get("loan.tables_intact", True))),
        "est_cost_usd": None,
    }
    return case, run
'''
        + f'''

def handler(input=None, output=None, expected=None, metadata=None, **_):
    case, run = _case_and_run(input, output, expected, metadata)
    if "{entry}" == "eval_tool_check":
        result = tool_check(case, run.get("tool_calls") or [])
    elif "{entry}" == "eval_facts_check":
        result = facts_check(case, run.get("answer") or "")
    elif "{entry}" == "eval_policy_check":
        result = policy_check(case, run)
    else:
        tool = tool_check(case, run.get("tool_calls") or [])
        facts = facts_check(case, run.get("answer") or "")
        policy = policy_check(case, run)
        judged = {{"score": 1.0, "reason": "hosted verdict uses code checks"}}
        result = {{"verdict": case_verdict(case, tool, facts, judged, policy)}}
    if result is None:
        return None
    if isinstance(result, dict) and "verdict" in result:
        score = 1.0 if result["verdict"] == "PASS" else 0.0
        return {{"name": "verdict", "score": score, "metadata": result}}
    return {{"name": "{entry}", "score": float(result.get("score") or 0), "metadata": result}}
'''
    )
