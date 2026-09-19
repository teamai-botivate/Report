"""Finance domain: chart of accounts, general-ledger-style transactions,
expenses, and AR/AP tracking.

Sales invoices/payments and supplier invoices/payments already live in
`app.models.sales` / `app.models.purchase` respectively (per CLAUDE.md's
repo layout, this module reuses them rather than duplicating an `invoices`/
`payments` table) — `receivables`/`payables` reference them directly.
Generic, non-sales/purchase cash movements (bank transfers, journal
entries, refunds, ad-hoc receipts) are recorded in
`financial_transactions`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Customer, Department, Employee, Supplier
from app.models.mixins import TimestampMixin
from app.models.purchase import SupplierInvoice
from app.models.sales import SalesInvoice


class Account(Base, TimestampMixin):
    """A chart-of-accounts entry (asset/liability/income/expense/equity)."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Allowed values: asset, liability, income, expense, equity."
    )
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class FinancialTransaction(Base, TimestampMixin):
    """A generic ledger transaction against an account, optionally referencing
    the source document (e.g. reference_type='sales_invoices',
    reference_id=<sales_invoices.id>) that generated it."""

    __tablename__ = "financial_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    transaction_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="Allowed values: debit, credit."
    )
    reference_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Name of the source table this transaction was generated from."
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped["Account"] = relationship()

    __table_args__ = (Index("ix_financial_transactions_account", "account_id"),)


class Expense(Base, TimestampMixin):
    """An operating expense, optionally attributed to a department and
    requiring approval."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Allowed values: travel, utilities, rent, marketing, office_supplies, other."
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    expense_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, approved, rejected, reimbursed."
    )

    department: Mapped["Department | None"] = relationship()
    approved_by: Mapped["Employee | None"] = relationship()

    __table_args__ = (
        Index("ix_expenses_department", "department_id"),
        Index("ix_expenses_approved_by", "approved_by_employee_id"),
    )


class Receivable(Base, TimestampMixin):
    """Money owed BY a customer TO the company, typically generated from a
    sales invoice; tracks aging/collection status."""

    __tablename__ = "receivables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    sales_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_invoices.id"), index=True, nullable=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Outstanding amount owed.")
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, comment="Allowed values: pending, partially_collected, collected, overdue, written_off."
    )

    customer: Mapped["Customer"] = relationship()
    sales_invoice: Mapped["SalesInvoice | None"] = relationship()

    __table_args__ = (
        Index("ix_receivables_customer", "customer_id"),
        Index("ix_receivables_sales_invoice", "sales_invoice_id"),
    )


class Payable(Base, TimestampMixin):
    """Money owed BY the company TO a supplier, typically generated from a
    supplier invoice; tracks aging/payment status."""

    __tablename__ = "payables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True, nullable=False)
    supplier_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_invoices.id"), index=True, nullable=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Outstanding amount owed to the supplier.")
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, comment="Allowed values: pending, partially_paid, paid, overdue."
    )

    supplier: Mapped["Supplier"] = relationship()
    supplier_invoice: Mapped["SupplierInvoice | None"] = relationship()

    __table_args__ = (
        Index("ix_payables_supplier", "supplier_id"),
        Index("ix_payables_supplier_invoice", "supplier_invoice_id"),
    )
