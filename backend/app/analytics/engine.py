"""Deterministic post-query analytics. The LLM never computes a number — every
growth %, margin, delta, ratio here is plain Python arithmetic over already-executed
query rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def safe_pct_change(current: float | int | None, previous: float | int | None) -> float | None:
    """(current - previous) / previous * 100, guarding zero/None division."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round((float(current) - float(previous)) / abs(float(previous)) * 100.0, 2)


# Backward-compatible alias.
pct_change = safe_pct_change


def margin_pct(revenue: float | int | None, cost: float | int | None) -> float | None:
    if revenue is None or cost is None or revenue == 0:
        return None
    return round((float(revenue) - float(cost)) / float(revenue) * 100.0, 2)


def average_order_value(total_revenue: float | int | None, order_count: int | None) -> float | None:
    if not order_count:
        return None
    return round(float(total_revenue or 0) / order_count, 2)


def conversion_rate(converted: int | None, total: int | None) -> float | None:
    if not total:
        return None
    return round(float(converted or 0) / total * 100.0, 2)


def delivery_delay_pct(delayed: int | None, total: int | None) -> float | None:
    if not total:
        return None
    return round(float(delayed or 0) / total * 100.0, 2)


def sum_field(rows: list[dict[str, Any]], field: str) -> float:
    total = 0.0
    for row in rows:
        val = row.get(field)
        if val is not None:
            total += float(val)
    return round(total, 2)


def count_rows(rows: list[dict[str, Any]]) -> int:
    return len(rows)


def scalar_from_single_row(rows: list[dict[str, Any]], field: str | None = None) -> Any:
    """Extract a single scalar from a one-row/one-column aggregate result.

    If `field` is given, prefer that named column (fixes the real production bug where
    "whichever column comes first" picked the wrong one — see CLAUDE.md known bugs).
    """
    if not rows:
        return None
    row = rows[0]
    if field and field in row:
        return row[field]
    # fall back to the first value only when no field was specified
    values = list(row.values())
    return values[0] if values else None


@dataclass
class TrendPoint:
    period: str
    value: float


def build_trend(rows: list[dict[str, Any]], period_field: str, value_field: str) -> list[TrendPoint]:
    points: list[TrendPoint] = []
    for row in rows:
        period = row.get(period_field)
        value = row.get(value_field)
        if period is None:
            continue
        points.append(TrendPoint(period=str(period), value=float(value) if value is not None else 0.0))
    return points


def rank_top_n(rows: list[dict[str, Any]], value_field: str, n: int = 10, descending: bool = True) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r.get(value_field) or 0), reverse=descending)[:n]
