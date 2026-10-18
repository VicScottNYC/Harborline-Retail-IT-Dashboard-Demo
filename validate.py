#!/usr/bin/env python3
"""Validate the Harborline v1 inventory sample and its catalog cases.

Usage: python3 validate.py
Exit code 0 when every check behaves as expected, 1 otherwise.

Import rule: the whole import is validated first. If any record or catalog
has an error, nothing is saved and every error is reported.

Type rule: each field's type is checked before the field is used. A field
with a type error is excluded from every check that depends on it.
"""
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
# Test fixtures (sample.json, catalog_cases.json) are read in main(), so importing
# this module for validation needs no fixture files.


def parse_ts(value):
    """UTC datetime for YYYY-MM-DDTHH:MM:SSZ, otherwise None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_date(value):
    """Date for YYYY-MM-DD, otherwise None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


REQUIRED = ["store_id", "device_id", "display_name", "category", "device_type", "make", "model",
            "model_family_id", "platform", "os_version", "os_support_end_date", "connection_method",
            "parent_device_id", "last_seen_at", "issues"]
TEXT_FIELDS = ["store_id", "device_id", "display_name", "category", "device_type", "make", "model",
               "connection_method", "platform"]
NONBLANK_FIELDS = ["store_id", "device_id", "display_name", "category", "device_type", "make", "model"]
NULLABLE_TEXT = ["os_version", "os_support_end_date", "last_seen_at", "parent_device_id", "model_family_id"]
ISSUE_FIELDS = ["issue_id", "issue_type", "severity", "description", "opened_at", "suggested_action"]
ISSUE_TYPES = {"connectivity", "firmware", "hardware", "content_playback", "lifecycle", "power", "configuration"}
SEVERITIES = {"critical", "warning", "info"}

# device_type: (category, allowed connection methods, allowed platforms,
#               stale minutes, offline minutes, allowed codes)
TYPES = {
    "Manager laptop": ("Endpoint", {"direct"}, {"Windows"}, 1440, 4320, {"WS"}),
    "Back-office desktop": ("Endpoint", {"direct"}, {"Windows"}, 1440, 4320, {"WS"}),
    "Tablet": ("Endpoint", {"direct"}, {"Android"}, 1440, 4320, {"WS"}),
    "Mobile computer": ("Endpoint", {"direct"}, {"Android"}, 360, 2880, {"MC"}),
    "Wearable": ("Endpoint", {"direct"}, {"Android"}, 360, 2880, {"WR"}),
    "Barcode scanner (cordless)": ("Endpoint", {"direct"}, {"Firmware"}, 360, 2880, {"SCN"}),
    "Barcode scanner (corded)": ("Endpoint", {"unmonitored"}, {"None"}, None, None, {"SCC"}),
    "Register": ("POS", {"direct"}, {"Android"}, 10, 1440, {"POS"}),
    "Self-checkout kiosk": ("POS", {"direct"}, {"Android"}, 10, 1440, {"POS"}),
    "Card reader": ("POS", {"direct"}, {"Firmware"}, 10, 1440, {"PAD"}),
    "Receipt printer": ("POS", {"direct"}, {"Firmware"}, 30, 1440, {"PRN"}),
    "Label printer": ("POS", {"direct"}, {"Firmware"}, 30, 1440, {"LBL"}),
    "Cash drawer": ("POS", {"via_parent", "unmonitored"}, {"None"}, 10, 1440, {"DRW"}),
    "Router": ("Network", {"direct"}, {"Firmware"}, 5, 1440, {"RTR"}),
    "Switch": ("Network", {"direct"}, {"Firmware"}, 5, 1440, {"SW"}),
    "Firewall": ("Network", {"direct"}, {"Firmware"}, 5, 1440, {"FW"}),
    "SD-WAN appliance": ("Network", {"direct"}, {"Firmware"}, 5, 1440, {"SDW"}),
    "Wireless access point": ("Network", {"direct"}, {"Firmware"}, 5, 1440, {"WAP"}),
    "UPS": ("Network", {"direct", "unmonitored"}, {"Firmware", "None"}, 5, 1440, {"UPS"}),
    "Environmental monitor": ("Network", {"direct"}, {"Firmware"}, 30, 1440, {"ENV"}),
    "Digital signage display": ("Media", {"direct"}, {"Firmware"}, 30, 1440, {"SGN"}),
    "Media player": ("Media", {"direct"}, {"Firmware"}, 30, 1440, {"MPL"}),
    "Display (TV)": ("Media", {"direct"}, {"Firmware"}, 30, 1440, {"TV"}),
    "Audio amplifier": ("Media", {"direct"}, {"Firmware"}, 60, 1440, {"AUD"}),
    "Audio zone controller": ("Media", {"direct"}, {"Firmware"}, 60, 1440, {"ZON"}),
    "Security camera": ("Media", {"direct"}, {"Firmware"}, 10, 1440, {"CAM"}),
}
ALL_CODES = set().union(*(t[5] for t in TYPES.values()))

TEXT = {
    "CONNECTION_UNMONITORED": "Device is unmonitored",
    "CONNECTION_NO_OBSERVATION": "No observation available",
    "CONNECTION_STALE": "Connection stale",
    "CONNECTION_OFFLINE": "Offline",
    "ISSUE_CRITICAL": "Critical issue",
    "ISSUE_WARNING": "Warning issue",
    "SUPPORT_NEARING": "Support ends within 180 days",
    "SUPPORT_UNSUPPORTED": "Unsupported (support ended)",
    "SUPPORT_UNKNOWN": "Support status unknown",
    "FIRMWARE_BEHIND_2PLUS": "Firmware two or more releases behind",
    "VERSION_NOT_RECOGNIZED": "Version not recognized: firmware lag not evaluated",
    "SUPPORT_DATE_MISSING": "Support end date not provided",
}


def check_catalog(fam):
    """Catalog-level checks. Returns (field, code, message) tuples."""
    rel = fam.get("releases")
    cur = fam.get("current_version")
    mn = fam.get("min_supported_version")
    if not isinstance(rel, list) or not rel:
        return [("releases", "CATALOG_RELEASES_EMPTY", "Release list is empty or missing.")]
    errs = []
    if len(set(rel)) != len(rel):
        errs.append(("releases", "CATALOG_DUPLICATE_RELEASE", "Release list contains a duplicate version."))
    if cur is None:
        errs.append(("current_version", "CATALOG_CURRENT_MISSING", "current_version is missing."))
    elif cur not in rel:
        errs.append(("current_version", "CATALOG_CURRENT_NOT_IN_RELEASES", f"'{cur}' is not in releases."))
    if mn is None:
        errs.append(("min_supported_version", "CATALOG_MIN_MISSING", "min_supported_version is missing."))
    elif mn not in rel:
        errs.append(("min_supported_version", "CATALOG_MIN_NOT_IN_RELEASES", f"'{mn}' is not in releases."))
    if cur in rel and mn in rel and rel.index(mn) > rel.index(cur):
        errs.append(("min_supported_version", "CATALOG_MIN_AFTER_CURRENT",
                     "min_supported_version comes after current_version in the release list."))
    return errs


def build_ctx(dataset, base):
    """Context for one dataset: its config, stores and catalog, plus base records for lookups."""
    cfg = dataset["config"]
    fam = {f["model_family_id"]: f for f in dataset["model_families"]}
    first, by_id = {}, {}
    for i, r in enumerate(base):
        first.setdefault(r.get("device_id"), i)
        by_id.setdefault(r.get("device_id"), r)
    return {
        "eval": parse_ts(cfg["evaluation_time_utc"]),
        "ref": parse_date(cfg["support_reference_date"]),
        "near": cfg["nearing_support_days"],
        "stores": {s["store_id"] for s in dataset["stores"]},
        "families": fam,
        "invalid_families": {fid for fid, f in fam.items() if check_catalog(f)},
        "first_index": first,
        "by_id": by_id,
    }


def validate_record(index, rec, ctx):
    """Return every independent error for one record. Checks that depend on a
    field with a type error are skipped; all other checks still run."""
    EVAL, STORES = ctx["eval"], ctx["stores"]
    errs = []
    if not isinstance(rec, dict):
        return [{"record": f"record[{index}]", "field": "(record)", "code": "RECORD_NOT_OBJECT",
                 "message": "Record must be an object."}]
    raw_id = rec.get("device_id")
    key = raw_id if isinstance(raw_id, str) and raw_id else f"record[{index}]"

    def E(field, code, msg):
        errs.append({"record": key, "field": field, "code": code, "message": msg})

    missing = [k for k in REQUIRED if k not in rec]
    if missing:
        E("(record)", "SCHEMA_MISSING_FIELD", "Missing fields: " + ", ".join(missing))
        return errs

    # Phase 1: types. Fields that fail are excluded from every later check.
    bad = set()
    for k in TEXT_FIELDS:
        if not isinstance(rec[k], str):
            bad.add(k)
            E(k, "FIELD_TYPE", f"{k} must be text.")
        elif k in NONBLANK_FIELDS and not rec[k].strip():
            bad.add(k)
            E(k, "TEXT_BLANK", f"{k} must be a nonblank string.")
    for k in NULLABLE_TEXT:
        if rec[k] is not None and not isinstance(rec[k], str):
            bad.add(k)
            E(k, "FIELD_TYPE", f"{k} must be text or null.")
    if not isinstance(rec["issues"], list):
        bad.add("issues")
        E("issues", "ISSUES_NOT_ARRAY", "issues must be an array of issue objects.")

    # Phase 2: values that depend only on the fields that passed.
    plat = rec["platform"] if "platform" not in bad else None
    method = rec["connection_method"] if "connection_method" not in bad else None
    dt = rec["device_type"] if "device_type" not in bad else None
    sid = rec["store_id"] if "store_id" not in bad else None
    did = rec["device_id"] if "device_id" not in bad else None
    fam_id = rec["model_family_id"] if "model_family_id" not in bad else None
    parent = rec["parent_device_id"] if "parent_device_id" not in bad else None

    # Required text and dates
    if plat is not None and plat != "None" and "os_version" not in bad:
        if rec["os_version"] is None or not rec["os_version"].strip():
            E("os_version", "OS_VERSION_REQUIRED", "os_version is required unless platform is None.")
    if "os_support_end_date" not in bad and rec["os_support_end_date"] is not None \
            and parse_date(rec["os_support_end_date"]) is None:
        E("os_support_end_date", "DATE_FORMAT", "Use the form YYYY-MM-DD.")

    # Identity
    m = None
    if did is not None:
        m = re.fullmatch(r"HO-(\d{3})-([A-Z]{2,3})-(\d{2})", did)
        if not m:
            E("device_id", "ID_PATTERN", f"'{did}' does not match HO-###-CODE-##.")
        else:
            if sid is not None and f"HO-{m.group(1)}" != sid:
                E("device_id", "ID_STORE_MISMATCH", f"Store prefix HO-{m.group(1)} does not match store_id {sid}.")
            if m.group(2) not in ALL_CODES:
                E("device_id", "ID_CODE_UNKNOWN", f"Code '{m.group(2)}' is not an approved device code.")
        if ctx["first_index"].get(did, index) != index:
            E("device_id", "ID_DUPLICATE", f"'{did}' already appears earlier in the import.")
    if sid is not None and sid not in STORES:
        E("store_id", "STORE_UNKNOWN", f"Store '{sid}' is not defined in stores.")

    # Device type, category, platform, connection method
    T = TYPES.get(dt) if dt is not None else None
    if dt is not None and T is None:
        E("device_type", "DEVICE_TYPE_UNKNOWN", f"'{dt}' is not an approved device type.")
    if T is not None:
        category, conns, plats, _, _, codes = T
        if m and m.group(2) in ALL_CODES and m.group(2) not in codes:
            E("device_id", "ID_CODE_TYPE_MISMATCH", f"Code {m.group(2)} does not belong to {dt}.")
        if "category" not in bad and rec["category"] != category:
            E("category", "CATEGORY_MISMATCH", f"{dt} belongs to {category}, not {rec['category']}.")
        if plat is not None and plat not in plats:
            E("platform", "PLATFORM_NOT_ALLOWED", f"{dt} cannot use platform {plat}.")
        if method is not None:
            if dt == "UPS" and plat is not None and (method == "direct") != (plat == "Firmware"):
                E("connection_method", "UPS_COMBINATION_INVALID",
                  "Managed UPS uses direct + Firmware; unmanaged UPS uses unmonitored + None.")
            if method not in conns:
                E("connection_method", "CONNECTION_NOT_ALLOWED", f"{dt} cannot use connection_method {method}.")

    # Catalog reference
    if plat is not None and fam_id is None and "model_family_id" not in bad and plat in ("Android", "Firmware"):
        E("model_family_id", "CATALOG_REQUIRED", f"{plat} devices need a model_family_id.")
    elif plat == "None" and rec["model_family_id"] is not None:
        E("model_family_id", "CATALOG_NOT_ALLOWED", "Platform None devices have no catalog reference.")
    elif fam_id is not None:
        if fam_id not in ctx["families"]:
            E("model_family_id", "CATALOG_NOT_FOUND", f"'{fam_id}' is not in model_families.")
        elif fam_id in ctx["invalid_families"]:
            E("model_family_id", "CATALOG_INVALID", f"'{fam_id}' fails catalog validation.")
        elif plat is not None and "make" not in bad and "model" not in bad:
            fam = ctx["families"][fam_id]
            if (rec["make"], rec["model"], plat) != (fam["make"], fam["model"], fam["platform"]):
                E("model_family_id", "CATALOG_MISMATCH",
                  f"make, model and platform must match catalog entry '{fam_id}'.")

    # Platform None
    if plat == "None":
        if "os_version" not in bad and rec["os_version"] is not None:
            E("os_version", "NONE_PLATFORM_HAS_VERSION", "Platform None requires os_version to be null.")
        if "os_support_end_date" not in bad and rec["os_support_end_date"] is not None:
            E("os_support_end_date", "NONE_PLATFORM_HAS_SUPPORT_DATE",
              "Platform None requires os_support_end_date to be null.")

    # Parent
    if method == "via_parent":
        if parent is None and "parent_device_id" not in bad:
            E("parent_device_id", "PARENT_REQUIRED", "via_parent devices need a parent_device_id.")
        elif parent is not None:
            pm = re.match(r"HO-(\d{3})-", parent)
            if pm and sid is not None and f"HO-{pm.group(1)}" != sid:
                E("parent_device_id", "PARENT_STORE_MISMATCH", f"Parent {parent} is in another store.")
            elif parent not in ctx["by_id"]:
                E("parent_device_id", "PARENT_NOT_FOUND", f"Parent {parent} is not in the import.")
            elif ctx["by_id"][parent].get("connection_method") != "direct":
                E("parent_device_id", "PARENT_NOT_DIRECT", f"Parent {parent} must be a direct device.")
    elif method in ("direct", "unmonitored") and parent is not None:
        E("parent_device_id", "PARENT_NOT_ALLOWED", f"{method} devices must have parent_device_id null.")

    # Timestamps
    ts = rec["last_seen_at"]
    if method == "unmonitored" and ts is not None and "last_seen_at" not in bad:
        E("last_seen_at", "UNMONITORED_HAS_TIMESTAMP", "Unmonitored devices must have last_seen_at null.")
    if ts is not None and "last_seen_at" not in bad:
        t = parse_ts(ts)
        if t is None:
            E("last_seen_at", "TIMESTAMP_FORMAT", "Use the form YYYY-MM-DDTHH:MM:SSZ.")
        elif t > EVAL:
            E("last_seen_at", "TIMESTAMP_FUTURE", "last_seen_at is later than the evaluation time.")

    # Issues
    if "issues" not in bad:
        ids = set()
        for n, iss in enumerate(rec["issues"]):
            f = f"issues[{n}]"
            if not isinstance(iss, dict):
                E(f, "ISSUE_NOT_OBJECT", "Each issue must be an object.")
                continue
            for k in ISSUE_FIELDS:
                if k not in iss:
                    E(f + "." + k, "ISSUE_FIELD_MISSING", f"Issue is missing {k}.")
            ibad = set()
            for k in ISSUE_FIELDS:
                if k in iss and k != "opened_at" and not isinstance(iss[k], str):
                    ibad.add(k)
                    E(f + "." + k, "FIELD_TYPE", f"{k} must be text.")
                elif k in iss and k in ("issue_id", "description", "suggested_action") \
                        and not iss[k].strip():
                    ibad.add(k)
                    E(f + "." + k, "TEXT_BLANK", f"{k} must be a nonblank string.")
            if isinstance(iss.get("issue_id"), str) and "issue_id" not in ibad:
                if iss["issue_id"] in ids:
                    E(f + ".issue_id", "ISSUE_ID_DUPLICATE", f"issue_id {iss['issue_id']} repeats on this device.")
                ids.add(iss["issue_id"])
            if "issue_type" in iss and "issue_type" not in ibad and iss["issue_type"] not in ISSUE_TYPES:
                E(f + ".issue_type", "ISSUE_TYPE_INVALID", f"'{iss['issue_type']}' is not an approved issue type.")
            if "severity" in iss and "severity" not in ibad and iss["severity"] not in SEVERITIES:
                E(f + ".severity", "ISSUE_SEVERITY_INVALID", f"'{iss['severity']}' is not an approved severity.")
            if "opened_at" in iss:
                if not isinstance(iss["opened_at"], str):
                    E(f + ".opened_at", "FIELD_TYPE", "opened_at must be text.")
                else:
                    t = parse_ts(iss["opened_at"])
                    if t is None:
                        E(f + ".opened_at", "TIMESTAMP_FORMAT", "Use the form YYYY-MM-DDTHH:MM:SSZ.")
                    elif t > EVAL:
                        E(f + ".opened_at", "ISSUE_OPENED_FUTURE", "opened_at is later than the evaluation time.")
    return errs


def derive(rec, ctx):
    """Derived outputs for a record that passed validation."""
    EVAL, REF, NEAR = ctx["eval"], ctx["ref"], ctx["near"]
    method = rec["connection_method"]
    _, _, _, stale, offline, _ = TYPES[rec["device_type"]]
    reasons, notes = [], []
    last = parse_ts(rec["last_seen_at"]) if rec["last_seen_at"] else None

    if method == "unmonitored":
        conn = "Unknown"
        reasons.append("CONNECTION_UNMONITORED")
    elif last is None:
        conn = "Unknown"
        reasons.append("CONNECTION_NO_OBSERVATION")
    else:
        age_min = (EVAL - last).total_seconds() / 60
        if age_min <= stale:
            conn = "Online"
        elif age_min <= offline:
            conn = "Stale"
            reasons.append("CONNECTION_STALE")
        else:
            conn = "Offline"
            reasons.append("CONNECTION_OFFLINE")

    if rec["platform"] == "None":
        support = "Not applicable"
    elif rec["os_support_end_date"] is None:
        support = "Unknown"
        reasons.append("SUPPORT_UNKNOWN")
        notes.append("SUPPORT_DATE_MISSING")
    else:
        days = (parse_date(rec["os_support_end_date"]) - REF).days
        if days < 0:
            support = "Unsupported"
            reasons.append("SUPPORT_UNSUPPORTED")
        elif days <= NEAR:
            support = "Nearing end of support"
            reasons.append("SUPPORT_NEARING")
        else:
            support = "Supported"

    behind = None
    fid = rec["model_family_id"]
    # Firmware lag applies only to Android and Firmware platforms, per the approved rules.
    if fid and rec["platform"] in ("Android", "Firmware") and fid not in ctx["invalid_families"]:
        fam = ctx["families"][fid]
        rel = fam["releases"]
        if rec["os_version"] in rel:
            behind = rel.index(fam["current_version"]) - rel.index(rec["os_version"])
            if behind >= 2:
                reasons.append("FIRMWARE_BEHIND_2PLUS")
        else:
            notes.append("VERSION_NOT_RECOGNIZED")

    for i in rec["issues"]:
        if i["severity"] == "critical":
            reasons.append("ISSUE_CRITICAL")
        elif i["severity"] == "warning":
            reasons.append("ISSUE_WARNING")
    crit = any(i["severity"] == "critical" for i in rec["issues"])
    warn = any(i["severity"] == "warning" for i in rec["issues"])

    if crit or conn == "Offline":
        health = "Critical"
    elif (warn or conn == "Stale" or support in ("Nearing end of support", "Unsupported")
          or (behind is not None and behind >= 2)):
        health = "Warning"
    elif conn == "Unknown" or support == "Unknown":
        health = "Unknown"
    else:
        health = "Healthy"

    return {"connection": conn, "support": support, "firmware_behind": behind, "health": health,
            "reasons": sorted(set(reasons)), "notes": sorted(set(notes))}


def check_config(config):
    """Configuration checks. Returns (field, code, message) tuples."""
    if not isinstance(config, dict):
        return [("config", "CONFIG_NOT_OBJECT", "config must be an object.")]
    errs = []
    if parse_ts(config.get("evaluation_time_utc")) is None:
        errs.append(("evaluation_time_utc", "CONFIG_EVALUATION_TIME_INVALID",
                     "Use the form YYYY-MM-DDTHH:MM:SSZ."))
    if parse_date(config.get("support_reference_date")) is None:
        errs.append(("support_reference_date", "CONFIG_REFERENCE_DATE_INVALID", "Use the form YYYY-MM-DD."))
    days = config.get("nearing_support_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        errs.append(("nearing_support_days", "CONFIG_NEARING_DAYS_INVALID",
                     "Must be a whole number of days, zero or more."))
    return errs


def validate_import(dataset):
    """Whole-import validation. Configuration and every catalog entry (used or not) are
    checked, then every device. Device checks are skipped if the configuration is invalid,
    because they depend on it. Empty result means the import may be saved."""
    config_errors = check_config(dataset.get("config"))
    errors = [{"record": "config", "field": f, "code": c, "message": m} for f, c, m in config_errors]
    seen = set()
    for fam in dataset["model_families"]:
        fid = fam.get("model_family_id")
        label = f"catalog:{fid}"
        if not isinstance(fid, str) or not fid.strip():
            errors.append({"record": label, "field": "model_family_id", "code": "CATALOG_ID_INVALID",
                           "message": "model_family_id must be a nonblank string."})
        elif fid in seen:
            errors.append({"record": label, "field": "model_family_id", "code": "CATALOG_ID_DUPLICATE",
                           "message": f"'{fid}' appears more than once in model_families."})
        seen.add(fid)
        for field, code, msg in check_catalog(fam):
            errors.append({"record": label, "field": field, "code": code, "message": msg})
    if config_errors:
        return errors
    ctx = build_ctx(dataset, dataset["devices"])
    for i, d in enumerate(dataset["devices"]):
        errors += validate_record(i, d, ctx)
    return errors


def main():
    DATA = json.loads((HERE / "sample.json").read_text(encoding="utf-8"))
    CATALOG_CASES = json.loads((HERE / "catalog_cases.json").read_text(encoding="utf-8"))
    failures = 0
    base_cases = [c for c in DATA["cases"] if c["group"] != "invalid"]
    base = [c["record"] for c in base_cases]
    ctx = build_ctx(DATA, base)

    print("== Catalog ==")
    for fam in DATA["model_families"]:
        if check_catalog(fam):
            failures += 1
            print(f"FAIL  {fam['model_family_id']}: {check_catalog(fam)}")
    print(f"Base catalog entries valid: {len(ctx['families']) - len(ctx['invalid_families'])} of {len(ctx['families'])}")

    print("\n== Catalog cases ==")
    print(f"{'ID':<6}{'Result':<8}Detail")
    for c in CATALOG_CASES:
        got = sorted({code for _, code, _ in check_catalog(c["family"])})
        want = sorted(set(c["expect"]))
        ok = got == want
        failures += not ok
        detail = ", ".join(got) if got else "valid"
        if not ok:
            detail += f"   (expected {', '.join(want) or 'valid'})"
        print(f"{c['id']:<6}{'PASS' if ok else 'FAIL':<8}{detail}")

    print("\n== Device records ==")
    base_errs = []
    for i, r in enumerate(base):
        base_errs += validate_record(i, r, ctx)
    if base_errs:
        failures += 1
        print("FAIL  base records rejected:")
        for e in base_errs:
            print(f"      {e['record']} | {e['field']} | {e['code']} | {e['message']}")
    else:
        print(f"Base import: {len(base)} records accepted.")

    print(f"{'ID':<6}{'Group':<22}{'Result':<8}Detail")
    for c in DATA["cases"]:
        cid, group, rec, exp = c["id"], c["group"], c["record"], c["expect"]
        if group == "invalid":
            errs = validate_record(len(base), rec, ctx)
            got = sorted({e["code"] for e in errs})
            want = sorted(set(exp["errors"] if "errors" in exp else [exp["error"]]))
            got_fields = sorted({e["field"] for e in errs})
            ok = got == want
            detail = ", ".join(got) if got else "accepted (no errors)"
            if not ok:
                detail += f"   (expected {', '.join(want)})"
            if "fields" in exp and got_fields != sorted(exp["fields"]):
                ok = False
                detail += f"   (fields {got_fields}, expected {sorted(exp['fields'])})"
            failures += not ok
            print(f"{cid:<6}{group:<22}{'PASS' if ok else 'FAIL':<8}{detail}")
            if cid == "X19":
                print("        Full error report for X19:")
                for e in errs:
                    print(f"          {e['record']} | {e['field']} | {e['code']} | {e['message']}")
            continue

        got = derive(rec, ctx)
        diffs = []
        for key in ("connection", "support", "firmware_behind", "health"):
            if got[key] != exp[key]:
                diffs.append(f"{key}: got {got[key]!r}, expected {exp[key]!r}")
        for key in ("reasons", "notes"):
            if got[key] != sorted(set(exp[key])):
                diffs.append(f"{key}: got {got[key]}, expected {sorted(set(exp[key]))}")
        if diffs:
            failures += 1
            print(f"{cid:<6}{group:<22}{'FAIL':<8}" + "; ".join(diffs))
        else:
            detail = f"{got['health']} | " + ("; ".join(TEXT[r] for r in got["reasons"]) or "no health reasons")
            if got["notes"]:
                detail += " | note: " + "; ".join(TEXT[n] for n in got["notes"])
            print(f"{cid:<6}{group:<22}{'PASS':<8}{detail}")

    print("\n== Import-level ==")
    clean = dict(DATA, devices=base)
    errs = validate_import(clean)
    ok = not errs
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL':<8}base import: {len(errs)} error(s)")
    unused = dict(clean, model_families=clean["model_families"] + [{
        "model_family_id": "unused-empty", "make": "Test", "model": "Empty", "platform": "Firmware",
        "releases": [], "current_version": "1.0", "min_supported_version": "1.0"}])
    codes = sorted({e["code"] for e in validate_import(unused)})
    ok = codes == ["CATALOG_RELEASES_EMPTY"]
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL':<8}unused invalid catalog entry rejected: {', '.join(codes)}")

    bad_cfg = dict(clean, config=dict(clean["config"], support_reference_date="bad-date"))
    codes = sorted({e["code"] for e in validate_import(bad_cfg)})
    ok = codes == ["CONFIG_REFERENCE_DATE_INVALID"]
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL':<8}invalid config rejected before device checks: {', '.join(codes)}")

    total = len(CATALOG_CASES) + len(DATA["cases"]) + 3
    print(f"\nSummary: {total - failures} of {total} checks behaved as expected; {failures} failure(s).")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()