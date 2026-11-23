"""Invoke a specialist AgentCore agent from the eval process.

The supervisor is a Strands agent in this process. Specialists stay AgentCore
apps (``loan_agents.runtime`` / BedrockAgentCoreApp):

- ``LOAN_AGENTCORE_INVOKE=local`` (default on EC2): run that AgentCore handler
  in this process. No Runtime ARN, ECR, or zip deploy.
- ``LOAN_AGENTCORE_INVOKE=runtime``: ``InvokeAgentRuntime`` against deployed
  AgentCore Runtimes.
"""
from __future__ import annotations

import json
import os
from typing import Any

from . import aws_config, context, telemetry
from .aws_config import SPECIALISTS


class ClientError(RuntimeError):
    """Raised when a specialist AgentCore invoke cannot complete."""


def invoke_mode(runtime_arn: str | None = None) -> str:
    """Return ``local`` or ``runtime``. Explicit env wins; otherwise ARNs imply runtime."""
    explicit = os.getenv("LOAN_AGENTCORE_INVOKE", "").strip().lower()
    if explicit in {"local", "ec2", "process"}:
        return "local"
    if explicit in {"runtime", "aws", "agentcore"}:
        return "runtime"
    if runtime_arn:
        return "runtime"
    return "local"


def _agentcore_client(region_name: str | None = None):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "bedrock-agentcore",
        region_name=region_name or aws_config.region_name(),
        config=Config(read_timeout=300),
    )


def _read_body(body: Any) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes | bytearray):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    read = getattr(body, "read", None)
    if callable(read):
        data = read()
        return data if isinstance(data, bytes) else str(data or "").encode("utf-8")
    return b""


def _parse_payload(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace").strip()
    if text.startswith("data:") or "\ndata:" in text:
        chunks: list[str] = []
        meta: dict[str, Any] = {}
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            piece = line[5:].strip()
            if not piece or piece == "[DONE]":
                continue
            try:
                parsed = json.loads(piece)
            except json.JSONDecodeError:
                chunks.append(piece)
                continue
            if isinstance(parsed, dict):
                if parsed.get("event") == "metadata":
                    meta = parsed
                elif parsed.get("text"):
                    chunks.append(parsed["text"])
                elif parsed.get("data"):
                    chunks.append(str(parsed["data"]))
                elif parsed.get("answer"):
                    chunks.append(parsed["answer"])
                    meta = {**meta, **parsed}
        out = {"answer": "".join(chunks), **meta}
        if chunks and not out.get("answer"):
            out["answer"] = "".join(chunks)
        return out
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"answer": text, "text": text}
    if isinstance(parsed, dict):
        if "answer" not in parsed and parsed.get("text"):
            parsed["answer"] = parsed["text"]
        return parsed
    return {"answer": str(parsed)}


def invoke_specialist(
    name: str,
    prompt: str,
    session_id: str,
    *,
    payload: dict[str, Any] | None = None,
    traceparent: str | None = None,
    agentcore_client: Any | None = None,
    runtime_arn: str | None = None,
) -> dict[str, Any]:
    if name not in SPECIALISTS:
        raise ClientError(f"Unknown specialist {name!r}")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ClientError("prompt must be a non-empty string")
    session = context.pad_session_id(session_id, payload.get("case_id") if payload else "")
    body = {
        "prompt": prompt,
        "session_id": session,
        "agent_name": name,
        "traceparent": traceparent or telemetry.current_traceparent(),
        **(payload or {}),
    }
    cfg = aws_config.load_config()
    arn = runtime_arn or cfg.runtime_arns.get(name)
    mode = invoke_mode(arn)
    if mode == "local":
        return _invoke_local(name, session, body)
    if not arn:
        raise ClientError(
            f"Runtime ARN for {name} is not configured. Set LOAN_AGENTCORE_INVOKE=local "
            "to run the AgentCore specialist on this EC2, or deploy LoanAgentStack."
        )
    return _invoke_runtime(name, session, body, arn, cfg.region, agentcore_client)


def _invoke_local(name: str, session: str, body: dict[str, Any]) -> dict[str, Any]:
    # Imported lazily: runtime -> agents -> client.
    from . import runtime

    previous = os.environ.get("LOAN_AGENT_NAME")
    os.environ["LOAN_AGENT_NAME"] = name
    try:
        parsed = runtime.handle_event(body)
    except Exception as exc:
        raise ClientError(f"AgentCore specialist {name} failed on this host: {exc}") from exc
    finally:
        if previous is None:
            os.environ.pop("LOAN_AGENT_NAME", None)
        else:
            os.environ["LOAN_AGENT_NAME"] = previous
    if not isinstance(parsed, dict):
        parsed = {"answer": str(parsed)}
    parsed.setdefault("session_id", session)
    parsed.setdefault("agent", name)
    parsed.setdefault("trace_id", parsed.get("trace_id") or "")
    parsed.setdefault("answer", parsed.get("text") or "")
    parsed.setdefault("tool_calls", parsed.get("tool_calls") or [])
    return parsed


def _invoke_runtime(
    name: str,
    session: str,
    body: dict[str, Any],
    arn: str,
    region: str,
    agentcore_client: Any | None,
) -> dict[str, Any]:
    client = agentcore_client or _agentcore_client(region)
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session,
            payload=json.dumps(body).encode("utf-8"),
        )
    except Exception as exc:
        raise ClientError(f"InvokeAgentRuntime failed for {name}: {exc}") from exc
    parsed = _parse_payload(_read_body(response.get("response") or response.get("payload")))
    parsed.setdefault("session_id", session)
    parsed.setdefault("agent", name)
    parsed.setdefault("trace_id", response.get("traceId") or parsed.get("trace_id") or "")
    parsed.setdefault("answer", parsed.get("text") or "")
    parsed.setdefault("tool_calls", parsed.get("tool_calls") or [])
    return parsed
