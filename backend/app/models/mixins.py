"""Reusable mixins for SQLAlchemy models.

TimestampMixin adds created_at/updated_at columns backed by the database's
own clock (server_default=func.now()) so that timestamps are consistent
regardless of which process (API server, seed script, migration) writes the
row, and work identically on SQLite and Postgres.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds created_at / updated_at audit columns to a model."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp (server clock).",
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Row last-updated timestamp (server clock).",
    )
