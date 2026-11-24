"""Per-request context for AgentCore specialist runtimes and the eval supervisor."""
from __future__ import annotations

import contextvars
from collections.abc import Iterator
from typing import Any


class CtxList:
    """Thread-safe list via contextvars so parallel cases do not mix tool calls or usage."""

    def __init__(self, name: str) -> None:
        self._var: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
            name, default=None
        )

    def _items(self) -> list[Any]:
        items = self._var.get()
        if items is None:
            items = []
            self._var.set(items)
        return items

    def clear(self) -> None:
        self._var.set([])

    def append(self, item: Any) -> None:
        self._items().append(item)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._items())

    def __len__(self) -> int:
        return len(self._items())

    def __getitem__(self, idx: int) -> Any:
        return self._items()[idx]

    def __bool__(self) -> bool:
        return bool(self._items())

    def __repr__(self) -> str:
        return repr(self._items())


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
