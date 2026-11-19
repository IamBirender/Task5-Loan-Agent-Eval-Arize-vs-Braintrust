"""Per-request context for AgentCore specialist runtimes and the eval supervisor."""
from __future__ import annotations

import contextvars

session_id: contextvars.ContextVar[str] = contextvars.ContextVar("loan_session_id", default="")
traceparent: contextvars.ContextVar[str] = contextvars.ContextVar("loan_traceparent", default="")
case_id: contextvars.ContextVar[str] = contextvars.ContextVar("loan_case_id", default="")
fault: contextvars.ContextVar[str | None] = contextvars.ContextVar("loan_fault", default=None)
tables_fingerprint_before: contextvars.ContextVar[str] = contextvars.ContextVar(
    "loan_fp_before", default=""
)


def pad_session_id(raw: str | None, case_id_value: str = "") -> str:
    """AgentCore runtimeSessionId must be 33-256 characters."""
    value = (raw or "").strip() or f"loan-eval-{case_id_value or 'session'}"
    if len(value) < 33:
        value = value + ("x" * (33 - len(value)))
    return value[:256]
