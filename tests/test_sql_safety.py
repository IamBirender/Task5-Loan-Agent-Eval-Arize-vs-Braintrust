from loan_agents.sql_safety import TextToSqlError, validate_sql


def test_validate_sql_allows_select():
    assert validate_sql("SELECT loan_id FROM loan_static LIMIT 10") == "SELECT loan_id FROM loan_static LIMIT 10"


def test_validate_sql_blocks_drop():
    try:
        validate_sql("SELECT 1; DROP TABLE loan_static")
    except TextToSqlError as exc:
        assert "multiple statements" in str(exc).lower() or "DROP" in str(exc)
    else:
        raise AssertionError("expected TextToSqlError")


def test_validate_sql_blocks_update():
    try:
        validate_sql("UPDATE loan_monthly SET current_actual_upb = 1")
    except TextToSqlError as exc:
        assert "UPDATE" in str(exc) or "SELECT" in str(exc)
    else:
        raise AssertionError("expected TextToSqlError")
