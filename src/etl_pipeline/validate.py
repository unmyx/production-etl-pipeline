from __future__ import annotations

import logging
from typing import Iterable, Sequence

import pandas as pd

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    pass


def _columns(columns: str | Sequence[str]) -> list[str]:
    return [columns] if isinstance(columns, str) else list(columns)


def require_columns(df: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValidationError(f"{name}: missing required columns {missing}")


def require_rows(df: pd.DataFrame, name: str) -> None:
    if df.empty:
        raise ValidationError(f"{name}: no rows to load")


def require_min_rows(df: pd.DataFrame, name: str, minimum: int) -> None:
    if len(df) < minimum:
        raise ValidationError(
            f"{name}: expected at least {minimum} rows but found {len(df)}"
        )


def require_unique(df: pd.DataFrame, columns: str | Sequence[str], name: str) -> None:
    keys = _columns(columns)
    duplicated = int(df.duplicated(subset=keys).sum())
    if duplicated:
        raise ValidationError(
            f"{name}: {duplicated} duplicate values for key {keys}"
        )


def require_non_null(df: pd.DataFrame, columns: Sequence[str], name: str) -> None:
    nulls = df[list(columns)].isna().sum()
    failed = {column: int(count) for column, count in nulls.items() if count}
    if failed:
        raise ValidationError(f"{name}: required fields contain nulls {failed}")


def require_positive(df: pd.DataFrame, columns: Sequence[str], name: str) -> None:
    failed = {
        column: int((df[column] <= 0).sum())
        for column in columns
        if pd.api.types.is_numeric_dtype(df[column]) and (df[column] <= 0).any()
    }
    if failed:
        raise ValidationError(f"{name}: values must be positive {failed}")


def require_non_negative(df: pd.DataFrame, columns: Sequence[str], name: str) -> None:
    failed = {
        column: int((df[column] < 0).sum())
        for column in columns
        if (df[column] < 0).any()
    }
    if failed:
        raise ValidationError(f"{name}: monetary values must not be negative {failed}")


def require_within_range(
    df: pd.DataFrame,
    column: str,
    minimum: float,
    maximum: float,
    name: str,
) -> None:
    out_of_range = int(((df[column] < minimum) | (df[column] > maximum)).sum())
    if out_of_range:
        raise ValidationError(
            f"{name}: {out_of_range} values in {column} outside [{minimum}, {maximum}]"
        )


def require_not_greater(
    df: pd.DataFrame,
    left: str,
    right: str,
    name: str,
    tolerance: float = 0.01,
) -> None:
    violations = int((df[left] > df[right] + tolerance).sum())
    if violations:
        raise ValidationError(
            f"{name}: {violations} rows where {left} is greater than {right}"
        )


def require_references(
    child: pd.DataFrame,
    child_column: str,
    parent: pd.DataFrame,
    parent_column: str,
    name: str,
) -> None:
    unknown = sorted(set(child[child_column]) - set(parent[parent_column]))
    if unknown:
        preview = unknown[:10]
        raise ValidationError(
            f"{name}: {child_column} contains {len(unknown)} unknown references "
            f"to {parent_column} {preview}"
        )


def validate_sources(
    customers: pd.DataFrame,
    products: pd.DataFrame,
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    segments: pd.DataFrame,
) -> None:
    require_columns(
        customers,
        ["customer_id", "first_name", "last_name", "full_name", "email"],
        "customers",
    )
    require_columns(
        products,
        ["product_id", "product_name", "category", "unit_price"],
        "products",
    )
    require_columns(
        orders,
        [
            "order_id",
            "customer_id",
            "order_date",
            "gross_value",
            "net_value",
            "total_products",
            "total_quantity",
        ],
        "orders",
    )
    require_columns(
        order_items,
        [
            "order_id",
            "line_number",
            "customer_id",
            "product_id",
            "quantity",
            "unit_price",
            "line_total",
            "discounted_total",
        ],
        "order_items",
    )
    require_columns(
        segments,
        ["customer_id", "segment", "region", "acquisition_channel"],
        "customer_segments",
    )

    for frame, name in (
        (customers, "customers"),
        (products, "products"),
        (orders, "orders"),
        (order_items, "order_items"),
        (segments, "customer_segments"),
    ):
        require_rows(frame, name)

    require_unique(customers, "customer_id", "customers")
    require_unique(products, "product_id", "products")
    require_unique(segments, "customer_id", "customer_segments")
    require_unique(orders, "order_id", "orders")
    require_unique(order_items, ["order_id", "line_number"], "order_items")

    require_non_null(
        customers,
        ["customer_id", "first_name", "last_name", "full_name", "email"],
        "customers",
    )
    require_non_null(
        products,
        ["product_id", "product_name", "category", "unit_price"],
        "products",
    )
    require_non_null(
        orders,
        ["order_id", "customer_id", "order_date", "net_value"],
        "orders",
    )
    require_non_null(
        order_items,
        [
            "order_id",
            "line_number",
            "customer_id",
            "product_id",
            "quantity",
            "unit_price",
            "discounted_total",
        ],
        "order_items",
    )
    require_non_null(
        segments,
        ["customer_id", "segment", "region", "acquisition_channel"],
        "customer_segments",
    )

    require_positive(order_items, ["quantity"], "order_items")
    require_positive(orders, ["total_quantity"], "orders")
    require_min_rows(order_items, "order_items", len(orders))
    require_non_negative(
        order_items,
        ["unit_price", "line_total", "discounted_total", "discount_amount"],
        "order_items",
    )
    require_non_negative(
        orders,
        ["gross_value", "net_value"],
        "orders",
    )
    require_non_negative(products, ["unit_price"], "products")
    require_within_range(
        order_items, "discount_percentage", 0, 100, "order_items"
    )
    require_not_greater(
        order_items, "discounted_total", "line_total", "order_items"
    )

    require_references(
        order_items, "customer_id", customers, "customer_id", "order_items"
    )
    require_references(
        order_items, "product_id", products, "product_id", "order_items"
    )
    require_references(orders, "customer_id", customers, "customer_id", "orders")

    missing_segments = sorted(
        set(customers["customer_id"]) - set(segments["customer_id"])
    )
    if missing_segments:
        raise ValidationError(
            "customer_segments: missing segmentation for "
            f"{len(missing_segments)} customers {missing_segments[:10]}"
        )
    orphan_segments = sorted(
        set(segments["customer_id"]) - set(customers["customer_id"])
    )
    if orphan_segments:
        raise ValidationError(
            "customer_segments: contains "
            f"{len(orphan_segments)} unknown customers {orphan_segments[:10]}"
        )

    validate_row_counts(orders, order_items)
    logger.info(
        "Validation passed: %s customers, %s products, %s orders, %s order items, "
        "%s segment rows",
        len(customers),
        len(products),
        len(orders),
        len(order_items),
        len(segments),
    )


def validate_row_counts(orders: pd.DataFrame, order_items: pd.DataFrame) -> None:
    if set(orders["order_id"]) != set(order_items["order_id"]):
        raise ValidationError(
            "order_items: order ids do not reconcile with transformed orders"
        )
    declared_items = int(orders["total_products"].sum())
    if declared_items != len(order_items):
        raise ValidationError(
            "order_items: flattened row count "
            f"{len(order_items)} does not match API totalProducts {declared_items}"
        )
    per_order = order_items.groupby("order_id").size()
    mismatch = orders.set_index("order_id")["total_products"] != per_order
    if bool(mismatch.any()):
        raise ValidationError(
            f"order_items: {int(mismatch.sum())} orders have unexpected item counts"
        )


def validate_reconciliation(
    source_rows: int,
    loaded_rows: int,
    label: str,
) -> None:
    if source_rows != loaded_rows:
        raise ValidationError(
            f"{label}: source has {source_rows} rows but {loaded_rows} were loaded"
        )
    logger.info("Reconciliation passed for %s: %s rows", label, loaded_rows)


def validate_revenue_reconciliation(
    source_total: float,
    loaded_total: float,
    label: str,
    tolerance: float = 0.01,
) -> None:
    if abs(source_total - loaded_total) > tolerance:
        raise ValidationError(
            f"{label}: source total {source_total} does not match loaded total "
            f"{loaded_total}"
        )
    logger.info("Revenue reconciliation passed for %s: %s", label, round(loaded_total, 2))
