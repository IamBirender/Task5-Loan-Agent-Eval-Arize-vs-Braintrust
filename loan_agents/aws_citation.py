"""Citation check through the AgentCore Gateway (Cedar-guarded Lambda)."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from . import aws_config

GATEWAY_TOOL_NAME = "citation-check___citation_check"


class CitationCheckError(RuntimeError):
    """Raised when the Gateway citation-check tool cannot complete."""


def _gateway_url(cfg: aws_config.LoanConfig) -> str:
    if cfg.gateway_url:
        return cfg.gateway_url
    if not cfg.gateway_arn:
        raise CitationCheckError("Gateway ARN/URL is not configured")
    gateway_id = cfg.gateway_arn.rsplit("/", 1)[-1]
    return f"https://{gateway_id}.gateway.bedrock-agentcore.{cfg.region}.amazonaws.com/mcp"


def _auth_headers(url: str, body: bytes, region_name: str) -> dict[str, str]:
    import botocore.auth
    import botocore.session
    from botocore.awsrequest import AWSRequest

    credentials = botocore.session.get_session().get_credentials().get_frozen_credentials()
    parsed = urlparse(url)
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/json", "Host": parsed.hostname},
    )
    botocore.auth.SigV4Auth(credentials, "bedrock-agentcore", region_name).add_auth(request)
    return dict(request.headers)


def call_gateway(
    response_text: str,
    citations: list[dict[str, Any]],
    *,
    opener: Any | None = None,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    cfg = aws_config.load_config()
    url = _gateway_url(cfg)
    payload = {
        "jsonrpc": "2.0",
        "id": "citation-check",
        "method": "tools/call",
        "params": {
            "name": GATEWAY_TOOL_NAME,
            "arguments": {
                "response_text": response_text,
                "citations": json.dumps(citations, default=str),
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = _auth_headers(url, body, cfg.region)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise CitationCheckError(f"Gateway HTTP {exc.code}: {exc.read()[:400]}") from exc
    except Exception as exc:
        raise CitationCheckError(f"Gateway request failed: {exc}") from exc
    parsed = json.loads(raw)
    if "error" in parsed:
        err = parsed["error"]
        raise CitationCheckError(f"Gateway MCP error {err.get('code')}: {err.get('message')}")
    result = parsed.get("result") or {}
    content = result.get("content") or []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text") or ""
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return result if isinstance(result, dict) else {"raw": raw}
