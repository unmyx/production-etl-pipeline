from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_pipeline import pipeline as pipeline_module
from etl_pipeline.config import Settings
from etl_pipeline.load import create_engine_from_url
from etl_pipeline.segments import build_segments
from etl_pipeline.validate import ValidationError

TEST_DB_NAME = "etl_demo_test"
EXPECTED_ORDER_ITEMS = 5
EXPECTED_CUSTOMERS = 3
EXPECTED_PRODUCTS = 3


class StubApiClient:
    def __init__(self, sources: dict[str, list[dict]]) -> None:
        self.sources = sources

    def get_all(self, resource: str) -> list[dict]:
        return self.sources[resource]


def extend_carts(carts: list[dict]) -> list[dict]:
    extended = copy.deepcopy(carts)
    extended[1]["products"].append(
        {
            "id": 11,
            "price": 29.99,
            "quantity": 1,
            "total": 29.99,
            "discountPercentage": 0.0,
            "discountedTotal": 29.99,
        }
    )
    extended[1]["total"] = 329.98
    extended[1]["discountedTotal"] = 329.98
    extended[1]["totalProducts"] = 2
    extended[1]["totalQuantity"] = 2
    return extended


@pytest.fixture(scope="module")
def test_settings():
    base = Settings.from_env()
    admin_engine = create_engine_from_url(
        base.database_url.set(database="postgres")
    ).execution_options(isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DB_NAME}"')

    yield replace(base, db_name=TEST_DB_NAME)

    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
    admin_engine.dispose()


@pytest.fixture
def pipeline_paths(tmp_path, monkeypatch, raw_sources):
    csv_path = tmp_path / "customer_segments.csv"
    build_segments(int(user["id"]) for user in raw_sources["users"]).to_csv(
        csv_path, index=False
    )
    monkeypatch.setattr(pipeline_module, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(pipeline_module, "CSV_PATH", csv_path)
    return csv_path


@pytest.fixture
def engine(test_settings):
    engine = create_engine_from_url(test_settings.database_url)
    yield engine
    engine.dispose()


def _scalar(engine, sql: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql)).scalar_one())


@pytest.mark.integration
def test_pipeline_loads_analytics_model_and_is_idempotent(
    test_settings, engine, pipeline_paths, raw_sources
):
    first = pipeline_module.run_pipeline(test_settings, client=StubApiClient(raw_sources))

    assert first["rows_fact_order_item"] == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item") == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.dim_customer") == EXPECTED_CUSTOMERS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.dim_product") == EXPECTED_PRODUCTS
    assert _scalar(engine, "SELECT COUNT(*) FROM staging.order_items") == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.dim_date") > 0

    second = pipeline_module.run_pipeline(test_settings, client=StubApiClient(raw_sources))

    assert second["rows_fact_order_item"] == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item") == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM staging.order_items") == EXPECTED_ORDER_ITEMS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.dim_customer") == EXPECTED_CUSTOMERS
    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.pipeline_runs WHERE status = 'SUCCESS'") == 2

    for view in (
        "analytics.vw_sales_by_category",
        "analytics.vw_customer_sales",
        "analytics.vw_daily_sales",
        "analytics.vw_product_performance",
    ):
        assert _scalar(engine, f"SELECT COUNT(*) FROM {view}") > 0, view


@pytest.mark.integration
def test_validation_failure_is_recorded_and_commits_nothing(
    test_settings, engine, pipeline_paths, raw_sources, tmp_path, monkeypatch
):
    incomplete = tmp_path / "incomplete_segments.csv"
    build_segments(int(user["id"]) for user in raw_sources["users"]).iloc[:-1].to_csv(
        incomplete, index=False
    )
    monkeypatch.setattr(pipeline_module, "CSV_PATH", incomplete)

    before = _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item")
    with pytest.raises(ValidationError, match="missing segmentation"):
        pipeline_module.run_pipeline(test_settings, client=StubApiClient(raw_sources))
    after = _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item")

    assert before == after
    assert _scalar(
        engine,
        "SELECT COUNT(*) FROM analytics.pipeline_runs "
        "WHERE status = 'FAILED' AND error_message LIKE '%missing segmentation%'",
    ) == 1


@pytest.mark.integration
def test_failed_load_rolls_back_without_partial_rows(
    test_settings, engine, pipeline_paths, raw_sources, monkeypatch
):
    pipeline_module.run_pipeline(test_settings, client=StubApiClient(raw_sources))
    before = _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item")

    extended = {**raw_sources, "carts": extend_carts(raw_sources["carts"])}

    def fail_inside_transaction(*args, **kwargs):
        raise RuntimeError("forced failure inside the load transaction")

    monkeypatch.setattr(pipeline_module, "fetch_loaded_counts", fail_inside_transaction)

    with pytest.raises(RuntimeError, match="forced failure inside the load transaction"):
        pipeline_module.run_pipeline(test_settings, client=StubApiClient(extended))

    assert _scalar(engine, "SELECT COUNT(*) FROM analytics.fact_order_item") == before
    assert _scalar(engine, "SELECT COUNT(*) FROM staging.order_items") == before
    assert _scalar(
        engine,
        "SELECT COUNT(*) FROM analytics.pipeline_runs "
        "WHERE status = 'FAILED' AND error_message LIKE '%forced failure%'",
    ) == 1
