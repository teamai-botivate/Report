"""SQL safety gate tests: every spec-mandated attack string must be rejected, and
legitimate SELECT statements must be accepted with a row-limit injected.
See CLAUDE.md "SQL safety gate" and prompt.txt sections 9 and 42.
"""
from __future__ import annotations

import pytest

from app.security.sql_guard import validate_sql, validate_sql_safe, SQLValidationError

ATTACK_STRINGS = [
    "DROP TABLE customers",
    "DELETE FROM customers",
    "UPDATE customers SET name = 'x'",
    "INSERT INTO customers (name) VALUES ('x')",
    "ALTER TABLE customers ADD COLUMN hacked INT",
    "TRUNCATE TABLE customers",
    "CREATE TABLE evil (id INT)",
    "GRANT ALL PRIVILEGES ON customers TO public",
    "REVOKE ALL PRIVILEGES ON customers FROM public",
    "SELECT * FROM customers; DROP TABLE customers;",
    "SELECT * FROM customers WHERE id = 1; DELETE FROM customers WHERE 1=1;",
    "select * from customers; update customers set name='x';",
    "  drop   table   customers  ",  # whitespace / case variance
]


@pytest.mark.parametrize("attack_sql", ATTACK_STRINGS)
def test_attack_strings_are_rejected(attack_sql: str) -> None:
    result = validate_sql_safe(attack_sql)
    assert result.ok is False
    assert result.code is not None

    with pytest.raises(SQLValidationError):
        validate_sql(attack_sql)


LEGITIMATE_QUERIES = [
    "SELECT id, name FROM customers",
    "SELECT id, name FROM customers WHERE id = 1",
    "SELECT c.id, SUM(i.total_amount) AS revenue FROM customers c "
    "JOIN sales_invoices i ON i.customer_id = c.id GROUP BY c.id ORDER BY revenue DESC LIMIT 10",
    "SELECT COUNT(*) FROM sales_orders WHERE status = 'delivered'",
    "SELECT * FROM (SELECT id FROM customers) sub",
    "WITH recent AS (SELECT * FROM sales_orders) SELECT * FROM recent",
]


@pytest.mark.parametrize("sql", LEGITIMATE_QUERIES)
def test_legitimate_selects_are_accepted(sql: str) -> None:
    result = validate_sql(sql)
    assert result.ok is True
    assert result.sql.strip().upper().startswith(("SELECT", "WITH"))
    assert "LIMIT" in result.sql.upper()


def test_row_limit_is_clamped_down() -> None:
    result = validate_sql("SELECT * FROM customers LIMIT 999999999", max_rows=100)
    assert "LIMIT 100" in result.sql


def test_row_limit_is_injected_when_absent() -> None:
    result = validate_sql("SELECT * FROM customers", max_rows=250)
    assert "LIMIT 250" in result.sql


def test_existing_small_limit_is_preserved() -> None:
    result = validate_sql("SELECT * FROM customers LIMIT 5", max_rows=1000)
    assert "LIMIT 5" in result.sql


def test_where_clause_literals_are_not_corrupted() -> None:
    """Regression test: an earlier bug in LIMIT injection (using exp.Limit(this=...)
    instead of exp.Limit(expression=...)) corrupted unrelated WHERE-clause literals."""
    result = validate_sql("SELECT id FROM customers WHERE id = 1")
    assert "WHERE id = 1" in result.sql
    assert "15000" not in result.sql


def test_unknown_table_is_rejected_when_known_tables_given() -> None:
    result = validate_sql_safe("SELECT * FROM secret_table", known_tables={"customers", "sales_orders"})
    assert result.ok is False
    assert result.code == "unknown_table"


def test_empty_sql_is_rejected() -> None:
    result = validate_sql_safe("")
    assert result.ok is False


def test_non_select_dml_wrapped_in_cte_is_rejected() -> None:
    result = validate_sql_safe("WITH x AS (SELECT 1) DELETE FROM customers")
    assert result.ok is False
