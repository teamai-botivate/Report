"""Query Planner Agent (CLAUDE.md Agents #3): turns a natural-language question
(+ retrieved semantic metadata + optional conversation context) into a
QueryPlan DAG (app/query_engine/plan.py). A single user turn may require
several distinct queries — some independent (run in parallel), some
dependent on another node's result (e.g. "growth vs last month" needs both
months' totals before a delta can be computed). See CLAUDE.md "Pipeline for
a turn" and prompt.txt section 8 (multi-query DAG example).

Structured-output JSON schema keeps the LLM from returning free-form text
we'd have to parse heuristically (prompt.txt section 7).
"""
from __future__ import annotations

import uuid
from typing import Any

from app.ai.openai_client import is_enabled, structured_completion
from app.query_engine.plan import QueryPlan, QueryPlanNode
from app.semantic_layer.retrieval import retrieve_relevant_schema

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "description": (
                "One entry per distinct SQL query needed to answer the question. "
                "Prefer several small, clear nodes over one giant query."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "short unique id, e.g. q1, q2"},
                    "description": {
                        "type": "string",
                        "description": "plain-English description of exactly what this node computes, e.g. 'September 2026 total revenue'",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "ids of nodes this node needs results from first; empty for independent nodes (most nodes)",
                    },
                },
                "required": ["id", "description", "depends_on"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["nodes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the Query Planner Agent inside an AI-native BI platform.

Given a user's business question and a relevant slice of database schema/measure
metadata, break the question into one or more analytical query nodes that
together answer the full question. Example: "Compare September sales revenue
with purchase value, show growth compared to August, list top 5 customers and
show delayed orders" should become separate nodes for September revenue,
September purchase value, August revenue, August purchase value, top 5
customers, and delayed orders — not one giant query.

Use `depends_on` only when a node genuinely cannot be computed until another
node's result is known (this is rare — most nodes can run independently in
parallel; a plain period-over-period comparison does NOT need depends_on,
since both periods can be queried independently and compared afterwards in
Python). Only reference tables/columns/measures present in the provided
schema context. Do not write SQL here — only describe each node in plain
English; the SQL Generation Agent will turn each description into a query
later, once you're done."""


def _heuristic_plan(question: str) -> QueryPlan:
    """Deterministic single-node fallback used when AI is disabled. The
    orchestrator's ai_disabled path never actually executes this (SQL
    generation itself requires AI — see CLAUDE.md), but plan_queries must
    still degrade gracefully rather than raising, in case a future zero-LLM
    caller (e.g. a recommended-report variant) wants a plan shape without SQL."""
    return QueryPlan(nodes=[QueryPlanNode(id="q1", description=question, depends_on=[])])


async def plan_queries(
    question: str,
    conversation_context: list[dict] | None = None,
    *,
    session=None,
) -> QueryPlan:
    """Retrieve relevant semantic metadata for the question, then (if AI is
    enabled) ask the LLM to decide how many distinct queries are needed and
    their dependencies. Falls back to a single-node heuristic plan if AI is
    disabled.

    `session` is an optional AsyncSession used for semantic metadata
    retrieval (app.semantic_layer.retrieval.retrieve_relevant_schema needs a
    DB session to read the metadata cache tables). If not supplied, schema
    retrieval is skipped and the planner falls back to describing the whole
    question as context-free (still works, just less targeted).
    """
    if not is_enabled():
        return _heuristic_plan(question)

    # retrieve_relevant_schema is deterministic and cache-backed — it does not
    # actually require a live DB session (the `session` arg is accepted only
    # for backward compatibility and ignored internally) — so this must run
    # unconditionally rather than being gated behind `session is not None`.
    # Gating it that way meant every real call from the API layer (which
    # never passes a session) silently retrieved zero metadata, and the SQL
    # Generation Agent downstream had no real table/column names to ground
    # its output in — verified live against a real OpenAI key to cause
    # hallucinated nonexistent table names. See orchestrator.py for the
    # matching fix.
    schema_context: dict[str, Any] = {}
    try:
        schema_context = await retrieve_relevant_schema(session, question)
    except Exception:  # noqa: BLE001 - metadata retrieval must never block planning
        schema_context = {}

    context_text = ""
    if conversation_context:
        context_text = "\n".join(
            f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in conversation_context[-6:]
        )

    user_prompt = (
        f"User question: {question}\n\n"
        f"Conversation context (may be empty):\n{context_text}\n\n"
        f"Relevant schema/measures (JSON): {schema_context}"
    )

    try:
        result = await structured_completion(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema_name="query_plan",
            json_schema=PLAN_SCHEMA,
            temperature=0.1,
        )
        nodes = [
            QueryPlanNode(
                id=n["id"],
                description=n["description"],
                depends_on=n.get("depends_on", []),
            )
            for n in result.get("nodes", [])
        ]
        if not nodes:
            return _heuristic_plan(question)
        return QueryPlan(nodes=nodes)
    except Exception:  # noqa: BLE001 - planning failure degrades to a single node, never crashes the turn
        return _heuristic_plan(question)


__all__ = ["plan_queries"]
