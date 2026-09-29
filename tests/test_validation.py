import pandas as pd
import pytest

from etl_pipeline.validate import (
    ValidationError,
    validate_reconciliation,
    validate_revenue_reconciliation,
    validate_sources,
)


def test_valid_sources_pass(frames):
    validate_sources(**frames)


def test_missing_required_column_fails(frames):
    frames["orders"] = frames["orders"].drop(columns=["net_value"])
    with pytest.raises(ValidationError, match="missing required columns"):
        validate_sources(**frames)


def test_duplicate_primary_identifier_fails(frames):
    frames["customers"] = pd.concat(
        [frames["customers"], frames["customers"].iloc[[0]]], ignore_index=True
    )
    with pytest.raises(ValidationError, match="duplicate values for key"):
        validate_sources(**frames)


def test_duplicate_order_line_fails(frames):
    frames["order_items"] = pd.concat(
        [frames["order_items"], frames["order_items"].iloc[[0]]], ignore_index=True
    )
    with pytest.raises(ValidationError, match="duplicate values for key"):
        validate_sources(**frames)


def test_null_required_value_fails(frames):
    frames["customers"].loc[0, "email"] = None
    with pytest.raises(ValidationError, match="required fields contain nulls"):
        validate_sources(**frames)


def test_invalid_quantity_fails(frames):
    frames["order_items"].loc[0, "quantity"] = 0
    with pytest.raises(ValidationError, match="values must be positive"):
        validate_sources(**frames)


def test_negative_monetary_value_fails(frames):
    frames["order_items"].loc[0, "discounted_total"] = -1.0
    with pytest.raises(ValidationError, match="must not be negative"):
        validate_sources(**frames)


def test_discount_greater_than_line_total_fails(frames):
    frames["order_items"].loc[0, "discounted_total"] = 9999.0
    with pytest.raises(ValidationError, match="is greater than"):
        validate_sources(**frames)


def test_discount_percentage_out_of_range_fails(frames):
    frames["order_items"].loc[0, "discount_percentage"] = 150.0
    with pytest.raises(ValidationError, match="outside"):
        validate_sources(**frames)


def test_unknown_customer_reference_fails(frames):
    frames["order_items"].loc[0, "customer_id"] = 999
    with pytest.raises(ValidationError, match="unknown references"):
        validate_sources(**frames)


def test_unknown_product_reference_fails(frames):
    frames["order_items"].loc[0, "product_id"] = 999
    with pytest.raises(ValidationError, match="unknown references"):
        validate_sources(**frames)


def test_missing_segmentation_fails(frames):
    frames["segments"] = frames["segments"].iloc[:-1]
    with pytest.raises(ValidationError, match="missing segmentation"):
        validate_sources(**frames)


def test_segmentation_for_unknown_customer_fails(frames):
    extra = pd.DataFrame(
        [
            {
                "customer_id": 999,
                "segment": "SMB",
                "region": "North",
                "acquisition_channel": "Email",
            }
        ]
    )
    frames["segments"] = pd.concat([frames["segments"], extra], ignore_index=True)
    with pytest.raises(ValidationError, match="unknown customers"):
        validate_sources(**frames)


def test_empty_source_fails(frames):
    frames["products"] = frames["products"].iloc[0:0]
    with pytest.raises(ValidationError, match="no rows to load"):
        validate_sources(**frames)


def test_order_item_count_mismatch_fails(frames):
    frames["orders"].loc[0, "total_products"] = 5
    with pytest.raises(ValidationError, match="does not match API totalProducts"):
        validate_sources(**frames)


def test_order_with_no_items_fails(frames):
    frames["orders"] = pd.concat(
        [
            frames["orders"],
            pd.DataFrame(
                [
                    {
                        "order_id": 404,
                        "customer_id": 1,
                        "order_date": frames["orders"]["order_date"].iloc[0],
                        "gross_value": 0.0,
                        "net_value": 0.0,
                        "total_products": 0,
                        "total_quantity": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValidationError, match="do not reconcile"):
        validate_sources(**frames)


def test_reconciliation_passes_on_matching_counts():
    validate_reconciliation(800, 800, "fact")


def test_reconciliation_fails_on_row_drift():
    with pytest.raises(ValidationError, match="source has 800 rows but 799"):
        validate_reconciliation(800, 799, "fact")


def test_revenue_reconciliation_fails_on_value_drift():
    with pytest.raises(ValidationError, match="does not match loaded total"):
        validate_revenue_reconciliation(100.00, 99.50, "revenue")
