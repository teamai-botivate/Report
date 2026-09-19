"""Report Edit Agent (CLAUDE.md Agents #8): handles follow-up conversational
edits to the report just shown. Distinguishes purely-structural edits
(reorder/remove/retype/rename/reformat — applied deterministically via
`apply_structural_operations`, no new query, cannot alter any existing value)
from edits that need new data (flagged `needs_requery=true` with a plain-
English description; the orchestrator runs a small follow-up query-plan
pipeline and merges the new real sections into the existing report).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from app.ai.openai_client import is_enabled, structured_completion
from app.schemas.report import ReportSpec

EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "needs_requery": {
            "type": "boolean",
            "description": "true if fulfilling this instruction requires querying data not already present in the current report",
        },
        "requery_description": {
            "type": "string",
            "description": "if needs_requery, a clear plain-English description of the additional data needed (empty string otherwise)",
        },
        "structural_ops": {
            "type": "array",
            "description": "structural edits to apply to the existing report (can be empty if this is a pure requery)",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "remove", "reorder", "retype", "rename", "limit_top_n", "set_format",
                        ],
                    },
                    "target_id": {"type": "string", "description": "id of the kpi/chart/table/report to target, or empty string for report-level rename"},
                    "value": {"type": "string", "description": "op-specific: new chart type, new row limit as a string, new title text, new format, or comma-separated ids for reorder"},
                },
                "required": ["op", "target_id", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["needs_requery", "requery_description", "structural_ops"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the Report Edit Agent inside an AI-native BI platform. The user is
looking at a generated business report and gives a follow-up instruction,
possibly referring to it with words like "this", "it", "that chart". You are
given the CURRENT report's structure (section ids, types, titles, row
counts — never full row data) and must decide how to satisfy the instruction.

If the instruction can be satisfied purely by rearranging/trimming/restyling
sections that ALREADY exist (e.g. "only top 5", "make it a line chart",
"remove this chart", "put the table first", "rename it to X", "show as
percentage"), return needs_requery=false and precise structural_ops:
  - limit_top_n: trims a chart/table's data to N rows (value = the number)
  - retype: changes a chart's rendering type (value = new chart type)
  - remove: drops a section entirely (target_id = that section's id)
  - reorder: sets the full new layout order (value = comma-separated ids)
  - rename: changes the report title (target_id empty) or a section's title
  - set_format: changes number formatting (value = currency/percentage/number/decimal)

If the instruction needs data NOT already in the report (e.g. "also compare
with August", "add a scorecard for total revenue", "show delayed orders
too"), return needs_requery=true and a clear plain-English description of
exactly what additional data is needed — never attempt to answer it yourself
or invent any numbers."""


def summarize_report_for_edit(report: dict) -> dict:
    """A compact, LLM-friendly summary of a ReportSpec dict — enough to
    reason about structure without re-sending every row of every chart/table
    (keeps prompts small)."""
    sections = []
    for kpi in report.get("kpis", []):
        sections.append({"id": kpi["id"], "kind": "kpi", "label": kpi.get("label"), "value": kpi.get("value")})
    for chart in report.get("charts", []):
        sections.append(
            {
                "id": chart["id"],
                "kind": "chart",
                "type": chart.get("type"),
                "title": chart.get("title"),
                "row_count": len(chart.get("data", [])),
            }
        )
    for table in report.get("tables", []):
        sections.append(
            {
                "id": table["id"],
                "kind": "table",
                "title": table.get("title"),
                "row_count": len(table.get("rows", [])),
            }
        )
    return {
        "title": report.get("title"),
        "subtitle": report.get("subtitle"),
        "sections": sections,
    }


_CHART_TYPE_WORDS = {
    "bar": "bar",
    "horizontal bar": "horizontal_bar",
    "line": "line",
    "area": "area",
    "pie": "pie",
    "donut": "donut",
    "scatter": "scatter",
    "funnel": "funnel",
    "gauge": "gauge",
    "heatmap": "heatmap",
}
_TOP_N_RE = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
_ONLY_N_RE = re.compile(r"\bonly\s+(\d+)\b", re.IGNORECASE)


def _heuristic_edit(instruction: str) -> dict:
    """Deterministic fallback used when AI is disabled: regex-detects common
    "top N" and chart-type-change phrasing. Anything it can't confidently
    classify is treated as needing a requery description equal to the raw
    instruction (which the orchestrator will only act on if AI later comes
    back on — with AI disabled entirely, the orchestrator's ai_disabled path
    is what actually governs behavior; this heuristic exists so
    report_edit_agent has a sane, testable degradation path of its own)."""
    lowered = instruction.lower()
    ops: list[dict[str, str]] = []

    n_match = _TOP_N_RE.search(lowered) or _ONLY_N_RE.search(lowered)
    if n_match:
        ops.append({"op": "limit_top_n", "target_id": "", "value": n_match.group(1)})

    for phrase, chart_type in _CHART_TYPE_WORDS.items():
        if phrase in lowered:
            ops.append({"op": "retype", "target_id": "", "value": chart_type})
            break

    rename_match = re.search(r"rename (?:it |this |the report )?to (.+)", lowered)
    if rename_match:
        ops.append({"op": "rename", "target_id": "", "value": rename_match.group(1).strip()})

    remove_words = ("remove", "delete", "drop")
    needs_requery = not ops and not any(w in lowered for w in remove_words)

    return {
        "needs_requery": needs_requery,
        "requery_description": instruction if needs_requery else "",
        "structural_ops": ops,
    }


async def edit_report(previous_report: dict, instruction: str) -> dict:
    """Classifies whether `instruction` is a pure structural edit or needs
    new data. Returns {"needs_requery": bool, "requery_description": str|None,
    "structural_ops": [...]}."""
    if not is_enabled():
        return _heuristic_edit(instruction)

    summary = summarize_report_for_edit(previous_report)
    user_prompt = f"User instruction: {instruction}\n\nCurrent report structure (JSON): {summary}"
    try:
        result = await structured_completion(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema_name="report_edit_plan",
            json_schema=EDIT_SCHEMA,
            temperature=0.1,
        )
    except Exception:  # noqa: BLE001 - degrade to heuristic rather than failing the edit turn
        return _heuristic_edit(instruction)

    return {
        "needs_requery": result.get("needs_requery", False),
        "requery_description": result.get("requery_description") or None,
        "structural_ops": result.get("structural_ops", []),
    }


def _find_section(report_dict: dict, target_id: str) -> tuple[str, dict] | tuple[None, None]:
    for kpi in report_dict.get("kpis", []):
        if kpi.get("id") == target_id:
            return "kpi", kpi
    for chart in report_dict.get("charts", []):
        if chart.get("id") == target_id:
            return "chart", chart
    for table in report_dict.get("tables", []):
        if table.get("id") == target_id:
            return "table", table
    return None, None


def _layout_ids(layout: list) -> list[str]:
    """layout entries are {"type":..., "id":...} dicts; tolerate plain ids too."""
    ids = []
    for entry in layout:
        if isinstance(entry, dict):
            ids.append(entry.get("id"))
        else:
            ids.append(entry)
    return ids


def apply_structural_operations(report: ReportSpec | dict, ops: list[dict]) -> ReportSpec:
    """Deterministically applies structural operations to an existing
    ReportSpec's charts/tables/kpis WITHOUT altering any underlying data
    value — only structure/presentation. Accepts a ReportSpec or an
    equivalent dict; always returns a ReportSpec."""
    report_dict = report.model_dump() if isinstance(report, ReportSpec) else copy.deepcopy(report)
    layout_by_id = {entry.get("id") if isinstance(entry, dict) else entry: entry for entry in report_dict.get("layout", [])}

    for op in ops:
        op_name = op.get("op")
        target_id = op.get("target_id", "")
        value = op.get("value", "")

        if op_name == "reorder" and value:
            wanted_ids = [i.strip() for i in value.split(",") if i.strip()]
            existing_ids = set(_layout_ids(report_dict.get("layout", [])))
            new_layout = [layout_by_id[i] for i in wanted_ids if i in existing_ids and i in layout_by_id]
            if new_layout:
                report_dict["layout"] = new_layout
            continue

        if op_name == "rename":
            if not target_id:
                report_dict["title"] = value or report_dict.get("title")
            else:
                kind, obj = _find_section(report_dict, target_id)
                if obj is not None:
                    if "title" in obj:
                        obj["title"] = value or obj["title"]
                    elif "label" in obj:
                        obj["label"] = value or obj["label"]
            continue

        kind, obj = _find_section(report_dict, target_id)
        if obj is None:
            continue

        if op_name == "remove":
            if kind == "kpi":
                report_dict["kpis"] = [k for k in report_dict["kpis"] if k["id"] != target_id]
            elif kind == "chart":
                report_dict["charts"] = [c for c in report_dict["charts"] if c["id"] != target_id]
            elif kind == "table":
                report_dict["tables"] = [t for t in report_dict["tables"] if t["id"] != target_id]
            report_dict["layout"] = [
                entry for entry in report_dict.get("layout", [])
                if (entry.get("id") if isinstance(entry, dict) else entry) != target_id
            ]

        elif op_name == "retype" and kind == "chart":
            obj["type"] = value or obj["type"]

        elif op_name == "limit_top_n":
            try:
                n = int(value)
            except (TypeError, ValueError):
                continue
            if kind == "chart":
                obj["data"] = obj["data"][:n]
            elif kind == "table":
                obj["rows"] = obj["rows"][:n]

        elif op_name == "set_format" and value in ("currency", "percentage", "number", "decimal"):
            if kind in ("kpi", "chart"):
                obj["format"] = value
            elif kind == "table":
                pass  # table columns carry per-column format; whole-table reformat is out of scope here

    return ReportSpec(**report_dict)


__all__ = ["edit_report", "apply_structural_operations", "summarize_report_for_edit"]
