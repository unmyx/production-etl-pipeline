import json

import pytest

from etl_pipeline.extract import ApiClient, ExtractionError, extract_api_data, new_run_label


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        return FakeResponse(self.pages.pop(0))


def test_pagination_collects_every_page():
    session = FakeSession(
        [
            {"users": [{"id": 1}, {"id": 2}], "total": 5, "skip": 0, "limit": 2},
            {"users": [{"id": 3}, {"id": 4}], "total": 5, "skip": 2, "limit": 2},
            {"users": [{"id": 5}], "total": 5, "skip": 4, "limit": 2},
        ]
    )
    client = ApiClient("https://example.test", page_size=2, session=session)

    records = client.get_all("users")

    assert [record["id"] for record in records] == [1, 2, 3, 4, 5]
    assert [call["params"]["skip"] for call in session.calls] == [0, 2, 4]
    assert {call["params"]["limit"] for call in session.calls} == {2}


def test_pagination_stops_when_total_is_reached_on_first_page():
    session = FakeSession([{"users": [{"id": 1}], "total": 1}])
    client = ApiClient("https://example.test", page_size=30, session=session)

    assert client.get_all("users") == [{"id": 1}]
    assert len(session.calls) == 1


def test_missing_resource_key_raises():
    session = FakeSession([{"message": "not found"}])
    client = ApiClient("https://example.test", page_size=30, session=session)

    with pytest.raises(ExtractionError, match="has no 'users' key"):
        client.get_all("users")


def test_extract_api_data_writes_latest_and_history_snapshots(tmp_path):
    session = FakeSession(
        [
            {"users": [{"id": 1}], "total": 1},
            {"products": [{"id": 10}], "total": 1},
            {"carts": [{"id": 100}], "total": 1},
        ]
    )
    client = ApiClient("https://example.test", page_size=30, session=session)

    history_dir = extract_api_data(client, tmp_path, run_label="20240101T000000Z")

    assert history_dir == tmp_path / "history" / "20240101T000000Z"
    for resource in ("users", "products", "carts"):
        latest = json.loads((tmp_path / f"{resource}.json").read_text())
        archived = json.loads((history_dir / f"{resource}.json").read_text())
        assert latest == archived


def test_empty_resource_response_fails_extraction(tmp_path):
    session = FakeSession(
        [
            {"users": [], "total": 0},
            {"products": [{"id": 10}], "total": 1},
            {"carts": [{"id": 100}], "total": 1},
        ]
    )
    client = ApiClient("https://example.test", page_size=30, session=session)

    with pytest.raises(ExtractionError, match="no records"):
        extract_api_data(client, tmp_path)


def test_run_label_is_a_sortable_utc_timestamp():
    label = new_run_label()

    assert len(label) == 16
    assert label.endswith("Z")
    assert label[8] == "T"
