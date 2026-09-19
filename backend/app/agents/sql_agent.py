"""SQL Generation Agent (CLAUDE.md Agents #4): turns one QueryPlanNode's plain-
English description + a relevant metadata slice into ONE SELECT statement.

The generated SQL is NOT trusted yet — every string returned here still must
pass through app/security/sql_guard.py (sqlglot AST allowlist + table check +
row-limit injection) before it is ever executed; that gate is enforced by the
executor (app/query_engine/executor.py), not here.

Portability note: SQLite is the dev/test engine (see CLAUDE.md "Database
(dev/test)"), while production targets Postgres/Neon. The prompt below asks
for SQLite-compatible, portable ANSI-ish SQL and explicitly avoids
Postgres-only syntax (e.g. ILIKE, ::type casts, ->>/jsonb operators) so the
same generated query works unchanged against both engines during local dev
and production — this is a deliberate tradeoff: a handful of advanced
Postgres-only functions are simply off the table for AI-generated SQL in
favor of one portable code path.
"""
from __future__ import annotations

from typing import Any

from app.ai.openai_client import is_enabled, structured_completion
from app.query_engine.plan import QueryPlanNode

SQL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "A single valid read-only SELECT statement, no trailing semicolon needed",
        },
    },
    "required": ["sql"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the SQL Generation Agent inside an AI-native BI platform.

Generate exactly ONE safe, read-only SQL SELECT statement that answers the
given query-plan node, using ONLY the tables/columns present in the provided
metadata context — never invent a table or column name.

Portability rules (this must run unmodified on both SQLite and PostgreSQL):
- Prefer ANSI-standard SQL. Avoid Postgres-only syntax such as ILIKE, ::type
  casts, jsonb operators, or DISTINCT ON.
- NEVER use engine-specific relative-date functions — these are NOT portable
  and will fail on whichever engine you didn't test against: no SQLite-style
  DATE('now', 'start of month', '-1 month')/julianday/strftime, and no
  Postgres-style CURRENT_DATE - INTERVAL '1 month'/date_trunc/EXTRACT. For
  "this month" / "last month" / "this week" / any relative-period logic, join
  against the `calendar_dates` table instead (one row per calendar day, with
  precomputed year/quarter/month/week_of_year/fiscal_year columns) and filter
  by comparing those integer columns to the row for CURRENT_DATE, e.g.:
    JOIN calendar_dates cd ON cd.date = <table>.<date_column>
    WHERE cd.year = (SELECT year FROM calendar_dates WHERE date = CURRENT_DATE)
      AND cd.month = (SELECT month FROM calendar_dates WHERE date = CURRENT_DATE)
  For "last month", compare against a month/year pair computed the same way
  (e.g. via a second calendar_dates lookup keyed off month arithmetic done in
  the WHERE clause with plain integer comparisons on year/month, not a
  relative-date function). For any other date filtering, prefer simple >=/<
  comparisons against literal date strings ('YYYY-MM-DD').
- Use standard JOIN syntax and GROUP BY/ORDER BY.

Safety rules (hard requirements, this is enforced separately but must hold):
- Exactly one statement. No trailing semicolon needed.
- SELECT only — never INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE.
- Never reference a table or column not present in the metadata context.
- Include a LIMIT clause (<=500) for any query that can return many rows;
  omit it only for a genuine single-row aggregate.

Column selection — select ONLY what the question actually needs, never
`SELECT *` and never every column of a joined table "just in case": if the
question asks about delivery delays and purchase value, select the
supplier/entity name plus the specific delay/value metrics, not every
contact/profile column (email, phone, rating, is_active, etc.) that table
happens to have. A wide, unfocused result set renders as a cluttered,
hard-to-read table in the final report — keep it to the identifying column(s)
plus the metric(s) the question is actually about, typically 3-6 columns.

Return only the SQL text in the `sql` field."""


def _metadata_prompt(metadata_context: dict) -> str:
    tables = metadata_context.get("tables", [])
    measures = metadata_context.get("matched_measures", [])
    relationships = metadata_context.get("relationships", [])
    lines = ["Available tables and columns:"]
    for t in tables:
        cols = ", ".join(c.get("column_name", "") for c in t.get("columns", []))
        lines.append(f"- {t.get('table_name')} ({t.get('module', '')}): {cols}")
    if measures:
        lines.append("\nRelevant business measures:")
        for m in measures:
            lines.append(f"- {m.get('name')}: {m.get('expression')} (format: {m.get('format')})")
    if relationships:
        lines.append("\nRelationships:")
        for r in relationships:
            lines.append(
                f"- {r.get('from_table')}.{r.get('from_column')} -> {r.get('to_table')}.{r.get('to_column')}"
            )
    return "\n".join(lines)


async def generate_sql(node: QueryPlanNode, metadata_context: dict) -> str:
    """One structured_completion call turning a node's description into one
    SELECT statement. Raises RuntimeError if AI is disabled (there is no
    deterministic NL->SQL fallback; the heuristic/recommended-report path
    bypasses SQL generation entirely by using hand-written SQL instead —
    see app/reports/recommended.py, owned by a different agent)."""
    if not is_enabled():
        raise RuntimeError(
            "AI is disabled: cannot generate SQL from a natural-language description "
            "without an OPENAI_API_KEY. Use a recommended report (zero-LLM, hand-written "
            "SQL) instead — see app/reports/recommended.py."
        )

    user_prompt = (
        f"Query node description: {node.description}\n\n"
        f"{_metadata_prompt(metadata_context)}"
    )
    result = await structured_completion(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        schema_name="sql_generation",
        json_schema=SQL_SCHEMA,
        temperature=0.0,
    )
    return result["sql"]


async def regenerate_sql(node: QueryPlanNode, error_message: str, metadata_context: dict) -> str:
    """Error-recovery path (prompt.txt section 25): given the previous SQL
    attempt and the execution/validation error, ask for a corrected query.
    This is the exact async signature expected by
    app.query_engine.executor.execute_plan's `regenerate` callback:
    (node, error_message) -> corrected_sql_string. Retries are bounded by
    SQL_MAX_RETRY in the executor — this function never loops itself.
    """
    if not is_enabled():
        raise RuntimeError(
            "AI is disabled: cannot regenerate SQL without an OPENAI_API_KEY."
        )

    user_prompt = (
        f"Query node description: {node.description}\n\n"
        f"{_metadata_prompt(metadata_context)}\n\n"
        f"Previous SQL attempt that failed:\n{node.sql or ''}\n\n"
        f"Error message:\n{error_message}\n\n"
        "Generate a corrected single SELECT statement that fixes this error, "
        "still following all the same portability and safety rules."
    )
    result = await structured_completion(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        schema_name="sql_generation_retry",
        json_schema=SQL_SCHEMA,
        temperature=0.0,
    )
    return result["sql"]


__all__ = ["generate_sql", "regenerate_sql"]
