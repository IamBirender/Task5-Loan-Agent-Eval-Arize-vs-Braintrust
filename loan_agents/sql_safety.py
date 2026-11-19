"""Read-only SQL validation (same conservative checks as the AgentCore sample)."""
from __future__ import annotations

import re

_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
    "GRANT", "REVOKE", "BEGIN", "COMMIT", "ROLLBACK",
)
_ALLOWED_LEADING_KEYWORDS = ("SELECT", "WITH")
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_WITH_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)

SYSTEM_PROMPT_TEMPLATE = """You are a read-only SQL assistant for the Fannie Mae loan sample.
Translate the user's natural-language question into a single PostgreSQL SELECT
statement against the schema below. Follow these rules without exception:

* Return ONLY the SQL statement. Do not wrap it in markdown fences, do not
  explain, do not prepend "SQL:" or any label.
* The statement MUST begin with SELECT or WITH. Do not emit INSERT, UPDATE,
  DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, REVOKE, BEGIN, COMMIT, or
  ROLLBACK.
* The statement MUST reference only the loan schema objects defined below.
* Use explicit column lists rather than SELECT * when practical.
* Apply sensible LIMITs (default 50) when the user does not specify one.
* Do not use parameter placeholders; inline literals are acceptable because
  the RDS Data API quotes them on execution.

Schema:
{schema}
""".strip()


class TextToSqlError(RuntimeError):
    """Raised when generated SQL is empty, mutating, or otherwise unsafe."""


def _strip_comments(sql: str) -> str:
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", sql))


def _first_keyword(sql: str) -> str:
    stripped = sql.lstrip().lstrip("(").lstrip()
    match = re.match(r"[A-Za-z_]+", stripped)
    return match.group(0).upper() if match else ""


def validate_sql(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise TextToSqlError("SQL must be a non-empty string")
    stripped = _strip_comments(sql).strip()
    if not stripped:
        raise TextToSqlError("SQL is empty after stripping comments")
    trimmed = stripped.rstrip().rstrip(";").rstrip()
    if ";" in trimmed:
        raise TextToSqlError("SQL must not contain multiple statements")
    leading = _first_keyword(trimmed)
    if leading not in _ALLOWED_LEADING_KEYWORDS:
        raise TextToSqlError(
            f"Only SELECT/WITH statements are allowed (got {leading or '<empty>'})"
        )
    if leading == "WITH" and not _WITH_SELECT_RE.search(trimmed):
        raise TextToSqlError("WITH statements must ultimately SELECT")
    upper = trimmed.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise TextToSqlError(f"SQL contains forbidden keyword: {keyword}")
    return trimmed


def normalise_generated_sql(text: str) -> str:
    sql = (text or "").strip()
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.I)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip()
