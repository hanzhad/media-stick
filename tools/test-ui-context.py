#!/usr/bin/env python3
"""Offline tests for the Pure Core UI context schema, tmpfs watcher & command dispatcher (Issue #95):
python3 tools/test-ui-context.py
"""
import sys

sys.dont_write_bytecode = True

import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
sys.path.insert(0, LIB)

AIZA = "AIza" + "Sy" + "A" * 33
SECRET = "GOCSPX-" + "a1B2c3D4e5F6"
OAUTH = "ya29." + "a" * 24
CLIENT = "1234567890-abcdefghij.apps.googleusercontent.com"


def _require_module(testcase, dotted_name):
    """Import a module under test; fail with AssertionError if not yet implemented."""
    try:
        return importlib.import_module(dotted_name)
    except ImportError as exc:
        testcase.fail(f"{dotted_name} is not implemented: {exc}")


def _compact_json_bytes(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class TestUiContextSchema(unittest.TestCase):
    def test_constants_and_empty_context(self):
        uc = _require_module(self, "mediastick_ui_context")
        self.assertEqual(uc.CONTEXT_VERSION, 1)
        self.assertEqual(uc.MAX_CONTEXT_BYTES, 8192)
        self.assertEqual(uc.VALID_APPS, ("", "sweettv", "youtube"))
        self.assertEqual(uc.VALID_VIEWS, ("none", "section", "show", "guide", "detail"))

        empty = uc.empty_context()
        self.assertEqual(empty, {
            "v": 1,
            "app": "",
            "view": "none",
            "section": "",
            "sections": [],
            "chips": [],
            "sort": None,
            "can_search": False,
            "search_query": "",
            "search_hint": "",
            "modal": None,
        })
        # Mutating returned dict must not affect subsequent calls
        empty["sections"].append("x")
        self.assertEqual(uc.empty_context()["sections"], [])

    def test_normalize_context_defaults_and_invalid_inputs(self):
        uc = _require_module(self, "mediastick_ui_context")
        for bad in (None, [], "sweettv", 42):
            ctx = uc.normalize_context(bad)
            self.assertEqual(ctx["v"], 1)
            self.assertEqual(ctx["app"], "")
            self.assertEqual(ctx["view"], "none")

        ctx = uc.normalize_context({
            "v": 99,
            "app": "netflix",
            "view": "unknown",
            "can_search": 1,
            "sections": [{"id": "live", "label": "TV"}],
            "chips": [{"id": "all", "label": "All", "active": True}],
        })
        self.assertEqual(ctx["v"], 1)
        self.assertEqual(ctx["app"], "")
        self.assertEqual(ctx["view"], "none")
        self.assertIs(ctx["can_search"], True)

    def test_modal_normalization_and_demo_only_episodes_programs(self):
        uc = _require_module(self, "mediastick_ui_context")
        episodes = [{"id": f"ep{i}", "title": f"Episode {i}"} for i in range(40)]
        programs = [{"id": f"pr{i}", "title": f"Program {i}"} for i in range(40)]

        # When demo is False/omitted, episodes/programs must NOT be included
        non_demo = uc.normalize_context({
            "app": "sweettv",
            "view": "show",
            "modal": {
                "kind": "show",
                "show_id": "sh-1",
                "title": "My Show",
                "fav_key": "show:1",
                "fav": True,
                "can_play": True,
                "play_label": "Watch",
                "alt_label": "From start",
                "can_archive": True,
                "seasons": [1, 2],
                "selected_season": 1,
                "demo": False,
                "episodes": episodes,
                "programs": programs,
            },
        })
        self.assertIsNotNone(non_demo["modal"])
        self.assertEqual(non_demo["modal"]["title"], "My Show")
        self.assertFalse(non_demo["modal"].get("episodes"))
        self.assertFalse(non_demo["modal"].get("programs"))

        # When demo=True, episodes/programs are allowed but bounded <= 25
        demo_ctx = uc.normalize_context({
            "app": "sweettv",
            "view": "show",
            "modal": {
                "kind": "show",
                "cid": "ch-5",
                "title": "Demo Show",
                "demo": True,
                "days": ["Mon", "Tue"],
                "selected_day": 0,
                "episodes": episodes,
                "programs": programs,
            },
        })
        self.assertTrue(demo_ctx["modal"]["demo"])
        self.assertLessEqual(len(demo_ctx["modal"].get("episodes", [])), 25)
        self.assertLessEqual(len(demo_ctx["modal"].get("programs", [])), 25)


class TestUiContextSecretGuard(unittest.TestCase):
    def test_refused_is_value_error(self):
        uc = _require_module(self, "mediastick_ui_context")
        self.assertTrue(issubclass(uc.Refused, ValueError))

    def test_rejects_secret_keys_and_values_before_truncation(self):
        uc = _require_module(self, "mediastick_ui_context")

        # Secret keys anywhere in nested structure
        for key in ("token", "access_token", "refresh_token", "password", "cookie", "secret"):
            with self.assertRaises(uc.Refused, msg=f"key={key} must raise Refused"):
                uc.normalize_context({"app": "sweettv", "view": "section", key: "harmless"})
            with self.assertRaises(uc.Refused, msg=f"nested key={key} must raise Refused"):
                uc.normalize_context({
                    "app": "sweettv",
                    "view": "show",
                    "modal": {"kind": "show", "title": "Ok", key: "harmless"},
                })

        # Secret values checked BEFORE truncation (beyond chip cap of 16 and beyond label cut)
        for secret in (AIZA, SECRET, OAUTH, CLIENT):
            # Secret at chip index 25 (past the 16-chip cap)
            chips = [{"id": f"c{i}", "label": f"Chip {i}"} for i in range(30)]
            chips[25]["label"] = f"prefix {secret} suffix"
            with self.assertRaises(uc.Refused, msg="secret past chip cap must still raise"):
                uc.normalize_context({"app": "youtube", "view": "section", "chips": chips})

            # Secret at the tail of a 600-char label (past any label truncation)
            long_label = ("A" * 500) + " " + secret
            with self.assertRaises(uc.Refused, msg="secret past label truncation must still raise"):
                uc.normalize_context({"app": "youtube", "view": "section", "search_hint": long_label})

    def test_allows_ordinary_non_secret_text(self):
        uc = _require_module(self, "mediastick_ui_context")
        ctx = uc.normalize_context({
            "app": "sweettv",
            "view": "section",
            "section": "movies",
            "search_hint": "Search movies, series, and channels",
            "chips": [{"id": "hd", "label": "HD channels", "active": False}],
        })
        self.assertEqual(ctx["app"], "sweettv")
        self.assertEqual(ctx["section"], "movies")


class TestUiContextTrimming(unittest.TestCase):
    def test_oversized_context_with_50_long_chips_trims_deterministically_under_8192_bytes(self):
        uc = _require_module(self, "mediastick_ui_context")
        raw = {
            "app": "sweettv",
            "view": "show",
            "section": "series-" + ("X" * 300),
            "sections": [{"id": f"sec{i}", "label": f"Section {i} " + ("Д" * 200)} for i in range(30)],
            "chips": [{"id": f"chip{i}", "label": f"Filter {i} " + ("Я" * 300), "active": i == 0} for i in range(50)],
            "sort": {"id": "popular", "label": "Popular " + ("Z" * 300)},
            "can_search": True,
            "search_query": "Search " + ("Q" * 400),
            "search_hint": "Hint " + ("H" * 400),
            "modal": {
                "kind": "show",
                "show_id": "s1",
                "title": "Title " + ("T" * 500),
                "fav_key": "fk",
                "fav": True,
                "can_play": True,
                "play_label": "Play " + ("P" * 200),
                "alt_label": "Alt " + ("A" * 200),
                "can_archive": True,
                "seasons": list(range(1, 30)),
                "selected_season": 1,
                "demo": True,
                "episodes": [{"id": f"e{i}", "title": f"Ep {i} " + ("E" * 250)} for i in range(25)],
            },
        }
        c1 = uc.normalize_context(raw)
        c2 = uc.normalize_context(raw)
        self.assertEqual(c1, c2)
        encoded = _compact_json_bytes(c1)
        self.assertLessEqual(len(encoded), uc.MAX_CONTEXT_BYTES)
        self.assertLessEqual(len(c1["chips"]), 16)


class TestValidateCmd(unittest.TestCase):
    def test_accepts_all_valid_commands(self):
        uc = _require_module(self, "mediastick_ui_context")
        cases = [
            {"app": "sweettv", "cmd": "set_section", "section": "live"},
            {"app": "sweettv", "cmd": "set_filter", "id": "hd"},
            {"app": "sweettv", "cmd": "sort", "sort": "popular"},
            {"app": "youtube", "cmd": "search", "query": "lofi"},
            {"app": "sweettv", "cmd": "play"},
            {"app": "sweettv", "cmd": "play_from_start"},
            {"app": "youtube", "cmd": "toggle_fav"},
            {"app": "sweettv", "cmd": "select_tab", "idx": 0},
            {"app": "sweettv", "cmd": "play_episode", "idx": 0},
            {"app": "sweettv", "cmd": "play_epg", "idx": 2},
        ]
        for payload in cases:
            out = uc.validate_cmd(payload)
            self.assertEqual(out["app"], payload["app"])
            self.assertEqual(out["cmd"], payload["cmd"])

    def test_rejects_unknown_cmd_bad_app_and_bad_idx(self):
        uc = _require_module(self, "mediastick_ui_context")
        invalid_cases = [
            None,
            [],
            "play",
            {},
            {"app": "sweettv"},
            {"app": "sweettv", "cmd": ""},
            {"app": "sweettv", "cmd": "unknown_cmd"},
            {"app": "sweettv", "cmd": "delete_all"},
            {"cmd": "play"},
            {"app": "", "cmd": "play"},
            {"app": "netflix", "cmd": "play"},
            {"app": 123, "cmd": "play"},
            {"app": "sweettv", "cmd": "play_episode", "idx": -1},
            {"app": "sweettv", "cmd": "play_episode", "idx": True},
            {"app": "sweettv", "cmd": "play_episode", "idx": "0"},
            {"app": "sweettv", "cmd": "play_episode", "idx": 1.5},
            {"app": "sweettv", "cmd": "play_epg", "idx": -5},
            {"app": "sweettv", "cmd": "play_epg", "idx": False},
        ]
        for payload in invalid_cases:
            with self.assertRaises(ValueError, msg=f"payload={payload!r} must raise ValueError"):
                uc.validate_cmd(payload)


class TestPanelUiContextIO(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="test-ui-ctx-")
        self.path = os.path.join(self.dir.name, "ui-context.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_context_path_constant(self):
        puc = _require_module(self, "panel_ui_context")
        self.assertEqual(puc.CONTEXT_PATH, "/run/media-stick/ui-context.json")

    def test_write_atomic_permissions_skip_unchanged_and_read_roundtrip(self):
        puc = _require_module(self, "panel_ui_context")
        doc = {"app": "sweettv", "view": "section", "section": "live"}
        self.assertTrue(puc.write_context(doc, path=self.path))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        self.assertEqual(os.listdir(self.dir.name), ["ui-context.json"])

        # Unchanged normalized content must skip disk write and return False
        st1 = os.stat(self.path)
        self.assertFalse(puc.write_context(doc, path=self.path))
        st2 = os.stat(self.path)
        self.assertEqual((st1.st_ino, st1.st_mtime_ns), (st2.st_ino, st2.st_mtime_ns))

        # Changed content writes atomically and returns True
        self.assertTrue(puc.write_context({"app": "youtube", "view": "section", "section": "home"}, path=self.path))
        got = puc.read_context(path=self.path)
        self.assertEqual(got["app"], "youtube")
        self.assertEqual(got["section"], "home")

    def test_read_context_fallbacks_on_missing_corrupt_oversized_or_leaking(self):
        uc = _require_module(self, "mediastick_ui_context")
        puc = _require_module(self, "panel_ui_context")
        expected_empty = uc.empty_context()

        # Missing file
        self.assertEqual(puc.read_context(path=self.path), expected_empty)

        # Corrupt / non-dict JSON
        for raw in ("", "{bad json", "[]", "null", "123"):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(raw)
            self.assertEqual(puc.read_context(path=self.path), expected_empty, raw)

        # Oversized file (> 16384 bytes) even if valid JSON
        huge = json.dumps({"app": "sweettv", "view": "section", "section": "x" * 20000})
        self.assertGreater(len(huge.encode("utf-8")), 16384)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(huge)
        self.assertEqual(puc.read_context(path=self.path), expected_empty)

        # Secret leaking file on disk
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"app": "sweettv", "view": "section", "token": "secret123"}, f)
        self.assertEqual(puc.read_context(path=self.path), expected_empty)


class TestUiContextWatcher(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="test-ui-watch-")
        self.path = os.path.join(self.dir.name, "ui-context.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_notify_wakes_immediately_and_deduplicates_unchanged(self):
        puc = _require_module(self, "panel_ui_context")
        seen = []
        ev = threading.Event()

        def on_change(ctx):
            seen.append(ctx)
            ev.set()

        watcher = puc.UiContextWatcher(path=self.path, ws_count=lambda: 0, on_change=on_change)
        watcher.start()
        try:
            puc.write_context({"app": "sweettv", "view": "section", "section": "live"}, path=self.path)
            # With ws_count() == 0, watcher is passive until notify()
            watcher.notify()
            self.assertTrue(ev.wait(timeout=1.5), "notify() must wake watcher immediately")
            self.assertEqual(seen[-1]["section"], "live")

            # Calling notify() again with unchanged file must NOT fire on_change again
            ev.clear()
            watcher.notify()
            self.assertFalse(ev.wait(timeout=0.15), "unchanged state must not re-fire on_change")
        finally:
            watcher.stop()

    def test_active_ws_client_polls_and_passive_when_zero_clients(self):
        puc = _require_module(self, "panel_ui_context")
        seen = []
        ev = threading.Event()
        clients = [0]

        def on_change(ctx):
            seen.append(ctx)
            ev.set()

        watcher = puc.UiContextWatcher(path=self.path, ws_count=lambda: clients[0], on_change=on_change)
        watcher.start()
        try:
            # Passive when ws_count == 0
            puc.write_context({"app": "youtube", "view": "section", "section": "subs"}, path=self.path)
            self.assertFalse(ev.wait(timeout=0.35), "ws_count()==0 must stay passive")

            # Active when ws_count > 0: polls every 0.2s
            clients[0] = 1
            self.assertTrue(ev.wait(timeout=1.5), "ws_count()>0 must detect file change via polling")
            self.assertEqual(seen[-1]["app"], "youtube")
            self.assertEqual(seen[-1]["section"], "subs")
        finally:
            watcher.stop()


class TestDispatchUiCmd(unittest.TestCase):
    def test_valid_cmd_calls_kodi_notify_all(self):
        puc = _require_module(self, "panel_ui_context")
        calls = []

        def fake_kodi(method, params=None):
            calls.append((method, params))
            return "OK"

        res = puc.dispatch_ui_cmd({"app": "sweettv", "cmd": "play"}, fake_kodi)
        self.assertEqual(res["app"], "sweettv")
        self.assertEqual(res["cmd"], "play")
        self.assertEqual(len(calls), 1)
        method, params = calls[0]
        self.assertEqual(method, "JSONRPC.NotifyAll")
        self.assertEqual(params["sender"], "media-stick.panel")
        self.assertEqual(params["message"], "mediastick.ui_cmd")
        self.assertEqual(params["data"], res)

    def test_invalid_cmd_raises_without_calling_kodi(self):
        puc = _require_module(self, "panel_ui_context")
        calls = []
        with self.assertRaises(ValueError):
            puc.dispatch_ui_cmd({"app": "sweettv", "cmd": "bad_cmd"}, lambda m, p=None: calls.append((m, p)))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
