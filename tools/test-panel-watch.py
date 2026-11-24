#!/usr/bin/env python3
"""Offline test of the Смотреть part of the panel (no Kodi, no device):
python3 tools/test-panel-watch.py

The pure functions of panel_watch (pictures, what may be played, the channel list, YouTube directories,
control requests), the routes against a fake Kodi, and the injection into the real page of `panel`.
The add-on's own modules (youtube_data, sweettv_data, apps) are loaded from the repository, as the panel
does on a device that has no copy yet."""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, ".kodi", "userdata", "addon_data")
os.environ.pop("MEDIASTICK_ADDON_LIB", None)
os.environ["MEDIASTICK_ADDONS_ROOT"] = os.path.join(TMP, ".kodi", "addons")
os.environ["MEDIASTICK_SWEETNOW_DIR"] = os.path.join(TMP, "now")      # what the SWEET.TV add-on wrote down about its streams
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")
os.environ["MEDIASTICK_RESUME_DIR"] = os.path.join(TMP, "resume")
os.environ.pop("MEDIASTICK_APP_ART", None)
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

import panel_accounts  # noqa: E402
import panel_lang  # noqa: E402
import mediastick_sweetlive as ml  # noqa: E402
import panel_watch as pw  # noqa: E402

NOW = 1_800_000_000
YT = "plugin://plugin.video.youtube/"
VID = YT + "play/?video_id=abcdefghijk"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Pictures(unittest.TestCase):
    def test_decodes_kodi_art(self):
        self.assertEqual(pw.image_url("image://https%3a%2f%2fi.ytimg.com%2fvi%2fabc%2fhq.jpg/"),
                         "https://i.ytimg.com/vi/abc/hq.jpg")

    def test_allowed_hosts(self):
        for url in ("https://i.ytimg.com/a.jpg", "https://yt3.ggpht.com/a", "https://lh3.googleusercontent.com/a",
                    "https://cdn.sweet.tv/i.png", "https://sweet.tv/i.png"):
            self.assertEqual(pw.image_url(url), url)

    def test_refused(self):
        for url in ("http://i.ytimg.com/a.jpg", "https://evil.example/a.jpg", "https://ytimg.com.evil.example/a",
                    "https://notytimg.com/a", "https://u:p@i.ytimg.com/a", "https://i.ytimg.com:8443/a",
                    "image://DefaultVideo.png/", "special://skin/x.png", "/home/media/a.png", "", None, 5,
                    "https://i.ytimg.com/a b.jpg", "https://i.ytimg.com/" + "a" * 600,
                    "image://http%3a%2f%2fi.ytimg.com%2fa.jpg/"):
            self.assertEqual(pw.image_url(url), "", url)


class Playing(unittest.TestCase):
    def test_accepts(self):
        self.assertEqual(pw.play_target(VID), VID)
        self.assertEqual(pw.play_target(YT + "play/?video_id=abcdefghijk&playlist_id=PL1"),
                         YT + "play/?video_id=abcdefghijk&playlist_id=PL1")
        self.assertEqual(pw.play_target("plugin://plugin.video.sweettv/playvid/12|null"),
                         "plugin://plugin.video.sweettv/playvid/12|null")
        self.assertEqual(pw.play_target("plugin://plugin.video.sweettv/playvid/12|345"),
                         "plugin://plugin.video.sweettv/playvid/12|345")
        self.assertEqual(pw.play_target("plugin://plugin.video.sweettv/playvod/9558|null|69"),
                         "plugin://plugin.video.sweettv/playvod/9558|null|69")
        self.assertEqual(pw.play_target("plugin://plugin.video.sweettv/playvod/1234|5678|69?start=120"),
                         "plugin://plugin.video.sweettv/playvod/1234|5678|69?start=120")

    def test_rejects(self):
        for f in (YT, YT + "special/my_subscriptions", YT + "kodion/search/query/?q=x", YT + "play/../x",
                  "plugin://plugin.video.other/play/?video_id=abcdefghijk",
                  "plugin://plugin.video.youtube.evil/play/?x=1", "http://example.com/play/",
                  "/home/media/x.mp4", "smb://nas/film.mkv", "plugin://plugin.video.sweettv/playvid/12",
                  "plugin://plugin.video.sweettv/playvid/ab|null", "plugin://plugin.video.sweettv/playvid/12|x",
                  "plugin://plugin.video.sweettv/playvid/12|null|rm", "plugin://plugin.video.sweettv/other/12|null",
                  "plugin://plugin.video.sweettv/playvod/9558",
                  "plugin://plugin.video.sweettv/playvod/ab|null|0",
                  "plugin://plugin.video.sweettv/playvod/9558|bad|0",
                  "plugin://plugin.video.sweettv/playvod/9558|null|bad",
                  VID + "\nx", VID + " x", VID + '"', "", None, 7, [VID]):
            self.assertEqual(pw.play_target(f), "", f)

    def test_resume(self):
        self.assertEqual(pw.clean_resume(430), 430)
        self.assertEqual(pw.clean_resume(430.9), 430)
        for v in (0, 3, -5, 10 ** 7, True, "430", None, float("nan")):
            self.assertEqual(pw.clean_resume(v), 0, v)

    def test_app_of(self):
        self.assertEqual(pw.app_of(VID), "youtube")
        self.assertEqual(pw.app_of("plugin://plugin.video.sweettv/playvid/1|null"), "sweettv")
        self.assertEqual(pw.app_of("plugin://plugin.video.sweettv/playvod/9558|null|69"), "sweettv")
        self.assertEqual(pw.app_of("/x.mkv"), "other")

    def test_sweet_ref_vod(self):
        self.assertIsNotNone(pw.sweet_ref("plugin://plugin.video.sweettv/playvod/9558|101|69?start=120"))


def channel(cid, name, now, start_now, stop_now, nxt, cats=(3,), icon="https://cdn.sweet.tv/c.png", number=1):
    epg = []
    if start_now is not None:
        epg.append({"id": cid * 10, "time_start": now + start_now, "time_stop": now + stop_now, "text": "Сейчас " + name})
    if nxt is not None:
        epg.append({"id": cid * 10 + 1, "time_start": now + nxt, "time_stop": now + nxt + 3600, "text": "Потом " + name})
    return {"id": cid, "name": name, "number": number, "icon_v2_url": icon, "category": list(cats), "catchup": True,
            "catchup_duration": 3, "available": True, "epg": epg}


FIXTURE = {"status": "OK",
           "list": [channel(5, "Первый", NOW, -1800, 1800, 1800),
                    channel(6, "Второй", NOW, None, None, 600, cats=(4,), icon="https://evil.example/x.png", number=2),
                    {"id": "bad", "name": "no id"}],
           "categories": [{"id": 3, "caption": "Новости"}, {"id": 4, "caption": "Кино"}, {"id": 9, "caption": "Пусто"}]}


class Sweet(unittest.TestCase):
    sw = pw.sweet()

    def test_now_and_next(self):
        r = pw.sweet_view(self.sw, FIXTURE, NOW)
        self.assertEqual(r["state"], "data")
        self.assertEqual([c["id"] for c in r["channels"]], ["5", "6"])
        first = r["channels"][0]
        self.assertEqual(first["now"], {"title": "Сейчас Первый", "start": NOW - 1800, "end": NOW + 1800, "percent": 50})
        self.assertEqual(first["next"]["title"], "Потом Первый")
        self.assertEqual(first["next"]["start"], NOW + 1800)
        self.assertRegex(first["next"]["time"], r"^\d\d:\d\d$")
        self.assertEqual(first["icon"], "https://cdn.sweet.tv/c.png")
        self.assertEqual(first["play"], "plugin://plugin.video.sweettv/playvid/5|null")
        self.assertEqual(first["cats"], ["c:3"])

    def test_gap_and_foreign_icon(self):
        second = pw.sweet_view(self.sw, FIXTURE, NOW)["channels"][1]
        self.assertIsNone(second["now"])
        self.assertEqual(second["next"]["title"], "Потом Второй")
        self.assertEqual(second["icon"], "")

    def test_categories_only_used_ones(self):
        r = pw.sweet_view(self.sw, FIXTURE, NOW)
        self.assertEqual(r["categories"], [{"key": "c:3", "name": "Новости"}, {"key": "c:4", "name": "Кино"}])

    def test_states(self):
        self.assertEqual(pw.sweet_view(self.sw, None, NOW)["state"], "signin")
        self.assertEqual(pw.sweet_view(self.sw, FIXTURE, NOW, signed=False)["state"], "signin")
        self.assertEqual(pw.sweet_view(self.sw, {"status": "FAIL", "list": []}, NOW)["state"], "error")
        self.assertEqual(pw.sweet_view(self.sw, ["x"], NOW)["state"], "error")
        self.assertEqual(pw.sweet_view(self.sw, {"status": "OK", "list": []}, NOW)["state"], "empty")


class YouTube(unittest.TestCase):
    data = pw.yt()

    def listing(self, files):
        return self.data.parse_reply({"result": {"files": files}})

    def test_mapping(self):
        lst = self.listing([
            {"file": VID, "filetype": "file", "label": "[B]Видео[/B]", "title": "Видео", "duration": 600,
             "thumbnail": "image://https%3a%2f%2fi.ytimg.com%2fvi%2fabcdefghijk%2fhq.jpg/", "studio": ["Канал"],
             "resume": {"position": 150, "total": 600}, "playcount": 0},
            {"file": YT + "channel/UC1/playlists/", "filetype": "directory", "label": "Список", "thumbnail": "x"},
            {"file": YT + "special/my_subscriptions?page=2", "filetype": "directory", "label": "Next"},
            {"file": "plugin://plugin.video.other/x", "filetype": "file", "label": "foreign"}])
        items = [pw.map_entry(e) for e in lst.entries]
        self.assertEqual(len(items), 2)
        v, folder = items
        self.assertTrue(v["playable"] and not v["folder"])
        self.assertEqual((v["title"], v["channel"], v["duration"], v["file"]), ("Видео", "Канал", 600, VID))
        self.assertEqual(v["thumb"], "https://i.ytimg.com/vi/abcdefghijk/hq.jpg")
        self.assertTrue(folder["folder"] and not folder["playable"])
        self.assertEqual(folder["thumb"], "")
        self.assertEqual(lst.more, YT + "special/my_subscriptions?page=2")

    def test_resume_seconds(self):
        e = self.listing([{"file": VID, "filetype": "file", "title": "t", "duration": 600,
                           "resume": {"position": 430, "total": 600}}]).entries[0]
        self.assertEqual(pw.map_entry(e)["resume"], 430)
        e = self.listing([{"file": VID, "filetype": "file", "title": "t", "duration": 600}]).entries[0]
        self.assertEqual(pw.map_entry(e)["resume"], 0)

    def state(self, gated=None, files=None, error=None, keys=True):
        d = self.data
        raw = pw.youtube_reply(d, None if error else {"files": files or []}) if error is not False else None
        return pw.youtube_state(d, gated, d.parse_reply(raw), keys)

    def test_error_to_state(self):
        d = self.data
        self.assertEqual(self.state(gated=d.SIGNIN), "signin")
        self.assertEqual(self.state(gated=d.NEEDKEY), "needkey")
        self.assertEqual(self.state(files=[{"file": VID, "filetype": "file", "title": "t"}]), "data")
        self.assertEqual(self.state(files=[]), "empty")
        self.assertEqual(self.state(files=[], keys=False), "needkey")
        self.assertEqual(self.state(error=True, keys=False), "needkey")     # refused path, no personal key
        self.assertEqual(self.state(error=True, keys=True), "error")        # refused path with a key
        self.assertEqual(pw.youtube_state(d, None, d.parse_reply(None), True), "error")

    def test_folder_path(self):
        self.assertEqual(pw.folder_path(YT + "channel/UC1/"), YT + "channel/UC1/")
        for p in ("", None, "http://x/", "plugin://plugin.video.other/", YT + "a b", YT + "a|b", "file:///etc"):
            self.assertEqual(pw.folder_path(p), "", p)


class Control(unittest.TestCase):
    def refused(self, body):
        with self.assertRaises(pw.Refused):
            pw.clean_ctl(body)

    def test_valid(self):
        self.assertEqual(pw.clean_ctl({"op": "playpause", "junk": 1}), {"op": "playpause"})
        self.assertEqual(pw.clean_ctl({"op": "seek", "to": 90}), {"op": "seek", "to": 90})
        self.assertEqual(pw.clean_ctl({"op": "seek", "by": -10}), {"op": "seek", "by": -10})
        self.assertEqual(pw.clean_ctl({"op": "volume", "level": 40.0}), {"op": "volume", "level": 40})
        self.assertEqual(pw.clean_ctl({"op": "volume", "by": -5}), {"op": "volume", "by": -5})
        self.assertEqual(pw.clean_ctl({"op": "subtitle", "off": True}), {"op": "subtitle", "off": True})
        self.assertEqual(pw.clean_ctl({"op": "subtitle", "index": 0}), {"op": "subtitle", "index": 0})
        self.assertEqual(pw.clean_ctl({"op": "audio", "index": 2}), {"op": "audio", "index": 2})

    def test_invalid(self):
        for body in (None, [], "stop", {}, {"op": "reboot"}, {"op": "seek"}, {"op": "seek", "to": -1},
                     {"op": "seek", "to": "5"}, {"op": "seek", "by": 10 ** 9}, {"op": "seek", "to": True},
                     {"op": "volume"}, {"op": "volume", "level": 101}, {"op": "volume", "level": -1},
                     {"op": "volume", "by": 500}, {"op": "subtitle"}, {"op": "subtitle", "index": -1},
                     {"op": "subtitle", "index": "1"}, {"op": "subtitle", "index": True}, {"op": "audio", "index": 100},
                     {"op": "audio"}, {"op": "seek", "to": float("nan")}):
            self.refused(body)

    def test_rpc(self):
        self.assertEqual(pw.ctl_rpc({"op": "playpause"}, 1), ("Player.PlayPause", {"playerid": 1}))
        self.assertEqual(pw.ctl_rpc({"op": "stop"}, 1), ("Player.Stop", {"playerid": 1}))
        self.assertEqual(pw.ctl_rpc({"op": "seek", "by": -10}, 1)[1]["value"], {"seconds": -10})
        self.assertEqual(pw.ctl_rpc({"op": "seek", "to": 3725}, 1)[1]["value"],
                         {"time": {"hours": 1, "minutes": 2, "seconds": 5, "milliseconds": 0}})
        self.assertEqual(pw.ctl_rpc({"op": "volume", "level": 30}, None), ("Application.SetVolume", {"volume": 30}))
        self.assertEqual(pw.ctl_rpc({"op": "volume", "by": 5}, None, 98)[1], {"volume": 100})
        self.assertEqual(pw.ctl_rpc({"op": "volume", "by": -5}, None, 3)[1], {"volume": 0})
        self.assertEqual(pw.ctl_rpc({"op": "mute"}, None), ("Application.SetMute", {"mute": "toggle"}))
        self.assertEqual(pw.ctl_rpc({"op": "subtitle", "off": True}, 1)[1]["subtitle"], "off")
        self.assertEqual(pw.ctl_rpc({"op": "subtitle", "index": 2}, 1)[1],
                         {"playerid": 1, "subtitle": 2, "enable": True})
        self.assertEqual(pw.ctl_rpc({"op": "audio", "index": 1}, 1)[1], {"playerid": 1, "stream": 1})


class NowPlaying(unittest.TestCase):
    def test_view(self):
        v = pw.now_view({"title": "Фильм", "showtitle": "Канал", "file": VID,
                         "thumbnail": "image://https%3a%2f%2fi.ytimg.com%2fa.jpg/"},
                        {"time": {"hours": 0, "minutes": 7, "seconds": 10, "milliseconds": 500},
                         "totaltime": {"hours": 1, "minutes": 0, "seconds": 0, "milliseconds": 0}, "speed": 1,
                         "subtitles": [{"index": 0, "name": "Русский", "language": "rus"}, {"index": 1, "language": "eng"}],
                         "currentsubtitle": {"index": 1}, "subtitleenabled": True,
                         "audiostreams": [{"index": 0, "name": "AAC", "language": "rus"}],
                         "currentaudiostream": {"index": 0}},
                        {"volume": 55, "muted": False})
        self.assertTrue(v["playing"])
        self.assertEqual((v["title"], v["channel"], v["app"], v["volume"]), ("Фильм", "Канал", "youtube", 55))
        self.assertEqual((v["time"], v["total"]), (430.5, 3600))
        self.assertEqual(v["subtitles"][1]["name"], "ENG")
        self.assertEqual((v["subtitle"], v["subtitles_on"], v["audio_index"]), (1, True, 0))
        self.assertEqual(v["thumb"], "https://i.ytimg.com/a.jpg")

    def test_a_live_sweettv_channel_is_named_and_marked_live(self):
        """What the owner saw: the title empty, the label the bare channel number, and a 1 minute window read as a movie."""
        item = {"title": "", "label": "5", "file": "plugin://plugin.video.sweettv/playvid/5|null"}
        v = pw.now_view(item, {"time": {"seconds": 45}, "totaltime": {"seconds": 56}}, None, name_of=lambda cid: "Первый канал")
        self.assertEqual((v["title"], v["live"], v["cid"], v["epg"], v["app"]), ("Первый канал", True, "5", "", "sweettv"))
        self.assertEqual(pw.item_title(item, lambda cid: "Первый канал"), "Первый канал")
        self.assertEqual(pw.item_title(item, lambda cid: ""), "")                       # the bare number is never a title

    def test_an_archived_programme_is_not_live_and_keeps_its_own_title(self):
        item = {"title": "Холостяк", "label": "Холостяк", "showtitle": "Первый канал",
                "file": "plugin://plugin.video.sweettv/playvid/5|51?ms_start=120"}
        v = pw.now_view(item, None, None, name_of=lambda cid: "x")
        self.assertEqual((v["title"], v["live"], v["cid"], v["epg"], v["channel"]),
                         ("Холостяк", False, "5", "51", "Первый канал"))

    def test_an_archive_that_is_a_stream_address_keeps_what_the_add_on_wrote_down(self):
        """Kodi gives the address of the stream for an archived programme: without the entry nothing says what it is."""
        stream = "https://hls-dvr2.sweet.tv/dvr/5/51/index.m3u8?token=x"
        item = {"title": "Холостяк", "label": "Холостяк", "showtitle": "", "file": stream}
        shutil.rmtree(ml.NOW_DIR, ignore_errors=True)
        self.addCleanup(shutil.rmtree, ml.NOW_DIR, True)
        v = pw.now_view(item, None, None, name_of=lambda cid: "Первый канал")
        self.assertEqual((v["live"], v["cid"], v["epg"], v["app"], v["channel"]), (False, "", "", "other", ""))
        self.assertIsNone(pw.sweet_ref(stream))
        ml.remember(5, 51, stream, 120)
        v = pw.now_view(item, None, None, name_of=lambda cid: "Первый канал")
        self.assertEqual((v["title"], v["live"], v["cid"], v["epg"], v["app"], v["channel"]),
                         ("Холостяк", False, "5", "51", "sweettv", "Первый канал"))
        self.assertEqual(pw.sweet_ref(stream), ("5", "51"))
        self.assertEqual(pw.sweet_ref(stream + "|Referer=x"), ("5", "51"))
        self.assertIsNone(pw.sweet_ref("https://example.org/dvr/5/52/index.m3u8?token=x"))
        ml.remember(5, "", "https://hls-live3.sweet.tv/live/5/index.m3u8", 0)
        v = pw.now_view({"title": "", "label": "5", "file": "https://hls-live3.sweet.tv/live/5/index.m3u8"}, None, None,
                        name_of=lambda cid: "Первый канал")
        self.assertEqual((v["title"], v["live"], v["cid"], v["epg"], v["channel"]), ("Первый канал", True, "5", "", "Первый канал"))

    def test_the_channel_is_named_for_a_plugin_path_without_a_show_title(self):
        item = {"title": "Холостяк", "label": "Холостяк", "file": "plugin://plugin.video.sweettv/playvid/5|51"}
        self.assertEqual(pw.now_view(item, None, None, name_of=lambda cid: "Первый канал")["channel"], "Первый канал")
        item["showtitle"] = "Свой"
        self.assertEqual(pw.now_view(item, None, None, name_of=lambda cid: "Первый канал")["channel"], "Свой")

    def test_a_broken_or_missing_file_of_streams_is_no_sweettv_item(self):
        os.makedirs(ml.NOW_DIR, exist_ok=True)
        self.addCleanup(shutil.rmtree, ml.NOW_DIR, True)
        with open(os.path.join(ml.NOW_DIR, ml.NOW_FILE), "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertIsNone(pw.sweet_ref("https://hls-dvr2.sweet.tv/dvr/5/51/index.m3u8"))
        with mock.patch.object(ml, "recall", side_effect=ValueError("boom")):
            self.assertIsNone(pw.sweet_ref("https://hls-dvr2.sweet.tv/dvr/5/51/index.m3u8"))

    def test_other_items_are_not_touched_by_the_sweettv_rules(self):
        v = pw.now_view({"title": "", "label": "7", "file": VID}, None, None, name_of=lambda cid: "x")
        self.assertEqual((v["title"], v["live"], v["cid"]), ("7", False, ""))
        self.assertEqual(pw.item_title({"title": "Фильм", "label": "f"}), "Фильм")
        self.assertEqual(pw.item_title(None), "")

    def test_the_name_comes_from_the_add_ons_channel_list(self):
        pw._cache.clear()
        path = os.path.join(TMP, ".kodi", "temp", "channelList.json")
        put(path, '{"list": [{"id": 5, "name": "Первый канал"}, {"id": 6}, "x"]}')
        self.assertEqual(pw.sweet_name("5"), "Первый канал")
        self.assertEqual(pw.sweet_name("6"), "")
        self.assertEqual(pw.sweet_name("404"), "")
        pw._cache.clear()
        os.remove(path)
        self.assertEqual(pw.sweet_name("5"), "")

    def test_odd_input_does_not_raise(self):
        v = pw.now_view(None, None, None)
        self.assertEqual((v["title"], v["time"], v["subtitles"], v["volume"]), ("", 0, [], None))


class Apps(unittest.TestCase):
    def test_launcher_rules(self):
        mod = pw.launcher_apps()
        found = [{"addonid": "plugin.video.youtube", "name": "YouTube"},
                 {"addonid": "plugin.video.sweettv", "name": "SWEET.TV"},
                 {"addonid": "script.module.x", "name": "hidden"}, {"addonid": "service.foo", "name": "hidden"},
                 {"addonid": "script.media-stick.home", "name": "hidden"},
                 {"addonid": "plugin.video.other", "name": "Other"}, {"addonid": "plugin.video.other", "name": "dup"}]
        apps = pw.build_apps(mod, found, {})
        ids = [a["id"] for a in apps]
        self.assertEqual(ids, ["plugin.video.sweettv", "plugin.video.youtube", "webapp:netflix", "webapp:disney",
                               "webapp:prime", "webapp:max", "plugin.video.other"])
        self.assertEqual({a["id"]: a["kind"] for a in apps}["webapp:netflix"], "launch")
        self.assertEqual(apps[0]["kind"], "catalog")
        self.assertEqual(ids[0], "plugin.video.sweettv")
        self.assertEqual(pw.build_apps(mod, found, {"plugin.video.other": 5})[0]["id"], "plugin.video.other")
        self.assertNotIn("xbmc", sys.modules)      # the stand-ins are gone after the load


class AppsCache(unittest.TestCase):
    """The apps list is cached only when Kodi answered with add-ons: a list from a Kodi that is still starting is shown, not kept."""
    WEB = ["webapp:netflix", "webapp:disney", "webapp:prime", "webapp:max"]

    def setUp(self):
        pw._cache.clear()

    @staticmethod
    def good(method, params=None, timeout=3):
        return {"addons": [{"addonid": "plugin.video.youtube", "name": "YouTube"}]}

    @staticmethod
    def down(method, params=None, timeout=3):
        raise OSError("kodi is starting")

    @staticmethod
    def empty(method, params=None, timeout=3):
        return {"addons": []}

    @staticmethod
    def errored(method, params=None, timeout=3):
        return {"error": {"code": -32100}}

    def ids(self, rpc):
        return [a["id"] for a in pw.get("/api/watch/apps", rpc)[0]["apps"]]

    def test_a_failing_kodi_shows_the_web_apps_and_is_not_cached(self):
        for bad in (self.down, self.empty, self.errored):
            pw._cache.clear()
            first = self.ids(bad)
            self.assertEqual(first, self.WEB, bad.__name__)
            self.assertIn("plugin.video.youtube", self.ids(self.good), bad.__name__)

    def test_a_good_list_is_cached(self):
        first = self.ids(self.good)
        self.assertIn("plugin.video.youtube", first)
        self.assertEqual(self.ids(self.down), first)
        self.assertEqual(self.ids(self.empty), first)


PNG = b"\x89PNG\r\n\x1a\n" + b"icon" * 20


class Art(unittest.TestCase):
    """The tiles' pictures: the icon files of the apps in the list, served by id, never by a path from the client."""
    ROOT = os.environ["MEDIASTICK_ADDONS_ROOT"]
    ADDONS = ("plugin.video.youtube", "plugin.video.sweettv", "plugin.video.noicon", "plugin.video.link", "plugin.video.sneaky")

    def setUp(self):
        pw._cache.clear()
        shutil.rmtree(os.path.join(TMP, ".kodi"), ignore_errors=True)
        shutil.rmtree(os.path.join(TMP, "outside"), ignore_errors=True)
        self.put_bytes("plugin.video.youtube/resources/media/icon.png", PNG + b"yt")
        put(os.path.join(self.ROOT, "plugin.video.youtube", "addon.xml"),
            "<addon id='plugin.video.youtube'><extension point='kodi.addon.metadata'><assets>"
            "<icon>resources/media/icon.png</icon></assets></extension></addon>")
        self.put_bytes("plugin.video.sweettv/icon.png", PNG + b"sw")      # no <icon> in its addon.xml: icon.png
        put(os.path.join(self.ROOT, "plugin.video.sweettv", "addon.xml"), "<addon id='plugin.video.sweettv'/>")
        put(os.path.join(self.ROOT, "plugin.video.noicon", "addon.xml"), "<addon id='plugin.video.noicon'/>")
        os.makedirs(os.path.join(TMP, "outside"))
        with open(os.path.join(TMP, "outside", "secret.png"), "wb") as f:
            f.write(PNG + b"secret")
        os.makedirs(os.path.join(self.ROOT, "plugin.video.link"))
        os.symlink(os.path.join(TMP, "outside", "secret.png"), os.path.join(self.ROOT, "plugin.video.link", "icon.png"))
        put(os.path.join(self.ROOT, "plugin.video.sneaky", "addon.xml"),
            "<addon id='plugin.video.sneaky'><icon>../../../outside/secret.png</icon></addon>")

    def put_bytes(self, rel, data):
        path = os.path.join(self.ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def rpc(self, method, params=None, timeout=3):
        if method == "Addons.GetAddons":
            return {"addons": [{"addonid": a, "name": a} for a in self.ADDONS]}
        return {}

    def apps(self):
        pw._cache.clear()
        return {a["id"]: a for a in pw.get("/api/watch/apps", self.rpc)[0]["apps"]}

    def test_the_icon_path_comes_from_addon_xml(self):
        self.assertEqual(pw.addon_icon_rel("<addon><assets><icon>resources/media/icon.png</icon></assets></addon>"), "resources/media/icon.png")
        self.assertEqual(pw.addon_icon_rel("<addon><icon>a.png</icon></addon>"), "a.png")
        for bad in ("<addon/>", "<addon><icon> </icon></addon>", "not xml", "", None):
            self.assertEqual(pw.addon_icon_rel(bad), "icon.png")

    def test_the_apps_payload_carries_an_art_address_only_for_an_icon_that_exists(self):
        apps = self.apps()
        self.assertEqual(apps["plugin.video.youtube"]["art"], "/api/watch/art?id=plugin.video.youtube")
        self.assertEqual(apps["plugin.video.sweettv"]["art"], "/api/watch/art?id=plugin.video.sweettv")
        self.assertEqual(apps["webapp:netflix"]["art"], "/api/watch/art?id=webapp%3Anetflix")
        for webapp in ("netflix", "disney", "prime", "max"):
            self.assertTrue(apps["webapp:" + webapp]["art"])
        self.assertEqual(apps["plugin.video.noicon"]["art"], "")
        self.assertEqual(apps["plugin.video.link"]["art"], "")        # a link out of the add-ons folder
        self.assertEqual(apps["plugin.video.sneaky"]["art"], "")      # addon.xml pointing out of its folder

    def test_a_valid_id_gives_the_bytes_and_the_cache_headers(self):
        yt = pw.art("/api/watch/art?id=plugin.video.youtube", self.rpc)
        status, headers, body = pw.art_response(yt)
        h = dict(headers)
        self.assertEqual((status, body, h["Content-Type"]), (200, PNG + b"yt", "image/png"))
        self.assertEqual(h["Cache-Control"], "public, max-age=86400")
        self.assertRegex(h["ETag"], r'^"[0-9a-f]+-[0-9a-f]+"$')
        self.assertRegex(h["Last-Modified"], r"GMT$")
        status, headers, body = pw.art_response(yt, h["ETag"])        # the phone asks again with the ETag
        self.assertEqual((status, body), (304, b""))
        self.assertEqual(pw.art_response(yt, '"other"')[0], 200)
        sw = pw.art("/api/watch/art?id=plugin.video.sweettv", self.rpc)
        self.assertEqual(pw.art_response(sw)[2], PNG + b"sw")

    def test_the_web_apps_use_the_launchers_own_art(self):
        found = pw.art("/api/watch/art?id=webapp%3Anetflix", self.rpc)
        want = open(os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "resources", "media", "apps",
                                 "netflix.png"), "rb").read()
        self.assertEqual((found["data"], found["type"]), (want, "image/png"))

    def test_everything_else_is_not_found(self):
        for query in ("", "id=", "id=plugin.video.nothere", "id=../../etc/passwd", "id=plugin.video.youtube/../../x",
                      "id=..", "id=.", "id=%2e%2e%2f%2e%2e%2fetc%2fpasswd", "id=/etc/passwd", "id=webapp%3A..%2Fx",
                      "id=webapp:nothere", "id=plugin.video.noicon", "id=plugin.video.link", "id=plugin.video.sneaky",
                      "id=plugin.video.youtube&id=plugin.video.sweettv", "id=plugin.video.youtube%00",
                      "path=/etc/passwd", "id=script.module.x"):
            self.assertIsNone(pw.art("/api/watch/art?" + query, self.rpc), query)
        status, headers, body = pw.art_response(None)
        self.assertEqual(status, 404)
        self.assertEqual(dict(headers)["Cache-Control"], "no-store")

    def test_a_huge_or_unknown_type_is_refused(self):
        self.put_bytes("plugin.video.noicon/icon.png", b"x" * (pw.ART_MAX + 1))
        self.assertIsNone(pw.art("/api/watch/art?id=plugin.video.noicon", self.rpc))
        os.unlink(os.path.join(self.ROOT, "plugin.video.noicon", "icon.png"))
        put(os.path.join(self.ROOT, "plugin.video.noicon", "addon.xml"), "<addon><icon>x.svg</icon></addon>")
        self.put_bytes("plugin.video.noicon/x.svg", b"<svg/>")
        self.assertIsNone(pw.art("/api/watch/art?id=plugin.video.noicon", self.rpc))

    def test_kodi_down_is_not_found(self):
        def down(*a, **k):
            raise ConnectionRefusedError()
        self.assertIsNone(pw.art("/api/watch/art?id=plugin.video.youtube", down))

    def test_the_panel_serves_it_as_bytes_and_the_tile_falls_back_to_the_letter(self):
        source = open(PANEL, encoding="utf-8").read()
        self.assertIn('if p == panel_watch.PREFIX + "art":', source)
        self.assertIn("panel_watch.art_response(panel_watch.art(self.path, kodi)", source)
        self.assertNotIn("status, headers, body = panel_watch.art_response", source)   # `status` is the panel's own function
        self.assertLess(source.index('p == panel_watch.PREFIX + "art"'), source.index("body, code = panel_watch.get(self.path, kodi)"))
        ui = open(os.path.join(LIB, "panel_watch_ui.py"), encoding="utf-8").read()
        self.assertIn("h('img',{src:a.art,alt:'',loading:'lazy'", ui)
        self.assertIn("onerror:e=>{e.target.remove();box.textContent=letter}", ui)
        self.assertIn("if(!a.art){box.textContent=letter;return box}", ui)
        self.assertIn(".wt-logo img{display:block;width:100%;height:100%;object-fit:cover;border-radius:inherit}", ui)
        self.assertIn("width:44px;height:44px;border-radius:14px", ui)        # the tile keeps its size


class Routes(unittest.TestCase):
    def setUp(self):
        pw._cache.clear()
        shutil.rmtree(os.path.join(TMP, ".kodi"), ignore_errors=True)
        self.calls = []

    def rpc(self, method, params=None, timeout=3):
        self.calls.append((method, params))
        if method == "Addons.GetAddons":
            return {"addons": [{"addonid": "plugin.video.youtube", "name": "YouTube"}]}
        if method == "Files.GetDirectory":
            if params["directory"] == YT:
                return {"files": [{"file": YT + "special/popular_right_now/", "filetype": "directory", "label": "t"}]}
            return {"files": [{"file": VID, "filetype": "file", "title": "Ролик", "duration": 61}]}
        if method == "Player.GetActivePlayers":
            return self.players
        return {}

    players = []

    def test_apps_and_launch(self):
        body, code = pw.get("/api/watch/apps", self.rpc)
        self.assertEqual(code, 200)
        self.assertIn("plugin.video.youtube", [a["id"] for a in body["apps"]])
        self.assertEqual(pw.post("/api/watch/launch", {"app": "webapp:netflix"}, self.rpc)[0], {"ok": True})
        self.assertEqual(self.calls[-1], ("Addons.ExecuteAddon", {"addonid": "script.media-stick.home",
                                                                  "params": ["launch", "webapp:netflix"]}))
        for bad in ({"app": "rm -rf"}, {"app": "plugin.video.nothere"}, {}, {"app": ["x"]}):
            self.assertEqual(pw.post("/api/watch/launch", bad, self.rpc)[1], 400)

    def test_youtube_home_signed_out_is_trending(self):
        body, code = pw.get("/api/watch/youtube?section=home", self.rpc)
        self.assertEqual((code, body["state"]), (200, "data"))
        self.assertEqual(body["items"][0]["file"], VID)
        self.assertEqual(body["items"][0]["thumb"], "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")

    def test_youtube_signed_out_section(self):
        body, _ = pw.get("/api/watch/youtube?section=history", self.rpc)
        self.assertEqual(body["state"], "needkey")        # no key and not signed in: the key comes first
        # only the add-on's root page is read (to learn the section routes); the gated section itself is not asked for
        dirs = [c[1]["directory"] for c in self.calls if c[0] == "Files.GetDirectory"]
        self.assertEqual(dirs, [pw.yt().ROOT])

    def test_youtube_search_and_paths(self):
        self.assertEqual(pw.get("/api/watch/youtube?section=search", self.rpc)[0]["state"], "prompt")
        body, _ = pw.get("/api/watch/youtube?section=search&q=cats", self.rpc)
        self.assertEqual(body["state"], "data")
        self.assertEqual(self.calls[-1][1]["directory"], YT + "kodion/search/query/?q=cats")
        self.assertEqual(pw.get("/api/watch/youtube?section=nope", self.rpc)[1], 400)
        self.assertEqual(pw.get("/api/watch/youtube?path=file:///etc/passwd", self.rpc)[1], 400)
        self.assertEqual(pw.get("/api/watch/youtube?path=" + YT + "channel/UC1/", self.rpc)[1], 200)

    def test_sweettv_missing_file_is_signin(self):
        self.assertEqual(pw.get("/api/watch/sweettv", self.rpc)[0]["state"], "signin")

    def test_sweettv_file(self):
        import json
        put(os.path.join(TMP, ".kodi", "temp", "channelList.json"), json.dumps(FIXTURE))
        put(os.path.join(os.environ["MEDIASTICK_ADDON_DATA"], "plugin.video.sweettv", "settings.xml"),
            '<settings><setting id="logged">true</setting></settings>')
        body, code = pw.get("/api/watch/sweettv", self.rpc)
        self.assertEqual((code, body["state"]), (200, "data"))

    def test_play(self):
        self.assertEqual(pw.post("/api/watch/play", {"file": VID}, self.rpc)[0], {"ok": True})
        self.assertEqual(self.calls[-1], ("Player.Open", {"item": {"file": VID}}))
        n = len(self.calls)
        self.assertEqual(pw.post("/api/watch/play", {"file": "/etc/passwd"}, self.rpc)[1], 400)
        self.assertEqual(len(self.calls), n)

    def test_ctl_needs_player(self):
        self.players = []
        self.assertEqual(pw.post("/api/watch/ctl", {"op": "stop"}, self.rpc)[1], 409)
        self.assertEqual(pw.post("/api/watch/ctl", {"op": "mute"}, self.rpc)[1], 200)
        self.assertEqual(pw.post("/api/watch/ctl", {"op": "bogus"}, self.rpc)[1], 400)
        self.players = [{"playerid": 1, "type": "video"}]
        self.assertEqual(pw.post("/api/watch/ctl", {"op": "seek", "by": 10}, self.rpc)[1], 200)
        self.assertEqual(self.calls[-1], ("Player.Seek", {"playerid": 1, "value": {"seconds": 10}}))

    def test_now_nothing_playing(self):
        self.players = []
        self.assertEqual(pw.get("/api/watch/now", self.rpc), ({"playing": False}, 200))

    def test_kodi_down(self):
        def down(*a, **k):
            raise ConnectionRefusedError()
        self.assertEqual(pw.get("/api/watch/now", down), ({"playing": False}, 200))
        self.assertEqual(pw.post("/api/watch/play", {"file": VID}, down)[1], 503)
        self.assertEqual(pw.get("/api/watch/nothing", down)[1], 404)


class FakeKodiSocket:
    """Kodi's JSON-RPC TCP socket for one client: reads the request, then plays `steps` back: a number
    is a pause in seconds, bytes go out as they are, a callable gets the request's id and returns bytes."""
    def __init__(self, steps):
        self.steps, self.request = steps, None
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        try:
            conn, _ = self.srv.accept()
            with conn:
                data = b""
                while self.request is None:
                    data += conn.recv(65536)
                    try:
                        self.request = json.loads(data)
                    except ValueError:
                        pass
                for step in self.steps:
                    if isinstance(step, (int, float)):
                        time.sleep(step)
                    else:
                        conn.sendall(step(self.request["id"]) if callable(step) else step)
        except OSError:
            pass     # the client gave up and went away

    def close(self):
        self.srv.close()


def jline(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def reply(result, other=0):
    return lambda rid: jline({"jsonrpc": "2.0", "id": rid + other, "result": result})


NOTE = jline({"jsonrpc": "2.0", "method": "Other.service_ipc", "params": {"data": {
    "response_required": False, "target": "plugin_wakeup"}, "sender": "plugin.video.youtube"}})
NOTE2 = jline({"jsonrpc": "2.0", "method": "GUI.OnScreensaverDeactivated", "params": {"data": {}}})


class KodiSocket(unittest.TestCase):
    """The panel's kodi(): the TCP socket pushes notifications to every client, and the YouTube add-on
    sends one before it answers Files.GetDirectory; the answer is the object with our id."""
    @classmethod
    def setUpClass(cls):
        env = {"PANEL_STATE_DIR": os.path.join(TMP, "state"), "MEDIASTICK_ONBOARDING_DIR": os.path.join(TMP, "onboarding"),
               "MEDIASTICK_YTCHANNEL_OFF": "1"}
        with mock.patch.dict(os.environ, env):
            loader = importlib.machinery.SourceFileLoader("panel_kodi_socket", PANEL)
            spec = importlib.util.spec_from_loader(loader.name, loader)
            cls.panel = importlib.util.module_from_spec(spec)
            loader.exec_module(cls.panel)
        cls.real_connect = staticmethod(socket.create_connection)

    def ask(self, steps, timeout=3):
        fake = FakeKodiSocket(steps)
        self.addCleanup(fake.close)
        connect = lambda addr, timeout=None: self.real_connect(("127.0.0.1", fake.port), timeout=timeout)
        with mock.patch.object(self.panel.socket, "create_connection", connect):
            return self.panel.kodi("Files.GetDirectory", {"directory": YT}, timeout=timeout), fake

    def test_a_notification_before_the_reply(self):
        got, fake = self.ask([NOTE, 0.1, reply({"files": [{"label": "Home"}]})])
        self.assertEqual(got, {"files": [{"label": "Home"}]})
        self.assertEqual(fake.request["method"], "Files.GetDirectory")

    def test_two_notifications_and_the_reply_in_one_chunk(self):
        got, _ = self.ask([lambda rid: NOTE + NOTE2 + reply({"ok": 1})(rid)])
        self.assertEqual(got, {"ok": 1})

    def test_the_reply_split_over_two_chunks_after_a_notification(self):
        def text(rid):
            return reply({"files": [{"label": "Кошки"}]})(rid)
        cut = lambda rid: text(rid).index("К".encode("utf-8")) + 1     # inside the first Cyrillic letter
        half = lambda rid: text(rid)[:cut(rid)]
        rest = lambda rid: text(rid)[cut(rid):]
        got, _ = self.ask([NOTE, 0.1, half, 0.2, rest])
        self.assertEqual(got, {"files": [{"label": "Кошки"}]})

    def test_a_notification_cut_in_two_before_the_reply(self):
        got, _ = self.ask([NOTE[:30], 0.1, NOTE[30:] + reply({"a": 2})(1)])
        self.assertEqual(got, {"a": 2})

    def test_an_error_reply_is_none(self):
        err = lambda rid: jline({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "Invalid params."}})
        self.assertIsNone(self.ask([NOTE, err])[0])

    def test_a_reply_with_another_id_is_ignored(self):
        got, _ = self.ask([reply({"wrong": 1}, other=7), NOTE, 0.1, reply({"right": 1})])
        self.assertEqual(got, {"right": 1})

    def test_a_closed_socket_is_none(self):
        self.assertIsNone(self.ask([NOTE])[0])

    def test_nobody_home_is_an_oserror(self):
        with mock.patch.object(self.panel.socket, "create_connection", side_effect=ConnectionRefusedError):
            with self.assertRaises(OSError):
                self.panel.kodi("Player.GetActivePlayers")

    def test_silence_is_a_timeout(self):
        t = time.monotonic()
        with self.assertRaises(OSError):
            self.ask([NOTE, 1.5, reply({})], timeout=0.3)
        self.assertLess(time.monotonic() - t, 1.2)

    def test_a_slow_reply_within_the_timeout_still_arrives(self):
        self.assertEqual(self.ask([NOTE, 0.8, reply({"slow": True})], timeout=2)[0], {"slow": True})

    def test_notifications_without_end_do_not_hold_the_call_forever(self):
        t = time.monotonic()
        with self.assertRaises(OSError):
            self.ask([NOTE, 0.2] * 40, timeout=0.5)       # an answer never comes, a notification every 0.2 s
        self.assertLess(time.monotonic() - t, 4)

    def test_take_leaves_what_follows_the_reply(self):
        take = self.panel.kodi_take
        self.assertEqual(take(NOTE + reply({"x": 1})(1) + NOTE2[:10], 1), (True, {"x": 1}, NOTE2[:10]))
        self.assertEqual(take(NOTE + NOTE2[:10], 1), (False, None, NOTE2[:10]))
        self.assertEqual(take(b"", 1), (False, None, b""))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PANEL, encoding="utf-8") as f:
            text = f.read()
        start = text.index('PAGE = r"""') + len('PAGE = r"""')
        cls.base = panel_lang.inject(panel_accounts.inject(text[start:text.index('"""\nPAGE = panel_accounts.inject')]))
        cls.page = pw.inject(cls.base)

    def test_tab_first_and_default(self):
        p = self.page
        self.assertIn("let tab='watch'", p)
        self.assertLess(p.index('data-go="watch" class="on"'), p.index('data-go="remote"'))
        self.assertNotIn('data-go="remote" class="on"', p)
        self.assertIn('<section id="t-watch" data-tab="watch">', p)
        self.assertIn('<section id="t-remote" data-tab="remote" class="hide">', p)
        self.assertEqual(p.count('<div data-wtbar class="hide"></div>'), 2)   # the bar of «Смотреть» and the bar of «Пульт»
        self.assertLess(p.index('<div data-wtbar class="hide"></div>', p.index('id="t-remote"')), p.index('class="modes"'))
        self.assertEqual(p.count("</body>"), 1)

    def test_wide_grid(self):
        self.assertIn('"top top" "watch watch" "screen remote" "acc acc" "https wifi" "info act"', self.page)
        self.assertIn("#t-watch{grid-area:watch}", self.page)

    def test_rules_of_the_page(self):
        import panel_watch_ui as ui
        self.assertNotRegex(ui.JS + ui.SECTION, r"confirm\(|alert\(")
        self.assertIn("'/api/watch/'", ui.JS)
        self.assertEqual(len(re.findall(r"@@\w+@@", self.page.replace("@@PAGE_VER@@", ""))), 0)

    def test_a_missing_marker_raises(self):
        # the page must not come out without the tab, or with half of it
        for marker in ("@@WATCH_NAV@@", "@@WATCH_SECTION@@", "@@WATCH_BAR@@", "@@WATCH_TAIL@@", "@@RESUME_ROW@@"):
            self.assertIn(marker, self.base)
            with self.assertRaises(ValueError) as e:
                pw.inject(self.base.replace(marker, ""))
            self.assertIn(marker, str(e.exception))
        with self.assertRaises(ValueError):
            pw.inject("<html></html>")

    def test_one_player_in_a_sheet_and_a_bar_to_open_it(self):
        import panel_watch_ui as ui
        js, everything = ui.JS, ui.JS + ui.CSS + ui.SECTION + ui.BAR
        self.assertEqual(js.count("mkPlayer("), 2)                   # its definition and the one call: one instance
        self.assertIn("W.wp=mkPlayer();", js)
        for gone in ("W.rp", "wtdp", "wtnp", "wt-pfull", "wt-pback", "Крестовина", "wt-npbox", "wt-now", "'player'", "wt-toast"):
            self.assertNotIn(gone, everything)
        for text in ("Меню плеера", "Описание", "Остановить", "Закрыть", "pressKey('osd')", "pressKey('info')", "Субтитры", "Аудио",
                     "'Перемотка'", "'Громкость'", "text:'−10'", "text:'+10'"):
            self.assertIn(text, js)
        # the sheet closes on the backdrop, on «Закрыть» and on a swipe down
        self.assertIn("h('div',{class:'sheet-back wt-back',onclick:closeSheet})", js)
        self.assertIn("h('button',{class:'wt-btn wide',text:'Закрыть',onclick:closeSheet})", js)
        self.assertIn("e.changedTouches[0].clientY-swipeY>80)closeSheet()", js)
        self.assertIn("'sheet wt-sheet wt-psheet hide'", js)         # the page's one sheet look (centred, 480 px at most on a wide screen)
        self.assertIn("'sheet-box wt-box wt-pbox'", js)
        self.assertNotIn(".wt-sheet{position:fixed", ui.CSS)
        self.assertIn("art.classList.toggle('hide',!picture(st.thumb))", js)   # no picture: no empty grey box
        self.assertIn("text:'вживую'", js)
        self.assertNotIn("'LIVE'", js)
        # the bar: a tap opens the sheet, its own button only plays/pauses
        self.assertIn("function mkBar(host)", js)
        self.assertIn("onclick:openSheet", js)
        self.assertIn("e.stopPropagation();buzz();ctl({op:'playpause'})", js)
        self.assertIn("W.bars=[...document.querySelectorAll('[data-wtbar]')].map(mkBar)", js)
        self.assertIn("W.bars.forEach(b=>b.update(on?st:null))", js)   # shown only while something plays
        # polling rules as before
        self.assertIn("if(document.hidden||W.busy||!(wide()||tab==='watch'||tab==='remote'))return;", js)
        self.assertNotIn("'/api/watch/'+p,b)).catch(()=>{})", js)

    def test_the_resume_switch_sits_in_the_settings_list_after_the_language_row(self):
        p = self.page
        self.assertNotIn("@@RESUME_ROW@@", p)
        row = p.index('id="wt-resume"')
        self.assertLess(p.index('data-sp="lang"'), row)
        self.assertLess(row, p.index('data-sp="info"'))
        self.assertGreater(row, p.index('id="t-setlist"'))
        for label in ("До 720p", "До 1080p (Pi 3)", "Без лимита / 4K (Pi 5)"):
            self.assertIn(label, p)
        panel_text = open(PANEL, encoding="utf-8").read()
        self.assertIn("@@LANG_ROW@@@@RESUME_ROW@@", panel_text)
        import panel_watch_ui as ui
        self.assertIn("sg('settings')", ui.JS)
        self.assertIn("spst('settings',{quality:", ui.JS)
        self.assertIn("toast(errText(e))", ui.JS)
        # the wide layout has no settings list: the same quality selector is a card of its own there
        self.assertIn('<section id="wt-rcard"', p)
        self.assertIn("#wt-rcard{display:none!important}", ui.CSS)
        self.assertIn("#wt-rcard{display:block!important;grid-column:1/-1}", ui.CSS)

    def test_the_play_button_and_the_sections_look_right(self):
        import panel_watch_ui as ui
        import panel_watch_sweet_ui as sweet
        both = ui.CSS + sweet.CSS
        # SWEET.TV official dark midnight-navy & turquoise brand palette (no Netflix red)
        self.assertIn("#0c111b", both.lower())
        self.assertIn("#121927", both.lower())
        self.assertTrue("#00d2c6" in both.lower() or "#14e0c8" in both.lower())
        self.assertIn("#ffc857", both.lower())
        self.assertNotIn("#e50914", both.lower())
        self.assertIn("class:'wt-seg'", ui.JS)
        self.assertIn("class:'wt-upr'", ui.JS)
        self.assertIn("'Завтра'", ui.JS)

    def test_the_sweettv_pages_ask_the_routes_of_the_api(self):
        import panel_watch_ui as ui
        js = ui.JS
        self.assertIn("api('/api/sweettv/'+p)", js)
        self.assertIn("api('/api/sweettv/'+p,b)", js)
        # Netflix-style navigation pills, sticky search, detail & guide views
        for pill in ("Продолжить", "Избранное", "Шоу", "Сериалы", "Фильмы", "ТВ-каналы"):
            self.assertIn(pill, js)
        for call in ("sg('home')", "sg('shows')", "sg('show?id='", "sg('movies", "sg('series", "sg('vod?id='",
                     "sg('channels')", "sg('guide?cid='", "sg('day?cid='", "sg('top')", "sg('search?q='",
                     "spst('favourite'", "spst('play'", "spst('ctl'", "sg('settings')", "spst('settings'"):
            self.assertIn(call, js)
        for page in ("swguide", "swshow", "swvod"):
            self.assertIn(page, js)
        for day_lbl in ("Сегодня", "Вчера"):
            self.assertIn(day_lbl, js)
        # upgraded Live/DVR/VOD player sheet controls
        for ctl_text in ("С начала", "−15с", "+30с", "+2м", "В эфир", "В эфире", "от эфира"):
            self.assertIn(ctl_text, js)
        for ctl_op in ("op:'from_start'", "op:'seek_by'", "op:'live'", "st.prog_start", "st.prog_stop", "st.lag_seconds"):
            self.assertIn(ctl_op, js)
        # no markup from the API, no image that is not a picture() one
        self.assertNotIn("innerHTML", js)
        self.assertNotRegex(js, r"style:'background-image:'\s*\+\s*(?!picture)")

    def test_the_script_is_one_piece_with_the_sweettv_part(self):
        import panel_watch_ui as ui
        self.assertNotIn("@@", ui.JS + ui.CSS)
        self.assertNotIn("SWEET_JS", ui.JS)
        self.assertNotIn("SWEET_CSS", ui.CSS)
        self.assertEqual(ui.JS.count("async function renderSweet("), 1)
        self.assertEqual(ui.JS.count("const plural="), 1)

    def test_the_script_passes_node_check(self):
        import subprocess
        import panel_watch_ui as ui
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("no node here")
        src = re.search(r"<script>(.*?)</script>", ui.JS, re.S).group(1)
        path = os.path.join(TMP, "watch.js")
        put(path, src)
        done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_toast_is_the_pages(self):
        import panel_watch_ui as ui
        self.assertNotIn("function toast", ui.JS)
        self.assertNotIn("toastT", ui.JS)
        self.assertIn("toast(errText(e))", ui.JS)

    def test_it_takes_the_pages_palette(self):
        import panel_watch_ui as ui
        for gone in ("--wb", "--wc", "--wl", "wt-on", "#0f1115", "#1b1d28"):
            self.assertNotIn(gone, ui.CSS + ui.JS)
        self.assertIn("var(--card2)", ui.CSS)


class SweetRoutes(unittest.TestCase):
    def setUp(self):
        import mediastick_resume as mr
        import panel_sweettv as ps
        self.ps = ps
        self.mr = mr
        shutil.rmtree(os.environ["MEDIASTICK_RESUME_DIR"], ignore_errors=True)
        shutil.rmtree(os.environ["MEDIASTICK_PREFS_DIR"], ignore_errors=True)
        shutil.rmtree(os.environ["MEDIASTICK_SWEETNOW_DIR"], ignore_errors=True)
        put(os.path.join(TMP, ".kodi", "temp", "channelList.json"), json.dumps(FIXTURE))
        self.calls = []
        self.players = [{"playerid": 1, "type": "video"}]
        self.item = {"file": "plugin://plugin.video.sweettv/playvid/5|null", "title": "", "label": "5"}
        self.props = {"time": {"hours": 0, "minutes": 0, "seconds": 10}, "totaltime": {"hours": 0, "minutes": 1, "seconds": 0}}

    def rpc(self, method, params=None, timeout=3):
        self.calls.append((method, params))
        if method == "Player.GetActivePlayers":
            return self.players
        if method == "Player.GetItem":
            return {"item": self.item}
        if method == "Player.GetProperties":
            return self.props
        return {}

    def test_home_returns_continue_favourites_and_quality(self):
        data = self.mr.empty()
        data = self.mr.record(data, "plugin://plugin.video.sweettv/playvid/5|50", 600, 3600, NOW,
                              meta={"title": "Вчерашнее", "cid": "5", "epg": "50", "start": NOW - 7200, "stop": NOW - 3600})
        data = self.mr.record(data, "plugin://plugin.video.sweettv/playvod/9558|101|69", 300, 2400, NOW + 1,
                              meta={"title": "Серия 1", "movie_id": "9558"})
        self.mr.save(data)
        self.mr.toggle_fav("vod:9558", {"title": "Фильм", "thumb": "https://cdn.sweet.tv/f.jpg"}, now=NOW)
        self.mr.write_quality("720p")
        with mock.patch("time.time", return_value=NOW):
            body, code = self.ps.get(self.ps.PREFIX + "home", self.rpc)
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["quality"], "720p")
        self.assertGreaterEqual(len(body["continue"]), 2)
        self.assertEqual(len(body["favourites"]), 1)
        self.assertEqual(body["favourites"][0]["key"], "vod:9558")
        self.assertIn("counts", body)
        self.assertIn("labels", body)

    def test_shows_and_show_detail_and_invalid_id(self):
        self.mr.toggle_fav("show:vod:10", {"title": "Шоу 10"}, now=NOW)
        sample_shows = {"ok": True, "items": [{"id": "vod:10", "title": "Шоу 10", "thumb": "https://cdn.sweet.tv/s.jpg"}]}
        sample_detail = {"ok": True, "id": "vod:10", "title": "Шоу 10", "seasons": [{"id": 1, "episodes": []}]}
        with mock.patch.object(self.ps.api, "shows", return_value=sample_shows), \
             mock.patch.object(self.ps.api, "show_detail", return_value=sample_detail):
            body, code = self.ps.get(self.ps.PREFIX + "shows", self.rpc)
            self.assertEqual(code, 200)
            self.assertTrue(body["items"][0]["favourite"])
            body, code = self.ps.get(self.ps.PREFIX + "show?id=vod:10", self.rpc)
            self.assertEqual(code, 200)
            self.assertEqual(body["id"], "vod:10")
        for bad in ("", "bogus", "vod:abc", "epg:", "tv:x"):
            _, code = self.ps.get(self.ps.PREFIX + "show?id=" + bad, self.rpc)
            self.assertEqual(code, 400, bad)

    def test_movies_series_and_vod_detail(self):
        cfg = {"ok": True, "genres": [{"id": 10, "caption": "Комедия"}], "sort_modes": [{"id": 1, "caption": "Популярные"}]}
        page = {"ok": True, "items": [{"id": 9558, "title": "Фильм"}], "total": 1, "offset": 0, "limit": 30, "has_more": False}
        vod = {"ok": True, "id": "9558", "title": "Фильм", "seasons": [], "episodes": [], "imdb": 7.5, "year": 2024,
               "duration": 120, "description": "Desc", "resume": 0, "favourite": False}
        with mock.patch.object(self.ps.api, "configuration", return_value=cfg), \
             mock.patch.object(self.ps.api, "catalog_page", return_value=page) as cat_mock, \
             mock.patch.object(self.ps.api, "vod_detail", return_value=vod):
            b1, c1 = self.ps.get(self.ps.PREFIX + "movies?genre=10&sort=1&offset=0&limit=30", self.rpc)
            self.assertEqual(c1, 200)
            self.assertEqual(b1["genres"], cfg["genres"])
            self.assertEqual(b1["sort_modes"], cfg["sort_modes"])
            b2, c2 = self.ps.get(self.ps.PREFIX + "series?offset=30&limit=20", self.rpc)
            self.assertEqual(c2, 200)
            self.assertEqual(cat_mock.call_args[0][0], "series")
            b3, c3 = self.ps.get(self.ps.PREFIX + "vod?id=9558", self.rpc)
            self.assertEqual((c3, b3["id"]), (200, "9558"))
        for bad in ("", "abc", "-1"):
            self.assertEqual(self.ps.get(self.ps.PREFIX + "vod?id=" + bad, self.rpc)[1], 400, bad)

    def test_channels_guide_day_top_and_search(self):
        self.mr.toggle_fav("ch:5", {"title": "Первый"}, now=NOW)
        with mock.patch("time.time", return_value=NOW):
            body, code = self.ps.get(self.ps.PREFIX + "channels", self.rpc)
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(any(c["id"] == "5" and c["favourite"] for c in body["channels"]))
        self.assertIn("categories", body)
        with mock.patch.object(self.ps.api, "top_search", return_value={"ok": True, "items": []}):
            self.assertEqual(self.ps.get(self.ps.PREFIX + "top", self.rpc)[1], 200)
        with mock.patch.object(self.ps.api, "search", return_value={"ok": True, "items": []}):
            self.assertEqual(self.ps.get(self.ps.PREFIX + "search?q=news", self.rpc)[1], 200)

    def test_favourite_toggle_and_invalid_key(self):
        body, code = self.ps.post(self.ps.PREFIX + "favourite",
                                  {"key": "ch:5", "title": "Первый", "thumb": "https://cdn.sweet.tv/c.png"}, self.rpc)
        self.assertEqual((code, body["ok"], body["favourite"]), (200, True, True))
        body, code = self.ps.post(self.ps.PREFIX + "favourite", {"key": "ch:5"}, self.rpc)
        self.assertEqual((code, body["ok"], body["favourite"]), (200, True, False))
        for bad in ({}, None, [], {"key": ""}, {"key": "bad:5"}):
            self.assertEqual(self.ps.post(self.ps.PREFIX + "favourite", bad, self.rpc)[1], 400, bad)

    def test_play_live_archive_from_start_and_vod(self):
        with mock.patch("time.time", return_value=NOW):
            # live channel
            b, c = self.ps.post(self.ps.PREFIX + "play", {"cid": 5}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][1]["item"]["file"], "plugin://plugin.video.sweettv/playvid/5|null")
            # in-progress EPG programme from_start=True -> offset 0
            b, c = self.ps.post(self.ps.PREFIX + "play", {"cid": 5, "epg": 50, "from_start": True}, self.rpc)
            self.assertEqual((c, b["ok"], b["epg"], b["offset"]), (200, True, "50", 0))
            # VOD movie/episode -> playvod/...
            b, c = self.ps.post(self.ps.PREFIX + "play", {"movie_id": 9558, "episode_id": 101, "owner_id": 69, "start": 120}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][1]["item"]["file"], "plugin://plugin.video.sweettv/playvod/9558|101|69?start=120")
            # invalid
            self.assertEqual(self.ps.post(self.ps.PREFIX + "play", {"cid": "bad"}, self.rpc)[1], 400)
            self.assertEqual(self.ps.post(self.ps.PREFIX + "play", {"movie_id": "bad"}, self.rpc)[1], 400)

    def test_ctl_from_start_seek_by_live_handoff_and_go_live(self):
        with mock.patch("time.time", return_value=NOW):
            # from_start on live catchup channel -> switches to current programme at 0:00
            b, c = self.ps.post(self.ps.PREFIX + "ctl", {"op": "from_start"}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][1]["item"]["file"], "plugin://plugin.video.sweettv/playvid/5|50")
            # seek_by -15 on live catchup channel -> rewinds into archive
            b, c = self.ps.post(self.ps.PREFIX + "ctl", {"op": "seek_by", "seconds": -15}, self.rpc)
            self.assertEqual((c, b["ok"], b["switched"]), (200, True, "archive"))
            # seek_by on in-progress archive within <= 15s of live edge -> forward_handoff to live
            self.item = {"file": "plugin://plugin.video.sweettv/playvid/5|50", "title": "Сейчас Первый"}
            self.props = {"time": {"hours": 0, "minutes": 29, "seconds": 50}, "totaltime": {"hours": 1, "minutes": 0, "seconds": 0}}
            # NOW - (NOW - 1800) = 1800s is live edge; 1790 + 30 = 1820 >= 1800 - 15 -> handoff to live
            b, c = self.ps.post(self.ps.PREFIX + "ctl", {"op": "seek_by", "seconds": 30}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][1]["item"]["file"], "plugin://plugin.video.sweettv/playvid/5|null")
            # seek_by on in-progress archive staying > 15s behind live edge -> Player.Seek, no handoff
            self.props = {"time": {"hours": 0, "minutes": 10, "seconds": 0}, "totaltime": {"hours": 1, "minutes": 0, "seconds": 0}}
            b, c = self.ps.post(self.ps.PREFIX + "ctl", {"op": "seek_by", "seconds": 120}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][0], "Player.Seek")
            # live op on archive -> returns to live
            b, c = self.ps.post(self.ps.PREFIX + "ctl", {"op": "live"}, self.rpc)
            self.assertEqual((c, b["ok"]), (200, True))
            self.assertEqual(self.calls[-1][1]["item"]["file"], "plugin://plugin.video.sweettv/playvid/5|null")
        # invalid ops and no player
        for bad in ({}, None, {"op": "bogus"}, {"op": "seek_by", "seconds": "10"}, {"op": "seek_by", "seconds": True}):
            self.assertEqual(self.ps.post(self.ps.PREFIX + "ctl", bad, self.rpc)[1], 400, bad)
        self.players = []
        self.assertEqual(self.ps.post(self.ps.PREFIX + "ctl", {"op": "from_start"}, self.rpc)[1], 409)

    def test_decorate_exposes_unified_live_catchup_timeline(self):
        live_view = {"playing": True, "app": "sweettv", "cid": "5", "epg": "", "live": True, "time": 10, "total": 60}
        d = self.ps.decorate(live_view, FIXTURE, NOW)
        self.assertEqual(d["programme"], "Сейчас Первый")
        self.assertEqual((d["prog_start"], d["prog_stop"]), (NOW - 1800, NOW + 1800))
        self.assertTrue(d["in_progress"])
        self.assertTrue(d["can_rewind"])
        self.assertFalse(d["go_live"])
        self.assertFalse(d["is_vod"])
        self.assertGreaterEqual(d["lag_seconds"], 0)
        vod_view = {"playing": True, "app": "sweettv", "cid": "", "epg": "", "live": False,
                    "file": "plugin://plugin.video.sweettv/playvod/9558|101|69", "time": 100, "total": 2400}
        dv = self.ps.decorate(vod_view, FIXTURE, NOW)
        self.assertTrue(dv["is_vod"])
        self.assertFalse(dv["can_rewind"])
        self.assertFalse(dv["go_live"])

    def test_legacy_sweettv_compat_wrappers_and_routes_are_removed(self):
        for attr in ("sections", "sections_view", "shows_view", "show_view", "films_view"):
            self.assertFalse(hasattr(self.ps, attr), attr)
        for route in ("sections", "films"):
            body, code = self.ps.get(self.ps.PREFIX + route, self.rpc)
            self.assertEqual(code, 404, route)
            self.assertIn("error", body)

    def test_legacy_sweetsections_scraper_and_references_are_retired(self):
        legacy_mod = "mediastick_" + "sweetsections"
        self.assertFalse(os.path.exists(os.path.join(LIB, legacy_mod + ".py")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "tools", "test-" + "sweetsections.py")))
        for folder in ("device", "tools"):
            base = os.path.join(ROOT, folder)
            for dirpath, _, filenames in os.walk(base):
                for fname in filenames:
                    if not fname.endswith((".py", ".sh", ".conf", ".xml", ".md")):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        self.assertNotIn(legacy_mod, f.read(), os.path.relpath(fpath, ROOT))

    def test_readme_documents_new_sweettv_routes_and_emulator(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        for token in ("/api/sweettv/home", "/api/sweettv/shows", "/api/sweettv/show", "/api/sweettv/movies",
                      "/api/sweettv/series", "/api/sweettv/vod", "/api/sweettv/favourite", "/api/sweettv/top",
                      "/api/sweettv/search", "/api/sweettv/day", "/api/sweettv/settings", "tools/emulator/"):
            self.assertTrue(token in readme, f"{token} not found in README.md")

    def test_shows_api_view_and_show_api_view_pass_raw_channels(self):
        with mock.patch.object(self.ps.api, "shows", return_value={"ok": True, "items": []}) as shows_mock, \
             mock.patch.object(self.ps.api, "show_detail", return_value={"ok": True, "id": "epg:8838", "episodes": []}) as detail_mock:
            self.ps.shows_api_view(FIXTURE, NOW)
            self.assertIs(shows_mock.call_args[0][0], FIXTURE)
            self.ps.show_api_view(FIXTURE, "epg:8838", NOW)
            self.assertIs(detail_mock.call_args[0][1], FIXTURE)

    def test_emulator_run_sh_configures_panel_port_symlinks_channels_and_disables_webserver(self):
        with open(os.path.join(ROOT, "tools", "emulator", "run.sh"), encoding="utf-8") as f:
            script = f.read()
        self.assertIn("PANEL_PORT=${PANEL_PORT:-18080}", script)
        self.assertIn("chmod +x /usr/local/bin/*", script)
        self.assertIn("python3 /usr/local/bin/panel", script)
        self.assertIn("/home/media/.kodi", script)
        self.assertIn("SWEETTV_CHANNELS", script)
        self.assertIn("channelList.json", script)
        self.assertIn("<webserver>false</webserver>", script)
        self.assertIn("<tcpport>9090</tcpport>", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
