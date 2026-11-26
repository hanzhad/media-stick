#!/usr/bin/env python3
"""Offline tests for Issue #34: Quick Resume snapshots, SQLite WAL page cache/resume,
playback-gated prefetch, and SWEET.TV SWR/prefetch fixes.

Run: python3 -B tools/test-quick-resume.py
"""
import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
TMP = tempfile.mkdtemp(prefix="media-stick-qr-test-")

os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_ADDON_LIB"] = os.path.join(ADDON, "resources", "lib")
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")
os.environ["MEDIASTICK_RESUME_DIR"] = os.path.join(TMP, "resume")
os.makedirs(os.environ["MEDIASTICK_PREFS_DIR"], exist_ok=True)
with open(os.path.join(os.environ["MEDIASTICK_PREFS_DIR"], "language"), "w", encoding="utf-8") as f:
    f.write("en\n")
os.environ["TZ"] = "UTC"
time.tzset()


class Fake:
    playing = False
    builtins = []
    notes = []
    rpc = []
    home = {}


class Control:
    def __init__(self):
        self.items, self.selected, self.label = [], 0, ""

    def reset(self):
        self.items, self.selected = [], 0

    def addItems(self, items):
        self.items = list(items)

    def selectItem(self, i):
        self.selected = i

    def getSelectedPosition(self):
        return self.selected if self.items else -1

    def size(self):
        return len(self.items)

    def setLabel(self, label):
        self.label = label

    def getLabel(self):
        return self.label


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2, self.props, self.art = label, label2, {}, {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def setLabel2(self, value):
        self.label2 = value

    def setArt(self, art):
        self.art = dict(art)


class WindowXML:
    def __init__(self, *a):
        self._props, self.focus = {}, 0
        self.controls = {
            100: Control(), 200: Control(), 201: Control(), 209: Control(), 210: Control(),
            211: Control(), 212: Control(), 213: Control(),
            300: Control(), 301: Control(), 400: Control(), 409: Control(), 410: Control(),
        }
        self.closed = False

    def setProperty(self, key, value):
        self._props[key] = value

    def getProperty(self, key):
        return self._props.get(key, "")

    def getControl(self, control_id):
        return self.controls[control_id]

    def setFocusId(self, control_id):
        self.focus = control_id

    def getFocusId(self):
        return self.focus

    def close(self):
        self.closed = True


class HomeWindow:
    def __init__(self, *a):
        pass

    def setProperty(self, key, value):
        Fake.home[key] = value

    def getProperty(self, key):
        return Fake.home.get(key, "")


class Player:
    def isPlaying(self):
        return Fake.playing

    def stop(self):
        Fake.playing = False


def translate(path):
    for special, name in (("special://temp", "temp"), ("special://profile", "profile")):
        if path.startswith(special):
            return TMP + "/" + name + path[len(special):]
    return path


xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: Fake.builtins.append(cmd)
xbmc.executeJSONRPC = lambda req: Fake.rpc.append(req) or "{}"
xbmc.getCondVisibility = lambda cond: True
xbmc.getIPAddress = lambda: "192.168.1.20"
xbmc.sleep = lambda ms: None
xbmc.Player = Player

xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = translate

xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = lambda *a: types.SimpleNamespace(getAddonInfo=lambda key: ADDON)

xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.WindowXML = WindowXML
xbmcgui.WindowXMLDialog = WindowXML
xbmcgui.Window = HomeWindow
xbmcgui.ListItem = ListItem
xbmcgui.Dialog = lambda: types.SimpleNamespace(notification=lambda h, t, *a, **k: Fake.notes.append(t))
xbmcgui.NOTIFICATION_INFO = "info"
xbmcgui.getCurrentWindowId = lambda: 10000

sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui, xbmcaddon=xbmcaddon)
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

import mediastick_resume as mr  # noqa: E402
import mediastick_store as ms  # noqa: E402
import mediastick_sweetapi as sweetapi  # noqa: E402
from resources.lib import page_cache, prefetch, sweettv_app, sweettv_pages as pages, youtube_app  # noqa: E402

NOW = 1_800_000_000.0


def wait_for(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class PageCacheSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pc-wal-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patch = mock.patch.object(page_cache, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        if hasattr(page_cache, "_memo"):
            page_cache._memo.clear()

    def test_drop_namespace_alias_clears_only_target_namespace(self):
        self.assertTrue(
            hasattr(page_cache, "drop_namespace"),
            "page_cache.drop_namespace alias is missing",
        )
        self.assertTrue(page_cache.put("sweettv:main", "movies:0:1:0", {"items": [1]}, now=NOW))
        self.assertTrue(page_cache.put("youtube:p1", "home", {"entries": [2]}, now=NOW))
        page_cache.drop_namespace("sweettv:main")
        self.assertIsNone(page_cache.get("sweettv:main", "movies:0:1:0", now=NOW))
        self.assertIsNotNone(page_cache.get("youtube:p1", "home", now=NOW))

    def test_backed_by_sqlite_wal_cache_store_without_json_files(self):
        self.assertTrue(page_cache.put("sweettv:main", "k1", {"ok": True, "n": 42}, now=NOW))
        hit = page_cache.get("sweettv:main", "k1", ttl=300, max_age=3600, now=NOW + 10)
        self.assertIsNotNone(hit)
        self.assertEqual((hit.value, hit.stale), ({"ok": True, "n": 42}, False))

        files = os.listdir(self.dir)
        db_files = [name for name in files if name.endswith(".db")]
        json_files = [name for name in files if name.endswith(".json")]
        self.assertTrue(db_files, f"Expected SQLite .db file in {self.dir}, found {files}")
        self.assertEqual(json_files, [], f"Expected no legacy .json cache files, found {json_files}")

        con = sqlite3.connect(os.path.join(self.dir, db_files[0]))
        self.addCleanup(con.close)
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")

    def test_secret_and_non_json_payloads_refused(self):
        self.assertFalse(page_cache.put("sweettv:main", "bad1", {"access_token": "secret"}, now=NOW))
        self.assertFalse(page_cache.put("sweettv:main", "bad2", {1, 2, 3}, now=NOW))
        self.assertIsNone(page_cache.get("sweettv:main", "bad1", now=NOW))
        self.assertIsNone(page_cache.get("sweettv:main", "bad2", now=NOW))


class PrefetchPlaybackGateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="prefetch-gate-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patch = mock.patch.object(page_cache, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        self.handles = []

    def tearDown(self):
        for handle in self.handles:
            handle.cancel()
            handle.wait(2)

    def test_playback_gate_hook_exists_and_blocks_warm_when_active(self):
        self.assertTrue(
            hasattr(prefetch, "_is_playback_or_cast_active"),
            "prefetch._is_playback_or_cast_active() hook is missing",
        )
        ran = []
        with mock.patch.object(prefetch, "_is_playback_or_cast_active", return_value=True), \
             mock.patch.object(prefetch, "IDLE_POLL", 0.01):
            handle = prefetch.warm(
                "sweettv:main",
                [("movies:0:1:0", lambda: ran.append("movies") or {"items": [1]})],
                idle=lambda: True,
                idle_timeout=0.08,
                pause=0,
                nice=0,
                log=lambda _: None,
            )
            self.handles.append(handle)
            self.assertTrue(handle.wait(2))
        self.assertEqual(ran, [])
        self.assertEqual(handle.note, "busy")

    def test_playback_gate_resumes_once_playback_stops(self):
        self.assertTrue(
            hasattr(prefetch, "_is_playback_or_cast_active"),
            "prefetch._is_playback_or_cast_active() hook is missing",
        )
        active = [True]
        ran = []
        with mock.patch.object(prefetch, "_is_playback_or_cast_active", side_effect=lambda: active[0]), \
             mock.patch.object(prefetch, "IDLE_POLL", 0.01):
            handle = prefetch.warm(
                "youtube:p1",
                [("home", lambda: ran.append("home") or {"entries": [1]})],
                idle=lambda: True,
                idle_timeout=1.0,
                pause=0,
                nice=0,
                log=lambda _: None,
            )
            self.handles.append(handle)
            time.sleep(0.08)
            self.assertEqual(ran, [])
            active[0] = False
            self.assertTrue(handle.wait(2))
        self.assertEqual(ran, ["home"])
        self.assertEqual(handle.stored, ["home"])


class QuickResumeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="qr-snap-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db_path = os.path.join(self.dir, "cache.db")

    def _import_quick_resume(self):
        try:
            from resources.lib import quick_resume
            return quick_resume
        except ImportError as exc:
            self.fail(f"quick_resume module not implemented: {exc}")

    def test_sweettv_snapshot_builder_roundtrip_and_size_cap(self):
        qr = self._import_quick_resume()
        cards = [{"key": f"sw:vod:{i}", "title": f"Film {i}", "thumb": f"https://img/{i}.jpg"} for i in range(10)]
        snap = qr.build_sweettv_snapshot(section="movies", filter="all", focused_index=4, cards=cards)
        self.assertEqual(snap["schema_v"], 2)
        validated = ms.validate_snapshot(snap)
        self.assertEqual(validated["section"], "movies")
        self.assertEqual(validated["filter"], "all")
        self.assertEqual(validated["focused_index"], 4)
        self.assertEqual(len(validated["cards"]), 10)

        store = ms.CacheStore(db_path=self.db_path)
        self.addCleanup(store.close)
        store.save_snapshot("sweettv", "default", snap, now=NOW)
        loaded = store.load_snapshot("sweettv", "default")
        self.assertEqual(loaded["section"], "movies")
        self.assertEqual(loaded["focused_index"], 4)

        # Oversized card list must be capped cleanly <= MAX_SNAPSHOT_BYTES (64 KB)
        huge_cards = [{"key": f"sw:vod:{i}", "title": "X" * 300, "blob": os.urandom(96).hex()} for i in range(600)]
        capped = qr.build_sweettv_snapshot(section="series", filter="drama", focused_index=1, cards=huge_cards)
        ms.validate_snapshot(capped)
        self.assertLessEqual(len(ms.encode_payload(capped)), ms.MAX_SNAPSHOT_BYTES)

    def test_youtube_snapshot_builder_roundtrip_and_size_cap(self):
        qr = self._import_quick_resume()
        cards = [{"video_id": f"vid_{i}", "title": f"Video {i}"} for i in range(8)]
        snap = qr.build_youtube_snapshot(
            section="search",
            query="jazz live",
            kind="videos",
            stack=[{"section": "home", "pos": 2}],
            focused_index=3,
            cards=cards,
        )
        validated = ms.validate_snapshot(snap)
        self.assertEqual(validated["section"], "search")
        self.assertEqual(validated["search_query"], "jazz live")
        self.assertEqual(validated["focused_index"], 3)
        self.assertTrue(validated["nav_stack"])

        store = ms.CacheStore(db_path=self.db_path)
        self.addCleanup(store.close)
        store.save_snapshot("youtube", "p1", snap, now=NOW)
        loaded = store.load_snapshot("youtube", "p1")
        self.assertEqual(loaded["section"], "search")
        self.assertEqual(loaded["search_query"], "jazz live")
        self.assertEqual(loaded["focused_index"], 3)

        huge_cards = [{"video_id": f"v{i}", "blob": os.urandom(96).hex()} for i in range(600)]
        capped = qr.build_youtube_snapshot(
            section="home", query="", kind="videos", stack=[], focused_index=0, cards=huge_cards,
        )
        ms.validate_snapshot(capped)
        self.assertLessEqual(len(ms.encode_payload(capped)), ms.MAX_SNAPSHOT_BYTES)


class SweetTVShelfSWRAndPrefetchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="shelf-swr-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patch = mock.patch.object(page_cache, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        if hasattr(page_cache, "_memo"):
            page_cache._memo.clear()

    def test_stale_cache_hit_shows_immediately_and_triggers_background_refresh(self):
        ns = pages.namespace()
        ckey = pages.catalog_key("movies", 0, 1, 0)
        stale_items = [{"id": 101, "title": "Old Film", "poster": "https://img/old.jpg"}]
        fresh_items = [{"id": 202, "title": "New Film", "poster": "https://img/new.jpg"}]

        # Seed entry older than PAGE_TTL (300s) but younger than PAGE_MAX_AGE (6h) -> stale!
        stale_ts = time.time() - (pages.PAGE_TTL + 30)
        self.assertTrue(page_cache.put(ns, ckey, pages.to_value("movies", stale_items, 1), now=stale_ts))

        win = sweettv_app.SweetTV()
        win.setup(demo=False)
        win.section = "movies"
        win.genres = [{"id": 1, "name": "Action"}]
        win._apply_cards = mock.Mock()

        api_called = threading.Event()

        def fake_catalog_page(section, genre_id=0, sort_mode_id=1, offset=0, limit=30, tr=None):
            api_called.set()
            return {"ok": True, "items": fresh_items, "total": 1}

        with mock.patch.object(sweetapi, "catalog_page", side_effect=fake_catalog_page), \
             mock.patch.object(prefetch, "warm", return_value=mock.Mock()):
            win._run_catalog(win._section_gen, "movies", 0, 1, 0, False, mr.empty(), set(), False)
            self.assertEqual([x["id"] for x in win.cat_items], [101], "stale cached items should render immediately")
            self.assertTrue(
                api_called.wait(1.5),
                "SWR stale hit must trigger background refresh via sweetapi.catalog_page",
            )
            self.assertTrue(
                wait_for(lambda: (page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE) or mock.Mock(value={})).value.get("items", [{}])[0].get("id") == 202, timeout=1.5),
                "background refresh must update page_cache with fresh items",
            )


class YouTubeIdlePlaybackTests(unittest.TestCase):
    def test_idle_returns_false_while_kodi_player_is_playing(self):
        win = youtube_app.YouTube()
        win.setup(demo=False)
        win.mode = "grid"
        win.refreshing = 0
        win.loading_more = 0

        Fake.playing = False
        self.assertTrue(win._idle())

        Fake.playing = True
        self.assertFalse(win._idle(), "YouTube._idle() must return False while video playback is active")
        Fake.playing = False


class ResumeWALAndMigrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="resume-wal-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patch = mock.patch.object(mr, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)

    def test_legacy_json_migration_to_sqlite_wal_is_idempotent(self):
        pos_doc = {
            "v": 1,
            "items": {
                "sw:105|9001": {
                    "cid": "105", "epg": "9001", "pos": 420, "total": 1800,
                    "done": False, "at": int(NOW), "title": "Evening News", "start": 1000, "stop": 2800,
                }
            },
            "live": {"cid": "105", "at": int(NOW)},
        }
        fav_doc = {
            "v": 1,
            "items": {
                "ch:105": {"title": "News 24", "thumb": "https://img/105.png", "at": int(NOW)}
            },
        }
        with open(os.path.join(self.dir, mr.STORE_FILE), "w", encoding="utf-8") as f:
            json.dump(pos_doc, f)
        with open(os.path.join(self.dir, mr.FAVS_FILE), "w", encoding="utf-8") as f:
            json.dump(fav_doc, f)

        loaded = mr.load()
        self.assertIn("sw:105|9001", loaded["items"])
        self.assertEqual(loaded["items"]["sw:105|9001"]["pos"], 420)
        favs = mr.load_favs()
        self.assertIn("ch:105", favs["items"])

        db_files = [name for name in os.listdir(self.dir) if name.endswith(".db")]
        self.assertTrue(db_files, f"Expected SQLite WAL state.db in {self.dir} after migration")

        # Update via API to a newer timestamp, then re-load: legacy JSON must not overwrite newer WAL row
        updated = mr.record(loaded, "plugin://plugin.video.sweettv/playvid/105|9001", 800, 1800, NOW + 60,
                            meta={"title": "Evening News", "start": 1000, "stop": 2800})
        self.assertTrue(mr.save(updated))
        reloaded = mr.load()
        self.assertEqual(reloaded["items"]["sw:105|9001"]["pos"], 800)

    def test_concurrent_wal_reads_and_writes_succeed_without_errors(self):
        errors = []

        def worker(idx):
            try:
                for step in range(10):
                    doc = mr.load()
                    doc = mr.record(
                        doc,
                        f"plugin://plugin.video.sweettv/playvid/{100 + idx}|{1000 + step}",
                        100 + step,
                        1800,
                        NOW + step,
                        meta={"title": f"Show {idx}", "start": 1000, "stop": 2800},
                    )
                    self.assertTrue(mr.save(doc))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
