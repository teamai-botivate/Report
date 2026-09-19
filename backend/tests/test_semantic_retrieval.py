"""Tests for the deterministic semantic-layer retrieval (`retrieve_relevant_metadata`).

These tests must pass with NO OpenAI key, NO database connection, and NO
running event loop — retrieval is pure keyword/synonym matching over the
static `dictionary.py` (optionally merged with `Base.metadata`, which is
importable in-process without hitting a real database).
"""
from __future__ import annotations

from app.semantic_layer.dictionary import MEASURES, TABLES
from app.semantic_layer.retrieval import retrieve_relevant_metadata


def _table_names(context: dict) -> set[str]:
    return {t["name"] for t in context["tables"]}


def _measure_names(context: dict) -> set[str]:
    return {m["name"] for m in context["measures"]}


def test_total_revenue_question_retrieves_sales_invoices_and_measure():
    context = retrieve_relevant_metadata("show total revenue")

    names = _table_names(context)
    assert "sales_invoices" in names

    measures = _measure_names(context)
    assert "Total Revenue" in measures


def test_top_customers_by_revenue_retrieves_customers_and_sales_tables():
    context = retrieve_relevant_metadata("top customers by revenue")

    names = _table_names(context)
    assert "customers" in names
    assert ("sales_invoices" in names) or ("sales_orders" in names)


def test_delayed_deliveries_retrieves_delivery_tables():
    context = retrieve_relevant_metadata("show me delayed deliveries")

    names = _table_names(context)
    assert "deliveries" in names or "delivery_delays" in names


def test_employee_attendance_by_department_retrieves_expected_tables():
    context = retrieve_relevant_metadata("employee attendance by department")

    names = _table_names(context)
    assert "employees" in names
    assert "attendance" in names
    assert "departments" in names


def test_narrow_question_never_returns_all_tables():
    context = retrieve_relevant_metadata("show total revenue")

    # There are 62 real business tables in dictionary.py; a narrow question
    # must never dump the whole schema into the prompt.
    assert len(TABLES) >= 40  # sanity check the dictionary is actually populated
    assert len(context["tables"]) < len(TABLES)
    assert len(context["tables"]) <= 6


def test_default_max_tables_is_respected():
    context = retrieve_relevant_metadata("revenue purchase inventory production attendance delivery", max_tables=3)
    assert len(context["tables"]) <= 3


def test_retrieval_works_standalone_without_cache_refresh():
    # No refresh_metadata_cache() call has happened in this test process;
    # retrieval must still work by lazily building from dictionary.py.
    from app.semantic_layer.metadata_cache import get_cached_metadata

    # Don't assert the cache is empty (another test module in the same
    # session may have populated it) — just confirm retrieval still works
    # correctly regardless of cache state.
    _ = get_cached_metadata()
    context = retrieve_relevant_metadata("total purchase value")
    assert any(t["name"] == "purchase_orders" for t in context["tables"])
    assert any(m["name"] == "Purchase Value" for m in context["measures"])


def test_measures_list_has_the_dax_like_measures_required_by_spec():
    names = {m.name for m in MEASURES}
    required = {
        "Total Revenue",
        "Purchase Value",
        "Total Orders",
        "Average Order Value",
        "Conversion Rate",
        "Gross Margin",
        "Delivery Delay",
        "Delivery Delay %",
        "Inventory Turnover",
        "Production Rejection %",
        "Employee Attendance %",
    }
    assert required <= names
