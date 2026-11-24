"""Dual OTLP export: Arize (OpenInference gRPC) and Braintrust. One TracerProvider."""
from __future__ import annotations

import json
import os
from typing import Any

from . import aws_config

_INSTALLED = False
PROJECT = "loan-agents"
EXPORT = {"arize": False, "braintrust": False, "arize_error": "", "braintrust_error": ""}


def _secret_values() -> dict[str, str]:
    arn = os.getenv("LOAN_OBSERVABILITY_SECRET_ARN", "").strip()
    values = {
        "ARIZE_API_KEY": os.getenv("ARIZE_API_KEY", ""),
        "ARIZE_SPACE_ID": os.getenv("ARIZE_SPACE_ID", ""),
        "BRAINTRUST_API_KEY": os.getenv("BRAINTRUST_API_KEY", ""),
    }
    if not arn:
        return values
    try:
        import boto3

        raw = boto3.client("secretsmanager", region_name=aws_config.region_name()).get_secret_value(
            SecretId=arn
        )
        payload = json.loads(raw.get("SecretString") or "{}")
        for key in values:
            if payload.get(key):
                values[key] = str(payload[key])
                os.environ.setdefault(key, values[key])
    except Exception:
        pass
    return values


def setup_tracing(force: bool = False) -> Any | None:
    """Install one TracerProvider with Arize + Braintrust processors. Idempotent."""
    global _INSTALLED
    os.environ["DISABLE_ADOT_OBSERVABILITY"] = "true"
    if _INSTALLED and not force:
        from opentelemetry import trace

        return trace.get_tracer_provider()
    keys = _secret_values()
    if not keys["ARIZE_API_KEY"] and not keys["BRAINTRUST_API_KEY"] and not force:
        return None
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": PROJECT}))
    if keys["ARIZE_API_KEY"] and keys["ARIZE_SPACE_ID"]:
        try:
            from arize.otel import register
            from openinference.instrumentation.strands_agents import (
                StrandsAgentsToOpenInferenceProcessor,
            )

            register(
                space_id=keys["ARIZE_SPACE_ID"],
                api_key=keys["ARIZE_API_KEY"],
                project_name=PROJECT,
                set_global_tracer_provider=False,
                tracer_provider=provider,
                span_processors=[StrandsAgentsToOpenInferenceProcessor()],
            )
            EXPORT["arize"] = True
        except Exception:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                exporter = OTLPSpanExporter(
                    endpoint="https://otlp.arize.com:443",
                    headers={
                        "authorization": f"Bearer {keys['ARIZE_API_KEY']}",
                        "space_id": keys["ARIZE_SPACE_ID"],
                        "arize-space-id": keys["ARIZE_SPACE_ID"],
                    },
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
                EXPORT["arize"] = True
            except Exception as exc:
                EXPORT["arize_error"] = str(exc)[:240]
    if keys["BRAINTRUST_API_KEY"]:
        try:
            from braintrust.otel import BraintrustSpanProcessor

            provider.add_span_processor(
                BraintrustSpanProcessor(parent=f"project_name:{PROJECT}")
            )
            EXPORT["braintrust"] = True
        except Exception as exc:
            EXPORT["braintrust_error"] = str(exc)[:240]
    trace.set_tracer_provider(provider)
    _INSTALLED = True
    return provider


def flush(timeout_millis: int = 30000) -> bool:
    """Push buffered OTEL spans to Arize / Braintrust. Call at the end of step 3."""
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        fn = getattr(provider, "force_flush", None)
        if not fn:
            return False
        return bool(fn(timeout_millis=timeout_millis))
    except Exception:
        return False


def current_traceparent() -> str:
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent") or ""


def attach_traceparent(traceparent: str | None):
    from opentelemetry import context
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    if not traceparent:
        return None
    ctx = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    return context.attach(ctx)


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


def tracer():
    try:
        from opentelemetry import trace

        return trace.get_tracer("loan_agents")
    except Exception:
        class _NoopTracer:
            def start_as_current_span(self, _name: str):
                return _NoopSpan()

        return _NoopTracer()


def set_span_case_attributes(span: Any, payload: dict[str, Any], result: dict[str, Any] | None = None) -> None:
    if span is None:
        return
    span.set_attribute("loan.case_id", str(payload.get("case_id") or ""))
    span.set_attribute("loan.gate", str(payload.get("gate") or ""))
    span.set_attribute("loan.method", str(payload.get("method") or ""))
    span.set_attribute("loan.session_id", str(payload.get("session_id") or ""))
    span.set_attribute("openinference.span.kind", "AGENT")
    if payload.get("expected"):
        span.set_attribute("loan.expected", str(payload["expected"])[:4000])
    if payload.get("guidelines"):
        span.set_attribute("loan.guidelines", json.dumps(payload["guidelines"], default=str)[:4000])
    if payload.get("expected_tools"):
        span.set_attribute("loan.expected_tools", json.dumps(payload["expected_tools"], default=str)[:2000])
    if payload.get("forbidden"):
        span.set_attribute("loan.forbidden", json.dumps(payload["forbidden"], default=str)[:2000])
    if payload.get("fault"):
        span.set_attribute("loan.fault", str(payload["fault"]))
    if result is None:
        return
    span.set_attribute("output.value", str(result.get("answer") or "")[:8000])
    span.set_attribute("loan.tool_calls", json.dumps(result.get("tool_calls") or [], default=str)[:8000])
    span.set_attribute("loan.tables_intact", bool(result.get("tables_intact", True)))
    span.set_attribute("loan.error", str(result.get("error") or ""))
    if result.get("tokens") is not None:
        span.set_attribute("llm.token_count.total", int(result["tokens"]))
    if result.get("input_tokens") is not None:
        span.set_attribute("llm.token_count.prompt", int(result["input_tokens"]))
    if result.get("output_tokens") is not None:
        span.set_attribute("llm.token_count.completion", int(result["output_tokens"]))
    if result.get("seconds") is not None:
        span.set_attribute("loan.seconds", float(result["seconds"]))


def run_from_span_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the scorer input from a trace's root-span attributes."""
    tool_raw = attrs.get("loan.tool_calls") or "[]"
    try:
        tool_calls = json.loads(tool_raw) if isinstance(tool_raw, str) else list(tool_raw)
    except json.JSONDecodeError:
        tool_calls = []
    tokens = attrs.get("llm.token_count.total") or attrs.get("loan.tokens") or 0
    input_tokens = attrs.get("llm.token_count.prompt") or 0
    output_tokens = attrs.get("llm.token_count.completion") or 0
    return {
        "id": attrs.get("loan.case_id") or "",
        "answer": attrs.get("output.value") or attrs.get("output") or "",
        "tool_calls": tool_calls,
        "error": attrs.get("loan.error") or "",
        "seconds": float(attrs.get("loan.seconds") or 0),
        "tokens": int(tokens or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "tables_intact": bool(attrs.get("loan.tables_intact", True)),
        "est_cost_usd": None,
    }
