CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS staging.customers (
    customer_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    age INTEGER,
    country TEXT,
    company TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    unit_price NUMERIC(14, 2) NOT NULL,
    rating NUMERIC(4, 2),
    stock INTEGER,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES staging.customers (customer_id),
    order_date DATE NOT NULL,
    gross_value NUMERIC(16, 2) NOT NULL,
    net_value NUMERIC(16, 2) NOT NULL,
    total_products INTEGER NOT NULL,
    total_quantity INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staging.order_items (
    order_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES staging.customers (customer_id),
    product_id INTEGER NOT NULL REFERENCES staging.products (product_id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(14, 2) NOT NULL,
    line_total NUMERIC(16, 2) NOT NULL,
    discount_percentage NUMERIC(6, 2) NOT NULL,
    discounted_total NUMERIC(16, 2) NOT NULL,
    discount_amount NUMERIC(16, 2) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (order_id, line_number)
);

CREATE INDEX IF NOT EXISTS ix_staging_order_items_product
    ON staging.order_items (product_id);

CREATE TABLE IF NOT EXISTS staging.customer_segments (
    customer_id INTEGER PRIMARY KEY,
    segment TEXT NOT NULL,
    region TEXT NOT NULL,
    acquisition_channel TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics.dim_customer (
    customer_id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    email TEXT,
    age INTEGER,
    country TEXT,
    company TEXT,
    segment TEXT NOT NULL,
    region TEXT NOT NULL,
    acquisition_channel TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_product (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    unit_price NUMERIC(14, 2) NOT NULL,
    rating NUMERIC(4, 2)
);

CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    day_of_month INTEGER NOT NULL,
    day_name TEXT NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.fact_order_item (
    order_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES analytics.dim_customer (customer_id),
    product_id INTEGER NOT NULL REFERENCES analytics.dim_product (product_id),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(14, 2) NOT NULL CHECK (unit_price >= 0),
    line_total NUMERIC(16, 2) NOT NULL CHECK (line_total >= 0),
    discount_percentage NUMERIC(6, 2) NOT NULL CHECK (discount_percentage >= 0),
    discount_amount NUMERIC(16, 2) NOT NULL CHECK (discount_amount >= 0),
    discounted_total NUMERIC(16, 2) NOT NULL CHECK (discounted_total >= 0),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (order_id, line_number)
);

CREATE INDEX IF NOT EXISTS ix_fact_order_item_customer
    ON analytics.fact_order_item (customer_id);

CREATE INDEX IF NOT EXISTS ix_fact_order_item_product
    ON analytics.fact_order_item (product_id);

CREATE INDEX IF NOT EXISTS ix_fact_order_item_date
    ON analytics.fact_order_item (date_key);

CREATE TABLE IF NOT EXISTS analytics.pipeline_runs (
    run_id BIGSERIAL PRIMARY KEY,
    run_label TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    rows_customers INTEGER,
    rows_products INTEGER,
    rows_orders INTEGER,
    rows_order_items INTEGER,
    rows_customer_segments INTEGER,
    rows_fact_order_item INTEGER,
    error_message TEXT
);

DROP VIEW IF EXISTS analytics.vw_sales_by_category;
DROP VIEW IF EXISTS analytics.vw_customer_sales;
DROP VIEW IF EXISTS analytics.vw_daily_sales;
DROP VIEW IF EXISTS analytics.vw_product_performance;

CREATE VIEW analytics.vw_sales_by_category AS
SELECT
    p.category,
    COUNT(DISTINCT f.order_id) AS orders,
    SUM(f.quantity) AS units_sold,
    ROUND(SUM(f.line_total), 2) AS gross_revenue,
    ROUND(SUM(f.discounted_total), 2) AS net_revenue,
    ROUND(AVG(f.discount_percentage), 2) AS avg_discount_percentage
FROM analytics.fact_order_item f
JOIN analytics.dim_product p ON p.product_id = f.product_id
GROUP BY p.category;

CREATE VIEW analytics.vw_customer_sales AS
SELECT
    c.customer_id,
    c.customer_name,
    c.segment,
    c.region,
    c.acquisition_channel,
    COUNT(DISTINCT f.order_id) AS orders,
    SUM(f.quantity) AS units_sold,
    ROUND(SUM(f.discounted_total), 2) AS net_revenue,
    ROUND(SUM(f.discounted_total) / COUNT(DISTINCT f.order_id), 2) AS avg_order_value
FROM analytics.fact_order_item f
JOIN analytics.dim_customer c ON c.customer_id = f.customer_id
GROUP BY c.customer_id, c.customer_name, c.segment, c.region, c.acquisition_channel;

CREATE VIEW analytics.vw_daily_sales AS
SELECT
    d.full_date,
    d.month_name,
    d.day_name,
    d.is_weekend,
    COUNT(DISTINCT f.order_id) AS orders,
    SUM(f.quantity) AS units_sold,
    ROUND(SUM(f.discounted_total), 2) AS net_revenue
FROM analytics.fact_order_item f
JOIN analytics.dim_date d ON d.date_key = f.date_key
GROUP BY d.full_date, d.month_name, d.day_name, d.is_weekend;

CREATE VIEW analytics.vw_product_performance AS
SELECT
    p.product_id,
    p.product_name,
    p.category,
    p.brand,
    COUNT(DISTINCT f.order_id) AS orders,
    SUM(f.quantity) AS units_sold,
    ROUND(SUM(f.discounted_total), 2) AS net_revenue,
    ROUND(AVG(f.discount_percentage), 2) AS avg_discount_percentage
FROM analytics.fact_order_item f
JOIN analytics.dim_product p ON p.product_id = f.product_id
GROUP BY p.product_id, p.product_name, p.category, p.brand;
