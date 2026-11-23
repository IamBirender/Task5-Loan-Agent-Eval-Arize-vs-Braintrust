"""Which AI model the agents and the judge use.

  MODEL_PROVIDER=agentcore  documented path: four AgentCore specialists + Strands supervisor
  MODEL_PROVIDER=local      offline DuckDB debug; does not feed the comparison
  MODEL_PROVIDER=dryrun     wiring test: no model is called
  MODEL_PROVIDER=bedrock / groq / anthropic / ollama  legacy local specialist objects (debug only)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent.parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parent / ".env")

PROVIDER = os.getenv("MODEL_PROVIDER", "agentcore").lower()
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "bedrock").lower()

OPENAI_STYLE = {
    "groq": ("https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY", ""), "openai/gpt-oss-120b", "qwen/qwen3.8-27b"),
    "ollama": ("https://ollama.com/v1", os.getenv("OLLAMA_API_KEY") or os.getenv("Ollam_api_key", ""), "gpt-oss:120b", "nemotron-3-super"),
}
BEDROCK_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_DEFAULTS = (os.getenv("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6"), "us.amazon.nova-pro-v1:0")

AGENT_MODEL = os.getenv("AGENT_MODEL") or {
    "anthropic": os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
    "bedrock": BEDROCK_DEFAULTS[0],
    "agentcore": BEDROCK_DEFAULTS[0],
    "dryrun": "none (dry run)",
}.get(PROVIDER, OPENAI_STYLE.get(PROVIDER, ("", "", "unknown", ""))[2])
AGENT_VERSION = os.getenv("AGENT_VERSION", "v3")
JUDGE_MODEL = os.getenv("JUDGE_MODEL") or {"bedrock": BEDROCK_DEFAULTS[1], "anthropic": "claude-sonnet-5-5"}.get(
    JUDGE_PROVIDER
) or OPENAI_STYLE.get(JUDGE_PROVIDER, ("", "", "", "qwen/qwen3.8-27b"))[3]

RUN_AGENTS: list = []
PRICES = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "gpt-oss-120b": (0.15, 0.6),
}


def track(agent):
    RUN_AGENTS.append(agent)
    return agent


def usage_and_cost() -> dict:
    tin = sum(a.event_loop_metrics.accumulated_usage.get("inputTokens", 0) for a in RUN_AGENTS)
    tout = sum(a.event_loop_metrics.accumulated_usage.get("outputTokens", 0) for a in RUN_AGENTS)
    price = next((v for k, v in PRICES.items() if k in AGENT_MODEL), None)
    cost = round((tin * price[0] + tout * price[1]) / 1e6, 4) if price else None
    return {"input_tokens": tin, "output_tokens": tout, "tokens": tin + tout, "est_cost_usd": cost}


def agent_model_name() -> str:
    return AGENT_MODEL


def _guardrail_kwargs() -> dict:
    gid = os.getenv("LOAN_GUARDRAIL_ID", "").strip()
    version = os.getenv("LOAN_GUARDRAIL_VERSION", "DRAFT")
    if not gid:
        try:
            from .aws_config import load_config

            gid = load_config().guardrail_id
            version = load_config().guardrail_version or version
        except Exception:
            gid = ""
    if not gid:
        return {}
    return {"guardrail_id": gid, "guardrail_version": version}


def agent_model():
    if PROVIDER == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
            model_id=AGENT_MODEL,
            max_tokens=16000,
        )
    if PROVIDER in ("bedrock", "agentcore"):
        from strands.models import BedrockModel

        kwargs = {"model_id": AGENT_MODEL, "region_name": BEDROCK_REGION, "max_tokens": 16000}
        kwargs.update(_guardrail_kwargs())
        try:
            return BedrockModel(**kwargs)
        except TypeError:
            kwargs.pop("guardrail_id", None)
            kwargs.pop("guardrail_version", None)
            return BedrockModel(**kwargs)
    from strands.models.openai import OpenAIModel

    base_url, key, _, _ = OPENAI_STYLE[PROVIDER]
    return OpenAIModel(client_args={"base_url": base_url, "api_key": key}, model_id=AGENT_MODEL, params={"temperature": 0})


def judge_complete(prompt: str) -> str:
    if JUDGE_PROVIDER == "bedrock":
        import boto3

        reply = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION).converse(
            modelId=JUDGE_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 2000, "temperature": 0},
        )
        return "".join(b.get("text", "") for b in reply["output"]["message"]["content"])
    if JUDGE_PROVIDER == "anthropic":
        import anthropic

        reply = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]).messages.create(
            model=JUDGE_MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}]
        )
        return "".join(b.text for b in reply.content if b.type == "text")
    import time

    from openai import OpenAI, RateLimitError

    base_url, key, _, _ = OPENAI_STYLE[JUDGE_PROVIDER]
    for wait in (15, 30, 60, 60, 0):
        try:
            reply = OpenAI(base_url=base_url, api_key=key, max_retries=0).chat.completions.create(
                model=JUDGE_MODEL, temperature=0, messages=[{"role": "user", "content": prompt}]
            )
            return reply.choices[0].message.content or ""
        except RateLimitError:
            if not wait:
                raise
            time.sleep(wait)
    return ""
