#!/usr/bin/env python3
"""Offline test of «remember where I stopped, on the device» (no Kodi, no device, no network): python3 tools/test-resume.py

The library (mediastick_resume: the choice, the positions file, what a played path is), the recorder in the home add-on's
service (samples in, throttled writes out), and each place that offers to continue: the YouTube app of the TV, the phone's
«Смотреть», the SWEET.TV app's state and the phone's programme sheet. Each place is tested with the choice off (it reads
what it always read) and on (only what the stick saved)."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
ADDON_LIB = os.path.join(ADDON, "resources", "lib")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
TMP = tempfile.mkdtemp()
for name, folder in (("SIGNIN", "signin"), ("ONBOARDING", "onboarding"), ("PREFS", "prefs"), ("RESUME", "resume"),
                     ("SWEETNOW", "now")):
    os.environ["MEDIASTICK_%s_DIR" % name] = os.path.join(TMP, folder)
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_ADDON_LIB"] = ADDON_LIB
BLOCKER = os.path.join(TMP, "blocker")            # a file where a directory is wanted: every write under it fails
with open(BLOCKER, "w", encoding="utf-8") as _f:
    _f.write("x")


class State:
    """What the stubbed Kodi player does."""
    playing, file, label, time, total = True, "", "", 0.0, 0.0
    seeks, rpc, logs = [], [], []
    answers = {}


class Player:
    def isPlayingVideo(self):
        return State.playing

    def getPlayingFile(self):
        if not State.file:
            raise RuntimeError("nothing plays")
        return State.file

    def getTime(self):
        return State.time

    def getTotalTime(self):
        return State.total

    def seekTime(self, seconds):
        State.seeks.append(seconds)


class Monitor:
    def waitForAbort(self, wait=0):
        time.sleep(0.01)
        return False


def executeJSONRPC(text):
    request = json.loads(text)
    State.rpc.append(request)
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": State.answers.get(request["method"], {})})


xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda text, level=0: State.logs.append(text)
xbmc.getInfoLabel = lambda label: State.label
xbmc.executeJSONRPC = executeJSONRPC
xbmc.Player, xbmc.Monitor = Player, Monitor
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda path: path.replace("special://temp", os.path.join(TMP, "temp"))
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=mock.MagicMock(), xbmcaddon=mock.MagicMock())
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

import mediastick_resume as mr  # noqa: E402
import panel_sweettv as ps  # noqa: E402
import panel_watch as pw  # noqa: E402
from resources.lib import resume_recorder, store, sweettv_files, sweettv_state as saved, sweettv_text, youtube_files  # noqa: E402

YT = "plugin://plugin.video.youtube/"
VID, VID2 = YT + "play/?video_id=abcdefghijk", YT + "play/?video_id=zzzzzzzzzzz"
LIVE, ARCHIVE = "plugin://plugin.video.sweettv/playvid/5|null", "plugin://plugin.video.sweettv/playvid/5|50?ms_start=30"
NOW = 1_800_000_000
PROGRAMME = {"title": "Утро", "start": NOW - 7200, "stop": NOW - 3600}
LIST = {"status": "OK", "list": [
    {"id": 5, "name": "Первый канал", "catchup": True, "catchup_duration": 7, "available": True, "epg": [
        {"id": 50, "time_start": NOW - 7200, "time_stop": NOW - 3600, "text": "Утро", "available": True},
        {"id": 51, "time_start": NOW - 3600, "time_stop": NOW + 3600, "text": "Холостяк", "available": True}]}]}


def clean_dirs():
    for folder in (mr.PREFS, mr.DIR, os.environ["MEDIASTICK_SWEETNOW_DIR"]):
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                os.unlink(os.path.join(folder, name))


class Base(unittest.TestCase):
    def setUp(self):
        clean_dirs()
        State.playing, State.file, State.label, State.time, State.total = True, "", "", 0.0, 0.0
        State.seeks, State.rpc, State.logs, State.answers = [], [], [], {}
        self.addCleanup(clean_dirs)

    def on(self, positions=None):
        if positions is not None:
            self.assertTrue(mr.save(positions))

    @staticmethod
    def placed(*rows):
        """A positions document with (file, pos, total) rows recorded one second apart."""
        data = mr.empty()
        for i, (file, pos, total) in enumerate(rows):
            data = mr.record(data, file, pos, total, 1000 + i, PROGRAMME)
        return data


class Library(Base):
    def test_what_a_path_is(self):
        self.assertEqual(mr.parse(VID), ("yt", "abcdefghijk"))
        self.assertEqual(mr.parse(VID + "&incognito=true"), ("yt", "abcdefghijk"))
        self.assertEqual(mr.parse(LIVE), ("sw", "5", ""))
        self.assertEqual(mr.parse(ARCHIVE), ("sw", "5", "50"))
        for other in (None, 5, "", YT + "play/", YT + "play/?video_id=a b", YT + "play/?video_id=../x", "plugin://x/y",
                      "plugin://plugin.video.sweettv/playvid/5", "plugin://plugin.video.sweettv/playvid/x|1"):
            self.assertIsNone(mr.parse(other), other)

    def test_keys(self):
        self.assertEqual((mr.key_of(mr.parse(VID)), mr.key_of(mr.parse(ARCHIVE))), ("yt:abcdefghijk", "sw:5|50"))
        self.assertEqual((mr.key_of(mr.parse(LIVE)), mr.key_of(None)), ("", ""))

    def test_a_place_is_recorded_and_the_input_is_not_changed(self):
        before = mr.empty()
        after = mr.record(before, VID, 150, 600, 1000)
        self.assertEqual(before, mr.empty())
        self.assertEqual(after["items"]["yt:abcdefghijk"], {"pos": 150, "total": 600, "done": False, "at": 1000})
        self.assertEqual((mr.seconds_for(after, VID), mr.progress_for(after, VID)), (150, 0.25))
        self.assertEqual((mr.seconds_for(after, VID2), mr.progress_for(after, VID2)), (0, 0.0))

    def test_a_video_near_its_end_is_watched_not_a_place(self):
        for pos, total in ((590, 600), (570, 600), (2920, 3000)):    # 10 s left, 30 s left, 97.3 %
            data = mr.record(mr.empty(), VID, pos, total, 1000)
            self.assertTrue(data["items"]["yt:abcdefghijk"]["done"], (pos, total))
            self.assertEqual((mr.seconds_for(data, VID), mr.progress_for(data, VID)), (0, 1.0))
        data = mr.record(mr.empty(), VID, 560, 600, 1000)             # 40 s left: still a place
        self.assertEqual(mr.seconds_for(data, VID), 560)

    def test_watching_again_after_the_end_makes_a_place_again(self):
        data = mr.record(mr.empty(), VID, 595, 600, 1000)
        data = mr.record(data, VID, 100, 600, 2000)
        self.assertEqual((mr.seconds_for(data, VID), data["items"]["yt:abcdefghijk"]["done"]), (100, False))

    def test_the_start_of_a_video_does_not_erase_an_older_place(self):
        data = mr.record(mr.empty(), VID, 300, 600, 1000)
        data = mr.record(data, VID, 2, 600, 2000)
        self.assertEqual(mr.seconds_for(data, VID), 300)
        self.assertEqual(mr.record(mr.empty(), VID, 2, 600, 1000)["items"], {})

    def test_a_live_channel_is_the_channel_only(self):
        data = mr.record(mr.empty(), LIVE, 12, 60, 1234)
        self.assertEqual((data["items"], data["live"]), ({}, {"cid": "5", "at": 1234}))

    def test_an_archived_programme_keeps_what_it_is(self):
        data = mr.record(mr.empty(), ARCHIVE, 1500, 3600, 1000, PROGRAMME)
        self.assertEqual(data["items"]["sw:5|50"], {"pos": 1500, "total": 3600, "done": False, "at": 1000, "cid": "5", "epg": "50",
                                                    "title": "Утро", "start": NOW - 7200, "stop": NOW - 3600})
        again = mr.record(data, ARCHIVE, 1800, 3600, 2000)             # no meta this time: what was known stays
        self.assertEqual((again["items"]["sw:5|50"]["title"], again["items"]["sw:5|50"]["start"]), ("Утро", NOW - 7200))
        self.assertEqual(mr.seconds_for(again, ARCHIVE), 1800)
        self.assertEqual(mr.seconds_for(again, "plugin://plugin.video.sweettv/playvid/5|50"), 1800)

    def test_nonsense_is_not_recorded(self):
        for pos, total in ((float("nan"), 600), (True, 600), (-5, 600), (100, 0), (100, None), ("100", 600), (10 ** 12, 600)):
            self.assertEqual(mr.record(mr.empty(), VID, pos, total, 1000)["items"], {}, (pos, total))
        self.assertEqual(mr.record(mr.empty(), "plugin://other/x", 100, 600, 1000), mr.empty())

    def test_the_newest_300_are_kept(self):
        data = mr.empty()
        for i in range(305):
            data = mr.record(data, YT + "play/?video_id=v%010d" % i, 100, 600, 1000 + i)
        self.assertEqual(len(data["items"]), mr.MAX_ITEMS)
        self.assertIn("yt:v%010d" % 304, data["items"])
        self.assertNotIn("yt:v%010d" % 0, data["items"])

    def test_a_document_that_is_not_ours_reads_as_nothing(self):
        junk = {"items": {"bad key": {"pos": 5, "total": 10, "at": 1}, "yt:abcdefghijk": {"pos": "x", "total": 10, "at": 1},
                          "yt:zzzzzzzzzzz": {"pos": 50, "total": 100, "at": 1, "extra": "dropped"},
                          "sw:5|50": {"pos": 5, "total": 10, "at": 1, "cid": "9"}, "yt:qqqqqqqqqqq": []},
                "live": {"cid": "x; rm", "at": 5}}
        data = mr.record(junk, "plugin://other/x", 1, 1, 1)
        self.assertEqual(sorted(data["items"]), ["sw:5|50", "yt:zzzzzzzzzzz"])
        self.assertEqual(data["items"]["yt:zzzzzzzzzzz"], {"pos": 50, "total": 100, "done": False, "at": 1})
        self.assertEqual(data["items"]["sw:5|50"]["cid"], "5")             # the key says which channel, not a field
        self.assertEqual(data["live"], {})
        for raw in (None, [], "x", 5, {"items": 5}):
            self.assertEqual(mr.record(raw, "plugin://other/x", 1, 1, 1), mr.empty())

    def test_the_file_is_written_whole_and_read_back(self):
        data = self.placed((VID, 150, 600), (ARCHIVE, 1500, 3600))
        self.assertTrue(mr.save(data))
        self.assertEqual(mr.load(), data)
        import sqlite3
        db_path = os.path.join(mr.DIR, "state.db")
        self.assertTrue(os.path.exists(db_path))
        self.assertEqual([n for n in os.listdir(mr.DIR) if n.endswith(".tmp")], [])
        with sqlite3.connect(db_path) as con:
            self.assertEqual(str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")

    def test_a_missing_or_broken_file_reads_as_nothing(self):
        self.assertEqual(mr.load(), mr.empty())
        os.makedirs(mr.DIR, exist_ok=True)
        for text in ("", "{", "[]", "null", '{"items": 3}'):
            with open(os.path.join(mr.DIR, "positions.json"), "w", encoding="utf-8") as f:
                f.write(text)
            self.assertEqual(mr.load(), mr.empty(), text)

    def test_a_disk_that_refuses_is_a_false_not_a_crash(self):
        self.assertFalse(mr.save(mr.empty(), os.path.join(BLOCKER, "positions.json")))
        with mock.patch.object(mr, "PREFS", os.path.join(BLOCKER, "prefs")):
            self.assertFalse(mr.write_quality("720p"))
            self.assertEqual(mr.read_quality(), "1080p")

    def test_the_deprecated_global_local_resume_override_is_removed(self):
        self.assertFalse(hasattr(mr, "enabled"))
        self.assertFalse(hasattr(mr, "set_enabled"))

    def test_writes_are_spaced(self):
        self.assertFalse(mr.due(100, 100 + mr.WRITE_EVERY - 1))
        self.assertTrue(mr.due(100, 100 + mr.WRITE_EVERY))
        self.assertTrue(mr.due(0.0, 1000))

    def test_a_programme_is_found_in_the_channel_list(self):
        self.assertEqual(mr.programme_meta(LIST, "5", "51"), {"title": "Холостяк", "start": NOW - 3600, "stop": NOW + 3600})
        for raw, cid, epg in (({}, "5", "50"), (None, "5", "50"), (LIST, "6", "50"), (LIST, "5", "99"), ({"list": [3, None]}, "5", "50")):
            self.assertEqual(mr.programme_meta(raw, cid, epg), {})

    def test_vod_paths_and_keys(self):
        movie = "plugin://plugin.video.sweettv/playvod/9558|null|69"
        episode = "plugin://plugin.video.sweettv/playvod/1234|5678|69?start=120"
        self.assertEqual(mr.key_of(mr.parse(movie)), "sw:vod:9558")
        self.assertEqual(mr.key_of(mr.parse(episode)), "sw:vod:1234|5678")
        for bad in ("plugin://plugin.video.sweettv/playvod/9558",
                    "plugin://plugin.video.sweettv/playvod/abc|null|0",
                    "plugin://plugin.video.sweettv/playvod/9558|bad|0",
                    "plugin://plugin.video.sweettv/playvod/9558|null|bad"):
            self.assertIsNone(mr.parse(bad), bad)

    def test_vod_movie_and_episode_are_recorded_and_roundtripped(self):
        movie = "plugin://plugin.video.sweettv/playvod/9558|null|69"
        episode = "plugin://plugin.video.sweettv/playvod/1234|5678|69"
        data = mr.record(mr.empty(), movie, 420, 3600, 1000, {"title": "Зрадники"})
        data = mr.record(data, episode, 900, 2400, 1005, {"title": "S1E2"})
        self.assertEqual(mr.seconds_for(data, movie), 420)
        self.assertEqual(mr.seconds_for(data, episode), 900)
        self.assertAlmostEqual(mr.progress_for(data, movie), 420 / 3600)
        self.assertTrue(mr.save(data))
        loaded = mr.load()
        self.assertEqual(mr.seconds_for(loaded, movie), 420)
        self.assertEqual(mr.seconds_for(loaded, episode), 900)

    def test_epg_optional_metadata_is_preserved(self):
        meta = {"title": "Утро", "start": NOW - 7200, "stop": NOW - 3600,
                "show_id": "321", "season": 2, "episode": 7, "thumb": "https://img.example/ep.jpg"}
        data = mr.record(mr.empty(), ARCHIVE, 1200, 3600, 1000, meta)
        entry = data["items"]["sw:5|50"]
        self.assertEqual((entry.get("show_id"), entry.get("season"), entry.get("episode"), entry.get("thumb")),
                         ("321", 2, 7, "https://img.example/ep.jpg"))
        self.assertTrue(mr.save(data))
        loaded = mr.load()["items"]["sw:5|50"]
        self.assertEqual((loaded.get("show_id"), loaded.get("season"), loaded.get("episode"), loaded.get("thumb")),
                         ("321", 2, 7, "https://img.example/ep.jpg"))


class Quality(Base):
    def test_normalize_quality(self):
        for raw, expected in (("720p", "720p"), ("1080p", "1080p"), ("unlimited", "unlimited"),
                              ("4k", "unlimited"), ("4K", "unlimited"),
                              (None, "1080p"), ("", "1080p"), ("480p", "1080p"), ("garbage", "1080p"), (1080, "1080p")):
            self.assertEqual(mr.normalize_quality(raw), expected, raw)

    def test_read_and_write_quality(self):
        self.assertEqual(mr.read_quality(), "1080p")
        os.makedirs(mr.PREFS, exist_ok=True)
        with open(os.path.join(mr.PREFS, "max-quality"), "w", encoding="utf-8") as f:
            f.write("bogus\n")
        self.assertEqual(mr.read_quality(), "1080p")
        self.assertTrue(mr.write_quality("720p"))
        self.assertEqual(mr.read_quality(), "720p")
        self.assertEqual(oct(os.stat(os.path.join(mr.PREFS, "max-quality")).st_mode & 0o777), "0o644")
        self.assertEqual([n for n in os.listdir(mr.PREFS) if n.endswith(".tmp")], [])
        self.assertTrue(mr.write_quality("4k"))
        self.assertEqual(mr.read_quality(), "unlimited")


class Favourites(Base):
    def test_toggle_fav_adds_removes_and_rejects_invalid_keys(self):
        self.assertEqual(mr.fav_keys(), set())
        for valid in ("show:vod:9558", "show:epg:12", "show:tv:5", "vod:9558", "ch:5"):
            now_fav, saved_ok = mr.toggle_fav(valid, {"title": "Item " + valid, "thumb": "https://cdn.sweet.tv/a.jpg"}, now=NOW)
            self.assertTrue((now_fav, saved_ok), valid)
            self.assertIn(valid, mr.fav_keys())
        self.assertEqual(len(mr.load_favs()["items"]), 5)
        now_fav, saved_ok = mr.toggle_fav("vod:9558", now=NOW + 1)
        self.assertEqual((now_fav, saved_ok), (False, True))
        self.assertNotIn("vod:9558", mr.fav_keys())
        for bad in ("", None, "bad", "show:bad:1", "vod:abc", "ch:", 123):
            now_fav, saved_ok = mr.toggle_fav(bad, now=NOW)
            self.assertEqual((now_fav, saved_ok), (False, False), bad)
        self.assertEqual(len(mr.load_favs()["items"]), 4)


class Listings(Base):
    def reply(self, *files):
        return {"jsonrpc": "2.0", "id": 1, "result": {"files": list(files)}}

    def test_only_what_the_stick_saved_is_in_a_listing(self):
        data = self.placed((VID, 150, 600), (VID2, 595, 600))
        reply = self.reply(
            {"file": VID, "title": "a", "resume": {"position": 430, "total": 600}, "playcount": 3, "lastplayed": "2026-01-01"},
            {"file": VID2, "title": "b", "resume": {"position": 10, "total": 600}},
            {"file": YT + "play/?video_id=ccccccccccc", "title": "c", "playcount": 5},
            {"file": YT + "channel/UC1/", "filetype": "directory", "label": "Channel"})
        files = mr.localize_reply(reply, data)["result"]["files"]
        self.assertEqual(files[0], {"file": VID, "title": "a", "playcount": 0, "resume": {"position": 150, "total": 600}})
        self.assertEqual(files[1], {"file": VID2, "title": "b", "playcount": 1})
        self.assertEqual(files[2], {"file": YT + "play/?video_id=ccccccccccc", "title": "c", "playcount": 0})
        self.assertEqual(files[3], reply["result"]["files"][3])                 # a folder is as it was
        self.assertEqual(reply["result"]["files"][0]["resume"]["position"], 430)    # the answer given is not changed

    def test_what_is_not_a_listing_is_returned_as_it_is(self):
        for reply in ({"error": {"code": -32602}}, {"result": None}, {"result": {"files": 3}}, None, [], {"result": {}}):
            self.assertEqual(mr.localize_reply(reply, mr.empty()), reply)

    def test_the_phone_ignores_local_resume_even_when_enabled(self):
        theirs = {"file": VID, "filetype": "file", "title": "t", "duration": 600, "resume": {"position": 430, "total": 600}}
        rpc = lambda method, params, timeout=0: {"files": [dict(theirs)]}    # noqa: E731
        data = pw.yt()
        self.on(self.placed((VID, 150, 600)))
        entry = pw._directory(data, rpc, YT).entries[0]
        self.assertEqual(pw.map_entry(entry)["resume"], 430)

    def test_the_tv_app_ignores_local_resume_even_when_enabled(self):
        State.answers["Files.GetDirectory"] = {"files": [{"file": VID, "title": "t", "resume": {"position": 430, "total": 600},
                                                          "playcount": 2}]}
        self.on(self.placed((VID, 150, 600)))
        item = youtube_files.get_directory(YT)["result"]["files"][0]
        self.assertEqual((item["resume"]["position"], item["playcount"]), (430, 2))
        self.assertEqual(State.rpc[-1]["method"], "Files.GetDirectory")


class Playing(Base):
    def test_the_phone_starts_youtube_from_its_own_resume_even_when_local_enabled(self):
        calls, seeks = [], []
        rpc = lambda method, params, timeout=0: calls.append((method, params)) or {}     # noqa: E731
        with mock.patch.object(pw, "_seek_when_started", lambda r, s: seeks.append(s)):
            self.on(self.placed((VID, 150, 600)))
            pw.play({"file": VID, "resume": 430}, rpc)
            self.assertEqual(calls[-1], ("Player.Open", {"item": {"file": VID}}))
            time.sleep(0.2)
        self.assertEqual(seeks, [430])

    def test_the_tv_app_starts_youtube_normally_even_when_local_enabled(self):
        threads = []
        with mock.patch.object(youtube_files.threading, "Thread", lambda target, args, daemon: threads.append(args) or mock.Mock()):
            self.on(self.placed((VID, 150, 600)))
            youtube_files.play(VID)
            self.assertEqual(State.rpc[-1]["params"], {"item": {"file": VID}})
        self.assertEqual(threads, [])

    def test_the_seek_waits_for_the_video_and_goes_once(self):
        State.total, State.time = 600, 0
        youtube_files._seek_when_started(150)
        self.assertEqual(State.seeks, [150])

    def test_no_seek_into_a_video_that_is_shorter_or_already_past_the_place(self):
        State.total = 100
        with mock.patch.object(youtube_files, "START_WAIT", 0.05):
            youtube_files._seek_when_started(150)
        State.total, State.time = 600, 200
        youtube_files._seek_when_started(150)
        State.playing = False
        with mock.patch.object(youtube_files, "START_WAIT", 0.05):
            youtube_files._seek_when_started(150)
        self.assertEqual(State.seeks, [])


class Recorder(Base):
    def make(self, meta=None):
        self.clock = [1000.0]
        self.writes = []
        real = mr.save

        def counting(data, path=None):
            self.writes.append(json.loads(json.dumps(data)))
            return real(data, path)

        lib = types.SimpleNamespace(**{k: getattr(mr, k) for k in ("parse", "load", "record", "due")}, save=counting)
        return resume_recorder.Recorder(lib, clock=lambda: self.clock[0], meta=meta, log=State.logs.append)

    def test_a_video_is_written_every_30_seconds_and_on_a_stop(self):
        r = self.make()
        for step in range(0, 25, 5):                                   # 25 s of samples: the first one is written, no more
            self.clock[0] = 1000 + step
            r.sample(VID, 100 + step, 600)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0]["items"]["yt:abcdefghijk"]["pos"], 100)
        self.clock[0] = 1030
        r.sample(VID, 130, 600)
        self.assertEqual(len(self.writes), 2)
        self.clock[0] = 1035
        r.sample(VID, 135, 600)
        r.flush()                                                      # the stop: its last sample is the place
        self.assertEqual(mr.seconds_for(mr.load(), VID), 135)
        self.assertEqual(len(self.writes), 3)
        r.flush()                                                      # nothing new: nothing written
        self.assertEqual(len(self.writes), 3)

    def test_a_video_that_ends_is_watched(self):
        r = self.make()
        r.sample(VID, 400, 600)
        r.finish()
        data = mr.load()
        self.assertEqual((mr.seconds_for(data, VID), mr.progress_for(data, VID)), (0, 1.0))

    def test_the_next_video_closes_the_one_before(self):
        r = self.make()
        r.sample(VID, 140, 600)
        self.clock[0] = 1001
        r.sample(VID2, 3, 300)                                         # the player moved on without a stop in between
        self.clock[0] = 1002
        r.sample(VID2, 50, 300)
        r.flush()
        data = mr.load()
        self.assertEqual((mr.seconds_for(data, VID), mr.seconds_for(data, VID2)), (140, 50))

    def test_the_start_of_a_video_writes_nothing(self):
        r = self.make()
        r.sample(VID, 1, 600)
        r.flush()
        self.assertEqual(self.writes, [])
        self.assertFalse(os.path.exists(os.path.join(mr.DIR, "positions.json")))

    def test_something_else_is_not_followed(self):
        r = self.make()
        r.sample("/media/film.mkv", 500, 6000)
        r.flush()
        r.sample("", 0, 0)
        r.finish()
        self.assertEqual(self.writes, [])

    def test_a_live_channel_is_remembered_as_the_channel(self):
        r = self.make()
        r.sample(LIVE, 20, 60)
        data = mr.load()
        self.assertEqual((data["live"]["cid"], data["items"]), ("5", {}))

    def test_an_archived_programme_is_looked_up_once_and_saved_with_its_times(self):
        asked = []
        r = self.make(meta=lambda cid, epg: asked.append((cid, epg)) or dict(PROGRAMME))
        for i in range(4):
            self.clock[0] = 1000 + 31 * i
            r.sample(ARCHIVE, 600 + 31 * i, 3600)
        r.flush()
        self.assertEqual(asked, [("5", "50")])
        entry = mr.load()["items"]["sw:5|50"]
        self.assertEqual((entry["title"], entry["start"], entry["stop"], entry["pos"]), ("Утро", NOW - 7200, NOW - 3600, 693))

    def test_a_programme_that_cannot_be_looked_up_is_still_saved_and_the_log_says_so(self):
        def broken(cid, epg):
            raise OSError("no list")

        r = self.make(meta=broken)
        r.sample(ARCHIVE, 600, 3600)
        entry = mr.load()["items"]["sw:5|50"]
        self.assertEqual((entry["pos"], entry["start"], entry["stop"]), (600, 0, 0))
        self.assertTrue(any("not looked up" in line for line in State.logs))

    def test_a_disk_that_refuses_is_logged_not_raised(self):
        r = self.make()
        with mock.patch.object(mr, "DIR", os.path.join(BLOCKER, "resume")):
            r.sample(VID, 100, 600)
        self.assertTrue(any("not written" in line for line in State.logs))

    def test_the_programme_is_read_from_the_add_ons_channel_list(self):
        path = os.path.join(TMP, "temp", "channelList.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(LIST, f)
        self.assertEqual(resume_recorder.programme_meta("5", "50"), {"title": "Утро", "start": NOW - 7200, "stop": NOW - 3600})
        self.assertEqual(resume_recorder.programme_meta("5", "99"), {})


class Watching(Base):
    def make(self):
        self.watcher = resume_recorder.start()
        self.assertIsNotNone(self.watcher)
        return self.watcher

    def test_a_tick_samples_what_plays_and_a_stop_writes_the_place(self):
        w = self.make()
        State.file, State.time, State.total = VID, 140.5, 600.0
        w.tick()
        State.file = ""                                               # Kodi has forgotten the item when the stop comes
        w.onPlayBackStopped()
        self.assertEqual(mr.seconds_for(mr.load(), VID), 140)

    def test_a_plugin_item_is_found_by_the_label_when_the_player_gives_the_stream(self):
        w = self.make()
        State.file, State.label, State.time, State.total = "https://cdn.example/stream.m3u8", ARCHIVE, 700.0, 3600.0
        w.tick()
        w.onPlayBackStopped()
        self.assertEqual(mr.load()["items"]["sw:5|50"]["pos"], 700)

    def test_an_archive_the_player_gives_as_a_stream_address_is_recorded_as_its_programme(self):
        """What the owner's device does: the player's file is the https address and the label is no help, so the plugin
        path was nowhere; the address the add-on wrote down says which channel and programme it is."""
        stream = "https://hls-dvr2.sweet.tv/dvr/5/50/index.m3u8?token=x"
        store.sweetlive.remember(5, 50, stream, 600, now=NOW)
        w = self.make()
        State.file, State.label, State.time, State.total = stream, "", 700.0, 3600.0
        w.tick()
        w.onPlayBackStopped()
        item = mr.load()["items"]["sw:5|50"]
        self.assertEqual((item["cid"], item["epg"], item["pos"], item["total"], item["done"]), ("5", "50", 700, 3600, False))
        self.assertEqual(mr.seconds_for(mr.load(), ARCHIVE), 700)            # the phone's "continue" finds it by the plugin path

    def test_one_programme_is_one_item_whether_the_player_names_it_by_path_or_by_address(self):
        stream = "https://hls-dvr2.sweet.tv/dvr/5/50/index.m3u8?token=x"
        store.sweetlive.remember(5, 50, stream, 0, now=NOW)
        w = self.make()
        State.file, State.label, State.time, State.total = stream, "", 700.0, 3600.0
        w.tick()
        State.file, State.time = "", 900.0
        State.label = ARCHIVE
        w.tick()
        w.onPlayBackStopped()
        self.assertEqual(list(mr.load()["items"]), ["sw:5|50"])
        self.assertEqual(mr.load()["items"]["sw:5|50"]["pos"], 900)

    def test_a_live_stream_address_remembers_the_channel_and_no_place(self):
        stream = "https://hls-live3.sweet.tv/live/5/index.m3u8"
        store.sweetlive.remember(5, "", stream, 0, now=NOW)
        w = self.make()
        State.file, State.time, State.total = stream, 40.0, 56.0
        w.tick()
        w.onPlayBackStopped()
        self.assertEqual(mr.load()["items"], {})
        self.assertEqual(mr.load()["live"]["cid"], "5")

    def test_a_stream_address_nobody_wrote_down_is_not_remembered(self):
        store.sweetlive.remember(5, 50, "https://hls-dvr2.sweet.tv/dvr/5/50/index.m3u8?token=x", 0, now=NOW)
        w = self.make()
        State.file, State.time, State.total = "https://example.org/film.m3u8", 700.0, 3600.0
        w.tick()
        w.onPlayBackStopped()
        self.assertEqual(mr.load(), mr.empty())

    def test_a_device_without_the_stream_library_still_records_by_path(self):
        w = self.make()
        State.file, State.time, State.total = ARCHIVE, 700.0, 3600.0
        with mock.patch.object(store, "sweetlive", None):
            w.tick()
            State.file, State.label = "https://cdn.example/stream.m3u8", ""
            w.tick()
        self.assertEqual(mr.load()["items"]["sw:5|50"]["pos"], 700)

    def test_the_end_of_a_video_is_watched(self):
        w = self.make()
        State.file, State.time, State.total = VID, 300.0, 600.0
        w.tick()
        w.onPlayBackEnded()
        self.assertEqual(mr.progress_for(mr.load(), VID), 1.0)

    def test_nothing_playing_or_an_item_that_goes_away_is_not_an_error(self):
        w = self.make()
        State.playing = False
        w.tick()
        State.playing = True
        w.tick()                                                      # getPlayingFile raises RuntimeError
        w.onPlayBackError()
        self.assertEqual(mr.load(), mr.empty())

    def test_a_device_without_the_library_has_no_watcher(self):
        with mock.patch.object(store, "resume", None):
            self.assertIsNone(resume_recorder.start())

    def test_a_vod_stream_is_recorded_via_sweetlive(self):
        stream = "https://vod.sweet.tv/vod/9558/5678/index.m3u8?token=x"
        store.sweetlive.remember("vod:9558", "5678", stream, 0, now=NOW)
        w = self.make()
        State.file, State.label, State.time, State.total = stream, "", 400.0, 1800.0
        w.tick()
        w.onPlayBackStopped()
        item = mr.load()["items"]["sw:vod:9558|5678"]
        self.assertEqual((item["pos"], item["total"], item["done"]), (400, 1800, False))


class SweetState(Base):
    def state(self, **resume):
        return saved.normalize_state({"resume": resume, "recent": [{"id": "9", "at": NOW - 500}], "last": "9"})

    def local(self, **fields):
        row = {"pos": 1500, "total": 3600, "done": False, "at": NOW, "cid": "5", "epg": "50", "title": "Утро",
               "start": NOW - 7200, "stop": NOW - 3600}
        row.update(fields)
        return {"v": 1, "items": {"sw:5|50": row}, "live": {}}

    def test_without_the_choice_the_state_is_what_it_was(self):
        state = self.state()
        self.assertIs(saved.merge_local(state, None), state)

    def test_a_place_the_stick_saved_is_in_the_state(self):
        merged = saved.merge_local(self.state(), self.local())
        self.assertEqual(merged["resume"]["5"], {"epg": "50", "title": "Утро", "start": NOW - 7200, "stop": NOW - 3600,
                                                 "pos": 1500, "at": NOW})

    def test_the_newer_record_wins(self):
        theirs = {"epg": "49", "title": "Старое", "start": NOW - 9000, "stop": NOW - 7200, "pos": 900, "at": NOW + 10}
        self.assertEqual(saved.merge_local(self.state(**{"5": theirs}), self.local())["resume"]["5"]["epg"], "49")
        older = dict(theirs, at=NOW - 10)
        self.assertEqual(saved.merge_local(self.state(**{"5": older}), self.local())["resume"]["5"]["epg"], "50")

    def test_a_programme_watched_to_its_end_or_left_at_an_edge_is_forgotten(self):
        mine = {"epg": "50", "title": "Утро", "start": NOW - 7200, "stop": NOW - 3600, "pos": 900, "at": NOW - 100}
        for fields in ({"done": True, "pos": 0}, {"pos": 30}, {"pos": 3600 - saved.END_MARGIN + 1}):
            merged = saved.merge_local(self.state(**{"5": mine}), self.local(**fields))
            self.assertNotIn("5", merged["resume"], fields)

    def test_a_place_without_its_programme_times_and_other_apps_are_left_out(self):
        local = self.local(start=0, stop=0)
        local["items"]["yt:abcdefghijk"] = {"pos": 100, "total": 600, "done": False, "at": NOW}
        mine = {"epg": "50", "title": "Утро", "start": NOW - 7200, "stop": NOW - 3600, "pos": 900, "at": NOW - 100}
        merged = saved.merge_local(self.state(**{"5": mine}), local)
        self.assertEqual(merged["resume"], self.state(**{"5": mine})["resume"])

    def test_the_channel_that_was_on_last_is_the_last_one_when_it_is_newer(self):
        local = {"v": 1, "items": {}, "live": {"cid": "5", "at": NOW}}
        merged = saved.merge_local(self.state(), local)
        self.assertEqual((merged["last"], merged["recent"][0]), ("5", {"id": "5", "at": NOW}))
        local["live"]["at"] = NOW - 9000
        self.assertEqual(saved.merge_local(self.state(), local)["last"], "9")

    def test_the_app_always_reads_local_positions(self):
        mr.save(self.placed((ARCHIVE, 1500, 3600)))
        self.assertIn("sw:5|50", sweettv_files.local_positions()["items"])
        with open(os.path.join(ADDON_LIB, "sweettv_app.py"), encoding="utf-8") as f:
            self.assertIn("saved.merge_local(saved.load_state(files.state_path()), files.local_positions())", f.read())

    def test_store_local_resume_is_none_for_youtube(self):
        self.on(self.placed((VID, 150, 600)))
        self.assertIsNone(store.local_resume())
        with mock.patch.object(store, "resume", None):
            self.assertIsNone(store.local_resume())
            self.assertIsNone(sweettv_files.local_positions())
            self.assertEqual(youtube_files._local(), (None, None))


class PhoneSweet(Base):
    def test_the_programme_sheet_always_has_the_stick_places(self):
        mr.save(self.placed((ARCHIVE, 1500, 3600), ("plugin://plugin.video.sweettv/playvid/5|51", 3590, 3600)))
        view = ps.guide_view(LIST, "5", NOW, ps.local())
        self.assertEqual((view["past"][0]["resume"], view["past"][0]["watched"]), (1500, False))
        self.assertEqual((view["current"]["resume"], view["current"]["watched"]), (0, True))
        self.assertEqual(view["next"], [])

    def test_play_from_the_place_the_stick_saved(self):
        body = {"cid": 5, "epg": 50, "at": "resume"}
        self.assertEqual(ps.play_request(LIST, body, NOW, None)[2], 0)
        mr.save(self.placed((ARCHIVE, 1500, 3600)))
        url, epg, offset = ps.play_request(LIST, body, NOW, ps.local())
        self.assertEqual((url, epg, offset), (ml_url(5, 50, 1500), "50", 1500))
        self.assertEqual(ps.play_request(LIST, {"cid": 5, "epg": 51, "at": "resume"}, NOW, ps.local())[2], 0)
        self.assertEqual(ps.play_request(LIST, dict(body, at=30), NOW, ps.local())[2], 30)

    def test_the_quality_choice_over_the_phone_api(self):
        body, code = ps.get(ps.PREFIX + "settings", None)
        self.assertEqual((code, body["ok"], body["quality"]), (200, True, "1080p"))
        for q in ("720p", "unlimited", "1080p"):
            body, code = ps.post(ps.PREFIX + "settings", {"quality": q}, None)
            self.assertEqual((code, body["ok"], body["quality"]), (200, True, q))
            self.assertEqual(mr.read_quality(), q)
            self.assertEqual(ps.get(ps.PREFIX + "settings", None)[0]["quality"], q)

    def test_invalid_quality_is_refused_and_nothing_changes(self):
        for value in ("480p", "2160p", 1080, None, True, ["1080p"], ""):
            body, code = ps.post(ps.PREFIX + "settings", {"quality": value}, None)
            self.assertEqual(code, 400, value)
            self.assertIn("error", body)
        for body in (None, {}, [], "x"):
            self.assertEqual(ps.post(ps.PREFIX + "settings", body, None)[1], 400)
        self.assertFalse(os.path.exists(os.path.join(mr.PREFS, "max-quality")))

    def test_a_disk_that_refuses_is_said_so(self):
        with mock.patch.object(mr, "write_quality", lambda value: False):
            body, code = ps.post(ps.PREFIX + "settings", {"quality": "720p"}, None)
        self.assertEqual(code, 500)
        self.assertIn("error", body)

    def test_a_device_without_the_library_says_so(self):
        with mock.patch.object(ps, "mr", None):
            self.assertEqual(ps.get(ps.PREFIX + "settings", None)[1], 503)
            self.assertEqual(ps.post(ps.PREFIX + "settings", {"quality": "720p"}, None)[1], 503)
            self.assertIsNone(ps.local())


class Texts(Base):
    def test_every_new_text_has_russian_and_ukrainian(self):
        texts = (ps.LOCAL_LABEL, ps.LOCAL_HINT, "Wrong value.", "The choice could not be saved.",
                 "Remembering places is not available on this device.")
        for msgid in texts:
            self.assertIn(msgid, sweettv_text.TEXT, msgid)
            self.assertTrue(sweettv_text.TEXT[msgid].get("ru") and sweettv_text.TEXT[msgid].get("uk"), msgid)
            self.assertNotEqual(sweettv_text.TEXT[msgid]["ru"], msgid)


def ml_url(cid, epg, offset):
    import mediastick_sweetlive
    return mediastick_sweetlive.url(cid, epg, offset)


if __name__ == "__main__":
    unittest.main()
