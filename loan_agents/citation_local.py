"""Local citation-check used only by MODEL_PROVIDER=local. Canonical path is the Gateway Lambda."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HANDLER_DIR = Path(__file__).resolve().parent.parent / "lambda" / "citation_check"
if str(_HANDLER_DIR) not in sys.path:
    sys.path.insert(0, str(_HANDLER_DIR))

from handler import handler as _lambda_handler  # noqa: E402


def check_citations(response_text: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    return _lambda_handler({"response_text": response_text, "citations": citations}, None)
