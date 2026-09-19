"""Master data domain.

Holds the reference/dimension entities every other business module hangs
off of: geography (regions/cities), organizational structure (branches,
departments, designations), product catalog, warehouses, customers,
suppliers, employees, and the calendar date-dimension table used for
period-over-period analytics (month/quarter/year rollups, fiscal year,
weekend flags, etc.).

IMPORTANT: this module must have zero imports from other `app.models.*`
domain modules — everything else imports FROM here, never the reverse,
to keep the import graph a DAG.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin


class Region(Base, TimestampMixin):
    """A geographic sales/reporting region (e.g. North, South, East, West)."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    cities: Mapped[list["City"]] = relationship(back_populates="region")


class City(Base, TimestampMixin):
    """A city, scoped to a region. Customers, suppliers and branches locate here."""

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="India", nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True, nullable=False)

    region: Mapped["Region"] = relationship(back_populates="cities")

    __table_args__ = (Index("ix_cities_region", "region_id"),)


class Branch(Base, TimestampMixin):
    """A physical company branch/office location that employees and orders belong to."""

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    city: Mapped["City"] = relationship()


class Department(Base, TimestampMixin):
    """An organizational department (Sales, Purchase, HR, Production, ...)."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)


class Designation(Base, TimestampMixin):
    """A job title/grade (e.g. Sales Executive, Manager)."""

    __tablename__ = "designations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, comment="Seniority level, 1=junior-most.")


class Warehouse(Base, TimestampMixin):
    """A physical stock-holding location, tied to a branch."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    branch: Mapped["Branch"] = relationship()


class ProductCategory(Base, TimestampMixin):
    """A (self-referencing) product category/sub-category hierarchy."""

    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_categories.id"), index=True, nullable=True
    )

    parent: Mapped["ProductCategory | None"] = relationship(remote_side=[id])


class Product(Base, TimestampMixin):
    """A sellable/purchasable/manufacturable SKU, the hub of the sales, purchase,
    inventory and production domains."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("product_categories.id"), index=True, nullable=False
    )
    unit: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    unit_price: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Standard selling price per unit."
    )
    unit_cost: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Standard cost price per unit, used for margin calcs."
    )
    reorder_level: Mapped[float] = mapped_column(
        Numeric(14, 2), default=50, comment="Stock quantity threshold that triggers a reorder alert."
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped["ProductCategory"] = relationship()

    __table_args__ = (Index("ix_products_category", "category_id"),)


class Customer(Base, TimestampMixin):
    """A buying customer entity. Anchors the sales-side transaction chain
    (leads -> enquiries -> quotations -> orders -> invoices -> payments)."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    segment: Mapped[str] = mapped_column(
        String(50), default="SMB", comment="Allowed values: SMB, Enterprise, Government, Retail."
    )
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    city: Mapped["City"] = relationship()

    __table_args__ = (Index("ix_customers_city", "city_id"),)


class Supplier(Base, TimestampMixin):
    """A vendor entity supplying materials/products. Anchors the purchase-side
    transaction chain (requisitions -> POs -> receipts -> invoices -> payments)."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General")
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rating: Mapped[float] = mapped_column(
        Numeric(3, 2), default=3.0, comment="Supplier quality/delivery rating, 0.00-5.00."
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    city: Mapped["City"] = relationship()

    __table_args__ = (Index("ix_suppliers_city", "city_id"),)


class Employee(Base, TimestampMixin):
    """A staff member. Belongs to a department/designation/branch, may report
    to a manager (self-referencing), and participates across HR, sales,
    purchase, production and task modules."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=False
    )
    designation_id: Mapped[int] = mapped_column(
        ForeignKey("designations.id"), index=True, nullable=False
    )
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hire_date: Mapped[dt.date] = mapped_column(Date, nullable=False, comment="Date of joining.")
    status: Mapped[str] = mapped_column(
        String(20), default="active", comment="Allowed values: active, on_leave, terminated."
    )
    base_salary: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, comment="Monthly base salary before allowances/deductions."
    )
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), index=True, nullable=True
    )

    department: Mapped["Department"] = relationship()
    designation: Mapped["Designation"] = relationship()
    branch: Mapped["Branch"] = relationship()
    manager: Mapped["Employee | None"] = relationship(remote_side=[id])

    __table_args__ = (
        Index("ix_employees_department", "department_id"),
        Index("ix_employees_designation", "designation_id"),
        Index("ix_employees_branch", "branch_id"),
        Index("ix_employees_manager", "manager_id"),
        Index("ix_employees_status", "status"),
    )


class CalendarDate(Base):
    """Date-dimension table: one row per calendar day, pre-computed rollup
    attributes (year/quarter/month/week/fiscal year/weekend flag) to make
    time-based grouping and period comparisons in generated SQL simple and
    fast instead of computing them inline in every query."""

    __tablename__ = "calendar_dates"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    month_name: Mapped[str] = mapped_column(String(20), nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    day_name: Mapped[str] = mapped_column(String(20), nullable=False)
    week_of_year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fiscal_year: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="e.g. 'FY2025-26'; fiscal year starts April 1."
    )

    __table_args__ = (Index("ix_calendar_dates_year_month", "year", "month"),)
