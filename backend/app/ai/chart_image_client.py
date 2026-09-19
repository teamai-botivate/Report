"""Whole-report image generation client (2026-09-19, single-image revision).

IMPORTANT — this module implements a deliberate, explicitly-confirmed
reversal of a previously "locked in" architectural rule, not an oversight.

CLAUDE.md's original "Charts" stack decision stated:
    "Charts: rendered client-side from structured `visualization` JSON + real
    row data returned by the backend. No image-generation model ever touches
    chart pixels."

That rule was first superseded earlier the same day (2026-09-19) by a
per-section approach: one AI-generated image per KPI card, per chart, and per
table (`generate_kpi_image`/`generate_chart_image`/`generate_table_image`,
orchestrated by `attach_report_images`). Live testing then surfaced a real
problem with that approach: when one section's image generation failed (e.g.
a delayed-orders table with up to 500 rows), the frontend fell back to a
plain scrollable HTML table for just that section, producing a report that
mixed polished AI images with a jarring scrolling-HTML-table section — visibly
inconsistent.

THIS REVISION replaces the per-section approach with ONE image for the ENTIRE
report (`generate_full_report_image`): title, all KPIs, all charts, all
tables, and all insights are described in a single prompt and rendered as one
picture via `settings.OPENAI_IMAGE_MODEL` (gpt-image-2). There is no more
mixing — a report is either ONE cohesive AI image, or (if image generation is
disabled/fails) the existing full multi-section ECharts/DOM layout, never a
blend of the two. See `ReportSpec.report_image_url` in `app/schemas/report.py`
and `ReportCanvas.tsx` on the frontend for the report-level (not per-item)
switch.

The old per-item functions (`generate_kpi_image`, `generate_chart_image`,
`generate_table_image`, `attach_report_images`) are kept below, unused by the
live report-generation path, in case per-section generation is wanted again
later — nothing in `report_agent.py` or `reports/recommended.py` calls them
anymore.

ACCURACY IS NOT GUARANTEED — more so now than before. Image generation is not
a deterministic, per-pixel-verifiable rendering path the way ECharts is: the
model draws the numbers/labels into the image itself, and there is no
code-level guarantee that every digit, label, bar length, or row value in the
resulting picture exactly matches the real data it was given. Packing an
entire report's worth of KPIs/charts/tables into ONE image multiplies the
number of real values the image model must reproduce verbatim in a single
generation call, which increases (not decreases) the surface area for a
misread digit or mislabeled bar relative to the old one-image-per-item
approach. This directly conflicts with this project's own stated "AI must
never fabricate a business number" principle and its automated-testing
guarantees for chart output specifically. The user was told this in plain
terms — including this specific "one image now carries far more numbers"
tradeoff — and chose to proceed anyway. Do not "fix" this by silently
reverting to ECharts-only rendering, and do not re-litigate the decision —
implement it well and let the ECharts/DOM fallback carry the accuracy
guarantee only for the disabled/failure case.

What is UNCHANGED and still fully guaranteed:
  - The KPI/chart/table DATA ITSELF still comes only from real, validated,
    executed SQL query results (see report_agent._materialize_report) — this
    module never invents, adjusts, or receives anything other than that
    already-materialized data. It only formats that real data into a prompt
    and asks the image model to depict it visually.
  - The existing decorative-only `generate_decorative_image()` function in
    `app/ai/image_client.py` is untouched: it remains a separate, narrower,
    non-data-bearing function for report banners.
  - View Data / View Query / Export CSV / Export Excel all continue to
    operate on the real underlying rows, never the image.

PROMPT AGENT: a text-LLM step (`_refine_full_report_prompt`, using the same
`gpt-4.1` model already used elsewhere in the app) rewrites the data-accurate
draft description of the WHOLE report (built by `_build_full_report_prompt`)
into a single, more detailed, better art-directed image-generation prompt
before it reaches gpt-image-2 — deciding dashboard layout/organization only,
never touching or inventing any of the real values embedded in it. The system
prompt for this step explicitly instructs the model to preserve every real
number/label verbatim, and to explicitly call out any truncation (e.g. "showing
top 15 of 367 rows") rather than silently dropping data or trying to cram an
illegible wall of numbers into the image. If text AI is disabled or
refinement fails, the original, simpler draft prompt is used unchanged.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.ai.openai_client import chat_completion
from app.ai.openai_client import is_enabled as text_ai_is_enabled
from app.core.config import get_settings
from app.schemas.report import ChartSpec, KPISpec, ReportSpec, TableSpec

logger = logging.getLogger("app.ai.chart_image")
settings = get_settings()

_FULL_REPORT_PROMPT_WRITER_SYSTEM = (
    "You are a prompt-writing specialist for an AI image generation model "
    "(gpt-image-2) that draws a complete business intelligence dashboard "
    "report as ONE single image. You will be given a plain, data-accurate "
    "description of an entire report — its title/subtitle, every KPI, every "
    "chart's real data points, every table's real rows (possibly a "
    "representative subset with a stated true total), and every insight. You "
    "MUST preserve every real number, label, and row verbatim — do not alter, "
    "round, invent, or drop any value; only decide layout and organization. "
    "Rewrite the input into a single detailed, vivid image-generation prompt "
    "that will produce a polished, professional, premium BI dashboard visual "
    "containing ALL of the given sections composed together on one canvas: "
    "specify where the KPI cards go (typically a top row), where charts go, "
    "where tables go, and where insights/callouts go, plus color palette, "
    "typography feel, spacing, and visual hierarchy, the way a senior product "
    "designer would brief an illustrator laying out one full dashboard page. "
    "If a table's description says it is showing a partial subset of a larger "
    "total, explicitly instruct the image to show that as a labeled note (e.g. "
    "'showing top 15 of 367 rows') rather than trying to cram every row in "
    "illegibly or silently pretending the subset is the whole table. Keep "
    "every real number/label from the input exactly as given, copied "
    "character for character — never round differently, truncate, or extend "
    "any number with extra digits/decimal places (image models frequently "
    "hallucinate extra trailing digits on numeric labels; your rewritten "
    "prompt MUST explicitly and repeatedly instruct the image model to "
    "reproduce every number exactly as given here, with no more and no fewer "
    "digits, and to prefer larger/clearer text over guessing digits it is "
    "unsure of — this matters even more here since a single image now carries "
    "many more numbers than a single chart/KPI/table would). KPI cards need "
    "special emphasis: image models sometimes render an empty/blank stat card "
    "when a report has several KPIs — your rewritten prompt MUST state the "
    "exact number of KPI cards required and repeat each card's exact label "
    "and number text, with an explicit instruction that no card may be left "
    "blank. Do not add commentary, explanation, or markdown — output ONLY the final "
    "image-generation prompt text."
)

# Keep prompts readable and within reasonable size/cost.
# Per-chart data point cap, same as the previous per-section approach.
_MAX_CHART_POINTS = 30
# Per-table row cap is tighter than before (was 30) because multiple tables
# now have to coexist legibly within ONE image alongside KPIs/charts/insights.
_MAX_TABLE_ROWS = 18

_client = None


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        # Avoid dumping ugly float noise (e.g. 4814533.190000001) into the prompt.
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _truncation_note(total: int, shown: int, unit: str = "rows") -> str:
    if total <= shown:
        return ""
    return (
        f" (showing the first {shown} of {total} {unit}, in the order the data "
        "was returned — the image must clearly label this as a partial view, "
        f"e.g. 'top {shown} of {total}')"
    )


def _describe_kpi(index: int, kpi: KPISpec) -> str:
    value_text = _format_value(kpi.value) if not isinstance(kpi.value, str) else kpi.value
    if kpi.format == "currency" and not isinstance(kpi.value, str):
        value_text = f"${value_text}"
    elif kpi.format == "percentage" and not isinstance(kpi.value, str):
        value_text = f"{value_text}%"

    delta_text = ""
    if kpi.delta is not None:
        direction = "up" if (kpi.trend == "up") else ("down" if kpi.trend == "down" else "flat")
        delta_text = f", small trend indicator: {direction} {abs(kpi.delta):.1f}%"
        if kpi.delta_label:
            delta_text += f" ({kpi.delta_label})"

    return (
        f"  Card {index}: small label text reading exactly '{kpi.label}', "
        f"below it large bold number text reading exactly '{value_text}'"
        f"{delta_text}. This card MUST NOT be left blank/empty."
    )


def _describe_chart(chart: ChartSpec) -> str:
    rows = chart.data or []
    shown = rows[:_MAX_CHART_POINTS]
    x_field = chart.x_field
    y_field = chart.y_field

    lines: list[str] = []
    for row in shown:
        if x_field and y_field and x_field in row and y_field in row:
            lines.append(f"    {row[x_field]}: {_format_value(row[y_field])}")
        else:
            pairs = ", ".join(f"{k}={_format_value(v)}" for k, v in row.items())
            lines.append(f"    {pairs}")

    data_text = "\n".join(lines) if lines else "    (no data rows)"
    note = _truncation_note(len(rows), len(shown), unit="data points")

    chart_type_label = {
        "bar": "vertical bar chart",
        "horizontal_bar": "horizontal bar chart",
        "line": "line chart",
        "area": "filled area chart",
        "pie": "pie chart",
        "donut": "donut chart",
        "scatter": "scatter plot",
        "funnel": "funnel chart",
        "gauge": "gauge chart",
        "heatmap": "heatmap",
    }.get(chart.type, "chart")

    header = f"- Chart '{chart.title}' ({chart_type_label})"
    if chart.subtitle:
        header += f" — {chart.subtitle}"
    header += (
        f", real data points{note} — each value below has exactly the digits "
        "shown, use a small enough font that every digit is legible rather "
        "than shortening or lengthening any number:"
    )
    return header + "\n" + data_text


def _describe_table(table: TableSpec) -> str:
    rows = table.rows or []
    shown = rows[:_MAX_TABLE_ROWS]
    columns = [c.field for c in table.columns] if table.columns else (list(shown[0].keys()) if shown else [])
    labels = [c.label for c in table.columns] if table.columns else columns

    header_text = " | ".join(labels) if labels else "(no columns)"
    row_lines = [
        "    " + " | ".join(_format_value(row.get(c, "")) for c in columns)
        for row in shown
    ]
    data_text = "\n".join(row_lines) if row_lines else "    (no data rows)"
    note = _truncation_note(len(rows), len(shown), unit="rows")

    return (
        f"- Table '{table.title}', columns: {header_text}, real rows{note}:\n"
        f"    {header_text}\n{data_text}"
    )


def _describe_insight(insight) -> str:
    return f"- [{insight.kind}] {insight.text}"


def _build_full_report_prompt(report: ReportSpec) -> str:
    """Builds a plain, data-accurate description of the ENTIRE report (every
    real KPI/chart/table/insight) for the prompt-writer step to turn into a
    single image-generation prompt. Never invents data — only formats what is
    already on the materialized ReportSpec."""
    parts: list[str] = []
    parts.append(f"Report title: '{report.title}'")
    if report.subtitle:
        parts.append(f"Report subtitle: '{report.subtitle}'")

    if report.kpis:
        parts.append(
            f"\nKPI cards: render EXACTLY {len(report.kpis)} stat cards in a top "
            "row, no more and no fewer. Every single card below MUST contain its "
            "label and number — a card with no visible text is a failure:"
        )
        parts.extend(_describe_kpi(i, k) for i, k in enumerate(report.kpis, start=1))

    if report.charts:
        parts.append("\nCharts:")
        parts.extend(_describe_chart(c) for c in report.charts)

    if report.tables:
        parts.append("\nTables:")
        parts.extend(_describe_table(t) for t in report.tables)

    if report.insights:
        parts.append("\nInsights / callouts (render as a highlighted section, e.g. bottom or side panel):")
        parts.extend(_describe_insight(i) for i in report.insights)

    description = "\n".join(parts)

    return (
        "Create ONE single professional business intelligence dashboard report "
        "image containing ALL of the following real sections composed together "
        "on one cohesive canvas — a title area, a row of KPI stat cards, one or "
        "more charts, one or more data tables, and an insights/callouts panel, "
        "exactly as described below. Do not omit any section; do not invent any "
        "section, value, or row not listed below.\n\n"
        f"{description}\n\n"
        "Style: clean corporate BI dashboard, white background, generous "
        "spacing between sections so nothing overlaps or is cut off, legible "
        "sans-serif font, no watermarks, no extra decorative elements beyond "
        "the dashboard itself. Use a varied, vivid accent-color system rather "
        "than a single blue tone everywhere: cycle each KPI card's icon badge "
        "and each chart/table's header accent through a palette of blue, "
        "purple, teal, amber, and pink (in that order, repeating if there are "
        "more sections than colors) so the dashboard reads as organized and "
        "colorful rather than a wall of identical blue boxes — bar/line/area "
        "chart series and pie/donut chart slices should also use that same "
        "5-color palette (a different color per category/series, not every "
        "bar in one chart being identical blue), while headers and body text "
        "stay dark navy/charcoal on white for readability. "
        "CRITICAL for every number and label: copy each one EXACTLY as written "
        "above, character for character — do not extend, truncate, round "
        "differently, or add extra digits. Every value above is already "
        "formatted with at most 2 decimal places; never draw a longer or "
        "different-looking number. If you cannot render a number with complete "
        "confidence and precision, render it in a larger, clearer font rather "
        "than guessing extra digits. If any table/chart notes that it is "
        "showing a partial subset of a larger total, render that note clearly "
        "in the image (e.g. 'top 15 of 367 rows') rather than pretending the "
        "subset is the complete data. CRITICAL for KPI cards specifically: "
        "every KPI card listed above must show its label and number as actual "
        "visible text inside the card — an empty or blank stat card is a "
        "failure of the image, never leave a card's interior blank."
    )


async def _refine_full_report_prompt(draft_prompt: str) -> str:
    """Prompt Agent step: runs the data-accurate whole-report draft prompt
    through a text-LLM (gpt-4.1) to turn it into a more detailed, better
    art-directed single image-generation prompt, before handing it to
    gpt-image-2. Does NOT touch or re-derive any data — only rewrites style/
    layout instructions around the numbers/labels the draft prompt already
    contains. Falls back to the draft prompt unchanged on any failure or when
    text AI is disabled (never blocks or fails image generation)."""
    if not text_ai_is_enabled():
        return draft_prompt
    try:
        refined = await chat_completion(
            system=_FULL_REPORT_PROMPT_WRITER_SYSTEM,
            user=draft_prompt,
            temperature=0.4,
            max_tokens=1600,
        )
        refined = refined.strip()
        return refined if refined else draft_prompt
    except Exception:  # noqa: BLE001 - prompt refinement is best-effort, never blocks image generation
        logger.exception("Full-report prompt refinement failed; falling back to the draft prompt (non-fatal).")
        return draft_prompt


async def generate_full_report_image(report: ReportSpec) -> str | None:
    """Builds a single description of the ENTIRE report's real data, refines
    it into one image-generation prompt, and calls gpt-image-2 ONCE to
    produce ONE image depicting the whole report (title + KPIs + charts +
    tables + insights). Returns a data URI or hosted URL, or None if AI/image
    generation is disabled or the call fails (never raises)."""
    if not is_enabled():
        return None
    try:
        draft_prompt = _build_full_report_prompt(report)
    except Exception:  # noqa: BLE001 - prompt building must never crash a report
        logger.exception("Failed to build full-report image prompt (non-fatal).")
        return None

    try:
        prompt = await _refine_full_report_prompt(draft_prompt)
        client = _get_client()
        response = await client.images.generate(
            model=settings.OPENAI_IMAGE_MODEL,
            prompt=prompt,
            # A single image now depicts an entire multi-section dashboard
            # (KPI row + charts + tables + insights), so it needs more usable
            # canvas than any one item did before. 1536x1024 is kept as a
            # pragmatic choice: it's the same "large" size already used and
            # supported by gpt-image-2 today, and a wide landscape canvas
            # suits a top-KPI-row + charts-below dashboard layout better than
            # a taller portrait canvas would.
            size="1536x1024",
            n=1,
        )
        if not response.data:
            return None
        image = response.data[0]
        url = getattr(image, "url", None)
        if url:
            return url
        b64 = getattr(image, "b64_json", None)
        if b64:
            return f"data:image/png;base64,{b64}"
        return None
    except Exception:  # noqa: BLE001 - the whole-report image is best-effort, never fails the report
        logger.exception("Full-report image generation failed (non-fatal).")
        return None


# ---------------------------------------------------------------------------
# Superseded per-section functions (2026-09-19, single-image revision).
#
# Kept only in case per-section image generation is wanted again later.
# Nothing in the live report-generation path (app/agents/report_agent.py,
# app/reports/recommended.py) calls these anymore — they've been replaced by
# generate_full_report_image() above, called once per report instead of once
# per KPI/chart/table.
# ---------------------------------------------------------------------------

_PROMPT_WRITER_SYSTEM = (
    "You are a prompt-writing specialist for an AI image generation model "
    "(gpt-image-2) that draws business intelligence dashboard visuals. You "
    "will be given a plain, data-accurate description of a chart, KPI card, "
    "or table (including its exact real values, which you MUST preserve "
    "verbatim — do not alter, round, invent, or drop any number, label, or "
    "row). Rewrite it into a single detailed, vivid image-generation prompt "
    "that will produce a polished, professional, premium BI dashboard visual: "
    "specify layout, color palette, typography feel, spacing, and visual "
    "hierarchy precisely, the way a senior product designer would brief an "
    "illustrator. Keep every real number/label from the input exactly as "
    "given, copied character for character — never round differently, "
    "truncate, or extend any number with extra digits/decimal places (image "
    "models frequently hallucinate extra trailing digits on numeric labels; "
    "your rewritten prompt MUST explicitly and repeatedly instruct the image "
    "model to reproduce every number exactly as given here, with no more and "
    "no fewer digits, and to prefer larger/clearer text over guessing digits "
    "it is unsure of). Do not add commentary, explanation, or markdown — "
    "output ONLY the final image-generation prompt text."
)

_MAX_DATA_POINTS = 30
_MAX_CONCURRENT_IMAGE_CALLS = 4
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_IMAGE_CALLS)


async def _refine_prompt(draft_prompt: str) -> str:
    if not text_ai_is_enabled():
        return draft_prompt
    try:
        refined = await chat_completion(
            system=_PROMPT_WRITER_SYSTEM,
            user=draft_prompt,
            temperature=0.4,
            max_tokens=800,
        )
        refined = refined.strip()
        return refined if refined else draft_prompt
    except Exception:  # noqa: BLE001
        logger.exception("Prompt refinement failed; falling back to the draft prompt (non-fatal).")
        return draft_prompt


async def _generate_image(prompt: str) -> str | None:
    try:
        prompt = await _refine_prompt(prompt)
        client = _get_client()
        response = await client.images.generate(
            model=settings.OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size="1536x1024",
            n=1,
        )
        if not response.data:
            return None
        image = response.data[0]
        url = getattr(image, "url", None)
        if url:
            return url
        b64 = getattr(image, "b64_json", None)
        if b64:
            return f"data:image/png;base64,{b64}"
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Chart/KPI/table image generation failed (non-fatal).")
        return None


def _build_chart_prompt(chart: ChartSpec) -> str:
    rows = chart.data or []
    shown = rows[:_MAX_DATA_POINTS]
    x_field = chart.x_field
    y_field = chart.y_field

    lines: list[str] = []
    for row in shown:
        if x_field and y_field and x_field in row and y_field in row:
            lines.append(f"{row[x_field]}: {_format_value(row[y_field])}")
        else:
            pairs = ", ".join(f"{k}={_format_value(v)}" for k, v in row.items())
            lines.append(pairs)

    data_text = "\n".join(f"- {line}" for line in lines) if lines else "(no data rows)"
    note = _truncation_note(len(rows), len(shown))

    chart_type_label = {
        "bar": "vertical bar chart",
        "horizontal_bar": "horizontal bar chart",
        "line": "line chart",
        "area": "filled area chart",
        "pie": "pie chart",
        "donut": "donut chart",
        "scatter": "scatter plot",
        "funnel": "funnel chart",
        "gauge": "gauge chart",
        "heatmap": "heatmap",
    }.get(chart.type, "chart")

    return (
        f"Create a professional {chart_type_label} image for a business intelligence "
        f"dashboard. Title: '{chart.title}'."
        + (f" Subtitle: '{chart.subtitle}'." if chart.subtitle else "")
        + f" Render these exact real data points as labeled values on the chart{note}:\n"
        + data_text
        + "\n\nStyle: clean corporate BI dashboard chart, blue color palette, white "
        "background, clear axis labels, legible sans-serif font, no watermarks, no "
        "extra decorative elements beyond the chart itself. CRITICAL for value "
        "labels: copy each number EXACTLY as written above, character for character "
        "— do not extend, truncate, round differently, or add extra digits. Every "
        "value above already has at most 2 decimal places; never draw a longer or "
        "different-looking number. If you cannot render a number with complete "
        "confidence and precision, render it in a larger, clearer font rather than "
        "guessing extra digits."
    )


def _build_kpi_prompt(kpi: KPISpec) -> str:
    value_text = _format_value(kpi.value) if not isinstance(kpi.value, str) else kpi.value
    if kpi.format == "currency" and not isinstance(kpi.value, str):
        value_text = f"${value_text}"
    elif kpi.format == "percentage" and not isinstance(kpi.value, str):
        value_text = f"{value_text}%"

    delta_text = ""
    if kpi.delta is not None:
        direction = "up" if (kpi.trend == "up") else ("down" if kpi.trend == "down" else "flat")
        delta_text = f" Show a small trend indicator: {direction} {abs(kpi.delta):.1f}%"
        if kpi.delta_label:
            delta_text += f" ({kpi.delta_label})"
        delta_text += "."

    return (
        "Create a single professional KPI stat card image for a business "
        f"intelligence dashboard. Label: '{kpi.label}'. Render this exact real "
        f"value as large bold text: '{value_text}'."
        + delta_text
        + " Style: clean corporate BI dashboard stat card, white background, blue "
        "accent color, minimal, legible sans-serif font, no watermarks. CRITICAL: "
        f"copy '{value_text}' EXACTLY, character for character — do not add, drop, "
        "or change any digit, and never extend it with extra decimal places."
    )


def _build_table_prompt(table: TableSpec) -> str:
    rows = table.rows or []
    shown = rows[:_MAX_DATA_POINTS]
    columns = [c.field for c in table.columns] if table.columns else (list(shown[0].keys()) if shown else [])
    labels = [c.label for c in table.columns] if table.columns else columns

    header_text = " | ".join(labels) if labels else "(no columns)"
    row_lines = []
    for row in shown:
        row_lines.append(" | ".join(_format_value(row.get(c, "")) for c in columns))
    data_text = "\n".join(row_lines) if row_lines else "(no data rows)"
    note = _truncation_note(len(rows), len(shown))

    return (
        "Create a clean, professional data table image for a business "
        f"intelligence dashboard. Title: '{table.title}'. Columns: {header_text}. "
        f"Render these exact real rows as table content{note}:\n"
        f"{header_text}\n{data_text}\n\n"
        "Style: clean corporate BI dashboard data table, alternating light-blue/"
        "white row shading, bold header row, right-aligned numeric columns, "
        "legible sans-serif font, no watermarks. CRITICAL: copy every number and "
        "label above EXACTLY as written, character for character — never add, "
        "drop, or change a digit, and never extend a number with extra decimal "
        "places beyond what is shown."
    )


async def generate_chart_image(chart: ChartSpec) -> str | None:
    """Superseded by generate_full_report_image(); kept for potential future
    per-section use, not called from the live report-generation path."""
    if not is_enabled():
        return None
    try:
        prompt = _build_chart_prompt(chart)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build chart image prompt (non-fatal).")
        return None
    async with _semaphore:
        return await _generate_image(prompt)


async def generate_kpi_image(kpi: KPISpec) -> str | None:
    """Superseded by generate_full_report_image(); kept for potential future
    per-section use, not called from the live report-generation path."""
    if not is_enabled():
        return None
    try:
        prompt = _build_kpi_prompt(kpi)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build KPI image prompt (non-fatal).")
        return None
    async with _semaphore:
        return await _generate_image(prompt)


async def generate_table_image(table: TableSpec) -> str | None:
    """Superseded by generate_full_report_image(); kept for potential future
    per-section use, not called from the live report-generation path."""
    if not is_enabled():
        return None
    try:
        prompt = _build_table_prompt(table)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build table image prompt (non-fatal).")
        return None
    async with _semaphore:
        return await _generate_image(prompt)


async def attach_report_images(report) -> None:
    """Superseded by generate_full_report_image(); kept for potential future
    per-section use, not called from the live report-generation path.

    Mutates a ReportSpec in place, setting `image_url` on every kpi/chart/
    table by running all the individual image-generation calls concurrently
    (bounded by the semaphore above). No-op when image generation is
    disabled. Never raises."""
    if not is_enabled():
        return

    async def _fill_kpi(kpi: KPISpec) -> None:
        kpi.image_url = await generate_kpi_image(kpi)

    async def _fill_chart(chart: ChartSpec) -> None:
        chart.image_url = await generate_chart_image(chart)

    async def _fill_table(table: TableSpec) -> None:
        table.image_url = await generate_table_image(table)

    tasks = (
        [_fill_kpi(k) for k in report.kpis]
        + [_fill_chart(c) for c in report.charts]
        + [_fill_table(t) for t in report.tables]
    )
    if not tasks:
        return
    await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "generate_full_report_image",
    "is_enabled",
    # Superseded, kept for potential future per-section use:
    "generate_chart_image",
    "generate_kpi_image",
    "generate_table_image",
    "attach_report_images",
]
