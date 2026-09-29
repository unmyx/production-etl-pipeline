from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ORDER_DATE_START = date(2024, 1, 8)
ORDER_DATE_SPAN_DAYS = 364
ORDER_DATE_STEP = 37

CUSTOMER_COLUMNS = [
    "customer_id",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "age",
    "country",
    "company",
]

PRODUCT_COLUMNS = [
    "product_id",
    "product_name",
    "category",
    "brand",
    "unit_price",
    "rating",
    "stock",
]

ORDER_COLUMNS = [
    "order_id",
    "customer_id",
    "order_date",
    "gross_value",
    "net_value",
    "total_products",
    "total_quantity",
]

ORDER_ITEM_COLUMNS = [
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


def read_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def synthesize_order_date(order_id: int) -> date:
    offset = (order_id * ORDER_DATE_STEP) % ORDER_DATE_SPAN_DAYS
    return ORDER_DATE_START + timedelta(days=offset)


def transform_users(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "customer_id": int(record["id"]),
            "first_name": record.get("firstName"),
            "last_name": record.get("lastName"),
            "email": record.get("email"),
            "age": record.get("age"),
            "country": (record.get("address") or {}).get("country"),
            "company": (record.get("company") or {}).get("name"),
        }
        for record in records
    ]
    frame = pd.DataFrame(rows, columns=[c for c in CUSTOMER_COLUMNS if c != "full_name"])
    frame["full_name"] = (
        frame["first_name"].fillna("").str.strip()
        + " "
        + frame["last_name"].fillna("").str.strip()
    ).str.strip()
    return frame[CUSTOMER_COLUMNS]


def transform_products(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "product_id": int(record["id"]),
            "product_name": record.get("title"),
            "category": record.get("category"),
            "brand": record.get("brand"),
            "unit_price": record.get("price"),
            "rating": record.get("rating"),
            "stock": record.get("stock"),
        }
        for record in records
    ]
    return pd.DataFrame(rows, columns=PRODUCT_COLUMNS)


def transform_orders(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "order_id": int(cart["id"]),
            "customer_id": int(cart["userId"]),
            "order_date": synthesize_order_date(int(cart["id"])),
            "gross_value": float(cart["total"]),
            "net_value": float(cart["discountedTotal"]),
            "total_products": int(cart["totalProducts"]),
            "total_quantity": int(cart["totalQuantity"]),
        }
        for cart in records
    ]
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def transform_order_items(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for cart in records:
        order_id = int(cart["id"])
        customer_id = int(cart["userId"])
        for line_number, item in enumerate(cart.get("products", []), start=1):
            line_total = float(item["total"])
            discounted_total = float(item["discountedTotal"])
            rows.append(
                {
                    "order_id": order_id,
                    "line_number": line_number,
                    "customer_id": customer_id,
                    "product_id": int(item["id"]),
                    "quantity": int(item["quantity"]),
                    "unit_price": float(item["price"]),
                    "line_total": line_total,
                    "discount_percentage": float(item.get("discountPercentage") or 0),
                    "discounted_total": discounted_total,
                    "discount_amount": round(line_total - discounted_total, 2),
                }
            )
    return pd.DataFrame(rows, columns=ORDER_ITEM_COLUMNS)


def build_customer_dimension(users: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    merged = users.merge(
        segments,
        on="customer_id",
        how="inner",
        validate="one_to_one",
        suffixes=("", "_segment"),
    )
    return merged[
        [
            "customer_id",
            "full_name",
            "email",
            "age",
            "country",
            "company",
            "segment",
            "region",
            "acquisition_channel",
        ]
    ].rename(columns={"full_name": "customer_name"})


def build_product_dimension(products: pd.DataFrame) -> pd.DataFrame:
    return products[
        ["product_id", "product_name", "category", "brand", "unit_price", "rating"]
    ].copy()


def build_date_dimension(dates: Iterable[date]) -> pd.DataFrame:
    unique_dates = sorted({value for value in dates})
    rows = [
        {
            "date_key": int(value.strftime("%Y%m%d")),
            "full_date": value,
            "year": value.year,
            "quarter": (value.month - 1) // 3 + 1,
            "month": value.month,
            "month_name": calendar.month_name[value.month],
            "day_of_month": value.day,
            "day_name": calendar.day_name[value.weekday()],
            "is_weekend": value.weekday() >= 5,
        }
        for value in unique_dates
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "date_key",
            "full_date",
            "year",
            "quarter",
            "month",
            "month_name",
            "day_of_month",
            "day_name",
            "is_weekend",
        ],
    )


def attach_date_key(order_items: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    dates = orders.set_index("order_id")["order_date"]
    result = order_items.copy()
    result["date_key"] = (
        result["order_id"].map(dates).map(lambda value: int(value.strftime("%Y%m%d")))
    )
    return result
