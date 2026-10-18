"""Configuration and file-handling failures. Each must return 503 with no device data."""
import json

import pytest
from fastapi.testclient import TestClient

from app import DEFAULT_PATH, create_app


def client_for_config(tmp_path, **changes):
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["config"].update(changes)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return TestClient(create_app(p))


def assert_clear_503(r, code):
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "inventory_invalid"
    assert "devices" not in body
    assert any(e["code"] == code for e in body["errors"]), body["errors"]


def test_bad_support_reference_date_returns_503(tmp_path):
    r = client_for_config(tmp_path, support_reference_date="bad-date").get("/devices")
    assert_clear_503(r, "CONFIG_REFERENCE_DATE_INVALID")


def test_nearing_days_as_string_returns_503(tmp_path):
    r = client_for_config(tmp_path, nearing_support_days="180").get("/devices")
    assert_clear_503(r, "CONFIG_NEARING_DAYS_INVALID")


def test_negative_nearing_days_returns_503(tmp_path):
    r = client_for_config(tmp_path, nearing_support_days=-1).get("/devices")
    assert_clear_503(r, "CONFIG_NEARING_DAYS_INVALID")


def test_boolean_nearing_days_returns_503(tmp_path):
    r = client_for_config(tmp_path, nearing_support_days=True).get("/devices")
    assert_clear_503(r, "CONFIG_NEARING_DAYS_INVALID")


def test_bad_evaluation_time_returns_503(tmp_path):
    r = client_for_config(tmp_path, evaluation_time_utc="2026-10-17 14:30").get("/devices")
    assert_clear_503(r, "CONFIG_EVALUATION_TIME_INVALID")


def test_invalid_utf8_file_returns_503(tmp_path):
    p = tmp_path / "bad_encoding.json"
    p.write_bytes(b'{"config": "\xff\xfe"}')
    r = TestClient(create_app(p)).get("/devices")
    assert_clear_503(r, "FILE_ENCODING_INVALID")


def test_valid_config_still_returns_devices(tmp_path):
    r = client_for_config(tmp_path).get("/devices")  # unchanged values
    assert r.status_code == 200
    assert r.json()["device_count"] == 168
