"""Import every model module so `Base.metadata` (and Alembic autogenerate)
sees all tables, and so cross-module string-based relationships resolve.

Import order matters only for readability here — SQLAlchemy resolves
string-based relationship() targets lazily via the mapper registry, so as
long as every module is imported once before `Base.metadata` is used, the
order below is not load-bearing. It is listed in dependency order anyway
(master first, since nothing else depends on anything but master) for
clarity.
"""
from app.models import (  # noqa: F401
    finance,
    hr,
    inventory,
    master,
    order_to_delivery,
    production,
    purchase,
    sales,
    tasks,
)

__all__ = [
    "finance",
    "hr",
    "inventory",
    "master",
    "order_to_delivery",
    "production",
    "purchase",
    "sales",
    "tasks",
]
