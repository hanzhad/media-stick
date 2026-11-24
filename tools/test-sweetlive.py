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

    def make(self, playing, raw=None):
        calls, notes = [], []

        class Player:
            def __init__(self):
                pass

            def getPlayingFile(self):
                if isinstance(playing[0], Exception):
                    raise playing[0]
                return playing[0]

        lib = types.ModuleType("resources.lib.sweettv")
        lib.refreshToken, lib.initSettings, lib.refreshChannelList = (lambda: True), (lambda: None), (lambda: None)
        lib.helper = types.SimpleNamespace(get_channel_list=lambda: LIST if raw is None else raw)
        fake = {"xbmc": types.SimpleNamespace(Player=Player, Monitor=object, log=lambda *a: None, LOGWARNING=2, LOGERROR=1,
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

    def item(self, videoid, query):
        """The item the add-on resolves for playvid/<videoid> when Kodi calls it with this query string."""
        log = []
        plugin = play_tests.kodi_plugin(log)
        helper = type("H", (play_tests.PlayHelper,), {"resolved": [], "channel_list": LIST, "plugin": plugin})
        sweet = stubs.load_sweettv(helper_class=helper, xbmcplugin=plugin)
        stubs.Settings.values.update(logged=True, bearer="Bearer x", playerType="ffmpeg")
        sweet.time = types.SimpleNamespace(time=lambda: NOW)
        with mock.patch.object(sys, "argv", ["plugin://plugin.video.sweettv/playvid/" + videoid, "1", query]):
            sweet.playvid(videoid)
        self.assertEqual(len(log), 1)
        return log[0][2], sweet

    def test_an_archive_starts_where_the_query_says_and_is_as_long_as_the_programme(self):
        item, _ = self.item("5|51", "?ms_start=3590")
        self.assertEqual(item.props, {"StartOffset": "3590", "TotalTime": "7200"})

    def test_an_archive_without_a_place_starts_at_the_beginning(self):
        item, _ = self.item("5|50", "")
        self.assertEqual(item.props, {"TotalTime": "3600"})

    def test_live_gets_neither_a_start_nor_a_length(self):
        item, _ = self.item("5|null", "?ms_start=300")
        self.assertEqual(item.props, {})

    def test_a_silly_start_is_no_start(self):
        for query in ("?ms_start=abc", "?ms_start=-5", "?ms_start=", "?other=1", "ms_start=%00"):
            item, _ = self.item("5|50", query)
            self.assertNotIn("StartOffset", item.props, query)
        item, _ = self.item("5|50", "?ms_start=99999999999999")
        self.assertEqual(item.props["StartOffset"], str(3 * 86400))

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
        raw = ps.slim(dict(LIST, junk="x", list=LIST["list"] + [{"id": 8, "icon_url": "u" * 500, "epg": [dict(SHOW, external_ids=[1] * 99)]}]))
        self.assertEqual(sorted(raw), ["categories", "list"])
        self.assertNotIn("junk", raw)
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
