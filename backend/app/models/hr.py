"""HR domain: attendance, leave, payroll and performance tracking.

Employees, departments, designations and branches live in
`app.models.master` (imported below, never redefined here) since they are
shared master data referenced by many domains beyond HR.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Employee  # noqa: F401  (re-exported for convenience)
from app.models.mixins import TimestampMixin


class Attendance(Base, TimestampMixin):
    """Daily attendance record for one employee."""

    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Allowed values: present, absent, half_day, on_leave, holiday."
    )
    check_in: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    hours_worked: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    employee: Mapped["Employee"] = relationship()

    __table_args__ = (Index("ix_attendance_employee_date", "employee_id", "date"),)


class LeaveRequest(Base, TimestampMixin):
    """An employee's leave application."""

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    leave_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="Allowed values: casual, sick, earned, unpaid."
    )
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, comment="Allowed values: pending, approved, rejected, cancelled."
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)

    employee: Mapped["Employee"] = relationship()

    __table_args__ = (Index("ix_leave_requests_employee", "employee_id"),)


class Payroll(Base, TimestampMixin):
    """One monthly payroll run line for one employee."""

    __tablename__ = "payroll"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    basic: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    allowances: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    deductions: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    net_pay: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="basic + allowances - deductions, paid out to the employee."
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, processed, paid."
    )
    paid_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    employee: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index(
            "ux_payroll_employee_period",
            "employee_id",
            "period_year",
            "period_month",
            unique=True,
        ),
    )


class EmployeePerformance(Base, TimestampMixin):
    """A periodic performance review score for one employee."""

    __tablename__ = "employee_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    review_period: Mapped[str] = mapped_column(String(30), nullable=False, comment="e.g. 'Q1-2026'.")
    score: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, comment="Performance score, typically 0.00-5.00."
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    employee: Mapped["Employee"] = relationship()

    __table_args__ = (Index("ix_employee_performance_employee", "employee_id"),)
