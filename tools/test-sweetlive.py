#!/usr/bin/env python3
"""Offline test of going back on a live SWEET.TV channel (no Kodi, no device, no network): python3 tools/test-sweetlive.py

A live stream is a window of about a minute in Kodi, so a seek back cannot reach further. What does: the archive of the
programme on now, started at (now - start - the step). One function (mediastick_sweetlive.plan) decides that for the TV
remote (the add-on's service sees the seek), for the -10 of the phone (panel_watch.ctl) and for "К эфиру"; this file tests
the function, the three places that ask it, the add-on's start place, and the texts (every msgid has ru and uk)."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in device/skin-overlay

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import runpy  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON_LIB = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "resources", "lib")
OVERLAY = os.path.join(ROOT, "device", "skin-overlay", "plugin.video.sweettv")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, ".kodi", "userdata", "addon_data")
os.environ["MEDIASTICK_ADDON_LIB"] = ADDON_LIB
os.environ["MEDIASTICK_SWEETNOW_DIR"] = os.path.join(TMP, "now")      # what the add-on wrote down about the streams it resolved
sys.path.insert(0, LIB)

import mediastick_sweetlive as ml  # noqa: E402
import panel_sweettv as ps  # noqa: E402
import panel_watch as pw  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


play_tests = load("sweettv_play_tests", "test-sweettv-play.py")
stubs = play_tests.stubs

NOW = 1_800_000_000
SHOW = {"id": 51, "time_start": NOW - 3600, "time_stop": NOW + 3600, "text": "Холостяк", "available": True}
LIST = {"status": "OK", "list": [
    {"id": 5, "name": "Первый канал", "catchup": True, "catchup_duration": 7, "available": True, "epg": [
        {"id": 50, "time_start": NOW - 7200, "time_stop": NOW - 3600, "text": "Утро", "available": True}, SHOW,
        {"id": 52, "time_start": NOW + 3600, "time_stop": NOW + 7200, "text": "Вечер", "available": True}]},
    {"id": 6, "name": "Без архива", "catchup": False, "available": True, "epg": [
        {"id": 60, "time_start": NOW - 600, "time_stop": NOW + 600, "text": "Новости", "available": True}]},
    {"id": 7, "name": "Пустой", "catchup": True, "available": True, "epg": []}]}
LIVE, ARCHIVE = "plugin://plugin.video.sweettv/playvid/5|null", "plugin://plugin.video.sweettv/playvid/5|50?ms_start=30"
# what Kodi's player gives for an archived programme: the address of the stream the add-on resolved, not the plugin path
DVR = "https://hls-dvr2.sweet.tv/dvr/5/50/index.m3u8?token=secret"
DVR_NOW = "https://hls-dvr2.sweet.tv/dvr/5/51/index.m3u8?token=secret"
LIVE_STREAM = "https://hls-live3.sweet.tv/live/5/index.m3u8?token=secret"


def clean_now():
    shutil.rmtree(ml.NOW_DIR, ignore_errors=True)


class Library(unittest.TestCase):
    def test_url_and_ref_belong_together(self):
        self.assertEqual(ml.url(5), LIVE)
        self.assertEqual(ml.url("5", "50"), "plugin://plugin.video.sweettv/playvid/5|50")
        self.assertEqual(ml.url(5, 50, 30), ARCHIVE)
        self.assertEqual(ml.ref(ARCHIVE), ("5", "50", 30))
        self.assertEqual(ml.ref(LIVE), ("5", "", 0))
        self.assertEqual(ml.ref(ml.url(5, 50)), ("5", "50", 0))

    def test_a_live_url_has_no_start_and_a_start_is_a_sane_number(self):
        self.assertEqual(ml.url(5, None, 30), LIVE)
        self.assertEqual(ml.url(5, 50, -3), "plugin://plugin.video.sweettv/playvid/5|50")
        self.assertEqual(ml.url(5, 50, float("nan")), "plugin://plugin.video.sweettv/playvid/5|50")
        self.assertTrue(ml.url(5, 50, 10 ** 12).endswith("?ms_start=%d" % ml.START_MAX))

    def test_what_is_not_an_id_is_refused(self):
        for cid, epg in (("5; rm", None), ("", None), ("5", "x"), ("5|6", None), ("-1", None), ("1" * 13, None)):
            self.assertEqual(ml.url(cid, epg), "", (cid, epg))
        for file in (None, 5, "", "plugin://plugin.video.youtube/play/?video_id=x", "plugin://plugin.video.sweettv/playvid/5",
                     "plugin://plugin.video.sweettv/playvid/5|50?ms_start=x"):
            self.assertIsNone(ml.ref(file), file)

    def test_the_programme_on_now_from_the_place_the_person_went_back_to(self):
        plan = ml.plan(LIST, 5, 10, NOW)
        self.assertTrue(plan["ok"])
        self.assertEqual((plan["epg"], plan["offset"], plan["title"]), ("51", 3590, "Холостяк"))
        self.assertEqual(plan["url"], "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590")
        self.assertEqual(ml.plan(LIST, "5", 600, NOW)["offset"], 3000)

    def test_never_before_the_start_of_the_programme(self):
        self.assertEqual(ml.plan(LIST, 5, 10 ** 6, NOW)["offset"], 0)
        self.assertEqual(ml.plan(LIST, 5, -50, NOW)["offset"], 3600)        # a negative step is no step
        self.assertEqual(ml.plan(LIST, 5, 0, NOW + 3599)["offset"], 7199)   # the last second of the programme is still inside it

    def test_milliseconds_in_the_list_are_understood(self):
        raw = {"list": [{"id": 5, "catchup": True, "epg": [dict(SHOW, time_start=(NOW - 3600) * 1000, time_stop=(NOW + 3600) * 1000)]}]}
        self.assertEqual(ml.plan(raw, 5, 10, NOW)["offset"], 3590)

    def test_why_not(self):
        self.assertEqual(ml.plan(LIST, 6, 10, NOW), {"ok": False, "reason": "no_archive"})
        self.assertEqual(ml.plan(LIST, 7, 10, NOW), {"ok": False, "reason": "no_programme"})
        self.assertEqual(ml.plan(LIST, 99, 10, NOW), {"ok": False, "reason": "unknown"})
        self.assertEqual(ml.plan(LIST, 5, 10, NOW + 99999)["reason"], "no_programme")      # the list ended: nothing is on
        for raw in (None, {}, [], {"list": "x"}, {"list": [None, 5, {"id": 5, "catchup": True, "epg": [None, "x", {}]}]}):
            self.assertFalse(ml.plan(raw, 5, 10, NOW)["ok"])
        raw = {"list": [{"id": 5, "catchup": True, "epg": [dict(SHOW, available=False)]}]}
        self.assertEqual(ml.plan(raw, 5, 10, NOW)["reason"], "no_archive")                # that programme has no archive
        raw = {"list": [{"id": 5, "catchup": True, "epg": [dict(SHOW, id=True)]}]}
        self.assertFalse(ml.plan(raw, 5, 10, NOW)["ok"])

    def test_vod_url_and_split_vod_id(self):
        self.assertEqual(ml.vod_url(9558), "plugin://plugin.video.sweettv/playvod/9558|null|0")
        self.assertEqual(ml.vod_url(9558, 101, 69, 120), "plugin://plugin.video.sweettv/playvod/9558|101|69?start=120")
        self.assertEqual(ml.vod_url(9558, None, 69, -5), "plugin://plugin.video.sweettv/playvod/9558|null|69")
        for bad in (("", None, 0), ("abc", None, 0), (9558, "bad", 0), (9558, None, "bad")):
            self.assertEqual(ml.vod_url(*bad), "", bad)
        self.assertEqual(ml.split_vod_id("9558|null|69"), ("9558", "null", "69"))
        self.assertEqual(ml.split_vod_id("9558|101|69?start=120"), ("9558", "101", "69"))
        for bad in ("9558", "9558|null", "x|null|0", "9558|bad|0", "", None):
            self.assertIsNone(ml.split_vod_id(bad), bad)

    def test_live_timeline_and_forward_handoff_and_ended_plan(self):
        live_tl = ml.live_timeline(LIST, "5", None, 10, 60, NOW)
        self.assertEqual((live_tl["programme"], live_tl["in_progress"], live_tl["can_rewind"], live_tl["go_live"]),
                         ("Холостяк", True, True, False))
        arch_tl = ml.live_timeline(LIST, "5", "50", 1200, 3600, NOW)
        self.assertEqual((arch_tl["programme"], arch_tl["in_progress"], arch_tl["go_live"]), ("Утро", False, True))

        # forward_handoff: ONLY in-progress (51: NOW-3600..NOW+3600) within 15s of live edge (3600)
        self.assertEqual(ml.forward_handoff(LIST, "5", "51", 3585, NOW),
                         {"ok": True, "switched": "live", "url": "plugin://plugin.video.sweettv/playvid/5|null"})
        self.assertIsNone(ml.forward_handoff(LIST, "5", "51", 3584, NOW))
        # finished archive (50: NOW-7200..NOW-3600): NEVER switches to live
        self.assertIsNone(ml.forward_handoff(LIST, "5", "50", 3595, NOW))

        # ended_plan: near live edge -> live; behind real time with started next programme -> next archive
        self.assertEqual(ml.ended_plan(LIST, "5", "51", NOW + 3600 - 30),
                         "plugin://plugin.video.sweettv/playvid/5|null")
        self.assertEqual(ml.ended_plan(LIST, "5", "50", NOW),
                         "plugin://plugin.video.sweettv/playvid/5|51")
        self.assertFalse(ml.ended_plan(LIST, "5", "51", NOW))


class Identity(unittest.TestCase):
    """What the address of a stream is: the add-on writes it down when it resolves, whoever sees the address looks it up."""

    def setUp(self):
        clean_now()
        self.addCleanup(clean_now)

    def read(self):
        with open(os.path.join(ml.NOW_DIR, ml.NOW_FILE), encoding="utf-8") as f:
            return f.read()

    def test_an_address_is_what_the_add_on_wrote_down(self):
        self.assertTrue(ml.remember(5, 50, DVR, 3590, now=NOW))
        entry = ml.recall(DVR)
        self.assertEqual((entry["cid"], entry["epg"], entry["offset"], entry["at"]), ("5", "50", 3590, NOW))
        self.assertEqual(ml.identify(DVR), ("5", "50", 3590))
        self.assertIsNone(ml.recall("https://hls-dvr2.sweet.tv/dvr/5/99/index.m3u8"))          # another address is another item

    def test_a_live_stream_has_no_programme(self):
        ml.remember("5", None, LIVE_STREAM)
        self.assertEqual(ml.identify(LIVE_STREAM), ("5", "", 0))
        ml.remember("5", "null", LIVE_STREAM, 99)
        self.assertEqual(ml.identify(LIVE_STREAM)[1], "")

    def test_the_plugin_path_is_known_without_the_file(self):
        self.assertEqual(ml.identify(ARCHIVE), ("5", "50", 30))
        self.assertEqual(ml.identify(LIVE), ("5", "", 0))

    def test_the_options_after_a_bar_are_not_part_of_the_address(self):
        ml.remember(5, 50, DVR + "|User-Agent=x&Referer=y", 10)
        self.assertEqual(ml.identify(DVR), ("5", "50", 10))
        self.assertEqual(ml.identify(DVR + "|Referer=z"), ("5", "50", 10))

    def test_neither_the_address_nor_its_token_is_kept(self):
        ml.remember(5, 50, DVR, 10)
        text = self.read()
        self.assertNotIn("secret", text)
        self.assertNotIn("index.m3u8", text)
        self.assertEqual(oct(os.stat(os.path.join(ml.NOW_DIR, ml.NOW_FILE)).st_mode & 0o777), "0o644")

    def test_what_is_not_a_stream_is_nothing(self):
        ml.remember(5, 50, DVR, 10)
        for file in (None, 5, "", "/home/media/film.mkv", "plugin://plugin.video.youtube/play/?video_id=x", "smb://nas/a.mkv", b"https://x"):
            self.assertIsNone(ml.recall(file, NOW), file)
            self.assertIsNone(ml.identify(file, NOW), file)

    def test_what_is_not_an_id_is_not_written(self):
        for cid, epg, url in (("5; rm", 50, DVR), ("", 50, DVR), (5, "x", DVR), (5, "1" * 13, DVR), (5, 50, ""), (5, 50, None),
                              (5, 50, "plugin://plugin.video.sweettv/playvid/5|50"), (5, 50, "file:///etc/passwd")):
            self.assertFalse(ml.remember(cid, epg, url, 0), (cid, epg, url))
        self.assertFalse(os.path.exists(os.path.join(ml.NOW_DIR, ml.NOW_FILE)))

    def test_a_silly_start_is_a_sane_one(self):
        for given, kept in ((-5, 0), (float("nan"), 0), ("x", 0), (None, 0), (True, 0), (10 ** 12, ml.START_MAX), (12.9, 12)):
            ml.remember(5, 50, DVR, given)
            self.assertEqual(ml.recall(DVR)["offset"], kept, given)

    def test_the_item_that_is_going_away_is_still_told_apart_from_the_next(self):
        ml.remember(5, 50, DVR, 10)
        ml.remember(5, 51, DVR_NOW, 20)             # opened while the first one still plays
        self.assertEqual(ml.identify(DVR)[1], "50")
        self.assertEqual(ml.identify(DVR_NOW)[1], "51")

    def test_the_last_few_are_kept_newest_first(self):
        urls = ["https://hls-dvr2.sweet.tv/dvr/5/%d/index.m3u8" % i for i in range(ml.NOW_KEEP + 2)]
        for i, url in enumerate(urls):
            ml.remember(5, 100 + i, url, 0)
        self.assertEqual(json.loads(self.read())["items"][0]["epg"], str(100 + len(urls) - 1))
        self.assertEqual([bool(ml.recall(u)) for u in urls], [False, False] + [True] * ml.NOW_KEEP)

    def test_the_same_address_again_replaces_what_was_written(self):
        ml.remember(5, 50, DVR, 10)
        ml.remember(5, 50, DVR, 99)
        self.assertEqual(ml.recall(DVR)["offset"], 99)
        self.assertEqual(len(json.loads(self.read())["items"]), 1)

    def test_an_address_of_the_same_folder_of_the_archive_is_the_entry_while_it_is_young(self):
        ml.remember(5, 50, DVR, 10, now=NOW)
        other = "https://hls-dvr2.sweet.tv/dvr/5/50/other-name.m3u8"
        self.assertEqual(ml.recall(other, NOW + 10)["epg"], "50")
        self.assertIsNone(ml.recall(other, NOW + ml.WEAK_AGE + 1))
        self.assertIsNone(ml.recall(other))                                                      # no clock, no guess
        self.assertIsNone(ml.recall("https://hls-dvr9.sweet.tv/dvr/5/50/x.m3u8", NOW + 10))     # another host
        self.assertIsNone(ml.recall("https://hls-dvr2.sweet.tv/live/5/x.m3u8", NOW + 10))       # another folder
        self.assertIsNone(ml.recall("https://hls-dvr2.sweet.tv/x.m3u8", NOW + 10))              # no folder at all

    def test_an_address_that_is_exactly_known_beats_a_guess(self):
        ml.remember(5, 50, DVR, 10, now=NOW)
        ml.remember(5, 51, DVR_NOW, 20, now=NOW + 5)
        self.assertEqual(ml.recall(DVR, NOW + 6)["epg"], "50")
        self.assertEqual(ml.recall(DVR_NOW, NOW + 6)["epg"], "51")

    def test_a_broken_file_is_nothing_and_not_a_crash(self):
        os.makedirs(ml.NOW_DIR)
        good = {"cid": "5", "epg": "50", "offset": 1, "at": NOW, "sha": ml._hash(DVR), "where": ""}
        broken = ["", "not json", "[]", "null", "{" + json.dumps("items") + ": 5}", json.dumps({"items": [None, 5, "x", {}]}),
                  json.dumps({"items": [dict(good, cid=5)]}), json.dumps({"items": [dict(good, epg=50)]}),
                  json.dumps({"items": [dict(good, sha="zz")]}), json.dumps({"items": [dict(good, at="now")]}),
                  json.dumps({"items": [dict(good, cid="x")]}), json.dumps({"items": [dict(good, offset=None)]})]
        for text in broken:
            with open(os.path.join(ml.NOW_DIR, ml.NOW_FILE), "w", encoding="utf-8") as f:
                f.write(text)
            self.assertIsNone(ml.recall(DVR, NOW), text)
        with open(os.path.join(ml.NOW_DIR, ml.NOW_FILE), "w", encoding="utf-8") as f:
            json.dump({"items": [good]}, f)
        self.assertEqual(ml.recall(DVR)["epg"], "50")                                            # the sound shape does read

    def test_vod_remember_identify_and_start_place(self):
        vod_stream = "https://vod.sweet.tv/vod/9558/101/index.m3u8?token=secret"
        self.assertTrue(ml.remember("vod:9558", "101", vod_stream, 120, now=NOW))
        self.assertEqual(ml.identify(vod_stream, NOW), ("vod:9558", "101", 120))
        self.assertEqual(ml.start_place(vod_stream, NOW + 3)["offset"], 120)
        vod_path = "plugin://plugin.video.sweettv/playvod/9558|101|69?start=120"
        self.assertEqual(ml.identify(vod_path, NOW), ("vod:9558", "101", 120))
        self.assertEqual(ml.start_place(vod_path, NOW)["offset"], 120)
        self.assertEqual(ml.start_of(["plugin://plugin.video.sweettv/playvod/9558|101|69", "1", "?start=120"],
                                     "9558|101|69", "vod:9558", "101", now=NOW), (120, "query"))

    def test_a_place_that_cannot_be_written_says_so(self):
        self.assertFalse(ml.remember(5, 50, DVR, 10, folder=os.path.join(TMP, "blocker", "now")))
        self.assertIsNone(ml.recall(DVR, folder=os.path.join(TMP, "blocker", "now")))
        self.assertEqual([n for n in os.listdir(TMP) if n.endswith(".tmp")], [])


with open(os.path.join(TMP, "blocker"), "w", encoding="utf-8") as _f:        # a file where a directory is wanted
    _f.write("x")


class FakeKodi:
    """Kodi's player for ml.follow: a place that moves with the clock, a length, and seeks that land or not."""

    def __init__(self, file=DVR_NOW, pos=10.0, total=lambda t: 5402.0, lands=True):
        self.file, self.pos, self.total_at, self.lands = file, pos, total, lands
        self.t, self.seeks = 0.0, []

    def sleep(self, seconds):
        self.t += seconds
        self.pos += seconds

    def getPlayingFile(self):
        if isinstance(self.file, Exception):
            raise self.file
        return self.file

    def getTime(self):
        return self.pos

    def getTotalTime(self):
        return self.total_at(self.t)

    def seekTime(self, seconds):
        self.seeks.append((round(self.t, 1), seconds))
        if self.lands:
            self.pos = float(seconds)

    def run(self, offset=5348, file=DVR_NOW):
        return ml.follow(self, {"offset": offset}, file, sleep=self.sleep, clock=lambda: self.t)


class StartPlace(unittest.TestCase):
    """An archive asked to start at second N begins at 0 (Kodi ignores StartOffset): the service puts it there."""

    def test_what_to_do_from_where_the_player_is(self):
        gap = ml.SEEK_TOLERANCE
        for args, expected in (((5348, 10, 5402), ("seek", 5348)), ((5348, 5348, 5402), ("done", 0)),
                               ((5348, 5348 - gap, 5402), ("done", 0)), ((5348, 5348 - gap - 1, 5402), ("seek", 5348)),
                               ((5348, 6000, 7000), ("done", 0)),                               # past it
                               ((0, 0, 5402), ("done", 0)), ((None, 0, 5402), ("done", 0)),     # no place asked
                               ((5, 0, 0), ("done", 0)),                                         # a start inside the tolerance
                               ((5348, 10, 0), ("wait", 0)), ((5348, 10, 1), ("wait", 0)),       # the length is not known yet
                               ((5348, 10, ml.MIN_TOTAL - 1), ("wait", 0)),
                               ((5348, 10, 5340), ("seek", 5335)),                               # a programme still on: never past what is there
                               ((5348, 10, 40), ("seek", 35))):
            self.assertEqual(ml.seek_step(*args), expected, args)

    def test_who_asked_for_a_start_place(self):
        ml.remember(5, 51, DVR_NOW, 3590, now=NOW)
        ml.remember(5, "", LIVE_STREAM, 0, now=NOW)
        ml.remember(5, 50, DVR, 0, now=NOW)
        try:
            self.assertEqual(ml.start_place(DVR_NOW, NOW + 3)["offset"], 3590)
            self.assertIsNone(ml.start_place(DVR_NOW, NOW + ml.SEEK_FRESH + 1))
            self.assertIsNone(ml.start_place(DVR_NOW, NOW - 5))                                    # not from the future
            self.assertIsNone(ml.start_place(DVR, NOW))                                            # from the beginning
            self.assertIsNone(ml.start_place(LIVE_STREAM, NOW))
            self.assertIsNone(ml.start_place("https://hls-dvr2.sweet.tv/dvr/5/other/x.m3u8", NOW))   # a guess is no reason to seek
            self.assertEqual(ml.start_place("plugin://plugin.video.sweettv/playvid/5|51?ms_start=77", NOW),
                             {"cid": "5", "epg": "51", "offset": 77, "at": NOW, "sha": "", "where": ""})
            for file in (None, "", LIVE, ARCHIVE.replace("ms_start=30", "ms_start=0"), "/home/media/film.mkv"):
                self.assertIsNone(ml.start_place(file, NOW), file)
        finally:
            clean_now()

    def test_a_stream_that_began_at_the_start_is_moved_to_the_place(self):
        kodi = FakeKodi()
        self.assertEqual(kodi.run(), "done")
        self.assertEqual([s for _, s in kodi.seeks], [5348])

    def test_a_player_that_began_at_the_place_is_left_alone(self):
        kodi = FakeKodi(pos=5349.0)                       # the resume point worked
        self.assertEqual(kodi.run(), "done")
        self.assertEqual(kodi.seeks, [])

    def test_it_waits_for_the_stream_to_say_how_long_it_is(self):
        kodi = FakeKodi(total=lambda t: 0.0 if t < 3 else 5402.0)
        self.assertEqual(kodi.run(), "done")
        self.assertEqual(len(kodi.seeks), 1)
        self.assertGreaterEqual(kodi.seeks[0][0], 3)

    def test_a_length_that_never_comes_is_given_up_on_without_a_blind_seek(self):
        kodi = FakeKodi(total=lambda t: 0.0)
        self.assertEqual(kodi.run(), "gave_up")
        self.assertEqual(kodi.seeks, [])
        self.assertGreaterEqual(kodi.t, ml.SEEK_WAIT)

    def test_a_seek_that_did_not_land_is_made_again_a_few_times_not_for_ever(self):
        kodi = FakeKodi(lands=False)
        self.assertEqual(kodi.run(), "gave_up")
        self.assertEqual(len(kodi.seeks), ml.SEEK_ATTEMPTS)
        times = [t for t, _ in kodi.seeks]
        self.assertTrue(all(b - a >= ml.SEEK_RETRY for a, b in zip(times, times[1:])), times)

    def test_a_seek_that_lands_late_is_not_repeated(self):
        kodi = FakeKodi()
        kodi.late = None

        def seek(seconds):                                   # the player reports the old place for a while
            kodi.seeks.append((round(kodi.t, 1), seconds))
            kodi.late = (kodi.t + 1.5, float(seconds))
        base = kodi.sleep

        def sleep(seconds):
            base(seconds)
            if kodi.late and kodi.t >= kodi.late[0]:
                kodi.pos, kodi.late = kodi.late[1], None
        kodi.seekTime, kodi.sleep = seek, sleep
        self.assertEqual(kodi.run(), "done")
        self.assertEqual(len(kodi.seeks), 1)

    def test_something_else_playing_is_left_alone(self):
        kodi = FakeKodi(file="https://hls-dvr2.sweet.tv/dvr/5/99/index.m3u8?token=secret")
        self.assertEqual(kodi.run(), "gone")
        self.assertEqual(kodi.seeks, [])
        kodi = FakeKodi(file="plugin://plugin.video.youtube/play/?video_id=x")
        self.assertEqual(kodi.run(), "gone")

    def test_the_item_that_changes_while_it_waits_is_not_seeked(self):
        kodi = FakeKodi(total=lambda t: 0.0)
        base = kodi.sleep

        def sleep(seconds):
            base(seconds)
            if kodi.t >= 2:
                kodi.file = "/home/media/film.mkv"
        kodi.sleep = sleep
        self.assertEqual(kodi.run(), "gone")
        self.assertEqual(kodi.seeks, [])

    def test_a_stopped_player_ends_it(self):
        self.assertEqual(FakeKodi(file=RuntimeError("nothing plays")).run(), "gone")
        kodi = FakeKodi()

        def stopped():
            raise RuntimeError("stopped")
        kodi.getTime = stopped
        self.assertEqual(kodi.run(), "gone")

    def test_a_plugin_path_is_followed_like_an_address(self):
        late = "plugin://plugin.video.sweettv/playvid/5|51?ms_start=5348"
        kodi = FakeKodi(file=late)
        self.assertEqual(kodi.run(file=late), "done")
        self.assertEqual([s for _, s in kodi.seeks], [5348])
        kodi = FakeKodi(file=LIVE)
        self.assertEqual(kodi.run(file=late), "gone")

    def test_the_options_after_a_bar_do_not_make_it_another_item(self):
        kodi = FakeKodi(file=DVR_NOW + "|User-Agent=x")
        self.assertEqual(kodi.run(file=DVR_NOW), "done")
        self.assertEqual(len(kodi.seeks), 1)


class Ask(unittest.TestCase):
    """Where an archive is to start, as the add-on learns it: the query of the path wherever Kodi leaves it, else what the
    opener wrote down just before (the device log showed ms_start in the path and an offset of 0 in the add-on)."""

    def setUp(self):
        clean_now()
        self.addCleanup(clean_now)

    def test_an_ask_is_taken_once(self):
        self.assertTrue(ml.ask(5, 51, 3590, now=NOW))
        self.assertEqual(ml.take_ask(5, 51, now=NOW + 3), (3590, "used"))
        self.assertEqual(ml.take_ask(5, 51, now=NOW + 3), (0, "none"))     # a later play of the programme is not put there
        self.assertFalse(os.path.exists(os.path.join(ml.NOW_DIR, ml.ASK_FILE)))

    def test_a_stale_ask_is_no_place_and_is_gone(self):
        ml.ask("5", "51", 3590, now=NOW)
        self.assertEqual(ml.take_ask(5, 51, now=NOW + ml.ASK_FRESH), (3590, "used"))
        ml.ask("5", "51", 3590, now=NOW)
        self.assertEqual(ml.take_ask(5, 51, now=NOW + ml.ASK_FRESH + 1), (0, "stale"))
        self.assertEqual(ml.take_ask(5, 51, now=NOW + 1), (0, "none"))

    def test_an_ask_for_another_channel_or_programme_is_left_alone(self):
        ml.ask(5, 51, 3590, now=NOW)
        for cid, epg in ((6, 51), (5, 50), (5, ""), (55, 51)):
            self.assertEqual(ml.take_ask(cid, epg, now=NOW), (0, "other"), (cid, epg))
        self.assertEqual(ml.take_ask(5, 51, now=NOW), (3590, "used"))

    def test_nothing_is_asked_for_live_the_beginning_or_a_wrong_id(self):
        for cid, epg, offset in ((5, "", 300), (5, None, 300), (5, "null", 300), (5, 51, 0), (5, 51, -3), (5, 51, None), (5, 51, True),
                                 (5, 51, float("nan")), ("x", 51, 300), (5, "x", 300), ("5/../6", 51, 300)):
            self.assertFalse(ml.ask(cid, epg, offset, now=NOW), (cid, epg, offset))
        self.assertFalse(os.path.exists(os.path.join(ml.NOW_DIR, ml.ASK_FILE)))
        self.assertTrue(ml.ask(5, 51, 10 ** 12 - 1, now=NOW))
        self.assertEqual(ml.take_ask(5, 51, now=NOW), (ml.START_MAX, "used"))

    def test_the_path_that_url_made_is_asked_for(self):
        self.assertTrue(ml.ask_url(ml.url(5, 51, 3590), now=NOW))
        self.assertEqual(ml._read_ask(), {"cid": "5", "epg": "51", "offset": 3590, "at": NOW})
        clean_now()
        for path in (ml.url(5, 51), ml.url(5), LIVE, "plugin://plugin.video.youtube/play/?video_id=x", "/home/media/film.mkv", None, 5):
            self.assertFalse(ml.ask_url(path, now=NOW), path)
        self.assertIsNone(ml._read_ask())

    def test_a_folder_that_cannot_be_written_is_no_failure(self):
        blocker = os.path.join(TMP, "ask-blocker")
        with open(blocker, "w") as f:
            f.write("x")
        self.assertFalse(ml.ask(5, 51, 3590, now=NOW, folder=os.path.join(blocker, "now")))
        self.assertFalse(ml.ask_url(ml.url(5, 51, 3590), folder=os.path.join(blocker, "now")))

    def test_a_file_that_is_not_an_ask_reads_as_none(self):
        path = os.path.join(ml.NOW_DIR, ml.ASK_FILE)
        os.makedirs(ml.NOW_DIR, exist_ok=True)
        for text in ("", "not json", "[]", "{}", json.dumps({"ask": 5}), json.dumps({"ask": {"cid": "5", "epg": "51"}}),
                     json.dumps({"ask": {"cid": 5, "epg": "51", "offset": 9, "at": NOW}}),
                     json.dumps({"ask": {"cid": "5", "epg": "51", "offset": -9, "at": NOW}}),
                     json.dumps({"ask": {"cid": "5", "epg": "", "offset": 9, "at": NOW}})):
            with open(path, "w") as f:
                f.write(text)
            self.assertEqual(ml.take_ask(5, 51, now=NOW), (0, "none"), text)

    def test_ids_are_split_from_whatever_kodi_left_after_them(self):
        for videoid, expected in (("5|51", ("5", "51")), ("5|null", ("5", "null")), ("1450|932347395?ms_start=8814", ("1450", "932347395")),
                                  ("5|51&ms_start=3", ("5", "51")), ("5|51|ms_start=3", ("5", "51")), ("5|51%3Fms_start%3D3", ("5", "51")),
                                  ("5|null?ms_start=3", ("5", "null")), (" 5|51", ("5", "51")), ("5|51/", ("5", "51"))):
            self.assertEqual(ml.split_id(videoid), expected, videoid)
        for videoid in ("5", "5|", "|51", "x|51", "5|x", "5|51x", "5|-1", "", None, 5, ["5|51"]):
            self.assertIsNone(ml.split_id(videoid), videoid)

    def start(self, argv, videoid="5|51", ask=None, now=NOW, cid=5, epg=51):
        clean_now()
        if ask:
            ml.ask(*ask, now=NOW)
        return ml.start_of(argv, videoid, cid, epg, now=now)

    def test_a_place_in_the_query_of_argv2(self):
        self.assertEqual(self.start(["plugin://x/playvid/5|51", "1", "?ms_start=3590"]), (3590, "query"))
        self.assertEqual(self.start(["plugin://x/playvid/5|51", "1", "ms_start=3590&resume:false"]), (3590, "query"))

    def test_a_place_only_in_argv0(self):
        argv = ["plugin://plugin.video.sweettv/playvid/1450|932347395?ms_start=8814", "1", ""]
        self.assertEqual(self.start(argv, "1450|932347395", cid=1450, epg=932347395), (8814, "path"))
        self.assertEqual(self.start(argv[:2], "1450|932347395", cid=1450, epg=932347395), (8814, "path"))

    def test_a_place_only_in_the_id_string(self):
        argv = ["plugin://plugin.video.sweettv/playvid/", "1", ""]
        for videoid in ("5|51?ms_start=3590", "5|51&ms_start=3590", "5|51|ms_start=3590", "5|51%3Fms_start%3D3590"):
            self.assertEqual(self.start(argv, videoid), (3590, "videoid"), videoid)

    def test_a_place_in_any_other_argument(self):
        self.assertEqual(self.start(["plugin://x/playvid/", "1", "", "resume:false", "ms_start=77"]), (77, "argv"))

    def test_a_place_only_in_the_ask(self):
        self.assertEqual(self.start(["plugin://x/playvid/5|51", "1", ""], ask=(5, 51, 3590)), (3590, "ask"))
        self.assertEqual(self.start(["plugin://x/playvid/5|51"], ask=(5, 51, 3590)), (3590, "ask"))
        self.assertEqual(self.start([], ask=(5, 51, 3590)), (3590, "ask"))
        self.assertEqual(self.start(None, videoid=None, ask=(5, 51, 3590)), (3590, "ask"))

    def test_a_stale_ask_gives_no_place(self):
        argv = ["plugin://x/playvid/5|51", "1", ""]
        self.assertEqual(self.start(argv, ask=(5, 51, 3590), now=NOW + ml.ASK_FRESH + 1), (0, "none, ask stale"))

    def test_an_ask_for_another_item_gives_no_place_and_stays(self):
        argv = ["plugin://x/playvid/5|51", "1", ""]
        for ask in ((5, 50, 3590), (6, 51, 3590)):
            self.assertEqual(self.start(argv, ask=ask), (0, "none, ask other"), ask)
            self.assertIsNotNone(ml._read_ask(), ask)

    def test_no_query_and_no_ask_is_the_beginning(self):
        for argv in (["plugin://x/playvid/5|51", "1", ""], ["plugin://x/playvid/5|51", "1"], [], None, "ms_start=5", [None, 1, 2]):
            self.assertEqual(self.start(argv), (0, "none, ask none"), argv)

    def test_what_the_query_says_wins_and_the_ask_is_used_up_all_the_same(self):
        argv = ["plugin://x/playvid/5|51", "1", "?ms_start=100"]
        self.assertEqual(self.start(argv, ask=(5, 51, 3590)), (100, "query"))
        self.assertIsNone(ml._read_ask())
        self.assertEqual(ml.start_of(["plugin://x/playvid/5|51", "1", ""], "5|51", 5, 51, now=NOW), (0, "none, ask none"))

    def test_a_silly_query_is_no_place_so_the_ask_decides(self):
        for query in ("?ms_start=abc", "?ms_start=-5", "?ms_start=", "?ms_start=0", "?other=1", "ms_start=%00"):
            argv = ["plugin://x/playvid/5|51", "1", query]
            self.assertEqual(self.start(argv), (0, "none, ask none"), query)
            self.assertEqual(self.start(argv, ask=(5, 51, 40)), (40, "ask"), query)
        self.assertEqual(self.start(["x", "1", "?ms_start=99999999999999"]), (ml.START_MAX, "query"))


def dictionary():
    """The add-on's sweettv_text module, found the way the library finds it."""
    ml._words.clear()
    ml.text("Live")
    return ml._words[0]


class Texts(unittest.TestCase):
    def test_every_text_has_russian_and_ukrainian(self):
        module = dictionary()
        self.assertIsNotNone(module, "the dictionary of the add-on is found")
        self.assertTrue(module.TEXT)
        for msgid, tr in module.TEXT.items():
            for lang in ("ru", "uk"):
                self.assertTrue(isinstance(tr.get(lang), str) and tr[lang].strip(), (msgid, lang))

    def test_every_text_used_here_is_in_the_dictionary(self):
        module = dictionary()
        used = set()
        for name in ("panel_sweettv.py", "mediastick_sweetlive.py"):
            with open(os.path.join(LIB, name), encoding="utf-8") as f:
                used |= set(re.findall(r'_t\(\s*"([^"]+)"', f.read()))
                f.seek(0)
                used |= set(re.findall(r'^NO_ARCHIVE = "([^"]+)"', f.read(), re.M))
        self.assertIn("Wrong channel.", used)
        self.assertIn("No archive for this channel", used)
        self.assertEqual(sorted(m for m in used if m not in module.TEXT), [])
        with open(os.path.join(OVERLAY, "service.py"), encoding="utf-8") as f:
            self.assertIn("_ml.text(_ml.NO_ARCHIVE)", f.read())      # the TV notification goes through the dictionary

    def test_tr_answers_russian_then_english(self):
        module = dictionary()
        self.assertEqual(module.tr("Back to live"), "К эфиру")
        self.assertEqual(module.tr("No such text"), "No such text")
        self.assertEqual(ml.text("No archive for this channel"), "Архива у этого канала нет")
        self.assertEqual(ml.text("Never heard of it"), "Never heard of it")

    def test_without_the_add_on_the_msgid_itself_is_shown(self):
        saved = list(ml._words), ml.TEXT_DIRS
        ml._words.clear()
        ml.TEXT_DIRS = (os.path.join(TMP, "nothing"),)
        try:
            self.assertEqual(ml.text("No archive for this channel"), "No archive for this channel")
        finally:
            ml._words[:] = saved[0]
            ml.TEXT_DIRS = saved[1]


class Clock:
    now = float(NOW)


class Service(unittest.TestCase):
    """The service of the add-on: the player's callbacks on a live channel."""

    def make(self, playing, raw=None, place=None):
        calls, notes = [], []
        place = [0.0] if place is None else place        # where the player is, seconds; a seek moves it and is kept after it

        class Player:
            def __init__(self):
                pass

            def getPlayingFile(self):
                if isinstance(playing[0], Exception):
                    raise playing[0]
                return playing[0]

            def getTime(self):
                return place[0]

            def getTotalTime(self):
                return 7200.0

            def seekTime(self, seconds):
                place.append(seconds)
                place[0] = float(seconds)

        lib = types.ModuleType("resources.lib.sweettv")
        lib.refreshToken, lib.initSettings, lib.refreshChannelList = (lambda: True), (lambda: None), (lambda: None)
        lib.helper = types.SimpleNamespace(get_channel_list=lambda: LIST if raw is None else raw)
        fake = {"xbmc": types.SimpleNamespace(Player=Player, Monitor=object, log=lambda *a: None, LOGWARNING=2, LOGERROR=1, LOGINFO=0,
                                              executebuiltin=calls.append),
                "xbmcgui": types.SimpleNamespace(NOTIFICATION_INFO="info",
                                                 Dialog=lambda: types.SimpleNamespace(notification=lambda *a: notes.append(a))),
                "resources": types.ModuleType("resources"), "resources.lib": types.ModuleType("resources.lib"),
                "resources.lib.helper": types.SimpleNamespace(Helper=lambda: object()), "resources.lib.sweettv": lib,
                "mediastick_sweetlive": ml}
        Clock.now = float(NOW)
        with mock.patch.dict(sys.modules, fake), mock.patch.object(time, "time", lambda: Clock.now):
            space = runpy.run_path(os.path.join(OVERLAY, "service.py"), run_name="sweet_service")
        return space["_MsPlayer"](), calls, notes

    def run_at(self, fn, *args):
        with mock.patch.object(time, "time", lambda: Clock.now):
            return fn(*args)

    def test_a_seek_back_on_a_live_channel_plays_the_archive_of_the_programme(self):
        player, calls, notes = self.make([LIVE])
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(calls, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590)"])
        self.assertEqual(notes, [])

    def test_the_place_is_written_down_before_the_archive_is_opened_from_the_tv(self):
        clean_now()
        self.addCleanup(clean_now)
        player, calls, _ = self.make([LIVE])
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(ml._read_ask(), {"cid": "5", "epg": "51", "offset": 3590, "at": NOW})
        self.assertEqual(len(calls), 1)
        clean_now()
        player, calls, _ = self.make([LIVE])
        self.run_at(player.onPlayBackPaused)
        Clock.now += 45
        self.run_at(player.onPlayBackResumed)
        self.assertEqual(ml._read_ask()["offset"], 3600)

    def test_nothing_is_written_down_when_nothing_is_opened(self):
        clean_now()
        self.addCleanup(clean_now)
        player, calls, _ = self.make(["plugin://plugin.video.sweettv/playvid/6|null"])      # no archive
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(calls, [])
        self.assertIsNone(ml._read_ask())

    def test_a_seek_forward_or_on_an_archive_or_on_something_else_does_nothing(self):
        for playing, offset in ((LIVE, 10000), (LIVE, 0), (ARCHIVE, -10000), ("plugin://plugin.video.youtube/play/?video_id=x", -10000),
                                ("/home/media/film.mkv", -10000), (OSError("no player"), -10000), (None, -10000)):
            player, calls, notes = self.make([playing])
            self.run_at(player.onPlayBackSeek, 0, offset)
            self.assertEqual((calls, notes), ([], []), (playing, offset))

    def test_a_held_key_is_one_rewind(self):
        player, calls, _ = self.make([LIVE])
        for _ in range(5):
            self.run_at(player.onPlayBackSeek, 0, -10000)
            Clock.now += 1
        self.assertEqual(len(calls), 1)
        Clock.now += 10
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(len(calls), 2)

    def test_no_archive_says_so_and_plays_nothing(self):
        player, calls, notes = self.make(["plugin://plugin.video.sweettv/playvid/6|null"])
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(calls, [])
        self.assertEqual([n[:3] for n in notes], [("SWEET.TV", "Архива у этого канала нет", "info")])

    def test_an_unreadable_list_is_not_a_crash(self):
        for raw in ({}, [], "x"):
            player, calls, notes = self.make([LIVE], raw=raw)
            self.run_at(player.onPlayBackSeek, 0, -10000)
            self.assertEqual(calls, [])

    def test_a_pause_longer_than_the_window_goes_to_the_archive_on_resume(self):
        player, calls, _ = self.make([LIVE])
        self.run_at(player.onPlayBackPaused)
        Clock.now += 45
        self.run_at(player.onPlayBackResumed)
        # back to where the picture stopped: 3600 s into the programme, however long the pause was
        self.assertEqual(calls, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|51?ms_start=3600)"])

    def test_a_short_pause_or_a_pause_on_something_else_is_left_alone(self):
        for playing, wait in ((LIVE, 10), (LIVE, ml.PAUSE_LIMIT), (ARCHIVE, 600), ("/home/media/film.mkv", 600)):
            player, calls, notes = self.make([playing])
            self.run_at(player.onPlayBackPaused)
            Clock.now += wait
            self.run_at(player.onPlayBackResumed)
            self.assertEqual((calls, notes), ([], []), (playing, wait))

    def test_a_stopped_player_forgets_the_pause(self):
        player, calls, _ = self.make([LIVE])
        self.run_at(player.onPlayBackPaused)
        self.run_at(player.onPlayBackStopped)
        Clock.now += 600
        self.run_at(player.onPlayBackResumed)
        self.assertEqual(calls, [])

    def test_a_live_stream_known_by_its_address_is_rewound_like_one_known_by_its_path(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.remember(5, "", LIVE_STREAM, 0)
        player, calls, notes = self.make([LIVE_STREAM])
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(calls, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590)"])
        ml.remember(5, 50, DVR, 0)
        player, calls, notes = self.make([DVR])                       # an archive is not rewound to an archive
        self.run_at(player.onPlayBackSeek, 0, -10000)
        self.assertEqual(calls, [])

    def started(self, playing, remembered=(), late=0, place=None):
        """onAVStarted of a player that plays `playing`, with the threads of the service run at once."""
        clean_now()
        self.addCleanup(clean_now)
        for cid, epg, url, offset in remembered:
            ml.remember(cid, epg, url, offset, now=NOW)
        place = [10.0] if place is None else place
        player, calls, notes = self.make([playing], place=place)
        threads = []

        class Thread:
            def __init__(self, target, args=(), daemon=None):
                self.target, self.args, self.daemon = target, args, daemon
                threads.append(self)

            def start(self):
                self.target(*self.args)

        Clock.now = float(NOW + late)
        with mock.patch("threading.Thread", Thread), mock.patch.object(time, "sleep", lambda s: None):
            self.run_at(player.onAVStarted)
        return place, threads

    def test_an_archive_asked_to_start_late_is_put_there_once_it_plays(self):
        place, threads = self.started(DVR_NOW, [(5, 51, DVR_NOW, 3590)])
        self.assertEqual(place[1:], [3590])
        self.assertEqual(place[0], 3590.0)
        self.assertEqual([t.daemon for t in threads], [True])         # it never holds Kodi back

    def test_an_archive_the_player_names_by_its_plugin_path_is_put_there_by_the_path(self):
        late = "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590"
        place, threads = self.started(late)                           # no entry: the path carries the place itself
        self.assertEqual(place[1:], [3590])
        for path in ("plugin://plugin.video.sweettv/playvid/5|51", "plugin://plugin.video.sweettv/playvid/5|null?ms_start=300", LIVE):
            place, threads = self.started(path)
            self.assertEqual((place, threads), ([10.0], []), path)

    def test_an_archive_that_began_where_it_was_asked_is_not_moved(self):
        place, _ = self.started(DVR_NOW, [(5, 51, DVR_NOW, 3590)], place=[3592.0])
        self.assertEqual(place, [3592.0])

    def test_nothing_is_done_for_what_nobody_asked_to_start_late(self):
        old = ml.SEEK_FRESH + 1
        cases = [(DVR_NOW, [(5, 51, DVR_NOW, 0)], 0),                  # from the beginning
                 (DVR_NOW, [], 0),                                     # nobody wrote it down
                 (DVR_NOW, [(5, 51, DVR_NOW, 3590)], old),             # an old entry is not a start someone waits for
                 (LIVE_STREAM, [(5, "", LIVE_STREAM, 0)], 0),          # live has no place
                 (DVR, [(5, 51, DVR_NOW, 3590)], 0),                   # another stream plays
                 ("/home/media/film.mkv", [(5, 51, DVR_NOW, 3590)], 0),
                 ("plugin://plugin.video.youtube/play/?video_id=x", [], 0),
                 (OSError("no player"), [(5, 51, DVR_NOW, 3590)], 0), (None, [], 0)]
        for playing, remembered, late in cases:
            place, threads = self.started(playing, remembered, late)
            self.assertEqual((place, threads), ([10.0], []), (playing, remembered, late))

    def test_a_failure_in_the_start_place_does_not_reach_kodi(self):
        with mock.patch.object(ml, "follow", side_effect=ValueError("boom")):
            place, threads = self.started(DVR_NOW, [(5, 51, DVR_NOW, 3590)])
        self.assertEqual(place, [10.0])
        self.assertEqual(len(threads), 1)

    def test_forward_seek_on_in_progress_epg_near_live_edge_switches_to_live_but_finished_archive_does_not(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.remember(5, 51, DVR_NOW, 0, now=NOW)
        player, calls, _ = self.make([DVR_NOW], place=[3590.0])
        self.run_at(player.onPlayBackSeek, 3590, 0)
        self.assertEqual(calls, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|null)"])

        ml.remember(5, 50, DVR, 0, now=NOW)
        player, calls, _ = self.make([DVR], place=[3590.0])
        self.run_at(player.onPlayBackSeek, 3590, 0)
        self.assertEqual(calls, [])

    def test_playback_ended_on_archive_continues_to_next_programme(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.remember(5, 50, DVR, 0, now=NOW)
        player, calls, _ = self.make([DVR])
        self.run_at(player.onPlayBackEnded)
        self.assertEqual(calls, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|51)"])

    def test_a_device_without_the_library_leaves_the_add_on_as_upstream(self):
        lib = types.ModuleType("resources.lib.sweettv")
        lib.refreshToken, lib.initSettings, lib.refreshChannelList = (lambda: True), (lambda: None), (lambda: None)
        fake = {"xbmc": types.SimpleNamespace(Player=object, Monitor=object, log=lambda *a: None, LOGWARNING=2, LOGERROR=1),
                "xbmcgui": types.SimpleNamespace(), "resources": types.ModuleType("resources"),
                "resources.lib": types.ModuleType("resources.lib"),
                "resources.lib.helper": types.SimpleNamespace(Helper=lambda: object()), "resources.lib.sweettv": lib,
                "mediastick_sweetlive": None}
        with mock.patch.dict(sys.modules, fake), mock.patch.object(sys, "path", [p for p in sys.path if p != LIB]):
            space = runpy.run_path(os.path.join(OVERLAY, "service.py"), run_name="sweet_service")
        self.assertIsNone(space["_ml"])


class AddOn(unittest.TestCase):
    """sweettv.py: where an archived programme starts, how long it is, and the way back to live."""

    def item(self, videoid, query, argv=None):
        """The item the add-on resolves for playvid/<videoid> when Kodi calls it with this query string (or, when `argv` is
        given, with these arguments)."""
        log = []
        plugin = play_tests.kodi_plugin(log)
        helper = type("H", (play_tests.PlayHelper,), {"resolved": [], "channel_list": LIST, "plugin": plugin})
        sweet = stubs.load_sweettv(helper_class=helper, xbmcplugin=plugin)
        stubs.Settings.values.update(logged=True, bearer="Bearer x", playerType="ffmpeg")
        sweet.time = types.SimpleNamespace(time=lambda: NOW)
        argv = ["plugin://plugin.video.sweettv/playvid/" + videoid, "1", query] if argv is None else argv
        with mock.patch.object(sys, "argv", argv):
            sweet.playvid(videoid)
        self.assertEqual(len(log), 1)
        return log[0][2], sweet

    def started_at(self, sweet):
        """The one line of the log that tells where the start place came from."""
        lines = [msg for level, msg in sweet.logs if "asked to start" in msg]
        self.assertEqual(len(lines), 1, sweet.logs)
        return lines[0]

    def test_where_the_start_place_came_from_is_in_the_log(self):
        item, sweet = self.item("5|51", "?ms_start=3590")
        self.assertEqual([(level, msg) for level, msg in sweet.logs if "asked to start" in msg],
                         [(stubs.INFO, "media-stick: SWEET.TV archive 5|51 asked to start at 3590s (query)")])
        item, sweet = self.item("5|51", "")
        self.assertIn("at 0s (none, ask none)", self.started_at(sweet))
        item, sweet = self.item("5|null", "?ms_start=300")      # live is not asked about
        self.assertEqual([m for _, m in sweet.logs if "asked to start" in m], [])

    def test_a_place_only_in_the_plugin_path_is_the_place(self):
        """The device: the offset was 0 although the path carried ms_start."""
        clean_now()
        self.addCleanup(clean_now)
        for argv in (["plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590", "1", ""],
                     ["plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590", "1"]):
            item, sweet = self.item("5|51", "", argv=argv)
            self.assertEqual(item.props, {"ResumeTime": "3590", "TotalTime": "7200"})
            self.assertIn("at 3590s (path)", self.started_at(sweet))
            self.assertEqual(ml.recall(play_tests.STREAM_URL)["offset"], 3590)

    def test_a_query_that_leaked_into_the_id_is_a_place_and_not_the_programme(self):
        """The id is "5|51?ms_start=3590": upstream would ask SWEET.TV for epg_id int("51?ms_start=3590") and fail."""
        clean_now()
        self.addCleanup(clean_now)
        for videoid in ("5|51?ms_start=3590", "5|51|ms_start=3590"):
            item, sweet = self.item(videoid, "", argv=["plugin://plugin.video.sweettv/playvid/", "1", ""])
            self.assertEqual(item.props, {"ResumeTime": "3590", "TotalTime": "7200"}, videoid)
            self.assertEqual(item.label, "Холостяк", videoid)
            self.assertIn("archive 5|51 asked to start at 3590s (videoid)", self.started_at(sweet), videoid)
            entry = ml.recall(play_tests.STREAM_URL)
            self.assertEqual((entry["cid"], entry["epg"], entry["offset"]), ("5", "51", 3590), videoid)

    def test_a_place_only_in_the_ask_is_the_place_and_is_used_once(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.ask(5, 51, 3590, now=NOW)
        item, sweet = self.item("5|51", "")
        self.assertEqual(item.props, {"ResumeTime": "3590", "TotalTime": "7200"})
        self.assertIn("at 3590s (ask)", self.started_at(sweet))
        entry = ml.recall(play_tests.STREAM_URL)
        self.assertEqual((entry["cid"], entry["epg"], entry["offset"]), ("5", "51", 3590))     # remembered, for the service's seek
        item, sweet = self.item("5|51", "")                  # the same programme, started from the TV a moment later
        self.assertEqual(item.props, {"TotalTime": "7200"})
        self.assertEqual(ml.recall(play_tests.STREAM_URL)["offset"], 0)

    def test_an_ask_that_is_old_or_for_another_item_is_no_place(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.ask(5, 51, 3590, now=NOW - ml.ASK_FRESH - 1)
        item, _ = self.item("5|51", "")
        self.assertEqual(item.props, {"TotalTime": "7200"})
        ml.ask(5, 50, 3590, now=NOW)
        item, _ = self.item("5|51", "")                    # asked for another programme of the channel
        self.assertEqual(item.props, {"TotalTime": "7200"})
        self.assertEqual(ml._read_ask()["epg"], "50")      # and left for the one it is for
        item, _ = self.item("5|50", "")
        self.assertEqual(item.props, {"ResumeTime": "3590", "TotalTime": "3600"})

    def test_an_ask_is_not_used_up_by_live(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.ask(5, 51, 3590, now=NOW)
        item, _ = self.item("5|null", "")
        self.assertEqual(item.props, {})
        item, _ = self.item("5|51", "")
        self.assertEqual(item.props["ResumeTime"], "3590")

    def test_an_archive_starts_where_the_query_says_and_is_as_long_as_the_programme(self):
        item, _ = self.item("5|51", "?ms_start=3590")
        # Kodi ignores StartOffset of a resolved plugin item; the resume point is what it starts from
        self.assertEqual(item.props, {"ResumeTime": "3590", "TotalTime": "7200"})
        self.assertNotIn("StartOffset", item.props)

    def test_an_archive_without_a_place_starts_at_the_beginning(self):
        item, _ = self.item("5|50", "")
        self.assertEqual(item.props, {"TotalTime": "3600"})

    def test_live_gets_neither_a_start_nor_a_length(self):
        item, _ = self.item("5|null", "?ms_start=300")
        self.assertEqual(item.props, {})

    def test_a_silly_start_is_no_start(self):
        for query in ("?ms_start=abc", "?ms_start=-5", "?ms_start=", "?other=1", "ms_start=%00"):
            item, _ = self.item("5|50", query)
            self.assertNotIn("ResumeTime", item.props, query)
        item, _ = self.item("5|50", "?ms_start=99999999999999")
        self.assertEqual(item.props["ResumeTime"], str(3 * 86400))

    def test_what_the_stream_is_is_written_down_for_the_player_to_find(self):
        """The player will be given the address of the stream, not the plugin path: the entry says which programme it is
        and where it was asked to start (the service's seek and the phone's "now playing" read it)."""
        clean_now()
        self.addCleanup(clean_now)
        self.item("5|51", "?ms_start=3590")
        entry = ml.recall(play_tests.STREAM_URL)
        self.assertEqual((entry["cid"], entry["epg"], entry["offset"]), ("5", "51", 3590))
        self.item("5|null", "")
        entry = ml.recall(play_tests.STREAM_URL)
        self.assertEqual((entry["cid"], entry["epg"], entry["offset"]), ("5", "", 0))

    def test_a_stream_that_cannot_be_written_down_is_still_played(self):
        with mock.patch.object(ml, "NOW_DIR", os.path.join(TMP, "blocker", "now")):
            item, _ = self.item("5|51", "?ms_start=3590")
        self.assertEqual(item.props["ResumeTime"], "3590")

    def test_golive_knows_an_archive_by_the_address_of_its_stream(self):
        clean_now()
        self.addCleanup(clean_now)
        ml.remember(5, 50, DVR, 0)
        ml.remember(5, "", LIVE_STREAM, 0)
        sweet = stubs.load_sweettv()
        commands = []
        back = ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|null)"]
        for label, playing, expected in (("", DVR, back), (DVR, DVR, back), ("", LIVE_STREAM, []),
                                         ("", "https://example.org/other.m3u8", []), ("", "", []),
                                         ("", OSError("nothing plays"), [])):
            commands.clear()

            def playing_file(playing=playing):
                if isinstance(playing, Exception):
                    raise playing
                return playing
            sweet.xbmc = types.SimpleNamespace(getInfoLabel=lambda name, label=label: label, executebuiltin=commands.append,
                                               log=lambda *a: None, LOGWARNING=2,
                                               Player=lambda: types.SimpleNamespace(getPlayingFile=playing_file))
            sweet.ms_golive()
            self.assertEqual(commands, expected, (label, playing))

    def test_golive_plays_the_channel_live_only_from_an_archive(self):
        sweet = stubs.load_sweettv()
        commands = []
        for path, expected in ((ARCHIVE, ["PlayMedia(plugin://plugin.video.sweettv/playvid/5|null)"]), (LIVE, []),
                               ("/home/media/film.mkv", []), ("plugin://plugin.video.sweettv/playvid/x|5", []), ("", [])):
            commands.clear()
            sweet.xbmc = types.SimpleNamespace(getInfoLabel=lambda label: path, executebuiltin=commands.append,
                                               log=lambda *a: None, LOGWARNING=2)
            sweet.ms_golive()
            self.assertEqual(commands, expected, path)


def use_list(test):
    """The add-on's channel list as a file the panel reads (with ballast, like the real one)."""
    ps._slim_cache.update(key=None, value=None)
    test.path = os.path.join(TMP, "channelList.json")
    with open(test.path, "w", encoding="utf-8") as f:
        json.dump(dict(LIST, junk=["x" * 1000] * 50), f)
    test.addCleanup(setattr, pw, "_sweet_list_path", pw._sweet_list_path)
    pw._sweet_list_path = lambda: test.path
    pw._cache.clear()


class Panel(unittest.TestCase):
    def setUp(self):
        use_list(self)

    def view(self, **kw):
        base = {"playing": True, "title": "x", "live": False, "cid": "", "epg": ""}
        base.update(kw)
        return base

    def test_the_list_is_kept_small(self):
        raw = ps.slim(dict(LIST, junk="x", list=LIST["list"] + [{"id": 8, "icon_url": "u" * 500, "is_fast_channel": True,
                                                                 "banner_url": "https://img.example/b.jpg",
                                                                 "epg": [dict(SHOW, external_ids=[1] * 99)]}]))
        self.assertEqual(sorted(raw), ["categories", "list"])
        self.assertNotIn("junk", raw)
        self.assertTrue(raw["list"][-1]["is_fast_channel"])
        self.assertEqual(raw["list"][-1]["banner_url"], "https://img.example/b.jpg")
        self.assertNotIn("logo_url", ps.slim({"list": [{"id": 9, "logo_url": "x"}]})["list"][0])
        self.assertNotIn("external_ids", raw["list"][-1]["epg"][0])
        self.assertEqual(ps.slim(None), {"list": [], "categories": []})
        self.assertEqual(ps.slim({"list": [None, 3, {"name": "no id"}]}), {"list": [], "categories": []})

    def test_the_list_is_read_again_only_when_the_file_changes(self):
        first = ps.channels()
        self.assertEqual(first["list"][0]["id"], 5)
        self.assertIs(ps.channels(), first)
        os.remove(self.path)
        self.assertEqual(ps.channels(), {})

    def test_now_playing_live_with_an_archive(self):
        view = ps.decorate(self.view(live=True, cid="5"), LIST, NOW)
        self.assertEqual((view["programme"], view["can_rewind"], view["go_live"]), ("Холостяк", True, False))

    def test_now_playing_live_without_an_archive_cannot_rewind(self):
        view = ps.decorate(self.view(live=True, cid="6"), LIST, NOW)
        self.assertEqual((view["programme"], view["can_rewind"], view["go_live"]), ("Новости", False, False))

    def test_now_playing_an_archive_offers_the_way_back_to_live(self):
        view = ps.decorate(self.view(cid="5", epg="50"), LIST, NOW)
        self.assertEqual((view["programme"], view["can_rewind"], view["go_live"]), ("Утро", False, True))

    def test_now_playing_something_else_is_left_as_it_is(self):
        view = ps.decorate(self.view(app="youtube"), LIST, NOW)
        self.assertEqual((view["programme"], view["can_rewind"], view["go_live"]), ("", False, False))
        view = ps.decorate(self.view(live=True, cid="99"), {}, NOW)
        self.assertEqual((view["programme"], view["can_rewind"], view["go_live"]), ("", False, False))

    def test_minus_ten_on_live_is_an_archive_from_a_place(self):
        found = ps.rewind(LIST, LIVE, -10, NOW)
        self.assertEqual(found, {"switched": "archive", "url": "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590",
                                 "epg": "51", "offset": 3590})
        self.assertEqual(ps.rewind(LIST, LIVE, -10 ** 9, NOW)["offset"], 0)

    def test_minus_ten_on_live_without_an_archive_says_so(self):
        found = ps.rewind(LIST, "plugin://plugin.video.sweettv/playvid/6|null", -10, NOW)
        self.assertEqual(found, {"switched": "", "note": "Архива у этого канала нет"})
        self.assertEqual(ps.rewind(LIST, "plugin://plugin.video.sweettv/playvid/99|null", -10, NOW), {"switched": "", "note": ""})

    def test_everything_else_is_an_ordinary_seek(self):
        for file, by in ((LIVE, 10), (LIVE, 0), (ARCHIVE, -10), ("plugin://plugin.video.youtube/play/?video_id=x", -10), (None, -10), ("", -10)):
            self.assertIsNone(ps.rewind(LIST, file, by, NOW), (file, by))

    def test_play_from_the_start_from_the_live_place_from_a_second(self):
        self.assertEqual(ps.play_request(LIST, {"cid": 5, "epg": 51}, NOW),
                         ("plugin://plugin.video.sweettv/playvid/5|51", "51", 0))
        self.assertEqual(ps.play_request(LIST, {"cid": "5", "epg": "51", "at": "now"}, NOW)[2], 3600)
        url, epg, offset = ps.play_request(LIST, {"cid": 5, "epg": 50, "at": 125.7}, NOW)
        self.assertEqual((url, offset), ("plugin://plugin.video.sweettv/playvid/5|50?ms_start=125", 125))
        self.assertEqual(ps.play_request(LIST, {"cid": 5, "epg": 50, "at": 10 ** 6}, NOW)[2], 3599)
        self.assertEqual(ps.play_request(LIST, {"cid": 5, "epg": 50, "at": -5}, NOW)[2], 0)
        self.assertEqual(ps.play_request(LIST, {"cid": 5}, NOW), (LIVE, "", 0))
        self.assertEqual(ps.play_request(LIST, {"cid": 5, "epg": None}, NOW), (LIVE, "", 0))

    def test_play_refuses(self):
        for body, code in (({}, 400), ({"cid": "x"}, 400), ({"cid": True}, 400), ({"cid": 5, "epg": "x"}, 400), ({"cid": 5, "epg": 777}, 404),
                           ({"cid": 99, "epg": 50}, 404), ({"cid": 5, "epg": 52}, 409), ({"cid": 6, "epg": 60}, 409),
                           ({"cid": 5, "epg": 50, "at": "later"}, 400), ({"cid": 5, "epg": 50, "at": True}, 400),
                           ({"cid": 5, "epg": 50, "at": float("nan")}, 400), (None, 400), ("5|50", 400)):
            with self.assertRaises(pw.Refused, msg=body) as caught:
                ps.play_request(LIST, body, NOW)
            self.assertEqual(caught.exception.code, code, body)

    def test_an_archive_older_than_the_channel_keeps_is_refused(self):
        raw = {"list": [{"id": 5, "catchup": True, "catchup_duration": 1, "epg": [dict(SHOW, time_start=NOW - 3 * 86400, time_stop=NOW - 3 * 86400 + 600)]}]}
        with self.assertRaises(pw.Refused):
            ps.play_request(raw, {"cid": 5, "epg": 51}, NOW)

    def test_refusals_are_in_the_language_of_the_page(self):
        with self.assertRaises(pw.Refused) as caught:
            ps.play_request(LIST, {"cid": "x"}, NOW)
        self.assertEqual(caught.exception.message, "Неверный канал.")


class Routes(unittest.TestCase):
    def setUp(self):
        self.calls, self.playing = [], {"file": ARCHIVE}
        use_list(self)

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        if method == "Player.GetActivePlayers":
            return [{"playerid": 1, "type": "video"}]
        if method == "Player.GetItem":
            return {"item": self.playing}
        return {}

    def known(self, *entries):
        clean_now()
        self.addCleanup(clean_now)
        for cid, epg, url in entries:
            ml.remember(cid, epg, url, 0)

    def rpc_of(self, item):
        def rpc(method, params=None):
            self.calls.append((method, params))
            return {"Player.GetActivePlayers": [{"playerid": 1, "type": "video"}], "Player.GetItem": {"item": item},
                    "Player.GetProperties": {"time": {"minutes": 1}, "totaltime": {"hours": 1, "minutes": 30, "seconds": 2}},
                    "Application.GetProperties": {"volume": 50, "muted": False}}.get(method, {})
        return rpc

    def test_an_archive_that_the_player_gives_as_a_stream_address_is_still_the_programme(self):
        """What the owner saw: file was the https address, so live false, no epg, no programme, no way back to live."""
        self.known((5, 50, DVR))
        item = {"file": DVR, "label": "Утро", "title": "Утро", "showtitle": "", "thumbnail": ""}
        with mock.patch.object(time, "time", lambda: NOW):
            state = pw.now_state(self.rpc_of(item))
        self.assertEqual((state["live"], state["cid"], state["epg"], state["title"]), (False, "5", "50", "Утро"))
        self.assertEqual((state["programme"], state["go_live"], state["can_rewind"]), ("Утро", True, False))
        self.assertEqual((state["channel"], state["app"]), ("Первый канал", "sweettv"))

    def test_a_live_channel_that_the_player_gives_as_a_stream_address_is_still_live(self):
        self.known((5, "", LIVE_STREAM))
        item = {"file": LIVE_STREAM, "label": "Первый канал", "title": "Первый канал", "showtitle": "Первый канал"}
        with mock.patch.object(time, "time", lambda: NOW):
            state = pw.now_state(self.rpc_of(item))
        self.assertEqual((state["live"], state["cid"], state["epg"], state["programme"], state["can_rewind"], state["go_live"]),
                         (True, "5", "", "Холостяк", True, False))

    def test_a_stream_nobody_wrote_down_is_not_sweettv(self):
        self.known((5, 50, DVR))
        for file in ("https://hls-dvr2.sweet.tv/dvr/5/77/index.m3u8?token=x", "https://example.org/a.m3u8", "/home/media/film.mkv"):
            with mock.patch.object(time, "time", lambda: NOW):
                state = pw.now_state(self.rpc_of({"file": file, "label": "x", "title": "x"}))
            self.assertEqual((state["live"], state["cid"], state["epg"], state["go_live"], state["app"]),
                             (False, "", "", False, "other"), file)

    def test_golive_from_an_archive_that_is_a_stream_address(self):
        self.known((5, 50, DVR))
        body, code = ps.post("/api/sweettv/golive", {}, self.rpc_of({"file": DVR}))
        self.assertEqual((code, body), (200, {"ok": True}))
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": LIVE}}))

    def test_golive_is_refused_for_a_live_stream_address_and_for_one_nobody_wrote_down(self):
        self.known((5, "", LIVE_STREAM), (5, 50, DVR))
        for file in (LIVE_STREAM, "https://example.org/a.m3u8"):
            self.calls.clear()
            body, code = ps.post("/api/sweettv/golive", {}, self.rpc_of({"file": file}))
            self.assertEqual(code, 409, file)
            self.assertNotIn("Player.Open", [m for m, _ in self.calls])

    def test_minus_ten_on_a_live_stream_address_opens_the_archive(self):
        self.known((5, "", LIVE_STREAM))
        with mock.patch.object(time, "time", lambda: NOW):
            body, code = pw.post("/api/watch/ctl", {"op": "seek", "by": -10}, self.rpc_of({"file": LIVE_STREAM}))
        self.assertEqual((code, body), (200, {"ok": True, "switched": "archive", "epg": "51", "offset": 3590}))
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590"}}))

    def test_minus_ten_in_an_archive_that_is_a_stream_address_is_an_ordinary_seek(self):
        self.known((5, 50, DVR))
        body, code = pw.post("/api/watch/ctl", {"op": "seek", "by": -10}, self.rpc_of({"file": DVR}))
        self.assertEqual((code, body), (200, {"ok": True}))
        self.assertEqual(self.calls[-1][0], "Player.Seek")
        self.assertNotIn("Player.Open", [m for m, _ in self.calls])

    def test_minus_ten_on_live_opens_the_archive_and_does_not_seek(self):
        self.playing = {"file": LIVE}
        with mock.patch.object(time, "time", lambda: NOW):
            body, code = pw.post("/api/watch/ctl", {"op": "seek", "by": -10}, self.rpc)
        self.assertEqual((code, body), (200, {"ok": True, "switched": "archive", "epg": "51", "offset": 3590}))
        methods = [m for m, _ in self.calls]
        self.assertIn("Player.Open", methods)
        self.assertNotIn("Player.Seek", methods)
        self.assertEqual(self.calls[-1][1], {"item": {"file": "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3590"}})

    def test_minus_ten_on_live_without_an_archive_seeks_and_says_why_it_is_short(self):
        self.playing = {"file": "plugin://plugin.video.sweettv/playvid/6|null"}
        with mock.patch.object(time, "time", lambda: NOW):
            body, code = pw.post("/api/watch/ctl", {"op": "seek", "by": -10}, self.rpc)
        self.assertEqual((code, body), (200, {"ok": True, "switched": "", "note": "Архива у этого канала нет"}))
        self.assertEqual(self.calls[-1], ("Player.Seek", {"playerid": 1, "value": {"seconds": -10}}))

    def test_other_seeks_are_what_they_were(self):
        for file, request in ((LIVE, {"op": "seek", "by": 10}), (ARCHIVE, {"op": "seek", "by": -10}), (LIVE, {"op": "seek", "to": 5}),
                              ("/home/media/film.mkv", {"op": "seek", "by": -10})):
            self.calls.clear()
            self.playing = {"file": file}
            body, code = pw.post("/api/watch/ctl", request, self.rpc)
            self.assertEqual((code, body), (200, {"ok": True}), request)
            self.assertEqual(self.calls[-1][0], "Player.Seek")
            self.assertNotIn("Player.Open", [m for m, _ in self.calls])

    def test_play_opens_the_archive_where_asked(self):
        with mock.patch.object(time, "time", lambda: NOW):
            body, code = ps.post("/api/sweettv/play", {"cid": 5, "epg": 51, "at": "now"}, self.rpc)
        self.assertEqual((code, body), (200, {"ok": True, "epg": "51", "offset": 3600}))
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": "plugin://plugin.video.sweettv/playvid/5|51?ms_start=3600"}}))

    def test_play_from_a_place_writes_down_the_place_before_it_opens(self):
        clean_now()
        self.addCleanup(clean_now)
        seen = []

        def rpc(method, params=None):
            seen.append((method, ml._read_ask()))              # what is written down at the moment the player is asked to open
            return self.rpc(method, params)
        with mock.patch.object(time, "time", lambda: NOW):
            ps.post("/api/sweettv/play", {"cid": 5, "epg": 51, "at": "now"}, rpc)
        asked = {"cid": "5", "epg": "51", "offset": 3600, "at": NOW}
        self.assertEqual([a for m, a in seen if m == "Player.Open"], [asked])
        self.assertEqual(ml._read_ask(), asked)

    def test_play_from_the_beginning_or_live_or_refused_asks_for_nothing(self):
        clean_now()
        self.addCleanup(clean_now)
        for body in ({"cid": 5, "epg": 51}, {"cid": 5}, {"cid": 5, "epg": 777, "at": 100}, {"cid": 5, "epg": 52, "at": 100}):
            with mock.patch.object(time, "time", lambda: NOW):
                ps.post("/api/sweettv/play", body, self.rpc)
            self.assertIsNone(ml._read_ask(), body)

    def test_the_place_given_in_seconds_is_asked_for_too(self):
        clean_now()
        self.addCleanup(clean_now)
        with mock.patch.object(time, "time", lambda: NOW):
            ps.post("/api/sweettv/play", {"cid": 5, "epg": 50, "at": 1200}, self.rpc)
        self.assertEqual(ml._read_ask()["offset"], 1200)
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": "plugin://plugin.video.sweettv/playvid/5|50?ms_start=1200"}}))

    def test_minus_ten_writes_down_the_place_before_it_opens(self):
        clean_now()
        self.addCleanup(clean_now)
        self.playing = {"file": LIVE}
        seen = []

        def rpc(method, params=None):
            seen.append((method, ml._read_ask()))
            return self.rpc(method, params)
        with mock.patch.object(time, "time", lambda: NOW):
            pw.post("/api/watch/ctl", {"op": "seek", "by": -10}, rpc)
        asked = {"cid": "5", "epg": "51", "offset": 3590, "at": NOW}
        self.assertEqual([a for m, a in seen if m == "Player.Open"], [asked])

    def test_ordinary_seeks_and_the_way_back_to_live_ask_for_nothing(self):
        clean_now()
        self.addCleanup(clean_now)
        for file, request in ((LIVE, {"op": "seek", "by": 10}), (ARCHIVE, {"op": "seek", "by": -10}),
                              ("plugin://plugin.video.sweettv/playvid/6|null", {"op": "seek", "by": -10})):
            self.playing = {"file": file}
            with mock.patch.object(time, "time", lambda: NOW):
                pw.post("/api/watch/ctl", request, self.rpc)
        self.playing = {"file": ARCHIVE}
        ps.post("/api/sweettv/golive", {}, self.rpc)
        self.assertIsNone(ml._read_ask())

    def test_play_refused_is_an_error_and_opens_nothing(self):
        body, code = ps.post("/api/sweettv/play", {"cid": 5, "epg": 777}, self.rpc)
        self.assertEqual(code, 404)
        self.assertIn("error", body)
        self.assertEqual(self.calls, [])

    def test_golive_opens_the_live_stream_of_the_archived_channel(self):
        body, code = ps.post("/api/sweettv/golive", {}, self.rpc)
        self.assertEqual((code, body), (200, {"ok": True}))
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": LIVE}}))

    def test_golive_needs_an_archive_playing(self):
        for file in (LIVE, "/home/media/film.mkv", "plugin://plugin.video.youtube/play/?video_id=x"):
            self.calls.clear()
            self.playing = {"file": file}
            body, code = ps.post("/api/sweettv/golive", {}, self.rpc)
            self.assertEqual(code, 409, file)
            self.assertNotIn("Player.Open", [m for m, _ in self.calls])
        self.calls.clear()
        body, code = ps.post("/api/sweettv/golive", {}, lambda m, p=None: [] if m == "Player.GetActivePlayers" else {})
        self.assertEqual(code, 409)

    def test_unknown_routes(self):
        self.assertEqual(ps.post("/api/sweettv/nothing", {}, self.rpc)[1], 404)
        self.assertEqual(ps.get("/api/sweettv/nothing", self.rpc)[1], 404)

    def test_the_panel_hands_the_routes_over_with_two_lines(self):
        with open(os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("import panel_sweettv", source)
        self.assertEqual(source.count("panel_sweettv.PREFIX"), 2)
        self.assertEqual(source.count("panel_sweettv.get(") + source.count("panel_sweettv.post("), 2)

    def test_now_state_carries_what_the_list_knows(self):
        def rpc(method, params=None):
            return {"Player.GetActivePlayers": [{"playerid": 1, "type": "video"}],
                    "Player.GetItem": {"item": {"file": LIVE, "label": "5", "title": ""}},
                    "Player.GetProperties": {"time": {"minutes": 1}, "totaltime": {"seconds": 1}},
                    "Application.GetProperties": {"volume": 50, "muted": False}}.get(method, {})
        with mock.patch.object(time, "time", lambda: NOW):
            state = pw.now_state(rpc)
        self.assertEqual((state["title"], state["live"], state["programme"], state["can_rewind"], state["go_live"]),
                         ("Первый канал", True, "Холостяк", True, False))


def programme(i, start, minutes=30, **kw):
    return dict({"id": 1000 + i, "text": "П%d" % i, "time_start": start, "time_stop": start + minutes * 60, "available": True}, **kw)


class GuideView(unittest.TestCase):
    """GET /api/sweettv/guide?cid=: the programmes of one channel, past newest first, the one on now, the ones to come."""

    def setUp(self):
        use_list(self)

    def test_past_current_next(self):
        view = ps.guide_view(LIST, "5", NOW)
        self.assertEqual((view["ok"], view["cid"], view["name"], view["archive"], view["archive_days"], view["now"]),
                         (True, "5", "Первый канал", True, 7, NOW))
        self.assertEqual(view["past"], [{"id": "50", "title": "Утро", "start": NOW - 7200, "stop": NOW - 3600, "archive": True}])
        self.assertEqual(view["current"], {"id": "51", "title": "Холостяк", "start": NOW - 3600, "stop": NOW + 3600, "archive": True})
        self.assertEqual(view["next"], [{"id": "52", "title": "Вечер", "start": NOW + 3600, "stop": NOW + 7200}])   # information only
        self.assertEqual(view["counts"], {"past": 1, "next": 1})

    def test_the_real_shape_ten_past_one_on_now_many_to_come(self):
        epg = [programme(i, NOW - 600 - 1800 * (10 - i)) for i in range(10)] + [programme(10, NOW - 600, 30)]
        epg += [programme(11 + i, NOW + 1200 + 1800 * i) for i in range(100)]
        epg.reverse()                                             # the order of the file is not trusted
        raw = {"list": [{"id": 9, "name": "Канал", "catchup": True, "catchup_duration": 7, "epg": epg}]}
        view = ps.guide_view(raw, "9", NOW)
        self.assertEqual(view["counts"], {"past": 10, "next": 100})
        self.assertEqual([p["id"] for p in view["past"]][:2], ["1009", "1008"])          # the newest past first
        self.assertEqual(view["past"][-1]["id"], "1000")
        self.assertEqual(view["current"]["id"], "1010")
        self.assertEqual([p["id"] for p in view["next"]][:2], ["1011", "1012"])          # the soonest next first
        self.assertTrue(all(p["archive"] for p in view["past"]))
        self.assertTrue(all("archive" not in p for p in view["next"]))

    def test_a_channel_without_an_archive_marks_nothing_playable(self):
        view = ps.guide_view(LIST, "6", NOW)
        self.assertFalse(view["archive"])
        self.assertEqual(view["current"]["archive"], False)
        raw = {"list": [{"id": 9, "name": "K", "catchup": True, "available": False, "epg": [programme(1, NOW - 3600)]}]}
        self.assertFalse(ps.guide_view(raw, "9", NOW)["past"][0]["archive"])

    def test_a_programme_the_archive_does_not_have_is_marked(self):
        raw = {"list": [{"id": 9, "name": "K", "catchup": True, "catchup_duration": 1, "epg": [
            programme(1, NOW - 3600), programme(2, NOW - 7200, available=False), programme(3, NOW - 2 * 86400)]}]}
        flags = {p["id"]: p["archive"] for p in ps.guide_view(raw, "9", NOW)["past"]}
        self.assertEqual(flags, {"1001": True, "1002": False, "1003": False})            # off, not available, older than a day

    def test_broken_rows_are_left_out(self):
        epg = [None, "x", {}, {"id": 1}, programme(1, NOW - 3600, 0), dict(programme(2, NOW - 3600), id=None),
               dict(programme(3, NOW - 3600), time_start="soon"), programme(4, NOW - 7200),
               dict(programme(5, 0), time_start=(NOW + 3600) * 1000, time_stop=(NOW + 5400) * 1000)]
        view = ps.guide_view({"list": [{"id": 9, "name": "K", "catchup": True, "epg": epg}]}, "9", NOW)
        self.assertEqual([p["id"] for p in view["past"]], ["1004"])
        self.assertIsNone(view["current"])
        self.assertEqual(view["counts"], {"past": 1, "next": 1})                         # a time in milliseconds is understood

    def test_no_programmes_at_all(self):
        view = ps.guide_view(LIST, "7", NOW)
        self.assertEqual((view["past"], view["current"], view["next"], view["counts"]), ([], None, [], {"past": 0, "next": 0}))

    def test_what_cannot_be_shown_is_refused(self):
        for cid, code in (("99", 404), ("x", 400), ("", 400), ("5|50", 400), (None, 400), (5, 400)):
            with self.assertRaises(pw.Refused, msg=cid) as caught:
                ps.guide_view(LIST, cid, NOW)
            self.assertEqual(caught.exception.code, code, cid)
        with self.assertRaises(pw.Refused):
            ps.guide_view({}, "5", NOW)                                                  # no list yet

    def test_the_route(self):
        with mock.patch.object(time, "time", lambda: NOW):
            body, code = ps.get("/api/sweettv/guide?cid=5", None)
            self.assertEqual((code, body["current"]["id"], body["counts"]), (200, "51", {"past": 1, "next": 1}))
            for path, expected in (("/api/sweettv/guide", 400), ("/api/sweettv/guide?cid=", 400), ("/api/sweettv/guide?cid=99", 404),
                                   ("/api/sweettv/guide?cid=a&cid=5", 400), ("/api/sweettv/nothing?cid=5", 404)):
                body, code = ps.get(path, None)
                self.assertEqual(code, expected, path)
                self.assertIn("error", body)

    def test_the_answer_is_json_and_small(self):
        view = ps.guide_view(ps.channels(), "5", NOW)
        self.assertLess(len(json.dumps(view)), 2000)


if __name__ == "__main__":
    unittest.main()
