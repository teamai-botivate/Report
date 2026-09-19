"""Deterministic (no-LLM) retrieval of the relevant slice of the semantic
layer for a natural-language question.

This is what keeps the AI from ever receiving the entire 62-table schema in
a prompt: `retrieve_relevant_metadata()` tokenizes the question and scores
each table/measure by keyword/synonym overlap, returning only the top-N
relevant tables (with their columns) and any matching measures.

Fully deterministic and unit-testable without any OpenAI key or database
connection: if `refresh_metadata_cache()` hasn't run yet in this process
(so `get_cached_metadata()` returns `{}`), this module lazily builds the
same structure directly from `dictionary.py` (+ `Base.metadata` if
importable) so tests can call it standalone.
"""
from __future__ import annotations

import re
from typing import Any

from app.semantic_layer import dictionary
from app.semantic_layer.metadata_cache import get_cached_metadata

_WORD_RE = re.compile(r"[a-z0-9']+")

# Generic English stopwords that carry no schema-matching signal. Kept small
# and hand-picked rather than pulling in an NLP dependency.
_STOPWORDS = {
    "a", "an", "the", "of", "for", "in", "on", "at", "to", "by", "with",
    "and", "or", "is", "are", "was", "were", "be", "been", "this", "that",
    "what", "which", "who", "whom", "show", "me", "us", "please", "give",
    "get", "list", "display", "find", "our", "my", "we", "i", "how",
    "many", "much", "do", "does", "did", "last", "this", "over", "per",
    "vs", "compare", "than", "also", "all", "top", "bottom",
}


def _tokenize(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1}


def _lazy_metadata() -> dict[str, Any]:
    """Return the cached metadata if `refresh_metadata_cache()` has already
    run, otherwise build the same structure on the fly from `dictionary.py`
    (+ `Base.metadata` reflection when the DB/session layer is importable).
    This makes `retrieve_relevant_metadata()` work standalone in unit tests
    with zero setup.
    """
    cached = get_cached_metadata()
    if cached:
        return cached

    # Reuse the exact same builder metadata_cache.py uses internally, so
    # retrieval never drifts from what refresh_metadata_cache() produces.
    from app.semantic_layer.metadata_cache import _build_metadata

    return _build_metadata()


def _table_score(question_tokens: set[str], table: dict[str, Any]) -> int:
    score = 0
    table_name = table["name"]

    # Exact/partial table-name match (e.g. "sales_orders" vs token "orders").
    name_words = set(table_name.split("_"))
    score += 3 * len(question_tokens & name_words)
    if table_name.replace("_", "") in question_tokens:
        score += 3

    # Synonym match (multi-word synonyms matched as substrings of the
    # original question via a second pass in the caller; here we match
    # single-word overlap plus a light multi-word check).
    for synonym in table.get("synonyms", []):
        syn_tokens = _tokenize(synonym)
        if syn_tokens and syn_tokens <= question_tokens:
            score += 4
        else:
            score += 2 * len(question_tokens & syn_tokens)

    # Description keyword overlap (lower weight — descriptions are prose).
    desc_tokens = _tokenize(table.get("description", ""))
    score += 1 * len(question_tokens & desc_tokens)

    # Column name / column-synonym overlap.
    for col_name in table.get("columns", []):
        col_words = set(col_name.split("_"))
        score += 2 * len(question_tokens & col_words)

    for col_name, col_info in table.get("column_descriptions", {}).items():
        for synonym in col_info.get("synonyms", []):
            syn_tokens = _tokenize(synonym)
            if syn_tokens and syn_tokens <= question_tokens:
                score += 3

    return score


def _measure_matches(question: str, question_tokens: set[str], measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched = []
    question_lower = question.lower()
    for measure in measures:
        hit = False
        name_tokens = _tokenize(measure["name"])
        if name_tokens <= question_tokens:
            hit = True
        for synonym in measure.get("synonyms", []):
            if synonym.lower() in question_lower:
                hit = True
                break
            syn_tokens = _tokenize(synonym)
            if syn_tokens and syn_tokens <= question_tokens:
                hit = True
                break
        if hit:
            matched.append(measure)
    return matched


def retrieve_relevant_metadata(question: str, max_tables: int = 6) -> dict[str, Any]:
    """Return a compact, question-relevant slice of the semantic layer.

    Deterministic, synchronous, and callable with no OpenAI key and no
    running event loop. Suitable for embedding directly into an LLM prompt
    without ever including the full schema.

    Returns:
        {
            "tables": [
                {"name": str, "description": str, "columns": [str, ...],
                 "primary_key": [...], "foreign_keys": [...]},
                ...
            ],
            "measures": [{"name", "expression", "format", "description"}, ...],
        }
    """
    metadata = _lazy_metadata()
    tables: dict[str, dict[str, Any]] = metadata.get("tables", {})
    measures: list[dict[str, Any]] = metadata.get("measures", [])

    question_tokens = _tokenize(question)

    scored = [
        (table_name, _table_score(question_tokens, table))
        for table_name, table in tables.items()
    ]
    scored = [(name, score) for name, score in scored if score > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    top_tables = [name for name, _score in scored[:max_tables]]

    # If the question clearly mentions time/period vocabulary, make sure the
    # calendar date-dimension table rides along even if it didn't score
    # highest, since date-based grouping/filtering needs it. Only add it
    # within the max_tables budget (never exceeding it).
    date_words = {"date", "dates", "month", "quarter", "year", "week", "today", "yesterday", "period", "fiscal"}
    if (
        "calendar_dates" in tables
        and "calendar_dates" not in top_tables
        and question_tokens & date_words
        and len(top_tables) < max_tables
    ):
        top_tables.append("calendar_dates")

    result_tables = []
    for name in top_tables:
        table = tables[name]
        result_tables.append(
            {
                "name": table["name"],
                "description": table["description"],
                "columns": table["columns"],
                "primary_key": table.get("primary_key", []),
                "foreign_keys": table.get("foreign_keys", []),
            }
        )

    matched_measures = _measure_matches(question, question_tokens, measures)

    return {"tables": result_tables, "measures": matched_measures}


async def retrieve_relevant_schema(session: Any = None, question: str = "", max_tables: int = 6) -> dict[str, Any]:
    """Backward-compatible async adapter for older callers (e.g.
    `app.agents.query_planner_agent`, `app.agents.sql_agent`) written
    against a previous DB-table-backed version of this module.

    Ignores `session` (the current metadata cache is in-process, not
    DB-backed — see `metadata_cache.py`) and simply adapts
    `retrieve_relevant_metadata()`'s result into the older shape those
    callers expect: `tables[i]` has `table_name`/`columns: [{"column_name"}]`,
    and measures are returned under the `matched_measures` key.
    """
    result = retrieve_relevant_metadata(question, max_tables=max_tables)
    tables = [
        {
            "table_name": t["name"],
            "module": "",
            "description": t["description"],
            "columns": [{"column_name": c} for c in t["columns"]],
        }
        for t in result["tables"]
    ]
    return {"tables": tables, "matched_measures": result["measures"], "relationships": []}
