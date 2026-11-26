#!/usr/bin/env python3
"""Sanitized SWEET.TV API spec validator, freshness checker, and opt-in live shape refresher.

Pure Core (no filesystem or network I/O):
  - extract_shape(value) -> redacted JSON shape (types only, never values)
  - diff_shapes(old, new, path="$") -> list of structural diff dicts
  - validate_spec_doc(doc, md_text, sweetapi_constants, today=None) -> validation report dict

CLI:
  python3 tools/sweettv-api-spec.py --check
  python3 tools/sweettv-api-spec.py --check-freshness [--max-age-days 30]
  python3 tools/sweettv-api-spec.py --refresh
"""
import sys

sys.dont_write_bytecode = True  # before any local import

import argparse  # noqa: E402
from datetime import date  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import mediastick_store as ms  # noqa: E402
import mediastick_sweetapi as sweetapi  # noqa: E402

DEFAULT_SHAPES_PATH = os.path.join(ROOT, "docs", "sweettv-api-shapes.json")
DEFAULT_MD_PATH = os.path.join(ROOT, "docs", "sweettv-api.md")
EXPECTED_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 30
EXPECTED_BASE_URL = sweetapi.API
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

SWEETAPI_ENDPOINTS = (
    sweetapi.CHANNELS,
    sweetapi.EPG_RECORDS,
    sweetapi.CONFIG,
    sweetapi.COLLECTIONS,
    sweetapi.COLLECTION_INFO,
    sweetapi.GENRE_MOVIES,
    sweetapi.MOVIE_INFO,
    sweetapi.MOVIE_LINK,
    sweetapi.SEARCH,
    sweetapi.TOP_SEARCH,
)


# ---- Pure Core --------------------------------------------------------------------------------

def _primitive_shape(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _merge_shapes(a, b):
    if a == b:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        merged = {}
        for k in dict.fromkeys(list(a.keys()) + list(b.keys())):
            if k in a and k in b:
                merged[k] = _merge_shapes(a[k], b[k])
            elif k in a:
                merged[k] = a[k]
            else:
                merged[k] = b[k]
        return merged
    if isinstance(a, list) and isinstance(b, list):
        if not a:
            return b
        if not b:
            return a
        return [_merge_shapes(a[0], b[0])]
    if isinstance(a, str) and isinstance(b, str):
        tokens = sorted(set(a.split("|") + b.split("|")))
        return "|".join(tokens)
    # Mixed container vs scalar (e.g. GetTop genres: str | list)
    types = []
    for item in (a, b):
        t = "list" if isinstance(item, list) else ("dict" if isinstance(item, dict) else str(item))
        types.extend(t.split("|"))
    return "|".join(sorted(set(types)))


def extract_shape(value):
    """Recursively convert any JSON payload into a redacted type-only shape structure."""
    if isinstance(value, dict):
        return {str(k): extract_shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if not value:
            return []
        elem_shapes = [extract_shape(item) for item in value]
        merged = elem_shapes[0]
        for s in elem_shapes[1:]:
            merged = _merge_shapes(merged, s)
        return [merged]
    return _primitive_shape(value)


def diff_shapes(old, new, path="$"):
    """Return a list of structural differences between two shape trees; empty list if identical."""
    diffs = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) - set(new)):
            diffs.append({"path": f"{path}.{k}", "change": "removed", "old": old[k]})
        for k in sorted(set(new) - set(old)):
            diffs.append({"path": f"{path}.{k}", "change": "added", "new": new[k]})
        for k in sorted(set(old) & set(new)):
            diffs.extend(diff_shapes(old[k], new[k], f"{path}.{k}"))
        return diffs
    if isinstance(old, list) and isinstance(new, list):
        if not old and not new:
            return diffs
        if not old or not new:
            diffs.append({"path": f"{path}[]", "change": "type_changed", "old": old, "new": new})
            return diffs
        diffs.extend(diff_shapes(old[0], new[0], f"{path}[]"))
        return diffs
    if old != new:
        diffs.append({"path": path, "change": "type_changed", "old": old, "new": new})
    return diffs


def _parse_iso_date(value):
    if not isinstance(value, str) or not ISO_DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_spec_doc(doc, md_text, sweetapi_constants, today=None):
    """Validate shapes JSON, markdown coverage, freshness, and absence of secrets."""
    errors = []
    cur_today = date.today() if today is None else today

    if not isinstance(doc, dict):
        return {"ok": False, "errors": ["shapes document must be a JSON object"], "stale": False, "age_days": None}

    if doc.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        errors.append(f"schema_version must be {EXPECTED_SCHEMA_VERSION}, got {doc.get('schema_version')!r}")

    if doc.get("base_url") != EXPECTED_BASE_URL:
        errors.append(f"base_url must be {EXPECTED_BASE_URL!r}, got {doc.get('base_url')!r}")

    max_age = doc.get("max_age_days")
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
        errors.append(f"max_age_days must be a non-negative integer, got {max_age!r}")
        max_age = DEFAULT_MAX_AGE_DAYS

    captured_raw = doc.get("captured_at")
    captured_date = _parse_iso_date(captured_raw)
    if captured_date is None:
        errors.append(f"captured_at must be a valid YYYY-MM-DD date, got {captured_raw!r}")
        age_days = None
        stale = False
    else:
        age_days = (cur_today - captured_date).days
        stale = age_days > max_age

    endpoints = doc.get("endpoints")
    if not isinstance(endpoints, dict):
        errors.append("endpoints must be a JSON object")
        endpoints = {}

    if not isinstance(md_text, str):
        errors.append("markdown documentation must be a string")
        md_text = ""

    for ep in sweetapi_constants:
        entry = endpoints.get(ep)
        if not isinstance(entry, dict):
            errors.append(f"missing or invalid endpoint {ep!r} in shapes JSON")
        else:
            if not isinstance(entry.get("request"), dict):
                errors.append(f"endpoint {ep!r} missing 'request' object in shapes JSON")
            if not isinstance(entry.get("response"), dict):
                errors.append(f"endpoint {ep!r} missing 'response' object in shapes JSON")
        if ep not in md_text:
            errors.append(f"missing endpoint {ep!r} in markdown doc")

    if ms.contains_secret(doc):
        errors.append("secret-like key or value detected in shapes JSON")
    if ms.contains_secret(md_text):
        errors.append("secret-like text detected in markdown doc")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "stale": stale,
        "age_days": age_days,
        "max_age_days": max_age,
        "captured_at": captured_raw,
    }


# ---- Thin I/O Shell ---------------------------------------------------------------------------

def _read_bearer_from_xml(xml_text):
    if not xml_text:
        return ""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for node in root.iter("setting"):
        if node.get("id") == "bearer":
            return (node.text or "").strip()
    return ""


def _load_bearer():
    """Read SWEET.TV bearer in RAM from local settings.xml or MEDIASTICK_HOST via SSH. Never logs it."""
    env_settings = os.environ.get("SWEETTV_SETTINGS")
    if env_settings and os.path.isfile(env_settings):
        try:
            with open(env_settings, encoding="utf-8") as f:
                tok = _read_bearer_from_xml(f.read())
            if tok:
                return tok
        except OSError:
            pass
    tok = sweetapi.bearer()
    if tok:
        return tok
    host = os.environ.get("MEDIASTICK_HOST", "mediastick.local")
    key = os.environ.get("MEDIASTICK_KEY", os.path.expanduser("~/.ssh/mediastick"))
    cmd = [
        "ssh",
        "-i", key,
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=8",
        "-o", "BatchMode=yes",
        f"media@{host}",
        "cat .kodi/userdata/addon_data/plugin.video.sweettv/settings.xml",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return _read_bearer_from_xml(proc.stdout)


def _probe_endpoint(token, method, body):
    headers = {
        **sweetapi.HEADERS,
        "accept-language": sweetapi.language(),
        "authorization": token,
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(sweetapi.API + method, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=sweetapi.TIMEOUT) as resp:
        raw = resp.read(16 * 1024 * 1024)
    return json.loads(raw.decode("utf-8"))


def _load_spec_files(shapes_path, md_path):
    with open(shapes_path, encoding="utf-8") as f:
        doc = json.load(f)
    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()
    return doc, md_text


def _atomic_write_json(path, doc):
    parent = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def refresh_spec(shapes_path, md_path, today=None):
    token = _load_bearer()
    if not token:
        print("ERROR: no SWEET.TV bearer available locally or via MEDIASTICK_HOST SSH", file=sys.stderr)
        return 1

    old_doc, md_text = _load_spec_files(shapes_path, md_path)
    new_doc = json.loads(json.dumps(old_doc))
    now_ts = int(time.time())

    # 1. Static-argument probes
    probes = {}
    probes[sweetapi.CONFIG] = _probe_endpoint(token, sweetapi.CONFIG, {})
    probes[sweetapi.TOP_SEARCH] = _probe_endpoint(token, sweetapi.TOP_SEARCH, {})
    probes[sweetapi.SEARCH] = _probe_endpoint(token, sweetapi.SEARCH, {"needle": "шоу"})
    probes[sweetapi.GENRE_MOVIES] = _probe_endpoint(token, sweetapi.GENRE_MOVIES, {"genre_id": 61})

    ch_list_probe = _probe_endpoint(
        token,
        sweetapi.CHANNELS,
        {
            "epg_current_time": now_ts,
            "epg_limit_prev": 1,
            "epg_limit_next": 1,
            "need_epg": True,
            "need_list": True,
            "need_categories": True,
            "need_offsets": False,
            "need_hash": False,
            "need_icons": False,
            "need_big_icons": False,
        },
    )
    probes[sweetapi.CHANNELS] = ch_list_probe

    # 2. Dependent probes using live IDs from the responses above
    cols_7 = _probe_endpoint(token, sweetapi.COLLECTIONS, {"type": 7})
    probes[sweetapi.COLLECTIONS] = cols_7

    epg_col_ids = [
        c["id"]
        for c in (cols_7.get("collection") or cols_7.get("collections") or [])
        if isinstance(c, dict) and c.get("type") == "Epg" and isinstance(c.get("id"), int)
    ]
    if epg_col_ids:
        col_info = _probe_endpoint(
            token,
            sweetapi.COLLECTION_INFO,
            {"id_list": epg_col_ids[:3], "need_translations": True},
        )
        probes[sweetapi.COLLECTION_INFO] = col_info
        sec_ids = []
        for col in col_info.get("collections") or col_info.get("collection") or []:
            if isinstance(col, dict):
                for sid in col.get("secondary_id_list") or []:
                    if isinstance(sid, int):
                        sec_ids.append(sid)
        if sec_ids:
            probes[sweetapi.EPG_RECORDS] = _probe_endpoint(
                token,
                sweetapi.EPG_RECORDS,
                {"id_list": sec_ids[:5], "image_type": 0, "need_extended_info": True},
            )

    movie_ids = [m for m in (probes[sweetapi.GENRE_MOVIES].get("movies") or []) if isinstance(m, int)]
    if movie_ids:
        movie_info = _probe_endpoint(
            token,
            sweetapi.MOVIE_INFO,
            {"movies": movie_ids[:5], "need_extended_info": True},
        )
        probes[sweetapi.MOVIE_INFO] = movie_info
        movies = [m for m in (movie_info.get("movies") or []) if isinstance(m, dict)]
        if movies:
            first_movie = movies[0]
            oid = sweetapi.owner_of(first_movie)
            link_body = {
                "movie_id": int(first_movie["id"]),
                "owner_id": int(oid),
                "video_quality_id": 2,
                "audio_track": -1,
                "preferred_link_type": 0,
                "subtitle": "all",
            }
            probes[sweetapi.MOVIE_LINK] = _probe_endpoint(token, sweetapi.MOVIE_LINK, link_body)

    any_diff = False
    for ep, raw_resp in probes.items():
        if ep not in new_doc["endpoints"]:
            continue
        new_shape = extract_shape(raw_resp)
        if ms.contains_secret(new_shape):
            print(f"REFUSED: secret-like key detected in shape for {ep}", file=sys.stderr)
            return 1
        old_shape = new_doc["endpoints"][ep].get("response", {})
        diffs = diff_shapes(old_shape, new_shape)
        if diffs:
            any_diff = True
            print(f"[diff] {ep}: {len(diffs)} change(s)")
            for d in diffs:
                print(f"  {d['change']} {d['path']}")
        new_doc["endpoints"][ep]["response"] = new_shape

    new_doc["captured_at"] = (date.today() if today is None else today).isoformat()
    report = validate_spec_doc(new_doc, md_text, SWEETAPI_ENDPOINTS, today=today)
    if not report["ok"]:
        for err in report["errors"]:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    _atomic_write_json(shapes_path, new_doc)
    print(f"Refreshed {len(probes)}/{len(SWEETAPI_ENDPOINTS)} endpoints; captured_at={new_doc['captured_at']}"
          + (" (shape changes recorded)" if any_diff else " (no shape changes)"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate or refresh the sanitized SWEET.TV API spec.")
    parser.add_argument("--check", action="store_true", help="Run offline structural, endpoint, and secret checks")
    parser.add_argument("--check-freshness", action="store_true", help="Exit 1 if captured_at exceeds --max-age-days")
    parser.add_argument("--max-age-days", type=int, default=None, help="Freshness threshold in days (default: doc max_age_days)")
    parser.add_argument("--refresh", action="store_true", help="Opt-in live probe to refresh docs/sweettv-api-shapes.json")
    parser.add_argument("--shapes", default=DEFAULT_SHAPES_PATH, help="Path to sweettv-api-shapes.json")
    parser.add_argument("--md", default=DEFAULT_MD_PATH, help="Path to sweettv-api.md")
    args = parser.parse_args(argv)

    if args.refresh:
        return refresh_spec(args.shapes, args.md)

    try:
        doc, md_text = _load_spec_files(args.shapes, args.md)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot load spec files: {exc}", file=sys.stderr)
        return 1

    report = validate_spec_doc(doc, md_text, SWEETAPI_ENDPOINTS)
    if not report["ok"]:
        for err in report["errors"]:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.check_freshness:
        limit = args.max_age_days if args.max_age_days is not None else report["max_age_days"]
        is_stale = report["age_days"] > limit
        status = "STALE" if is_stale else "FRESH"
        print(f"{status}: captured_at={report['captured_at']} (age {report['age_days']}d, max {limit}d)")
        return 1 if is_stale else 0

    print(f"OK: {len(SWEETAPI_ENDPOINTS)} endpoints valid, captured_at={report['captured_at']} (age {report['age_days']}d / max {report['max_age_days']}d)")
    if report["stale"]:
        print(
            f"NOTE: spec is stale (age {report['age_days']}d > {report['max_age_days']}d); "
            "run `python3 tools/sweettv-api-spec.py --refresh` if needed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
