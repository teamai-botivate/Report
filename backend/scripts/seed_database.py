"""Realistic, interconnected demo-data generator for the AI-native BI platform.

This is NOT a "random row per table" generator. It builds business process
chains that actually reference each other via foreign keys, so that the AI
chat demo can answer questions like "show delayed deliveries", "which
products are below reorder level", "attendance % this month", "production
rejection rate by machine", "top customers by revenue this year vs last
year", etc. with real, coherent data.

Chains built (per prompt.txt section 4 / CLAUDE.md):
    Lead -> Enquiry -> Quotation -> SalesOrder -> SalesOrderItem(s)
          -> ProductionOrder -> ProductionOrderItem -> ProductionOutput / ProductionRejection
          -> Packing -> Dispatch -> Shipment -> Delivery (+ DeliveryDelay)
          -> SalesInvoice -> SalesPayment -> Receivable (+ occasional SalesReturn)

    PurchaseRequisition -> PurchaseOrder -> PurchaseOrderItem(s)
          -> MaterialReceipt -> SupplierInvoice -> SupplierPayment -> Payable
          (+ occasional PurchaseReturn)

Master data is seeded first, in FK dependency order:
    regions -> cities -> branches -> departments -> designations ->
    warehouses -> product_categories -> products -> customers -> suppliers
    -> employees -> calendar_dates (full date range)

Not every lead completes the funnel - realistic drop-off is modeled via the
CONVERSION RATES below. Dates skew toward the present so "this month" /
"last month" style queries have a healthy amount of data.

Usage (from backend/):
    python -m scripts.seed_database                 # uses SEED_SIZE env / Settings default
    SEED_SIZE=small python -m scripts.seed_database
    python -m scripts.seed_database --size large

Programmatic (used by app/core/bootstrap.py):
    from scripts.seed_database import seed_all
    await seed_all("small")
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker  # noqa: E402

from app.db.session import AsyncSessionLocal, Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers all tables on Base.metadata)
from app.models.finance import (  # noqa: E402
    Account,
    Expense,
    FinancialTransaction,
    Payable,
    Receivable,
)
from app.models.hr import (  # noqa: E402
    Attendance,
    EmployeePerformance,
    LeaveRequest,
    Payroll,
)
from app.models.inventory import (  # noqa: E402
    InventoryAdjustment,
    MaterialBatch,
    Stock,
    StockMovement,
    StockTransfer,
)
from app.models.master import (  # noqa: E402
    Branch,
    CalendarDate,
    City,
    Customer,
    Department,
    Designation,
    Employee,
    Product,
    ProductCategory,
    Region,
    Supplier,
    Warehouse,
)
from app.models.order_to_delivery import (  # noqa: E402
    Delivery,
    DeliveryDelay,
    Dispatch,
    Packing,
    Shipment,
)
from app.models.production import (  # noqa: E402
    Bom,
    BomItem,
    Machine,
    MachineDowntime,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOutput,
    ProductionRejection,
    WorkCenter,
)
from app.models.purchase import (  # noqa: E402
    MaterialReceipt,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseRequisition,
    PurchaseReturn,
    SupplierInvoice,
    SupplierPayment,
)
from app.models.sales import (  # noqa: E402
    Enquiry,
    Lead,
    Quotation,
    SalesInvoice,
    SalesOrder,
    SalesOrderItem,
    SalesPayment,
    SalesReturn,
    SalesTarget,
)
from app.models.tasks import (  # noqa: E402
    Task,
    TaskAssignment,
    TaskCategory,
    TaskComment,
    TaskPriority,
    TaskStatusHistory,
)

# --------------------------------------------------------------------------
# Volume targets per size (see CLAUDE.md "Status": large ~= 200 employees /
# 800 customers / 1500 leads / 300 products, verified end-to-end in ~60s).
# --------------------------------------------------------------------------

SIZE_CONFIG: dict[str, dict] = {
    "small": dict(
        employees=25, customers=60, suppliers=25, products=40, leads=80,
        years_back=2, cities=15, branches=4, warehouses=5,
        attendance_days_back=60,
    ),
    "medium": dict(
        employees=50, customers=150, suppliers=40, products=80, leads=300,
        years_back=3, cities=25, branches=8, warehouses=10,
        attendance_days_back=180,
    ),
    "large": dict(
        employees=200, customers=800, suppliers=120, products=300, leads=1500,
        years_back=3, cities=45, branches=16, warehouses=20,
        attendance_days_back=270,
    ),
}

RANDOM_SEED = 42

# Conversion / realism rates -------------------------------------------------
LEAD_TO_ENQUIRY_RATE = 0.60
ENQUIRY_TO_QUOTATION_RATE = 0.50
QUOTATION_TO_ORDER_RATE = 0.40
ORDER_CANCEL_RATE = 0.06
DELIVERY_LATE_RATE = 0.18
PRODUCTION_REJECTION_RATE_RANGE = (0.01, 0.06)
LOW_STOCK_RATE = 0.18
ATTENDANCE_PRESENT_RATE = 0.86
ATTENDANCE_HALFDAY_RATE = 0.04
ATTENDANCE_LEAVE_RATE = 0.04
# remainder -> absent

BATCH_SIZE = 500

DEPARTMENTS = [
    ("Sales", "SAL"), ("Purchase", "PUR"), ("Production", "PRD"),
    ("Warehouse", "WHS"), ("Finance", "FIN"), ("HR", "HR"),
    ("Quality", "QA"), ("Logistics", "LOG"), ("IT", "IT"), ("Admin", "ADM"),
]
DESIGNATIONS = [
    ("Executive", 1), ("Senior Executive", 2), ("Assistant Manager", 3),
    ("Manager", 4), ("Senior Manager", 5), ("General Manager", 6),
    ("Director", 7),
]
PRODUCT_CATEGORIES = [
    "Raw Materials", "Fasteners", "Electronics", "Packaging",
    "Finished Goods - Industrial", "Finished Goods - Consumer",
    "Machinery Spares", "Chemicals", "Textiles", "Tools",
]
FINISHED_CATEGORY_NAMES = {"Finished Goods - Industrial", "Finished Goods - Consumer"}
LEAD_SOURCES = ["website", "referral", "cold_call", "exhibition", "ad_campaign"]
CUSTOMER_SEGMENTS = ["SMB", "Enterprise", "Government", "Retail"]
SUPPLIER_CATEGORIES = ["Raw Material", "Packaging", "Electronics", "Logistics", "General", "Services"]
PAYMENT_METHODS = ["bank_transfer", "cheque", "cash", "card", "upi"]
LEAVE_TYPES = ["casual", "sick", "earned", "unpaid"]
EXPENSE_CATEGORIES = ["travel", "utilities", "rent", "marketing", "office_supplies", "other"]
TASK_CATEGORIES = ["Sales Follow-up", "Production", "Quality Check", "Logistics", "Admin", "Finance", "HR"]
TASK_PRIORITIES = [("Low", 1), ("Medium", 2), ("High", 3), ("Urgent", 4)]
DELAY_REASONS = ["traffic", "vehicle_breakdown", "customer_unavailable", "weather", "address_issue", "warehouse_delay"]
DOWNTIME_REASONS = ["breakdown", "maintenance", "changeover", "no_material", "power_outage"]

REGION_NAMES = ["North", "South", "East", "West", "Central"]
INDIAN_CITIES_BY_REGION = {
    "North": ["Delhi", "Chandigarh", "Jaipur", "Lucknow", "Ludhiana", "Kanpur", "Agra", "Dehradun"],
    "South": ["Bengaluru", "Chennai", "Hyderabad", "Coimbatore", "Kochi", "Madurai", "Vijayawada", "Mysuru"],
    "East": ["Kolkata", "Patna", "Bhubaneswar", "Guwahati", "Ranchi", "Siliguri"],
    "West": ["Mumbai", "Pune", "Ahmedabad", "Surat", "Nagpur", "Nashik", "Vadodara", "Rajkot"],
    "Central": ["Bhopal", "Indore", "Raipur", "Jabalpur", "Gwalior"],
}


def fiscal_year_for(d: dt.date) -> str:
    """Fiscal year starts 1 April. A date in Jan-Mar belongs to the fiscal
    year that started the previous April, e.g. 2025-02-01 -> FY2024-25."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY{start}-{str(start + 1)[-2:]}"


def daterange(start: dt.date, end: dt.date):
    cur = start
    one = dt.timedelta(days=1)
    while cur <= end:
        yield cur
        cur += one


def clamp_date(d: dt.date, today: dt.date) -> dt.date:
    return d if d <= today else today


class SeedContext:
    """Holds ids/rows produced by each stage so later stages can reference
    them without re-querying the DB."""

    def __init__(self, size: str, rng: random.Random, fake: Faker, today: dt.date):
        self.size = size
        self.cfg = SIZE_CONFIG[size]
        self.rng = rng
        self.fake = fake
        self.today = today
        self.start_date = today.replace(year=today.year - self.cfg["years_back"])

        self.regions: list[int] = []
        self.cities: list[int] = []
        self.branches: list[int] = []
        self.departments: dict[str, int] = {}
        self.designations: list[int] = []
        self.warehouses: list[int] = []
        self.categories: dict[str, int] = {}
        self.products: list[dict] = []
        self.customers: list[int] = []
        self.suppliers: list[int] = []
        self.employees: list[dict] = []
        self.sales_employees: list[int] = []
        self.purchase_employees: list[int] = []
        self.logistics_employees: list[int] = []
        self.work_centers: list[int] = []
        self.machines: list[int] = []
        self.bom_by_product: dict[int, int] = {}

        self.counts: dict[str, int] = {}

    def record(self, table: str, n: int) -> None:
        self.counts[table] = self.counts.get(table, 0) + n


async def _bulk_add(session, objects: list) -> None:
    """Add objects in batches, flushing (to populate autoincrement ids) and
    committing periodically. Cheap enough for small/medium/large tiers while
    avoiding one-commit-per-row overhead."""
    if not objects:
        return
    for i in range(0, len(objects), BATCH_SIZE):
        chunk = objects[i : i + BATCH_SIZE]
        session.add_all(chunk)
        await session.flush()
    await session.commit()


# --------------------------------------------------------------------------
# Master data
# --------------------------------------------------------------------------

async def seed_master_data(session, ctx: SeedContext) -> None:
    cfg = ctx.cfg

    regions = [Region(name=n) for n in REGION_NAMES]
    await _bulk_add(session, regions)
    ctx.regions = [r.id for r in regions]
    region_by_name = {r.name: r.id for r in regions}
    ctx.record("regions", len(regions))

    all_city_names: list[tuple[str, str]] = []
    for region_name, city_list in INDIAN_CITIES_BY_REGION.items():
        for c in city_list:
            all_city_names.append((c, region_name))
    while len(all_city_names) < cfg["cities"]:
        region_name = ctx.rng.choice(REGION_NAMES)
        all_city_names.append((ctx.fake.city(), region_name))
    all_city_names = all_city_names[: cfg["cities"]]

    cities = [
        City(name=name, state=None, country="India", region_id=region_by_name[region_name])
        for name, region_name in all_city_names
    ]
    await _bulk_add(session, cities)
    ctx.cities = [c.id for c in cities]
    ctx.record("cities", len(cities))

    branch_cities = ctx.rng.sample(ctx.cities, k=min(cfg["branches"], len(ctx.cities)))
    branches = [
        Branch(name=f"Branch {i + 1}", code=f"BR{i + 1:03d}", city_id=city_id, is_active=True)
        for i, city_id in enumerate(branch_cities)
    ]
    await _bulk_add(session, branches)
    ctx.branches = [b.id for b in branches]
    ctx.record("branches", len(branches))

    departments = [Department(name=name, code=code) for name, code in DEPARTMENTS]
    await _bulk_add(session, departments)
    ctx.departments = {d.code: d.id for d in departments}
    ctx.record("departments", len(departments))

    designations = [Designation(title=title, level=level) for title, level in DESIGNATIONS]
    await _bulk_add(session, designations)
    ctx.designations = [d.id for d in designations]
    ctx.record("designations", len(designations))

    warehouses = [
        Warehouse(name=f"Warehouse {i + 1}", code=f"WH{i + 1:03d}", branch_id=ctx.rng.choice(ctx.branches), is_active=True)
        for i in range(cfg["warehouses"])
    ]
    await _bulk_add(session, warehouses)
    ctx.warehouses = [w.id for w in warehouses]
    ctx.record("warehouses", len(warehouses))

    categories = [ProductCategory(name=name) for name in PRODUCT_CATEGORIES]
    await _bulk_add(session, categories)
    ctx.categories = {c.name: c.id for c in categories}
    ctx.record("product_categories", len(categories))
    finished_category_ids = {ctx.categories[n] for n in FINISHED_CATEGORY_NAMES}

    products = []
    for i in range(cfg["products"]):
        cat_name = ctx.rng.choice(PRODUCT_CATEGORIES)
        cat_id = ctx.categories[cat_name]
        unit_cost = round(ctx.rng.uniform(10, 5000), 2)
        margin = ctx.rng.uniform(1.15, 1.8)
        unit_price = round(unit_cost * margin, 2)
        products.append(
            Product(
                sku=f"SKU-{i + 1:05d}",
                name=f"{ctx.fake.word().capitalize()} {cat_name.split(' - ')[-1][:12]} {i + 1}",
                category_id=cat_id,
                unit=ctx.rng.choice(["pcs", "kg", "box", "ltr", "set"]),
                unit_price=unit_price,
                unit_cost=unit_cost,
                reorder_level=round(ctx.rng.uniform(20, 200), 0),
                is_active=ctx.rng.random() > 0.05,
            )
        )
    await _bulk_add(session, products)
    for p in products:
        ctx.products.append(
            dict(
                id=p.id,
                category_id=p.category_id,
                unit_price=float(p.unit_price),
                unit_cost=float(p.unit_cost),
                reorder_level=float(p.reorder_level),
                is_finished=p.category_id in finished_category_ids,
            )
        )
    ctx.record("products", len(products))

    customers = []
    for i in range(cfg["customers"]):
        customers.append(
            Customer(
                code=f"CUST{i + 1:05d}",
                name=ctx.fake.company(),
                city_id=ctx.rng.choice(ctx.cities),
                segment=ctx.rng.choice(CUSTOMER_SEGMENTS),
                email=ctx.fake.company_email(),
                phone=ctx.fake.phone_number()[:30],
                is_active=ctx.rng.random() > 0.05,
            )
        )
    await _bulk_add(session, customers)
    ctx.customers = [c.id for c in customers]
    ctx.record("customers", len(customers))

    suppliers = []
    for i in range(cfg["suppliers"]):
        suppliers.append(
            Supplier(
                code=f"SUPP{i + 1:05d}",
                name=ctx.fake.company(),
                city_id=ctx.rng.choice(ctx.cities),
                category=ctx.rng.choice(SUPPLIER_CATEGORIES),
                email=ctx.fake.company_email(),
                phone=ctx.fake.phone_number()[:30],
                rating=round(ctx.rng.uniform(2.0, 5.0), 2),
                is_active=ctx.rng.random() > 0.05,
            )
        )
    await _bulk_add(session, suppliers)
    ctx.suppliers = [s.id for s in suppliers]
    ctx.record("suppliers", len(suppliers))

    print(
        f"  master data: {len(regions)} regions, {len(cities)} cities, {len(branches)} branches, "
        f"{len(departments)} departments, {len(designations)} designations, {len(warehouses)} warehouses, "
        f"{len(categories)} categories, {len(products)} products, {len(customers)} customers, "
        f"{len(suppliers)} suppliers"
    )


async def seed_employees(session, ctx: SeedContext) -> None:
    cfg = ctx.cfg
    dept_ids = list(ctx.departments.values())

    employees_orm = []
    for i in range(cfg["employees"]):
        hire_date = ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today)
        employees_orm.append(
            Employee(
                employee_code=f"EMP{i + 1:05d}",
                name=ctx.fake.name(),
                department_id=ctx.rng.choice(dept_ids),
                designation_id=ctx.rng.choice(ctx.designations),
                branch_id=ctx.rng.choice(ctx.branches),
                email=ctx.fake.email(),
                phone=ctx.fake.phone_number()[:30],
                hire_date=hire_date,
                status="active" if ctx.rng.random() > 0.06 else "on_leave",
                base_salary=round(ctx.rng.uniform(20000, 200000), 2),
                manager_id=None,
            )
        )
    await _bulk_add(session, employees_orm)

    # Simple hierarchy: later-created employees may report to an earlier one.
    ids = [e.id for e in employees_orm]
    for idx, emp in enumerate(employees_orm):
        if idx < max(1, len(employees_orm) // 10):
            continue
        if ctx.rng.random() < 0.85:
            candidate_pool = ids[: max(1, idx)]
            manager_id = ctx.rng.choice(candidate_pool)
            if manager_id != emp.id:
                emp.manager_id = manager_id
    await session.commit()

    for e in employees_orm:
        ctx.employees.append(dict(id=e.id, department_id=e.department_id, branch_id=e.branch_id))
    ctx.record("employees", len(employees_orm))

    sales_dept_id = ctx.departments.get("SAL")
    ctx.sales_employees = [e["id"] for e in ctx.employees if e["department_id"] == sales_dept_id] or [e["id"] for e in ctx.employees]
    purchase_dept_id = ctx.departments.get("PUR")
    ctx.purchase_employees = [e["id"] for e in ctx.employees if e["department_id"] == purchase_dept_id] or [e["id"] for e in ctx.employees]
    logistics_dept_id = ctx.departments.get("LOG")
    ctx.logistics_employees = [e["id"] for e in ctx.employees if e["department_id"] == logistics_dept_id] or [e["id"] for e in ctx.employees]

    print(f"  employees: {len(employees_orm)}")


async def seed_calendar(session, ctx: SeedContext) -> None:
    cal_rows = []
    for d in daterange(ctx.start_date, ctx.today):
        iso = d.isocalendar()
        cal_rows.append(
            CalendarDate(
                date=d,
                year=d.year,
                quarter=(d.month - 1) // 3 + 1,
                month=d.month,
                month_name=d.strftime("%B"),
                day=d.day,
                day_name=d.strftime("%A"),
                week_of_year=iso[1],
                is_weekend=d.weekday() >= 5,
                fiscal_year=fiscal_year_for(d),
            )
        )
    await _bulk_add(session, cal_rows)
    ctx.record("calendar_dates", len(cal_rows))
    print(f"  calendar_dates: {len(cal_rows)} days ({ctx.start_date} .. {ctx.today})")


# --------------------------------------------------------------------------
# HR domain (attendance / leave / payroll / performance)
# --------------------------------------------------------------------------

async def seed_hr(session, ctx: SeedContext) -> None:
    cfg = ctx.cfg
    employee_ids = [e["id"] for e in ctx.employees]

    attendance_start = max(ctx.start_date, ctx.today - dt.timedelta(days=cfg["attendance_days_back"]))
    attendance_days = [d for d in daterange(attendance_start, ctx.today) if d.weekday() < 5]

    attendance_rows = []
    for emp_id in employee_ids:
        for d in attendance_days:
            r = ctx.rng.random()
            if r < ATTENDANCE_PRESENT_RATE:
                status = "present"
                check_in = dt.datetime.combine(d, dt.time(hour=ctx.rng.randint(8, 10), minute=ctx.rng.randint(0, 59)))
                check_out = check_in + dt.timedelta(hours=ctx.rng.uniform(7.5, 9.5))
                hours = round((check_out - check_in).total_seconds() / 3600, 2)
            elif r < ATTENDANCE_PRESENT_RATE + ATTENDANCE_LEAVE_RATE:
                status, check_in, check_out, hours = "on_leave", None, None, 0
            elif r < ATTENDANCE_PRESENT_RATE + ATTENDANCE_LEAVE_RATE + ATTENDANCE_HALFDAY_RATE:
                check_in = dt.datetime.combine(d, dt.time(9, 0))
                check_out = check_in + dt.timedelta(hours=4)
                status, hours = "half_day", 4.0
            else:
                status, check_in, check_out, hours = "absent", None, None, 0
            attendance_rows.append(
                Attendance(employee_id=emp_id, date=d, status=status, check_in=check_in, check_out=check_out, hours_worked=hours)
            )
    await _bulk_add(session, attendance_rows)
    ctx.record("attendance", len(attendance_rows))

    leave_rows = []
    for emp_id in employee_ids:
        for _ in range(ctx.rng.randint(0, 4)):
            start = ctx.fake.date_between(start_date=attendance_start, end_date=ctx.today)
            end = start + dt.timedelta(days=ctx.rng.randint(0, 4))
            leave_rows.append(
                LeaveRequest(
                    employee_id=emp_id,
                    leave_type=ctx.rng.choice(LEAVE_TYPES),
                    start_date=start,
                    end_date=end,
                    status=ctx.rng.choice(["approved", "approved", "approved", "pending", "rejected"]),
                    reason=ctx.fake.sentence(nb_words=8),
                    applied_on=dt.datetime.combine(start - dt.timedelta(days=ctx.rng.randint(1, 5)), dt.time(9, 0)),
                )
            )
    await _bulk_add(session, leave_rows)
    ctx.record("leave_requests", len(leave_rows))

    # Payroll: one row per employee per month, for the last N months (bounded
    # for speed - full years_back could be huge for `large`).
    months_back = min(cfg["years_back"] * 12, 15)
    cur = ctx.today.replace(day=1)
    period_list = []
    y, m = cur.year, cur.month
    for _ in range(months_back):
        period_list.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    employees_full = {e["id"]: e for e in ctx.employees}
    payroll_rows = []
    emp_hire_dates = {}
    for e in employees_full.values():
        pass
    # fetch hire dates via a fresh query is unnecessary; recompute is fine since
    # base_salary/hire_date aren't tracked in ctx.employees - use a lightweight
    # SELECT to keep this function self-contained.
    from sqlalchemy import select as _select

    result = await session.execute(_select(Employee.id, Employee.hire_date, Employee.base_salary))
    hire_and_salary = {row[0]: (row[1], float(row[2])) for row in result.all()}

    for emp_id in employee_ids:
        hire_date, base_salary = hire_and_salary[emp_id]
        for (y, m) in period_list:
            if dt.date(y, m, 1) < hire_date.replace(day=1):
                continue
            basic = round(base_salary * 0.6, 2)
            allowances = round(base_salary * ctx.rng.uniform(0.1, 0.3), 2)
            deductions = round(base_salary * ctx.rng.uniform(0.05, 0.15), 2)
            net_pay = round(basic + allowances - deductions, 2)
            is_past = dt.date(y, m, 1) < ctx.today.replace(day=1)
            payroll_rows.append(
                Payroll(
                    employee_id=emp_id,
                    period_month=m,
                    period_year=y,
                    basic=basic,
                    allowances=allowances,
                    deductions=deductions,
                    net_pay=net_pay,
                    status="paid" if is_past else ctx.rng.choice(["paid", "processed", "pending"]),
                    paid_on=dt.date(y, m, min(28, 5)) if is_past else None,
                )
            )
    await _bulk_add(session, payroll_rows)
    ctx.record("payroll", len(payroll_rows))

    perf_rows = []
    for emp_id in employee_ids:
        hire_date, _ = hire_and_salary[emp_id]
        for _ in range(ctx.rng.randint(1, 3)):
            reviewed_on = ctx.fake.date_between(start_date=hire_date, end_date=ctx.today)
            perf_rows.append(
                EmployeePerformance(
                    employee_id=emp_id,
                    review_period=f"Q{(reviewed_on.month - 1) // 3 + 1}-{reviewed_on.year}",
                    score=round(ctx.rng.uniform(2.0, 5.0), 2),
                    remarks=ctx.fake.sentence(nb_words=10),
                    reviewed_on=reviewed_on,
                )
            )
    await _bulk_add(session, perf_rows)
    ctx.record("employee_performance", len(perf_rows))

    print(
        f"  HR: {len(attendance_rows)} attendance, {len(leave_rows)} leave_requests, "
        f"{len(payroll_rows)} payroll, {len(perf_rows)} employee_performance"
    )


# --------------------------------------------------------------------------
# Production infra (work centers / machines / BOM) - needed before sales
# pipeline can create production orders.
# --------------------------------------------------------------------------

async def seed_production_infra(session, ctx: SeedContext) -> None:
    work_centers = [
        WorkCenter(name=f"Work Center {i + 1}", code=f"WC{i + 1:03d}", branch_id=branch_id)
        for i, branch_id in enumerate(ctx.branches)
    ]
    await _bulk_add(session, work_centers)
    ctx.work_centers = [w.id for w in work_centers]
    ctx.record("work_centers", len(work_centers))

    machines = []
    for wc_id in ctx.work_centers:
        for j in range(ctx.rng.randint(2, 4)):
            machines.append(
                Machine(
                    name=f"Machine {wc_id}-{j + 1}",
                    code=f"MC{wc_id:03d}{j + 1}",
                    work_center_id=wc_id,
                    status=ctx.rng.choice(["operational", "operational", "operational", "under_maintenance", "idle"]),
                )
            )
    await _bulk_add(session, machines)
    ctx.machines = [m.id for m in machines]
    ctx.record("machines", len(machines))

    downtime_rows = []
    for m in machines:
        for _ in range(ctx.rng.randint(0, 3)):
            start = dt.datetime.combine(
                ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today),
                dt.time(ctx.rng.randint(0, 20), 0),
            )
            hours = round(ctx.rng.uniform(0.5, 12), 2)
            end = start + dt.timedelta(hours=hours)
            today_end = dt.datetime.combine(ctx.today, dt.time(23, 59))
            downtime_rows.append(
                MachineDowntime(
                    machine_id=m.id,
                    start_time=start,
                    end_time=end if end <= today_end else None,
                    reason=ctx.rng.choice(DOWNTIME_REASONS),
                    downtime_hours=hours,
                )
            )
    await _bulk_add(session, downtime_rows)
    ctx.record("machine_downtime", len(downtime_rows))

    finished = [p for p in ctx.products if p["is_finished"]]
    components = [p for p in ctx.products if not p["is_finished"]]
    bom_rows = []
    bom_item_rows = []
    if components and finished:
        bom_rows = [Bom(product_id=p["id"], version="1.0", is_active=True) for p in finished]
        await _bulk_add(session, bom_rows)
        for bom in bom_rows:
            ctx.bom_by_product[bom.product_id] = bom.id
            chosen = ctx.rng.sample(components, k=min(ctx.rng.randint(2, 5), len(components)))
            for comp in chosen:
                bom_item_rows.append(
                    BomItem(bom_id=bom.id, component_product_id=comp["id"], quantity_required=round(ctx.rng.uniform(1, 10), 2))
                )
        await _bulk_add(session, bom_item_rows)
    ctx.record("boms", len(bom_rows))
    ctx.record("bom_items", len(bom_item_rows))

    print(
        f"  production infra: {len(work_centers)} work_centers, {len(machines)} machines, "
        f"{len(downtime_rows)} machine_downtime, {len(bom_rows)} boms, {len(bom_item_rows)} bom_items"
    )


# --------------------------------------------------------------------------
# Sales pipeline: Lead -> Enquiry -> Quotation -> SalesOrder -> Items
# --------------------------------------------------------------------------

async def seed_sales_pipeline(session, ctx: SeedContext) -> None:
    cfg = ctx.cfg
    n_leads = cfg["leads"]

    leads_orm = []
    for i in range(n_leads):
        created_on = dt.datetime.combine(
            ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today), dt.time(ctx.rng.randint(8, 18), 0)
        )
        leads_orm.append(
            Lead(
                lead_code=f"LD{i + 1:06d}",
                customer_name=ctx.fake.company(),
                city_id=ctx.rng.choice(ctx.cities),
                source=ctx.rng.choice(LEAD_SOURCES),
                status="new",
                owner_employee_id=ctx.rng.choice(ctx.sales_employees),
                created_on=created_on,
                estimated_value=round(ctx.rng.uniform(5000, 500000), 2),
            )
        )
    await _bulk_add(session, leads_orm)
    ctx.record("leads", len(leads_orm))

    # --- Enquiries (subset of leads convert) ---
    enquiries_orm = []
    enquiry_lead_map = []  # (lead, enquiry, product)
    converting_leads = ctx.rng.sample(leads_orm, k=int(len(leads_orm) * LEAD_TO_ENQUIRY_RATE))
    converting_lead_ids = {l.id for l in converting_leads}
    for i, lead in enumerate(converting_leads):
        created_on = lead.created_on + dt.timedelta(days=ctx.rng.randint(1, 10))
        created_on = dt.datetime.combine(clamp_date(created_on.date(), ctx.today), created_on.time())
        product = ctx.rng.choice(ctx.products)
        enq = Enquiry(
            enquiry_code=f"ENQ{i + 1:06d}",
            lead_id=lead.id,
            customer_id=None,
            product_id=product["id"],
            quantity=round(ctx.rng.uniform(5, 500), 2),
            status="open",
            created_on=created_on,
            owner_employee_id=lead.owner_employee_id,
        )
        enquiries_orm.append(enq)
        enquiry_lead_map.append((lead, enq, product))
    await _bulk_add(session, enquiries_orm)
    ctx.record("enquiries", len(enquiries_orm))

    # --- Quotations (subset of enquiries convert; attach a real customer) ---
    quotations_orm = []
    quote_enquiry_map = []  # (quote, enq, product, customer_id)
    converting_enquiries = ctx.rng.sample(enquiry_lead_map, k=int(len(enquiry_lead_map) * ENQUIRY_TO_QUOTATION_RATE))
    for i, (lead, enq, product) in enumerate(converting_enquiries):
        customer_id = ctx.rng.choice(ctx.customers)
        enq.customer_id = customer_id
        created_on = enq.created_on + dt.timedelta(days=ctx.rng.randint(1, 7))
        created_on = dt.datetime.combine(clamp_date(created_on.date(), ctx.today), created_on.time())
        total_amount = round(product["unit_price"] * enq.quantity, 2)
        quote = Quotation(
            quotation_code=f"QT{i + 1:06d}",
            enquiry_id=enq.id,
            customer_id=customer_id,
            total_amount=total_amount,
            status="sent",
            valid_until=created_on.date() + dt.timedelta(days=30),
            created_on=created_on,
            owner_employee_id=enq.owner_employee_id,
        )
        quotations_orm.append(quote)
        quote_enquiry_map.append((quote, enq, product, customer_id))
    await _bulk_add(session, quotations_orm)
    ctx.record("quotations", len(quotations_orm))

    # --- Sales orders (subset of quotations convert) ---
    orders_orm = []
    order_meta = []  # dict(order=, product=, quantity=, customer_id=, cancelled=)
    converting_quotes = ctx.rng.sample(quote_enquiry_map, k=int(len(quote_enquiry_map) * QUOTATION_TO_ORDER_RATE))
    for i, (quote, enq, product, customer_id) in enumerate(converting_quotes):
        order_date = clamp_date(quote.created_on.date() + dt.timedelta(days=ctx.rng.randint(1, 5)), ctx.today)
        expected_delivery = order_date + dt.timedelta(days=ctx.rng.randint(7, 30))
        is_cancelled = ctx.rng.random() < ORDER_CANCEL_RATE
        order = SalesOrder(
            order_code=f"SO{i + 1:06d}",
            quotation_id=quote.id,
            customer_id=customer_id,
            branch_id=ctx.rng.choice(ctx.branches),
            salesperson_id=enq.owner_employee_id,
            order_date=order_date,
            status="cancelled" if is_cancelled else "pending",
            total_amount=quote.total_amount,
            expected_delivery_date=expected_delivery,
        )
        orders_orm.append(order)
        order_meta.append(dict(order=order, product=product, quantity=float(enq.quantity), customer_id=customer_id, cancelled=is_cancelled))
        quote.status = "rejected" if is_cancelled else "accepted"
    await _bulk_add(session, orders_orm)
    ctx.record("sales_orders", len(orders_orm))

    # Backfill lead/enquiry statuses now that fates are known.
    quote_by_enquiry_id = {enq.id: q for (q, enq, _p, _c) in quote_enquiry_map}
    order_by_quote_id = {m["order"].quotation_id: m for m in order_meta}
    for lead, enq, product in enquiry_lead_map:
        q = quote_by_enquiry_id.get(enq.id)
        if q is not None:
            m = order_by_quote_id.get(q.id)
            if m is not None:
                lead.status = "lost" if m["cancelled"] else "converted"
                enq.status = "closed" if m["cancelled"] else "converted"
            else:
                lead.status = "qualified"
                enq.status = "quoted"
        else:
            lead.status = "qualified"
            enq.status = "open"
    for lead in leads_orm:
        if lead.id not in converting_lead_ids:
            lead.status = ctx.rng.choice(["new", "contacted", "lost"])
    await session.commit()

    # --- Sales order items ---
    items_orm = []
    for m in order_meta:
        order = m["order"]
        primary_product = m["product"]
        quantity = max(1.0, m["quantity"])
        unit_price = primary_product["unit_price"]
        items_orm.append(
            SalesOrderItem(sales_order_id=order.id, product_id=primary_product["id"], quantity=quantity, unit_price=unit_price, line_total=round(quantity * unit_price, 2))
        )
        extra_total = 0.0
        if ctx.rng.random() < 0.4:
            for _ in range(ctx.rng.randint(1, 2)):
                extra_product = ctx.rng.choice(ctx.products)
                extra_qty = round(ctx.rng.uniform(1, 50), 2)
                extra_line_total = round(extra_qty * extra_product["unit_price"], 2)
                extra_total += extra_line_total
                items_orm.append(
                    SalesOrderItem(sales_order_id=order.id, product_id=extra_product["id"], quantity=extra_qty, unit_price=extra_product["unit_price"], line_total=extra_line_total)
                )
        if extra_total:
            order.total_amount = round(float(order.total_amount) + extra_total, 2)
    await _bulk_add(session, items_orm)
    ctx.record("sales_order_items", len(items_orm))

    print(
        f"  sales pipeline: {len(leads_orm)} leads, {len(enquiries_orm)} enquiries, "
        f"{len(quotations_orm)} quotations, {len(orders_orm)} sales_orders, {len(items_orm)} sales_order_items"
    )

    ctx.order_meta = [m for m in order_meta if not m["cancelled"]]
    ctx.all_order_meta = order_meta


async def seed_production_orders(session, ctx: SeedContext) -> None:
    """Production orders for sales orders whose product is a finished good."""
    production_orders_orm = []
    po_meta = []
    for i, m in enumerate(ctx.order_meta):
        product = m["product"]
        if not product["is_finished"] or not ctx.work_centers:
            continue
        order = m["order"]
        planned_start = order.order_date
        planned_end = planned_start + dt.timedelta(days=ctx.rng.randint(3, 15))
        status = "completed" if planned_end < ctx.today else ctx.rng.choice(["in_progress", "planned"])
        po = ProductionOrder(
            order_code=f"PRO{i + 1:06d}",
            product_id=product["id"],
            sales_order_id=order.id,
            quantity_planned=m["quantity"],
            planned_start=planned_start,
            planned_end=clamp_date(planned_end, ctx.today) if status != "planned" else planned_end,
            status=status,
            work_center_id=ctx.rng.choice(ctx.work_centers),
        )
        production_orders_orm.append(po)
        po_meta.append(dict(po=po, order=order, product=product, quantity=m["quantity"]))
    await _bulk_add(session, production_orders_orm)
    ctx.record("production_orders", len(production_orders_orm))

    poi_rows = []
    for meta in po_meta:
        bom_id = ctx.bom_by_product.get(meta["product"]["id"])
        if bom_id is None:
            continue
        comps = ctx.rng.sample(ctx.products, k=min(3, len(ctx.products)))
        for comp in comps:
            poi_rows.append(
                ProductionOrderItem(production_order_id=meta["po"].id, component_product_id=comp["id"], quantity_consumed=round(meta["quantity"] * ctx.rng.uniform(0.5, 3), 2))
            )
    await _bulk_add(session, poi_rows)
    ctx.record("production_order_items", len(poi_rows))

    output_rows = []
    rejection_rows = []
    output_meta = []
    for meta in po_meta:
        po = meta["po"]
        if po.status == "planned":
            continue
        n_batches = ctx.rng.randint(1, 3)
        remaining = meta["quantity"]
        span_days = max(1, (po.planned_end - po.planned_start).days)
        for b in range(n_batches):
            batch_qty = round(remaining / (n_batches - b), 2) if b < n_batches - 1 else round(remaining, 2)
            remaining -= batch_qty
            output_date = clamp_date(po.planned_start + dt.timedelta(days=ctx.rng.randint(0, span_days)), ctx.today)
            machine_id = ctx.rng.choice(ctx.machines) if ctx.machines else None
            out = ProductionOutput(production_order_id=po.id, output_date=output_date, quantity_produced=max(batch_qty, 0.0), machine_id=machine_id)
            output_rows.append(out)
            output_meta.append((out, po))
    await _bulk_add(session, output_rows)
    ctx.record("production_output", len(output_rows))

    for out, po in output_meta:
        if ctx.rng.random() < 0.5:
            continue
        rate = ctx.rng.uniform(*PRODUCTION_REJECTION_RATE_RANGE)
        qty_rejected = round(float(out.quantity_produced) * rate, 2)
        if qty_rejected <= 0:
            continue
        rejection_rows.append(
            ProductionRejection(
                production_order_id=po.id,
                rejection_date=out.output_date,
                quantity_rejected=qty_rejected,
                reason=ctx.rng.choice(["quality_defect", "dimension_mismatch", "material_fault", "process_error"]),
            )
        )
    await _bulk_add(session, rejection_rows)
    ctx.record("production_rejections", len(rejection_rows))

    print(
        f"  production orders: {len(production_orders_orm)} orders, {len(poi_rows)} items, "
        f"{len(output_rows)} output, {len(rejection_rows)} rejections"
    )


async def seed_fulfillment(session, ctx: SeedContext) -> None:
    """Packing -> Dispatch -> Shipment -> Delivery (+ DeliveryDelay) for
    non-cancelled orders old enough to have progressed."""
    eligible = [m for m in ctx.order_meta if (ctx.today - m["order"].order_date).days >= 3]
    fulfilled = ctx.rng.sample(eligible, k=int(len(eligible) * 0.75)) if eligible else []

    packings_orm = []
    packing_by_order = {}
    for m in fulfilled:
        order = m["order"]
        packed_date = clamp_date(order.order_date + dt.timedelta(days=ctx.rng.randint(1, 4)), ctx.today)
        pk = Packing(sales_order_id=order.id, packed_date=packed_date, status="completed", packages_count=ctx.rng.randint(1, 10))
        packings_orm.append(pk)
        packing_by_order[order.id] = pk
    await _bulk_add(session, packings_orm)
    ctx.record("packings", len(packings_orm))

    order_by_id = {m["order"].id: m for m in fulfilled}
    dispatches_orm = []
    for order_id, pk in packing_by_order.items():
        dispatch_date = clamp_date(pk.packed_date + dt.timedelta(days=ctx.rng.randint(0, 2)), ctx.today)
        dispatches_orm.append(
            Dispatch(
                sales_order_id=order_id,
                dispatch_date=dispatch_date,
                vehicle_number=f"VH-{ctx.rng.randint(1000, 9999)}",
                dispatched_by_employee_id=ctx.rng.choice(ctx.logistics_employees) if ctx.logistics_employees else None,
                status="dispatched",
            )
        )
    await _bulk_add(session, dispatches_orm)
    ctx.record("dispatches", len(dispatches_orm))

    carriers = ["BlueDart", "Delhivery", "DTDC", "FedEx", "Own Fleet", "Gati"]
    shipments_orm = [
        Shipment(dispatch_id=d.id, carrier=ctx.rng.choice(carriers), tracking_number=f"TRK{ctx.rng.randint(10**9, 10**10 - 1)}", shipped_date=d.dispatch_date)
        for d in dispatches_orm
    ]
    await _bulk_add(session, shipments_orm)
    ctx.record("shipments", len(shipments_orm))

    dispatch_by_order = {d.sales_order_id: d for d in dispatches_orm}
    shipment_by_dispatch = {s.dispatch_id: s for s in shipments_orm}

    deliveries_orm = []
    delivery_meta = []  # (delivery, delayed: bool, delay_days)
    for order_id, disp in dispatch_by_order.items():
        m = order_by_id[order_id]
        order = m["order"]
        shipment = shipment_by_dispatch[disp.id]
        expected = order.expected_delivery_date or (order.order_date + dt.timedelta(days=14))
        is_late = ctx.rng.random() < DELIVERY_LATE_RATE
        has_arrived = expected <= ctx.today or ctx.rng.random() < 0.5
        if not has_arrived:
            deliveries_orm.append(
                Delivery(shipment_id=shipment.id, sales_order_id=order_id, expected_delivery_date=expected, actual_delivery_date=None, status="pending", delay_days=0)
            )
            continue
        if is_late:
            delay = ctx.rng.randint(1, 10)
            actual = expected + dt.timedelta(days=delay)
            if actual > ctx.today:
                actual = ctx.today
                delay = max((actual - expected).days, 0)
            status = "delayed" if delay > 0 else "delivered"
        else:
            delay = 0
            actual = clamp_date(expected - dt.timedelta(days=ctx.rng.randint(0, 2)), ctx.today)
            status = "delivered"
        d = Delivery(shipment_id=shipment.id, sales_order_id=order_id, expected_delivery_date=expected, actual_delivery_date=actual, status=status, delay_days=max(delay, 0))
        deliveries_orm.append(d)
        if delay > 0:
            delivery_meta.append((d, delay))
    await _bulk_add(session, deliveries_orm)
    ctx.record("deliveries", len(deliveries_orm))

    delay_rows = []
    for d, delay in delivery_meta:
        delay_rows.append(
            DeliveryDelay(
                delivery_id=d.id,
                reason=ctx.rng.choice(DELAY_REASONS),
                days_delayed=delay,
                logged_on=d.actual_delivery_date or ctx.today,
                notes=ctx.fake.sentence(nb_words=8),
            )
        )
    await _bulk_add(session, delay_rows)
    ctx.record("delivery_delays", len(delay_rows))

    print(
        f"  fulfillment: {len(packings_orm)} packings, {len(dispatches_orm)} dispatches, "
        f"{len(shipments_orm)} shipments, {len(deliveries_orm)} deliveries, {len(delay_rows)} delivery_delays"
    )

    ctx.delivered_order_ids = {d.sales_order_id for d in deliveries_orm if d.status in ("delivered", "delayed")}


async def seed_sales_invoicing(session, ctx: SeedContext) -> None:
    """Invoice delivered orders (mostly), plus some old dispatched-but-not-
    yet-delivered orders billed in advance, then payments/receivables/returns."""
    candidates = [m for m in ctx.order_meta if m["order"].id in ctx.delivered_order_ids]
    extra_pool = [m for m in ctx.order_meta if m["order"].id not in ctx.delivered_order_ids and (ctx.today - m["order"].order_date).days > 20]
    candidates += ctx.rng.sample(extra_pool, k=int(len(extra_pool) * 0.3)) if extra_pool else []

    invoice_orm = []
    invoice_meta = []
    for i, m in enumerate(candidates):
        order = m["order"]
        invoice_date = clamp_date(order.order_date + dt.timedelta(days=ctx.rng.randint(5, 20)), ctx.today)
        due_date = invoice_date + dt.timedelta(days=ctx.rng.choice([15, 30, 45]))
        inv = SalesInvoice(
            invoice_code=f"INV{i + 1:06d}",
            sales_order_id=order.id,
            customer_id=order.customer_id,
            invoice_date=invoice_date,
            due_date=due_date,
            total_amount=order.total_amount,
            status="unpaid",
        )
        invoice_orm.append(inv)
        invoice_meta.append(dict(invoice=inv, order=order))
    await _bulk_add(session, invoice_orm)
    ctx.record("sales_invoices", len(invoice_orm))

    payment_orm = []
    receivable_orm = []
    for meta in invoice_meta:
        inv = meta["invoice"]
        total = float(inv.total_amount)
        r = ctx.rng.random()
        if r < 0.65:
            pay_date1 = inv.invoice_date + dt.timedelta(days=ctx.rng.randint(1, 30))
            if pay_date1 > ctx.today:
                inv.status = "unpaid"
                receivable_orm.append(Receivable(customer_id=inv.customer_id, sales_invoice_id=inv.id, amount=total, due_date=inv.due_date, status="pending"))
                continue
            if ctx.rng.random() < 0.25:
                amt1 = round(total * ctx.rng.uniform(0.3, 0.6), 2)
                payment_orm.append(SalesPayment(sales_invoice_id=inv.id, payment_date=pay_date1, amount=amt1, method=ctx.rng.choice(PAYMENT_METHODS)))
                pay_date2 = clamp_date(pay_date1 + dt.timedelta(days=ctx.rng.randint(1, 20)), ctx.today)
                payment_orm.append(SalesPayment(sales_invoice_id=inv.id, payment_date=pay_date2, amount=round(total - amt1, 2), method=ctx.rng.choice(PAYMENT_METHODS)))
            else:
                payment_orm.append(SalesPayment(sales_invoice_id=inv.id, payment_date=pay_date1, amount=total, method=ctx.rng.choice(PAYMENT_METHODS)))
            inv.status = "paid"
        elif r < 0.85:
            pay_date1 = clamp_date(inv.invoice_date + dt.timedelta(days=ctx.rng.randint(1, 30)), ctx.today)
            amt1 = round(total * ctx.rng.uniform(0.2, 0.7), 2)
            payment_orm.append(SalesPayment(sales_invoice_id=inv.id, payment_date=pay_date1, amount=amt1, method=ctx.rng.choice(PAYMENT_METHODS)))
            inv.status = "partially_paid"
            receivable_orm.append(
                Receivable(customer_id=inv.customer_id, sales_invoice_id=inv.id, amount=round(total - amt1, 2), due_date=inv.due_date, status="overdue" if inv.due_date < ctx.today else "pending")
            )
        else:
            inv.status = "overdue" if inv.due_date < ctx.today else "unpaid"
            receivable_orm.append(Receivable(customer_id=inv.customer_id, sales_invoice_id=inv.id, amount=total, due_date=inv.due_date, status="overdue" if inv.due_date < ctx.today else "pending"))
    await _bulk_add(session, payment_orm)
    await _bulk_add(session, receivable_orm)
    ctx.record("sales_payments", len(payment_orm))
    ctx.record("receivables", len(receivable_orm))

    return_rows = []
    delivered_meta = [m for m in invoice_meta if m["order"].id in ctx.delivered_order_ids]
    sample_size = int(len(delivered_meta) * 0.06)
    for m in (ctx.rng.sample(delivered_meta, k=sample_size) if sample_size else []):
        order = m["order"]
        product = ctx.rng.choice(ctx.products)
        qty = round(ctx.rng.uniform(1, 10), 2)
        return_rows.append(
            SalesReturn(
                sales_order_id=order.id,
                product_id=product["id"],
                quantity=qty,
                reason=ctx.rng.choice(["damaged in transit", "wrong item", "quality issue", "customer changed mind"]),
                return_date=clamp_date(order.order_date + dt.timedelta(days=ctx.rng.randint(15, 40)), ctx.today),
                refund_amount=round(qty * product["unit_price"], 2),
            )
        )
    await _bulk_add(session, return_rows)
    ctx.record("sales_returns", len(return_rows))

    print(
        f"  sales invoicing: {len(invoice_orm)} sales_invoices, {len(payment_orm)} sales_payments, "
        f"{len(receivable_orm)} receivables, {len(return_rows)} sales_returns"
    )


async def seed_sales_targets(session, ctx: SeedContext) -> None:
    months_back = min(ctx.cfg["years_back"] * 12, 15)
    cur = ctx.today.replace(day=1)
    period_list = []
    y, m = cur.year, cur.month
    for _ in range(months_back):
        period_list.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    rows = []
    for emp_id in ctx.sales_employees:
        for (y, m) in period_list:
            rows.append(
                SalesTarget(salesperson_id=emp_id, period_month=m, period_year=y, target_amount=round(ctx.rng.uniform(100000, 1000000), 2), branch_id=ctx.rng.choice(ctx.branches))
            )
    await _bulk_add(session, rows)
    ctx.record("sales_targets", len(rows))
    print(f"  sales_targets: {len(rows)}")


# --------------------------------------------------------------------------
# Purchase pipeline: Requisition -> PO -> Items -> Receipt -> Invoice -> Payment
# --------------------------------------------------------------------------

async def seed_purchase_pipeline(session, ctx: SeedContext) -> None:
    n_req = max(30, ctx.cfg["products"] * 2)
    dept_ids = list(ctx.departments.values())

    req_orm = []
    for i in range(n_req):
        product = ctx.rng.choice(ctx.products)
        requested_on = dt.datetime.combine(ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today), dt.time(ctx.rng.randint(8, 18), 0))
        req_orm.append(
            PurchaseRequisition(
                requisition_code=f"PR{i + 1:06d}",
                product_id=product["id"],
                quantity=round(ctx.rng.uniform(50, 1000), 2),
                requested_by_employee_id=ctx.rng.choice(ctx.purchase_employees),
                status="approved",
                requested_on=requested_on,
                department_id=ctx.rng.choice(dept_ids),
            )
        )
    await _bulk_add(session, req_orm)
    ctx.record("purchase_requisitions", len(req_orm))

    product_by_id = {p["id"]: p for p in ctx.products}
    converting = ctx.rng.sample(req_orm, k=int(len(req_orm) * 0.85))
    po_orm = []
    po_meta = []
    for i, req in enumerate(converting):
        product = product_by_id[req.product_id]
        order_date = clamp_date(req.requested_on.date() + dt.timedelta(days=ctx.rng.randint(1, 5)), ctx.today)
        expected_date = order_date + dt.timedelta(days=ctx.rng.randint(5, 21))
        unit_price = product["unit_cost"]
        total_amount = round(unit_price * float(req.quantity), 2)
        status = "received" if expected_date < ctx.today else ctx.rng.choice(["approved", "sent"])
        po = PurchaseOrder(
            po_code=f"PO{i + 1:06d}",
            requisition_id=req.id,
            supplier_id=ctx.rng.choice(ctx.suppliers),
            order_date=order_date,
            status=status,
            total_amount=total_amount,
            expected_date=expected_date,
        )
        po_orm.append(po)
        po_meta.append(dict(po=po, req=req, product=product, quantity=float(req.quantity), unit_price=unit_price))
    await _bulk_add(session, po_orm)
    ctx.record("purchase_orders", len(po_orm))

    poi_orm = []
    for m in po_meta:
        po = m["po"]
        poi_orm.append(PurchaseOrderItem(purchase_order_id=po.id, product_id=m["product"]["id"], quantity=m["quantity"], unit_price=m["unit_price"], line_total=float(po.total_amount)))
        if ctx.rng.random() < 0.3:
            extra_product = ctx.rng.choice(ctx.products)
            extra_qty = round(ctx.rng.uniform(10, 200), 2)
            extra_total = round(extra_qty * extra_product["unit_cost"], 2)
            poi_orm.append(PurchaseOrderItem(purchase_order_id=po.id, product_id=extra_product["id"], quantity=extra_qty, unit_price=extra_product["unit_cost"], line_total=extra_total))
            po.total_amount = round(float(po.total_amount) + extra_total, 2)
    await _bulk_add(session, poi_orm)
    ctx.record("purchase_order_items", len(poi_orm))

    print(f"  purchase pipeline: {len(req_orm)} purchase_requisitions, {len(po_orm)} purchase_orders, {len(poi_orm)} purchase_order_items")
    ctx.purchase_po_meta = po_meta


async def seed_material_receipts(session, ctx: SeedContext) -> None:
    receivable_pos = [m for m in ctx.purchase_po_meta if m["po"].expected_date <= ctx.today or m["po"].status == "received"]
    n_receipts = int(len(receivable_pos) * 0.9)
    chosen = ctx.rng.sample(receivable_pos, k=n_receipts) if n_receipts else []

    receipts_orm = []
    receipt_meta = []
    for i, m in enumerate(chosen):
        po = m["po"]
        received_date = clamp_date(po.order_date + dt.timedelta(days=ctx.rng.randint(3, 25)), ctx.today)
        qty = m["quantity"]
        rejected = round(qty * ctx.rng.uniform(0, 0.05), 2)
        accepted = round(qty - rejected, 2)
        mr = MaterialReceipt(
            grn_code=f"GRN{i + 1:06d}",
            purchase_order_id=po.id,
            product_id=m["product"]["id"],
            warehouse_id=ctx.rng.choice(ctx.warehouses),
            received_date=received_date,
            quantity_received=qty,
            quantity_accepted=accepted,
            quantity_rejected=rejected,
            status="completed",
        )
        receipts_orm.append(mr)
        receipt_meta.append(dict(mr=mr, po=po, product=m["product"], quantity=qty, rejected=rejected))
        po.status = "received"
    await _bulk_add(session, receipts_orm)
    ctx.record("material_receipts", len(receipts_orm))

    pr_rows = []
    for m in receipt_meta:
        if m["rejected"] > 0 and ctx.rng.random() < 0.5:
            pr_rows.append(
                PurchaseReturn(
                    purchase_order_id=m["po"].id,
                    product_id=m["product"]["id"],
                    quantity=m["rejected"],
                    reason=ctx.rng.choice(["quality issue", "damaged", "wrong item", "excess supply"]),
                    return_date=clamp_date(m["mr"].received_date + dt.timedelta(days=ctx.rng.randint(1, 5)), ctx.today),
                )
            )
    await _bulk_add(session, pr_rows)
    ctx.record("purchase_returns", len(pr_rows))

    print(f"  material receipts: {len(receipts_orm)} material_receipts, {len(pr_rows)} purchase_returns")
    ctx.receipt_meta = receipt_meta


async def seed_supplier_invoicing(session, ctx: SeedContext) -> None:
    invoice_orm = []
    for i, m in enumerate(ctx.receipt_meta):
        po = m["po"]
        invoice_date = clamp_date(m["mr"].received_date + dt.timedelta(days=ctx.rng.randint(0, 5)), ctx.today)
        due_date = invoice_date + dt.timedelta(days=ctx.rng.choice([15, 30, 45, 60]))
        invoice_orm.append(
            SupplierInvoice(invoice_code=f"SINV{i + 1:06d}", purchase_order_id=po.id, supplier_id=po.supplier_id, invoice_date=invoice_date, due_date=due_date, total_amount=po.total_amount, status="unpaid")
        )
    await _bulk_add(session, invoice_orm)
    ctx.record("supplier_invoices", len(invoice_orm))

    payment_orm = []
    payable_orm = []
    for inv in invoice_orm:
        total = float(inv.total_amount)
        r = ctx.rng.random()
        if r < 0.7:
            pay_date = inv.invoice_date + dt.timedelta(days=ctx.rng.randint(1, 40))
            if pay_date > ctx.today:
                inv.status = "unpaid"
                payable_orm.append(Payable(supplier_id=inv.supplier_id, supplier_invoice_id=inv.id, amount=total, due_date=inv.due_date, status="pending"))
                continue
            payment_orm.append(SupplierPayment(supplier_invoice_id=inv.id, payment_date=pay_date, amount=total, method=ctx.rng.choice(PAYMENT_METHODS)))
            inv.status = "paid"
        elif r < 0.88:
            pay_date = clamp_date(inv.invoice_date + dt.timedelta(days=ctx.rng.randint(1, 40)), ctx.today)
            amt = round(total * ctx.rng.uniform(0.3, 0.7), 2)
            payment_orm.append(SupplierPayment(supplier_invoice_id=inv.id, payment_date=pay_date, amount=amt, method=ctx.rng.choice(PAYMENT_METHODS)))
            inv.status = "partially_paid"
            payable_orm.append(Payable(supplier_id=inv.supplier_id, supplier_invoice_id=inv.id, amount=round(total - amt, 2), due_date=inv.due_date, status="overdue" if inv.due_date < ctx.today else "pending"))
        else:
            inv.status = "overdue" if inv.due_date < ctx.today else "unpaid"
            payable_orm.append(Payable(supplier_id=inv.supplier_id, supplier_invoice_id=inv.id, amount=total, due_date=inv.due_date, status="overdue" if inv.due_date < ctx.today else "pending"))
    await _bulk_add(session, payment_orm)
    await _bulk_add(session, payable_orm)
    ctx.record("supplier_payments", len(payment_orm))
    ctx.record("payables", len(payable_orm))

    print(f"  supplier invoicing: {len(invoice_orm)} supplier_invoices, {len(payment_orm)} supplier_payments, {len(payable_orm)} payables")


# --------------------------------------------------------------------------
# Inventory: stock levels, movements, transfers, batches, adjustments
# --------------------------------------------------------------------------

async def seed_inventory(session, ctx: SeedContext) -> None:
    stock_rows = []
    stock_keys = set()
    for p in ctx.products:
        n_warehouses = ctx.rng.randint(1, min(3, len(ctx.warehouses)))
        for wh_id in ctx.rng.sample(ctx.warehouses, k=n_warehouses):
            key = (p["id"], wh_id)
            if key in stock_keys:
                continue
            stock_keys.add(key)
            reorder = p["reorder_level"]
            qty = round(reorder * ctx.rng.uniform(0.1, 0.95), 2) if ctx.rng.random() < LOW_STOCK_RATE else round(reorder * ctx.rng.uniform(1.05, 5), 2)
            reserved = round(qty * ctx.rng.uniform(0, 0.2), 2)
            stock_rows.append(Stock(product_id=p["id"], warehouse_id=wh_id, quantity_on_hand=qty, quantity_reserved=reserved))
    await _bulk_add(session, stock_rows)
    ctx.record("stock", len(stock_rows))

    movement_rows = []
    for m in getattr(ctx, "receipt_meta", []):
        movement_rows.append(
            StockMovement(
                product_id=m["product"]["id"],
                warehouse_id=m["mr"].warehouse_id,
                movement_type="receipt",
                quantity=m["quantity"],
                reference_type="material_receipts",
                reference_id=m["mr"].id,
                movement_date=dt.datetime.combine(m["mr"].received_date, dt.time(10, 0)),
            )
        )
    for m in ctx.order_meta[: min(len(ctx.order_meta), 3000)]:
        order = m["order"]
        movement_rows.append(
            StockMovement(
                product_id=m["product"]["id"],
                warehouse_id=ctx.rng.choice(ctx.warehouses),
                movement_type="dispatch",
                quantity=m["quantity"],
                reference_type="sales_orders",
                reference_id=order.id,
                movement_date=dt.datetime.combine(order.order_date, dt.time(15, 0)),
            )
        )
    await _bulk_add(session, movement_rows)
    ctx.record("stock_movements", len(movement_rows))

    transfer_rows = []
    if len(ctx.warehouses) >= 2:
        n_transfers = max(15, len(ctx.products) // 3)
        for _ in range(n_transfers):
            p = ctx.rng.choice(ctx.products)
            from_wh, to_wh = ctx.rng.sample(ctx.warehouses, 2)
            transfer_rows.append(
                StockTransfer(
                    product_id=p["id"],
                    from_warehouse_id=from_wh,
                    to_warehouse_id=to_wh,
                    quantity=round(ctx.rng.uniform(5, 100), 2),
                    transfer_date=ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today),
                    status=ctx.rng.choice(["completed", "completed", "in_transit", "pending"]),
                )
            )
    await _bulk_add(session, transfer_rows)
    ctx.record("stock_transfers", len(transfer_rows))

    batch_rows = []
    for p in ctx.rng.sample(ctx.products, k=max(1, len(ctx.products) // 2)):
        manufactured = ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today)
        batch_rows.append(
            MaterialBatch(
                product_id=p["id"],
                batch_code=f"BATCH-{p['id']}-{ctx.rng.randint(1000, 9999)}",
                warehouse_id=ctx.rng.choice(ctx.warehouses),
                quantity=round(ctx.rng.uniform(10, 500), 2),
                manufactured_date=manufactured,
                expiry_date=manufactured + dt.timedelta(days=ctx.rng.randint(180, 1095)),
            )
        )
    await _bulk_add(session, batch_rows)
    ctx.record("material_batches", len(batch_rows))

    adj_rows = []
    for _ in range(max(15, len(ctx.products) // 4)):
        p = ctx.rng.choice(ctx.products)
        adj_rows.append(
            InventoryAdjustment(
                product_id=p["id"],
                warehouse_id=ctx.rng.choice(ctx.warehouses),
                adjustment_type=ctx.rng.choice(["increase", "decrease"]),
                quantity=round(ctx.rng.uniform(1, 50), 2),
                reason=ctx.rng.choice(["stock count correction", "damage", "expiry write-off", "system error correction"]),
                adjusted_on=ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today),
            )
        )
    await _bulk_add(session, adj_rows)
    ctx.record("inventory_adjustments", len(adj_rows))

    print(
        f"  inventory: {len(stock_rows)} stock, {len(movement_rows)} stock_movements, "
        f"{len(transfer_rows)} stock_transfers, {len(batch_rows)} material_batches, {len(adj_rows)} inventory_adjustments"
    )


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

async def seed_tasks(session, ctx: SeedContext) -> None:
    categories = [TaskCategory(name=n) for n in TASK_CATEGORIES]
    await _bulk_add(session, categories)
    ctx.record("task_categories", len(categories))

    priorities = [TaskPriority(name=n, level=lvl) for n, lvl in TASK_PRIORITIES]
    await _bulk_add(session, priorities)
    ctx.record("task_priorities", len(priorities))

    n_tasks = max(60, len(ctx.employees) * 3)
    employee_ids = [e["id"] for e in ctx.employees]
    attendance_start = max(ctx.start_date, ctx.today - dt.timedelta(days=400))

    tasks_orm = []
    for i in range(n_tasks):
        created_on = dt.datetime.combine(ctx.fake.date_between(start_date=attendance_start, end_date=ctx.today), dt.time(ctx.rng.randint(8, 18), 0))
        due_date = created_on.date() + dt.timedelta(days=ctx.rng.randint(1, 21))
        status = ctx.rng.choice(["open", "in_progress", "completed", "completed", "cancelled"])
        completed_on = None
        if status == "completed":
            completed_on = dt.datetime.combine(clamp_date(due_date, ctx.today), dt.time(ctx.rng.randint(9, 19), 0))
        tasks_orm.append(
            Task(
                title=ctx.fake.sentence(nb_words=6).rstrip("."),
                description=ctx.fake.sentence(nb_words=15),
                category_id=ctx.rng.choice(categories).id,
                priority_id=ctx.rng.choice(priorities).id,
                status=status,
                assigned_to_employee_id=ctx.rng.choice(employee_ids),
                created_by_employee_id=ctx.rng.choice(employee_ids),
                due_date=due_date,
                created_on=created_on,
                completed_on=completed_on,
                related_module=ctx.rng.choice(["sales", "purchase", "production", "delivery", None]),
                related_record_id=None,
            )
        )
    await _bulk_add(session, tasks_orm)
    ctx.record("tasks", len(tasks_orm))

    assignment_rows = []
    comment_rows = []
    history_rows = []
    for t in tasks_orm:
        assignment_rows.append(TaskAssignment(task_id=t.id, employee_id=t.assigned_to_employee_id, assigned_on=t.created_on, role="assignee"))
        if ctx.rng.random() < 0.2:
            assignment_rows.append(TaskAssignment(task_id=t.id, employee_id=ctx.rng.choice(employee_ids), assigned_on=t.created_on, role="reviewer"))
        for _ in range(ctx.rng.randint(0, 3)):
            comment_rows.append(TaskComment(task_id=t.id, employee_id=ctx.rng.choice(employee_ids), comment=ctx.fake.sentence(nb_words=10), commented_on=t.created_on + dt.timedelta(hours=ctx.rng.randint(1, 100))))
        if t.status in ("completed", "in_progress", "cancelled"):
            history_rows.append(
                TaskStatusHistory(
                    task_id=t.id,
                    old_status="open",
                    new_status=t.status,
                    changed_on=t.completed_on or (t.created_on + dt.timedelta(hours=ctx.rng.randint(1, 200))),
                    changed_by_employee_id=t.assigned_to_employee_id,
                )
            )
    await _bulk_add(session, assignment_rows)
    await _bulk_add(session, comment_rows)
    await _bulk_add(session, history_rows)
    ctx.record("task_assignments", len(assignment_rows))
    ctx.record("task_comments", len(comment_rows))
    ctx.record("task_status_history", len(history_rows))

    print(f"  tasks: {len(tasks_orm)} tasks, {len(assignment_rows)} task_assignments, {len(comment_rows)} task_comments, {len(history_rows)} task_status_history")


# --------------------------------------------------------------------------
# Finance: chart of accounts, transactions, expenses, receivables/payables
# (receivables/payables already produced in sales/purchase invoicing steps)
# --------------------------------------------------------------------------

ACCOUNTS = [
    ("Cash", "asset", "1000"),
    ("Bank", "asset", "1010"),
    ("Accounts Receivable", "asset", "1100"),
    ("Inventory", "asset", "1200"),
    ("Accounts Payable", "liability", "2000"),
    ("Salaries Payable", "liability", "2100"),
    ("Equity", "equity", "3000"),
    ("Sales Revenue", "income", "4000"),
    ("Cost of Goods Sold", "expense", "5000"),
    ("Operating Expenses", "expense", "5100"),
]


async def seed_finance(session, ctx: SeedContext) -> None:
    accounts_orm = [Account(name=n, account_type=t, code=c) for n, t, c in ACCOUNTS]
    await _bulk_add(session, accounts_orm)
    ctx.record("accounts", len(accounts_orm))
    account_by_type: dict[str, list[int]] = {}
    for a in accounts_orm:
        account_by_type.setdefault(a.account_type, []).append(a.id)

    txn_rows = []
    txn_start = max(ctx.start_date, ctx.today - dt.timedelta(days=730))
    for d in daterange(txn_start, ctx.today):
        if d.day not in (1, 15):
            continue
        for _ in range(ctx.rng.randint(1, 3)):
            acc_type = ctx.rng.choice(list(account_by_type.keys()))
            account_id = ctx.rng.choice(account_by_type[acc_type])
            txn_rows.append(
                FinancialTransaction(
                    account_id=account_id,
                    transaction_date=d,
                    amount=round(ctx.rng.uniform(1000, 200000), 2),
                    transaction_type=ctx.rng.choice(["debit", "credit"]),
                    reference_type="ledger",
                    reference_id=None,
                    description=f"{acc_type} entry {d.isoformat()}",
                )
            )
    await _bulk_add(session, txn_rows)
    ctx.record("financial_transactions", len(txn_rows))

    dept_ids = list(ctx.departments.values())
    employee_ids = [e["id"] for e in ctx.employees]
    n_expenses = max(60, len(ctx.employees) * 2)
    expense_rows = [
        Expense(
            category=ctx.rng.choice(EXPENSE_CATEGORIES),
            amount=round(ctx.rng.uniform(500, 50000), 2),
            expense_date=ctx.fake.date_between(start_date=ctx.start_date, end_date=ctx.today),
            department_id=ctx.rng.choice(dept_ids),
            description=ctx.fake.sentence(nb_words=8),
            approved_by_employee_id=ctx.rng.choice(employee_ids),
            status=ctx.rng.choice(["approved", "approved", "approved", "pending", "rejected"]),
        )
        for _ in range(n_expenses)
    ]
    await _bulk_add(session, expense_rows)
    ctx.record("expenses", len(expense_rows))

    print(f"  finance: {len(accounts_orm)} accounts, {len(txn_rows)} financial_transactions, {len(expense_rows)} expenses")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

async def seed_all(size: str = "medium") -> None:
    """Seed the whole database at the given SEED_SIZE tier.

    Idempotent-safe to call from app/core/bootstrap.py: callers are expected
    to only invoke this against an empty database (bootstrap checks
    `customers` count first); this function itself does not check emptiness
    or truncate anything, it simply inserts.
    """
    if size not in SIZE_CONFIG:
        raise ValueError(f"Invalid SEED_SIZE {size!r}; must be one of {list(SIZE_CONFIG)}")

    rng = random.Random(RANDOM_SEED)
    fake = Faker()
    Faker.seed(RANDOM_SEED)
    today = dt.date.today()

    ctx = SeedContext(size=size, rng=rng, fake=fake, today=today)

    print(f"=== Seeding database (size={size}, today={today}) ===")

    async with AsyncSessionLocal() as session:
        print("Seeding master data...")
        await seed_master_data(session, ctx)
        print("Seeding employees...")
        await seed_employees(session, ctx)
        print("Seeding calendar_dates...")
        await seed_calendar(session, ctx)
        print("Seeding HR (attendance/leave/payroll/performance)...")
        await seed_hr(session, ctx)
        print("Seeding production infrastructure (work centers/machines/BOM)...")
        await seed_production_infra(session, ctx)
        print("Seeding sales pipeline (leads/enquiries/quotations/orders)...")
        await seed_sales_pipeline(session, ctx)
        print("Seeding production orders...")
        await seed_production_orders(session, ctx)
        print("Seeding fulfillment (packing/dispatch/shipment/delivery)...")
        await seed_fulfillment(session, ctx)
        print("Seeding sales invoicing/payments...")
        await seed_sales_invoicing(session, ctx)
        print("Seeding sales targets...")
        await seed_sales_targets(session, ctx)
        print("Seeding purchase pipeline (requisitions/POs)...")
        await seed_purchase_pipeline(session, ctx)
        print("Seeding material receipts...")
        await seed_material_receipts(session, ctx)
        print("Seeding supplier invoicing/payments...")
        await seed_supplier_invoicing(session, ctx)
        print("Seeding inventory (stock/movements/transfers/batches)...")
        await seed_inventory(session, ctx)
        print("Seeding tasks...")
        await seed_tasks(session, ctx)
        print("Seeding finance (accounts/transactions/expenses)...")
        await seed_finance(session, ctx)

    print("=== Seeding complete ===")
    total_rows = sum(ctx.counts.values())
    for table, n in sorted(ctx.counts.items()):
        print(f"  {table}: {n}")
    print(f"Total rows inserted across {len(ctx.counts)} tables: {total_rows}")


async def _ensure_schema_and_seed(size: str) -> None:
    """Standalone CLI entrypoint safety net: `python -m scripts.seed_database`
    is documented (README.md/SETUP.md) as runnable directly against a fresh
    database with no prior `reset_db`/bootstrap step. `seed_all()` itself
    assumes tables already exist (the normal `app/core/bootstrap.py` flow
    always calls `Base.metadata.create_all` first) — so calling it standalone
    against a brand-new SQLite file previously failed with
    `sqlite3.OperationalError: no such table: regions`. Ensure the schema
    exists first, exactly like bootstrap.py does, before seeding.
    """
    import app.models  # noqa: F401 - register all tables on Base.metadata
    from app.db.session import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await seed_all(size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AI-native BI platform database with realistic demo data.")
    parser.add_argument("--size", choices=list(SIZE_CONFIG.keys()), default=None, help="Data volume to generate.")
    args = parser.parse_args()

    from app.core.config import get_settings

    size = args.size or os.environ.get("SEED_SIZE") or get_settings().SEED_SIZE
    asyncio.run(_ensure_schema_and_seed(size))


if __name__ == "__main__":
    main()
