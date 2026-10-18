"""Store filtering on GET /devices."""
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app import DEFAULT_PATH, create_app

APPROVED = {"HO-014": 62, "HO-022": 38, "HO-031": 41, "HO-047": 27}


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(DEFAULT_PATH))


def test_no_filter_returns_all_168_and_null_store_id(client):
    body = client.get("/devices").json()
    assert body["store_id"] is None
    assert body["device_count"] == 168
    assert len(body["devices"]) == 168


@pytest.mark.parametrize("store_id,expected", sorted(APPROVED.items()))
def test_each_store_returns_its_approved_count(client, store_id, expected):
    r = client.get("/devices", params={"store_id": store_id})
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == store_id
    assert body["device_count"] == expected
    assert len(body["devices"]) == expected
    assert all(d["store_id"] == store_id for d in body["devices"])


def test_filtered_devices_are_identical_to_unfiltered_views(client):
    everything = client.get("/devices").json()["devices"]
    for store_id in APPROVED:
        filtered = client.get("/devices", params={"store_id": store_id}).json()["devices"]
        expected = [d for d in everything if d["store_id"] == store_id]
        assert filtered == expected


def test_filter_preserves_evaluation_time_and_notice(client):
    body = client.get("/devices", params={"store_id": "HO-014"}).json()
    assert body["evaluation_time_utc"] == "2026-10-17T14:30:00Z"
    assert "not live telemetry" in body["demo_notice"]


def test_filter_does_not_change_the_underlying_inventory(client):
    before = client.get("/devices").json()
    client.get("/devices", params={"store_id": "HO-047"})
    after = client.get("/devices").json()
    assert before == after


def test_unknown_well_formed_store_returns_404(client):
    r = client.get("/devices", params={"store_id": "HO-999"})
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "store_not_found"
    assert "HO-999" in body["message"]
    assert "devices" not in body


@pytest.mark.parametrize("bad", ["HO-14", "ho-014", "HO-0140", "HO-14A", "XX-014", "HO-014 ", "", "014"])
def test_malformed_store_id_returns_422(client, bad):
    r = client.get("/devices", params={"store_id": bad})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error"
    assert "devices" not in body


def test_known_store_with_no_devices_returns_200_and_empty_list(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["stores"].append({"store_id": "HO-099", "name": "Empty test store",
                           "location": "Nowhere", "format": "Standard"})
    p = tmp_path / "with_empty_store.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices", params={"store_id": "HO-099"})
    assert r.status_code == 200
    body = r.json()
    assert body["device_count"] == 0
    assert body["devices"] == []
    assert body["store_id"] == "HO-099"


def test_failed_inventory_returns_503_before_store_lookup(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["model_families"].append({
        "model_family_id": "unused-empty", "make": "Test", "model": "Empty", "platform": "Firmware",
        "releases": [], "current_version": "1.0", "min_supported_version": "1.0"})
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    c = TestClient(create_app(p))
    # Valid store, unknown store, and malformed store all report the inventory failure first.
    for params in ({"store_id": "HO-014"}, {"store_id": "HO-999"}, {"store_id": "bad"}):
        r = c.get("/devices", params=params)
        assert r.status_code == 503, params
        assert r.json()["error"] == "inventory_invalid"
        assert "devices" not in r.json()
