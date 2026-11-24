"""AgentCore Runtime entrypoint for one loan specialist (selected by LOAN_AGENT_NAME)."""
from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator

from . import agents, context, models, telemetry, tools

try:
    from bedrock_agentcore import BedrockAgentCoreApp
except ImportError:  # pragma: no cover - unit tests without the SDK
    class BedrockAgentCoreApp:
        def entrypoint(self, func):
            self.handler = func
            return func

        def run(self):
            raise RuntimeError("bedrock-agentcore is not installed")


app = BedrockAgentCoreApp()


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    if isinstance(event.get("prompt"), str):
        return event
    body = event.get("payload") or event.get("input") or event.get("body")
    if isinstance(body, bytes | bytearray):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"prompt": body}
    return body if isinstance(body, dict) else {}


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    """Run the specialist named by LOAN_AGENT_NAME. Used by the runtime and by tests."""
    telemetry.setup_tracing()
    payload = _payload(event)
    prompt = payload.get("prompt") or ""
    name = payload.get("agent_name") or os.getenv("LOAN_AGENT_NAME") or "pool_screening"
    session = context.pad_session_id(payload.get("session_id"), payload.get("case_id") or "")
    token = telemetry.attach_traceparent(payload.get("traceparent"))
    tools.CALLS.clear()
    models.RUN_AGENTS.clear()
    context.fault.set(payload.get("fault"))
    context.session_id.set(session)
    context.case_id.set(str(payload.get("case_id") or ""))
    context.traceparent.set(str(payload.get("traceparent") or ""))
    before = ""
    try:
        before = tools.tables_fingerprint()
    except Exception:
        before = ""
    t0 = time.time()
    error = ""
    answer = ""
    span_cm = telemetry.tracer().start_as_current_span(f"loan.{name}")
    span = span_cm.__enter__()
    try:
        telemetry.set_span_case_attributes(span, {**payload, "session_id": session})
        if models.PROVIDER == "dryrun":
            answer = f"(dry run - no AI model was called for {payload.get('case_id') or name})"
        else:
            agent = agents._specialist(name)
            answer = str(agent(prompt))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        context.fault.set(None)
        if token is not None:
            from opentelemetry import context as otel_context

            otel_context.detach(token)
    after = before
    try:
        after = tools.tables_fingerprint()
    except Exception:
        after = before
    usage = models.usage_and_cost()
    result = {
        "answer": answer,
        "text": answer,
        "agent": name,
        "session_id": session,
        "tool_calls": list(tools.CALLS),
        "tables_intact": after == before,
        "error": error,
        "seconds": round(time.time() - t0, 1),
        **usage,
    }
    try:
        telemetry.set_span_case_attributes(span, {**payload, "session_id": session}, result)
    finally:
        span_cm.__exit__(None, None, None)
    return result


@app.entrypoint
async def handler(event: dict[str, Any], _context: Any | None = None) -> AsyncIterator[dict[str, Any]]:
    result = handle_event(event)
    text = result.get("answer") or ""
    if text:
        yield {"text": text}
    yield {"event": "metadata", **result}


if __name__ == "__main__":
    app.run()
