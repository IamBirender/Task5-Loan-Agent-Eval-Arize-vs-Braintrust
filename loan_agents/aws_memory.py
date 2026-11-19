"""AgentCore Memory in the credit_events namespace."""
from __future__ import annotations

import json
from typing import Any

from . import aws_config

CREDIT_EVENTS_NAMESPACE = "credit_events"


class MemoryError(RuntimeError):
    """Raised when AgentCore Memory read or write fails."""


def _client(region_name: str | None = None):
    import boto3

    return boto3.client(
        "bedrock-agentcore",
        region_name=region_name or aws_config.region_name(),
    )


def _record_to_dict(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"content": str(record)}
    content = record.get("content")
    if isinstance(content, dict):
        text = content.get("text") or content.get("value") or json.dumps(content, default=str)
    else:
        text = content if isinstance(content, str) else json.dumps(content, default=str)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return {
        "id": record.get("memoryRecordId") or record.get("id") or "",
        "namespace": record.get("namespace") or "",
        "content": text,
        "metadata": metadata,
        "score": record.get("score") if isinstance(record.get("score"), int | float) else None,
    }


def retrieve_memory(
    namespace: str = CREDIT_EVENTS_NAMESPACE,
    query: str | None = None,
    *,
    limit: int = 20,
    client: Any | None = None,
    memory_id: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(namespace, str) or not namespace.strip():
        raise MemoryError("namespace must be a non-empty string")
    cfg = aws_config.load_config()
    resolved = memory_id or cfg.memory_id
    if not resolved:
        raise MemoryError("AgentCore Memory id is not configured")
    agentcore = client or _client(cfg.region)
    request: dict[str, Any] = {
        "memoryId": resolved,
        "namespace": namespace.strip(),
        "maxResults": int(limit),
    }
    if query:
        request["searchCriteria"] = {"searchQuery": query}
    try:
        response = agentcore.retrieve_memory_records(**request)
    except Exception as exc:
        raise MemoryError(f"RetrieveMemoryRecords failed: {exc}") from exc
    records = (
        (response or {}).get("memoryRecordSummaries")
        or (response or {}).get("memoryRecords")
        or []
    )
    normalised = [_record_to_dict(r) for r in records]
    return [r for r in normalised if not r["namespace"] or r["namespace"] == namespace.strip()]


def create_memory_record(
    content: str,
    namespace: str = CREDIT_EVENTS_NAMESPACE,
    metadata: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise MemoryError("content must be a non-empty string")
    cfg = aws_config.load_config()
    resolved = memory_id or cfg.memory_id
    if not resolved:
        raise MemoryError("AgentCore Memory id is not configured")
    agentcore = client or _client(cfg.region)
    try:
        response = agentcore.create_memory_record(
            memoryId=resolved,
            namespace=namespace,
            content={"text": content},
            metadata=metadata or {},
        )
    except TypeError:
        response = agentcore.create_event(
            memoryId=resolved,
            actorId="loan-seed",
            sessionId="credit-events-seed",
            payload=[{"blob": json.dumps({"namespace": namespace, "content": content, "metadata": metadata or {}})}],
        )
    except Exception as exc:
        raise MemoryError(f"CreateMemoryRecord failed: {exc}") from exc
    return {"id": (response or {}).get("memoryRecordId") or "", "namespace": namespace}
