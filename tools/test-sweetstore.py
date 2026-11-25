#!/usr/bin/env python3
"""Offline tests for mediastick_sweetstore.py."""
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
sys.path.insert(0, LIB)

import mediastick_sweetstore as store  # noqa: E402


class TestSweetStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "catalog.db")
        self.st = store.SweetStore(self.db_path)

    def tearDown(self):
        self.st.close()
        self.tmp.cleanup()

    def test_strip_programme_prefix(self):
        self.assertEqual(store.strip_programme_prefix('Премьера. Х/ф "Любовь"'), "Любовь")
        self.assertEqual(store.strip_programme_prefix("Прем'єра. Т/с Следствие"), "Следствие")
        self.assertEqual(store.strip_programme_prefix("Обычное шоу"), "Обычное шоу")

    def test_channels_and_search(self):
        now = 1_800_000_000
        count = self.st.upsert_channels({
            "list": [
                {"id": 10, "name": "Новый Канал HD", "number": 4, "catchup": True, "catchup_duration": 7, "available": True},
                {"id": 11, "name": "Новый Закрытый", "number": 99, "catchup": False, "available": False},
            ]
        }, now=now)
        self.assertEqual(count, 2)
        found = self.st.search_channels("новый", available_only=True)
        self.assertEqual([c["cid"] for c in found], ["10"])
        all_found = self.st.search_channels("новый", available_only=False)
        self.assertEqual([c["cid"] for c in all_found], ["10", "11"])

    def test_epg_channel_day_and_recall(self):
        now = 1_800_000_000
        self.st.upsert_channels({
            "list": [{"id": 5, "name": "Первый", "catchup": True, "catchup_duration": 7, "available": True}]
        }, now=now)
        self.st.upsert_epg("5", [
            {"id": 501, "text": "Премьера. Утро", "time_start": now - 3600, "time_stop": now - 1800, "available": True},
            {"id": 502, "text": "Сейчас", "time_start": now - 600, "time_stop": now + 600, "available": True},
        ], now=now)
        day_key = store._day_key(now - 3600)
        rows = self.st.channel_day("5", day_key, now=now)
        self.assertEqual([r["epg"] for r in rows], ["501", "502"])
        self.assertTrue(all(r["can_archive"] and r["playable_in_archive"] and r["archive"] for r in rows))
        rec = self.st.recall_programme("501")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["base_title"], "Утро")

    def test_title_detail_roundtrip(self):
        ok = self.st.upsert_title_detail({
            "ok": True,
            "id": "vod:42",
            "title": "Тест",
            "description": "Описание фильма",
            "age_rating": "16+",
            "genres": [1, 2],
            "countries": ["Украина"],
            "seasons": [{"number": 1, "episodes": [{"id": 100, "number": 1, "title": "1 серия"}]}],
        })
        self.assertTrue(ok)
        got = self.st.get_title_detail("vod:42")
        self.assertEqual(got["description"], "Описание фильма")
        self.assertEqual(got["age_rating"], "16+")
        self.assertEqual(got["seasons_count"], 1)


if __name__ == "__main__":
    unittest.main()
