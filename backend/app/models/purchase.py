"""Purchase domain: the procure-to-pay chain.

Purchase Requisition -> Purchase Order -> (PO Items) -> Material Receipt ->
Supplier Invoice -> Supplier Payment, plus Returns. Suppliers/products/
employees/warehouses/departments are master data imported from
`app.models.master`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Department, Employee, Product, Supplier, Warehouse
from app.models.mixins import TimestampMixin


class PurchaseRequisition(Base, TimestampMixin):
    """An internal request to purchase a product, the entry point of the
    procurement chain."""

    __tablename__ = "purchase_requisitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requisition_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    requested_by_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, comment="Allowed values: pending, approved, rejected, converted."
    )
    requested_on: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=True
    )

    product: Mapped["Product"] = relationship()
    requested_by: Mapped["Employee"] = relationship()
    department: Mapped["Department | None"] = relationship()

    __table_args__ = (
        Index("ix_purchase_requisitions_product", "product_id"),
        Index("ix_purchase_requisitions_requested_by", "requested_by_employee_id"),
        Index("ix_purchase_requisitions_department", "department_id"),
    )


class PurchaseOrder(Base, TimestampMixin):
    """A purchase order issued to a supplier, optionally originating from a
    requisition."""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    requisition_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_requisitions.id"), index=True, nullable=True
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True, nullable=False)
    order_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="draft",
        index=True,
        comment="Allowed values: draft, approved, sent, partially_received, received, cancelled.",
    )
    total_amount: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Order value; the basis for the 'Purchase Value' semantic measure."
    )
    expected_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    requisition: Mapped["PurchaseRequisition | None"] = relationship()
    supplier: Mapped["Supplier"] = relationship()
    items: Mapped[list["PurchaseOrderItem"]] = relationship(back_populates="purchase_order")

    __table_args__ = (
        Index("ix_purchase_orders_supplier", "supplier_id"),
        Index("ix_purchase_orders_requisition", "requisition_id"),
        Index("ix_purchase_orders_order_date", "order_date"),
    )


class PurchaseOrderItem(Base, TimestampMixin):
    """One product line on a purchase order."""

    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_purchase_order_items_order", "purchase_order_id"),
        Index("ix_purchase_order_items_product", "product_id"),
    )


class MaterialReceipt(Base, TimestampMixin):
    """A goods-receipt note (GRN): materials physically received against a
    purchase order into a warehouse. Modeled as one row per product line
    (rather than a separate line-items table) to keep the receiving flow
    simple; `product_id`/`quantity_*` describe that single line."""

    __tablename__ = "material_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grn_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    received_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    quantity_received: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    quantity_accepted: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    quantity_rejected: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, partial, completed."
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship()
    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        Index("ix_material_receipts_order", "purchase_order_id"),
        Index("ix_material_receipts_warehouse", "warehouse_id"),
        Index("ix_material_receipts_product", "product_id"),
    )


class SupplierInvoice(Base, TimestampMixin):
    """An invoice raised by a supplier against a purchase order."""

    __tablename__ = "supplier_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True, nullable=False)
    invoice_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="unpaid", index=True, comment="Allowed values: unpaid, partially_paid, paid, overdue."
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship()
    supplier: Mapped["Supplier"] = relationship()

    __table_args__ = (
        Index("ix_supplier_invoices_order", "purchase_order_id"),
        Index("ix_supplier_invoices_supplier", "supplier_id"),
    )


class SupplierPayment(Base, TimestampMixin):
    """A payment made against a supplier invoice."""

    __tablename__ = "supplier_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_invoice_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_invoices.id"), index=True, nullable=False
    )
    payment_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="Allowed values: bank_transfer, cheque, cash, card, upi."
    )

    supplier_invoice: Mapped["SupplierInvoice"] = relationship()

    __table_args__ = (Index("ix_supplier_payments_invoice", "supplier_invoice_id"),)


class PurchaseReturn(Base, TimestampMixin):
    """A product return sent back to a supplier against a purchase order."""

    __tablename__ = "purchase_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    purchase_order: Mapped["PurchaseOrder"] = relationship()
    product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_purchase_returns_order", "purchase_order_id"),
        Index("ix_purchase_returns_product", "product_id"),
    )
