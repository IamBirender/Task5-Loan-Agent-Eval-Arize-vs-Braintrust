"""Audit extra cases: uniqueness, schema, and figures vs the 8-loan DuckDB sample."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from loan_agents import data, tools
from scoring import cases, checks

ROOT = Path(__file__).resolve().parent.parent
PATHS = [
    ROOT / "extra_test_cases.json",
]
NEED = {"name", "description", "evaluatedAgent", "inputs", "expectations", "metadata"}
META = ("testId", "qualityGate", "evaluationMethod", "source")
# Limits, gate numbers, percents of samples, and policy numbers that are not loan-file cells.
ALLOW_NOT_IN_FILE = {
    "120", "180", "25", "40", "80", "95", "99", "100", "108", "110",
    "12", "13", "16", "17", "18", "19", "20", "24", "33", "36", "43",
    "61", "72", "94", "97",
    "25000", "40000", "80000",
    "0.25", "0.4", "0.8",
    "5", "6", "7", "8", "9",  # these won't appear as 1-digit anyway
}
DERIVED = {
    "218750": "Original Home Value = 175000 / 0.80",
    "22.4": "1 - 114920.58 / 148000",
    "9.7": "165000 / 1697000",
    "12.5": "5/8 vs 4/8",
    "114.3": "199984.52 / 175000",
}


def main() -> None:
    cs = cases.load()
    ids = [c["id"] for c in cs]
    print(f"loaded {len(cs)} unique_ids={len(set(ids))}")
    dups = [i for i, n in Counter(ids).items() if n > 1]
    print(f"duplicate ids: {len(dups)} {dups[:10]}")

    schema_bad = []
    extras = []
    for p in PATHS:
        if not p.exists():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        for j in doc.get("testCases", []):
            extras.append((p.name, j))
            miss = NEED - j.keys()
            if miss:
                schema_bad.append((j.get("name"), f"keys {miss}"))
            e = j.get("expectations") or {}
            if "Response" not in (e.get("expectedResponse") or {}):
                schema_bad.append((j.get("name"), "expectedResponse"))
            m = j.get("metadata") or {}
            for k in META:
                if k not in m:
                    schema_bad.append((j.get("name"), k))
            inp = j.get("inputs") or {}
            if not inp.get("UserInput") and not inp.get("Turns"):
                schema_bad.append((j.get("name"), "no input"))
            if not inp.get("SessionId"):
                schema_bad.append((j.get("name"), "no SessionId"))
    print(f"schema_bad {len(schema_bad)} {schema_bad[:12]}")

    prompts = defaultdict(list)
    for c in cs:
        if c["source"] != "added by us":
            continue
        prompts[(c["gate_code"], c["input"].strip().lower())].append(c["id"])
    cloned = {k: v for k, v in prompts.items() if len(v) > 1}
    extra_n = sum(1 for c in cs if c["source"] == "added by us")
    print(f"extra cases {extra_n} unique prompts {len(prompts)} cloned groups {len(cloned)} cases in clones {sum(len(v) for v in cloned.values())}")
    print("clone sizes", dict(Counter(len(v) for v in cloned.values())))
    for (_gate, text), ids_ in list(cloned.items())[:12]:
        print(f"  clone {ids_[:4]} n={len(ids_)} :: {text[:90]}")

    loan_ids = [r[0] for r in data.connect().execute("SELECT loan_id FROM loan_static").fetchall()]
    truth = [
        tools.credit_performance(),
        tools.memory_read(),
        tools.data_validation(),
        tools.rows("SELECT * FROM default_risk_screen"),
        tools.rows("SELECT * FROM loan_static"),
        {"configured_screen_thresholds": {"ltv_min": 80, "dti_min": 43, "min_score_below": 700}},
    ]
    truth += [tools.loan_performance(i) for i in loan_ids]
    truth += [tools.cohort_comparison(i) for i in loan_ids]
    truth_text = json.dumps(truth, default=str)
    truth_text += json.dumps(data.connect().execute("SELECT * FROM loan_monthly").fetchall(), default=str)
    known = {checks._norm(f) for f in checks.FACT.findall(truth_text)}

    missing_by_fig = Counter()
    problem_cases = []
    for c in cs:
        if c["source"] != "added by us":
            continue
        facts = checks.all_figures(c)
        own = {checks._norm(f) for f in checks.FACT.findall(c["input"])} | set(checks.VERDICT.findall(c["input"]))
        missing = [
            f
            for f in facts
            if f not in known
            and f not in own
            and not checks.VERDICT.fullmatch(f)
            and f not in ALLOW_NOT_IN_FILE
            and f not in DERIVED
        ]
        if missing:
            problem_cases.append((c["id"], missing, c["expected"][:120]))
            for f in missing:
                missing_by_fig[f] += 1
    print(f"extra cases with unexplained figures: {len(problem_cases)}")
    print("top unexplained figures:")
    for fig, n in missing_by_fig.most_common(40):
        print(f"  {fig!r}: {n}")
    print("sample problem cases:")
    for row in problem_cases[:20]:
        print(" ", row)

    print("--- tool snapshots ---")
    dv = tools.data_validation()
    print("data_validation keys", list(dv)[:20] if isinstance(dv, dict) else type(dv))
    print(json.dumps(dv, default=str)[:2000])
    print("memory_read", json.dumps(tools.memory_read(), default=str)[:1500])
    cp = tools.credit_performance()
    print("pool", {k: cp[k] for k in ("loans", "monthly_records", "original_balance_total") if k in cp})
    print("active", cp.get("active_at_last_period"))
    print("90+", cp.get("ever_90_plus_days"))
    print("180+", cp.get("ever_180_plus_days"))
    print("modified", cp.get("modified_loans"))
    print("reo", cp.get("indicative_reo_loss"))
    print("outcomes", cp.get("outcomes"))


if __name__ == "__main__":
    main()
