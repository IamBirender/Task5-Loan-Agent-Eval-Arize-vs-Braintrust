"""Preflight for EC2 / eval box: region, identity, Bedrock models, outbound HTTPS, SSM runtimes."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loan_agents.aws_config import SPECIALISTS  # noqa: E402

REQUIRED_MODELS = (
    "us.anthropic.claude-sonnet-4-6",
    "us.amazon.nova-pro-v1:0",
    "amazon.titan-embed-text-v2:0",
)
SUPPORTED_REGIONS = ("us-east-1", "us-west-2", "ap-southeast-2", "eu-central-1")
OUTBOUND = (
    "https://otlp.arize.com",
    "https://api.braintrust.dev",
)


class ReadyError(RuntimeError):
    pass


def _region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def check_region(region: str | None = None) -> str:
    value = region or _region()
    if value not in SUPPORTED_REGIONS:
        raise ReadyError(f"region {value} is not in {SUPPORTED_REGIONS}")
    return value


def check_identity(sts_client: Any | None = None) -> dict[str, str]:
    import boto3

    client = sts_client or boto3.client("sts", region_name=_region())
    ident = client.get_caller_identity()
    return {"account": ident.get("Account", ""), "arn": ident.get("Arn", "")}


def check_bedrock_models(bedrock_client: Any | None = None) -> list[str]:
    import boto3

    client = bedrock_client or boto3.client("bedrock", region_name=_region())
    granted: list[str] = []
    try:
        ids: list[str] = []
        resp = client.list_foundation_models()
        ids.extend(m.get("modelId") or "" for m in resp.get("modelSummaries") or [])
        list_profiles = getattr(client, "list_inference_profiles", None)
        if callable(list_profiles):
            try:
                profiles = list_profiles()
                ids.extend(
                    p.get("inferenceProfileId") or ""
                    for p in (profiles.get("inferenceProfileSummaries") or [])
                )
            except Exception:
                pass
        for model in REQUIRED_MODELS:
            if any(model == i or model in i or i.endswith(model) for i in ids if i):
                granted.append(model)
    except ReadyError:
        raise
    except Exception as exc:
        raise ReadyError(f"Bedrock ListFoundationModels failed: {exc}") from exc
    missing = [m for m in REQUIRED_MODELS if m not in granted]
    if missing:
        raise ReadyError(f"Bedrock model access not granted for: {', '.join(missing)}")
    return granted


def check_outbound(opener=None) -> dict[str, bool]:
    open_fn = opener or urlopen
    out: dict[str, bool] = {}
    for url in OUTBOUND:
        try:
            req = Request(url, method="HEAD")
            open_fn(req, timeout=10)
            out[url] = True
        except Exception:
            try:
                req = Request(url, method="GET")
                open_fn(req, timeout=10)
                out[url] = True
            except Exception as exc:
                raise ReadyError(f"outbound HTTPS failed for {url}: {exc}") from exc
    return out


def check_runtime_arns(ssm_client: Any | None = None) -> dict[str, str]:
    import boto3

    client = ssm_client or boto3.client("ssm", region_name=_region())
    found: dict[str, str] = {}
    missing: list[str] = []
    for name in SPECIALISTS:
        param = f"/loan/runtime/{name}/arn"
        try:
            value = client.get_parameter(Name=param)["Parameter"]["Value"]
            if value:
                found[name] = value
            else:
                missing.append(param)
        except Exception:
            missing.append(param)
    extras = {}
    for param in ("/loan/kb/id", "/loan/memory/id", "/loan/guardrail/id"):
        try:
            extras[param] = client.get_parameter(Name=param)["Parameter"]["Value"]
        except Exception:
            extras[param] = ""
    if missing:
        raise ReadyError("runtime ARNs missing in SSM: " + ", ".join(missing))
    found["_kb"] = extras.get("/loan/kb/id", "")
    found["_memory"] = extras.get("/loan/memory/id", "")
    found["_guardrail"] = extras.get("/loan/guardrail/id", "")
    return found


def main() -> int:
    report: dict[str, Any] = {}
    try:
        report["region"] = check_region()
        report["identity"] = check_identity()
        report["models"] = check_bedrock_models()
        report["outbound"] = check_outbound()
        try:
            report["runtimes"] = check_runtime_arns()
        except ReadyError as exc:
            report["runtimes"] = str(exc)
            print(json.dumps(report, indent=2))
            print("Pre-deploy checks passed. Deploy the stack, seed, then rerun this script.")
            return 0
    except ReadyError as exc:
        print(f"NOT READY: {exc}")
        return 1
    print(json.dumps(report, indent=2))
    print("READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
