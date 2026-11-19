"""Bedrock Knowledge Base Retrieve, with a normalized passage shape."""
from __future__ import annotations

from typing import Any

from . import aws_config


class KBRetrieveError(RuntimeError):
    """Raised when Knowledge Base retrieval fails."""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _extract_source(location: dict[str, Any]) -> str:
    if not isinstance(location, dict):
        return ""
    s3 = location.get("s3Location")
    if isinstance(s3, dict) and isinstance(s3.get("uri"), str):
        return s3["uri"]
    for key in (
        "webLocation", "confluenceLocation", "salesforceLocation",
        "sharePointLocation", "customDocumentLocation",
    ):
        nested = location.get(key)
        if isinstance(nested, dict):
            for field in ("url", "uri", "documentId", "id"):
                value = nested.get(field)
                if isinstance(value, str) and value:
                    return value
    return str(location.get("type") or "")


def _extract_page(metadata: dict[str, Any] | None) -> int | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("page", "pageNumber", "page_number", "x-amz-bedrock-kb-chunk-page-number"):
        page = _coerce_int(metadata.get(key))
        if page is not None:
            return page
    source = metadata.get("x-amz-bedrock-kb-source-uri") or metadata.get("source")
    if isinstance(source, str) and "#" in source:
        page = _coerce_int(source.rsplit("#", 1)[-1])
        if page is not None:
            return page
    return None


def normalize_passage(passage: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(passage, dict):
        return None
    content = passage.get("content") or {}
    text = content.get("text") if isinstance(content, dict) else None
    if not isinstance(text, str):
        text = str(passage.get("text") or "")
    location = passage.get("location") if isinstance(passage.get("location"), dict) else {}
    source = passage.get("source") or _extract_source(location)
    if not text and not source:
        return None
    metadata = passage.get("metadata") if isinstance(passage.get("metadata"), dict) else {}
    page = passage.get("page") if isinstance(passage.get("page"), int) else _extract_page(metadata)
    score = _coerce_float(passage.get("score"))
    if isinstance(source, str) and source.startswith("s3://"):
        source = source.rsplit("/", 1)[-1]
    return {"source": source or "kb", "page": page or 1, "text": text[:1200], "score": score}


def retrieve(
    query: str,
    top_k: int = 5,
    *,
    client: Any | None = None,
    kb_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise KBRetrieveError("query must be a non-empty string")
    cfg = aws_config.load_config()
    knowledge_base_id = kb_id or cfg.kb_id
    if not knowledge_base_id:
        raise KBRetrieveError("Knowledge Base id is not configured")
    if client is None:
        import boto3

        client = boto3.client("bedrock-agent-runtime", region_name=cfg.region)
    try:
        response = client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": int(top_k)},
            },
        )
    except Exception as exc:
        raise KBRetrieveError(f"Bedrock Retrieve failed: {exc}") from exc
    passages = []
    for item in response.get("retrievalResults") or []:
        normalised = normalize_passage(item)
        if normalised:
            passages.append(normalised)
    return {"query": query, "passages": passages}
