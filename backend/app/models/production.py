"""Production domain: work centers, machines, bill of materials, production
orders and their output/rejection/downtime tracking. Products and sales
orders (for make-to-order linkage) are imported from other domain modules."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Branch, Product
from app.models.mixins import TimestampMixin
from app.models.sales import SalesOrder


class WorkCenter(Base, TimestampMixin):
    """A production floor/work area within a branch."""

    __tablename__ = "work_centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)

    branch: Mapped["Branch"] = relationship()

    __table_args__ = (Index("ix_work_centers_branch", "branch_id"),)


class Machine(Base, TimestampMixin):
    """A production machine belonging to a work center."""

    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    work_center_id: Mapped[int] = mapped_column(
        ForeignKey("work_centers.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="operational", comment="Allowed values: operational, under_maintenance, idle, retired."
    )

    work_center: Mapped["WorkCenter"] = relationship()

    __table_args__ = (Index("ix_machines_work_center", "work_center_id"),)


class MachineDowntime(Base, TimestampMixin):
    """A logged downtime event for a machine, used for OEE/availability
    reporting."""

    __tablename__ = "machine_downtime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True, nullable=False)
    start_time: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Allowed values: breakdown, maintenance, changeover, no_material, power_outage."
    )
    downtime_hours: Mapped[float] = mapped_column(Numeric(8, 2), default=0)

    machine: Mapped["Machine"] = relationship()

    __table_args__ = (Index("ix_machine_downtime_machine", "machine_id"),)


class Bom(Base, TimestampMixin):
    """A bill-of-materials header for a finished-good product (versioned)."""

    __tablename__ = "boms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped["Product"] = relationship()
    items: Mapped[list["BomItem"]] = relationship(back_populates="bom")

    __table_args__ = (Index("ix_boms_product", "product_id"),)


class BomItem(Base, TimestampMixin):
    """A single component/quantity line within a BOM."""

    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"), index=True, nullable=False)
    component_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )
    quantity_required: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    bom: Mapped["Bom"] = relationship(back_populates="items")
    component_product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_bom_items_bom", "bom_id"),
        Index("ix_bom_items_component_product", "component_product_id"),
    )


class ProductionOrder(Base, TimestampMixin):
    """A manufacturing order to produce a quantity of a product, optionally
    tied to the sales order that triggered it (make-to-order)."""

    __tablename__ = "production_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    sales_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=True
    )
    quantity_planned: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    planned_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="planned",
        index=True,
        comment="Allowed values: planned, in_progress, completed, on_hold, cancelled.",
    )
    work_center_id: Mapped[int] = mapped_column(
        ForeignKey("work_centers.id"), index=True, nullable=False
    )

    product: Mapped["Product"] = relationship()
    sales_order: Mapped["SalesOrder | None"] = relationship()
    work_center: Mapped["WorkCenter"] = relationship()

    __table_args__ = (
        Index("ix_production_orders_product", "product_id"),
        Index("ix_production_orders_sales_order", "sales_order_id"),
        Index("ix_production_orders_work_center", "work_center_id"),
    )


class ProductionOrderItem(Base, TimestampMixin):
    """A raw-material/component consumption line for a production order
    (actual consumption, vs. the planned BOM quantities)."""

    __tablename__ = "production_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id"), index=True, nullable=False
    )
    component_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )
    quantity_consumed: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    production_order: Mapped["ProductionOrder"] = relationship()
    component_product: Mapped["Product"] = relationship()

    __table_args__ = (
        Index("ix_production_order_items_order", "production_order_id"),
        Index("ix_production_order_items_component", "component_product_id"),
    )


class ProductionOutput(Base, TimestampMixin):
    """A completed-goods output record for a production order on a given date,
    optionally attributed to the machine that produced it."""

    __tablename__ = "production_output"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id"), index=True, nullable=False
    )
    output_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    quantity_produced: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("machines.id"), index=True, nullable=True
    )

    production_order: Mapped["ProductionOrder"] = relationship()
    machine: Mapped["Machine | None"] = relationship()

    __table_args__ = (
        Index("ix_production_output_order", "production_order_id"),
        Index("ix_production_output_machine", "machine_id"),
    )


class ProductionRejection(Base, TimestampMixin):
    """Quality-rejected quantity for a production order, the numerator of the
    'Production Rejection %' semantic measure."""

    __tablename__ = "production_rejections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id"), index=True, nullable=False
    )
    rejection_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    quantity_rejected: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Allowed values: quality_defect, dimension_mismatch, material_fault, process_error."
    )

    production_order: Mapped["ProductionOrder"] = relationship()

    __table_args__ = (Index("ix_production_rejections_order", "production_order_id"),)
