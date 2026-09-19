"""Analytics engine: deterministic calculations must be correct and never
divide by zero without returning None. The LLM never computes a number —
every function here is plain Python arithmetic over already-executed rows.
"""
from app.analytics.engine import (
    average_order_value,
    build_trend,
    conversion_rate,
    count_rows,
    delivery_delay_pct,
    margin_pct,
    rank_top_n,
    safe_pct_change,
    scalar_from_single_row,
    sum_field,
)


def test_safe_pct_change_basic():
    assert safe_pct_change(120, 100) == 20.0


def test_safe_pct_change_negative():
    assert safe_pct_change(80, 100) == -20.0


def test_safe_pct_change_zero_previous_is_none():
    assert safe_pct_change(50, 0) is None


def test_safe_pct_change_none_inputs_are_none():
    assert safe_pct_change(None, 100) is None
    assert safe_pct_change(100, None) is None


def test_safe_pct_change_uses_absolute_previous_for_sign():
    # previous negative: pct change should still reflect direction correctly
    assert safe_pct_change(-50, -100) == 50.0


def test_margin_pct_basic():
    assert margin_pct(1000, 600) == 40.0


def test_margin_pct_zero_revenue_is_none():
    assert margin_pct(0, 100) is None


def test_margin_pct_none_inputs_are_none():
    assert margin_pct(None, 100) is None
    assert margin_pct(1000, None) is None


def test_average_order_value_basic():
    assert average_order_value(1000, 4) == 250.0


def test_average_order_value_zero_orders_is_none():
    assert average_order_value(1000, 0) is None


def test_average_order_value_none_orders_is_none():
    assert average_order_value(1000, None) is None


def test_conversion_rate_basic():
    assert conversion_rate(25, 200) == 12.5


def test_conversion_rate_zero_total_is_none():
    assert conversion_rate(5, 0) is None


def test_delivery_delay_pct_basic():
    assert delivery_delay_pct(10, 40) == 25.0


def test_delivery_delay_pct_zero_total_is_none():
    assert delivery_delay_pct(0, 0) is None


def test_sum_field_ignores_none_values():
    rows = [{"amount": 10}, {"amount": None}, {"amount": 5.5}]
    assert sum_field(rows, "amount") == 15.5


def test_sum_field_missing_field_treated_as_zero():
    rows = [{"other": 1}, {"amount": 3}]
    assert sum_field(rows, "amount") == 3


def test_count_rows():
    assert count_rows([{"a": 1}, {"a": 2}, {"a": 3}]) == 3
    assert count_rows([]) == 0


def test_scalar_from_single_row_prefers_named_field():
    """Regression test for the real production bug (CLAUDE.md): a KPI showed
    the wrong column's value because 'whichever key comes first' was used
    instead of the actually-requested field."""
    rows = [{"total_value": 2517126.67, "order_count": 2}]
    assert scalar_from_single_row(rows, field="order_count") == 2


def test_scalar_from_single_row_falls_back_to_first_when_no_field():
    rows = [{"a": 1, "b": 2}]
    assert scalar_from_single_row(rows) == 1


def test_scalar_from_single_row_empty_rows_is_none():
    assert scalar_from_single_row([]) is None


def test_build_trend_skips_rows_with_no_period():
    rows = [{"month": "Jan", "revenue": 100}, {"month": None, "revenue": 50}, {"month": "Feb", "revenue": 200}]
    trend = build_trend(rows, "month", "revenue")
    assert [p.period for p in trend] == ["Jan", "Feb"]
    assert [p.value for p in trend] == [100.0, 200.0]


def test_rank_top_n_descending():
    rows = [{"name": "A", "revenue": 10}, {"name": "B", "revenue": 50}, {"name": "C", "revenue": 30}]
    top2 = rank_top_n(rows, "revenue", n=2)
    assert [r["name"] for r in top2] == ["B", "C"]


def test_rank_top_n_ascending():
    rows = [{"name": "A", "revenue": 10}, {"name": "B", "revenue": 50}]
    bottom = rank_top_n(rows, "revenue", n=1, descending=False)
    assert [r["name"] for r in bottom] == ["A"]
