"""Aurora Serverless v2 access through the RDS Data API. Agents never open DuckDB."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import aws_config
from .sql_safety import validate_sql

_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "data" / "schemas" / "loans.sql",
    Path("/app/data/schemas/loans.sql"),
]


class SqlError(RuntimeError):
    """Raised when an RDS Data API call fails."""


def _rds_client(region_name: str | None = None):
    import boto3

    return boto3.client("rds-data", region_name=region_name or aws_config.region_name())


def _field_value(field: dict[str, Any]) -> Any:
    if "isNull" in field and field["isNull"]:
        return None
    for key in (
        "stringValue", "longValue", "doubleValue", "booleanValue", "blobValue",
    ):
        if key in field:
            return field[key]
    array = field.get("arrayValue")
    if isinstance(array, dict):
        for key in ("stringValues", "longValues", "doubleValues", "booleanValues"):
            if key in array:
                return array[key]
    return None


def _rows_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = response.get("columnMetadata") or []
    names = [c.get("name") or f"col{i}" for i, c in enumerate(metadata)]
    records = response.get("records") or []
    rows: list[dict[str, Any]] = []
    for record in records:
        values = [_field_value(f) if isinstance(f, dict) else f for f in record]
        rows.append(dict(zip(names, values)))
    return rows


def _sql_params(params: tuple | dict | None) -> list[dict[str, Any]]:
    if not params:
        return []
    if isinstance(params, dict):
        items = params.items()
    else:
        items = ((f"p{i}", v) for i, v in enumerate(params))
    out: list[dict[str, Any]] = []
    for name, value in items:
        if value is None:
            out.append({"name": str(name), "value": {"isNull": True}})
        elif isinstance(value, bool):
            out.append({"name": str(name), "value": {"booleanValue": value}})
        elif isinstance(value, int) and not isinstance(value, bool):
            out.append({"name": str(name), "value": {"longValue": value}})
        elif isinstance(value, float):
            out.append({"name": str(name), "value": {"doubleValue": value}})
        else:
            out.append({"name": str(name), "value": {"stringValue": str(value)}})
    return out


def _bind_qmarks(sql: str, params: tuple) -> str:
    """Turn DuckDB-style ``?`` placeholders into :p0, :p1 for the Data API."""
    out, index = [], 0
    for ch in sql:
        if ch == "?":
            out.append(f":p{index}")
            index += 1
        else:
            out.append(ch)
    if index != len(params):
        raise SqlError(f"expected {index} SQL parameters, got {len(params)}")
    return "".join(out)


def execute(
    sql: str,
    params: tuple | dict | None = None,
    *,
    rds_client: Any | None = None,
    validate: bool = True,
) -> list[dict[str, Any]]:
    cfg = aws_config.load_config()
    if not cfg.aurora_cluster_arn or not cfg.aurora_secret_arn:
        raise SqlError("Aurora cluster/secret ARNs are not configured")
    statement = sql.strip()
    bound: tuple | dict | None = params
    if params is not None and not isinstance(params, dict) and "?" in statement:
        statement = _bind_qmarks(statement, tuple(params))
        bound = {f"p{i}": v for i, v in enumerate(params)}
    if validate:
        statement = validate_sql(statement)
    client = rds_client or _rds_client(cfg.region)
    try:
        response = client.execute_statement(
            resourceArn=cfg.aurora_cluster_arn,
            secretArn=cfg.aurora_secret_arn,
            database=cfg.aurora_database,
            sql=statement,
            includeResultMetadata=True,
            parameters=_sql_params(bound),
        )
    except Exception as exc:
        raise SqlError(f"RDS Data API failed: {exc}") from exc
    return _rows_from_response(response)


def schema_text() -> str:
    for path in _SCHEMA_CANDIDATES:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return (
        "Tables: loan.loan_static, loan.loan_monthly, loan.loan_features, "
        "loan.default_risk_screen."
    )


def fingerprint(*, rds_client: Any | None = None) -> str:
    rows = execute(
        "SELECT md5(concat("
        "COALESCE((SELECT string_agg(loan_id, ',' ORDER BY loan_id) FROM loan.loan_static), ''),"
        "':',"
        "COALESCE((SELECT string_agg(loan_identifier || ':' || COALESCE(period_ym,''), ',' "
        "ORDER BY loan_identifier, period_ym) FROM loan.loan_monthly), '')"
        ")) AS fp",
        rds_client=rds_client,
        validate=True,
    )
    if not rows:
        return ""
    return str(rows[0].get("fp") or "")
