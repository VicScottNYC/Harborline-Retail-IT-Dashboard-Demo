import json
from collections import Counter

from fastapi.testclient import TestClient

from app import DEFAULT_PATH, create_app

STATUS_FIELDS = {"connection_status", "support_status", "releases_behind", "health_status",
                 "health_reasons", "evaluation_notes"}


def valid_client():
    return TestClient(create_app(DEFAULT_PATH))


def test_returns_all_168_devices_with_fixed_evaluation_time():
    r = valid_client().get("/devices")
    assert r.status_code == 200
    body = r.json()
    assert body["device_count"] == 168
    assert len(body["devices"]) == 168
    assert body["evaluation_time_utc"] == "2026-10-17T14:30:00Z"
    assert "not live telemetry" in body["demo_notice"]


def test_store_totals_match_approved_counts():
    devices = valid_client().get("/devices").json()["devices"]
    assert Counter(d["store_id"] for d in devices) == {
        "HO-014": 62, "HO-022": 38, "HO-031": 41, "HO-047": 27}


def test_every_device_has_calculated_statuses():
    devices = valid_client().get("/devices").json()["devices"]
    for d in devices:
        assert STATUS_FIELDS <= d.keys()
        assert d["connection_status"] in {"Online", "Stale", "Offline", "Unknown"}
        assert d["health_status"] in {"Healthy", "Warning", "Critical", "Unknown"}


def test_health_totals_match_regression_values():
    devices = valid_client().get("/devices").json()["devices"]
    assert Counter(d["health_status"] for d in devices) == {
        "Healthy": 69, "Warning": 77, "Critical": 12, "Unknown": 10}


def test_offline_devices_are_always_critical():
    devices = valid_client().get("/devices").json()["devices"]
    for d in devices:
        if d["connection_status"] == "Offline":
            assert d["health_status"] == "Critical"


def test_invalid_catalog_returns_503_and_no_devices(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["model_families"].append({
        "model_family_id": "unused-empty", "make": "Test", "model": "Empty", "platform": "Firmware",
        "releases": [], "current_version": "1.0", "min_supported_version": "1.0"})
    p = tmp_path / "bad_catalog.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "inventory_invalid"
    assert "devices" not in body
    assert any(e["code"] == "CATALOG_RELEASES_EMPTY" for e in body["errors"])


def test_invalid_device_returns_503_and_no_devices(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["devices"][5]["device_type"] = "Kiosk (unapproved)"
    p = tmp_path / "bad_device.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    body = r.json()
    assert "devices" not in body
    assert any(e["code"] == "DEVICE_TYPE_UNKNOWN" for e in body["errors"])


def test_one_bad_record_blocks_the_whole_import(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["devices"][0]["store_id"] = 123
    p = tmp_path / "one_bad.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    assert "devices" not in r.json()


def test_missing_file_fails_clearly(tmp_path):
    r = TestClient(create_app(tmp_path / "nope.json")).get("/devices")
    assert r.status_code == 503
    assert r.json()["errors"][0]["code"] == "FILE_NOT_FOUND"


def test_malformed_json_fails_clearly(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    assert r.json()["errors"][0]["code"] == "JSON_INVALID"


def test_missing_top_level_section_fails_clearly(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    del data["stores"]
    p = tmp_path / "no_stores.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    assert r.json()["errors"][0]["code"] == "SCHEMA_TOP_LEVEL"


def test_structurally_broken_config_fails_clearly(tmp_path):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["config"] = {}
    p = tmp_path / "bad_config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = TestClient(create_app(p)).get("/devices")
    assert r.status_code == 503
    assert "devices" not in r.json()
    codes = {e["code"] for e in r.json()["errors"]}
    assert {"CONFIG_EVALUATION_TIME_INVALID", "CONFIG_REFERENCE_DATE_INVALID",
            "CONFIG_NEARING_DAYS_INVALID"} <= codes
