#!/usr/bin/env python3
"""Offline tests for mediastick_sweetstore.py (Pure Core + Thin WAL SQLite Shell)."""
import ast
from datetime import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
TMPFILES_CONF = os.path.join(ROOT, "device", "files", "etc", "tmpfiles.d", "media-stick.conf")
EMU_START_SH = os.path.join(ROOT, "tools", "emulator", "start.sh")
sys.path.insert(0, LIB)

import mediastick_store as ms_core  # noqa: E402
import mediastick_sweetstore as store  # noqa: E402

NOW = 1_800_000_000


def _local_day_key(ts: int) -> str:
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")


def _strip_comments(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", ";"))
    )


def _unpack_swr_hit(testcase: unittest.TestCase, hit):
    testcase.assertIsNotNone(hit)
    if hasattr(hit, "data") and hasattr(hit, "stale"):
        return hit.data, bool(hit.stale)
    if isinstance(hit, dict) and "data" in hit and "stale" in hit:
        return hit["data"], bool(hit["stale"])
    if isinstance(hit, tuple) and len(hit) == 2:
        return hit[0], bool(hit[1])
    testcase.fail(f"Unexpected get_swr return shape: {hit!r}")


class TestDeploymentAndImports(unittest.TestCase):
    """Verify stdlib-only zero-xbmc constraint, DEFAULT_DB_PATH, tmpfiles.d, and emulator backup."""

    def test_zero_xbmc_imports(self):
        path = os.path.join(LIB, "mediastick_sweetstore.py")
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

    def test_default_db_path_and_env_override(self):
        self.assertEqual(store.DEFAULT_DB_PATH, "/var/cache/media-stick/sweettv/sweettv.db")
        self.assertTrue(
            callable(getattr(store, "reset_default_store", None)),
            "mediastick_sweetstore must define reset_default_store()",
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_a = os.path.join(tmp, "a", "sweettv.db")
            db_b = os.path.join(tmp, "b", "sweettv.db")
            with mock.patch.dict(os.environ, {"MEDIASTICK_SWEETSTORE_DB": db_a}):
                store.reset_default_store()
                st_a = store.default_store()
                self.assertEqual(st_a.db_path, db_a)
                self.assertIs(store.default_store(), st_a)
            with mock.patch.dict(os.environ, {"MEDIASTICK_SWEETSTORE_DB": db_b}):
                store.reset_default_store()
                st_b = store.default_store()
                self.assertEqual(st_b.db_path, db_b)
                self.assertIsNot(st_b, st_a)
            store.reset_default_store()

    def test_tmpfiles_declares_sweettv_wal_dir_and_preserves_existing_rules(self):
        with open(TMPFILES_CONF, encoding="utf-8") as f:
            text = _strip_comments(f.read())
        expected_entries = (
            ("/run/media-stick", "1775", "root", "media"),
            ("/run/media-stick/shots", "0775", "media", "media"),
            ("/run/media-stick/signin", "0755", "media", "media"),
            ("/run/media-stick/resume", "0755", "media", "media"),
            ("/run/media-stick/page-cache", "0755", "media", "media"),
            ("/tmp/chromium-cache", "0755", "media", "media"),
            ("/var/cache/media-stick", "1775", "root", "media"),
            ("/var/lib/media-stick", "1775", "root", "media"),
            ("/var/cache/media-stick/sweettv", "0755", "media", "media"),
        )
        for path, mode, owner, group in expected_entries:
            for kind in ("d", "z"):
                with self.subTest(kind=kind, path=path):
                    pattern = rf"(?m)^{kind}\s+{re.escape(path)}\s+{mode}\s+{owner}\s+{group}\s+-"
                    self.assertRegex(
                        text,
                        pattern,
                        f"tmpfiles.d missing '{kind} {path} {mode} {owner} {group} -'",
                    )

    def test_emulator_start_pulls_sweettv_db_backup(self):
        with open(EMU_START_SH, encoding="utf-8") as f:
            script = _strip_comments(f.read())
        self.assertIn("/var/lib/media-stick/resume/state.db", script)
        self.assertIn("/var/cache/media-stick/sweettv/sweettv.db", script)


class TestSweetStorePureCore(unittest.TestCase):
    """In-memory tests for Pure Core normalizers (zero disk, SQLite, or network I/O)."""

    def test_strip_programme_prefix_table(self):
        cases = (
            ('Премьера. Х/ф "Любовь"', "Любовь"),
            ("Прем'єра. Т/с Следствие", "Следствие"),
            ("Прем’єра! М/ф «Мавка»", "Мавка"),
            ('Д/ф "Планета Земля"', "Планета Земля"),
            ("Д/с Таємниці архівів", "Таємниці архівів"),
            ("М/с Губка Боб", "Губка Боб"),
            ("Новинка. Велике шоу", "Велике шоу"),
            ('Новинка: "Зрадники"', "Зрадники"),
            ("Анонс. Вечірні новини", "Вечірні новини"),
            ("Анонс: Кіно", "Кіно"),
            ("ПРЕМЬЕРА. новинка. х/ф «Інтерстеллар»", "Інтерстеллар"),
            # Adjacent negative / boundary cases (must NOT over-strip valid title words)
            ("Обычное шоу", "Обычное шоу"),
            ("Премьер-министр", "Премьер-министр"),
            ("Новинки техніки", "Новинки техніки"),
            ("Анонси тижня", "Анонси тижня"),
            ("", ""),
            (None, ""),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(store.strip_programme_prefix(raw), expected)

    def test_base_show_title_table(self):
        self.assertTrue(
            callable(getattr(store, "base_show_title", None)),
            "mediastick_sweetstore must define Pure Core base_show_title(title)",
        )
        cases = (
            ("Премьера. Холостяк. Випуск 6", "Холостяк"),
            ("Прем'єра. Т/с Слідство Сезон 2 Серія 5", "Слідство"),
            ("Холостяк Сезон 14 Випуск 1", "Холостяк"),
            ("Шоу Season 2 Episode 5", "Шоу"),
            ("Шоу Сезон 1 Серия 3", "Шоу"),
            ("Шоу Епізод 4", "Шоу"),
            ("Шоу Эпизод 4", "Шоу"),
            ("Новинка. МастерШеф - Сезон 14 - Випуск 1", "МастерШеф"),
            # Adjacent negative / boundary cases
            ("Destination X", "Destination X"),
            ("Seasoned Chef", "Seasoned Chef"),
            ("Обычное шоу", "Обычное шоу"),
            ("", ""),
            (None, ""),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(store.base_show_title(raw), expected)

    def test_compute_can_archive_boundaries(self):
        self.assertTrue(
            callable(getattr(store, "compute_can_archive", None)),
            "mediastick_sweetstore must define Pure Core compute_can_archive()",
        )
        week = 7 * 86400
        three_days = 3 * 86400
        cases = (
            # (catchup, catchup_duration, available, time_start, now, expected)
            (True, 7, True, NOW, NOW, True),
            (True, 7, True, NOW - 1800, NOW, True),
            (True, 7, True, NOW - week, NOW, True),
            (True, 7, True, NOW - week - 1, NOW, False),
            (True, 7, True, NOW + 1, NOW, False),
            (True, 3, True, NOW - three_days, NOW, True),
            (True, 3, True, NOW - three_days - 1, NOW, False),
            (False, 7, True, NOW - 1800, NOW, False),
            (True, 7, False, NOW - 1800, NOW, False),
            (True, 0, True, NOW - 1800, NOW, False),
            (True, 7, True, 0, NOW, False),
            (True, 7, True, -100, NOW, False),
        )
        for catchup, dur, avail, t_start, now_ts, expected in cases:
            with self.subTest(catchup=catchup, dur=dur, avail=avail, t_start=t_start):
                self.assertIs(
                    store.compute_can_archive(catchup, dur, avail, t_start, now_ts),
                    expected,
                )

    def test_normalize_channels_payload_extracts_all_fields_and_ignores_junk(self):
        self.assertTrue(
            callable(getattr(store, "normalize_channels_payload", None)),
            "mediastick_sweetstore must define Pure Core normalize_channels_payload(doc, now)",
        )
        doc = {
            "status": "OK",
            "categories": [
                {"id": 29, "caption": "Розваги", "order": 10},
                {"id": 1000, "caption": "Усі", "order": 1},
                "junk",
                {"caption": "missing_id"},
            ],
            "list": [
                {
                    "id": 15,
                    "name": "СТБ HD",
                    "number": 5,
                    "slug": "stb-hd",
                    "icon_v2_url": "https://img.example/stb-v2.webp",
                    "icon_url": "https://img.example/stb.png",
                    "banner_url": "https://img.example/stb-banner.jpg",
                    "catchup": True,
                    "catchup_duration": 7,
                    "epg_days_future": 4,
                    "available": True,
                    "is_fast_channel": True,
                    "quality": 2,
                    "category": [29, "1000", None, "bad"],
                    "epg": [
                        {
                            "id": 501,
                            "text": 'Премьера. Х/ф "Інтерстеллар"',
                            "description": "Наукова фантастика",
                            "tv_show_id": 777,
                            "season_number": 1,
                            "episode_number": 2,
                            "time_start": NOW - 3600,
                            "time_stop": NOW - 1800,
                            "image_url": "https://img.example/501.jpg",
                            "preview_url": "https://img.example/501-prev.jpg",
                            "available": True,
                        },
                        {"id": 502, "text": "", "time_start": NOW, "time_stop": NOW + 600},
                        None,
                    ],
                },
                None,
                {"id": 0, "name": "BadId"},
            ],
        }
        norm = store.normalize_channels_payload(doc, NOW)
        self.assertEqual(norm["status"], "OK")
        self.assertEqual(
            norm["categories"],
            [{"id": 1000, "caption": "Усі"}, {"id": 29, "caption": "Розваги"}],
        )
        self.assertEqual(len(norm["channels"]), 1)
        ch = norm["channels"][0]
        self.assertEqual(ch["cid"], "15")
        self.assertEqual(ch["name"], "СТБ HD")
        self.assertEqual(ch["number"], 5)
        self.assertEqual(ch["slug"], "stb-hd")
        self.assertTrue(ch["icon_url"])
        self.assertEqual(ch["banner_url"], "https://img.example/stb-banner.jpg")
        self.assertTrue(ch["catchup"])
        self.assertEqual(ch["catchup_duration"], 7)
        self.assertEqual(ch["epg_days_future"], 4)
        self.assertTrue(ch["available"])
        self.assertTrue(ch["is_fast_channel"])
        self.assertEqual(ch["category"], [29, 1000])

        self.assertEqual(len(norm["programmes"]), 1)
        pr = norm["programmes"][0]
        required_prog_keys = {
            "epg_id", "cid", "title", "base_title", "description",
            "show_id", "season_num", "episode_num", "time_start", "time_stop",
            "day_key", "image_url", "preview_url", "can_archive", "available",
        }
        self.assertTrue(required_prog_keys.issubset(pr.keys()), set(pr.keys()))
        self.assertEqual((pr["epg_id"], pr["cid"]), ("501", "15"))
        self.assertEqual(pr["base_title"], "Інтерстеллар")
        self.assertEqual(pr["description"], "Наукова фантастика")
        self.assertEqual((pr["show_id"], pr["season_num"], pr["episode_num"]), ("777", 1, 2))
        self.assertEqual(pr["day_key"], _local_day_key(NOW - 3600))
        self.assertTrue(pr["can_archive"])
        self.assertTrue(pr["available"])

        # Boundary / malformed payloads do not raise
        for bad in (None, [], "bad"):
            empty = store.normalize_channels_payload(bad, NOW)
            self.assertEqual((empty["channels"], empty["programmes"]), ([], []))

    def test_normalize_title_payload_sorts_seasons_and_episodes_ascending(self):
        self.assertTrue(
            callable(getattr(store, "normalize_title_payload", None)),
            "mediastick_sweetstore must define Pure Core normalize_title_payload(detail, now)",
        )
        detail = {
            "ok": True,
            "id": "vod:9558",
            "title": "Зрадники",
            "description": "Реаліті-шоу",
            "age_rating": "16+",
            "genres": [3, 12],
            "genre_names": ["Шоу", "Комедия"],
            "countries": ["Україна"],
            "seasons": [
                {
                    "id": 20,
                    "number": 2,
                    "title": "Сезон 2",
                    "episodes": [
                        {"id": 202, "number": 2, "title": "S2E2", "duration": 2400},
                        {"id": 201, "number": 1, "title": "S2E1", "duration": 2300},
                    ],
                },
                {
                    "id": 10,
                    "number": 1,
                    "title": "Сезон 1",
                    "episodes": [
                        {"id": 103, "number": 3, "title": "S1E3", "duration": 2500},
                        {"id": 101, "number": 1, "title": "S1E1", "duration": 2400},
                        {"id": 102, "number": 2, "title": "S1E2", "duration": 2450},
                    ],
                },
            ],
        }
        t_row, ep_rows = store.normalize_title_payload(detail, NOW)
        self.assertIsInstance(t_row, dict)
        self.assertTrue(t_row)
        self.assertIsInstance(ep_rows, list)
        self.assertEqual(len(ep_rows), 5)
        ep_order = [
            (
                e.get("season_num") if "season_num" in e else e.get("season"),
                e.get("episode_num") if "episode_num" in e else e.get("number"),
                e.get("title"),
            )
            for e in ep_rows
        ]
        self.assertEqual(
            ep_order,
            [
                (1, 1, "S1E1"),
                (1, 2, "S1E2"),
                (1, 3, "S1E3"),
                (2, 1, "S2E1"),
                (2, 2, "S2E2"),
            ],
        )
        if "seasons" in t_row and isinstance(t_row["seasons"], list):
            self.assertEqual([s["number"] for s in t_row["seasons"]], [1, 2])
            self.assertEqual([e["number"] for e in t_row["seasons"][0]["episodes"]], [1, 2, 3])
            self.assertEqual([e["number"] for e in t_row["seasons"][1]["episodes"]], [1, 2])

        for bad in (None, {}, {"ok": False, "id": "vod:1"}):
            bad_t, bad_eps = store.normalize_title_payload(bad, NOW)
            self.assertFalse(bad_t)
            self.assertEqual(bad_eps, [])


class TestSweetStoreSQLiteShell(unittest.TestCase):
    """Thin WAL SQLite Shell tests against a temporary database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "sweettv", "sweettv.db")
        self.st = store.SweetStore(self.db_path)

    def tearDown(self):
        self.st.close()
        self.tmp.cleanup()

    def test_wal_pragmas_tables_composite_pks_and_indexes(self):
        con = sqlite3.connect(self.db_path)
        self.addCleanup(con.close)
        mode = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        timeout = int(con.execute("PRAGMA busy_timeout").fetchone()[0])
        # Check connection pragmas on the store's own SQLite connection too (synchronous/temp_store are per-connection)
        sync_val = int(self.st._conn.execute("PRAGMA synchronous").fetchone()[0])
        temp_val = int(self.st._conn.execute("PRAGMA temp_store").fetchone()[0])
        self.assertEqual(mode, "wal")
        self.assertGreaterEqual(timeout, 3000)
        self.assertEqual(sync_val, 1)   # NORMAL
        self.assertEqual(temp_val, 2)   # MEMORY

        tables = {
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        expected_tables = {
            "meta", "channel_categories", "channels", "programmes",
            "titles", "episodes", "collections", "search_index", "swr_cache",
        }
        self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

        # Verify programmes indexes cover (cid, time_start, time_stop), (cid, day_key, time_start), and (show_id)
        idx_cols = set()
        for idx_row in con.execute("PRAGMA index_list('programmes')").fetchall():
            idx_name = idx_row[1]
            cols = tuple(r[2] for r in con.execute(f"PRAGMA index_info('{idx_name}')").fetchall())
            idx_cols.add(cols)
        self.assertIn(("cid", "time_start", "time_stop"), idx_cols)
        self.assertIn(("cid", "day_key", "time_start"), idx_cols)
        self.assertIn(("show_id",), idx_cols)

        # Composite PK(cid, epg_id) on programmes: identical epg_id on two channels must not clobber each other
        self.st.upsert_channels({
            "status": "OK",
            "list": [
                {"id": 10, "name": "Ch 10", "catchup": True, "catchup_duration": 7, "available": True},
                {"id": 20, "name": "Ch 20", "catchup": True, "catchup_duration": 7, "available": True},
            ],
        }, now=NOW)
        self.st.upsert_epg("10", [{"id": 999, "text": "Show on 10", "time_start": NOW - 600, "time_stop": NOW + 600}], now=NOW)
        self.st.upsert_epg("20", [{"id": 999, "text": "Show on 20", "time_start": NOW - 600, "time_stop": NOW + 600}], now=NOW)
        r10 = self.st.recall_programme("999", cid="10", now=NOW)
        r20 = self.st.recall_programme("999", cid="20", now=NOW)
        self.assertIsNotNone(r10)
        self.assertIsNotNone(r20)
        self.assertEqual(r10["title"], "Show on 10")
        self.assertEqual(r20["title"], "Show on 20")

        # Composite PK(title_key, ep_key) on episodes: identical episode id across two titles must coexist
        for tid, ep_title in (("vod:1", "Title 1 Ep"), ("vod:2", "Title 2 Ep")):
            self.st.upsert_title_detail({
                "ok": True,
                "id": tid,
                "title": tid,
                "seasons": [{"number": 1, "episodes": [{"id": 101, "number": 1, "title": ep_title}]}],
            }, now=NOW)
        self.assertEqual(self.st.get_title_detail("vod:1")["seasons"][0]["episodes"][0]["title"], "Title 1 Ep")
        self.assertEqual(self.st.get_title_detail("vod:2")["seasons"][0]["episodes"][0]["title"], "Title 2 Ep")

    def test_secret_refused_on_all_writes(self):
        self.assertTrue(
            callable(getattr(self.st, "put_swr", None)),
            "SweetStore must define put_swr()",
        )
        with self.assertRaises(ms_core.SecretRefused):
            self.st.upsert_channels({
                "status": "OK",
                "list": [{"id": 1, "name": "Ch", "icon_url": "https://cdn.example/i.png?token=sig123"}],
            }, now=NOW)
        with self.assertRaises(ms_core.SecretRefused):
            self.st.upsert_epg("1", [
                {"id": 10, "text": "P", "time_start": NOW, "time_stop": NOW + 600, "access_token": "secret"},
            ], now=NOW)
        with self.assertRaises(ms_core.SecretRefused):
            self.st.upsert_title_detail({
                "ok": True, "id": "vod:1", "title": "Film",
                "vod_url": "https://cdn.example/stream.m3u8?token=abc",
            }, now=NOW)
        with self.assertRaises(ms_core.SecretRefused):
            self.st.put_swr("catalog:movies", {"refresh_token": "secret"}, ttl_s=300, now=NOW)

        self.assertEqual(self.st.get_channels_payload(now=NOW), {})
        self.assertIsNone(self.st.get_title_detail("vod:1"))

    def test_channels_reconciliation_sync_errors_and_get_channels_payload(self):
        for method in ("record_sync_error", "get_channels_payload"):
            self.assertTrue(
                callable(getattr(self.st, method, None)),
                f"SweetStore must define {method}()",
            )
        # 1. Empty store returns {}
        self.assertEqual(self.st.get_channels_payload(now=NOW), {})

        # 2. Error recorded before any successful sync -> {"status": "error", "error": ...}
        self.st.record_sync_error("UNAUTHORIZED", now=NOW)
        err_payload = self.st.get_channels_payload(now=NOW)
        self.assertEqual(err_payload.get("status"), "error")
        self.assertEqual(err_payload.get("error"), "UNAUTHORIZED")

        # Non-OK upsert_channels also records sync error
        self.st.upsert_channels({"status": "FORBIDDEN"}, now=NOW + 5)
        self.assertEqual(self.st.get_channels_payload(now=NOW + 5).get("error"), "FORBIDDEN")

        # 3. Full sync populates categories, channels, inline EPG, updated_at, and clears sync_error
        full_doc = {
            "status": "OK",
            "categories": [
                {"id": 29, "caption": "Розваги", "order": 2},
                {"id": 1000, "caption": "Усі", "order": 1},
            ],
            "list": [
                {
                    "id": 10,
                    "name": "FAST Кіно HD",
                    "number": 4,
                    "icon_v2_url": "https://img.example/10-v2.webp",
                    "icon_url": "https://img.example/10.png",
                    "banner_url": "https://img.example/10-banner.jpg",
                    "category": [29, 1000],
                    "catchup": True,
                    "catchup_duration": 7,
                    "epg_days_future": 5,
                    "available": True,
                    "is_fast_channel": True,
                    "epg": [
                        {
                            "id": 1001,
                            "text": "Вечірнє кіно",
                            "description": "Опис ефіру",
                            "time_start": NOW - 600,
                            "time_stop": NOW + 1200,
                            "available": True,
                            "tv_show_id": 55,
                            "season_number": 2,
                            "episode_number": 8,
                            "preview_url": "https://img.example/1001.jpg",
                        }
                    ],
                },
                {
                    "id": 11,
                    "name": "Тимчасовий Канал",
                    "number": 9,
                    "category": [1000],
                    "catchup": False,
                    "available": True,
                },
            ],
        }
        count = self.st.upsert_channels(full_doc, now=NOW + 10)
        self.assertEqual(count, 2)

        payload = self.st.get_channels_payload(now=NOW + 10)
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["updated_at"], NOW + 10)
        self.assertEqual(payload["sync_error"], "")
        self.assertEqual([c["id"] for c in payload["categories"]], [1000, 29])
        by_id = {int(c["id"]): c for c in payload["list"]}
        self.assertEqual(set(by_id.keys()), {10, 11})
        ch10 = by_id[10]
        self.assertEqual(ch10["banner_url"], "https://img.example/10-banner.jpg")
        self.assertEqual(ch10["category"], [29, 1000])
        self.assertEqual(ch10["epg_days_future"], 5)
        self.assertTrue(ch10["is_fast_channel"])
        self.assertTrue(ch10["catchup"])
        self.assertEqual(len(ch10["epg"]), 1)
        epg0 = ch10["epg"][0]
        for k in ("id", "text", "description", "time_start", "time_stop", "available",
                  "tv_show_id", "season_number", "episode_number", "preview_url"):
            self.assertIn(k, epg0, k)
        self.assertEqual((epg0["description"], epg0["season_number"], epg0["episode_number"]), ("Опис ефіру", 2, 8))

        # 4. Transient sync error AFTER successful sync keeps cached channels & sets sync_error
        self.st.upsert_channels({"status": "SERVICE_UNAVAILABLE"}, now=NOW + 20)
        after_err = self.st.get_channels_payload(now=NOW + 20)
        self.assertEqual(after_err["status"], "OK")
        self.assertEqual(len(after_err["list"]), 2)
        self.assertEqual(after_err["updated_at"], NOW + 10)
        self.assertEqual(after_err["sync_error"], "SERVICE_UNAVAILABLE")

        # 5. Atomic reconciliation: channel 11 removed from account is deleted on next full sync
        reduced_doc = {
            "status": "OK",
            "categories": [{"id": 1000, "caption": "Усі", "order": 1}],
            "list": [full_doc["list"][0]],
        }
        self.assertEqual(self.st.upsert_channels(reduced_doc, now=NOW + 60), 1)
        reconciled = self.st.get_channels_payload(now=NOW + 60)
        self.assertEqual([int(c["id"]) for c in reconciled["list"]], [10])
        self.assertEqual(reconciled["updated_at"], NOW + 60)
        self.assertEqual(reconciled["sync_error"], "")
        self.assertEqual(self.st.search_channels("тимчасовий", available_only=False), [])

    def test_channels_and_search(self):
        count = self.st.upsert_channels({
            "status": "OK",
            "list": [
                {"id": 10, "name": "Новый Канал HD", "number": 4, "catchup": True, "catchup_duration": 7, "available": True},
                {"id": 11, "name": "Новый Закрытый", "number": 99, "catchup": False, "available": False},
            ],
        }, now=NOW)
        self.assertEqual(count, 2)
        found = self.st.search_channels("новый", available_only=True)
        self.assertEqual([c["cid"] for c in found], ["10"])
        all_found = self.st.search_channels("новый", available_only=False)
        self.assertEqual([c["cid"] for c in all_found], ["10", "11"])

    def test_epg_channel_day_and_recall_programme(self):
        self.st.upsert_channels({
            "status": "OK",
            "list": [{"id": 5, "name": "Первый", "catchup": True, "catchup_duration": 7, "available": True}],
        }, now=NOW)
        self.st.upsert_epg("5", [
            {"id": 501, "text": "Премьера. Утро", "description": "Ранкове шоу",
             "time_start": NOW - 3600, "time_stop": NOW - 1800, "available": True,
             "tv_show_id": 42, "season_number": 1, "episode_number": 3, "preview_url": "https://img.example/501.jpg"},
            {"id": 502, "text": "Сейчас", "time_start": NOW - 600, "time_stop": NOW + 600, "available": True},
            {"id": 503, "text": "Ввечері", "time_start": NOW + 600, "time_stop": NOW + 2400, "available": True},
        ], now=NOW)
        day_key = _local_day_key(NOW - 3600)
        rows = self.st.channel_day("5", day_key, now=NOW)
        by_epg = {r["epg"]: r for r in rows}
        self.assertTrue({"501", "502"}.issubset(by_epg.keys()))

        required_day_keys = {
            "epg", "cid", "title", "description", "start", "stop",
            "can_archive", "playable_in_archive", "live", "playable",
            "available", "preview", "season", "episode", "show_id",
        }
        for r in rows:
            self.assertTrue(required_day_keys.issubset(r.keys()), set(r.keys()))
            self.assertEqual(r["can_archive"], r["playable_in_archive"])

        self.assertEqual((by_epg["501"]["can_archive"], by_epg["501"]["live"], by_epg["501"]["playable"]), (True, False, True))
        self.assertEqual((by_epg["501"]["season"], by_epg["501"]["episode"], by_epg["501"]["show_id"]), (1, 3, "42"))
        self.assertEqual((by_epg["502"]["can_archive"], by_epg["502"]["live"], by_epg["502"]["playable"]), (True, True, True))
        if "503" in by_epg:
            self.assertEqual((by_epg["503"]["can_archive"], by_epg["503"]["live"], by_epg["503"]["playable"]), (False, False, False))

        rec = self.st.recall_programme("501", cid="5", now=NOW)
        self.assertIsNotNone(rec)
        expected_recall_keys = {
            "cid", "epg", "title", "description", "time_start", "time_stop",
            "start", "stop", "available", "can_archive", "channel_name",
        }
        self.assertTrue(expected_recall_keys.issubset(rec.keys()), set(rec.keys()))
        self.assertEqual((rec["cid"], rec["epg"], rec["channel_name"]), ("5", "501", "Первый"))
        self.assertEqual((rec["start"], rec["stop"]), (NOW - 3600, NOW - 1800))
        self.assertEqual((rec["time_start"], rec["time_stop"]), (NOW - 3600, NOW - 1800))
        self.assertTrue(rec["can_archive"])

        # Adjacent negative cases: wrong cid or unknown epg_id returns None
        self.assertIsNone(self.st.recall_programme("501", cid="999", now=NOW))
        self.assertIsNone(self.st.recall_programme("999999", now=NOW))

    def test_programme_at_slot_boundaries_and_adjacent_programmes(self):
        for method in ("programme_at", "adjacent_programmes"):
            self.assertTrue(
                callable(getattr(self.st, method, None)),
                f"SweetStore must define {method}()",
            )
        self.st.upsert_channels({
            "status": "OK",
            "list": [
                {"id": 5, "name": "Ch5", "catchup": True, "catchup_duration": 7, "available": True},
                {"id": 6, "name": "Ch6", "catchup": True, "catchup_duration": 7, "available": True},
            ],
        }, now=NOW)
        self.st.upsert_epg("5", [
            {"id": 101, "text": "Slot 1", "time_start": 1000, "time_stop": 2000, "available": True},
            {"id": 102, "text": "Slot 2", "time_start": 2000, "time_stop": 3500, "available": True},
            {"id": 103, "text": "Slot 3", "time_start": 3500, "time_stop": 5000, "available": True},
        ], now=NOW)
        self.st.upsert_epg("6", [
            {"id": 201, "text": "Other Ch", "time_start": 500, "time_stop": 6000, "available": True},
        ], now=NOW)

        # Slot boundary invariants: time_start <= int(wall_ts) < time_stop
        self.assertIsNone(self.st.programme_at("5", 999))
        p_start = self.st.programme_at("5", 1000)
        self.assertEqual((p_start["epg"], p_start["offset"]), ("101", 0))
        p_end_minus_eps = self.st.programme_at("5", 1999.9)
        self.assertEqual((p_end_minus_eps["epg"], p_end_minus_eps["offset"]), ("101", 999))
        p_exact_boundary = self.st.programme_at("5", 2000)
        self.assertEqual((p_exact_boundary["epg"], p_exact_boundary["offset"]), ("102", 0))
        self.assertIsNone(self.st.programme_at("5", 5000))
        self.assertIsNone(self.st.programme_at("999", 2000))

        # adjacent_programmes(cid, epg_id) -> (prev_prog, next_prog) isolated per channel
        prev1, next1 = self.st.adjacent_programmes("5", "101")
        self.assertIsNone(prev1)
        self.assertEqual(next1["epg"], "102")

        prev2, next2 = self.st.adjacent_programmes("5", "102")
        self.assertEqual((prev2["epg"], next2["epg"]), ("101", "103"))

        prev3, next3 = self.st.adjacent_programmes("5", "103")
        self.assertEqual(prev3["epg"], "102")
        self.assertIsNone(next3)

        self.assertEqual(self.st.adjacent_programmes("5", "999"), (None, None))
        self.assertEqual(self.st.adjacent_programmes("6", "102"), (None, None))

    def test_title_detail_roundtrip_reconstructs_sorted_seasons_and_episodes(self):
        ret = self.st.upsert_title_detail({
            "ok": True,
            "id": "vod:42",
            "title": "Тест Серіал",
            "description": "Описание сериала",
            "age_rating": "16+",
            "genres": [1, 12],
            "genre_names": ["Сериалы", "Комедия"],
            "countries": ["Украина"],
            "seasons": [
                {
                    "id": 2,
                    "number": 2,
                    "title": "Сезон 2",
                    "episodes": [
                        {"id": 202, "number": 2, "title": "S2E2", "duration": 1800},
                        {"id": 201, "number": 1, "title": "S2E1", "duration": 1750},
                    ],
                },
                {
                    "id": 1,
                    "number": 1,
                    "title": "Сезон 1",
                    "episodes": [
                        {"id": 103, "number": 3, "title": "S1E3", "duration": 1900},
                        {"id": 101, "number": 1, "title": "S1E1", "duration": 1800},
                        {"id": 102, "number": 2, "title": "S1E2", "duration": 1850},
                    ],
                },
            ],
        }, now=NOW)
        self.assertIsNone(ret)

        got = self.st.get_title_detail("vod:42")
        self.assertIsNotNone(got)
        self.assertEqual(got["description"], "Описание сериала")
        self.assertEqual(got["age_rating"], "16+")
        self.assertEqual(got["genres"], [1, 12])
        self.assertEqual(got["countries"], ["Украина"])
        self.assertIn("seasons", got)
        self.assertEqual([s["number"] for s in got["seasons"]], [1, 2])
        self.assertEqual([e["number"] for e in got["seasons"][0]["episodes"]], [1, 2, 3])
        self.assertEqual([e["title"] for e in got["seasons"][0]["episodes"]], ["S1E1", "S1E2", "S1E3"])
        self.assertEqual([e["number"] for e in got["seasons"][1]["episodes"]], [1, 2])
        self.assertIsNone(self.st.get_title_detail("vod:missing"))

    def test_swr_cache_fresh_stale_and_expired(self):
        for method in ("put_swr", "get_swr"):
            self.assertTrue(
                callable(getattr(self.st, method, None)),
                f"SweetStore must define {method}()",
            )
        self.assertIsNone(self.st.get_swr("shows:uk", max_age_s=3600, now=NOW))
        sample = {"items": [{"id": "vod:9558", "title": "Зрадники"}]}
        self.st.put_swr("shows:uk", sample, ttl_s=300, now=NOW)

        data_fresh, stale_fresh = _unpack_swr_hit(self, self.st.get_swr("shows:uk", max_age_s=3600, now=NOW + 300))
        self.assertEqual(data_fresh, sample)
        self.assertFalse(stale_fresh)

        data_stale, stale_flag = _unpack_swr_hit(self, self.st.get_swr("shows:uk", max_age_s=3600, now=NOW + 301))
        self.assertEqual(data_stale, sample)
        self.assertTrue(stale_flag)

        self.assertIsNone(self.st.get_swr("shows:uk", max_age_s=3600, now=NOW + 3601))

    def test_seed_from_channel_file_and_clear_on_signout(self):
        for method in ("seed_from_channel_file", "clear"):
            self.assertTrue(
                callable(getattr(self.st, method, None)),
                f"SweetStore must define {method}()",
            )
        missing_path = os.path.join(self.tmp.name, "missing.json")
        self.assertFalse(self.st.seed_from_channel_file(missing_path, now=NOW))

        seed_path = os.path.join(self.tmp.name, "channelList.json")
        with open(seed_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "OK",
                "categories": [{"id": 1, "caption": "News"}],
                "list": [{"id": 7, "name": "Seeded Ch", "available": True, "category": [1]}],
            }, f)
        self.assertTrue(self.st.seed_from_channel_file(seed_path, now=NOW))
        self.assertEqual([int(c["id"]) for c in self.st.get_channels_payload(now=NOW)["list"]], [7])

        # Does NOT overwrite when channels table is already non-empty
        other_path = os.path.join(self.tmp.name, "other.json")
        with open(other_path, "w", encoding="utf-8") as f:
            json.dump({"status": "OK", "list": [{"id": 99, "name": "Other", "available": True}]}, f)
        self.assertFalse(self.st.seed_from_channel_file(other_path, now=NOW + 10))
        self.assertEqual([int(c["id"]) for c in self.st.get_channels_payload(now=NOW + 10)["list"]], [7])

        # Populate remaining tables and verify clear() wipes everything on sign-out
        self.st.upsert_epg("7", [{"id": 70, "text": "News", "time_start": NOW - 600, "time_stop": NOW + 600}], now=NOW)
        self.st.upsert_title_detail({"ok": True, "id": "vod:7", "title": "Movie"}, now=NOW)
        self.st.put_swr("k", {"v": 1}, ttl_s=300, now=NOW)

        self.st.clear()
        self.assertEqual(self.st.get_channels_payload(now=NOW), {})
        self.assertIsNone(self.st.get_title_detail("vod:7"))
        self.assertIsNone(self.st.recall_programme("70", now=NOW))
        self.assertIsNone(self.st.get_swr("k", now=NOW))
        self.assertEqual(self.st.search_channels("seeded", available_only=False), [])

        with sqlite3.connect(self.db_path) as con:
            for tbl in ("meta", "channel_categories", "channels", "programmes",
                        "titles", "episodes", "collections", "search_index", "swr_cache"):
                cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                self.assertEqual(cnt, 0, f"Table {tbl} not wiped by clear()")


if __name__ == "__main__":
    unittest.main()
