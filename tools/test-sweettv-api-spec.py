#!/usr/bin/env python3
"""Offline tests for the sanitized SWEET.TV API spec, freshness check, and shape tool:
python3 tools/test-sweettv-api-spec.py
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from datetime import date

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import mediastick_store as ms  # noqa: E402
import mediastick_sweetapi as sweetapi  # noqa: E402

SPEC_TOOL = os.path.join(ROOT, "tools", "sweettv-api-spec.py")
SHAPES_JSON = os.path.join(ROOT, "docs", "sweettv-api-shapes.json")
API_MD = os.path.join(ROOT, "docs", "sweettv-api.md")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")

EXPECTED_ENDPOINTS = (
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


def _load_spec_module(testcase):
    testcase.assertTrue(os.path.isfile(SPEC_TOOL), f"missing {SPEC_TOOL}")
    spec = importlib.util.spec_from_file_location("sweettv_api_spec", SPEC_TOOL)
    testcase.assertIsNotNone(spec)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _valid_doc(captured_at="2026-11-26", max_age_days=30):
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "max_age_days": max_age_days,
        "base_url": "https://api.sweet.tv/",
        "endpoints": {
            ep: {"request": {"id": "int"}, "response": {"status": "str"}}
            for ep in EXPECTED_ENDPOINTS
        },
    }


def _valid_md():
    return "\n".join(f"## {ep}\n" for ep in EXPECTED_ENDPOINTS)


class PureCoreShapeTests(unittest.TestCase):
    def test_extract_shape_redacts_values_and_preserves_structure(self):
        mod = _load_spec_module(self)
        payload = {
            "status": "OK",
            "count": 42,
            "rating": 8.5,
            "available": True,
            "deprecated": False,
            "extra": None,
            "empty_list": [],
            "items": [
                {
                    "id": 987654321,
                    "title": "Secret Title",
                    "stream": "https://cdn.example.com/stream.m3u8?token=sig123",
                }
            ],
        }
        shape = mod.extract_shape(payload)
        self.assertIsInstance(shape, dict)
        self.assertEqual(set(shape.keys()), set(payload.keys()))
        self.assertEqual(shape["empty_list"], [])
        self.assertIsInstance(shape["items"], list)
        self.assertEqual(len(shape["items"]), 1)

        # bool must be distinct from int
        self.assertNotEqual(mod.extract_shape(True), mod.extract_shape(1))

        # Concrete values and secret strings must be completely redacted
        dumped = json.dumps(shape)
        for leaked in ("Secret Title", "sig123", "987654321", "8.5", "cdn.example.com"):
            self.assertNotIn(leaked, dumped)
        self.assertFalse(ms.contains_secret(shape))

    def test_diff_shapes_detects_added_removed_and_type_changed_fields(self):
        mod = _load_spec_module(self)
        base = {
            "status": "str",
            "movies": [{"id": "int", "title": "str", "nested": {"year": "int"}}],
        }
        self.assertFalse(mod.diff_shapes(base, json.loads(json.dumps(base))))

        added = json.loads(json.dumps(base))
        added["movies"][0]["nested"]["banner_url"] = "str"
        diff_added = mod.diff_shapes(base, added)
        self.assertTrue(diff_added)
        self.assertIn("banner_url", json.dumps(diff_added))

        removed = json.loads(json.dumps(base))
        del removed["movies"][0]["title"]
        diff_removed = mod.diff_shapes(base, removed)
        self.assertTrue(diff_removed)
        self.assertIn("title", json.dumps(diff_removed))

        changed = json.loads(json.dumps(base))
        changed["movies"][0]["id"] = "str"
        diff_changed = mod.diff_shapes(base, changed)
        self.assertTrue(diff_changed)
        self.assertIn("id", json.dumps(diff_changed))


class PureCoreValidationTests(unittest.TestCase):
    def test_validate_spec_doc_accepts_valid_doc_and_checks_freshness_boundaries(self):
        mod = _load_spec_module(self)
        doc = _valid_doc(captured_at="2026-11-01", max_age_days=30)
        md = _valid_md()

        # 29 days: fresh
        r29 = mod.validate_spec_doc(doc, md, EXPECTED_ENDPOINTS, today=date(2026, 11, 30))
        self.assertTrue(r29["ok"], r29)
        self.assertFalse(r29["stale"])
        self.assertEqual(r29["age_days"], 29)

        # 30 days: boundary (age_days <= max_age_days is still fresh)
        r30 = mod.validate_spec_doc(doc, md, EXPECTED_ENDPOINTS, today=date(2026, 12, 1))
        self.assertTrue(r30["ok"], r30)
        self.assertFalse(r30["stale"])
        self.assertEqual(r30["age_days"], 30)

        # 31 days: stale (age_days > max_age_days), but structurally valid
        r31 = mod.validate_spec_doc(doc, md, EXPECTED_ENDPOINTS, today=date(2026, 12, 2))
        self.assertTrue(r31["ok"], r31)
        self.assertTrue(r31["stale"])
        self.assertEqual(r31["age_days"], 31)

    def test_validate_spec_doc_rejects_invalid_captured_at_and_metadata(self):
        mod = _load_spec_module(self)
        md = _valid_md()
        for bad_date in ("", "not-a-date", "2026-13-40", None, 20261126):
            doc = _valid_doc(captured_at=bad_date)
            res = mod.validate_spec_doc(doc, md, EXPECTED_ENDPOINTS, today=date(2026, 11, 26))
            self.assertFalse(res["ok"], repr(bad_date))
            self.assertTrue(res["errors"])

        bad_schema = _valid_doc()
        bad_schema["schema_version"] = 2
        self.assertFalse(mod.validate_spec_doc(bad_schema, md, EXPECTED_ENDPOINTS, today=date(2026, 11, 26))["ok"])

        bad_base = _valid_doc()
        bad_base["base_url"] = "https://example.com/"
        self.assertFalse(mod.validate_spec_doc(bad_base, md, EXPECTED_ENDPOINTS, today=date(2026, 11, 26))["ok"])

    def test_validate_spec_doc_rejects_missing_endpoint_in_json_or_markdown(self):
        mod = _load_spec_module(self)
        missing_ep = EXPECTED_ENDPOINTS[-1]

        doc_missing = _valid_doc()
        del doc_missing["endpoints"][missing_ep]
        res_json = mod.validate_spec_doc(doc_missing, _valid_md(), EXPECTED_ENDPOINTS, today=date(2026, 11, 26))
        self.assertFalse(res_json["ok"])
        self.assertIn(missing_ep, json.dumps(res_json["errors"]))

        md_missing = "\n".join(f"## {ep}\n" for ep in EXPECTED_ENDPOINTS[:-1])
        res_md = mod.validate_spec_doc(_valid_doc(), md_missing, EXPECTED_ENDPOINTS, today=date(2026, 11, 26))
        self.assertFalse(res_md["ok"])
        self.assertIn(missing_ep, json.dumps(res_md["errors"]))

    def test_validate_spec_doc_refuses_secrets_in_json_or_markdown(self):
        mod = _load_spec_module(self)
        doc_secret = _valid_doc()
        doc_secret["endpoints"][sweetapi.MOVIE_LINK]["response"] = {
            "url": "https://cdn.example.com/master.m3u8?token=secret123"
        }
        res_doc = mod.validate_spec_doc(doc_secret, _valid_md(), EXPECTED_ENDPOINTS, today=date(2026, 11, 26))
        self.assertFalse(res_doc["ok"])
        self.assertTrue(res_doc["errors"])

        md_secret = _valid_md() + "\nExample header: Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc\n"
        res_md = mod.validate_spec_doc(_valid_doc(), md_secret, EXPECTED_ENDPOINTS, today=date(2026, 11, 26))
        self.assertFalse(res_md["ok"])
        self.assertTrue(res_md["errors"])


class CommittedSpecDocsTests(unittest.TestCase):
    def test_shapes_json_exists_has_required_schema_and_all_sweetapi_endpoints(self):
        self.assertTrue(os.path.isfile(SHAPES_JSON), f"missing {SHAPES_JSON}")
        with open(SHAPES_JSON, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc.get("schema_version"), 1)
        self.assertEqual(doc.get("max_age_days"), 30)
        self.assertEqual(doc.get("base_url"), "https://api.sweet.tv/")
        date.fromisoformat(doc["captured_at"])
        self.assertIsInstance(doc.get("endpoints"), dict)
        for ep in EXPECTED_ENDPOINTS:
            self.assertIn(ep, doc["endpoints"], f"missing endpoint {ep} in shapes json")
        self.assertFalse(ms.contains_secret(doc))

    def test_markdown_doc_exists_covers_all_endpoints_pitfalls_and_has_no_secrets(self):
        self.assertTrue(os.path.isfile(API_MD), f"missing {API_MD}")
        with open(API_MD, encoding="utf-8") as f:
            md_text = f.read()
        for ep in EXPECTED_ENDPOINTS:
            self.assertIn(ep, md_text, f"missing endpoint {ep} in {API_MD}")
        for pitfall_marker in (
            "banner_url",
            "horizontal_poster_url",
            "GetEpgRecords",
            "preview_url_ext",
            "playable_episode_ids",
            "GetConfiguration",
            "sort_modes",
        ):
            self.assertIn(pitfall_marker, md_text, f"missing pitfall detail {pitfall_marker} in {API_MD}")
        self.assertFalse(ms.contains_secret(md_text))

    def test_agents_md_references_sweettv_api_spec_and_refresh(self):
        self.assertTrue(os.path.isfile(AGENTS_MD), f"missing {AGENTS_MD}")
        with open(AGENTS_MD, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("docs/sweettv-api.md", text)
        self.assertIn("captured_at", text)
        self.assertIn("sweettv-api-spec.py --refresh", text)


class CliTests(unittest.TestCase):
    def test_cli_check_passes_on_committed_docs(self):
        self.assertTrue(os.path.isfile(SPEC_TOOL), f"missing {SPEC_TOOL}")
        proc = subprocess.run(
            [sys.executable, "-B", SPEC_TOOL, "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_cli_check_freshness_respects_max_age_days(self):
        self.assertTrue(os.path.isfile(SPEC_TOOL), f"missing {SPEC_TOOL}")
        fresh = subprocess.run(
            [sys.executable, "-B", SPEC_TOOL, "--check-freshness", "--max-age-days", "36500"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)

        stale = subprocess.run(
            [sys.executable, "-B", SPEC_TOOL, "--check-freshness", "--max-age-days", "-1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)

    def test_spec_tool_is_stdlib_only(self):
        self.assertTrue(os.path.isfile(SPEC_TOOL), f"missing {SPEC_TOOL}")
        with open(SPEC_TOOL, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=SPEC_TOOL)
        stdlib = sys.stdlib_module_names
        allowed_local = {"mediastick_store", "mediastick_sweetapi"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        non_stdlib = imported - stdlib - allowed_local
        self.assertEqual(non_stdlib, set(), f"non-stdlib imports found: {non_stdlib}")


if __name__ == "__main__":
    unittest.main()
