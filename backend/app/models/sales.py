"""Sales domain: the lead-to-cash chain.

Lead -> Enquiry -> Quotation -> Sales Order -> (Order Items) -> Invoice ->
Payment, plus Returns and Targets. Customers/products/employees/branches are
master data imported from `app.models.master`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Branch, City, Customer, Employee, Product
from app.models.mixins import TimestampMixin


class Lead(Base, TimestampMixin):
    """A prospective customer lead, the entry point of the sales funnel."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    source: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Allowed values: website, referral, cold_call, exhibition, ad_campaign."
    )
    status: Mapped[str] = mapped_column(
        String(20), default="new", index=True, comment="Allowed values: new, contacted, qualified, converted, lost."
    )
    owner_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    created_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    estimated_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    city: Mapped["City"] = relationship()
    owner: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_leads_city", "city_id"),
        Index("ix_leads_owner", "owner_employee_id"),
    )


class Enquiry(Base, TimestampMixin):
    """A concrete product enquiry, optionally sourced from a lead or an
    existing customer."""

    __tablename__ = "enquiries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enquiry_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True, nullable=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), index=True, nullable=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="open", index=True, comment="Allowed values: open, quoted, closed, dropped."
    )
    created_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    owner_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )

    lead: Mapped["Lead | None"] = relationship()
    customer: Mapped["Customer | None"] = relationship()
    product: Mapped["Product"] = relationship()
    owner: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_enquiries_lead", "lead_id"),
        Index("ix_enquiries_customer", "customer_id"),
        Index("ix_enquiries_product", "product_id"),
        Index("ix_enquiries_owner", "owner_employee_id"),
    )


class Quotation(Base, TimestampMixin):
    """A price quotation issued to a customer in response to an enquiry."""

    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    enquiry_id: Mapped[int] = mapped_column(ForeignKey("enquiries.id"), index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Quoted total value.")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True, comment="Allowed values: draft, sent, accepted, rejected, expired."
    )
    valid_until: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    owner_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )

    enquiry: Mapped["Enquiry"] = relationship()
    customer: Mapped["Customer"] = relationship()
    owner: Mapped["Employee"] = relationship()

    __table_args__ = (
        Index("ix_quotations_enquiry", "enquiry_id"),
        Index("ix_quotations_customer", "customer_id"),
        Index("ix_quotations_owner", "owner_employee_id"),
    )


class SalesOrder(Base, TimestampMixin):
    """A confirmed sales order, the anchor of the order-to-delivery chain."""

    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id"), index=True, nullable=True
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    salesperson_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    order_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
        comment="Allowed values: pending, confirmed, in_production, dispatched, delivered, cancelled.",
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Order value; the basis for the 'Revenue' semantic measure via invoices."
    )
    expected_delivery_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    quotation: Mapped["Quotation | None"] = relationship()
    customer: Mapped["Customer"] = relationship()
    branch: Mapped["Branch"] = relationship()
    salesperson: Mapped["Employee"] = relationship()
    items: Mapped[list["SalesOrderItem"]] = relationship(back_populates="sales_order")

    __table_args__ = (
        Index("ix_sales_orders_customer", "customer_id"),
        Index("ix_sales_orders_branch", "branch_id"),
        Index("ix_sales_orders_salesperson", "salesperson_id"),
        Index("ix_sales_orders_quotation", "quotation_id"),
        Index("ix_sales_orders_order_date", "order_date"),
    )


class SalesOrderItem(Base, TimestampMixin):
    """One product line on a sales order."""

    __tablename__ = "sales_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_sales_order_items_order", "sales_order_id"),
        Index("ix_sales_order_items_product", "product_id"),
    )


class SalesInvoice(Base, TimestampMixin):
    """A customer invoice raised against a sales order. `total_amount` here is
    the canonical source for the 'Revenue' semantic measure (SUM of valid
    sales invoices)."""

    __tablename__ = "sales_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True, nullable=False)
    invoice_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Invoiced revenue amount; source of the 'Revenue' measure."
    )
    status: Mapped[str] = mapped_column(
        String(20), default="unpaid", index=True, comment="Allowed values: unpaid, partially_paid, paid, overdue, void."
    )

    sales_order: Mapped["SalesOrder"] = relationship()
    customer: Mapped["Customer"] = relationship()

    __table_args__ = (
        Index("ix_sales_invoices_order", "sales_order_id"),
        Index("ix_sales_invoices_customer", "customer_id"),
        Index("ix_sales_invoices_invoice_date", "invoice_date"),
    )


class SalesPayment(Base, TimestampMixin):
    """A payment received against a sales invoice."""

    __tablename__ = "sales_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id"), index=True, nullable=False
    )
    payment_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="Allowed values: bank_transfer, cheque, cash, card, upi."
    )

    sales_invoice: Mapped["SalesInvoice"] = relationship()

    __table_args__ = (Index("ix_sales_payments_invoice", "sales_invoice_id"),)


class SalesReturn(Base, TimestampMixin):
    """A product return against a sales order."""

    __tablename__ = "sales_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    refund_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)

    sales_order: Mapped["SalesOrder"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_sales_returns_order", "sales_order_id"),
        Index("ix_sales_returns_product", "product_id"),
    )


class SalesTarget(Base, TimestampMixin):
    """A monthly revenue target assigned to a salesperson (and optionally a
    branch), the denominator for target-vs-achievement measures."""

    __tablename__ = "sales_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    salesperson_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id"), index=True, nullable=True
    )

    salesperson: Mapped["Employee"] = relationship()
    branch: Mapped["Branch | None"] = relationship()

    __table_args__ = (
        Index("ix_sales_targets_salesperson", "salesperson_id"),
        Index("ix_sales_targets_branch", "branch_id"),
        Index(
            "ux_sales_targets_person_period",
            "salesperson_id",
            "period_year",
            "period_month",
            unique=True,
        ),
    )
