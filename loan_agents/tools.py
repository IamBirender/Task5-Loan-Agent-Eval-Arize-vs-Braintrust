"""The 9 tools named in the test cases. Agent path uses Aurora, Bedrock KB, Memory, Gateway."""
from __future__ import annotations

import functools
import json
import os
import re

from strands import Agent, tool

from . import aws_citation, aws_config, aws_kb, aws_memory, aws_sql, context, data, models
from .sql_safety import SYSTEM_PROMPT_TEMPLATE, TextToSqlError, normalise_generated_sql, validate_sql

CALLS = context.CtxList("loan_tool_calls")
FAULT: str | None = None
LOAN_ID = re.compile(r"\b1\d{11}\b|\b9{12}\b")
PEER_FEATURES = ["borrower_credit_score", "ltv", "dti", "original_interest_rate", "original_upb"]
COHORT_FEATURES = ["borrower_credit_score", "ltv", "original_interest_rate", "orig_term", "num_units"]

_RDS_CLIENT = None
_KB_CLIENT = None
_MEMORY_CLIENT = None
_GATEWAY_OPENER = None


def use_aws() -> bool:
    """Aurora/KB/Memory/Gateway when those ARNs exist; otherwise DuckDB on this host."""
    flag = os.getenv("LOAN_USE_AWS", "").strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    if flag in {"1", "true", "yes"}:
        return True
    if os.getenv("LOAN_AURORA_CLUSTER_ARN") and os.getenv("LOAN_AURORA_SECRET_ARN"):
        return True
    if models.PROVIDER != "agentcore":
        return False
    try:
        cfg = aws_config.load_config()
    except Exception:
        return False
    return bool(cfg.aurora_cluster_arn and cfg.aurora_secret_arn)


def current_fault() -> str | None:
    return FAULT or context.fault.get()


def recorded(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            if current_fault() == f"{fn.__name__}_down":
                raise ConnectionError(
                    f"{fn.__name__} service unavailable (simulated outage for the resiliency test)"
                )
            out = fn(*args, **kwargs)
        except Exception as e:
            out = {"error": f"{type(e).__name__}: {e}"}
        text = json.dumps(out, default=str)
        CALLS.append({"tool": fn.__name__, "args": kwargs or list(args), "output": text[:2000]})
        return text
    return wrapper


def db():
    return data.connect(read_only=True)


def rows(sql, params=()):
    if use_aws():
        return aws_sql.execute(sql, params, rds_client=_RDS_CLIENT)
    cur = db().execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def fmt_period(p):
    return f"{p[5:]}/{p[:4]}" if p and len(p) == 7 else p


def tables_fingerprint() -> str:
    if use_aws():
        return aws_sql.fingerprint(rds_client=_RDS_CLIENT)
    return str(data.fingerprint())


def text_to_sql(question: str) -> dict:
    """Turn a plain-English question about the loans into ONE read-only SQL SELECT, run it, and return the SQL and rows.
    Use it for every screen (the default risk screen or custom thresholds) and for field lookups.
    Tables: loan_static (one row per loan: loan_id, state, purpose, orig_upb, ltv, cltv, dti, borrower_score,
    co_borrower_score, min_score, ...), default_risk_screen (the configured screen, one flag column per rule + flag_count),
    loan_features (derived facts per loan) and loan_monthly (61 source fields, one row per loan per month)."""
    schema = aws_sql.schema_text() if use_aws() else data.schema_text(db())
    system = SYSTEM_PROMPT_TEMPLATE.format(schema=schema)
    sql = str(models.track(Agent(model=models.agent_model(), system_prompt=system, callback_handler=None))(question))
    sql = normalise_generated_sql(sql)
    try:
        sql = validate_sql(sql)
    except TextToSqlError as e:
        return {"sql": sql, "blocked_by": "validate_sql", "error": str(e)}
    try:
        result = rows(sql)
    except Exception as e:
        return {"sql": sql, "error": f"{type(e).__name__}: {e}"[:400]}
    return {"sql": sql, "row_count": len(result), "rows": result[:50]}


def loan_performance(loan_identifier: str) -> dict:
    """Full performance history of ONE loan: origination facts, peak delinquency, modifications, how it ended,
    and (for a loss) the indicative net loss. Monthly rows are listed only when something changed."""
    f = rows("SELECT * FROM loan_features WHERE loan_identifier = ?", (str(loan_identifier),))
    if not f:
        return {"error": f"loan {loan_identifier} not found in the sample", "loans_in_sample": 8}
    extra = rows(
        "SELECT num_borrowers, num_units, purpose AS loan_purpose, property_type, channel, orig_term, orig_date, "
        "mi_pct FROM loan_static WHERE loan_id = ?",
        (str(loan_identifier),),
    )
    f = {**f[0], **(extra[0] if extra else {})}
    f["loan_purpose"] = {"P": "purchase", "C": "cash-out refinance", "R": "refinance (no cash out)"}.get(
        f.get("loan_purpose"), f.get("loan_purpose")
    )
    if f.get("outcome") == "active" and f.get("original_upb"):
        f["pct_paid_down"] = round((1 - (f.get("last_upb") or 0) / f["original_upb"]) * 100, 1)
    else:
        f["pct_paid_down"] = None
    months = rows(
        "SELECT period_ym, current_loan_delinquency_status AS dq, current_actual_upb AS upb, current_interest_rate AS rate, "
        "modification_flag AS mod, zero_balance_code AS zb, loan_payment_history AS history, "
        "borrower_assistance_plan AS bap, alternative_delinquency_resolution AS adr "
        "FROM loan_monthly WHERE loan_identifier = ? ORDER BY period_ym",
        (str(loan_identifier),),
    )
    changes, prev = [], {}
    for m in months:
        key = (m["dq"], m["rate"], m["mod"], m["zb"], m["history"], m["bap"], m["adr"])
        grew = prev.get("upb") is not None and m["upb"] is not None and m["upb"] > prev["upb"]
        if key != prev.get("key") or grew:
            changes.append({
                "period": fmt_period(m["period_ym"]), "months_delinquent": m["dq"], "upb": m["upb"],
                "interest_rate": m["rate"], "modification_flag": m["mod"], "zero_balance_code": m["zb"] or None,
                **({"balance_increased": True} if grew else {}),
                **({"payment_history": m["history"]} if m["history"] else {}),
                **({"borrower_assistance_plan": m["bap"]} if m["bap"] else {}),
                **({"alternative_delinquency_resolution": m["adr"]} if m["adr"] else {}),
            })
        prev = {"key": key, "upb": m["upb"] if m["upb"] else prev.get("upb")}
    for k in ("first_period", "last_period", "peak_first_period", "first_90_plus_period", "first_180_plus_period", "first_modified_period"):
        if k in f:
            f[k] = fmt_period(f[k])
    if f.get("indicative_net_loss") is not None:
        f["loss_note"] = (
            "Indicative only: UPB at removal + disposition costs - net sales proceeds. It is NOT Fannie Mae's "
            "published Net Loss, because delinquent accrued interest and other proceeds are not in this file."
        )
    return {"loan": f, "monthly_changes": changes}


def reo_dates(loan_id: str) -> dict:
    d = rows(
        "SELECT max(NULLIF(foreclosure_date,'')) AS f, max(NULLIF(disposition_date,'')) AS d "
        "FROM loan_monthly WHERE loan_identifier = ?",
        (loan_id,),
    )[0]
    mmyyyy = lambda v: f"{v[:2]}/{v[2:]}" if v else None
    return {"foreclosure_date": mmyyyy(d["f"]), "disposition_date": mmyyyy(d["d"])}


def credit_performance() -> dict:
    """Pool-level credit summary for all 8 loans: size, active loans, outcomes, serious delinquency (90+ and 180+ days),
    modifications, indicative REO loss and pool loss rate, plus a one-line row per loan."""
    loans = rows("SELECT * FROM loan_features ORDER BY loan_identifier")
    last = max(l["last_period"] for l in loans)
    active = [l for l in loans if l["outcome"] == "active"]
    reo = [l for l in loans if l["indicative_net_loss"] is not None]
    total_orig = sum(l["original_upb"] for l in loans)
    mods = []
    for l in loans:
        if l["first_modified_period"]:
            before = rows(
                "SELECT current_interest_rate AS r, current_actual_upb AS u FROM loan_monthly "
                "WHERE loan_identifier=? AND period_ym < ? AND current_actual_upb > 0 ORDER BY period_ym DESC LIMIT 1",
                (l["loan_identifier"], l["first_modified_period"]),
            )[0]
            after = rows(
                "SELECT current_interest_rate AS r, current_actual_upb AS u FROM loan_monthly "
                "WHERE loan_identifier=? AND period_ym >= ? ORDER BY period_ym LIMIT 3",
                (l["loan_identifier"], l["first_modified_period"]),
            )
            mods.append({
                "loan_identifier": l["loan_identifier"],
                "first_flagged_modified": fmt_period(l["first_modified_period"]),
                "rate_before": before["r"], "rate_after": [a["r"] for a in after],
                "upb_before": before["u"], "upb_after": [a["u"] for a in after],
                "max_upb_seen": l["max_upb_seen"],
                "max_upb_pct_of_original": round(l["max_upb_seen"] / l["original_upb"] * 100, 1),
            })
    return {
        "loans": len(loans),
        "monthly_records": sum(l["monthly_records"] for l in loans),
        "original_balance_total": total_orig,
        "last_reporting_period": fmt_period(last),
        "active_at_last_period": {
            "count": len(active),
            "outstanding_upb": round(sum(l["last_upb"] for l in active), 2),
            "loans": [l["loan_identifier"] for l in active],
        },
        "outcomes": {o: [l["loan_identifier"] for l in loans if l["outcome"] == o] for o in sorted({l["outcome"] for l in loans})},
        "ever_90_plus_days": [
            {"loan_identifier": l["loan_identifier"], "first": fmt_period(l["first_90_plus_period"])}
            for l in loans if l["first_90_plus_period"]
        ],
        "ever_180_plus_days": [
            {"loan_identifier": l["loan_identifier"], "first": fmt_period(l["first_180_plus_period"])}
            for l in loans if l["first_180_plus_period"]
        ],
        "modified_loans": mods,
        "indicative_reo_loss": [
            {
                "loan_identifier": l["loan_identifier"], "upb_at_removal": l["upb_at_removal"],
                "costs": l["disposition_costs"], "net_sales_proceeds": l["net_sales_proceeds"],
                "indicative_net_loss": l["indicative_net_loss"], "severity_pct": l["indicative_severity_pct"],
                **reo_dates(l["loan_identifier"]),
                "loan_share_of_pool_original_balance_pct": round(l["original_upb"] / total_orig * 100, 1),
            }
            for l in reo
        ],
        "pool_loss_rate_pct_of_original_balance": round(sum(l["indicative_net_loss"] for l in reo) / total_orig * 100, 2),
        "per_loan": [
            {k: l[k] for k in (
                "loan_identifier", "property_state", "original_upb", "ltv", "dti",
                "borrower_credit_score", "peak_months_delinquent", "outcome",
            )}
            for l in loans
        ],
        "note": "Indicative figures only. This is an 8-loan sample: it cannot prove that any rule predicts default.",
    }


def cohort_comparison(loan_identifier: str, k: int = 3) -> dict:
    """Rank the k loans most similar to one loan by origination characteristics (credit score, LTV, interest rate,
    loan term, number of units). Each feature is scaled 0-1 across the 8 loans; distance = mean absolute difference."""
    loans = rows(
        "SELECT f.*, s.orig_term, s.num_units FROM loan_features f JOIN loan_static s ON s.loan_id = f.loan_identifier"
    )
    me = next((l for l in loans if l["loan_identifier"] == str(loan_identifier)), None)
    if me is None:
        return {"error": f"loan {loan_identifier} not found in the sample"}
    rng = {f: (min(l[f] for l in loans), max(l[f] for l in loans)) for f in COHORT_FEATURES}

    def scale(l, f):
        return (l[f] - rng[f][0]) / ((rng[f][1] - rng[f][0]) or 1)

    peers = sorted(
        (
            {
                "loan_identifier": l["loan_identifier"], "outcome": l["outcome"],
                "peak_months_delinquent": l["peak_months_delinquent"],
                "last_period": fmt_period(l["last_period"]),
                "modified": bool(l["first_modified_period"]),
                "distance": round(sum(abs(scale(l, f) - scale(me, f)) for f in COHORT_FEATURES) / len(COHORT_FEATURES), 3),
            }
            for l in loans if l is not me
        ),
        key=lambda p: p["distance"],
    )
    return {"loan": loan_identifier, "features": COHORT_FEATURES, "method": "min-max scaling, mean absolute difference", "peers": peers[:k]}


def memory_read(namespace: str = "credit_events") -> dict:
    """Read long-term memory. Namespace 'credit_events' stores the loans that had a credit event
    (90+ days delinquent, a modification, or a loss), with peak delinquency and outcome. Loans with no event are not stored."""
    if use_aws():
        recs = aws_memory.retrieve_memory(namespace, client=_MEMORY_CLIENT)
        parsed = []
        for rec in recs:
            try:
                parsed.append(json.loads(rec["content"]) if isinstance(rec["content"], str) else rec["content"])
            except json.JSONDecodeError:
                parsed.append({"raw": rec["content"]})
        return {
            "namespace": namespace,
            "records": parsed,
            "note": f"{len(parsed)} records in {namespace}.",
        }
    if namespace != "credit_events":
        return {"namespace": namespace, "records": [], "note": "no records in this namespace"}
    recs = []
    for l in rows(
        "SELECT * FROM loan_features WHERE first_90_plus_period IS NOT NULL OR first_modified_period IS NOT NULL "
        "OR indicative_net_loss IS NOT NULL ORDER BY loan_identifier"
    ):
        ended = l["zero_balance_effective_date"]
        recs.append({
            "loan_identifier": l["loan_identifier"],
            "peak_months_delinquent": l["peak_months_delinquent"],
            "peak_first_reported": fmt_period(l["peak_first_period"]),
            "modified": bool(l["first_modified_period"]),
            "first_modified": fmt_period(l["first_modified_period"]),
            "outcome": l["outcome"],
            "outcome_date": f"{ended[:2]}/{ended[2:]}" if ended else f"still active at {fmt_period(l['last_period'])}",
            "origination": {f: l[f] for f in PEER_FEATURES},
        })
    return {
        "namespace": "credit_events",
        "records": recs,
        "note": f"{len(recs)} of 8 loans had a credit event; the others are not stored.",
    }


def kb_retrieve(query: str, top_k: int = 5) -> dict:
    """Search Fannie Mae's public documents (glossary and file layout, dataset FAQs, tutorial, statistical summary) and return
    the best matching passages with their source file and page."""
    if use_aws():
        return aws_kb.retrieve(query, top_k=top_k, client=_KB_CLIENT)
    import math
    from functools import lru_cache

    word = re.compile(r"[a-z0-9]{3,}")

    @lru_cache(maxsize=1)
    def passages():
        return [(p["source"], p["page"], p["text"]) for p in json.loads(data.KB_FILE.read_text(encoding="utf-8"))]

    q = set(word.findall(query.lower()))
    scored = sorted(
        ((len(q & set(word.findall(p.lower()))) / math.sqrt(1 + len(p) / 400), s, pg, p) for s, pg, p in passages()),
        reverse=True,
    )
    hits = [{"source": s, "page": pg, "text": p[:1200], "score": round(sc, 3)} for sc, s, pg, p in scored[:top_k] if sc > 0]
    return {"query": query, "passages": hits} if hits else {"query": query, "passages": [], "note": "no supporting documents found"}


def data_validation() -> dict:
    """Profile of the validated BASELINE file, used to judge new monthly files and drift: expected column count,
    record and loan counts, last period, how often key fields are filled, and the serious-delinquency rate."""
    n_rows = rows("SELECT count(*) AS n FROM loan_monthly")[0]["n"]
    n_loans = rows("SELECT count(DISTINCT loan_identifier) AS n FROM loan_monthly")[0]["n"]
    last = rows("SELECT max(period_ym) AS last FROM loan_monthly")[0]["last"]
    hist = rows(
        "SELECT count(*) AS n, min(period_ym) AS mn, max(period_ym) AS mx FROM loan_monthly WHERE loan_payment_history <> ''"
    )[0]
    dq90 = rows("SELECT count(*) AS n FROM loan_features WHERE first_90_plus_period IS NOT NULL")[0]["n"]
    return {
        "expected_columns": 108, "baseline_records": n_rows, "baseline_loans": n_loans,
        "last_period": fmt_period(last), "columns_with_values": 61,
        "loan_payment_history_filled": {
            "records": hist["n"], "of": n_rows, "from": fmt_period(hist["mn"]), "to": fmt_period(hist["mx"]),
        },
        "loans_ever_90_plus_days": {"count": dq90, "of": n_loans},
        "rules": [
            "A file with a different column count must be rejected before analysis (schema change).",
            "A large change in how often a field is filled is drift: investigate before using the field.",
            "Compare new results with the baseline AND with the source data before accepting them.",
        ],
    }


def citation_check(response_text: str, scope: str = "draft") -> dict:
    """Check a draft or response against the source data. Runs the citation checker with each mentioned
    loan's fact sheet as the evidence, and returns that evidence so the numbers can be compared one by one."""
    ids = sorted(set(LOAN_ID.findall(response_text)))
    evidence = []
    for i in ids:
        f = rows("SELECT * FROM loan_features WHERE loan_identifier = ?", (i,))
        evidence.append({
            "text": json.dumps(f[0], default=str) if f else f"loan {i} not found",
            "source": f"loan_features/{i}", "page": 1,
        })
    if not ids:
        evidence.append({
            "text": json.dumps(credit_performance(), default=str)[:4000],
            "source": "credit_performance/pool", "page": 1,
        })
    if use_aws():
        result = aws_citation.call_gateway(response_text, evidence, opener=_GATEWAY_OPENER)
    else:
        from . import citation_local

        result = citation_local.check_citations(response_text, evidence)
    return {
        "scope": scope,
        "repo_citation_check": {
            "passed": result.get("passed"),
            "total_claims": result.get("total_claims"),
            "unsupported_claims": result.get("unsupported_claims"),
        },
        "evidence": evidence,
        "note": "The checker tests word overlap. Compare every number and date in the claim with the evidence yourself.",
    }


ALL = {
    fn.__name__: tool(recorded(fn))
    for fn in [
        text_to_sql, loan_performance, credit_performance, cohort_comparison,
        memory_read, kb_retrieve, data_validation, citation_check,
    ]
}
