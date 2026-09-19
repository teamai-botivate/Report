"""Hand-authored semantic dictionary for the AI-native BI platform.

This is the static, human-curated half of the semantic layer (the other half
is structural facts reflected from `Base.metadata` — see `metadata_cache.py`).
It exists so the AI never receives the entire 62-table schema in a prompt:
`retrieval.py` uses the descriptions/synonyms defined here (merged with
column names) to pick a small, relevant slice of tables + measures for a
given natural-language question.

Every table name and column name below was read directly from the model
files under `app/models/` (master.py, sales.py, purchase.py, inventory.py,
production.py, order_to_delivery.py, tasks.py, finance.py, hr.py) — nothing
here is guessed.

This module has zero SQLAlchemy/DB imports on purpose so it can be imported
standalone (e.g. from unit tests) with no database/event loop required.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInfo:
    """Business description + synonyms for one column worth annotating.

    Not every column of every table needs an entry here — only the
    "business meaning bearing" ones (measures, dates, key dimensions,
    status flags). Purely structural facts (type, PK/FK, nullability) come
    from `Base.metadata` reflection in `metadata_cache.py`.
    """

    description: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableInfo:
    """Business description + column annotations + synonyms for one table."""

    description: str
    module: str
    synonyms: tuple[str, ...] = ()
    columns: dict[str, ColumnInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class Measure:
    """A named business measure ("DAX-like" pre-defined metric).

    `expression` is a SQL fragment (valid inside a SELECT list, typically an
    aggregate over one or two joined tables) that the SQL Generation Agent
    can use verbatim or adapt when building a query plan node.
    """

    name: str
    expression: str
    synonyms: tuple[str, ...] = ()
    format: str = "number"  # "currency" | "percent" | "number" | "days"
    description: str = ""


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

TABLES: dict[str, TableInfo] = {
    # -- master data -------------------------------------------------------
    "regions": TableInfo(
        description="Geographic sales/reporting regions (e.g. North, South, East, West).",
        module="master",
        synonyms=("region", "regions", "zone", "territory"),
        columns={"name": ColumnInfo("Region name.", ("region name",))},
    ),
    "cities": TableInfo(
        description="Cities, each scoped to a region; customers/suppliers/branches locate here.",
        module="master",
        synonyms=("city", "cities", "location", "town"),
        columns={
            "name": ColumnInfo("City name.", ("city name",)),
            "state": ColumnInfo("State/province."),
            "country": ColumnInfo("Country."),
            "region_id": ColumnInfo("FK to regions.id."),
        },
    ),
    "branches": TableInfo(
        description="Physical company branch/office locations that employees and orders belong to.",
        module="master",
        synonyms=("branch", "branches", "office", "location"),
        columns={
            "name": ColumnInfo("Branch name."),
            "code": ColumnInfo("Branch short code."),
            "is_active": ColumnInfo("Whether the branch is currently active."),
        },
    ),
    "departments": TableInfo(
        description="Organizational departments (Sales, Purchase, HR, Production, ...).",
        module="master",
        synonyms=("department", "departments", "dept", "team"),
        columns={"name": ColumnInfo("Department name.", ("department name",))},
    ),
    "designations": TableInfo(
        description="Job titles/grades (e.g. Sales Executive, Manager).",
        module="master",
        synonyms=("designation", "designations", "job title", "role", "grade"),
        columns={"title": ColumnInfo("Designation/job title.")},
    ),
    "warehouses": TableInfo(
        description="Physical stock-holding locations, each tied to a branch.",
        module="master",
        synonyms=("warehouse", "warehouses", "store", "godown"),
        columns={"name": ColumnInfo("Warehouse name."), "code": ColumnInfo("Warehouse code.")},
    ),
    "product_categories": TableInfo(
        description="Self-referencing product category/sub-category hierarchy.",
        module="master",
        synonyms=("category", "categories", "product category", "product categories"),
        columns={"name": ColumnInfo("Category name.")},
    ),
    "products": TableInfo(
        description=(
            "Sellable/purchasable/manufacturable SKUs; the hub of the sales, purchase, "
            "inventory and production domains."
        ),
        module="master",
        synonyms=("product", "products", "item", "items", "sku", "skus", "material"),
        columns={
            "sku": ColumnInfo("Unique stock-keeping unit code.", ("sku",)),
            "name": ColumnInfo("Product name.", ("product name", "item name")),
            "unit_price": ColumnInfo(
                "Standard selling price per unit.", ("price", "selling price", "unit price")
            ),
            "unit_cost": ColumnInfo(
                "Standard cost price per unit; used for margin calculations.",
                ("cost", "unit cost", "cost price"),
            ),
            "reorder_level": ColumnInfo(
                "Stock quantity threshold that triggers a reorder alert.",
                ("reorder level", "reorder point"),
            ),
        },
    ),
    "customers": TableInfo(
        description=(
            "Buying customer entities; anchors the sales-side transaction chain "
            "(leads -> enquiries -> quotations -> orders -> invoices -> payments)."
        ),
        module="master",
        synonyms=("customer", "customers", "client", "clients", "buyer", "account"),
        columns={
            "name": ColumnInfo("Customer name.", ("customer name", "client name")),
            "segment": ColumnInfo(
                "Customer segment: SMB, Enterprise, Government, Retail.", ("segment", "customer segment")
            ),
            "is_active": ColumnInfo("Whether the customer is currently active."),
        },
    ),
    "suppliers": TableInfo(
        description=(
            "Vendor entities supplying materials/products; anchors the purchase-side "
            "transaction chain (requisitions -> POs -> receipts -> invoices -> payments)."
        ),
        module="master",
        synonyms=("supplier", "suppliers", "vendor", "vendors"),
        columns={
            "name": ColumnInfo("Supplier name.", ("supplier name", "vendor name")),
            "rating": ColumnInfo("Supplier quality/delivery rating, 0.00-5.00.", ("supplier rating",)),
        },
    ),
    "employees": TableInfo(
        description=(
            "Staff members belonging to a department/designation/branch, may report to a "
            "manager; participate across HR, sales, purchase, production and task modules."
        ),
        module="master",
        synonyms=("employee", "employees", "staff", "worker", "personnel", "headcount"),
        columns={
            "employee_code": ColumnInfo("Unique employee code."),
            "name": ColumnInfo("Employee name.", ("employee name",)),
            "hire_date": ColumnInfo("Date of joining.", ("hire date", "joining date", "date of joining")),
            "status": ColumnInfo(
                "Employee status: active, on_leave, terminated.", ("employee status",)
            ),
            "base_salary": ColumnInfo("Monthly base salary before allowances/deductions.", ("salary",)),
            "department_id": ColumnInfo("FK to departments.id."),
            "manager_id": ColumnInfo("FK to employees.id (self-referencing manager)."),
        },
    ),
    "calendar_dates": TableInfo(
        description=(
            "Date-dimension table: one row per calendar day with pre-computed rollup "
            "attributes (year/quarter/month/week/fiscal year/weekend flag) for time-based "
            "grouping and period-over-period comparisons."
        ),
        module="master",
        synonyms=("calendar", "date", "dates", "time", "period", "month", "quarter", "year"),
        columns={
            "date": ColumnInfo("The calendar date (primary key)."),
            "year": ColumnInfo("Calendar year."),
            "quarter": ColumnInfo("Calendar quarter (1-4).", ("quarter",)),
            "month": ColumnInfo("Calendar month number (1-12)."),
            "month_name": ColumnInfo("Calendar month name.", ("month",)),
            "fiscal_year": ColumnInfo("Fiscal year label, e.g. 'FY2025-26'.", ("fiscal year",)),
            "is_weekend": ColumnInfo("Whether the date falls on a weekend."),
        },
    ),
    # -- sales domain --------------------------------------------------------
    "leads": TableInfo(
        description="Prospective customer leads; the entry point of the sales funnel.",
        module="sales",
        synonyms=("lead", "leads", "prospect", "prospects"),
        columns={
            "status": ColumnInfo(
                "Lead status: new, contacted, qualified, converted, lost.", ("lead status",)
            ),
            "source": ColumnInfo(
                "Lead source: website, referral, cold_call, exhibition, ad_campaign.",
                ("lead source", "source"),
            ),
            "estimated_value": ColumnInfo("Estimated deal value of the lead."),
        },
    ),
    "enquiries": TableInfo(
        description="Concrete product enquiries, optionally sourced from a lead or existing customer.",
        module="sales",
        synonyms=("enquiry", "enquiries", "inquiry", "inquiries"),
        columns={
            "status": ColumnInfo("Enquiry status: open, quoted, closed, dropped."),
            "quantity": ColumnInfo("Quantity enquired about."),
        },
    ),
    "quotations": TableInfo(
        description="Price quotations issued to a customer in response to an enquiry.",
        module="sales",
        synonyms=("quotation", "quotations", "quote", "quotes"),
        columns={
            "total_amount": ColumnInfo("Quoted total value.", ("quotation value", "quoted amount")),
            "status": ColumnInfo("Quotation status: draft, sent, accepted, rejected, expired."),
            "valid_until": ColumnInfo("Quotation expiry date."),
        },
    ),
    "sales_orders": TableInfo(
        description="Confirmed sales orders; the anchor of the order-to-delivery chain.",
        module="sales",
        synonyms=("sales order", "sales orders", "order", "orders", "sale"),
        columns={
            "order_code": ColumnInfo("Unique sales order code."),
            "order_date": ColumnInfo("Date the order was placed.", ("order date",)),
            "status": ColumnInfo(
                "Order status: pending, confirmed, in_production, dispatched, delivered, cancelled.",
                ("order status",),
            ),
            "total_amount": ColumnInfo(
                "Order value; feeds the 'Total Orders'/'Average Order Value' measures.",
                ("order value", "order amount"),
            ),
            "expected_delivery_date": ColumnInfo(
                "Expected delivery date for the order.", ("expected delivery date",)
            ),
        },
    ),
    "sales_order_items": TableInfo(
        description="Individual product line items on a sales order.",
        module="sales",
        synonyms=("sales order item", "order item", "order items", "order line"),
        columns={
            "quantity": ColumnInfo("Quantity ordered on this line."),
            "unit_price": ColumnInfo("Unit price on this line."),
            "line_total": ColumnInfo("Line total (quantity x unit_price)."),
        },
    ),
    "sales_invoices": TableInfo(
        description=(
            "Customer invoices raised against a sales order. `total_amount` here is the "
            "canonical source for the 'Total Revenue' measure (SUM of invoiced amounts)."
        ),
        module="sales",
        synonyms=(
            "sales invoice",
            "sales invoices",
            "invoice",
            "invoices",
            "revenue",
            "sales revenue",
            "sales value",
            "turnover",
            "billing",
        ),
        columns={
            "invoice_date": ColumnInfo("Date the invoice was raised.", ("invoice date",)),
            "due_date": ColumnInfo("Payment due date."),
            "total_amount": ColumnInfo(
                "Invoiced revenue amount; source of the 'Total Revenue' measure.",
                ("revenue", "sales revenue", "sales value", "turnover", "invoice amount", "invoice value"),
            ),
            "status": ColumnInfo(
                "Invoice status: unpaid, partially_paid, paid, overdue, void.", ("invoice status", "payment status")
            ),
        },
    ),
    "sales_payments": TableInfo(
        description="Payments received against a sales invoice.",
        module="sales",
        synonyms=("sales payment", "sales payments", "payment received", "collection"),
        columns={
            "amount": ColumnInfo("Amount paid.", ("payment amount",)),
            "payment_date": ColumnInfo("Date payment was received."),
            "method": ColumnInfo("Payment method: bank_transfer, cheque, cash, card, upi."),
        },
    ),
    "sales_returns": TableInfo(
        description="Product returns against a sales order.",
        module="sales",
        synonyms=("sales return", "sales returns", "return", "returns"),
        columns={
            "quantity": ColumnInfo("Quantity returned."),
            "refund_amount": ColumnInfo("Amount refunded to the customer.", ("refund",)),
            "return_date": ColumnInfo("Date of the return."),
        },
    ),
    "sales_targets": TableInfo(
        description=(
            "Monthly revenue targets assigned to a salesperson (and optionally a branch); "
            "the denominator for target-vs-achievement measures."
        ),
        module="sales",
        synonyms=("sales target", "sales targets", "target", "targets", "quota"),
        columns={
            "target_amount": ColumnInfo("Target revenue amount for the period.", ("target amount", "quota")),
            "period_month": ColumnInfo("Target period month."),
            "period_year": ColumnInfo("Target period year."),
        },
    ),
    # -- purchase domain -----------------------------------------------------
    "purchase_requisitions": TableInfo(
        description="Internal requests to purchase a product; the entry point of the procurement chain.",
        module="purchase",
        synonyms=("requisition", "requisitions", "purchase requisition", "purchase request"),
        columns={
            "status": ColumnInfo("Requisition status: pending, approved, rejected, converted."),
            "quantity": ColumnInfo("Quantity requested."),
        },
    ),
    "purchase_orders": TableInfo(
        description="Purchase orders issued to a supplier, optionally originating from a requisition.",
        module="purchase",
        synonyms=(
            "purchase order",
            "purchase orders",
            "po",
            "pos",
            "purchase",
            "purchases",
            "procurement",
        ),
        columns={
            "po_code": ColumnInfo("Unique purchase order code."),
            "order_date": ColumnInfo("Date the PO was placed."),
            "status": ColumnInfo(
                "PO status: draft, approved, sent, partially_received, received, cancelled."
            ),
            "total_amount": ColumnInfo(
                "Order value; the basis for the 'Purchase Value'/'Total Orders' measures.",
                ("purchase value", "purchase amount", "po value", "order value"),
            ),
            "expected_date": ColumnInfo("Expected delivery/receipt date for the PO."),
        },
    ),
    "purchase_order_items": TableInfo(
        description="Individual product line items on a purchase order.",
        module="purchase",
        synonyms=("purchase order item", "po item", "po items", "po line"),
        columns={
            "quantity": ColumnInfo("Quantity ordered on this line."),
            "unit_price": ColumnInfo("Unit price on this line."),
            "line_total": ColumnInfo("Line total (quantity x unit_price)."),
        },
    ),
    "material_receipts": TableInfo(
        description=(
            "Goods-receipt notes (GRN): materials physically received against a purchase "
            "order into a warehouse, one row per product line."
        ),
        module="purchase",
        synonyms=("material receipt", "material receipts", "grn", "goods receipt", "receiving"),
        columns={
            "quantity_received": ColumnInfo("Quantity physically received.", ("quantity received",)),
            "quantity_accepted": ColumnInfo("Quantity accepted after inspection."),
            "quantity_rejected": ColumnInfo(
                "Quantity rejected on receipt.", ("rejected quantity", "rejection")
            ),
            "received_date": ColumnInfo("Date materials were received."),
        },
    ),
    "supplier_invoices": TableInfo(
        description="Invoices raised by a supplier against a purchase order.",
        module="purchase",
        synonyms=("supplier invoice", "supplier invoices", "vendor invoice", "vendor invoices"),
        columns={
            "total_amount": ColumnInfo("Invoiced amount owed to the supplier.", ("invoice amount",)),
            "invoice_date": ColumnInfo("Date the supplier invoice was raised."),
            "status": ColumnInfo("Supplier invoice status: unpaid, partially_paid, paid, overdue."),
        },
    ),
    "supplier_payments": TableInfo(
        description="Payments made against a supplier invoice.",
        module="purchase",
        synonyms=("supplier payment", "supplier payments", "payment made", "vendor payment"),
        columns={
            "amount": ColumnInfo("Amount paid to the supplier.", ("payment amount",)),
            "payment_date": ColumnInfo("Date the payment was made."),
        },
    ),
    "purchase_returns": TableInfo(
        description="Product returns sent back to a supplier against a purchase order.",
        module="purchase",
        synonyms=("purchase return", "purchase returns", "return to vendor", "return to supplier"),
        columns={"quantity": ColumnInfo("Quantity returned."), "return_date": ColumnInfo("Date of the return.")},
    ),
    # -- inventory domain ------------------------------------------------------
    "stock": TableInfo(
        description="Current on-hand/reserved stock quantity for a product at a warehouse.",
        module="inventory",
        synonyms=("stock", "inventory", "stock level", "on-hand stock"),
        columns={
            "quantity_on_hand": ColumnInfo(
                "Physical quantity currently in the warehouse.", ("quantity on hand", "stock on hand")
            ),
            "quantity_reserved": ColumnInfo(
                "Quantity earmarked against open sales orders.", ("reserved quantity",)
            ),
        },
    ),
    "stock_movements": TableInfo(
        description=(
            "Immutable ledger of every stock-affecting event (receipt, dispatch, "
            "adjustment, transfer leg, production consumption/output)."
        ),
        module="inventory",
        synonyms=("stock movement", "stock movements", "stock ledger", "inventory movement"),
        columns={
            "movement_type": ColumnInfo(
                "Movement type: receipt, dispatch, adjustment, transfer_in, transfer_out, "
                "production_in, production_out."
            ),
            "quantity": ColumnInfo("Quantity moved."),
            "movement_date": ColumnInfo("Date/time of the movement."),
        },
    ),
    "stock_transfers": TableInfo(
        description="Stock transfers of a product between two warehouses.",
        module="inventory",
        synonyms=("stock transfer", "stock transfers", "warehouse transfer"),
        columns={
            "quantity": ColumnInfo("Quantity transferred."),
            "status": ColumnInfo("Transfer status: pending, in_transit, completed, cancelled."),
        },
    ),
    "material_batches": TableInfo(
        description=(
            "Tracked batches/lots of a product at a warehouse, with optional "
            "manufacture/expiry dates for shelf-life-sensitive materials."
        ),
        module="inventory",
        synonyms=("batch", "batches", "lot", "lots", "material batch"),
        columns={
            "quantity": ColumnInfo("Batch quantity."),
            "expiry_date": ColumnInfo("Batch expiry date.", ("expiry date", "expiry")),
        },
    ),
    "inventory_adjustments": TableInfo(
        description="Manual stock corrections (write-offs, stock-count reconciliations, etc.).",
        module="inventory",
        synonyms=("inventory adjustment", "inventory adjustments", "stock adjustment", "write-off"),
        columns={
            "adjustment_type": ColumnInfo("Adjustment type: increase, decrease."),
            "quantity": ColumnInfo("Adjustment quantity."),
        },
    ),
    # -- production domain -----------------------------------------------------
    "work_centers": TableInfo(
        description="Production floor/work areas within a branch.",
        module="production",
        synonyms=("work center", "work centers", "work centre", "shop floor"),
        columns={"name": ColumnInfo("Work center name.")},
    ),
    "machines": TableInfo(
        description="Production machines belonging to a work center.",
        module="production",
        synonyms=("machine", "machines", "equipment"),
        columns={
            "status": ColumnInfo("Machine status: operational, under_maintenance, idle, retired.")
        },
    ),
    "machine_downtime": TableInfo(
        description="Logged downtime events for a machine, used for OEE/availability reporting.",
        module="production",
        synonyms=("downtime", "machine downtime", "breakdown"),
        columns={
            "downtime_hours": ColumnInfo("Hours of downtime.", ("downtime hours",)),
            "reason": ColumnInfo(
                "Downtime reason: breakdown, maintenance, changeover, no_material, power_outage."
            ),
        },
    ),
    "boms": TableInfo(
        description="Bill-of-materials headers for a finished-good product (versioned).",
        module="production",
        synonyms=("bom", "boms", "bill of materials"),
        columns={"version": ColumnInfo("BOM version.")},
    ),
    "bom_items": TableInfo(
        description="Component/quantity lines within a BOM.",
        module="production",
        synonyms=("bom item", "bom items", "bom line"),
        columns={"quantity_required": ColumnInfo("Quantity of the component required.")},
    ),
    "production_orders": TableInfo(
        description=(
            "Manufacturing orders to produce a quantity of a product, optionally tied to "
            "the sales order that triggered them (make-to-order)."
        ),
        module="production",
        synonyms=("production order", "production orders", "manufacturing order", "work order"),
        columns={
            "quantity_planned": ColumnInfo("Planned production quantity.", ("planned quantity",)),
            "status": ColumnInfo(
                "Production order status: planned, in_progress, completed, on_hold, cancelled."
            ),
            "planned_start": ColumnInfo("Planned start date."),
            "planned_end": ColumnInfo("Planned end date."),
        },
    ),
    "production_order_items": TableInfo(
        description="Raw-material/component consumption lines for a production order.",
        module="production",
        synonyms=("production consumption", "material consumption"),
        columns={"quantity_consumed": ColumnInfo("Quantity of the component actually consumed.")},
    ),
    "production_output": TableInfo(
        description="Completed-goods output records for a production order on a given date.",
        module="production",
        synonyms=("production output", "output", "produced quantity"),
        columns={
            "quantity_produced": ColumnInfo("Quantity produced.", ("quantity produced", "output quantity")),
            "output_date": ColumnInfo("Date the output was produced."),
        },
    ),
    "production_rejections": TableInfo(
        description=(
            "Quality-rejected quantity for a production order; the numerator of the "
            "'Production Rejection %' measure."
        ),
        module="production",
        synonyms=("production rejection", "production rejections", "quality rejection", "defect", "scrap"),
        columns={
            "quantity_rejected": ColumnInfo(
                "Quantity rejected for quality reasons.", ("rejected quantity", "rejection quantity")
            ),
            "reason": ColumnInfo(
                "Rejection reason: quality_defect, dimension_mismatch, material_fault, process_error."
            ),
        },
    ),
    # -- order-to-delivery domain -----------------------------------------------
    "packings": TableInfo(
        description="Packing/staging step for a sales order prior to dispatch.",
        module="order_to_delivery",
        synonyms=("packing", "packings", "packaging"),
        columns={"status": ColumnInfo("Packing status: pending, in_progress, completed.")},
    ),
    "dispatches": TableInfo(
        description="Dispatch of a packed sales order from the branch/warehouse.",
        module="order_to_delivery",
        synonyms=("dispatch", "dispatches"),
        columns={
            "dispatch_date": ColumnInfo("Date of dispatch."),
            "status": ColumnInfo("Dispatch status: pending, dispatched, in_transit."),
        },
    ),
    "shipments": TableInfo(
        description="Carrier/tracking information for a dispatch.",
        module="order_to_delivery",
        synonyms=("shipment", "shipments", "shipping"),
        columns={
            "carrier": ColumnInfo("Shipping carrier name."),
            "tracking_number": ColumnInfo("Carrier tracking number."),
        },
    ),
    "deliveries": TableInfo(
        description=(
            "Final delivery outcome for a sales order: expected vs. actual delivery date, "
            "current status, and computed delay in days. `delay_days` materializes the "
            "'Delivery Delay' measure (actual_delivery_date - expected_delivery_date)."
        ),
        module="order_to_delivery",
        synonyms=(
            "delivery",
            "deliveries",
            "delivered",
            "delayed delivery",
            "delayed deliveries",
            "delivery delay",
            "late delivery",
        ),
        columns={
            "expected_delivery_date": ColumnInfo(
                "Expected delivery date.", ("expected delivery date",)
            ),
            "actual_delivery_date": ColumnInfo("Actual delivery date.", ("actual delivery date",)),
            "status": ColumnInfo(
                "Delivery status: pending, out_for_delivery, delivered, delayed, failed.",
                ("delivery status",),
            ),
            "delay_days": ColumnInfo(
                "actual_delivery_date - expected_delivery_date, in days; 0/negative = on-time/early.",
                ("delay days", "days delayed", "delivery delay"),
            ),
        },
    ),
    "delivery_delays": TableInfo(
        description=(
            "Explanatory delay-reason log entries for a delivery, supporting root-cause "
            "analysis of late deliveries."
        ),
        module="order_to_delivery",
        synonyms=("delivery delay reason", "delay reason", "delay log"),
        columns={
            "reason": ColumnInfo(
                "Delay reason: traffic, vehicle_breakdown, customer_unavailable, weather, "
                "address_issue, warehouse_delay."
            ),
            "days_delayed": ColumnInfo("Days delayed for this reason entry.", ("days delayed",)),
        },
    ),
    # -- task management domain --------------------------------------------------
    "task_categories": TableInfo(
        description="Task categorization tags (e.g. Follow-up, Maintenance, Documentation).",
        module="tasks",
        synonyms=("task category", "task categories"),
        columns={"name": ColumnInfo("Category name.")},
    ),
    "task_priorities": TableInfo(
        description="Task priority levels (Low/Medium/High/Urgent) with a numeric sort level.",
        module="tasks",
        synonyms=("task priority", "task priorities", "priority"),
        columns={"name": ColumnInfo("Priority name.")},
    ),
    "tasks": TableInfo(
        description=(
            "Units of work, optionally linked back to a record in another module via "
            "related_module/related_record_id."
        ),
        module="tasks",
        synonyms=("task", "tasks", "to-do", "todo", "follow-up"),
        columns={
            "title": ColumnInfo("Task title."),
            "status": ColumnInfo("Task status: open, in_progress, completed, cancelled."),
            "due_date": ColumnInfo("Task due date.", ("due date",)),
        },
    ),
    "task_assignments": TableInfo(
        description="Additional employees assigned to a task beyond the primary assignee.",
        module="tasks",
        synonyms=("task assignment", "task assignments"),
        columns={"role": ColumnInfo("Assignment role: assignee, reviewer, watcher.")},
    ),
    "task_comments": TableInfo(
        description="Comment thread entries on a task.",
        module="tasks",
        synonyms=("task comment", "task comments"),
        columns={"comment": ColumnInfo("Comment text.")},
    ),
    "task_status_history": TableInfo(
        description="Audit trail of every status transition of a task.",
        module="tasks",
        synonyms=("task status history", "task history"),
        columns={"new_status": ColumnInfo("Status the task transitioned to.")},
    ),
    # -- finance domain --------------------------------------------------------
    "accounts": TableInfo(
        description="Chart-of-accounts entries (asset/liability/income/expense/equity).",
        module="finance",
        synonyms=("account", "accounts", "chart of accounts", "ledger account"),
        columns={
            "account_type": ColumnInfo("Account type: asset, liability, income, expense, equity.")
        },
    ),
    "financial_transactions": TableInfo(
        description=(
            "Generic ledger transactions against an account, optionally referencing the "
            "source document (sales invoice, supplier invoice, etc.) that generated them."
        ),
        module="finance",
        synonyms=("financial transaction", "transactions", "ledger entry", "journal entry"),
        columns={
            "amount": ColumnInfo("Transaction amount."),
            "transaction_type": ColumnInfo("Transaction type: debit, credit."),
            "transaction_date": ColumnInfo("Date of the transaction."),
        },
    ),
    "expenses": TableInfo(
        description="Operating expenses, optionally attributed to a department and requiring approval.",
        module="finance",
        synonyms=("expense", "expenses", "cost", "spending"),
        columns={
            "amount": ColumnInfo("Expense amount.", ("expense amount",)),
            "category": ColumnInfo(
                "Expense category: travel, utilities, rent, marketing, office_supplies, other."
            ),
            "expense_date": ColumnInfo("Date the expense was incurred."),
            "status": ColumnInfo("Expense status: pending, approved, rejected, reimbursed."),
        },
    ),
    "receivables": TableInfo(
        description=(
            "Money owed BY a customer TO the company, typically generated from a sales "
            "invoice; tracks aging/collection status."
        ),
        module="finance",
        synonyms=("receivable", "receivables", "ar", "accounts receivable", "amount due from customer"),
        columns={
            "amount": ColumnInfo("Outstanding amount owed by the customer.", ("outstanding amount",)),
            "status": ColumnInfo(
                "Receivable status: pending, partially_collected, collected, overdue, written_off."
            ),
            "due_date": ColumnInfo("Date the receivable is due."),
        },
    ),
    "payables": TableInfo(
        description=(
            "Money owed BY the company TO a supplier, typically generated from a supplier "
            "invoice; tracks aging/payment status."
        ),
        module="finance",
        synonyms=("payable", "payables", "ap", "accounts payable", "amount owed to supplier"),
        columns={
            "amount": ColumnInfo("Outstanding amount owed to the supplier.", ("outstanding amount",)),
            "status": ColumnInfo("Payable status: pending, partially_paid, paid, overdue."),
            "due_date": ColumnInfo("Date the payable is due."),
        },
    ),
    # -- HR domain ---------------------------------------------------------------
    "attendance": TableInfo(
        description="Daily attendance records for employees.",
        module="hr",
        synonyms=("attendance", "present", "absent", "clock-in", "check-in"),
        columns={
            "status": ColumnInfo(
                "Attendance status: present, absent, half_day, on_leave, holiday.",
                ("attendance status",),
            ),
            "date": ColumnInfo("Attendance date."),
            "hours_worked": ColumnInfo("Hours worked that day.", ("hours worked",)),
        },
    ),
    "leave_requests": TableInfo(
        description="Employee leave applications.",
        module="hr",
        synonyms=("leave", "leave request", "leave requests", "leave application"),
        columns={
            "leave_type": ColumnInfo("Leave type: casual, sick, earned, unpaid."),
            "status": ColumnInfo("Leave status: pending, approved, rejected, cancelled."),
        },
    ),
    "payroll": TableInfo(
        description="Monthly payroll run lines for employees.",
        module="hr",
        synonyms=("payroll", "salary", "pay", "compensation"),
        columns={
            "net_pay": ColumnInfo(
                "basic + allowances - deductions, paid out to the employee.", ("net pay", "take-home pay")
            ),
            "status": ColumnInfo("Payroll status: pending, processed, paid."),
        },
    ),
    "employee_performance": TableInfo(
        description="Periodic performance review scores for employees.",
        module="hr",
        synonyms=("performance", "performance review", "employee performance", "appraisal"),
        columns={"score": ColumnInfo("Performance score, typically 0.00-5.00.", ("performance score",))},
    ),
}


# ---------------------------------------------------------------------------
# Measures (DAX-like semantic measures, per CLAUDE.md / prompt.txt section 37)
# ---------------------------------------------------------------------------

MEASURES: list[Measure] = [
    Measure(
        name="Total Revenue",
        expression="SUM(sales_invoices.total_amount)",
        synonyms=("revenue", "sales revenue", "sales value", "turnover", "total sales"),
        format="currency",
        description="Sum of total_amount across valid sales invoices.",
    ),
    Measure(
        name="Purchase Value",
        expression="SUM(purchase_orders.total_amount)",
        synonyms=("purchase value", "purchase amount", "procurement value", "total purchase"),
        format="currency",
        description="Sum of total_amount across purchase orders.",
    ),
    Measure(
        name="Total Orders",
        expression="COUNT(sales_orders.id)",
        synonyms=("total orders", "order count", "number of orders", "orders placed"),
        format="number",
        description="Count of sales orders placed.",
    ),
    Measure(
        name="Total Purchase Orders",
        expression="COUNT(purchase_orders.id)",
        synonyms=("total purchase orders", "purchase order count", "number of purchase orders"),
        format="number",
        description="Count of purchase orders raised.",
    ),
    Measure(
        name="Average Order Value",
        expression="SUM(sales_orders.total_amount) / NULLIF(COUNT(sales_orders.id), 0)",
        synonyms=("average order value", "aov", "avg order value", "mean order value"),
        format="currency",
        description="Total sales order value divided by the number of sales orders.",
    ),
    Measure(
        name="Conversion Rate",
        expression=(
            "COUNT(DISTINCT CASE WHEN leads.status = 'converted' THEN leads.id END) "
            "/ NULLIF(COUNT(DISTINCT leads.id), 0) * 100"
        ),
        synonyms=("conversion rate", "lead conversion", "conversion %", "win rate"),
        format="percent",
        description="Percentage of leads whose status is 'converted'.",
    ),
    Measure(
        name="Gross Margin",
        expression=(
            "(SUM(sales_order_items.line_total) - SUM(sales_order_items.quantity * products.unit_cost)) "
            "/ NULLIF(SUM(sales_order_items.line_total), 0) * 100"
        ),
        synonyms=("gross margin", "margin", "margin %", "profit margin"),
        format="percent",
        description=(
            "(Revenue - cost of goods sold) / Revenue, using sales_order_items.line_total as revenue "
            "and products.unit_cost * quantity as cost."
        ),
    ),
    Measure(
        name="Delivery Delay",
        expression="deliveries.actual_delivery_date - deliveries.expected_delivery_date",
        synonyms=("delivery delay", "delay days", "days late", "shipment delay"),
        format="days",
        description=(
            "actual_delivery_date - expected_delivery_date in days (also materialized as "
            "deliveries.delay_days); positive means late, zero/negative means on-time or early."
        ),
    ),
    Measure(
        name="Delivery Delay %",
        expression=(
            "COUNT(CASE WHEN deliveries.delay_days > 0 THEN deliveries.id END) "
            "/ NULLIF(COUNT(deliveries.id), 0) * 100"
        ),
        synonyms=("delivery delay %", "delayed delivery rate", "late delivery %", "% delayed deliveries"),
        format="percent",
        description="Percentage of deliveries with delay_days > 0 (i.e. delivered later than expected).",
    ),
    Measure(
        name="Inventory Turnover",
        expression=(
            "SUM(CASE WHEN stock_movements.movement_type = 'dispatch' THEN stock_movements.quantity ELSE 0 END) "
            "/ NULLIF(AVG(stock.quantity_on_hand), 0)"
        ),
        synonyms=("inventory turnover", "stock turnover", "turnover ratio"),
        format="number",
        description="Total dispatched quantity over a period divided by average on-hand stock quantity.",
    ),
    Measure(
        name="Production Rejection %",
        expression=(
            "SUM(production_rejections.quantity_rejected) "
            "/ NULLIF(SUM(production_output.quantity_produced) + SUM(production_rejections.quantity_rejected), 0) * 100"
        ),
        synonyms=("production rejection %", "rejection rate", "defect rate", "scrap rate", "quality rejection %"),
        format="percent",
        description=(
            "Rejected quantity as a percentage of total quantity attempted "
            "(produced + rejected) for production orders."
        ),
    ),
    Measure(
        name="Employee Attendance %",
        expression=(
            "COUNT(CASE WHEN attendance.status = 'present' THEN attendance.id END) "
            "/ NULLIF(COUNT(attendance.id), 0) * 100"
        ),
        synonyms=("attendance %", "attendance rate", "employee attendance", "attendance percentage"),
        format="percent",
        description="Percentage of attendance records marked 'present' out of all attendance records.",
    ),
]


# ---------------------------------------------------------------------------
# Backward-compatible flat view: {table_name: description}. Used by
# `app/api/metadata.py`'s fallback path when the in-process cache hasn't
# been populated yet (before `refresh_metadata_cache()` has run).
# ---------------------------------------------------------------------------
TABLE_DESCRIPTIONS: dict[str, str] = {name: info.description for name, info in TABLES.items()}
