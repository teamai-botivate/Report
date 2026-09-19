# DATABASE

## Source of truth

Neon PostgreSQL in production; local dev/test uses a SQLite file through the exact
same SQLAlchemy 2.x async models (`DATABASE_URL` is the only difference — see
`app/core/config.py::_normalize_database_url`). No code forks between the two
engines; Postgres-only syntax is avoided in models and generated SQL so both work.

## Schema: 62 tables across 9 business modules + master data

All models live under `backend/app/models/`, one module per business domain, all
inheriting `TimestampMixin` (`created_at`/`updated_at`) and importing `Base` from
`app/db/session.py`. Import direction is strictly one-way (no circular imports):
`master.py` has zero dependencies on other domain modules; every other module
imports master entities (and, for `production`/`order_to_delivery`/`finance`, sales
and/or purchase entities) as needed.

### Master data (`models/master.py`) — 12 tables
`regions`, `cities`, `branches`, `departments`, `designations`, `warehouses`,
`product_categories`, `products`, `customers`, `suppliers`, `employees`,
`calendar_dates` (one row per day spanning the seeded date range, for
period-comparison queries).

### HR (`models/hr.py`) — 4 tables
`attendance`, `leave_requests`, `payroll`, `employee_performance` — all FK to
`employees` (and transitively `departments`/`designations` via master.py).

### Sales (`models/sales.py`) — 9 tables
`leads` → `enquiries` → `quotations` → `sales_orders` (+ `sales_order_items`) →
`sales_invoices` → `sales_payments`, plus `sales_returns` and `sales_targets`. This
mirrors the funnel in `prompt.txt` section 3: Lead → Enquiry → Quotation → Order →
Invoice → Payment.

### Purchase (`models/purchase.py`) — 7 tables
`purchase_requisitions` → `purchase_orders` (+ `purchase_order_items`) →
`material_receipts` → `supplier_invoices` → `supplier_payments`, plus
`purchase_returns`.

### Inventory (`models/inventory.py`) — 5 tables
`stock`, `stock_movements`, `stock_transfers`, `material_batches`,
`inventory_adjustments` — keyed by `products` × `warehouses` from master.py.

### Production (`models/production.py`) — 9 tables
`work_centers`, `machines`, `machine_downtime`, `boms`, `bom_items`,
`production_orders` (+ `production_order_items`), `production_output`,
`production_rejections`.

### Order-to-Delivery (`models/order_to_delivery.py`) — 5 tables
`packings` → `dispatches` → `shipments` → `deliveries` → `delivery_delays`, linked
back to `sales_orders`. (`delivery_status` is folded into `deliveries.status` rather
than a separate table.)

### Tasks (`models/tasks.py`) — 6 tables
`task_categories`, `task_priorities`, `tasks`, `task_assignments`,
`task_comments`, `task_status_history`.

### Finance (`models/finance.py`) — 5 tables
`accounts`, `financial_transactions`, `expenses`, `receivables`, `payables` — reuses
`sales_invoices`/`supplier_invoices`/`sales_payments`/`supplier_payments` from the
sales/purchase modules rather than duplicating invoice/payment tables.

### Runtime-only (not part of the seeded business schema)
`sql_audit_log` (`models/audit.py`) — every AI-generated query that reaches the
executor is recorded here (SQL text, status, row count, elapsed ms, tables
referenced), regardless of whether it passed validation.

## Conventions

- Every table: integer surrogate primary key `id`.
- Money columns: `Numeric(14, 2)`. Ratings/scores: smaller `Numeric` precision.
- Status/type fields: plain `String` columns with a `comment="Allowed values: ..."`
  annotation instead of native `ENUM` (Postgres-only) or `JSONB` — keeps SQLite and
  Postgres behaviorally identical.
- FK columns and commonly-filtered columns (dates, status) are indexed.
- `relationship()` back-references added only where clearly useful; self-referencing
  FKs (`employees.manager_id`, `product_categories.parent_id`) use `remote_side`.

## Seeding

`backend/scripts/seed_database.py::seed_all(size: "small"|"medium"|"large")` builds
realistically interconnected data — not isolated random rows per table — following
the cascades above (a customer has leads→enquiries→quotations→orders→invoices→
payments with realistic funnel drop-off; a product appears across sales, purchase,
inventory, and production; an employee appears in HR, tasks, and sales/production
assignment). Dates span roughly 2–3 years back from the seed run date, with denser,
more realistic recent data so "this month vs last month" comparisons are meaningful.

Auto-seed on boot (`app/core/bootstrap.py`) runs this automatically against an
empty database and is idempotent — a second boot with existing data skips it.

```bash
python -m scripts.seed_database        # SEED_SIZE from env, default medium
python -m scripts.reset_db --yes       # drop_all + create_all
```

## Metadata / semantic layer

The AI never receives the full 62-table schema in a prompt. `app/semantic_layer/`
maintains a cached dictionary (table/column descriptions, synonyms, and named
business measures like "Total Revenue" → `SUM(sales_invoices.total_amount)`) plus a
deterministic retrieval function that returns only the handful of tables/measures
relevant to the current question. See `AI_ARCHITECTURE.md`.

## Read-only execution boundary

A second SQLAlchemy engine (`app/db/session.py::readonly_engine`) is used to execute
every AI-generated (and recommended-report) SELECT, after it passes
`app/security/sql_guard.py::validate_sql()`. In production this should point at a
real read-only Postgres role via `DATABASE_URL_READONLY`. SQLite has no roles, so in
dev the AST-level allowlist gate is the enforced boundary.
