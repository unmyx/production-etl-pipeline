from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .extract import ApiClient, extract_api_data, load_customer_segments
from .load import (
    create_engine_from_url,
    fetch_loaded_counts,
    initialize_database,
    record_run_finish,
    record_run_start,
    upsert_dataframe,
)
from .logging_config import configure_logging
from .transform import (
    attach_date_key,
    build_customer_dimension,
    build_date_dimension,
    build_product_dimension,
    read_json,
    transform_order_items,
    transform_orders,
    transform_products,
    transform_users,
)
from .validate import (
    validate_reconciliation,
    validate_revenue_reconciliation,
    validate_sources,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
CSV_PATH = ROOT / "data" / "source" / "customer_segments.csv"


def run_pipeline(settings: Settings | None = None, client: ApiClient | None = None) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    started_at = datetime.now(timezone.utc)
    run_label = started_at.strftime("%Y%m%dT%H%M%SZ")
    logger.info("Pipeline run %s starting", run_label)

    api_client = client or ApiClient(
        settings.api_base_url,
        settings.request_timeout,
        settings.api_page_size,
    )
    snapshot_dir = extract_api_data(api_client, RAW_DIR, run_label)

    customers = transform_users(read_json(snapshot_dir / "users.json"))
    products = transform_products(read_json(snapshot_dir / "products.json"))
    carts = read_json(snapshot_dir / "carts.json")
    orders = transform_orders(carts)
    order_items = transform_order_items(carts)
    segments = load_customer_segments(CSV_PATH)
    logger.info(
        "Transformed %s customers, %s products, %s orders, %s order items",
        len(customers),
        len(products),
        len(orders),
        len(order_items),
    )

    engine = create_engine_from_url(settings.database_url)
    initialize_database(engine)
    run_id = record_run_start(engine, run_label, started_at)

    counts: dict[str, Any] = {
        "rows_customers": len(customers),
        "rows_products": len(products),
        "rows_orders": len(orders),
        "rows_order_items": len(order_items),
        "rows_customer_segments": len(segments),
        "rows_fact_order_item": None,
    }

    try:
        validate_sources(customers, products, orders, order_items, segments)

        dim_customer = build_customer_dimension(customers, segments)
        dim_product = build_product_dimension(products)
        dim_date = build_date_dimension(orders["order_date"])
        fact_order_item = attach_date_key(order_items, orders)

        with engine.begin() as connection:
            upsert_dataframe(
                connection, customers, "staging", "customers", "customer_id",
                touch_column="loaded_at",
            )
            upsert_dataframe(
                connection, products, "staging", "products", "product_id",
                touch_column="loaded_at",
            )
            upsert_dataframe(
                connection, orders, "staging", "orders", "order_id",
                touch_column="loaded_at",
            )
            upsert_dataframe(
                connection, order_items, "staging", "order_items",
                ["order_id", "line_number"], touch_column="loaded_at",
            )
            upsert_dataframe(
                connection, segments, "staging", "customer_segments", "customer_id",
                touch_column="loaded_at",
            )
            upsert_dataframe(
                connection, dim_customer, "analytics", "dim_customer", "customer_id"
            )
            upsert_dataframe(
                connection, dim_product, "analytics", "dim_product", "product_id"
            )
            upsert_dataframe(
                connection, dim_date, "analytics", "dim_date", "date_key"
            )
            upsert_dataframe(
                connection, fact_order_item, "analytics", "fact_order_item",
                ["order_id", "line_number"], touch_column="loaded_at",
            )

            loaded = fetch_loaded_counts(connection)
            validate_reconciliation(
                len(order_items), int(loaded["rows_fact_order_item"]),
                "analytics.fact_order_item",
            )
            validate_reconciliation(
                len(dim_customer), int(loaded["rows_customers"]),
                "analytics.dim_customer",
            )
            validate_reconciliation(
                len(dim_product), int(loaded["rows_products"]),
                "analytics.dim_product",
            )
            validate_revenue_reconciliation(
                round(float(order_items["discounted_total"].sum()), 2),
                float(loaded["net_revenue"]),
                "analytics.fact_order_item net revenue",
            )

        counts["rows_fact_order_item"] = int(loaded["rows_fact_order_item"])
        record_run_finish(engine, run_id, "SUCCESS", counts)
    except Exception as exc:
        logger.error("Pipeline run %s failed: %s", run_label, exc)
        record_run_finish(engine, run_id, "FAILED", counts, error_message=str(exc)[:2000])
        raise

    logger.info("Pipeline run %s completed successfully", run_label)
    return {"run_label": run_label, "run_id": run_id, **counts}


def main() -> None:
    result = run_pipeline()
    logger.info("Final status: SUCCESS %s", result)


if __name__ == "__main__":
    main()
