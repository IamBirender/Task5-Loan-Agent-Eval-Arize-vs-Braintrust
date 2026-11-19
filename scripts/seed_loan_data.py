"""Load Aurora, upload KB passages, and seed AgentCore Memory from local files.

Reads data/loans.duckdb and data/kb_passages.json. Those Fannie Mae files are
not in git. Stops with a clear error if they are missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loan_agents import aws_config, aws_memory, aws_sql, data  # noqa: E402

CREDIT_SQL = """
SELECT * FROM loan_features
WHERE first_90_plus_period IS NOT NULL
   OR first_modified_period IS NOT NULL
   OR indicative_net_loss IS NOT NULL
ORDER BY loan_identifier
"""


def _require_files() -> None:
    missing = [p for p in (data.DB_FILE, data.KB_FILE) if not p.exists()]
    if missing:
        names = ", ".join(str(p.relative_to(ROOT)) for p in missing)
        raise SystemExit(
            f"Missing {names}. Copy the Fannie Mae prepared files onto this machine "
            "(they are not in git) and rerun."
        )


def _copy_table(con, table: str, columns: list[str] | None = None) -> int:
    if columns:
        rel = con.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchdf()
    else:
        rel = con.execute(f"SELECT * FROM {table}").fetchdf()
    if rel.empty:
        return 0
    aws_sql.execute(f"DELETE FROM loan.{table}", validate=False)
    inserted = 0
    cols = list(rel.columns)
    for _, row in rel.iterrows():
        placeholders = ", ".join(f":{c}" for c in cols)
        sql = f"INSERT INTO loan.{table} ({', '.join(cols)}) VALUES ({placeholders})"
        params = {c: (None if row[c] is None or str(row[c]) == "NaT" else row[c]) for c in cols}
        for k, v in list(params.items()):
            try:
                if v is not None and v != v:  # NaN
                    params[k] = None
            except Exception:
                pass
            if hasattr(v, "item"):
                params[k] = v.item()
        aws_sql.execute(sql, params, validate=False)
        inserted += 1
    return inserted


def seed_aurora() -> None:
    con = data.connect(read_only=True)
    n_static = _copy_table(con, "loan_static")
    n_features = _copy_table(con, "loan_features")
    monthly_cols = [
        "loan_identifier", "period_ym", "monthly_reporting_period",
        "current_loan_delinquency_status", "current_actual_upb", "current_interest_rate",
        "modification_flag", "zero_balance_code", "zero_balance_effective_date",
        "loan_payment_history", "borrower_assistance_plan", "alternative_delinquency_resolution",
        "foreclosure_date", "disposition_date", "upb_at_the_time_of_removal",
        "foreclosure_costs", "property_preservation_and_repair_costs", "asset_recovery_costs",
        "miscellaneous_holding_expenses_and_credits", "associated_taxes_for_holding_property",
        "net_sales_proceeds",
    ]
    present = [c[0] for c in con.execute("DESCRIBE loan_monthly").fetchall()]
    monthly_cols = [c for c in monthly_cols if c in present]
    n_monthly = _copy_table(con, "loan_monthly", monthly_cols)
    print(f"Aurora: loan_static {n_static}, loan_features {n_features}, loan_monthly {n_monthly}")


def seed_kb() -> None:
    import boto3

    cfg = aws_config.load_config()
    if not cfg.docs_bucket or not cfg.kb_id:
        raise SystemExit("Knowledge Base id or docs bucket is missing in SSM.")
    s3 = boto3.client("s3", region_name=cfg.region)
    passages = json.loads(data.KB_FILE.read_text(encoding="utf-8"))
    by_source: dict[str, list[str]] = {}
    for p in passages:
        by_source.setdefault(p["source"], []).append(f"[page {p['page']}] {p['text']}")
    for source, chunks in by_source.items():
        key = f"passages/{source}.txt"
        s3.put_object(Bucket=cfg.docs_bucket, Key=key, Body="\n\n".join(chunks).encode("utf-8"))
        print(f"uploaded s3://{cfg.docs_bucket}/{key}")
    agent = boto3.client("bedrock-agent", region_name=cfg.region)
    sources = agent.list_data_sources(knowledgeBaseId=cfg.kb_id).get("dataSourceSummaries") or []
    if not sources:
        print("No KB data source yet; ingestion skipped.")
        return
    ds_id = sources[0]["dataSourceId"]
    job = agent.start_ingestion_job(knowledgeBaseId=cfg.kb_id, dataSourceId=ds_id)
    status = (job.get("ingestionJob") or {}).get("status")
    print(f"KB ingestion job status: {status}. Wait until it is COMPLETE before step 3.")


def seed_memory() -> None:
    con = data.connect(read_only=True)
    rows = con.execute(CREDIT_SQL).fetchdf().to_dict(orient="records")
    for rec in rows:
        payload = {k: (v.item() if hasattr(v, "item") else v) for k, v in rec.items()}
        aws_memory.create_memory_record(
            json.dumps(payload, default=str),
            namespace="credit_events",
            metadata={"loan_identifier": str(payload.get("loan_identifier") or "")},
        )
    print(f"Memory: wrote {len(rows)} credit_events records")


def main() -> None:
    _require_files()
    seed_aurora()
    seed_kb()
    seed_memory()
    print("seed complete")


if __name__ == "__main__":
    main()
