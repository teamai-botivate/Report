"""Recommended reports run fixed, hand-written SQL with zero LLM calls and
must produce a valid ReportSpec from real seeded data, including when AI is
disabled (the whole point of this feature)."""
import pytest

from app.reports.recommended import CATALOG, list_catalog, run_recommended
from app.schemas.report import ReportSpec


def test_catalog_list_is_json_friendly():
    items = list_catalog()
    assert len(items) == len(CATALOG)
    for item in items:
        assert set(item.keys()) == {"id", "title", "description"}


@pytest.mark.asyncio
async def test_unknown_key_raises_value_error():
    with pytest.raises(ValueError):
        await run_recommended("does_not_exist")


@pytest.mark.asyncio
async def test_every_recommended_report_produces_valid_report_with_seeded_data():
    """Seed the real small-size dataset (same generator used everywhere
    else) so every recommended report's SQL has real, coherent data to
    return, then run every single one end-to-end."""
    from scripts.reset_db import reset_db
    from scripts.seed_database import seed_all

    await reset_db()
    await seed_all(size="small")

    for recommended in CATALOG:
        report = await run_recommended(recommended.id)
        assert isinstance(report, ReportSpec)
        assert report.title == recommended.title
        assert report.id  # a fresh uuid was assigned


@pytest.mark.asyncio
async def test_recommended_report_kpis_are_scalar_or_none_never_a_container():
    """A kpi's value must be a real scalar — never a dict/list, which would
    indicate a materialization bug leaking a raw row instead of one column's
    value."""
    from scripts.reset_db import reset_db
    from scripts.seed_database import seed_all

    await reset_db()
    await seed_all(size="small")

    report = await run_recommended("revenue_overview")
    for kpi in report.kpis:
        assert kpi.value is None or isinstance(kpi.value, (int, float, str))
