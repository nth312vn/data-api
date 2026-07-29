import pytest

from app.services.query_engine.sql_safety import DynamicSqlError, SqlSafetyValidator


@pytest.mark.parametrize(
    ("sql", "parameters"),
    [
        ("SELECT 1", frozenset()),
        (
            "WITH regional AS ("
            "SELECT customer_id FROM sales WHERE region = :region"
            ") SELECT customer_id FROM regional WHERE customer_id <> :customer_id",
            frozenset({"region", "customer_id"}),
        ),
        (
            "SELECT customer_id, row_number() OVER (ORDER BY customer_id) AS rank "
            "FROM sales WHERE region = :region OR backup_region = :region",
            frozenset({"region"}),
        ),
        (
            "SELECT note FROM sales WHERE note = 'DROP TABLE sales'",
            frozenset(),
        ),
    ],
)
def test_validator_accepts_read_only_selects(
    sql: str,
    parameters: frozenset[str],
) -> None:
    result = SqlSafetyValidator().validate(sql)

    assert result.parameter_names == parameters
    assert result.canonical_sql
    assert not hasattr(result, "original_sql")


def test_validator_removes_comments_from_canonical_sql() -> None:
    result = SqlSafetyValidator().validate(
        "SELECT customer_id /* private ticket reference */ FROM sales -- comment"
    )

    assert "comment" not in result.canonical_sql
    assert "ticket" not in result.canonical_sql


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "SELECT FROM",
        "SELECT 1; SELECT 2",
        "SELECT 1; DELETE FROM sales",
        "INSERT INTO sales VALUES (1)",
        "UPDATE sales SET region = 'EU'",
        "DELETE FROM sales",
        "MERGE INTO sales USING staged ON sales.id = staged.id "
        "WHEN MATCHED THEN DELETE",
        "CREATE TABLE sales_copy AS SELECT * FROM sales",
        "DROP TABLE sales",
        "ALTER TABLE sales ADD COLUMN note VARCHAR",
        "TRUNCATE TABLE sales",
        "CALL refresh_sales()",
        "EXECUTE prepared_query",
        "SET SESSION query_max_run_time = '1m'",
        "USE catalog.schema",
        "GRANT SELECT ON sales TO analyst",
        "REVOKE SELECT ON sales FROM analyst",
        "SHOW TABLES",
        "DESCRIBE sales",
        "EXPLAIN SELECT * FROM sales",
        "VALUES (1)",
        "TABLE sales",
        "WITH x AS (SELECT 1) DELETE FROM sales",
        "SELECT\u0000 1",
        "SELECT\u0008 1",
        "SELECT\u001f 1",
        "SELECT\u007f 1",
        "SELECT\u200b 1",
        "SELECT\u200e 1",
        "SELECT\u202e 1",
        "SELECT\u2066 1",
        "SELECT\ufeff 1",
    ],
)
def test_validator_rejects_non_select_or_unsafe_sql(sql: str) -> None:
    with pytest.raises(DynamicSqlError) as exc_info:
        SqlSafetyValidator().validate(sql)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code.startswith("dynamic_sql_")


def test_validator_rejects_invalid_placeholder_name() -> None:
    with pytest.raises(DynamicSqlError) as exc_info:
        SqlSafetyValidator().validate("SELECT * FROM sales WHERE id = :1bad")

    assert exc_info.value.code == "dynamic_sql_invalid_parameter"
