from __future__ import annotations

import pytest

from etl_pipeline.segments import build_segments
from etl_pipeline.transform import (
    transform_order_items,
    transform_orders,
    transform_products,
    transform_users,
)

RAW_USERS = [
    {
        "id": 1,
        "firstName": "Emily",
        "lastName": "Johnson",
        "email": "emily.johnson@x.dummyjson.com",
        "age": 29,
        "address": {"country": "United States"},
        "company": {"name": "Dooley, Kozey and Cronin"},
    },
    {
        "id": 2,
        "firstName": "Michael",
        "lastName": "Smith",
        "email": "michael.smith@x.dummyjson.com",
        "age": 41,
        "address": {"country": "Canada"},
        "company": {"name": "Bogisich LLC"},
    },
    {
        "id": 3,
        "firstName": "Sophia",
        "lastName": "Brown",
        "email": "sophia.brown@x.dummyjson.com",
        "age": 35,
        "address": {"country": "Germany"},
        "company": {"name": "Kuhlman Group"},
    },
]

RAW_PRODUCTS = [
    {
        "id": 10,
        "title": "Essence Mascara Lash Princess",
        "category": "beauty",
        "brand": "Essence",
        "price": 9.99,
        "rating": 4.2,
        "stock": 50,
    },
    {
        "id": 11,
        "title": "Blue Frock",
        "category": "tops",
        "brand": "Fashion Studio",
        "price": 29.99,
        "rating": 4.5,
        "stock": 20,
    },
    {
        "id": 12,
        "title": "iPhone 6",
        "category": "smartphones",
        "brand": "Apple",
        "price": 299.99,
        "rating": 4.8,
        "stock": 5,
    },
]

RAW_CARTS = [
    {
        "id": 1,
        "userId": 1,
        "total": 89.95,
        "discountedTotal": 80.95,
        "totalProducts": 2,
        "totalQuantity": 5,
        "products": [
            {
                "id": 10,
                "price": 9.99,
                "quantity": 3,
                "total": 29.97,
                "discountPercentage": 10.0,
                "discountedTotal": 26.97,
            },
            {
                "id": 11,
                "price": 29.99,
                "quantity": 2,
                "total": 59.98,
                "discountPercentage": 10.0,
                "discountedTotal": 53.98,
            },
        ],
    },
    {
        "id": 2,
        "userId": 2,
        "total": 299.99,
        "discountedTotal": 299.99,
        "totalProducts": 1,
        "totalQuantity": 1,
        "products": [
            {
                "id": 12,
                "price": 299.99,
                "quantity": 1,
                "total": 299.99,
                "discountPercentage": 0.0,
                "discountedTotal": 299.99,
            }
        ],
    },
    {
        "id": 3,
        "userId": 3,
        "total": 29.97,
        "discountedTotal": 28.47,
        "totalProducts": 2,
        "totalQuantity": 3,
        "products": [
            {
                "id": 10,
                "price": 9.99,
                "quantity": 2,
                "total": 19.98,
                "discountPercentage": 5.0,
                "discountedTotal": 18.98,
            },
            {
                "id": 10,
                "price": 9.99,
                "quantity": 1,
                "total": 9.99,
                "discountPercentage": 5.0,
                "discountedTotal": 9.49,
            },
        ],
    },
]


@pytest.fixture
def raw_sources() -> dict[str, list[dict]]:
    return {
        "users": RAW_USERS,
        "products": RAW_PRODUCTS,
        "carts": RAW_CARTS,
    }


@pytest.fixture
def frames(raw_sources: dict[str, list[dict]]) -> dict:
    return {
        "customers": transform_users(raw_sources["users"]),
        "products": transform_products(raw_sources["products"]),
        "orders": transform_orders(raw_sources["carts"]),
        "order_items": transform_order_items(raw_sources["carts"]),
        "segments": build_segments(int(user["id"]) for user in raw_sources["users"]),
    }
