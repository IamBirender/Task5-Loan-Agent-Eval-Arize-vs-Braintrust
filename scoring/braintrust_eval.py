"""Upload the test cases and one Braintrust experiment from the step-3 invoke log.

OTLP traces from step 3 land in project Logs. Datasets and Experiments in the UI
come from this Eval() path (same as the original 13 Nov run).
"""
from __future__ import annotations

import time
from typing import Any

import braintrust
from braintrust import Score

from loan_agents import models
from scoring import runs

PROJECT = "loan-agents"


def dataset_name(n: int) -> str:
    return "loan-agent-test-cases-v1" if n == 60 else f"loan-agent-test-cases-{n}"


def publish(
    all_cases: dict[str, dict],
    saved: dict[str, dict],
    *,
    bt: Any | None = None,
    experiment_name: str | None = None,
    max_concurrency: int = 1,
) -> dict[str, Any]:
    sdk = bt or braintrust
    name = dataset_name(len(all_cases))
    dataset = sdk.init_dataset(project=PROJECT, name=name)
    for case in all_cases.values():
        dataset.insert(
            id=case["id"],
            input={"case_id": case["id"], "question": case["input"]},
            expected=case["expected"],
            metadata={
                "quality_gate": case["gate"],
                "agent": case["agent"],
                "method": case["method"],
                "guidelines": case["guidelines"],
                "expected_tools": case["expected_tools"],
            },
        )
    dataset.flush()

    grades: dict[str, dict] = {}

    def cached(inp: dict) -> dict:
        cid = inp["case_id"]
        if cid not in grades:
            grades[cid] = runs.grade(all_cases[cid], saved[cid])
        return grades[cid]

    def task(inp, hooks=None):
        rec = saved.get(inp["case_id"], {"answer": "", "tool_calls": [], "error": "not run in step 3"})
        if hooks is not None and rec.get("tokens") is not None:
            try:
                hooks.span.log(
                    metrics={
                        "prompt_tokens": rec.get("input_tokens"),
                        "completion_tokens": rec.get("output_tokens"),
                        "tokens": rec["tokens"],
                        "agent_seconds": rec.get("seconds"),
                    },
                    metadata={"est_cost_usd": rec.get("est_cost_usd"), "model": rec.get("model")},
                )
            except Exception:
                pass
        return {
            "answer": rec.get("answer"),
            "tools_used": [c["tool"] for c in rec.get("tool_calls") or []],
            "error": rec.get("error"),
            "seconds": rec.get("seconds"),
            "tokens": rec.get("tokens"),
            "est_cost_usd": rec.get("est_cost_usd"),
        }

    def as_score(score_name, check):
        if check is None:
            return None
        return Score(name=score_name, score=check["score"], metadata={k: v for k, v in check.items() if k != "score"})

    def tool_check(input, output, expected, **_):
        return as_score("tool_check", cached(input)["tool_check"])

    def facts_check(input, output, expected, **_):
        return as_score("facts_check", cached(input)["facts_check"])

    def ai_judge(input, output, expected, **_):
        judged = cached(input)["ai_judge"]
        return Score(name="ai_judge", score=judged["score"], metadata={"reason": judged.get("reason")})

    def policy_check(input, output, expected, **_):
        return as_score("policy_check", cached(input).get("policy_check"))

    def verdict(input, output, expected, **_):
        value = cached(input)["verdict"]
        return None if value == "REVIEW" else Score(name="verdict", score=1.0 if value == "PASS" else 0.0, metadata={"verdict": value})

    exp_name = experiment_name or (
        f"{models.AGENT_VERSION}-{models.PROVIDER}-{models.agent_model_name()}-{time.strftime('%Y%m%d-%H%M')}"
    )
    t0 = time.time()
    result = sdk.Eval(
        PROJECT,
        data=[row for row in dataset if row["input"]["case_id"] in saved],
        task=task,
        scores=[tool_check, facts_check, policy_check, ai_judge, verdict],
        max_concurrency=max_concurrency,
        experiment_name=exp_name,
        metadata={"agent_model": models.agent_model_name(), "judge_model": models.JUDGE_MODEL},
    )
    summary = getattr(result, "summary", None)
    return {
        "dataset": name,
        "experiment_name": exp_name,
        "experiment_url": getattr(summary, "experiment_url", None),
        "grades": grades,
        "seconds": round(time.time() - t0, 1),
    }
