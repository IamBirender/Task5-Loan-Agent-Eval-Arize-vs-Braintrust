"""Resolve deployed loan-eval identifiers from env vars, then SSM."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

SPECIALISTS = (
    "pool_screening",
    "credit_performance",
    "cohort_comparison",
    "compliance_validation",
)

PARAM_MEMORY_ID = "/loan/memory/id"
PARAM_KB_ID = "/loan/kb/id"
PARAM_DOCS_BUCKET = "/loan/docs/bucket"
PARAM_AURORA_CLUSTER_ARN = "/loan/aurora/cluster_arn"
PARAM_AURORA_SECRET_ARN = "/loan/aurora/secret_arn"
PARAM_GATEWAY_ARN = "/loan/gateway/arn"
PARAM_EVALUATOR_ARN = "/loan/evaluator/arn"
PARAM_GUARDRAIL_ID = "/loan/guardrail/id"


class ConfigError(RuntimeError):
    """Raised when a required identifier cannot be resolved."""


@dataclass
class LoanConfig:
    runtime_arns: dict[str, str] = field(default_factory=dict)
    memory_id: str = ""
    kb_id: str = ""
    docs_bucket: str = ""
    aurora_cluster_arn: str = ""
    aurora_secret_arn: str = ""
    gateway_arn: str = ""
    gateway_url: str = ""
    evaluator_arn: str = ""
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"
    aurora_database: str = "loan"
    region: str = ""


def region_name() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def _ssm_client(region: str | None = None):
    import boto3

    return boto3.client("ssm", region_name=region or region_name())


def get_parameter(name: str, *, ssm_client: Any | None = None) -> str:
    client = ssm_client or _ssm_client()
    try:
        response = client.get_parameter(Name=name, WithDecryption=True)
    except Exception as exc:
        raise ConfigError(f"SSM parameter {name} is missing: {exc}") from exc
    value = ((response.get("Parameter") or {}).get("Value") or "").strip()
    if not value:
        raise ConfigError(f"SSM parameter {name} is empty")
    return value


def _optional_param(name: str, env_key: str, ssm_client: Any | None = None) -> str:
    env = os.getenv(env_key, "").strip()
    if env:
        return env
    try:
        return get_parameter(name, ssm_client=ssm_client)
    except ConfigError:
        return ""


@lru_cache(maxsize=1)
def load_config(ssm_client: Any | None = None) -> LoanConfig:
    client = ssm_client
    runtimes: dict[str, str] = {}
    for name in SPECIALISTS:
        env_key = f"LOAN_RUNTIME_{name.upper()}_ARN"
        runtimes[name] = _optional_param(f"/loan/runtime/{name}/arn", env_key, client)
    if not runtimes.get("pool_screening"):
        runtimes["pool_screening"] = _optional_param(
            "/loan/runtime/arn", "LOAN_RUNTIME_ARN", client
        )
    return LoanConfig(
        runtime_arns=runtimes,
        memory_id=_optional_param(PARAM_MEMORY_ID, "LOAN_MEMORY_ID", client),
        kb_id=_optional_param(PARAM_KB_ID, "LOAN_KB_ID", client),
        docs_bucket=_optional_param(PARAM_DOCS_BUCKET, "LOAN_DOCS_BUCKET", client),
        aurora_cluster_arn=_optional_param(
            PARAM_AURORA_CLUSTER_ARN, "LOAN_AURORA_CLUSTER_ARN", client
        ),
        aurora_secret_arn=_optional_param(
            PARAM_AURORA_SECRET_ARN, "LOAN_AURORA_SECRET_ARN", client
        ),
        gateway_arn=_optional_param(PARAM_GATEWAY_ARN, "LOAN_GATEWAY_ARN", client),
        gateway_url=os.getenv("LOAN_GATEWAY_URL", "").strip(),
        evaluator_arn=_optional_param(PARAM_EVALUATOR_ARN, "LOAN_EVALUATOR_ARN", client),
        guardrail_id=os.getenv("LOAN_GUARDRAIL_ID", "").strip()
        or _optional_param(PARAM_GUARDRAIL_ID, "LOAN_GUARDRAIL_ID", client),
        guardrail_version=os.getenv("LOAN_GUARDRAIL_VERSION", "DRAFT"),
        aurora_database=os.getenv("LOAN_AURORA_DATABASE", "loan"),
        region=region_name(),
    )


def reset_config_cache() -> None:
    load_config.cache_clear()
