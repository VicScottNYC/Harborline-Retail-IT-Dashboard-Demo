# Harborline Retail IT Operations API (demo)

A FastAPI backend for a fictional retail IT operations dashboard. It loads a device inventory file, validates the whole import before using it, derives connection, support, and health status for each device, and serves device lists with optional store filtering.

> **Demo data only.** The inventory is fictional, and statuses are calculated at a fixed evaluation time. They are not live telemetry.

## Features

- **Whole-file validation.** If any record or catalog entry is invalid, nothing is served. `/devices` returns HTTP 503 with a clear list of errors.
- **Derived status.** Connection (Online, Stale, Offline, Unknown), support (Supported, Nearing end of support, Unsupported), firmware lag, and overall health (Healthy, Warning, Critical, Unknown) are calculated, not stored.
- **Store filtering.** `GET /devices?store_id=HO-014` returns one store's devices, with 404 for unknown stores and 422 for malformed IDs.
- **Interactive docs.** Swagger UI is available at `/docs`.

## Tech stack

- Python 3.10+
- FastAPI, Uvicorn
- pytest, with FastAPI's `TestClient`

## Project structure

```
app.py                    FastAPI app, routes, and loading
validate.py               Validation rules and status calculation
inventory_v1.json         Fictional inventory (4 stores, 168 devices)
test_devices.py           Inventory loading, validation, and status tests
test_store_filter.py      Store filter and error response tests
test_config_and_io.py     Configuration and file-handling failure tests
```

## Setup (macOS / Linux)

```bash
cd Harborline-Retail-IT-Dashboard-Demo
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn httpx pytest
```

## Run the tests

```bash
python -m pytest -v
```

Expected result: **38 passed**.

## Run the server

```bash
uvicorn app:app --reload
```

Then open:

- http://127.0.0.1:8000/devices for the full device list
- http://127.0.0.1:8000/docs for the interactive API docs

## Example requests

```bash
# All devices (168)
curl http://127.0.0.1:8000/devices

# One store
curl "http://127.0.0.1:8000/devices?store_id=HO-014"   # 62 devices
curl "http://127.0.0.1:8000/devices?store_id=HO-022"   # 38 devices
curl "http://127.0.0.1:8000/devices?store_id=HO-031"   # 41 devices
curl "http://127.0.0.1:8000/devices?store_id=HO-047"   # 27 devices

# Error cases
curl -i "http://127.0.0.1:8000/devices?store_id=HO-999"  # 404 Not Found
curl -i "http://127.0.0.1:8000/devices?store_id=HO-14"   # 422 Unprocessable Content
```

## Configuration

The inventory path can be overridden with an environment variable:

```bash
INVENTORY_PATH=/path/to/other_inventory.json uvicorn app:app --reload
```

## Notes

- `validate.py` can also be run directly as a standalone check against its sample cases, with `python validate.py`.
- The app loads and validates the inventory once, when it starts. Restart the server after changing the file.

## License

Add a license of your choice, or remove this section.
