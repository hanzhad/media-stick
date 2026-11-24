#!/usr/bin/env python3
"""Offline test of the shared page cache (no Kodi, no device): python3 tools/test-page-cache.py

page_cache needs no Kodi (its folder is a temp directory here); time is passed in as `now`."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
sys.path.insert(0, ADDON)

from resources.lib import page_cache as pc  # noqa: E402

NOW = 1_800_000_000.0
NS = "youtube:7"


def entries(n=3):
    """What a YouTube screen keeps for a page: the cards as rows (titles, addresses, picture addresses)."""
    return {"entries": [["video", f"plugin://plugin.video.youtube/play/?video_id=v{i}", f"Title {i}", "Channel", 61,
                         f"https://i.ytimg.com/vi/v{i}/hq.jpg", "", 0, 0, False, 0, 0.0] for i in range(n)], "more": ""}


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patch = mock.patch.object(pc, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        pc._memo.clear()

    def files(self):
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def file_of(self, namespace=NS):
        return pc._path(namespace)

    def text(self, namespace=NS):
        with open(self.file_of(namespace), encoding="utf-8") as f:
            return f.read()


class PutGet(Case):
    def test_what_is_put_comes_back_with_its_age(self):
        self.assertTrue(pc.put(NS, "rec", entries(), now=NOW))
        hit = pc.get(NS, "rec", now=NOW + 12)
        self.assertEqual((hit.value, hit.age_s, hit.stale), (entries(), 12, False))
        self.assertIsNone(pc.get(NS, "other", now=NOW))
        self.assertIsNone(pc.get("youtube:8", "rec", now=NOW))              # another namespace: another file

    def test_a_page_older_than_the_ttl_is_returned_stale_and_older_than_max_age_not_at_all(self):
        pc.put(NS, "rec", {"a": 1}, now=NOW)
        self.assertFalse(pc.get(NS, "rec", ttl=300, now=NOW + 299).stale)
        self.assertTrue(pc.get(NS, "rec", ttl=300, now=NOW + 300).stale)
        self.assertEqual(pc.get(NS, "rec", ttl=300, now=NOW + 3600).age_s, 3600)
        self.assertIsNotNone(pc.get(NS, "rec", max_age=pc.DEFAULT_MAX_AGE, now=NOW + pc.DEFAULT_MAX_AGE))
        self.assertIsNone(pc.get(NS, "rec", max_age=pc.DEFAULT_MAX_AGE, now=NOW + pc.DEFAULT_MAX_AGE + 1))
        self.assertIsNone(pc.get(NS, "rec", max_age=60, now=NOW + 61))
        self.assertEqual(pc.DEFAULT_MAX_AGE, 24 * 3600)

    def test_a_page_written_in_the_future_is_stale_not_lost(self):
        pc.put(NS, "rec", {"a": 1}, now=NOW + 5000)                           # the clock went back
        hit = pc.get(NS, "rec", now=NOW)
        self.assertEqual((hit.age_s, hit.stale), (0, True))

    def test_fresh_says_whether_there_is_nothing_to_fetch(self):
        pc.put(NS, "rec", {"a": 1}, now=NOW)
        self.assertTrue(pc.fresh(NS, "rec", 300, now=NOW + 10))
        self.assertFalse(pc.fresh(NS, "rec", 300, now=NOW + 400))
        self.assertFalse(pc.fresh(NS, "gone", 300, now=NOW))

    def test_a_second_put_replaces_and_the_value_is_a_copy(self):
        pc.put(NS, "rec", {"a": [1]}, now=NOW)
        pc.get(NS, "rec", now=NOW).value["a"].append(2)                       # the caller changes what it got
        self.assertEqual(pc.get(NS, "rec", now=NOW).value, {"a": [1]})
        pc.put(NS, "rec", {"a": [3]}, now=NOW + 1)
        self.assertEqual(pc.get(NS, "rec", now=NOW + 1).value, {"a": [3]})

    def test_the_value_is_what_a_file_gives_back(self):
        pc.put(NS, "rec", {"t": (1, 2), "s": "Привіт"}, now=NOW)
        self.assertEqual(pc.get(NS, "rec", now=NOW).value, {"t": [1, 2], "s": "Привіт"})
        pc._memo.clear()                                                    # and the same from the disk
        self.assertEqual(pc.get(NS, "rec", now=NOW).value, {"t": [1, 2], "s": "Привіт"})

    def test_a_page_survives_a_restart(self):
        pc.put(NS, "rec", entries(), now=NOW)
        pc._memo.clear()                                                    # a new process knows nothing
        self.assertEqual(pc.get(NS, "rec", now=NOW + 1).value, entries())

    def test_remove_forgets_one_page(self):
        pc.put(NS, "a", 1, now=NOW)
        pc.put(NS, "b", 2, now=NOW)
        pc.remove(NS, "a")
        self.assertEqual((pc.get(NS, "a", now=NOW), pc.get(NS, "b", now=NOW).value), (None, 2))
        pc.remove(NS, "never")
        pc.remove("nobody:1", "x")


class Refused(Case):
    def test_what_is_not_json_is_refused_and_nothing_is_written(self):
        for value in (object(), {1, 2}, {"a": float("nan")}, {"a": float("inf")}, {"a": b"bytes"}, {(1, 2): 3}):
            self.assertFalse(pc.put(NS, "k", value, now=NOW), value)
        self.assertEqual(self.files(), [])

    def test_bad_names_are_refused(self):
        for namespace, key in (("", "k"), (None, "k"), (5, "k"), ("x" * 200, "k"), ("a\nb", "k"), (NS, ""), (NS, None), (NS, "k" * 401)):
            self.assertFalse(pc.put(namespace, key, 1, now=NOW), (namespace, key))
            self.assertIsNone(pc.get(namespace, key, now=NOW))
        self.assertEqual(self.files(), [])
        self.assertTrue(pc.put("sweettv:me@example.org", "k" * 400, 1, now=NOW))        # an account name may be an address

    def test_a_value_with_a_credential_is_refused(self):
        for value in ({"access_token": "x"}, {"a": {"Refresh_Token": "x"}}, [{"client_secret": "x"}], {"api_key": "x"},
                      {"headers": {"Authorization": "Bearer abc"}}, {"cookie": "x"}, {"password": "x"}, {"u": "https://x/?access_token=abc"},
                      {"u": "Bearer abcdef"}, {"u": "ya29.a0AfH6SMB"}, {"u": "https://x/?api_key=1"}, {"s": ["fine", {"session_id": "1"}]}):
            self.assertFalse(pc.put(NS, "k", value, now=NOW), value)
        deep = cur = {}
        for _ in range(30):
            cur["n"] = cur = {}
        self.assertFalse(pc.put(NS, "k", deep, now=NOW))                    # pages are flat
        self.assertEqual(self.files(), [])

    def test_a_page_of_entries_has_no_credential_on_disk(self):
        page = entries(40)
        page["entries"][0][2] = "How to get an API key and a token"           # words in a title are not credentials
        self.assertTrue(pc.put(NS, "rec", page, now=NOW))
        text = self.text()
        for word in ("access_token", "refresh_token", "client_secret", "Bearer", "ya29", "password="):
            self.assertNotIn(word, text)
        self.assertEqual(json.loads(text)["items"]["rec"]["v"], page)

    def test_a_page_too_big_for_a_file_is_refused_and_the_others_stay(self):
        pc.put(NS, "small", {"a": 1}, now=NOW)
        self.assertFalse(pc.put(NS, "huge", {"blob": "x" * (pc.MAX_FILE_BYTES + 10)}, now=NOW + 1))
        self.assertEqual(pc.get(NS, "small", now=NOW).value, {"a": 1})
        self.assertIsNone(pc.get(NS, "huge", now=NOW))


class Caps(Case):
    def test_at_most_forty_pages_for_a_namespace_the_oldest_go_first(self):
        for i in range(pc.MAX_ENTRIES + 5):
            pc.put(NS, f"k{i}", {"i": i}, now=NOW + i)
        found = [i for i in range(pc.MAX_ENTRIES + 5) if pc.get(NS, f"k{i}", max_age=1e9, now=NOW + 100)]
        self.assertEqual((len(found), found[0], found[-1]), (pc.MAX_ENTRIES, 5, pc.MAX_ENTRIES + 4))
        doc = json.loads(self.text())
        self.assertEqual(len(doc["items"]), pc.MAX_ENTRIES)

    def test_a_put_of_an_old_key_keeps_it_young_and_is_not_the_one_dropped(self):
        for i in range(pc.MAX_ENTRIES):
            pc.put(NS, f"k{i}", i, now=NOW + i)
        pc.put(NS, "k0", "again", now=NOW + 100)
        pc.put(NS, "new", 1, now=NOW + 101)
        self.assertEqual(pc.get(NS, "k0", max_age=1e9, now=NOW + 102).value, "again")
        self.assertIsNone(pc.get(NS, "k1", max_age=1e9, now=NOW + 102))

    def test_a_file_stays_below_its_size_cap_by_dropping_the_oldest_pages(self):
        chunk = "x" * 100_000
        for i in range(10):
            self.assertTrue(pc.put(NS, f"k{i}", {"blob": chunk}, now=NOW + i))
        self.assertLessEqual(os.path.getsize(self.file_of()), pc.MAX_FILE_BYTES)
        self.assertIsNotNone(pc.get(NS, "k9", max_age=1e9, now=NOW + 20))             # the newest is kept
        self.assertIsNone(pc.get(NS, "k0", max_age=1e9, now=NOW + 20))

    def test_the_folder_stays_below_its_total_the_file_untouched_longest_goes_first(self):
        chunk = "x" * 400_000
        with mock.patch.object(pc, "MAX_TOTAL_BYTES", 1_000_000):
            for i in range(4):
                pc.put(f"app:{i}", "k", {"blob": chunk}, now=NOW + i)
                os.utime(self.file_of(f"app:{i}"), (NOW + i, NOW + i))
        size = sum(os.path.getsize(os.path.join(self.dir, name)) for name in self.files())
        self.assertLessEqual(size, 1_000_000)
        self.assertIsNotNone(pc.get("app:3", "k", max_age=1e9, now=NOW + 10))
        self.assertIsNone(pc.get("app:0", "k", max_age=1e9, now=NOW + 10))

    def test_a_leftover_temp_file_is_swept_when_old(self):
        os.makedirs(self.dir, exist_ok=True)
        old, young = os.path.join(self.dir, "old.tmp"), os.path.join(self.dir, "young.tmp")
        for path in (old, young):
            open(path, "w").close()
        os.utime(old, (1, 1))
        pc.put(NS, "k", 1, now=NOW)
        self.assertEqual([name for name in self.files() if name.endswith(".tmp")], ["young.tmp"])


class Damage(Case):
    def test_a_corrupt_or_foreign_file_is_an_empty_cache_and_is_written_over(self):
        pc.put(NS, "k", 1, now=NOW)
        path = self.file_of()
        for content in ("{not json", "", "[]", "null", '{"v": 1}', '{"v": 2, "ns": "youtube:7", "items": {}}',
                        json.dumps({"v": 1, "ns": "someone:else", "items": {"k": {"t": NOW, "v": 1}}}),
                        json.dumps({"v": 1, "ns": NS, "items": {"k": 5, "j": {"t": "x", "v": 1}, "i": {"t": NOW}}}), "\x00\xff garbage"):
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)
            pc._memo.clear()
            self.assertIsNone(pc.get(NS, "k", now=NOW), content)
            self.assertTrue(pc.put(NS, "k", 2, now=NOW), content)
            self.assertEqual(pc.get(NS, "k", now=NOW).value, 2)

    def test_a_damaged_item_does_not_take_the_good_ones_with_it(self):
        with open(self.file_of(), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "ns": NS, "items": {"good": {"t": NOW, "v": [1]}, "bad": 5, "nan": {"t": "now", "v": 1}}}, f)
        self.assertEqual(pc.get(NS, "good", now=NOW).value, [1])
        self.assertIsNone(pc.get(NS, "bad", now=NOW))

    def test_a_file_that_changed_on_disk_is_read_again(self):
        pc.put(NS, "k", 1, now=NOW)
        pc.get(NS, "k", now=NOW)
        with open(self.file_of(), "w", encoding="utf-8") as f:                     # another process wrote it
            json.dump({"v": 1, "ns": NS, "items": {"k": {"t": NOW, "v": "other process"}}}, f)
        self.assertEqual(pc.get(NS, "k", now=NOW).value, "other process")
        os.unlink(self.file_of())
        self.assertIsNone(pc.get(NS, "k", now=NOW))

    def test_nothing_raises_when_the_folder_cannot_be_used(self):
        blocker = os.path.join(self.dir, "blocker")
        open(blocker, "w").close()
        with mock.patch.object(pc, "DIR", os.path.join(blocker, "inside")):         # a file where the folder should be
            self.assertFalse(pc.put(NS, "k", 1, now=NOW))
            self.assertIsNone(pc.get(NS, "k", now=NOW))
            pc.drop(NS)
            pc.drop_service("youtube")
            pc.remove(NS, "k")
        with mock.patch.object(pc, "directory", side_effect=RuntimeError("no kodi")):
            self.assertIsNone(pc.get(NS, "k", now=NOW))
            self.assertFalse(pc.put(NS, "k", 1, now=NOW))
            pc.drop(NS)
            pc.drop_service("youtube")
        self.assertIsNone(pc.get(None, None))

    def test_a_write_that_fails_leaves_the_old_file_and_no_temp_file(self):
        pc.put(NS, "k", "old", now=NOW)
        with mock.patch.object(pc.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(pc.put(NS, "k", "new", now=NOW + 1))
        self.assertEqual(pc.get(NS, "k", now=NOW + 1).value, "old")
        pc._memo.clear()
        self.assertEqual(pc.get(NS, "k", now=NOW + 1).value, "old")
        self.assertEqual([name for name in self.files() if name.endswith(".tmp")], [])

    def test_a_file_is_written_whole_into_place(self):
        calls = []
        real = os.replace
        with mock.patch.object(pc.os, "replace", side_effect=lambda a, b: calls.append((a, b)) or real(a, b)):
            pc.put(NS, "k", 1, now=NOW)
        (tmp, final), = calls
        self.assertTrue(tmp.endswith(".tmp") and final == self.file_of() and os.path.dirname(tmp) == self.dir)
        self.assertEqual(self.files(), [os.path.basename(final)])


class Dropping(Case):
    def test_drop_forgets_a_namespace_and_no_other(self):
        pc.put("youtube:1", "k", 1, now=NOW)
        pc.put("youtube:2", "k", 2, now=NOW)
        pc.drop("youtube:1")
        self.assertIsNone(pc.get("youtube:1", "k", now=NOW))
        self.assertEqual(pc.get("youtube:2", "k", now=NOW).value, 2)
        pc.drop("youtube:1")
        pc.drop(None)

    def test_drop_service_forgets_every_namespace_of_an_app_and_not_the_others(self):
        for ns in ("youtube:1", "youtube:2", "youtube:anon", "sweettv:me", "youtubers:x"):
            pc.put(ns, "k", ns, now=NOW)
        pc.drop_service("youtube")
        self.assertEqual([pc.get(ns, "k", now=NOW) is not None for ns in ("youtube:1", "youtube:2", "youtube:anon", "sweettv:me", "youtubers:x")],
                         [False, False, False, True, True])

    def test_drop_service_removes_an_unreadable_file_of_the_app_by_its_name(self):
        pc.put("youtube:1", "k", 1, now=NOW)
        with open(self.file_of("youtube:1"), "w") as f:
            f.write("{broken")
        pc.put("sweettv:me", "k", 1, now=NOW)
        pc.drop_service("youtube")
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(pc.get("sweettv:me", "k", now=NOW).value, 1)

    def test_the_cache_lives_where_the_addon_keeps_its_data(self):
        self.assertEqual(pc.CACHE_DIR, "special://profile/addon_data/script.media-stick.home/cache/")
        with mock.patch.object(pc, "DIR", None):
            import types
            vfs = types.ModuleType("xbmcvfs")
            vfs.translatePath = lambda path: "/translated/" + path
            with mock.patch.dict(sys.modules, {"xbmcvfs": vfs}):
                self.assertEqual(pc.directory(), "/translated/" + pc.CACHE_DIR)


class Threads(Case):
    def test_writers_in_many_threads_leave_a_whole_file(self):
        import threading
        errors = []

        def work(n):
            try:
                for i in range(25):
                    pc.put(NS, f"k{n}-{i}", {"n": n, "i": i}, now=NOW + i)
                    pc.get(NS, f"k{n}-{i}", max_age=1e9, now=NOW + 100)
            except Exception as e:                                       # nothing may raise
                errors.append(e)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        pc._memo.clear()
        doc = json.loads(self.text())
        self.assertEqual(len(doc["items"]), pc.MAX_ENTRIES)
        self.assertEqual([name for name in self.files() if name.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
