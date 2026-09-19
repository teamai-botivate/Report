"""Explanation/Conversation Agent (CLAUDE.md Agents #9): intent classification
(ANALYSIS/REPORT_EDIT/DATA_PREVIEW/EXPLAIN_WHY/GREETING_OR_OTHER) + the final
natural-language chat reply, referencing only real computed numbers already
present in the ReportSpec — never inventing a new one.
"""
from __future__ import annotations

from typing import Any

from app.ai.openai_client import chat_completion, is_enabled, structured_completion
from app.schemas.report import ReportSpec

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["ANALYSIS", "REPORT_EDIT", "DATA_PREVIEW", "EXPLAIN_WHY", "GREETING_OR_OTHER"],
        },
    },
    "required": ["intent"],
    "additionalProperties": False,
}

INTENT_SYSTEM_PROMPT = """Classify a user chat message for a conversational BI platform into exactly one intent:
- ANALYSIS: a new business question needing fresh data/metrics/comparisons/reports (not a follow-up edit of the report already shown)
- REPORT_EDIT: asking to modify the CURRENTLY DISPLAYED report/chart with no fundamentally new question — e.g. "only top 5", "make it a line chart",
  "remove this chart", "add a revenue scorecard on top", "also compare with August", "rename it to X". Only valid if a report is currently active.
- DATA_PREVIEW: explicitly asking to see/preview the underlying data/rows (e.g. "give me the data", "show the table", "show me the rows")
- EXPLAIN_WHY: asking "why" something happened, a follow-up deep-dive needing genuinely new analysis
- GREETING_OR_OTHER: greetings, thanks, unrelated chit-chat
If no report is currently active, never return REPORT_EDIT — return ANALYSIS instead."""

EXPLAIN_SYSTEM_PROMPT = """You are the Explanation Agent inside an AI-native BI platform.
You are given a business question and the REAL computed report already shown to
the user (its title, KPI values, and insight sentences — already validated
from the database). Write a concise (2-4 sentence), business-friendly
natural-language answer referencing ONLY the figures given to you. Never
invent a number, table name, or SQL detail. If growth/comparison figures are
present, state direction (increase/decrease) and the percentage."""

_GREETING_WORDS = ("hi", "hello", "hey", "thanks", "thank you", "good morning", "good afternoon", "good evening")
_DATA_WORDS = ("data", "preview", "rows", "raw data", "underlying data")
_EDIT_VERBS = (
    "only", "make it", "change", "remove", "add", "also show", "also compare",
    "rename", "sort", "reorder", "put it", "move it", "instead", "top ",
)


def _heuristic_intent(message: str, has_active_report: bool) -> str:
    lowered = message.lower().strip()
    if any(lowered.startswith(w) or lowered == w for w in _GREETING_WORDS):
        return "GREETING_OR_OTHER"
    if lowered.startswith("why") or " why " in f" {lowered} ":
        return "EXPLAIN_WHY"
    if any(w in lowered for w in _DATA_WORDS):
        return "DATA_PREVIEW"
    if has_active_report and any(v in lowered for v in _EDIT_VERBS):
        return "REPORT_EDIT"
    return "ANALYSIS"


async def classify_intent(message: str, has_active_report: bool) -> str:
    if not is_enabled():
        return _heuristic_intent(message, has_active_report)

    user_prompt = f"Message: {message}\n\nA report is currently active: {has_active_report}"
    try:
        result = await structured_completion(
            system=INTENT_SYSTEM_PROMPT,
            user=user_prompt,
            schema_name="intent_classification",
            json_schema=INTENT_SCHEMA,
            temperature=0.0,
        )
        intent = result.get("intent", "ANALYSIS")
        if intent == "REPORT_EDIT" and not has_active_report:
            return "ANALYSIS"
        return intent
    except Exception:  # noqa: BLE001 - degrade to heuristic rather than failing the turn
        return _heuristic_intent(message, has_active_report)


def _report_context_text(report: ReportSpec) -> str:
    lines = [f"Report title: {report.title}"]
    if report.subtitle:
        lines.append(f"Subtitle: {report.subtitle}")
    for kpi in report.kpis:
        delta_text = f" ({kpi.delta:+.2f}% {kpi.delta_label or ''})" if kpi.delta is not None else ""
        lines.append(f"KPI - {kpi.label}: {kpi.value}{delta_text}")
    for insight in report.insights:
        lines.append(f"Insight: {insight.text}")
    return "\n".join(lines)


async def explain_result(question: str, report: ReportSpec) -> str:
    """Final natural-language chat reply. If AI is enabled, one chat_completion
    call whose prompt embeds only the ReportSpec's own KPI/insight values
    (never raw DB rows), so the model narrates real numbers without ever
    seeing (and being tempted to alter) the underlying dataset. If disabled,
    a deterministic templated sentence built from the report's title + first
    KPI/insight."""
    if not is_enabled():
        return _heuristic_explanation(question, report)

    user_prompt = f"User question: {question}\n\nReport (real, already-computed values):\n{_report_context_text(report)}"
    try:
        return await chat_completion(system=EXPLAIN_SYSTEM_PROMPT, user=user_prompt, temperature=0.3)
    except Exception:  # noqa: BLE001 - never fail the turn over the narration step
        return _heuristic_explanation(question, report)


def _heuristic_explanation(question: str, report: ReportSpec) -> str:
    """Deterministic templated sentence when AI is disabled."""
    if report.kpis:
        kpi = report.kpis[0]
        sentence = f"Here is {report.title.lower()}: {kpi.label} is {kpi.value}."
        if kpi.delta is not None:
            direction = "up" if (kpi.trend == "up") else ("down" if kpi.trend == "down" else "flat")
            sentence += f" That's {direction} {abs(kpi.delta):.2f}% {kpi.delta_label or ''}.".rstrip()
        return sentence
    if report.insights:
        return f"Here is {report.title.lower()}: {report.insights[0].text}"
    return f"Here is the report for: {question}"


__all__ = ["classify_intent", "explain_result"]
