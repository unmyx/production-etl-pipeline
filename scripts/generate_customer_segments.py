"""Generate the deterministic synthetic customer segmentation CSV source."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl_pipeline.config import Settings  # noqa: E402
from etl_pipeline.extract import ApiClient  # noqa: E402
from etl_pipeline.segments import build_segments  # noqa: E402

OUTPUT = ROOT / "data" / "source" / "customer_segments.csv"
RAW_USERS = ROOT / "data" / "raw" / "users.json"


def load_user_records() -> list[dict]:
    if RAW_USERS.exists():
        print(f"Using existing raw snapshot: {RAW_USERS}")
        return json.loads(RAW_USERS.read_text(encoding="utf-8"))

    settings = Settings.from_env()
    print("No raw snapshot found, extracting users from the API")
    client = ApiClient(
        settings.api_base_url, settings.request_timeout, settings.api_page_size
    )
    return client.get_all("users")


def main() -> None:
    users = load_user_records()
    if not users:
        raise SystemExit("No users available to derive customer segments from")

    segments = build_segments(int(user["id"]) for user in users)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    segments.to_csv(OUTPUT, index=False)
    print(
        f"Generated {len(segments)} customer segment rows for customer ids "
        f"{segments['customer_id'].min()}-{segments['customer_id'].max()}: {OUTPUT}"
    )


if __name__ == "__main__":
    main()
