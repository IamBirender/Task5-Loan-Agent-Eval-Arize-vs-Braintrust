"""Upload test cases as 50 Braintrust datasets and 50 experiments (T1-T50, T51-T100, ...).

Each 50-case slice is dealt across G1–G22 so every experiment covers all gates.
OTLP traces from step 3 land in project Logs. Datasets and Experiments in the UI
come from this Eval() path.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

import braintrust
from braintrust import Score

from loan_agents import models
from scoring import runs

PROJECT = "loan-agents"
CHUNK = 50
ALL_GATES = tuple(f"G{i}" for i in range(1, 23))


def chunk_name(start: int, end: int) -> str:
    return f"T{start}-T{end}"


def _gate_code(case: dict) -> str:
    if case.get("gate_code"):
        return str(case["gate_code"])
    gate = str(case.get("gate") or "")
    return gate.split()[0] if gate else ""


def _slice(cases: list[dict], size: int) -> list[tuple[str, list[dict]]]:
    out = []
    for i in range(0, len(cases), size):
        part = cases[i : i + size]
        out.append((chunk_name(i + 1, i + len(part)), part))
    return out


def _gate_sort_key(gate: str) -> int:
    n = gate[1:] if gate.startswith("G") else gate
    return int(n) if n.isdigit() else 10**9


def chunk_cases(cases: list[dict], size: int = CHUNK) -> list[tuple[str, list[dict]]]:
    """Split into named slices of `size`.

    Sequential slicing would put T1-T50 on G1 only (cases.load is gate-sorted).
    When every gate has at least one case per chunk, deal round-robin so each
    slice includes all gates and still has exactly `size` cases.
    """
    n = len(cases)
    if n == 0:
        return []
    n_chunks = (n + size - 1) // size
    buckets: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        gate = _gate_code(case)
        if gate:
            buckets[gate].append(case)
    gates = sorted(buckets, key=_gate_sort_key)
    last_cap = n - size * (n_chunks - 1)
    can_cover = (
        len(gates) >= 2
        and sum(len(part) for part in buckets.values()) == n
        and all(len(buckets[g]) >= n_chunks for g in gates)
        and len(gates) <= min(size, last_cap)
    )
    if not can_cover:
        return _slice(cases, size)

    piles: list[list[dict]] = [[] for _ in range(n_chunks)]
    for gate in gates:
        for i in range(n_chunks):
            piles[i].append(buckets[gate].pop(0))
    leftover = [case for gate in gates for case in buckets[gate]]
    i = 0
    for case in leftover:
        tries = 0
        while len(piles[i % n_chunks]) >= size:
            i += 1
            tries += 1
            if tries > n_chunks:
                raise RuntimeError("chunk deal overflow")
        piles[i % n_chunks].append(case)
        i += 1
    return [(chunk_name(i * size + 1, i * size + len(piles[i])), piles[i]) for i in range(n_chunks)]


def dataset_name(n: int) -> str:
    """Legacy helper: a full suite of n cases is T1-Tn."""
    return chunk_name(1, n)


def _publish_one(
    label: str,
    part: list[dict],
    all_by_id: dict[str, dict],
    saved: dict[str, dict],
    grades: dict[str, dict],
    sdk: Any,
    max_concurrency: int,
    experiment_name: str | None = None,
) -> dict[str, Any]:
    dataset = sdk.init_dataset(project=PROJECT, name=label)
    for case in part:
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
                "chunk": label,
            },
        )
    dataset.flush()

    def cached(inp: dict) -> dict:
        cid = inp["case_id"]
        if cid not in grades:
            grades[cid] = runs.grade(all_by_id[cid], saved[cid])
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
        return None if value == "REVIEW" else Score(
            name="verdict", score=1.0 if value == "PASS" else 0.0, metadata={"verdict": value}
        )

    result = sdk.Eval(
        PROJECT,
        data=[row for row in dataset if row["input"]["case_id"] in saved],
        task=task,
        scores=[tool_check, facts_check, policy_check, ai_judge, verdict],
        max_concurrency=max_concurrency,
        experiment_name=experiment_name or label,
        metadata={
            "agent_model": models.agent_model_name(),
            "judge_model": models.JUDGE_MODEL,
            "chunk": label,
        },
    )
    summary = getattr(result, "summary", None)
    gates = sorted({_gate_code(c) for c in part if _gate_code(c)}, key=_gate_sort_key)
    return {
        "dataset": label,
        "experiment_name": experiment_name or label,
        "experiment_url": getattr(summary, "experiment_url", None),
        "n": len(part),
        "n_gates": len(gates),
        "gates": gates,
        "ids": [c["id"] for c in part],
    }


def publish(
    all_cases: dict[str, dict] | list[dict],
    saved: dict[str, dict],
    *,
    bt: Any | None = None,
    experiment_name: str | None = None,
    max_concurrency: int = 1,
    chunk_size: int = CHUNK,
) -> dict[str, Any]:
    sdk = bt or braintrust
    ordered = list(all_cases.values()) if isinstance(all_cases, dict) else list(all_cases)
    all_by_id = {c["id"]: c for c in ordered}
    grades: dict[str, dict] = {}
    t0 = time.time()
    parts = chunk_cases(ordered, chunk_size)
    chunks_out = []
    for label, part in parts:
        exp = experiment_name if experiment_name and len(parts) == 1 else label
        chunks_out.append(
            _publish_one(label, part, all_by_id, saved, grades, sdk, max_concurrency, experiment_name=exp)
        )
    return {
        "dataset": chunks_out[0]["dataset"] if len(chunks_out) == 1 else f"{len(chunks_out)} chunks",
        "experiment_name": chunks_out[0]["experiment_name"] if len(chunks_out) == 1 else f"{len(chunks_out)} experiments",
        "experiment_url": chunks_out[0].get("experiment_url") if len(chunks_out) == 1 else None,
        "chunks": chunks_out,
        "grades": grades,
        "seconds": round(time.time() - t0, 1),
    }
