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
