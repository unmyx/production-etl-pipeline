# Production-Style ETL Pipeline

End-to-end ETL project that extracts data from a public REST API and a synthetic CSV source,
cleans and validates it in Python, loads a PostgreSQL staging layer and a small star schema,
and exposes analytical SQL views on top of the final model.

Portfolio project built on public API data and generated source data. Not client work.

## Verified Results

Measured against the current DummyJSON API snapshot used during verification. The public API
can change, so rerunning the pipeline later is not guaranteed to reproduce these numbers.

| Check | Verified result |
| --- | --- |
| Automated tests | 43 passed |
| PostgreSQL integration tests | 3 passed |
| Customers | 208 |
| Products | 194 |
| Orders | 208 |
| Order items | 800 |
| Units sold | 2,417 |
| Net revenue | 3,456,709.58 |
| Gross revenue | 3,834,278.63 |
| Source vs loaded net revenue | reconciled |
| Foreign-key orphans | 0 |
| Successful pipeline executions | 9 |
| Idempotency | fact row count unchanged at 800 |

## Business scenario

A direct-to-consumer retailer sells physical goods across many product categories. Order data
arrives from a commerce API as nested cart documents, while customer segmentation is maintained
separately as a CSV extract from the marketing team. The data team needs one repeatable nightly
job that:

- lands the raw API payloads for audit,
- flattens cart documents into order-line facts,
- refuses to publish data that fails quality checks,
- and refreshes a small analytics model that answers revenue questions by category, customer
  and day.

The pipeline is deliberately small enough to read in one sitting, but it exercises the parts of
data engineering that matter: pagination, raw snapshots, transformation, validation,
referential integrity, idempotent loading, run metadata and reconciliation.

## Architecture

```text
DummyJSON REST API                    Synthetic CSV
  users / products / carts              customer segments
          |                                   |
          +----------------+------------------+
                           v
                   Extraction (requests)
                           v
                Raw JSON snapshots (data/raw)
                           v
             Transformation (pandas, flattening)
                           v
              Validation (rules + reconciliation)
                           v
              PostgreSQL staging schema (upserts)
                           v
            PostgreSQL analytics schema (star model)
                           v
                  Analytical SQL views
                           v
              pipeline_runs metadata table
```

## Data sources

**REST API: DummyJSON** (`https://dummyjson.com`)

| Resource | Rows | Notes |
| --- | --- | --- |
| `users` | 208 | Source of customer dimension attributes |
| `products` | 194 | Source of product dimension attributes |
| `carts` | 208 | Nested documents, one per user, each containing order lines |

All three resources are read with `limit`/`skip` pagination. The extractor loops until the API
reported `total` is reached, so a single response is never assumed to be the whole dataset.
The 208 carts contain 800 order lines, and a cart can legitimately contain the same product on
more than one line, so the fact grain is `(order_id, line_number)` rather than
`(order_id, product_id)`.

**CSV: synthetic customer segmentation**

`scripts/generate_customer_segments.py` produces `data/source/customer_segments.csv`. Customer
ids are derived from the extracted `users` payload, never hard-coded: the generator reads the
latest raw snapshot (or calls the API when no snapshot exists) and emits one deterministic
segment row per real customer id. Assignment is based on a SHA-256 hash of the customer id, so
the same input always produces the same file.

Columns: `customer_id`, `segment`, `region`, `acquisition_channel`.

## Transformations

- `transform_users` flattens `address.country` and `company.name` and builds a trimmed
  `full_name`.
- `transform_products` maps title, category, brand, price, rating and stock into a product frame.
- `transform_orders` builds one header row per cart with gross value, discounted value, product
  count and quantity count.
- `transform_order_items` flattens each nested `products` array into one row per cart line,
  assigns a 1-based `line_number` and derives `discount_amount = line_total - discounted_total`.
- `build_customer_dimension` joins users to the segmentation CSV; `build_product_dimension`
  drops staging-only columns.
- `build_date_dimension` and `attach_date_key` expand order dates into calendar attributes and
  key each fact row to a date.

## Technology stack

- Python 3.11+ with `requests`, `pandas` and `SQLAlchemy`
- PostgreSQL 16 accessed through `psycopg` 3
- Plain SQL for schema, upserts and analytical views
- `pytest` for unit and PostgreSQL-backed integration tests
- Docker Compose for the local database

## Repository structure

```text
.
|-- docker-compose.yml            Local PostgreSQL 16 service
|-- pyproject.toml                Dependencies, packaging, pytest config
|-- .env.example                  Safe example configuration
|-- sql/
|   `-- schema.sql                Staging, analytics, and view definitions
|-- scripts/
|   `-- generate_customer_segments.py
|-- src/etl_pipeline/
|   |-- config.py                 Environment driven settings
|   |-- logging_config.py         Python logging setup
|   |-- extract.py                Paginated API client and raw snapshots
|   |-- segments.py               Deterministic segmentation generator
|   |-- transform.py              Flattening and dimension building
|   |-- validate.py               Validation and reconciliation rules
|   |-- load.py                   Schema application and idempotent upserts
|   `-- pipeline.py               Orchestration and run tracking
|-- tests/
|   |-- conftest.py               Shared source fixtures
|   |-- test_extract.py           Pagination and snapshot behaviour
|   |-- test_transform.py         Nested cart flattening and dimensions
|   |-- test_segments.py          Segmentation determinism
|   |-- test_validation.py        Every validation rule
|   `-- test_pipeline_integration.py  PostgreSQL end-to-end and idempotency
`-- data/
    |-- raw/                      Latest API snapshots plus per-run history (generated)
    `-- source/                   Generated CSV source
```

## Database model

Two schemas are used. `staging` holds cleaned source-level data; `analytics` holds the model
that consumers query.

Staging tables:

| Table | Grain | Key |
| --- | --- | --- |
| `staging.customers` | One row per API user | `customer_id` |
| `staging.products` | One row per API product | `product_id` |
| `staging.orders` | One row per cart header | `order_id` |
| `staging.order_items` | One row per cart line | `(order_id, line_number)` |
| `staging.customer_segments` | One row per segmented customer | `customer_id` |

Analytics tables:

| Table | Grain | Key |
| --- | --- | --- |
| `analytics.dim_customer` | Customer with segmentation attributes | `customer_id` |
| `analytics.dim_product` | Product attributes | `product_id` |
| `analytics.dim_date` | Calendar day | `date_key` (`YYYYMMDD`) |
| `analytics.fact_order_item` | One row per order line | `(order_id, line_number)` |
| `analytics.pipeline_runs` | One row per pipeline execution | `run_id` |

`fact_order_item` references `dim_customer`, `dim_product` and `dim_date` with foreign keys, and
carries quantity, unit price, gross line total, discount percentage, discount amount and net
discounted total. Foreign keys, primary keys, check constraints on quantities and monetary
values, and indexes on the customer, product and date columns are defined in `sql/schema.sql`.

Analytical views:

| View | Answers |
| --- | --- |
| `analytics.vw_sales_by_category` | Revenue, orders and units by product category |
| `analytics.vw_customer_sales` | Revenue and average order value per customer, with segment |
| `analytics.vw_daily_sales` | Daily order, unit and revenue trend |
| `analytics.vw_product_performance` | Best selling products by units and revenue |

Every view reads from `analytics.fact_order_item` joined to the dimensions. No view contains
hard-coded results.

## Validation rules

Validation runs after transformation and before anything is written to the analytics model.
Any validation failure raises `ValidationError`, stops the run before the load, and is recorded
as a `FAILED` run.

Required columns

- Each of the five transformed frames must contain its documented columns.

Required values

- Customer id, name and email are not null.
- Product id, name, category and price are not null.
- Order id, customer id, order date and net value are not null.
- Order-item keys, quantity, unit price and discounted total are not null.
- Segment, region and acquisition channel are not null.

Keys and uniqueness

- `customer_id`, `product_id`, `order_id` and segment `customer_id` are unique.
- `(order_id, line_number)` is unique in order items.

Business rules

- Quantities are strictly positive.
- Unit prices, line totals, discount amounts and discounted totals are not negative.
- Discount percentage is between 0 and 100.
- Discounted total never exceeds the gross line total.

Referential integrity

- Every order-item `customer_id` exists in customers.
- Every order-item `product_id` exists in products.
- Every order `customer_id` exists in customers.

Segmentation consistency

- Every extracted customer has exactly one segment row.
- No segment row references an unknown customer.

Row-count sanity and reconciliation

- No transformed frame is empty, and every order has at least one order line.
- Order ids in the header frame match order ids in the flattened frame.
- Flattened order-line count equals the `totalProducts` the API reports per cart.
- Loaded `fact_order_item` count equals the transformed order-line count.
- Loaded `dim_customer` and `dim_product` counts equal the transformed dimensions.
- Loaded net revenue equals the transformed sum of discounted totals.

The row-count and revenue reconciliation checks run inside the same transaction as the load, so
a mismatch rolls the whole load back.

## Idempotency approach

The pipeline is safe to run repeatedly. Each load step writes the incoming frame into a
temporary table and then issues `INSERT ... ON CONFLICT (key) DO UPDATE`, so a rerun updates
existing rows instead of appending duplicates:

- `staging.customers`, `staging.products`, `staging.orders`, `staging.order_items` and
  `staging.customer_segments` upsert on their natural keys.
- `analytics.dim_customer`, `analytics.dim_product` and `analytics.dim_date` upsert on their
  dimension keys.
- `analytics.fact_order_item` upserts on `(order_id, line_number)`.
- `analytics.pipeline_runs` is append-only by design; one row is written per execution.

Nothing is dropped or truncated. `sql/schema.sql` is idempotent (`CREATE ... IF NOT EXISTS`,
and the views are dropped and recreated so definition changes are applied) and is applied at the
start of every run. Running the pipeline twice leaves the analytics model unchanged; the
verified counts below show this.

## How to run locally

1. Create your environment file:

```bash
cp .env.example .env
```

2. Start PostgreSQL:

```bash
docker compose up -d db
```

3. Create a virtual environment and install the project:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
```

4. Generate the synthetic CSV source:

```bash
python scripts/generate_customer_segments.py
```

5. Run the pipeline (internet access is required for the API step):

```bash
python -m etl_pipeline.pipeline
```

The same entry point is available as the `etl-pipeline` console script after installation.

The database password in `.env.example` and `docker-compose.yml` is a throwaway value for the
local container. Replace it before pointing the pipeline at any shared database.

## How to run tests

```bash
pytest
```

Unit tests run anywhere. The three tests in `tests/test_pipeline_integration.py` are marked
`integration`: they create and drop a throwaway `etl_demo_test` database and cover idempotency,
view output, failure handling and transaction rollback. They skip automatically when PostgreSQL
is not reachable. Run only the unit tests with:

```bash
pytest -m "not integration"
```

## Example analytical queries

Revenue by category:

```sql
SELECT category, orders, units_sold, net_revenue
FROM analytics.vw_sales_by_category
ORDER BY net_revenue DESC
LIMIT 5;
```

Top customers within a segment:

```sql
SELECT customer_name, segment, region, orders, net_revenue, avg_order_value
FROM analytics.vw_customer_sales
WHERE segment = 'Enterprise'
ORDER BY net_revenue DESC
LIMIT 5;
```

Daily revenue trend with a weekend flag:

```sql
SELECT full_date, day_name, orders, units_sold, net_revenue
FROM analytics.vw_daily_sales
ORDER BY full_date;
```

Segment rollup straight off the fact table:

```sql
SELECT
    c.segment,
    COUNT(DISTINCT f.order_id) AS orders,
    ROUND(SUM(f.discounted_total), 2) AS net_revenue
FROM analytics.fact_order_item f
JOIN analytics.dim_customer c ON c.customer_id = f.customer_id
GROUP BY c.segment
ORDER BY net_revenue DESC;
```

Run history and row counts:

```sql
SELECT run_id, run_label, status, rows_order_items, rows_fact_order_item, completed_at
FROM analytics.pipeline_runs
ORDER BY run_id;
```

## Example output

Real output from a local run against the live DummyJSON API and a generated CSV source:

```text
Transformed 208 customers, 194 products, 208 orders, 800 order items
Validation passed: 208 customers, 194 products, 208 orders, 800 order items, 208 segment rows
Reconciliation passed for analytics.fact_order_item: 800 rows
Revenue reconciliation passed for analytics.fact_order_item net revenue: 3456709.58
Pipeline run 20260928T162917Z completed successfully
```

Loaded row counts:

| Table | Rows |
| --- | --- |
| `staging.customers` | 208 |
| `staging.products` | 194 |
| `staging.orders` | 208 |
| `staging.order_items` | 800 |
| `staging.customer_segments` | 208 |
| `analytics.dim_customer` | 208 |
| `analytics.dim_product` | 194 |
| `analytics.dim_date` | 208 |
| `analytics.fact_order_item` | 800 |

Source and loaded revenue agree exactly: `3456709.58` net, `3834278.63` gross.

Top categories from `analytics.vw_sales_by_category`:

```text
      category      | orders | units_sold | gross_revenue | net_revenue
--------------------+--------+------------+---------------+--------------
 vehicle            |     19 |         60 |    1875999.40 |   1682064.05
 motorcycle         |     22 |         84 |     669999.16 |    609460.61
 mens-watches       |     24 |         72 |     644849.28 |    593063.86
 womens-watches     |     17 |         45 |     282859.55 |    249189.51
 laptops            |     16 |         56 |      91899.44 |     85006.24
```

Top customers from `analytics.vw_customer_sales`:

```text
 customer_id |  customer_name  |  segment   | region | orders | units_sold | net_revenue
-------------+-----------------+------------+--------+--------+------------+-------------
          30 | Addison Wright  | SMB        | South  |      1 |         15 |   155507.16
          52 | Grace Perry     | Consumer   | West   |      1 |         18 |   130175.28
          95 | Miles Stevenson | Enterprise | North  |      1 |         24 |   129783.31
```

Run metadata after two consecutive executions:

```text
 run_id |    run_label     | status  | rows_order_items | rows_fact_order_item
--------+------------------+---------+------------------+----------------------
      1 | 20260928T162917Z | SUCCESS |              800 |                  800
      2 | 20260928T162926Z | SUCCESS |              800 |                  800
```

The fact table still holds 800 rows after the second run, and the foreign-key orphan checks for
customer, product and date return zero.

## Limitations and assumptions

- DummyJSON is a public demo API. It is not transactional and the payload can change without
  notice, so the row counts above are a snapshot of one day, not a fixed guarantee.
- Carts in DummyJSON carry no date field. Order dates are synthesised deterministically from
  `order_id` (a stable offset within a 364-day window). `dim_date` and `vw_daily_sales`
  therefore demonstrate the modelling pattern rather than real trading dates. Replacing
  `synthesize_order_date` with a real order timestamp is the only change needed to make them
  meaningful.
- The customer segmentation CSV is synthetic. Segments are hash-derived, so they are
  reproducible and correctly keyed to real customer ids, but they carry no business meaning.
- The pipeline reloads the current source data into staging using upserts. There is no
  incremental watermark, no orchestration scheduler and no delete detection; source records
  removed upstream stay in the model.
- Loads are single-transaction and synchronous. The dataset is small enough that batching by
  chunk and parallel extraction were deliberately not added.
- Raw snapshots are kept per run under `data/raw/history/<run_label>/` with no retention or
  pruning policy, so that directory grows with every execution.
- Failures during extraction or transformation happen before the run row is created, so they
  appear in the logs but not in `pipeline_runs`. Only validation and load failures are recorded
  as `FAILED`.
- `SQLAlchemy` is pinned below 2.1. Version 2.1 requires its compiled Cython extension to be
  importable, which is not guaranteed on every platform; the 2.0 line ships a pure-Python
  fallback and keeps the project portable.
