#!/usr/bin/env python3
"""Offline test of the Смотреть part of the panel (no Kodi, no device):
python3 tools/test-panel-watch.py

The pure functions of panel_watch (pictures, what may be played, the channel list, YouTube directories,
control requests), the routes against a fake Kodi, and the injection into the real page of `panel`.
The add-on's own modules (youtube_data, sweettv_data, apps) are loaded from the repository, as the panel
does on a device that has no copy yet."""
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, ".kodi", "userdata", "addon_data")
os.environ.pop("MEDIASTICK_ADDON_LIB", None)
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

import panel_accounts  # noqa: E402
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

    def test_rejects(self):
        for f in (YT, YT + "special/my_subscriptions", YT + "kodion/search/query/?q=x", YT + "play/../x",
                  "plugin://plugin.video.other/play/?video_id=abcdefghijk",
                  "plugin://plugin.video.youtube.evil/play/?x=1", "http://example.com/play/",
                  "/home/media/x.mp4", "smb://nas/film.mkv", "plugin://plugin.video.sweettv/playvid/12",
                  "plugin://plugin.video.sweettv/playvid/ab|null", "plugin://plugin.video.sweettv/playvid/12|x",
                  "plugin://plugin.video.sweettv/playvid/12|null|rm", "plugin://plugin.video.sweettv/other/12|null",
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
        self.assertEqual(pw.app_of("/x.mkv"), "other")


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


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PANEL, encoding="utf-8") as f:
            text = f.read()
        start = text.index('PAGE = r"""') + len('PAGE = r"""')
        cls.base = panel_accounts.inject(text[start:text.index('"""\nPAGE = panel_accounts.inject')])
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
        for marker in ("@@WATCH_NAV@@", "@@WATCH_SECTION@@", "@@WATCH_BAR@@", "@@WATCH_TAIL@@"):
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
        self.assertIn("h('div',{class:'wt-back',onclick:closeSheet})", js)
        self.assertIn("h('button',{class:'wt-btn wide',text:'Закрыть',onclick:closeSheet})", js)
        self.assertIn("e.changedTouches[0].clientY-swipeY>80)closeSheet()", js)
        self.assertIn(".wt-psheet .wt-box{max-width:480px", ui.CSS)  # centred, 480 px at most on a wide screen
        # the bar: a tap opens the sheet, its own button only plays/pauses
        self.assertIn("function mkBar(host)", js)
        self.assertIn("onclick:openSheet", js)
        self.assertIn("e.stopPropagation();buzz();ctl({op:'playpause'})", js)
        self.assertIn("W.bars=[...document.querySelectorAll('[data-wtbar]')].map(mkBar)", js)
        self.assertIn("W.bars.forEach(b=>b.update(on?st:null))", js)   # shown only while something plays
        # polling rules as before
        self.assertIn("if(document.hidden||W.busy||!(wide()||tab==='watch'||tab==='remote'))return;", js)
        self.assertNotIn("'/api/watch/'+p,b)).catch(()=>{})", js)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
