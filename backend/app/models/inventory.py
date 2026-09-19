"""Inventory domain: stock levels, movements, transfers, batches and
adjustments. Products/warehouses/categories are master data imported from
`app.models.master`."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.master import Product, Warehouse
from app.models.mixins import TimestampMixin


class Stock(Base, TimestampMixin):
    """Current on-hand/reserved stock quantity for a product at a warehouse.
    One row per (product, warehouse) pair."""

    __tablename__ = "stock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    quantity_on_hand: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0, comment="Physical quantity currently in the warehouse."
    )
    quantity_reserved: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0, comment="Quantity earmarked against open sales orders."
    )

    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        Index("ux_stock_product_warehouse", "product_id", "warehouse_id", unique=True),
    )


class StockMovement(Base, TimestampMixin):
    """An immutable ledger entry for any stock-affecting event (receipt,
    dispatch, adjustment, transfer leg, production consumption/output)."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    movement_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Allowed values: receipt, dispatch, adjustment, transfer_in, transfer_out, production_in, production_out.",
    )
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Name of the source table, e.g. 'material_receipts'."
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    movement_date: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)

    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        Index("ix_stock_movements_product", "product_id"),
        Index("ix_stock_movements_warehouse", "warehouse_id"),
    )


class StockTransfer(Base, TimestampMixin):
    """A stock transfer of a product between two warehouses."""

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    from_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    to_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    transfer_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="Allowed values: pending, in_transit, completed, cancelled."
    )

    product: Mapped["Product"] = relationship()
    from_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[to_warehouse_id])

    __table_args__ = (
        Index("ix_stock_transfers_product", "product_id"),
        Index("ix_stock_transfers_from_warehouse", "from_warehouse_id"),
        Index("ix_stock_transfers_to_warehouse", "to_warehouse_id"),
    )


class MaterialBatch(Base, TimestampMixin):
    """A tracked batch/lot of a product at a warehouse, with optional
    manufacture/expiry dates for shelf-life-sensitive materials."""

    __tablename__ = "material_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    batch_code: Mapped[str] = mapped_column(String(50), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    manufactured_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)

    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        Index("ix_material_batches_product", "product_id"),
        Index("ix_material_batches_warehouse", "warehouse_id"),
    )


class InventoryAdjustment(Base, TimestampMixin):
    """A manual stock correction (write-off, stock-count reconciliation, etc.)."""

    __tablename__ = "inventory_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), index=True, nullable=False
    )
    adjustment_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Allowed values: increase, decrease."
    )
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjusted_on: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    product: Mapped["Product"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        Index("ix_inventory_adjustments_product", "product_id"),
        Index("ix_inventory_adjustments_warehouse", "warehouse_id"),
    )
