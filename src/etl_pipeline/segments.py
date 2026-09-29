from __future__ import annotations

import hashlib
from typing import Iterable

import pandas as pd

SEGMENTS = ("Consumer", "SMB", "Enterprise")
REGIONS = ("North", "Central", "South", "West")
CHANNELS = ("Organic", "Paid Search", "Referral", "Email")

SEGMENT_COLUMNS = ["customer_id", "segment", "region", "acquisition_channel"]


def stable_index(customer_id: int, salt: str, size: int) -> int:
    digest = hashlib.sha256(f"{salt}:{customer_id}".encode("utf-8")).hexdigest()
    return int(digest, 16) % size


def build_segments(customer_ids: Iterable[int]) -> pd.DataFrame:
    rows = [
        {
            "customer_id": int(customer_id),
            "segment": SEGMENTS[stable_index(customer_id, "segment", len(SEGMENTS))],
            "region": REGIONS[stable_index(customer_id, "region", len(REGIONS))],
            "acquisition_channel": CHANNELS[
                stable_index(customer_id, "channel", len(CHANNELS))
            ],
        }
        for customer_id in sorted({int(value) for value in customer_ids})
    ]
    return pd.DataFrame(rows, columns=SEGMENT_COLUMNS)
