from datetime import date

from etl_pipeline.transform import (
    attach_date_key,
    build_customer_dimension,
    build_date_dimension,
    build_product_dimension,
    synthesize_order_date,
    transform_order_items,
    transform_orders,
    transform_products,
    transform_users,
)


def test_transform_users_flattens_address_and_company(raw_sources):
    users = transform_users(raw_sources["users"])

    assert list(users["customer_id"]) == [1, 2, 3]
    assert users.loc[0, "full_name"] == "Emily Johnson"
    assert users.loc[0, "country"] == "United States"
    assert users.loc[1, "company"] == "Bogisich LLC"


def test_transform_products_maps_api_fields(raw_sources):
    products = transform_products(raw_sources["products"])

    assert list(products["product_id"]) == [10, 11, 12]
    assert products.loc[0, "product_name"] == "Essence Mascara Lash Princess"
    assert products.loc[0, "unit_price"] == 9.99


def test_transform_carts_flattens_nested_products(raw_sources):
    items = transform_order_items(raw_sources["carts"])

    assert len(items) == 5
    assert list(items.columns) == [
        "order_id",
        "line_number",
        "customer_id",
        "product_id",
        "quantity",
        "unit_price",
        "line_total",
        "discount_percentage",
        "discounted_total",
        "discount_amount",
    ]
    assert items.loc[0, "order_id"] == 1
    assert items.loc[0, "line_number"] == 1
    assert items.loc[0, "product_id"] == 10
    assert items.loc[0, "quantity"] == 3
    assert items.loc[0, "line_total"] == 29.97
    assert items.loc[0, "discounted_total"] == 26.97
    assert items.loc[0, "discount_amount"] == 3.0


def test_repeated_product_in_cart_keeps_separate_lines(raw_sources):
    items = transform_order_items(raw_sources["carts"])
    cart_three = items[items["order_id"] == 3]

    assert len(cart_three) == 2
    assert list(cart_three["product_id"]) == [10, 10]
    assert list(cart_three["line_number"]) == [1, 2]
    assert list(cart_three["quantity"]) == [2, 1]


def test_transform_orders_uses_cart_totals(raw_sources):
    orders = transform_orders(raw_sources["carts"])

    assert list(orders["order_id"]) == [1, 2, 3]
    first = orders.iloc[0]
    assert first["customer_id"] == 1
    assert first["gross_value"] == 89.95
    assert first["net_value"] == 80.95
    assert first["total_products"] == 2
    assert first["total_quantity"] == 5


def test_synthesized_order_date_is_deterministic_and_spread(raw_sources):
    orders = transform_orders(raw_sources["carts"])

    assert synthesize_order_date(1) == synthesize_order_date(1)
    assert isinstance(synthesize_order_date(1), date)
    assert synthesize_order_date(1) != synthesize_order_date(2)
    assert orders["order_date"].notna().all()


def test_build_customer_dimension_joins_segments(frames):
    dimension = build_customer_dimension(frames["customers"], frames["segments"])

    assert len(dimension) == 3
    assert list(dimension.columns) == [
        "customer_id",
        "customer_name",
        "email",
        "age",
        "country",
        "company",
        "segment",
        "region",
        "acquisition_channel",
    ]
    assert dimension["segment"].notna().all()


def test_build_product_dimension_drops_staging_only_columns(frames):
    dimension = build_product_dimension(frames["products"])

    assert "stock" not in dimension.columns
    assert len(dimension) == 3


def test_build_date_dimension_describes_calendar_dates():
    dimension = build_date_dimension([date(2024, 3, 4), date(2024, 3, 9), date(2024, 3, 4)])

    assert len(dimension) == 2
    monday = dimension[dimension["date_key"] == 20240304].iloc[0]
    saturday = dimension[dimension["date_key"] == 20240309].iloc[0]
    assert monday["day_name"] == "Monday"
    assert bool(monday["is_weekend"]) is False
    assert bool(saturday["is_weekend"]) is True
    assert monday["month_name"] == "March"


def test_attach_date_key_maps_order_dates(frames):
    fact = attach_date_key(frames["order_items"], frames["orders"])
    expected = {
        order_id: int(value.strftime("%Y%m%d"))
        for order_id, value in zip(frames["orders"]["order_id"], frames["orders"]["order_date"])
    }

    assert fact["date_key"].notna().all()
    for order_id, date_key in expected.items():
        assert set(fact.loc[fact["order_id"] == order_id, "date_key"]) == {date_key}
