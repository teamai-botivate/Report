"""Order-to-delivery domain: packing, dispatch, shipment and delivery
tracking, closing the loop from `sales_orders` (imported from
`app.models.sales`) through to the customer's doorstep, including delivery
delay tracking used by the 'Delivery Delay' semantic measure
(actual_delivery_date - expected_delivery_date)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Employee
from app.models.mixins import TimestampMixin
from app.models.sales import SalesOrder


class Packing(Base, TimestampMixin):
    """Packing/staging step for a sales order prior to dispatch."""

    __tablename__ = "packings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    packed_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, in_progress, completed."
    )
    packages_count: Mapped[int] = mapped_column(Integer, default=1)

    sales_order: Mapped["SalesOrder"] = relationship()

    __table_args__ = (Index("ix_packings_sales_order", "sales_order_id"),)


class Dispatch(Base, TimestampMixin):
    """Dispatch of a packed sales order from the branch/warehouse."""

    __tablename__ = "dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    dispatch_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    vehicle_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dispatched_by_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, dispatched, in_transit."
    )

    sales_order: Mapped["SalesOrder"] = relationship()
    dispatched_by: Mapped["Employee | None"] = relationship()

    __table_args__ = (
        Index("ix_dispatches_sales_order", "sales_order_id"),
        Index("ix_dispatches_dispatched_by", "dispatched_by_employee_id"),
    )


class Shipment(Base, TimestampMixin):
    """Carrier/tracking information for a dispatch."""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), index=True, nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipped_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    dispatch: Mapped["Dispatch"] = relationship()

    __table_args__ = (Index("ix_shipments_dispatch", "dispatch_id"),)


class Delivery(Base, TimestampMixin):
    """Final delivery outcome for a sales order: expected vs. actual delivery
    date, current status, and computed delay in days (0 if on-time/early).
    `delay_days` is the materialized form of the 'Delivery Delay' measure."""

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True, nullable=False)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"), index=True, nullable=False
    )
    expected_delivery_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    actual_delivery_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
        comment="Allowed values: pending, out_for_delivery, delivered, delayed, failed.",
    )
    delay_days: Mapped[int] = mapped_column(
        Integer, default=0, comment="actual_delivery_date - expected_delivery_date, in days; 0 or negative means on-time/early."
    )

    shipment: Mapped["Shipment"] = relationship()
    sales_order: Mapped["SalesOrder"] = relationship()
    delay_log: Mapped[list["DeliveryDelay"]] = relationship(back_populates="delivery")

    __table_args__ = (
        Index("ix_deliveries_shipment", "shipment_id"),
        Index("ix_deliveries_sales_order", "sales_order_id"),
    )


class DeliveryDelay(Base, TimestampMixin):
    """An explanatory delay-reason log entry for a delivery, supporting
    root-cause analysis of late deliveries (a delivery may have more than
    one contributing delay reason logged over time)."""

    __tablename__ = "delivery_delays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Allowed values: traffic, vehicle_breakdown, customer_unavailable, weather, address_issue, warehouse_delay.",
    )
    days_delayed: Mapped[int] = mapped_column(Integer, nullable=False)
    logged_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivery: Mapped["Delivery"] = relationship(back_populates="delay_log")

    __table_args__ = (Index("ix_delivery_delays_delivery", "delivery_id"),)
