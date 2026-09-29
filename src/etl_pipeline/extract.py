from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

RESOURCES = ("users", "products", "carts")
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class ExtractionError(RuntimeError):
    pass


def new_run_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        page_size: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.page_size = page_size
        self.session = session or requests.Session()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "Request failed for %s (attempt %s/%s): %s. Retrying in %ss",
                    url,
                    attempt,
                    MAX_RETRIES,
                    last_error,
                    delay,
                )
                time.sleep(delay)
        raise ExtractionError(f"Could not fetch {url}: {last_error}")

    def get_all(self, resource: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        skip = 0
        total: int | None = None

        while True:
            payload = self._get(
                f"{self.base_url}/{resource}",
                {"limit": self.page_size, "skip": skip},
            )
            page = payload.get(resource)
            if page is None:
                raise ExtractionError(f"Response for '{resource}' has no '{resource}' key")
            if total is None:
                total = int(payload.get("total", len(page)))

            records.extend(page)
            logger.info("Extracted %s: %s/%s records", resource, len(records), total)

            if not page or len(records) >= total:
                break
            skip += self.page_size

        if len(records) > total:
            logger.warning(
                "Received %s %s records but the API reported a total of %s",
                len(records),
                resource,
                total,
            )
        return records


def extract_api_data(
    client: ApiClient,
    snapshot_dir: Path,
    run_label: str | None = None,
) -> Path:
    run_label = run_label or new_run_label()
    history_dir = snapshot_dir / "history" / run_label
    history_dir.mkdir(parents=True, exist_ok=True)

    for resource in RESOURCES:
        records = client.get_all(resource)
        if not records:
            raise ExtractionError(f"API returned no records for '{resource}'")
        payload = json.dumps(records, indent=2)
        (snapshot_dir / f"{resource}.json").write_text(payload, encoding="utf-8")
        (history_dir / f"{resource}.json").write_text(payload, encoding="utf-8")
        logger.info("Saved raw snapshot for %s (%s records)", resource, len(records))

    return history_dir


def load_customer_segments(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Customer segment source not found: {path}. "
            "Run 'python scripts/generate_customer_segments.py' first."
        )
    frame = pd.read_csv(path)
    logger.info("Loaded customer segment CSV source: %s rows", len(frame))
    return frame
