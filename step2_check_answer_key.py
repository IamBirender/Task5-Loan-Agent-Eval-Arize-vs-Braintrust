"""STEP 2 - Audit the answer keys. Does not create cases.

Every figure in each expected response must appear in the 8-loan data (tool outputs) or in
the case's own question. A figure found in neither means the key may be wrong, so a later
FAIL is not the agent's fault.

Cases come from scoring.cases.load(): agentic_evaluation_test_cases.xlsx plus extra_test_cases.json.
ONLY_SENIOR_CASES=1 uses just the 60 spreadsheet rows.

Usage:  python step2_check_answer_key.py
"""
import json

from loan_agents import data, tools
from scoring import cases, checks
from scripts.build_extra_test_cases import MAX_GUIDELINES, SENIOR_EXPECTED_CAP

DERIVED = {
    "218750": "Original Home Value = $175,000 / 80% LTV (a calculation)",
    "22.4": "share paid down = 1 - 114,920.58 / 148,000 (a calculation)",
    "9.7": "REO loan's $165,000 / $1,697,000 pool (a calculation)",
    "12.5": "one more loan of 8 (4/8 -> 5/8) (a calculation)",
    "3.49": "pool indicative loss rate = 59,160.03 / 1,697,000",
}
DOC_CASES = {"AV-G7-006": "dates quoted from the Fannie Mae FAQ document, not from the loan data"}
ALLOWED_TOOLS = {
    "text_to_sql",
    "loan_performance",
    "credit_performance",
    "cohort_comparison",
    "pool_screening",
    "citation_check",
    "data_validation",
    "kb_retrieve",
    "memory_read",
}


def known_figures() -> set[str]:
    ids = [r[0] for r in data.connect().execute("SELECT loan_id FROM loan_static").fetchall()]
    truth = [
        tools.credit_performance(),
        tools.memory_read(),
        tools.data_validation(),
        tools.rows("SELECT * FROM default_risk_screen"),
        tools.rows("SELECT * FROM loan_static"),
        {"configured_screen_thresholds": {"ltv_min": 80, "dti_min": 43, "min_score_below": 700}},
    ]
    truth += [tools.loan_performance(i) for i in ids] + [tools.cohort_comparison(i) for i in ids]
    blob = json.dumps(truth, default=str)
    blob += json.dumps(data.connect().execute("SELECT * FROM loan_monthly").fetchall(), default=str)
    return {checks._norm(f) for f in checks.FACT.findall(blob)}


def audit(all_cases: list[dict] | None = None, known: set[str] | None = None) -> dict:
    all_cases = all_cases if all_cases is not None else cases.load()
    known = known if known is not None else known_figures()
    missing_rows, derived_rows, format_rows, tool_rows = [], [], [], []
    for c in all_cases:
        facts = checks.all_figures(c)
        own = {checks._norm(f) for f in checks.FACT.findall(c["input"])} | set(checks.VERDICT.findall(c["input"]))
        missing = [f for f in facts if f not in known and f not in own and not checks.VERDICT.fullmatch(f)]
        if c["id"] in DOC_CASES:
            derived_rows.append((c, [], [DOC_CASES[c["id"]]]))
            continue
        explained = [f"{f} ({DERIVED[f]})" for f in missing if f in DERIVED]
        missing = [f for f in missing if f not in DERIVED]
        if missing:
            missing_rows.append((c, missing))
        elif explained:
            derived_rows.append((c, explained, []))
        if c["source"] == "added by us":
            if not c["expected"].startswith("The response must"):
                format_rows.append((c["id"], "expected must start with 'The response must'"))
            if len(c["expected"]) > SENIOR_EXPECTED_CAP:
                format_rows.append((c["id"], f"expected {len(c['expected'])} chars > {SENIOR_EXPECTED_CAP}"))
            if len(c["guidelines"]) > MAX_GUIDELINES:
                format_rows.append((c["id"], f"{len(c['guidelines'])} guidelines"))
        bad_tools = [t["name"] for t in c["expected_tools"] if t["name"] not in ALLOWED_TOOLS]
        if bad_tools:
            tool_rows.append((c["id"], bad_tools))
    senior = [c for c in all_cases if c["source"] != "added by us"]
    extras = [c for c in all_cases if c["source"] == "added by us"]
    return {
        "n": len(all_cases),
        "n_senior": len(senior),
        "n_extras": len(extras),
        "missing": missing_rows,
        "derived": derived_rows,
        "format": format_rows,
        "tools": tool_rows,
        "extra_missing": [(c, m) for c, m in missing_rows if c["source"] == "added by us"],
        "senior_missing": [(c, m) for c, m in missing_rows if c["source"] != "added by us"],
    }


def render(report: dict) -> str:
    lines = [
        "# Answer key check (step 2)",
        "",
        "This step **audits** expected answers. It does not generate test cases.",
        "Keys live in `agentic_evaluation_test_cases.xlsx` (60) and `extra_test_cases.json` (2440).",
        "Figures in each expected response must appear in the 8-loan sample or in the question.",
        "",
        f"**{report['n']} cases** ({report['n_senior']} spreadsheet, {report['n_extras']} extras).",
        "",
        "## Unreproducible figures",
        "",
        "| Case | Source | Figures not in the data or the question |",
        "|---|---|---|",
    ]
    if not report["missing"]:
        lines.append("| — | — | none |")
    for c, missing in report["missing"]:
        lines.append(f"| {c['id']} | {c['source']} | **NOT FOUND: {', '.join(missing)}** |")
    lines += [
        "",
        f"**{len(report['missing'])} of {report['n']}** keys have figures that could not be reproduced. "
        f"Spreadsheet: {len(report['senior_missing'])}. Extras: {len(report['extra_missing'])}.",
        "",
        "## Derived or document figures (ok)",
        "",
    ]
    if not report["derived"]:
        lines.append("None.")
    else:
        for c, explained, notes in report["derived"]:
            extra = "; ".join(explained + notes)
            lines.append(f"- {c['id']}: {extra}")
    lines += ["", "## Extra-key format (spreadsheet voice, short judge keys)", ""]
    if report["format"]:
        for cid, why in report["format"][:50]:
            lines.append(f"- {cid}: {why}")
        if len(report["format"]) > 50:
            lines.append(f"- … {len(report['format']) - 50} more")
    else:
        lines.append(
            f"All {report['n_extras']} extras start with “The response must”, "
            f"stay ≤ {SENIOR_EXPECTED_CAP} characters, and have ≤ {MAX_GUIDELINES} guidelines."
        )
    lines += ["", "## Expected tools", ""]
    if report["tools"]:
        for cid, names in report["tools"]:
            lines.append(f"- {cid}: unknown {', '.join(names)}")
    else:
        lines.append("Every expected tool name is a configured specialist tool.")
    return "\n".join(lines) + "\n"


def main() -> None:
    report = audit()
    text = render(report)
    out = data.HERE / "results" / "answer_key_check.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {out.relative_to(data.HERE)}")
    if report["extra_missing"] or report["format"] or report["tools"]:
        raise SystemExit("Extra answer keys failed the step-2 audit.")


if __name__ == "__main__":
    main()
