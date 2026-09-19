"""SQL execution audit log — every AI-generated query that reaches the executor is
recorded here, regardless of whether it passed or failed validation."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SQLAuditLog(Base):
    __tablename__ = "sql_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    node_id: Mapped[str | None] = mapped_column(String(64))
    question: Mapped[str | None] = mapped_column(Text, comment="Original NL question this query served")
    sql_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True, comment="validated|rejected|executed|error")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    elapsed_ms: Mapped[float | None] = mapped_column()
    tables_referenced: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
