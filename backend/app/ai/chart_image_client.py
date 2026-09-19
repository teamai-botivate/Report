"""Chart/KPI/table image generation client (2026-09-19 product override).

IMPORTANT — this module implements a deliberate, explicitly-confirmed
reversal of a previously "locked in" architectural rule, not an oversight.

CLAUDE.md's original "Charts" stack decision stated:
    "Charts: rendered client-side from structured `visualization` JSON + real
    row data returned by the backend. No image-generation model ever touches
    chart pixels."

That rule is superseded, by explicit user request, given three times over
with the accuracy risk fully explained and accepted each time: every KPI,
chart, and table in a report is now ALSO rendered as an AI-generated image via
`settings.OPENAI_IMAGE_MODEL` (gpt-image-2), using the real query-result data
formatted into the image prompt. The ECharts/DOM rendering path
(frontend/components/report/ChartRenderer.tsx, DataTableView.tsx,
ReportCanvas.tsx) is NOT removed — it is kept, fully intact, as the automatic
fallback whenever `image_url` is absent (AI/image generation disabled, or
generation failed for that one item).

ACCURACY IS NOT GUARANTEED. Image generation is not a deterministic,
per-pixel-verifiable rendering path the way ECharts is: the model draws the
numbers/labels into the image itself, and there is no code-level guarantee
that every digit, label, or bar length in the resulting picture exactly
matches the real data it was given. This directly conflicts with this
project's own stated "AI must never fabricate a business number" principle
and its automated-testing guarantees for chart output specifically. The user
was told this in plain terms and chose to proceed anyway. Do not "fix" this
by silently reverting to ECharts-only rendering, and do not re-litigate the
decision — implement it well and let the ECharts fallback carry the accuracy
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

PROMPT AGENT (2026-09-19, added at user request for better image quality):
a small intermediate text-LLM step (`_refine_prompt`, using the same
`gpt-4.1` model already used elsewhere in the app) rewrites each data-
accurate draft prompt (built by `_build_chart_prompt`/`_build_kpi_prompt`/
`_build_table_prompt`) into a more detailed, better art-directed prompt
before it reaches gpt-image-2 — improving layout/color/typography guidance
without touching the real values embedded in it. The system prompt for this
step explicitly instructs the model to preserve every number/label verbatim.
This is a style-quality improvement only; it does not change, and cannot
improve, the fundamental lack of pixel-level accuracy guarantee described
above — a prompt-refinement bug or a refined prompt the image model
misreads can still produce a visual that doesn't exactly match the source
data. If text AI is disabled or refinement fails, the original, simpler
draft prompt is used unchanged (see `_refine_prompt`'s fallback behavior).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.ai.openai_client import chat_completion
from app.ai.openai_client import is_enabled as text_ai_is_enabled
from app.core.config import get_settings
from app.schemas.report import ChartSpec, KPISpec, TableSpec

logger = logging.getLogger("app.ai.chart_image")
settings = get_settings()

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

# Keep prompts readable and within reasonable size/cost — if a chart/table has
# more rows than this, only the first N (in whatever order they already
# arrived in, i.e. however the SQL query ordered them) are described in the
# prompt, and the prompt explicitly says so rather than silently truncating.
_MAX_DATA_POINTS = 30

# Cap concurrent image-generation calls so a report with many
# KPIs/charts/tables doesn't take forever or hammer the API with unlimited
# parallel requests.
_MAX_CONCURRENT_IMAGE_CALLS = 4
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_IMAGE_CALLS)

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


def _truncation_note(total: int, shown: int) -> str:
    if total <= shown:
        return ""
    return (
        f" (showing the first {shown} of {total} rows, in the order the data was "
        "returned — note in the image that this is a partial view if space allows)"
    )


async def _refine_prompt(draft_prompt: str) -> str:
    """Prompt Agent step (2026-09-19): runs the data-accurate draft prompt
    built by _build_*_prompt through a text-LLM (gpt-4.1, same model already
    used for the rest of the app) to turn it into a more detailed, better
    art-directed image-generation prompt, before handing it to gpt-image-2.

    This does NOT touch or re-derive any data — it only rewrites style/layout
    instructions around the numbers/labels the draft prompt already contains,
    and the system prompt explicitly instructs the model to preserve every
    real value verbatim. If text AI is disabled or this call fails for any
    reason, falls back to the original draft prompt unchanged (never blocks
    or fails image generation over a prompt-refinement hiccup).
    """
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
    except Exception:  # noqa: BLE001 - prompt refinement is best-effort, never blocks image generation
        logger.exception("Prompt refinement failed; falling back to the draft prompt (non-fatal).")
        return draft_prompt


async def _generate_image(prompt: str) -> str | None:
    """Shared call/response-parsing logic — same non-fatal error handling and
    b64_json/url fallback pattern as generate_decorative_image()."""
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
    except Exception:  # noqa: BLE001 - a single image is best-effort, never fails the report
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
            # No clear x/y split (e.g. multi-series or heatmap) — describe the
            # whole row's real key/value pairs instead of guessing a field.
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
    """Formats chart's real data/type/title into a detailed prompt and calls
    the image model. Returns a data URI or hosted URL, or None if AI/image
    generation is disabled or the call fails (never raises)."""
    if not is_enabled():
        return None
    try:
        prompt = _build_chart_prompt(chart)
    except Exception:  # noqa: BLE001 - prompt building must never crash a report
        logger.exception("Failed to build chart image prompt (non-fatal).")
        return None
    async with _semaphore:
        return await _generate_image(prompt)


async def generate_kpi_image(kpi: KPISpec) -> str | None:
    """Same idea as generate_chart_image but for a single KPI stat card."""
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
    """Same idea as generate_chart_image but for a table's columns/rows."""
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
    """Mutates a ReportSpec in place, setting `image_url` on every kpi/chart/
    table by running all the individual image-generation calls concurrently
    (bounded by the semaphore above). No-op (leaves every image_url as None)
    when image generation is disabled — callers don't need to branch on
    is_enabled() themselves. Never raises: any individual failure just leaves
    that item's image_url as None, exactly like the existing banner pattern."""
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
    "generate_chart_image",
    "generate_kpi_image",
    "generate_table_image",
    "attach_report_images",
    "is_enabled",
]
