"""Read scorer inputs from Arize / Braintrust traces and register online evaluators."""
from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from loan_agents.telemetry import run_from_span_attrs

from . import checks, evaluator_source, runs

PROJECT = "loan-agents"


def _http_json(url: str, headers: dict[str, str], payload: dict | None = None, timeout: int = 30) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST" if body else "GET")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def register_arize_evaluators(*, space_id: str | None = None, api_key: str | None = None, opener: Callable | None = None) -> dict[str, Any]:
    space = space_id or os.getenv("ARIZE_SPACE_ID", "")
    key = api_key or os.getenv("ARIZE_API_KEY", "")
    source = evaluator_source.arize_evaluator_source()
    if not space or not key:
        return {"registered": False, "reason": "missing Arize credentials", "source_chars": len(source)}
    payload = {
        "space_id": space,
        "project_name": PROJECT,
        "evaluators": [
            {"name": "tool_check", "type": "code", "code": source, "entry": "eval_tool_check", "scope": "trace"},
            {"name": "facts_check", "type": "code", "code": source, "entry": "eval_facts_check", "scope": "trace"},
            {"name": "policy_check", "type": "code", "code": source, "entry": "eval_policy_check", "scope": "trace"},
            {"name": "ai_judge", "type": "llm", "prompt": checks.JUDGE_PROMPT, "scope": "trace"},
            {"name": "verdict", "type": "code", "code": source, "entry": "eval_verdict", "scope": "trace"},
        ],
    }
    try:
        fetch = opener or _http_json
        result = fetch(
            "https://api.arize.com/v1/evaluators",
            {"x-api-key": key, "space_id": space},
            payload,
        )
        return {"registered": True, "result": result, "source_chars": len(source)}
    except Exception as exc:
        return {"registered": False, "reason": str(exc)[:400], "source_chars": len(source), "payload_names": [e["name"] for e in payload["evaluators"]]}


def register_braintrust_evaluators(*, api_key: str | None = None, opener: Callable | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("BRAINTRUST_API_KEY", "")
    source = evaluator_source.braintrust_scorer_source()
    if not key:
        return {"registered": False, "reason": "missing Braintrust credentials", "source_chars": len(source)}
    payload = {
        "project_name": PROJECT,
        "online": True,
        "idle_timeout": 120,
        "scores": [
            {"name": "tool_check", "scope": "trace", "code": source, "entry": "eval_tool_check"},
            {"name": "facts_check", "scope": "trace", "code": source, "entry": "eval_facts_check"},
            {"name": "policy_check", "scope": "trace", "code": source, "entry": "eval_policy_check"},
            {"name": "ai_judge", "scope": "trace", "type": "llm", "prompt": checks.JUDGE_PROMPT},
            {"name": "verdict", "scope": "trace", "code": source, "entry": "eval_verdict"},
        ],
    }
    try:
        fetch = opener or _http_json
        result = fetch(
            "https://api.braintrust.dev/v1/evaluators",
            {"Authorization": f"Bearer {key}"},
            payload,
        )
        return {"registered": True, "result": result, "source_chars": len(source)}
    except Exception as exc:
        return {"registered": False, "reason": str(exc)[:400], "source_chars": len(source), "payload_names": [s["name"] for s in payload["scores"]]}


def spans_to_run(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not spans:
        return None
    root = max(spans, key=lambda s: len((s.get("attributes") or {})))
    attrs = root.get("attributes") or root
    if not attrs.get("output.value") and not attrs.get("loan.case_id"):
        for span in spans:
            candidate = span.get("attributes") or span
            if candidate.get("output.value") or candidate.get("loan.tool_calls"):
                attrs = candidate
                break
    return run_from_span_attrs(attrs)


def fetch_arize_spans(case_id: str, session_id: str = "", *, opener: Callable | None = None) -> list[dict[str, Any]]:
    space = os.getenv("ARIZE_SPACE_ID", "")
    key = os.getenv("ARIZE_API_KEY", "")
    if not space or not key:
        return []
    payload = {
        "space_id": space,
        "project_name": PROJECT,
        "filter": {"case_id": case_id, "session_id": session_id},
    }
    try:
        fetch = opener or _http_json
        result = fetch(
            "https://api.arize.com/v1/spans/search",
            {"x-api-key": key, "space_id": space},
            payload,
        )
    except (URLError, Exception):
        return []
    if isinstance(result, list):
        return result
    return result.get("spans") or result.get("data") or []


def fetch_braintrust_spans(case_id: str, session_id: str = "", *, opener: Callable | None = None) -> list[dict[str, Any]]:
    key = os.getenv("BRAINTRUST_API_KEY", "")
    if not key:
        return []
    payload = {
        "query": (
            f"select * from project_logs('{PROJECT}') "
            f"where metadata.case_id = '{case_id}' or metadata.session_id = '{session_id}' "
            "limit 50"
        )
    }
    try:
        fetch = opener or _http_json
        result = fetch(
            "https://api.braintrust.dev/btql",
            {"Authorization": f"Bearer {key}"},
            payload,
        )
    except (URLError, Exception):
        return []
    if isinstance(result, list):
        return result
    return result.get("data") or result.get("spans") or []


def grade_from_spans(case: dict, spans: list[dict[str, Any]]) -> dict | None:
    run = spans_to_run(spans)
    if run is None:
        return None
    run["id"] = case["id"]
    return runs.grade(case, run)


NOT_RUN = {
    "tool_check": None,
    "facts_check": None,
    "policy_check": None,
    "ai_judge": {"score": None, "reason": "trace not found"},
    "verdict": "NOT RUN",
}
