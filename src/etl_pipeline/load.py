from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def create_engine_from_url(database_url: Any) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, future=True)


def initialize_database(engine: Engine, schema_path: Path = SCHEMA_PATH) -> None:
    statements = schema_path.read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(statements)
    logger.info("Applied database schema from %s", schema_path.name)


def upsert_dataframe(
    connection: Connection,
    frame: pd.DataFrame,
    schema: str,
    table: str,
    key_columns: str | Sequence[str],
    columns: Sequence[str] | None = None,
    touch_column: str | None = None,
) -> int:
    keys = [key_columns] if isinstance(key_columns, str) else list(key_columns)
    selected = list(frame.columns) if columns is None else list(columns)

    if frame.empty:
        logger.warning("Skipping %s.%s load: no rows", schema, table)
        return 0

    payload = frame.loc[:, selected]
    temp_table = f"tmp_{table}_{uuid4().hex[:8]}"
    column_list = ", ".join(selected)

    connection.exec_driver_sql(
        f"CREATE TEMP TABLE {temp_table} ON COMMIT DROP AS "
        f"SELECT {column_list} FROM {schema}.{table} WITH NO DATA"
    )
    payload.to_sql(
        temp_table,
        connection,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=500,
    )

    insert_columns = list(selected)
    select_expressions = list(selected)
    if touch_column:
        insert_columns.append(touch_column)
        select_expressions.append(f"NOW() AS {touch_column}")

    assignments = [f"{column} = EXCLUDED.{column}" for column in selected if column not in keys]
    if touch_column:
        assignments.append(f"{touch_column} = NOW()")
    conflict_action = f"DO UPDATE SET {', '.join(assignments)}" if assignments else "DO NOTHING"

    connection.exec_driver_sql(
        f"INSERT INTO {schema}.{table} ({', '.join(insert_columns)}) "
        f"SELECT {', '.join(select_expressions)} FROM {temp_table} "
        f"ON CONFLICT ({', '.join(keys)}) {conflict_action}"
    )
    logger.info("Upserted %s rows into %s.%s", len(payload), schema, table)
    return len(payload)


def fetch_loaded_counts(connection: Connection) -> Mapping[str, Any]:
    return connection.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM analytics.fact_order_item) AS rows_fact_order_item,
                (SELECT COUNT(*) FROM analytics.dim_customer) AS rows_customers,
                (SELECT COUNT(*) FROM analytics.dim_product) AS rows_products,
                (SELECT COALESCE(SUM(discounted_total), 0) FROM analytics.fact_order_item)
                    AS net_revenue
            """
        )
    ).mappings().one()


def record_run_start(engine: Engine, run_label: str, started_at: Any) -> int:
    with engine.begin() as connection:
        run_id = connection.execute(
            text(
                """
                INSERT INTO analytics.pipeline_runs (run_label, started_at, status)
                VALUES (:run_label, :started_at, 'RUNNING')
                RETURNING run_id
                """
            ),
            {"run_label": run_label, "started_at": started_at},
        ).scalar_one()
    logger.info("Registered pipeline run %s with run_id=%s", run_label, run_id)
    return int(run_id)


def record_run_finish(
    engine: Engine,
    run_id: int,
    status: str,
    counts: Mapping[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    counts = counts or {}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE analytics.pipeline_runs
                SET completed_at = NOW(),
                    status = :status,
                    rows_customers = :rows_customers,
                    rows_products = :rows_products,
                    rows_orders = :rows_orders,
                    rows_order_items = :rows_order_items,
                    rows_customer_segments = :rows_customer_segments,
                    rows_fact_order_item = :rows_fact_order_item,
                    error_message = :error_message
                WHERE run_id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "rows_customers": counts.get("rows_customers"),
                "rows_products": counts.get("rows_products"),
                "rows_orders": counts.get("rows_orders"),
                "rows_order_items": counts.get("rows_order_items"),
                "rows_customer_segments": counts.get("rows_customer_segments"),
                "rows_fact_order_item": counts.get("rows_fact_order_item"),
                "error_message": error_message,
            },
        )
    logger.info("Recorded pipeline run %s as %s", run_id, status)
