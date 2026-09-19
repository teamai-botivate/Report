"""SQL safety gate for all AI-generated queries.

Every AI-generated SQL string MUST pass through `validate_sql()` before it is ever
executed. Pipeline: Generate -> Parse -> Validate -> Safety Check -> Execute ->
Validate Result (see CLAUDE.md "Read-only SQL execution").

This module never executes SQL itself — it only parses with sqlglot and inspects
the AST. Execution happens in app/query_engine/executor.py against the read-only
engine, after this gate passes.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.core.logging_config import audit_logger, sql_logger
from app.core.config import get_settings

settings = get_settings()

# Statement types that are NEVER allowed, regardless of dialect.
_FORBIDDEN_EXPR_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Grant,
    exp.Merge,
    exp.Attach,
    exp.Command,  # catches dialect-specific DDL/admin statements sqlglot can't otherwise classify
    exp.Transaction,
    exp.Pragma,
)

# Keyword-level defense in depth in case sqlglot parses something unexpected as benign.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|EXEC|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)

# A semicolon followed by more non-whitespace content indicates statement chaining.
_MULTI_STATEMENT_RE = re.compile(r";\s*\S")


class SQLValidationError(ValueError):
    def __init__(self, reason: str, code: str = "invalid_sql"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass
class SQLValidationResult:
    ok: bool
    sql: str
    original_sql: str
    reason: str | None = None
    code: str | None = None
    tables_referenced: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def _check_single_statement(sql: str) -> None:
    if _MULTI_STATEMENT_RE.search(sql):
        raise SQLValidationError("Multiple statements are not allowed (statement chaining detected).", "multi_statement")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:  # noqa: BLE001 - surfaced as validation failure
        raise SQLValidationError(f"SQL failed to parse: {exc}", "parse_error") from exc
    non_empty = [s for s in statements if s is not None]
    if len(non_empty) != 1:
        raise SQLValidationError("Exactly one SQL statement is required.", "multi_statement")


def _check_keywords(sql: str) -> None:
    match = _FORBIDDEN_KEYWORDS.search(sql)
    if match:
        raise SQLValidationError(f"Forbidden keyword detected: {match.group(0).upper()}", "forbidden_keyword")


def _check_ast(tree: exp.Expression) -> None:
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise SQLValidationError(
            f"Only SELECT statements are allowed (got {type(tree).__name__}).", "not_select"
        )
    for node in tree.walk():
        node_expr = node[0] if isinstance(node, tuple) else node
        if isinstance(node_expr, _FORBIDDEN_EXPR_TYPES):
            raise SQLValidationError(
                f"Forbidden SQL construct detected: {type(node_expr).__name__}", "forbidden_construct"
            )


def _extract_tables(tree: exp.Expression) -> list[str]:
    tables = set()
    for table in tree.find_all(exp.Table):
        if table.name:
            tables.add(table.name.lower())
    return sorted(tables)


def _inject_row_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    """Force a LIMIT <= max_rows on the outermost SELECT/UNION."""
    existing_limit = tree.args.get("limit")
    if existing_limit is not None:
        try:
            current = int(existing_limit.expression.this)
            if current > max_rows:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        except (AttributeError, TypeError, ValueError):
            tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    else:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return tree


def validate_sql(
    sql: str,
    *,
    max_rows: int | None = None,
    known_tables: set[str] | None = None,
    dialect: str = "postgres",
) -> SQLValidationResult:
    """Validate an AI-generated SQL string and return a safe-to-execute version.

    Raises SQLValidationError on any violation. On success, returns a
    SQLValidationResult with `.sql` containing the (possibly LIMIT-injected) query.
    """
    start = time.perf_counter()
    max_rows = max_rows or settings.SQL_MAX_ROWS
    original_sql = sql
    cleaned = _strip_trailing_semicolon(sql)

    if not cleaned:
        raise SQLValidationError("Empty SQL.", "empty")

    _check_keywords(cleaned)
    _check_single_statement(cleaned)

    try:
        tree = sqlglot.parse_one(cleaned, read=dialect)
    except Exception as exc:  # noqa: BLE001
        raise SQLValidationError(f"SQL failed to parse: {exc}", "parse_error") from exc

    _check_ast(tree)

    tables = _extract_tables(tree)
    if known_tables is not None:
        unknown = [t for t in tables if t.lower() not in known_tables]
        if unknown:
            raise SQLValidationError(
                f"Query references unknown table(s): {', '.join(unknown)}", "unknown_table"
            )

    safe_tree = _inject_row_limit(tree, max_rows)
    safe_sql = safe_tree.sql(dialect=dialect)

    elapsed_ms = (time.perf_counter() - start) * 1000
    result = SQLValidationResult(
        ok=True,
        sql=safe_sql,
        original_sql=original_sql,
        tables_referenced=tables,
        elapsed_ms=elapsed_ms,
    )
    sql_logger.info("SQL validated ok tables=%s elapsed_ms=%.2f", tables, elapsed_ms)
    audit_logger.info("SQL_VALIDATE_OK sql=%r tables=%s", safe_sql, tables)
    return result


def validate_sql_safe(sql: str, **kwargs) -> SQLValidationResult:
    """Non-raising variant: returns a SQLValidationResult with ok=False on failure."""
    try:
        return validate_sql(sql, **kwargs)
    except SQLValidationError as exc:
        audit_logger.warning("SQL_VALIDATE_REJECT sql=%r reason=%s code=%s", sql, exc.reason, exc.code)
        return SQLValidationResult(ok=False, sql=sql, original_sql=sql, reason=exc.reason, code=exc.code)
