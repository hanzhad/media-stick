#!/usr/bin/env python3
"""Offline test of the shared SQLite WAL store (no Kodi, no device): python3 tools/test-store.py"""
import ast
import json
import multiprocessing
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
sys.path.insert(0, LIB)

import mediastick_store as ms  # noqa: E402

NOW = 1_800_000_000.0


def _mp_worker(db_path, worker_id, count, err_q):
    try:
        state = ms.StateStore(db_path=db_path)
        for i in range(count):
            key = f"yt:w{worker_id}_{i}"
            state.upsert_resume(
                media_key=key,
                app="youtube",
                pos=10 + i,
                total=100,
                done=False,
                updated_at=NOW + i,
                meta={"title": f"Video {worker_id}-{i}"},
            )
            got = state.get_resume(key)
            if not got or got["pos"] != 10 + i:
                err_q.put(f"mismatch on {key}: {got}")
                return
        state.close()
    except Exception as exc:
        err_q.put(f"worker {worker_id}: {exc!r}")


class ZeroXbmcImports(unittest.TestCase):
    def test_module_has_no_xbmc_imports(self):
        path = os.path.join(LIB, "mediastick_store.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        xbmc_mods = {m for m in imported if m.startswith("xbmc")}
        self.assertEqual(xbmc_mods, set())
        self.assertFalse(any(m.startswith("xbmc") for m in sys.modules))


class PureCoreSecrets(unittest.TestCase):
    def test_contains_secret_rejects_secret_keys_recursively(self):
        secret_keys = [
            "token", "password", "passwd", "secret", "cookie",
            "authorization", "bearer", "refresh_token", "access_token",
            "api_key", "auth", "client_secret",
        ]
        for k in secret_keys:
            self.assertTrue(ms.contains_secret({k: "val"}), k)
            self.assertTrue(ms.contains_secret({k.upper(): "val"}), k.upper())
            self.assertTrue(ms.contains_secret({"nested": [{"inner": {k: "val"}}]}), f"nested {k}")

    def test_contains_secret_rejects_secret_string_patterns(self):
        patterns = [
            "Bearer abcdef123456",
            "bearer xyz.123",
            "Authorization: Bearer tok",
            "https://cdn.example.com/stream.m3u8?token=sig123",
            "https://example.com/cb?access_token=abc",
            "https://example.com/cb?refresh_token=abc",
            "https://example.com/api?api_key=12345",
            "https://example.com/play?auth=signed",
            "ya29.a0AfH6SMB_example",
            "password=hunter2",
        ]
        for s in patterns:
            self.assertTrue(ms.contains_secret(s), s)
            self.assertTrue(ms.contains_secret({"items": [{"url": s}]}), s)

    def test_contains_secret_allows_safe_content_and_titles(self):
        safe_values = [
            None,
            123,
            True,
            "",
            [],
            {},
            {"title": "How to get an API key and a token", "section": "shows"},
            {"title": "The Secret Garden", "author": "Frances Hodgson Burnett"},
            {"cards": [{"id": "yt:abc", "thumb": "https://i.ytimg.com/vi/abc/hq.jpg"}]},
        ]
        for val in safe_values:
            self.assertFalse(ms.contains_secret(val), repr(val))


class PureCoreEncodingAndClassification(unittest.TestCase):
    def test_encode_decode_payload_roundtrip_and_compression(self):
        sample = {"title": "Привіт 🎬", "items": [1, 2, {"ok": True, "n": None}]}
        blob = ms.encode_payload(sample)
        self.assertIsInstance(blob, bytes)
        raw_json = zlib.decompress(blob).decode("utf-8")
        self.assertEqual(json.loads(raw_json), sample)
        self.assertEqual(ms.decode_payload(blob), sample)

    def test_decode_payload_rejects_corrupt_bytes(self):
        for bad in (b"", b"not-zlib", zlib.compress(b"{broken json")):
            with self.assertRaises((ValueError, zlib.error)):
                ms.decode_payload(bad)

    def test_classify_cache_entry_swr_boundaries(self):
        self.assertEqual(ms.classify_cache_entry(NOW, NOW, ttl=300, max_age=3600), "fresh")
        self.assertEqual(ms.classify_cache_entry(NOW, NOW + 300, ttl=300, max_age=3600), "fresh")
        self.assertEqual(ms.classify_cache_entry(NOW, NOW + 300.001, ttl=300, max_age=3600), "stale")
        self.assertEqual(ms.classify_cache_entry(NOW, NOW + 3600, ttl=300, max_age=3600), "stale")
        self.assertEqual(ms.classify_cache_entry(NOW, NOW + 3600.001, ttl=300, max_age=3600), "expired")


class PureCoreSnapshotAndEviction(unittest.TestCase):
    def test_max_snapshot_bytes_constant(self):
        self.assertEqual(ms.MAX_SNAPSHOT_BYTES, 65536)

    def test_validate_snapshot_normalizes_and_preserves_all_fields(self):
        snap = {
            "schema_v": 1,
            "section": "movies",
            "filter": "action",
            "sort": "year",
            "search_query": "matrix",
            "nav_stack": ["home", "movies"],
            "focused_control": 50,
            "focused_index": 3,
            "focused_key": "sw:vod:999",
            "scroll_offset": 120,
            "cards": [{"key": "sw:vod:999", "title": "The Matrix"}],
            "media_ref": {"kind": "vod", "id": "999"},
        }
        out = ms.validate_snapshot(snap)
        for k, v in snap.items():
            self.assertEqual(out[k], v)

    def test_validate_snapshot_rejects_non_dict_and_oversized_payload(self):
        for bad in (None, [], "snap", 42):
            with self.assertRaises((ValueError, TypeError)):
                ms.validate_snapshot(bad)

        # Generate incompressible varied cards so zlib compressed size > 65536
        big_cards = [{"id": i, "blob": os.urandom(96).hex()} for i in range(600)]
        oversized = {
            "schema_v": 1,
            "section": "movies",
            "cards": big_cards,
        }
        self.assertGreater(len(ms.encode_payload(oversized)), ms.MAX_SNAPSHOT_BYTES)
        with self.assertRaises(ValueError):
            ms.validate_snapshot(oversized)

    def test_compute_eviction_keys_lru_order_and_budget(self):
        self.assertEqual(ms.compute_eviction_keys([], 1000), [])
        rows = [
            ("ns1", "k_mid", 400, 200.0),
            ("ns1", "k_old", 400, 100.0),
            ("ns2", "k_new", 400, 300.0),
        ]
        # Total = 1200; budget = 1200 -> evict nothing
        self.assertEqual(ms.compute_eviction_keys(rows, 1200), [])
        # Budget = 800 -> evict k_old (remaining 800 <= 800)
        self.assertEqual(ms.compute_eviction_keys(rows, 800), [("ns1", "k_old")])
        # Budget = 500 -> evict k_old then k_mid (remaining 400 <= 500)
        self.assertEqual(ms.compute_eviction_keys(rows, 500), [("ns1", "k_old"), ("ns1", "k_mid")])
        # Budget = 0 -> evict all in LRU order
        self.assertEqual(
            ms.compute_eviction_keys(rows, 0),
            [("ns1", "k_old"), ("ns1", "k_mid"), ("ns2", "k_new")],
        )


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db_path = os.path.join(self.dir, "state.db")
        self.store = ms.StateStore(db_path=self.db_path)
        self.addCleanup(self.store.close)

    def test_wal_pragmas_and_schema(self):
        con = sqlite3.connect(self.db_path)
        self.addCleanup(con.close)
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
        tables = {
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertEqual(mode.lower(), "wal")
        self.assertGreaterEqual(timeout, 3000)
        self.assertTrue({"resume", "favourites", "app_recent", "prefs"}.issubset(tables))

    def test_resume_crud_and_ordering(self):
        self.assertIsNone(self.store.get_resume("yt:missing"))
        self.store.upsert_resume("yt:a", "youtube", 120, 600, False, NOW, {"title": "A"})
        self.store.upsert_resume("sw:vod:10", "sweettv", 0, 1800, True, NOW + 10, {"title": "B"})
        got = self.store.get_resume("yt:a")
        self.assertEqual(got["pos"], 120)
        self.assertEqual(got["total"], 600)
        self.assertFalse(got["done"])
        self.assertEqual(got["meta"]["title"], "A")

        # Update existing
        self.store.upsert_resume("yt:a", "youtube", 300, 600, False, NOW + 20, {"title": "A2"})
        self.assertEqual(self.store.get_resume("yt:a")["pos"], 300)

        items = self.store.list_resume()
        self.assertEqual([x["media_key"] for x in items], ["yt:a", "sw:vod:10"])

        self.store.delete_resume("yt:a")
        self.store.delete_resume("yt:nonexistent")
        self.assertIsNone(self.store.get_resume("yt:a"))
        self.assertEqual([x["media_key"] for x in self.store.list_resume()], ["sw:vod:10"])

    def test_favourites_app_recent_and_prefs(self):
        self.store.set_favourite("vod:42", "sweettv", title="Movie 42", thumb="https://img/42.jpg", meta={"year": 2024}, added_at=NOW)
        favs = self.store.list_favourites(app="sweettv")
        self.assertEqual(len(favs), 1)
        self.assertEqual(favs[0]["fav_key"], "vod:42")
        self.assertEqual(favs[0]["title"], "Movie 42")

        self.store.record_app_launch("plugin.video.sweettv", launched_at=NOW + 5)
        self.store.record_app_launch("webapp:netflix", launched_at=NOW + 10)
        recent = self.store.get_app_recent()
        self.assertEqual(recent["plugin.video.sweettv"], NOW + 5)
        self.assertEqual(recent["webapp:netflix"], NOW + 10)

        self.assertIsNone(self.store.get_pref("max-quality"))
        self.assertEqual(self.store.get_pref("max-quality", "1080p"), "1080p")
        self.store.set_pref("max-quality", "720p")
        self.assertEqual(self.store.get_pref("max-quality"), "720p")
        self.store.set_pref("max-quality", "unlimited")
        self.assertEqual(self.store.get_pref("max-quality"), "unlimited")

    def test_migrate_legacy_json_is_idempotent_and_never_clobbers_newer_sqlite(self):
        pos_path = os.path.join(self.dir, "positions.json")
        fav_path = os.path.join(self.dir, "sweettv-favourites.json")
        rec_path = os.path.join(self.dir, "recent.json")

        with open(pos_path, "w", encoding="utf-8") as f:
            json.dump({
                "v": 1,
                "items": {
                    "yt:old": {"pos": 50, "total": 200, "done": False, "at": int(NOW)},
                    "sw:vod:77": {"movie_id": "77", "episode_id": "", "pos": 100, "total": 300, "done": False, "at": int(NOW), "title": "Old Title"},
                },
                "live": {"cid": "105", "at": int(NOW)},
            }, f)
        with open(fav_path, "w", encoding="utf-8") as f:
            json.dump({
                "v": 1,
                "items": {
                    "vod:77": {"title": "Fav 77", "thumb": "https://img/77.jpg", "at": int(NOW), "meta": {"kind": "vod"}},
                },
            }, f)
        with open(rec_path, "w", encoding="utf-8") as f:
            json.dump({"plugin.video.youtube": NOW, "webapp:netflix": NOW}, f)

        # Pre-populate a NEWER SQLite row for sw:vod:77 and webapp:netflix
        self.store.upsert_resume("sw:vod:77", "sweettv", 250, 300, False, NOW + 500, {"title": "Newer SQLite"})
        self.store.record_app_launch("webapp:netflix", launched_at=NOW + 500)

        self.store.migrate_legacy_json(positions_path=pos_path, favourites_path=fav_path, recent_path=rec_path)
        # Idempotent second run
        self.store.migrate_legacy_json(positions_path=pos_path, favourites_path=fav_path, recent_path=rec_path)

        # yt:old imported; sw:vod:77 NOT clobbered
        self.assertEqual(self.store.get_resume("yt:old")["pos"], 50)
        self.assertEqual(self.store.get_resume("sw:vod:77")["pos"], 250)
        self.assertEqual(self.store.get_resume("sw:vod:77")["meta"]["title"], "Newer SQLite")

        favs = self.store.list_favourites()
        self.assertEqual([x["fav_key"] for x in favs], ["vod:77"])

        recent = self.store.get_app_recent()
        self.assertEqual(recent["plugin.video.youtube"], NOW)
        self.assertEqual(recent["webapp:netflix"], NOW + 500)

    def test_concurrent_multiprocess_wal_writes_and_reads(self):
        ctx = multiprocessing.get_context("spawn")
        err_q = ctx.Queue()
        procs = [
            ctx.Process(target=_mp_worker, args=(self.db_path, wid, 20, err_q))
            for wid in range(4)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=15)
            self.assertEqual(p.exitcode, 0)
        errors = []
        while not err_q.empty():
            errors.append(err_q.get())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.list_resume()), 80)


class CacheStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db_path = os.path.join(self.dir, "cache.db")
        self.cache = ms.CacheStore(db_path=self.db_path, max_bytes=8 * 1024 * 1024)
        self.addCleanup(self.cache.close)

    def test_wal_pragmas_and_schema(self):
        con = sqlite3.connect(self.db_path)
        self.addCleanup(con.close)
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = con.execute("PRAGMA busy_timeout").fetchone()[0]
        tables = {
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        self.assertEqual(mode.lower(), "wal")
        self.assertGreaterEqual(timeout, 3000)
        self.assertTrue({"pages", "ui_snapshots"}.issubset(tables))
        self.assertNotIn("api_cache", tables)
        self.assertFalse(hasattr(ms.CacheStore, "get_api"))
        self.assertFalse(hasattr(ms.CacheStore, "put_api"))

    def test_init_db_drops_retired_api_cache_table_and_updates_architecture_doc(self):
        legacy_db = os.path.join(self.dir, "legacy_cache.db")
        seed_con = sqlite3.connect(legacy_db)
        try:
            seed_con.execute(
                "CREATE TABLE api_cache ("
                "endpoint TEXT NOT NULL, req_hash TEXT NOT NULL, payload BLOB NOT NULL, "
                "size_bytes INTEGER NOT NULL, fetched_at REAL NOT NULL, "
                "ttl_s REAL NOT NULL, last_used_at REAL NOT NULL, "
                "PRIMARY KEY(endpoint, req_hash))"
            )
            seed_con.execute(
                "INSERT INTO api_cache (endpoint, req_hash, payload, size_bytes, fetched_at, ttl_s, last_used_at) "
                "VALUES ('/ep', 'h1', X'00', 1, 1.0, 60.0, 1.0)"
            )
            seed_con.commit()
        finally:
            seed_con.close()

        migrated = ms.CacheStore(db_path=legacy_db)
        self.addCleanup(migrated.close)
        migrated.put_page("sweettv:main", "k1", {"ok": True}, version=1, lang="uk", now=NOW)

        check_con = sqlite3.connect(legacy_db)
        try:
            tables = {
                r[0] for r in check_con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        finally:
            check_con.close()
        self.assertNotIn("api_cache", tables)
        self.assertTrue({"pages", "ui_snapshots"}.issubset(tables))
        self.assertEqual(
            migrated.get_page("sweettv:main", "k1", version=1, lang="uk", ttl=60, max_age=600, now=NOW).data,
            {"ok": True},
        )

        arch_path = os.path.join(ROOT, "docs", "architecture.md")
        with open(arch_path, encoding="utf-8") as f:
            arch_text = f.read()
        self.assertNotIn("api_cache", arch_text)
        self.assertIn("/var/cache/media-stick/sweettv/sweettv.db", arch_text)

    def test_page_swr_version_and_lang_semantics(self):
        self.cache.put_page("sweettv:main", "movies:p1", {"cards": [1, 2]}, version=4, lang="uk", now=NOW)

        # Fresh
        hit = self.cache.get_page("sweettv:main", "movies:p1", version=4, lang="uk", ttl=300, max_age=3600, now=NOW + 100)
        self.assertIsNotNone(hit)
        self.assertFalse(hit.stale)
        self.assertEqual(hit.data, {"cards": [1, 2]})

        # Stale
        hit_stale = self.cache.get_page("sweettv:main", "movies:p1", version=4, lang="uk", ttl=300, max_age=3600, now=NOW + 500)
        self.assertIsNotNone(hit_stale)
        self.assertTrue(hit_stale.stale)
        self.assertEqual(hit_stale.data, {"cards": [1, 2]})

        # Expired
        self.assertIsNone(self.cache.get_page("sweettv:main", "movies:p1", version=4, lang="uk", ttl=300, max_age=3600, now=NOW + 3601))
        # Version mismatch
        self.assertIsNone(self.cache.get_page("sweettv:main", "movies:p1", version=5, lang="uk", ttl=300, max_age=3600, now=NOW + 10))
        # Lang mismatch
        self.assertIsNone(self.cache.get_page("sweettv:main", "movies:p1", version=4, lang="ru", ttl=300, max_age=3600, now=NOW + 10))

    def test_secret_refused_before_any_write(self):
        self.cache.put_page("sweettv:main", "safe", {"ok": True}, version=1, lang="uk", now=NOW)
        for bad in ({"access_token": "secret"}, {"url": "https://cdn.example/v.m3u8?token=abc"}):
            with self.assertRaises(ms.SecretRefused):
                self.cache.put_page("sweettv:main", "bad", bad, version=1, lang="uk", now=NOW)
            with self.assertRaises(ms.SecretRefused):
                self.cache.save_snapshot("sweettv", "default", {"schema_v": 1, "media_ref": bad}, now=NOW)

        self.assertIsNone(self.cache.get_page("sweettv:main", "bad", version=1, lang="uk", ttl=60, max_age=600, now=NOW))
        self.assertIsNone(self.cache.load_snapshot("sweettv", "default"))
        # Existing safe entry untouched
        self.assertEqual(self.cache.get_page("sweettv:main", "safe", version=1, lang="uk", ttl=60, max_age=600, now=NOW).data, {"ok": True})

    def test_drop_namespace_alias_and_drop_service_prefix(self):
        for ns in ("youtube:1", "youtube:2", "youtubers:x", "sweettv:main"):
            self.cache.put_page(ns, "k", {"ns": ns}, version=1, lang="en", now=NOW)

        self.cache.drop("youtube:1")
        self.assertIsNone(self.cache.get_page("youtube:1", "k", version=1, lang="en", ttl=60, max_age=600, now=NOW))
        self.assertIsNotNone(self.cache.get_page("youtube:2", "k", version=1, lang="en", ttl=60, max_age=600, now=NOW))

        self.cache.drop_service("youtube")
        self.assertIsNone(self.cache.get_page("youtube:2", "k", version=1, lang="en", ttl=60, max_age=600, now=NOW))
        self.assertIsNotNone(self.cache.get_page("youtubers:x", "k", version=1, lang="en", ttl=60, max_age=600, now=NOW))
        self.assertIsNotNone(self.cache.get_page("sweettv:main", "k", version=1, lang="en", ttl=60, max_age=600, now=NOW))

    def test_lru_eviction_keeps_pages_within_max_bytes(self):
        small_db = os.path.join(self.dir, "small_cache.db")
        small = ms.CacheStore(db_path=small_db, max_bytes=20_000)
        self.addCleanup(small.close)

        # Each incompressible blob is ~8KB compressed
        for i in range(4):
            blob = {"i": i, "data": os.urandom(6000).hex()}
            small.put_page("ns", f"p{i}", blob, version=1, lang="en", now=NOW + i)

        con = sqlite3.connect(small_db)
        self.addCleanup(con.close)
        total_bytes = con.execute(
            "SELECT COALESCE((SELECT SUM(size_bytes) FROM pages), 0)"
        ).fetchone()[0]
        self.assertLessEqual(total_bytes, 20_000)
        # Oldest entry evicted, newest kept
        self.assertIsNone(small.get_page("ns", "p0", version=1, lang="en", ttl=600, max_age=600, now=NOW + 10))
        self.assertIsNotNone(small.get_page("ns", "p3", version=1, lang="en", ttl=600, max_age=600, now=NOW + 10))

    def test_quick_resume_snapshot_roundtrip_oversize_and_drop(self):
        snap = {
            "schema_v": 1,
            "section": "series",
            "filter": "drama",
            "sort": "popular",
            "search_query": "",
            "nav_stack": ["home", "series"],
            "focused_control": 50,
            "focused_index": 2,
            "focused_key": "sw:vod:55",
            "scroll_offset": 0,
            "cards": [{"key": "sw:vod:55", "title": "Show 55"}],
            "media_ref": {"movie_id": "55"},
        }
        self.cache.save_snapshot("sweettv", "default", snap, now=NOW)
        loaded = self.cache.load_snapshot("sweettv", "default")
        self.assertIsNotNone(loaded)
        for k, v in snap.items():
            self.assertEqual(loaded[k], v)

        # Oversized snapshot rejected cleanly without overwriting valid snapshot
        oversized = {"schema_v": 1, "section": "series", "cards": [{"blob": os.urandom(96).hex()} for _ in range(600)]}
        with self.assertRaises(ValueError):
            self.cache.save_snapshot("sweettv", "default", oversized, now=NOW + 1)
        self.assertEqual(self.cache.load_snapshot("sweettv", "default")["focused_key"], "sw:vod:55")

        self.cache.save_snapshot("youtube", "default", {"schema_v": 1, "section": "home"}, now=NOW)
        self.cache.drop_snapshots("sweettv")
        self.assertIsNone(self.cache.load_snapshot("sweettv", "default"))
        self.assertIsNotNone(self.cache.load_snapshot("youtube", "default"))
        self.cache.drop_snapshots()
        self.assertIsNone(self.cache.load_snapshot("youtube", "default"))


if __name__ == "__main__":
    unittest.main()
