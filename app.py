"""Harborline inventory API, milestone 1: read-only device list from inventory_v1.json.

The file is loaded and validated as a whole when the app is created. If anything
fails, /devices returns HTTP 503 with the errors and no device data.
"""
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import validate as V

DEFAULT_PATH = Path(__file__).parent / "inventory_v1.json"
MAX_ERRORS_SHOWN = 50
REQUIRED_TOP_LEVEL = ("config", "stores", "model_families", "devices")
STORE_ID_PATTERN = re.compile(r"HO-\d{3}")


def _file_error(code, message, path):
    return {"record": str(path), "field": "(file)", "code": code, "message": message}


def load_inventory(path):
    """Return (dataset, errors). The dataset is returned only when the whole import is valid."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, [_file_error("FILE_NOT_FOUND", "Inventory file not found.", path)]
    except UnicodeDecodeError:
        return None, [_file_error("FILE_ENCODING_INVALID",
                                  "Inventory file is not valid UTF-8 text.", path)]
    except OSError as e:
        return None, [_file_error("FILE_UNREADABLE", f"Inventory file could not be read: {e.strerror}.", path)]
    try:
        dataset = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [_file_error("JSON_INVALID", f"Invalid JSON at line {e.lineno}: {e.msg}.", path)]
    if not isinstance(dataset, dict) or any(k not in dataset for k in REQUIRED_TOP_LEVEL):
        return None, [_file_error("SCHEMA_TOP_LEVEL",
                                  "Inventory must contain config, stores, model_families and devices.", path)]
    try:
        errors = V.validate_import(dataset)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return None, [_file_error("IMPORT_UNREADABLE",
                                  f"Inventory structure could not be read: {type(e).__name__}.", path)]
    if errors:
        return None, errors
    return dataset, []


def device_view(device, ctx):
    """One device with its calculated statuses. Nothing is stored; everything is derived."""
    r = V.derive(device, ctx)
    return {
        "store_id": device["store_id"],
        "device_id": device["device_id"],
        "display_name": device["display_name"],
        "category": device["category"],
        "device_type": device["device_type"],
        "make": device["make"],
        "model": device["model"],
        "platform": device["platform"],
        "os_version": device["os_version"],
        "os_support_end_date": device["os_support_end_date"],
        "connection_method": device["connection_method"],
        "last_seen_at": device["last_seen_at"],
        "issues": device["issues"],
        "connection_status": r["connection"],
        "support_status": r["support"],
        "releases_behind": r["firmware_behind"],
        "health_status": r["health"],
        "health_reasons": [V.TEXT[code] for code in r["reasons"]],
        "evaluation_notes": [V.TEXT[code] for code in r["notes"]],
    }


def create_app(inventory_path=None):
    path = inventory_path or os.environ.get("INVENTORY_PATH") or DEFAULT_PATH
    dataset, errors = load_inventory(path)
    app = FastAPI(title="Harborline Retail IT Operations (demo)", version="0.1.0")

    views, eval_time, known_stores = [], None, set()
    if dataset is not None:
        ctx = V.build_ctx(dataset, dataset["devices"])
        views = [device_view(d, ctx) for d in dataset["devices"]]
        eval_time = dataset["config"]["evaluation_time_utc"]
        known_stores = {s["store_id"] for s in dataset["stores"]}

    @app.get("/devices")
    def list_devices(store_id: str | None = None):
        if dataset is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "inventory_invalid",
                    "message": "The inventory failed validation. No device data is returned.",
                    "error_count": len(errors),
                    "errors": errors[:MAX_ERRORS_SHOWN],
                },
            )
        if store_id is not None:
            if not STORE_ID_PATTERN.fullmatch(store_id):
                return JSONResponse(status_code=422, content={
                    "error": "validation_error",
                    "message": "store_id must look like HO-### (for example HO-014).",
                })
            if store_id not in known_stores:
                return JSONResponse(status_code=404, content={
                    "error": "store_not_found",
                    "message": f"Store {store_id} is not in the inventory.",
                })
            selected = [v for v in views if v["store_id"] == store_id]
        else:
            selected = views
        return {
            "store_id": store_id,
            "evaluation_time_utc": eval_time,
            "demo_notice": ("Demo statuses are calculated at the evaluation time above. "
                            "They are not live telemetry."),
            "device_count": len(selected),
            "devices": selected,
        }

    return app


app = create_app()