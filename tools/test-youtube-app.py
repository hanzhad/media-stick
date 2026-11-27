#!/usr/bin/env python3
"""Offline test of the YouTube app (no Kodi, no device, no network): python3 tools/test-youtube-app.py

The pure part (youtube_data, youtube_state, youtube_demo) is tested directly; the window runs on stubbed xbmc, xbmcgui,
xbmcaddon and xbmcvfs, with a stand-in for the YouTube add-on's directories, and the sign-in library the real one on a
temp directory."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

import calendar  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
import zlib  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
SKIN = os.path.join(ADDON, "resources", "skins", "default", "1080i")
MEDIA = os.path.join(ADDON, "resources", "skins", "default", "media")
XML = os.path.join(SKIN, "script-media-stick-youtube.xml")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["TZ"] = "UTC"
time.tzset()


class Fake:
    """What the stubbed Kodi shows and does."""
    builtins, notes, rpc, played, typed = [], [], [], [], []
    playing = False
    stopped = 0
    home = {}
    now = None
    signed, keys, name, profile = True, True, "Anna", "p1"             # profile: the id of the add-on's current profile
    step, phone = None, ("http://192.168.1.20/", "/tmp/qr.png")      # the key wizard's step; the phone page and its QR


class Control:
    def __init__(self):
        self.items, self.selected = [], 0

    def reset(self):
        self.items, self.selected = [], 0

    def addItems(self, items):
        self.items += list(items)                # Kodi's addItems appends

    def selectItem(self, i):
        self.selected = i

    def getSelectedPosition(self):
        return self.selected if self.items else -1

    def size(self):
        return len(self.items)


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2, self.props, self.art = label, label2, {}, {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def setArt(self, art):
        self.art = dict(art)


class WindowXML:
    def __init__(self, *a):
        self._props, self.focus = {}, 0
        self.controls = {100: Control(), 200: Control(), 300: Control()}
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

    def doModal(self):
        self.onInit()

    def onAction(self, action):
        pass


class HomeWindow:
    def __init__(self, *a):
        pass

    def setProperty(self, key, value):
        Fake.home[key] = value

    def getProperty(self, key):
        return Fake.home.get(key, "")


class Action:
    def __init__(self, action_id, button=0):
        self.id, self.button = action_id, button

    def getId(self):
        return self.id

    def getButtonCode(self):
        return self.button


class Player:
    def isPlaying(self):
        return Fake.playing

    def stop(self):
        Fake.stopped += 1


def translate(path):
    for special, name in (("special://temp", "temp"), ("special://profile", "profile")):
        if path.startswith(special):
            return TMP + "/" + name + path[len(special):]
    return path


class Dialog:
    def notification(self, heading, text, *a, **k):
        Fake.notes.append(text)

    def input(self, heading, defaultt="", *a, **k):
        Fake.asked = (heading, defaultt)
        return Fake.typed.pop(0) if Fake.typed else ""


xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: Fake.builtins.append(cmd)
xbmc.executeJSONRPC = lambda req: Fake.rpc.append(req) or "{}"
xbmc.getCondVisibility = lambda cond: True
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
xbmcgui.Dialog = Dialog
xbmcgui.NOTIFICATION_INFO = "info"
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui, xbmcaddon=xbmcaddon)
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

from resources.lib import (accounts, apps, page_cache, prefetch, profiles, store, youtube_app, youtube_cards as C,  # noqa: E402
                           youtube_data as D, youtube_demo as demo, youtube_files as files, youtube_pages as P,
                           youtube_state as S)
import mediastick_ui_context  # noqa: E402
import panel_ui_context  # noqa: E402

R = D.ROOT
REAL_KEYS_POLL = youtube_app.KEYS_POLL            # the window tests make it short
RAIL, GRID, ACTION = youtube_app.RAIL, youtube_app.GRID, youtube_app.ACTION
AVATAR = youtube_app.AVATAR                                        # 150: the button over the circle of the account
KIND_IDS = tuple(youtube_app.KIND_BUTTONS)                         # 401..404: Videos, Channels, Playlists, Live
UP, DOWN = youtube_app.ACTION_MOVE_UP, youtube_app.ACTION_MOVE_DOWN
SEARCH_AT = D.SECTION_KEYS.index(D.SEARCH)
LATER = R + "special/playlist/WL/?category_label=Watch+Later"     # not the fallback path: the main page decides
INVALID = {"id": 1, "jsonrpc": "2.0", "error": {"code": -32602, "message": "Invalid params."}}    # what the add-on says to a path it does not serve


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def vid(n, title=None, channel="Chan", seconds=65, **extra):
    title = title or f"Video {n}"
    return {"file": f"{R}play/?video_id=v{n}", "filetype": "file", "label": title, "title": title, "thumbnail": "",
            "art": {"thumb": f"https://i.ytimg.com/vi/v{n}/hq.jpg"}, "plot": "", "duration": seconds,
            "runtime": seconds, "studio": [channel], **extra}


def folder(path, title, **extra):
    return {"file": path, "filetype": "directory", "label": title, "title": title, **extra}


def answer(*files):
    return {"id": 1, "jsonrpc": "2.0", "result": {"files": list(files)}}


def main_page():
    tiles = [folder(s.route, s.name) for s in D.SECTIONS if s.route and s.key != "later"]
    return answer(folder(R + "sign/in/", "Sign In", filetype="file"), *tiles, folder(LATER, "Watch Later"),
                  folder(R + "kodion/search/input/", "Search"))


# What plugin.video.youtube 7.4.4 really listed on its main page and answered for a video, as seen on a device
# (label -> file, filetype), in the form Files.GetDirectory gives it. The routes of the actions are not known.
REAL_TILES = [
    ("[B]Sign In[/B]", "sign/in/?category_label=Sign+In", "file"),
    ("[B]My Subscriptions[/B]", "special/my_subscriptions?category_label=My+Subscriptions", "directory"),
    ("Recommendations", "special/recommendations?category_label=Recommendations", "directory"),
    ("Related Videos", "special/related_videos?category_label=Related+Videos", "directory"),
    ("Trending", "special/popular_right_now?category_label=Trending", "directory"),
    ("Search", "kodion/search/list/?category_label=Search", "directory"),
    ("My Channel", "channel/mine?category_label=My+Channel", "directory"),
    ("Watch Later", "special/playlist/WL/?category_label=Watch+Later", "directory"),
    ("Disliked Videos", "special/disliked_videos?category_label=Disliked+Videos", "directory"),
    ("History", "special/playlist/HL/?category_label=History", "directory"),
    ("Playlists", "channel/mine/playlists?category_label=Playlists", "directory"),
    ("Subscribed Channels", "subscriptions/list/?category_label=Subscribed+Channels", "directory"),
    ("Bookmarks", "kodion/bookmarks/list/?category_label=Bookmarks", "directory"),
    ("Browse Channels", "special/browse_channels?category_label=Browse+Channels", "directory"),
    ("Completed Live Events", "special/live_events/completed?category_label=Completed+Live+Events", "directory"),
    ("Upcoming Live Events", "special/live_events/upcoming?category_label=Upcoming+Live+Events", "directory"),
    ("Live broadcast", "special/live?category_label=Live+broadcast", "directory"),
    ("Switch User", "users/switch/?category_label=Switch+User", "file"),
    ("Sign Out", "sign/out/?category_label=Sign+Out", "file"),
    ("Setup Wizard", "config/setup_wizard/?category_label=Setup+Wizard", "file"),
]
REAL_RECOMMENDATIONS = R + "special/recommendations?category_label=Recommendations"
REAL_SUBSCRIPTIONS = R + "special/my_subscriptions?category_label=My+Subscriptions"


def real_main_page():
    return answer(*({"file": R + path, "filetype": kind, "label": label} for label, path, kind in REAL_TILES))


def real_video(n, title=None, **extra):
    """A video of Recommendations: no duration, no plot, the channel unknown (artist ["Untitled"]), the thumbnail
    wrapped in image:// and url-encoded, the add-on's own picture as fanart."""
    title = title or f"Real video {n}"
    return {"file": f"{R}play/?video_id=ID{n}", "filetype": "file", "label": title, "title": title, "plot": "",
            "thumbnail": f"image://https%3a%2f%2fi.ytimg.com%2fvi%2fID{n}%2fhqdefault.jpg/", "runtime": 0,
            "art": {"fanart": "special://home/addons/plugin.video.youtube/resources/media/fanart.jpg"},
            "studio": "", "artist": ["Untitled"], **extra}


# ---- the pure part ---------------------------------------------------------------------------

class Parser(unittest.TestCase):
    def test_text_loses_kodi_markup_and_control_characters(self):
        self.assertEqual(D.clean_text("[B]Live[/B] now [COLOR red]red[/COLOR][CR]next"), "Live now red next")
        self.assertEqual(D.clean_text("a [odd] one\n\ttwo\x00"), "a (odd) one two")
        self.assertEqual(D.clean_text(None), "")
        self.assertEqual(D.clean_text(True), "")
        self.assertEqual(D.clean_text("x" * 500, 10), "x" * 10)
        self.assertEqual(D.clean_text("Привіт, світе"), "Привіт, світе")

    def test_what_the_font_cannot_draw_is_taken_out_of_titles_and_channels(self):
        for raw, clean in (("Winter in New York ❄️ Snowfall", "Winter in New York Snowfall"),     # the owner's example
                           ("🔥🔥 Hot 🔥🔥", "Hot"), ("👨‍👩‍👧 Family day", "Family day"), ("Hello‍World", "HelloWorld"),
                           ("Left → right ← and ✔ done ★", "Left right and done"), ("tick ⏰ tock ①", "tick tock"),
                           ("Bad�byte", "Badbyte"), ("lone \ud83d half \ude00", "lone half"), ("a️b", "ab"),
                           ("𝐇𝐞𝐥𝐥𝐨 𝗪𝗼𝗿𝗹𝗱", "Hello World"), ("  many   spaces \n here ", "many spaces here")):
            self.assertEqual(D.clean_text(raw), clean, raw)
        for kept in ("Привіт, світе! «Тест» – “цитата” … 100%", "Café – naïve ½ ™ © №5 • x × y", "Rock & Roll: Part 2 (live) — 3:45",
                     "Ёжик, Їжак, Ґанок, ЩЬ"):
            self.assertEqual(D.clean_text(kept), kept)
        for code in list(range(0x2190, 0x2C00)) + list(range(0x1F000, 0x20000, 37)) + [0xFE0F, 0x200D, 0xFFFD, 0xD83D, 0xDE00]:
            self.assertEqual(D.clean_text(f"a{chr(code)}b"), "ab", hex(code))
        entry = D.parse_entry({"file": R + "play/?video_id=a", "filetype": "file", "title": "Winter in New York ❄️ Snowfall",
                               "studio": ["Orbit Lab 🚀"], "artist": ["🎵"]})
        self.assertEqual((entry.title, entry.channel), ("Winter in New York Snowfall", "Orbit Lab"))
        self.assertEqual(D.parse_entry({"file": R + "play/?video_id=a", "title": "❄️❄️", "artist": ["🎵"]}).title, "Untitled")
        self.assertEqual(D.name_of(["🎵"], "🔥 Real 🔥"), "Real")                               # an all-symbol name is no name

    def test_a_video_without_a_picture_gets_the_one_youtube_has(self):
        url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        bare = {"file": R + "play/?video_id=dQw4w9WgXcQ", "filetype": "file", "label": "L"}
        self.assertEqual(D.parse_entry(bare).thumb, url)
        self.assertEqual(D.parse_entry({**bare, "thumbnail": "image://x"}).thumb, "image://x")      # the add-on's own wins
        fanart = {"fanart": "special://home/addons/plugin.video.youtube/resources/media/fanart.jpg"}
        self.assertEqual(D.parse_entry({**bare, "art": fanart}).thumb, url)                         # better than the add-on's logo
        self.assertEqual(D.parse_entry({**bare, "art": {**fanart, "poster": "/p.png"}}).thumb, "/p.png")
        for path in ("play/?video_id=short", "play/?video_id=", "play/?x=dQw4w9WgXcQ", "play/?video_id=dQw4w9WgXc!",
                     "play/?video_id=dQw4w9WgXcQQ", "play/?video_id=demo00"):                       # not a real id: no address
            self.assertEqual(D.parse_entry({"file": R + path, "filetype": "file", "art": fanart}).thumb, fanart["fanart"], path)
            self.assertEqual(D.parse_entry({"file": R + path, "filetype": "file"}).thumb, "", path)
        listed = D.parse_entry({"file": R + "playlist/PL1/?video_id=dQw4w9WgXcQ", "filetype": "directory"})
        self.assertEqual(listed.thumb, "")                                                          # only a video has one
        self.assertEqual(D.thumb_url("not a path"), "")

    def test_what_is_known_about_a_video_is_read_and_what_is_not_is_left_out(self):
        full = D.parse_entry(vid(1, views="1,234", dateadded="2026-11-20 10:00:00", live=True, playcount=2,
                                 resume={"position": 30, "total": 120}))
        self.assertEqual((full.views, full.published, full.live, full.progress, full.count),
                         (1234, calendar.timegm((2026, 11, 20, 10, 0, 0)), True, 0.25, 0))
        self.assertEqual(D.parse_entry(vid(1, playcount=1)).progress, 1.0)                         # played to the end
        self.assertEqual(D.parse_entry(vid(1, resume={"position": 0, "total": 100})).progress, 0.0)
        self.assertEqual(D.parse_entry(vid(1, resume={"position": 500, "total": 100})).progress, 1.0)
        for none in ({}, {"live": "yes"}, {"live": 1}, {"views": True}, {"views": -3}, {"views": 10 ** 13}, {"views": "many"},
                     {"dateadded": "1999-01-01"}, {"dateadded": "2026-13-45"}, {"dateadded": "x"}, {"dateadded": 5},
                     {"playcount": 0}, {"resume": 5}, {"resume": {"position": "x"}}):
            card = D.parse_entry(vid(1, **none))
            self.assertEqual((card.views, card.published, card.live, card.progress), (0, 0, False, 0.0), none)
        self.assertEqual(D.as_count("12 345"), 12345)
        self.assertEqual(D.as_epoch("2026-11-20"), calendar.timegm((2026, 11, 20, 0, 0, 0)))
        self.assertEqual(D.as_epoch("2026-11-20T10:00:00Z"), calendar.timegm((2026, 11, 20, 10, 0, 0)))
        playlist = D.parse_entry(folder(R + "playlist/P/", "L", videos=24, views=99, playcount=1, live=True))
        self.assertEqual((playlist.count, playlist.views, playlist.progress, playlist.live), (24, 0, 0.0, False))
        self.assertTrue({"playcount", "resume", "dateadded"} <= set(D.PROPERTIES))

    def test_durations(self):
        for raw, seconds in ((65, 65), (65.0, 65), ("65", 65), ("1:05", 65), ("1:01:05", 3665), (0, 0), (-3, 0),
                             (True, 0), (None, 0), ("x", 0), (float("nan"), 0), (10 ** 9, 0), ("1:2:3:4", 0)):
            self.assertEqual(D.as_seconds(raw), seconds, raw)
        self.assertEqual([D.format_duration(s) for s in (0, 5, 65, 3599, 3600, 3725, "x")],
                         ["", "0:05", "1:05", "59:59", "1:00:00", "1:02:05", ""])

    def test_a_video_a_playlist_the_next_page_and_what_is_no_card(self):
        listing = D.parse_reply(answer(
            vid(1, "[B]One[/B]", "The Channel", 125),
            folder(R + "playlist/PL1/", "A playlist", art={"thumb": "/x/y.png"}),
            folder(R + "special/recommendations/?page=2", "Next Page"),
            folder(R + "sign/in/", "Sign In", filetype="file"),                       # an action, not a video
            {"file": "/home/media/video.mkv", "filetype": "file", "label": "Not YouTube"},
            {"file": "plugin://plugin.video.other/play/?x=1", "filetype": "file", "label": "Other add-on"},
            vid(1)))                                                                   # the same video twice
        self.assertEqual([(e.kind, e.title) for e in listing.entries], [(D.VIDEO, "One"), (D.FOLDER, "A playlist")])
        one = listing.entries[0]
        self.assertEqual((one.channel, one.seconds, one.thumb), ("The Channel", 125, "https://i.ytimg.com/vi/v1/hq.jpg"))
        self.assertEqual(listing.entries[1].thumb, "/x/y.png")
        self.assertEqual((listing.more, listing.error, listing.skipped), (R + "special/recommendations/?page=2", "", 4))

    def test_missing_fields_get_sensible_values(self):
        entry = D.parse_entry({"file": R + "play/?video_id=a", "filetype": "file"})
        self.assertEqual((entry.title, entry.channel, entry.seconds, entry.thumb), ("Untitled", "", 0, ""))
        entry = D.parse_entry({"file": R + "play/?video_id=a", "label": "L", "runtime": 90, "artist": ["", "Artist"],
                               "thumbnail": "image://x"})
        self.assertEqual((entry.title, entry.channel, entry.seconds, entry.thumb), ("L", "Artist", 90, "image://x"))
        self.assertEqual(D.parse_entry({"file": R + "play/?video_id=a", "filetype": "file", "studio": "Solo"}).channel, "Solo")

    def test_odd_input_never_raises(self):
        junk = [None, 5, "x", [], {}, {"file": None}, {"file": 3}, {"file": R + "play/?v=1", "art": 4, "studio": 7},
                {"file": R + "play/?v=2", "art": {"thumb": 9}, "duration": {"a": 1}, "title": ["no"]},
                {"file": R + "play/?v=\n3", "filetype": "file"}, {"file": R + "x" * 5000, "filetype": "directory"},
                {"file": "plugin://plugin.video.youtube/", "filetype": 7}]
        for item in junk:
            D.parse_entry(item) if isinstance(item, dict) else D.parse_reply(answer(item))
        listing = D.parse_reply(answer(*junk))
        self.assertEqual([e.path for e in listing.entries], [R + "play/?v=1", R + "play/?v=2"])
        for raw in (None, [], "x", 5, {}, {"result": None}, {"result": []}, {"result": {"files": "no"}},
                    {"error": None, "result": {"files": 3}}, {"error": 5}, {"error": {"message": ["x"]}}):
            self.assertIsInstance(D.parse_reply(raw), D.Listing)

    def test_an_answer_with_no_files_is_empty_not_an_error_and_a_failure_is_an_error(self):
        empty = D.parse_reply({"result": {"limits": {"start": 0, "end": 0, "total": 0}}})
        self.assertEqual((empty.entries, empty.error), ((), ""))
        for raw in (None, {}, {"result": 1}):
            self.assertTrue(D.parse_reply(raw).error)
        failed = D.parse_reply({"error": {"code": -32100, "message": "Plugin [B]failed[/B]"}})
        self.assertEqual(failed.error, "Plugin failed")
        self.assertTrue(D.parse_reply({"error": {"code": 1}}).error)

    def test_a_page_is_added_without_repeating_cards(self):
        first = D.parse_reply(answer(vid(1), vid(2), folder(R + "x/?page=2", "Next Page")))
        page = D.parse_reply(answer(vid(2), vid(3)))
        merged = D.merge(first, page)
        self.assertEqual([e.title for e in merged.entries], ["Video 1", "Video 2", "Video 3"])
        self.assertEqual(merged.more, "")

    def test_routes_are_found_on_the_main_page_by_the_words_in_the_path(self):
        found = D.discover_routes(D.parse_reply(main_page()))
        self.assertEqual(found["later"], LATER)
        self.assertEqual(found["rec"], R + "special/recommendations/")
        self.assertNotIn(D.SEARCH, found)
        self.assertEqual(D.discover_routes(D.NO_LISTING), {})
        tiles = D.parse_reply(answer(folder(R + "kodion/search/history/", "History of searches"),
                                     folder(R + "subscriptions/list/", "Channels"),
                                     folder(R + "special/new_uploaded_videos_tv/", "My Subscriptions")))
        self.assertEqual(D.discover_routes(tiles), {"subs": R + "special/new_uploaded_videos_tv/"})     # the feed, not the channel list

    def test_views_search_routes_and_the_header_line(self):
        self.assertEqual(D.section_view("rec").route, D.SECTIONS[0].route)
        self.assertEqual(D.section_view("later", {"later": LATER}).route, LATER)
        self.assertTrue(D.section_view("later").needs_login)
        self.assertEqual(D.section_view("nonsense").key, "rec")
        view = D.section_view(D.SEARCH, query="  rock  &  roll ")
        self.assertEqual((view.route, view.needs_login), (R + "kodion/search/query/?q=rock+%26+roll", False))
        self.assertEqual(D.section_view(D.SEARCH).route, "")
        self.assertEqual(D.search_route("x" * 500), D.search_route("x" * 80))
        folder_view = D.folder_view(D.parse_entry(folder(R + "playlist/P/", "Mix")))
        self.assertEqual(D.crumb([(D.section_view("lists"), 0)], folder_view), "Playlists › Mix")
        self.assertEqual(D.crumb([], D.section_view("rec")), "Recommendations")

    def test_the_search_route_asks_for_the_type(self):
        base = R + "kodion/search/query/?q=cats"
        self.assertEqual(D.search_route("cats"), base)                                       # Videos: the add-on's default
        self.assertEqual(D.search_route("cats", D.KIND_VIDEO), base)
        self.assertEqual(D.search_route("cats", D.KIND_CHANNEL), base + "&search_type=channel")
        self.assertEqual(D.search_route("cats", D.KIND_PLAYLIST), base + "&search_type=playlist")
        self.assertEqual(D.search_route("cats", D.KIND_LIVE), base + "&search_type=video&event_type=live")
        self.assertEqual(D.search_route("cats", "nonsense"), base)
        self.assertEqual([D.search_route("  ", kind) for kind in D.KIND_KEYS], [""] * 4)     # no words, no route
        self.assertEqual(D.search_route("a b&c", D.KIND_CHANNEL), R + "kodion/search/query/?q=a+b%26c&search_type=channel")
        self.assertEqual([k.name for k in D.KINDS], ["Videos", "Channels", "Playlists", "Live"])
        self.assertEqual(D.DEFAULT_KIND, D.KINDS[0].key)
        for kind in D.KIND_KEYS:                                                              # and the route says it back
            self.assertEqual(D.route_kind(D.search_route("cats", kind)), kind)
        self.assertEqual(D.route_kind(R + "kodion/search/query/?q=x&search_type=video&event_type=upcoming"), D.KIND_VIDEO)

    def test_a_search_view_has_a_type_and_the_old_calls_still_work(self):
        view = D.section_view(D.SEARCH, query="owls", kind=D.KIND_PLAYLIST)
        self.assertEqual((view.key, view.kind, view.route, view.title),
                         (D.SEARCH, D.KIND_PLAYLIST, R + "kodion/search/query/?q=owls&search_type=playlist", "Results for “owls”"))
        self.assertEqual(D.section_view(D.SEARCH, None, "owls").kind, D.KIND_VIDEO)          # the old positional call: Videos
        self.assertEqual(D.section_view(D.SEARCH, None, "owls", D.KIND_LIVE).kind, D.KIND_LIVE)
        self.assertEqual(D.section_view(D.SEARCH, kind=D.KIND_LIVE).route, "")               # nothing typed yet: no route
        self.assertEqual(D.section_view(D.SEARCH, query="x", kind="nonsense").kind, D.KIND_VIDEO)
        self.assertEqual(D.section_view("rec", kind=D.KIND_LIVE).kind, "")                   # only a search has a type
        self.assertEqual(D.View("folder", "T", "plugin://x", False).kind, "")

    def test_the_add_ons_type_switch_tiles_are_no_cards_but_the_real_results_and_the_next_page_stay(self):
        query = R + "kodion/search/query/?q=cats"
        tiles = [folder(query + extra, name) for name, extra in (
            ("Videos", "&search_type=video"), ("Channels", "&search_type=channel"), ("Playlists", "&search_type=playlist"),
            ("Live broadcast", "&search_type=video&event_type=live"), ("Upcoming", "&search_type=video&event_type=upcoming"),
            ("Completed", "&search_type=video&event_type=completed"))]
        more = query + "&search_type=channel&page_token=CAoQAA"
        listing = D.parse_reply(answer(*tiles, vid(1, "A cat"), folder(R + "channel/UC1/", "Cat Channel"),
                                       folder(R + "playlist/PL1/", "Cat Mix"), folder(more, "Next Page")))
        self.assertEqual([(e.kind, e.title) for e in listing.entries],
                         [(D.VIDEO, "A cat"), (D.FOLDER, "Cat Channel"), (D.FOLDER, "Cat Mix")])
        self.assertEqual((listing.more, listing.skipped, listing.error), (more, 6, ""))
        only = D.parse_reply(answer(*tiles))                                                  # nothing but the tiles: empty
        self.assertEqual((only.entries, only.skipped), ((), 6))
        self.assertEqual(D.mode_for(only, True), D.EMPTY)
        for path in (query + "&search_type=channel", query + "&event_type=live", R + "kodion/search/query?q=x&search_type=playlist"):
            self.assertEqual(D.parse_reply(answer(folder(path, "T"))).entries, (), path)
        for path in (query, R + "kodion/search/history/", R + "channel/UC1/?search_type=video", R + "playlist/PL1/?event_type=live"):
            self.assertEqual([e.kind for e in D.parse_reply(answer(folder(path, "T"))).entries], [D.FOLDER], path)
        file_tile = {**folder(query + "&search_type=channel", "T"), "filetype": "file"}       # not a directory: no card anyway
        self.assertEqual(D.parse_reply(answer(file_tile)).entries, ())

    def test_an_empty_search_says_what_was_searched(self):
        for kind, title in ((D.KIND_VIDEO, "No videos found"), (D.KIND_CHANNEL, "No channels found"),
                            (D.KIND_PLAYLIST, "No playlists found"), (D.KIND_LIVE, "No live broadcasts found")):
            message = D.message(D.EMPTY, D.section_view(D.SEARCH, query="x", kind=kind), True)
            self.assertEqual((message.title, message.action, message.text), (title, "New search", D.EMPTY_TEXT[D.SEARCH]), kind)
        legacy = D.message(D.EMPTY, D.View(D.SEARCH, "Search", "", False), True)              # a search view with no type: as before
        self.assertEqual(legacy.title, "No results")
        self.assertEqual(D.message(D.EMPTY, D.section_view("history"), True).title, "Nothing here")
        self.assertEqual(D.message(D.ERROR, D.section_view(D.SEARCH, query="x", kind=D.KIND_LIVE)).title, "YouTube did not answer")

    def test_which_card_and_what_it_says(self):
        found, empty, failed = D.parse_reply(answer(vid(1))), D.NO_LISTING, D.Listing((), "", "boom")
        self.assertEqual([D.mode_for(found, k) for k in (True, False, None)], [D.DATA] * 3)       # cards win
        self.assertEqual((D.mode_for(empty, False), D.mode_for(empty, True), D.mode_for(empty, None)),
                         (D.NEEDKEY, D.EMPTY, D.EMPTY))
        self.assertEqual(D.mode_for(failed, False), D.ERROR)
        for signed, needs, keys, want in ((False, True, True, D.SIGNIN), (False, True, None, D.SIGNIN),
                                          (False, True, False, D.NEEDKEY),             # signing in needs the key first
                                          (False, False, True, None), (True, True, False, None), (None, True, False, None)):
            self.assertEqual(D.gate(signed, needs, keys), want, (signed, needs, keys))
        needkey = D.message(D.NEEDKEY)
        self.assertIn("Google key", needkey.title)
        self.assertIn("Accounts > YouTube > Keys", needkey.text)
        self.assertIn("phone", D.message(D.SIGNIN).text)
        self.assertEqual(D.message(D.SIGNIN).action, "Sign in to YouTube")
        self.assertIn("boom", D.message(D.ERROR, detail="boom").text)
        self.assertEqual(D.message(D.LOADING).action, "")
        self.assertEqual(D.message(D.PROMPT).action, "Search")
        self.assertNotIn("Keys", D.message(D.EMPTY, D.section_view("history"), True).text)
        self.assertIn("Keys", D.message(D.EMPTY, D.section_view("history"), None).text)      # cannot tell: the hint is there
        self.assertEqual(D.message(D.EMPTY, D.section_view(D.SEARCH, query="x"), True).action, "New search")
        for mode in (D.SIGNIN, D.NEEDKEY, D.EMPTY, D.LOADING, D.ERROR, D.PROMPT):
            message = D.message(mode, D.section_view("rec"))
            self.assertTrue(message.title)

    def test_the_personal_key_is_in_the_add_ons_key_file_or_not(self):
        full = {"keys": {"personal": {"api_key": "a", "client_id": "b", "client_secret": "c"}, "developer": {}}}
        self.assertTrue(D.keys_present(full))
        for raw in (None, [], {}, {"keys": {}}, {"keys": {"personal": {"api_key": "a", "client_id": "", "client_secret": "c"}}},
                    {"keys": {"personal": {"api_key": "a", "client_id": "b"}}}, {"keys": {"personal": 3}},
                    {"keys": {"developer": {"api_key": "a", "client_id": "b", "client_secret": "c"}}}):
            self.assertFalse(D.keys_present(raw), raw)

    def test_the_key_wizard_step_is_there_only_while_a_wizard_runs(self):
        now = 1_800_000_000
        fresh = {"step": 3, "total": 6, "title": "Создайте проект", "hint": "Откройте страницу ❄️ на телефоне", "updated": now - 60}
        self.assertEqual(D.parse_step(fresh, now), D.Step(3, 6, "Создайте проект", "Откройте страницу на телефоне"))
        for raw in (None, [], "x", 5, {}, {**fresh, "step": 0}, {**fresh, "step": 7}, {**fresh, "step": -1},
                    {**fresh, "step": True}, {**fresh, "step": "3"}, {**fresh, "step": 2.5}, {**fresh, "step": None},
                    {**fresh, "updated": now - D.STEP_MAX_AGE - 1}, {**fresh, "updated": now + D.STEP_MAX_AGE + 1},
                    {**fresh, "updated": None}, {**fresh, "updated": "now"}, {**fresh, "updated": True},
                    {**fresh, "updated": float("nan")}, {**fresh, "updated": float("inf")},
                    {k: v for k, v in fresh.items() if k != "updated"}, {**fresh, "step": 5, "total": 4}):
            self.assertIsNone(D.parse_step(raw, now), raw)
        self.assertEqual(D.parse_step({**fresh, "updated": now - D.STEP_MAX_AGE}, now).number, 3)      # just in time
        self.assertEqual(D.parse_step({**fresh, "updated": float(now)}, now).number, 3)
        self.assertEqual(D.parse_step({"step": 2, "updated": now}, now), D.Step(2, D.STEP_TOTAL, "", ""))    # no words
        self.assertEqual(D.parse_step({"step": 2, "title": None, "hint": {}, "updated": now}, now), D.Step(2, 6, "", ""))
        self.assertEqual(D.parse_step({"step": 2, "total": 4, "updated": now}, now).total, 4)
        for total in ("x", 0, 100, True, None, -2):
            self.assertEqual(D.parse_step({"step": 2, "total": total, "updated": now}, now).total, 6, total)
        self.assertEqual(D.parse_step({**fresh, "title": "[B]Шаг[/B]  один", "hint": "x" * 500}, now).hint, "x" * 160)
        self.assertEqual(D.parse_step({**fresh, "title": "Ключ 🔑 API"}, now).title, "Ключ API")

    def test_the_card_texts_and_the_play_path(self):
        video = D.parse_entry(vid(1, channel="Chan", seconds=3725))
        props = C.card_props(video)
        self.assertEqual((props["title1"], props["title2"], props["meta"], props["badge"], props["kind"]),
                         ("Video 1", "", "Chan", "1:02:05", "video"))
        self.assertEqual(D.play_path(video), R + "play/?video_id=v1")
        playlist = D.parse_entry(folder(R + "playlist/P/", "L"))
        channel = D.parse_entry(folder(R + "channel/UC1/", "C"))
        self.assertEqual((C.card_props(playlist)["meta"], C.card_props(channel)["meta"]), ("Playlist", "Channel"))
        self.assertEqual(D.play_path(playlist), "")
        self.assertEqual(D.play_path(D.Entry(D.VIDEO, "file:///etc/passwd", "t", "", 0, "", "")), "")
        self.assertTrue(D.fresh(100, 150) and not D.fresh(100, 100 + D.CACHE_TTL) and not D.fresh(None, 1) and not D.fresh(100, 50))


class RealAddon(unittest.TestCase):
    """What plugin.video.youtube 7.4.4 really sends (see REAL_TILES, real_video)."""

    def test_markup_in_labels_and_titles_is_cleaned(self):
        self.assertEqual(D.clean_text("[B]Sign In[/B]"), "Sign In")
        self.assertEqual(D.clean_text("[B]My Subscriptions[/B]"), "My Subscriptions")
        self.assertEqual(D.clean_text("[COLOR FFAABBCC]Hot[/COLOR]:[B] now[/B]"), "Hot: now")       # a tag leaves nothing behind
        self.assertEqual(D.clean_text("[COLOR=red]red[/COLOR] and [color red]more[/color]"), "red and more")
        self.assertEqual(D.clean_text("one[CR]two"), "one two")
        tile = D.parse_entry({"file": R + "special/my_subscriptions?category_label=My+Subscriptions",
                              "filetype": "directory", "label": "[B]My Subscriptions[/B]"})
        self.assertEqual(tile.title, "My Subscriptions")
        video = D.parse_entry(real_video(1, "[B]Martin Garrix[/B] - [COLOR red]Play[/COLOR]"))
        self.assertEqual(video.title, "Martin Garrix - Play")

    def test_the_sections_are_taken_off_the_main_page_as_listed(self):
        main = D.parse_reply(real_main_page())
        self.assertEqual(main.skipped, 4)                                       # Sign In, Switch User, Sign Out, Setup Wizard
        found = D.discover_routes(main)
        self.assertEqual(found, {"rec": REAL_RECOMMENDATIONS, "subs": REAL_SUBSCRIPTIONS, "later": LATER,
                                 "history": R + "special/playlist/HL/?category_label=History",
                                 "lists": R + "channel/mine/playlists?category_label=Playlists",
                                 "trend": R + "special/popular_right_now?category_label=Trending"})
        self.assertNotIn(D.SEARCH, found)
        self.assertNotEqual(found["subs"], R + "subscriptions/list/?category_label=Subscribed+Channels")   # the feed, not the channel list
        for route in found.values():
            self.assertIn("?category_label=", route)                            # the query stays
        self.assertFalse(found["subs"].endswith("/") or "my_subscriptions/" in found["subs"])   # no slash added

    def test_watch_later_and_history_are_the_playlists_wl_and_hl(self):
        for key, path in (("later", "special/playlist/WL/"), ("history", "special/playlist/HL/")):
            for shape in (path, path.rstrip("/"), path + "?category_label=x"):
                page = D.parse_reply(answer(folder(R + "kodion/search/history/", "Old searches"), folder(R + shape, "Tile")))
                self.assertEqual(D.discover_routes(page).get(key), R + shape, shape)
        other = D.parse_reply(answer(folder(R + "special/playlist/PL123/", "Some playlist")))
        self.assertEqual(D.discover_routes(other), {})
        later = next(s for s in D.SECTIONS if s.key == "later")
        history = next(s for s in D.SECTIONS if s.key == "history")
        self.assertEqual((later.route, history.route), (R + "special/playlist/WL/", R + "special/playlist/HL/"))

    def test_the_fallback_routes_are_the_real_ones(self):
        routes = {s.key: s.route for s in D.SECTIONS}
        self.assertEqual((routes["subs"], routes["lists"], routes["trend"]),
                         (R + "special/my_subscriptions", R + "channel/mine/playlists", R + "special/popular_right_now"))
        self.assertEqual(routes["rec"], R + "special/recommendations/")        # the call that was seen to work
        self.assertFalse(any("watch_history" in r or "watch_later" in r for r in routes.values()))

    def test_trending_is_a_section_that_needs_no_sign_in(self):
        trend = next(s for s in D.SECTIONS if s.key == "trend")
        self.assertFalse(trend.needs_login)
        self.assertEqual([r.name for r in D.rail()],
                         ["Recommendations", "Subscriptions", "Watch later", "History", "Playlists", "Trending", "Search"])
        self.assertIsNone(D.gate(False, trend.needs_login, True))
        self.assertEqual(D.section_view("trend").route, R + "special/popular_right_now")
        self.assertIn("trend", D.SECTION_KEYS)
        self.assertEqual(S.normalize_state({"section": "trend"})["section"], "trend")

    def test_a_channel_called_untitled_is_no_channel(self):
        for artist in (["Untitled"], ["untitled"], [" UNTITLED "], [], [""], "Untitled", None):
            card = D.parse_entry(real_video(1, artist=artist))
            self.assertEqual(card.channel, "", artist)
            self.assertEqual(C.card_props(card)["meta"], "", artist)               # the line is empty: the card is shorter
        self.assertEqual(D.parse_entry(real_video(1, artist=["Untitled", "Real Channel"])).channel, "Real Channel")
        self.assertEqual(D.parse_entry(real_video(1, artist=["Untitled"], studio=["Studio"])).channel, "Studio")
        self.assertEqual(D.parse_entry(real_video(1, artist=["The Untitled Band"])).channel, "The Untitled Band")
        playlist = D.parse_entry(folder(R + "playlist/P/", "L", artist=["Untitled"]))
        self.assertEqual((playlist.channel, C.card_props(playlist)["meta"]), ("", "Playlist"))

    def test_no_duration_shows_no_length(self):
        for extra in ({}, {"duration": 0}, {"duration": None}, {"runtime": 0, "duration": ""}):
            card = D.parse_entry(real_video(1, **extra))
            self.assertEqual((card.seconds, C.card_props(card)["badge"], C.card_props(card)["strip"]), (0, "", ""), extra)
        self.assertEqual(C.card_props(D.parse_entry(real_video(1, runtime=75)))["badge"], "1:15")
        self.assertEqual(C.card_props(D.parse_entry(real_video(1, duration=75, runtime=0)))["badge"], "1:15")

    def test_a_wrapped_thumbnail_is_kept_as_it_is_and_wins_over_the_add_ons_fanart(self):
        card = D.parse_entry(real_video(7))
        self.assertEqual(card.thumb, "image://https%3a%2f%2fi.ytimg.com%2fvi%2fID7%2fhqdefault.jpg/")
        only_fanart = D.parse_entry(real_video(7, thumbnail=""))
        self.assertEqual(only_fanart.thumb, "special://home/addons/plugin.video.youtube/resources/media/fanart.jpg")
        self.assertEqual(D.parse_entry(real_video(7, art={"thumb": "https://x/y.jpg", "fanart": "https://x/f.jpg"})).thumb,
                         "https://x/y.jpg")
        for none in ("", None, "DefaultVideo.png", "image://DefaultVideo.png/", "image://Default%56ideo.png/", 5):
            self.assertEqual(D.parse_entry(real_video(7, thumbnail=none, art={})).thumb, "", none)
        self.assertNotEqual(D.picture("image://https%3a%2f%2fx%2fDefaultVideo.png/"), "")             # a web address is no icon name

    def test_invalid_params_is_a_refusal_and_not_a_network_problem(self):
        refused = D.parse_reply(INVALID)
        self.assertEqual((refused.entries, refused.error, refused.refused), ((), "Invalid params.", True))
        self.assertTrue(D.parse_reply({"error": {"code": -32602}}).refused)
        self.assertTrue(D.parse_reply({"error": {"message": "invalid params: directory"}}).refused)
        failed = D.parse_reply({"error": {"code": -32100, "message": "Plugin crashed"}})
        self.assertEqual((failed.refused, D.mode_for(failed, True)), (False, D.ERROR))
        self.assertEqual([D.mode_for(refused, k) for k in (True, False, None)], [D.UNAVAILABLE] * 3)
        for keys in (True, False, None):
            text = D.message(D.UNAVAILABLE, D.section_view("subs"), keys).text
            self.assertNotIn("network", text)
            self.assertTrue(text.startswith("This section is not available right now."), text)
            self.assertEqual("Google key" in text, keys is not True, keys)
            self.assertEqual("Phone: Accounts > YouTube > Keys" in text, keys is not True, keys)
        self.assertIn("Check the network", D.message(D.ERROR, detail="Plugin crashed").text)
        self.assertEqual(D.message(D.UNAVAILABLE).action, "Try again")

    def test_a_section_that_needs_the_key_says_so_with_the_phone_path(self):
        message = D.message(D.NEEDKEY, D.section_view("subs"), False)
        self.assertEqual((message.title, message.text, message.action),
                         ("Set up your Google key", "Open the Media Stick page on your phone: Accounts > YouTube > Keys",
                          "Try again"))

    def test_the_key_is_in_the_settings_the_add_on_keeps_it_in(self):
        def xml(key="k", ident="i", secret="s", extra=""):
            return ('<settings version="2">' + extra + f'<setting id="youtube.api.key">{key}</setting>'
                    f'<setting id="youtube.api.id">{ident}</setting><setting id="youtube.api.secret">{secret}</setting>'
                    '<setting id="youtube.api.enable" default="true">false</setting></settings>')
        self.assertTrue(D.settings_keys_present(xml()))
        self.assertTrue(D.settings_keys_present('<?xml version="1.0" encoding="utf-8" standalone="yes"?>' + xml()))
        for text in (xml(key=""), xml(ident=" "), xml(secret=""), "<settings/>", "<settings version='2'></settings>",
                     '<settings><setting id="youtube.api.key">k</setting></settings>',
                     '<settings><setting id="youtube.api.key" default="true"/><setting id="youtube.api.id"/>'
                     '<setting id="youtube.api.secret"/></settings>'):
            self.assertIs(D.settings_keys_present(text), False, text)
        for text in ("", "{half", "<settings>", None, 5):
            self.assertIsNone(D.settings_keys_present(text), text)
        self.assertIs(D.keys_state(True, False), True)
        self.assertIs(D.keys_state(False, True), True)
        self.assertIs(D.keys_state(True, None), True)                         # one place with a key is enough
        self.assertIs(D.keys_state(False, False), False)
        self.assertIsNone(D.keys_state(False, None))
        self.assertIsNone(D.keys_state(None, None))


class CardTexts(unittest.TestCase):
    """What a card says: youtube_cards, the lines and the strip on the picture."""
    NOW = 1_800_000_000

    def video(self, **extra):
        return D.parse_entry(vid(1, "Title", **extra))

    def test_views_and_how_long_ago(self):
        for count, text in ((0, ""), (None, ""), (1, "1 view"), (999, "999 views"), (1000, "1K views"), (1234, "1.2K views"),
                            (340000, "340K views"), (1000000, "1M views"), (1240000, "1.2M views"), (12000000, "12M views"),
                            (2500000000, "2.5B views")):
            self.assertEqual(C.format_views(count), text, count)
        for seconds, text in ((30, "just now"), (120, "2 minutes ago"), (3600, "1 hour ago"), (3 * 86400, "3 days ago"),
                              (7 * 86400, "1 week ago"), (20 * 86400, "2 weeks ago"), (45 * 86400, "1 month ago"),
                              (400 * 86400, "1 year ago"), (800 * 86400, "2 years ago")):
            self.assertEqual(C.age_text(self.NOW - seconds, self.NOW), text, seconds)
        for published, now in ((0, self.NOW), (self.NOW + 5, self.NOW), (self.NOW, 0), (self.NOW, None)):
            self.assertEqual(C.age_text(published, now), "")

    def test_the_grey_lines_have_what_is_known_filled_from_the_top_and_nothing_else(self):
        rich = self.video(views=1240000, dateadded="2026-11-20 10:00:00", channel="Northern Workshop")
        now = D.as_epoch("2026-11-23 10:00:00")
        self.assertEqual(C.meta_lines(rich, now), ("Northern Workshop", "1.2M views · 3 days ago"))
        self.assertEqual(C.meta_lines(rich), ("Northern Workshop", "1.2M views"))             # no clock: no age
        self.assertEqual(C.meta_lines(self.video(channel="Only")), ("Only", ""))
        self.assertEqual(C.meta_lines(self.video(channel="", views=5000)), ("5K views", ""))   # no gap above the second line
        self.assertEqual(C.meta_lines(D.parse_entry(real_video(1))), ("", ""))               # what the add-on sends today
        self.assertEqual(C.meta_lines(D.parse_entry(folder(R + "playlist/P/", "L"))), ("Playlist", ""))
        self.assertEqual(C.meta_lines(D.parse_entry(folder(R + "channel/C/", "L"))), ("Channel", ""))
        self.assertEqual(C.meta_lines(D.parse_entry(folder(R + "special/other/", "L"))), ("", ""))
        self.assertEqual(C.meta_lines(D.parse_entry(folder(R + "playlist/P/", "L", artist=["Anna"]))), ("Anna", ""))
        props = C.card_props(D.parse_entry(real_video(1)))
        for key in ("meta", "meta2"):
            for word in ("Untitled", "None", "[]"):
                self.assertNotIn(word, props[key])
        huge = self.video(channel="X" * 55, views=1240000, dateadded="2026-11-20 10:00:00")
        self.assertTrue(C.meta_lines(huge, now)[0].endswith("…"))
        for entry in (rich, huge, self.video(channel="Ы" * 70, views=2_100_000_000, dateadded="2020-01-01")):
            for line in C.meta_lines(entry, now):
                self.assertLessEqual(C.fit.text_px(line, C.META_SIZE), C.META_WIDTH)
        self.assertEqual(C.one_line(["1.2M views", "3 days ago"]), "1.2M views · 3 days ago")
        self.assertEqual(C.one_line(["12.3M views and a lot of other words", "yesterday afternoon at the market"])
                         .count("·"), 0)                                                       # too long: the age goes

    def test_a_title_is_two_lines_with_an_ellipsis_and_each_line_fits(self):
        self.assertEqual(C.title_lines("Short"), ("Short", ""))
        long_ = "Why the night sky is dark, and why that was once a serious problem for astronomers"
        first, second = C.title_lines(long_)
        self.assertTrue(first and second.endswith("…"))
        self.assertTrue(long_.startswith(first))
        for title in (long_, "Ранкова прогулянка вздовж озера та ще дуже багато інших цікавих слів у назві відео", "W" * 80,
                      "A" * 12 + " " + "B" * 60):
            for line in C.title_lines(title):
                self.assertLessEqual(C.fit.text_px(line, C.TITLE_SIZE), C.TITLE_WIDTH, title)
        self.assertEqual(C.title_lines("")[0], "")

    def test_the_pill_shows_only_what_is_known(self):
        self.assertEqual(C.badge_of(self.video(seconds=754)), ("12:34", C.DARK))
        self.assertEqual(C.badge_of(self.video(seconds=3725)), ("1:02:05", C.DARK))
        for none in (0, None):
            self.assertEqual(C.badge_of(self.video(seconds=none)), ("", C.NONE))
            props = C.card_props(self.video(seconds=none))
            self.assertEqual((props["badge"], props["strip"]), ("", ""))                    # no length: no pill, no strip
        live = self.video(seconds=754, live=True)
        self.assertEqual(C.badge_of(live), (C.LIVE, C.RED))
        self.assertEqual(C.badge_of(self.video(seconds=0, live=True)), (C.LIVE, C.RED))
        playlist = D.parse_entry(folder(R + "playlist/P/", "L", videos=24))
        self.assertEqual(C.badge_of(playlist), ("24 videos", C.DARK))
        self.assertEqual(C.badge_of(D.parse_entry(folder(R + "playlist/P/", "L", videos=1)))[0], "1 video")
        self.assertEqual(C.badge_of(D.parse_entry(folder(R + "playlist/P/", "L"))), ("", C.NONE))
        self.assertEqual(C.badge_of(D.parse_entry(folder(R + "channel/C/", "L", videos=0))), ("", C.NONE))
        self.assertEqual(C.card_props(playlist)["badge"], "24 videos")
        widths = [C.badge_width(t) for t in ("3:21", "12:34", "1:02:03", "24 videos", "4999 videos")]
        self.assertEqual(widths, sorted(widths))
        self.assertTrue(all(w in C.BADGE_WIDTHS for w in widths))
        for text in ("3:21", "12:34", "1:02:03", "LIVE", "24 videos", "4999 videos"):
            self.assertLessEqual(C.fit.text_px(text, C.BADGE_SIZE) + C.BADGE_PAD, C.badge_width(text), text)

    def test_the_red_bar_is_drawn_only_for_a_video_that_was_watched(self):
        self.assertEqual([C.bar_step(p) for p in (0, -1, None, "x", 0.01, 0.3, 0.4, 0.6, 0.7, 0.89, 0.9, 1, 7)],
                         [0, 0, 0, 0, 25, 25, 50, 50, 75, 75, 100, 100, 100])
        self.assertEqual(C.card_props(self.video(seconds=0))["strip"], "")
        self.assertEqual(C.card_props(self.video(seconds=0, playcount=1))["strip"], "n000-100")       # the bar alone
        both = C.card_props(self.video(seconds=754, resume={"position": 300, "total": 600}))["strip"]
        self.assertEqual(both, f"d{C.badge_width('12:34'):03d}-050")
        self.assertEqual(C.card_props(self.video(seconds=0, live=True, playcount=1))["strip"], f"l{C.badge_width('LIVE'):03d}-000")

    def test_every_strip_picture_the_cards_can_ask_for_is_in_the_skin(self):
        names = [f"youtube-strip-{C.strip_key(*v)}.png" for v in C.strip_variants()]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertTrue(os.path.isfile(os.path.join(MEDIA, name)), name)
        entries = [self.video(seconds=s, **extra) for s in (0, 5, 754, 3725, 40000) for extra in
                   ({}, {"live": True}, {"playcount": 1}, {"resume": {"position": 10, "total": 100}},
                    {"resume": {"position": 70, "total": 100}})]
        entries += [D.parse_entry(folder(R + "playlist/P/", "L", videos=n)) for n in (1, 24, 150, 9999, 10 ** 9)]
        for entry in entries:
            strip = C.card_props(entry)["strip"]
            self.assertTrue(strip == "" or f"youtube-strip-{strip}.png" in names, (entry, strip))


    def test_the_wizard_block_has_the_step_and_the_words_cut_to_fit(self):
        self.assertEqual(C.step_lines(None), ("", "", ""))
        step = D.Step(3, 6, "Создайте проект", "Откройте страницу на телефоне")
        self.assertEqual(C.step_lines(step), ("Step 3 of 6: Создайте проект", "Откройте страницу на телефоне", ""))
        self.assertEqual(C.step_lines(D.Step(2, 6, "", "")), ("Step 2 of 6", "", ""))                 # no words: the step only
        self.assertEqual(C.step_lines(D.Step(2, 6, "", "Только подсказка")), ("Step 2 of 6", "Только подсказка", ""))
        self.assertEqual(C.step_lines(D.Step(4, 4, "Title", ""))[0], "Step 4 of 4: Title")
        head, first, second = C.step_lines(D.Step(6, 6, "Очень длинное название шага " * 5, "слово " * 60))
        for line, size in ((head, C.STEP_SIZE), (first, C.HINT_SIZE), (second, C.HINT_SIZE)):
            self.assertLessEqual(C.fit.text_px(line, size), C.STEP_WIDTH)
        self.assertTrue(head.startswith("Step 6 of 6: Очень") and head.endswith("…") and second.endswith("…"))
        self.assertEqual(D.message(D.NEEDKEY).title, "Set up your Google key")


class State(unittest.TestCase):
    def test_normalize_save_load(self):
        blank = {"section": "rec", "query": "", "kind": "video"}
        self.assertEqual(S.normalize_state(None), blank)
        self.assertEqual(S.normalize_state({"section": "x", "query": None}), blank)
        state = S.record_query(S.normalize_state({}), "  cats ")
        self.assertEqual(state, {"section": "search", "query": "cats", "kind": "video"})
        self.assertEqual(S.remember_section(state, "later"), {"section": "later", "query": "cats", "kind": "video"})
        path = os.path.join(TMP, "state", "youtube.json")
        self.assertTrue(S.save_state(path, state))
        self.assertEqual(S.load_state(path), state)
        put(path, "{not json")
        self.assertEqual(S.load_state(path), blank)
        self.assertEqual(S.load_state(os.path.join(TMP, "none.json")), blank)
        self.assertEqual(os.listdir(os.path.dirname(path)), ["youtube.json"])

    def test_the_type_of_a_search_is_kept_with_the_search_but_not_in_the_file(self):
        state = S.normalize_state({})
        self.assertEqual(state["kind"], D.KIND_VIDEO)                                   # Videos unless chosen otherwise
        chosen = S.remember_kind(state, D.KIND_CHANNEL)
        self.assertEqual(chosen["kind"], D.KIND_CHANNEL)
        self.assertEqual(S.record_query(chosen, "owls")["kind"], D.KIND_CHANNEL)         # a new search keeps the type
        self.assertEqual(S.remember_section(chosen, "later")["kind"], D.KIND_CHANNEL)
        self.assertEqual(S.remember_kind(chosen, "nonsense")["kind"], D.KIND_VIDEO)
        self.assertEqual(S.normalize_state({"kind": ["video"]})["kind"], D.KIND_VIDEO)
        path = os.path.join(TMP, "state", "kind.json")
        self.assertTrue(S.save_state(path, S.record_query(chosen, "owls")))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"section": "search", "query": "owls"})        # only the query is saved
        put(path, json.dumps({"section": "search", "query": "owls", "kind": "live"}))       # a file with it anyway: ignored
        self.assertEqual(S.load_state(path), {"section": "search", "query": "owls", "kind": "video"})

    def test_a_save_that_cannot_happen_returns_false(self):
        blocked = os.path.join(TMP, "blocked")
        put(blocked, "a file where a folder should be")
        self.assertFalse(S.save_state(os.path.join(blocked, "youtube.json"), S.normalize_state({})))


class Demo(unittest.TestCase):
    NOW = calendar.timegm((2026, 11, 23, 12, 0, 0))

    def listing(self, route, scenario=""):
        return D.parse_reply(demo.reply(route, scenario, "/art", self.NOW))

    def test_the_demo_has_the_real_shape_and_parses_whole(self):
        main = self.listing(R)
        self.assertEqual(main.skipped, 1)                                     # the Sign In action
        routes = D.discover_routes(main)
        self.assertEqual(routes, demo.ROUTES)
        self.assertNotEqual(routes["later"], D.SECTIONS[2].route)             # the demo goes through discovery
        for key, route in routes.items():
            listing = self.listing(route)
            self.assertEqual((listing.error, listing.skipped), ("", 0), key)
            self.assertGreaterEqual(len(listing.entries), 5, key)
        rec = self.listing(routes["rec"])
        self.assertEqual((len(rec.entries), rec.more), (demo.PAGE, demo.NEXT_PAGE))
        page = self.listing(rec.more)
        self.assertEqual((len(page.entries), page.more), (10, ""))
        self.assertFalse({e.path for e in rec.entries} & {e.path for e in page.entries})
        self.assertGreaterEqual(len(demo.VIDEOS), 40)

    def test_playlists_open_and_have_videos(self):
        lists = self.listing(demo.ROUTES["lists"])
        self.assertEqual({e.kind for e in lists.entries}, {D.FOLDER})
        for entry in lists.entries:
            inside = self.listing(entry.path)
            self.assertTrue(inside.entries and all(e.kind == D.VIDEO for e in inside.entries), entry.path)

    def test_the_cards_cover_the_odd_cases_and_unicode(self):
        entries = self.listing(demo.ROUTES["rec"]).entries + self.listing(demo.NEXT_PAGE).entries
        self.assertTrue(any(not e.thumb for e in entries))                    # the fallback picture
        self.assertTrue(any(not e.channel for e in entries))                  # artist [] or ["Untitled"]
        raw = [f for f in demo.reply(demo.ROUTES["rec"], "", "/art")["result"]["files"] if f["file"].startswith(R + "play/")]
        self.assertTrue(any(f["artist"] == ["Untitled"] for f in raw) and any(f["artist"] == [] for f in raw))
        self.assertTrue(any(e.seconds == 0 for e in entries))                 # a live stream, and the bare ones
        self.assertTrue(any(e.seconds >= 3600 for e in entries))
        self.assertIn("Тихий Берег", {e.channel for e in entries})
        self.assertTrue(all(len(e.title) <= 120 for e in entries))
        self.assertIn("Pixel Kitchen", {e.channel for e in entries})           # the symbol in its name is cleaned
        self.assertIn("Winter in New York Snowfall", {e.title for e in entries})
        self.assertTrue(any(len(e.title) > 70 for e in entries))              # one that needs the ellipsis
        self.assertTrue(any(len(e.title) < 20 for e in entries))

    def test_the_demo_cards_show_every_part_of_a_card_and_some_show_none(self):
        everything = [e for key in demo.SECTION_VIDEOS for e in self.listing(demo.ROUTES[key]).entries]
        everything += self.listing(demo.NEXT_PAGE).entries + self.listing(demo.ROUTES["lists"]).entries
        props = {e.path: C.card_props(e, self.NOW) for e in everything}              # one card for each video, whatever the section
        shown = list(props.values())
        self.assertTrue(any(p["meta"] and p["meta2"].startswith("1.2M views") for p in shown))
        self.assertTrue(any(p["meta2"].startswith("340K views") for p in shown))
        self.assertTrue(any(p["meta2"].endswith("3 days ago") for p in shown))
        self.assertEqual([p["badge"] for p in shown].count("LIVE"), 1)               # one live stream
        self.assertTrue(any(p["badge"] == "24 videos" for p in shown))               # and one playlist of 24
        self.assertTrue(any(":" in p["badge"] for p in shown))
        self.assertTrue(any(p["strip"].endswith("-100") for p in shown))             # watched to the end
        self.assertTrue(any(p["strip"][-3:] in ("025", "050", "075") for p in shown))    # part of the way
        bare = [p for p in shown if not p["meta"] and not p["meta2"] and not p["badge"] and p["kind"] == "video"]
        self.assertTrue(bare, "videos as bare as what the add-on sends today")
        raw = demo.reply(demo.ROUTES["rec"], "", "/art", self.NOW)["result"]["files"]
        self.assertTrue(any("🍳" in f["studio"][0] for f in raw if f["studio"]))     # the raw data has the symbol, the card not
        self.assertFalse(any("🍳" in p["meta"] for p in shown))
        self.assertTrue(all("Untitled" not in p["meta"] for p in shown))
        self.assertEqual(demo.THUMBS, len(demo.CHANNELS))                           # one scene for each channel

    def test_search_finds_or_makes_up_results(self):
        route = lambda q: D.search_route(q)                                    # noqa: E731
        self.assertEqual([e.title for e in self.listing(route("bread")).entries], ["Bread without kneading"])
        both = self.listing(route("hall")).entries
        self.assertTrue(len(both) >= 2 and all("hall" in e.title.casefold() for e in both))
        invented = self.listing(route("something else"))
        self.assertEqual(len(invented.entries), len(demo.SEARCH_FILLERS))
        self.assertTrue(all(e.title.startswith("something else: ") for e in invented.entries))

    def test_the_demo_answers_each_type_of_search_and_starts_it_with_the_add_ons_switch_tiles(self):
        for kind in D.KIND_KEYS:
            raw = demo.reply(D.search_route("stage", kind), "", "/art", self.NOW)["result"]["files"]
            self.assertEqual([f["label"] for f in raw[:6]], [f"[B]{n}[/B]" for n in
                                                              ("Videos", "Channels", "Playlists", "Live broadcast", "Upcoming", "Completed")])
            self.assertEqual(self.listing(D.search_route("stage", kind)).skipped, 6, kind)     # all six are dropped
        channels = self.listing(D.search_route("stage", D.KIND_CHANNEL)).entries
        self.assertEqual([(e.kind, e.title) for e in channels], [(D.FOLDER, "Stage Notes")])
        inside = self.listing(channels[0].path)
        self.assertTrue(inside.entries and all(e.kind == D.VIDEO for e in inside.entries))
        self.assertEqual([e.title for e in self.listing(D.search_route("e", D.KIND_CHANNEL)).entries],
                         ["Northern Workshop", "Pixel Kitchen", "Stage Notes", "Garden Hour"])
        lists = self.listing(D.search_route("space", D.KIND_PLAYLIST)).entries
        self.assertEqual([(e.kind, e.title, e.count) for e in lists], [(D.FOLDER, "Space and stars", 5)])
        self.assertTrue(self.listing(lists[0].path).entries)
        live = self.listing(D.search_route("jazz", D.KIND_LIVE)).entries
        self.assertEqual([(e.kind, e.live) for e in live], [(D.VIDEO, True)])
        for kind in (D.KIND_CHANNEL, D.KIND_PLAYLIST, D.KIND_LIVE):                           # nothing matches: an empty list
            self.assertEqual(self.listing(D.search_route("zzz qqq", kind)).entries, (), kind)

    def test_scenarios(self):
        self.assertEqual(tuple(demo.situation(s) for s in ("", "signin", "needkey", "unavailable")),
                         ((True, True), (False, True), (True, False), (True, False)))
        self.assertEqual(self.listing(demo.ROUTES["rec"], "empty").entries, ())
        self.assertTrue(self.listing(demo.ROUTES["rec"], "error").error)
        refused = self.listing(demo.ROUTES["rec"], "unavailable")
        self.assertEqual((refused.entries, refused.refused), ((), True))
        self.assertEqual(self.listing(R, "unavailable").skipped, 1)                         # the main page still answers
        self.assertEqual(len(self.listing(R, "error").entries), len(demo.ROUTES) + 1)    # the main page still answers
        self.assertEqual(self.listing("plugin://plugin.video.youtube/nowhere/").entries, ())


# ---- the window ------------------------------------------------------------------------------

def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class Site:
    """The YouTube add-on's directories: route -> answer; asked from a worker thread, and a route can be held back."""

    def __init__(self):
        self.routes, self.calls, self.held = {}, [], {}

    def get(self, route):
        self.calls.append((route, threading.current_thread() is threading.main_thread()))
        gate = self.held.get(route)
        if gate:
            gate.wait(3)
        return self.routes.get(route, answer())

    def asked(self):
        return [route for route, _ in self.calls]


class WindowCase(unittest.TestCase):
    def setUp(self):
        for name in ("temp", "profile", "addon_data"):
            shutil.rmtree(os.path.join(TMP, name), ignore_errors=True)
        for fake in (Fake.builtins, Fake.notes, Fake.rpc, Fake.played, Fake.typed):
            fake.clear()
        Fake.playing, Fake.stopped, Fake.now = False, 0, None
        Fake.home.clear()
        Fake.signed, Fake.keys, Fake.name, Fake.profile = True, True, "Anna", "p1"
        Fake.step, Fake.phone = None, ("http://192.168.1.20/", "/tmp/qr.png")
        self.site = Site()
        self.site.routes[R] = main_page()
        for patch in (mock.patch.object(youtube_app, "clock", lambda: Fake.now or time.time()),
                      mock.patch.object(youtube_app, "PAGES", False),             # DiskCache turns the disk cache on
                      mock.patch.object(youtube_app, "KEYS_POLL", 0.02),
                      mock.patch.object(youtube_app, "PROFILE_POLL", 0.02),
                      mock.patch.object(files, "profile_id", side_effect=lambda log=True: Fake.profile),
                      mock.patch.object(files, "read_step", side_effect=lambda now: Fake.step),
                      mock.patch.object(files, "phone_page", side_effect=lambda: Fake.phone),
                      mock.patch.object(files, "get_directory", side_effect=self.site.get),
                      mock.patch.object(files, "signed_in", side_effect=lambda: Fake.signed),
                      mock.patch.object(files, "profile_name", side_effect=lambda: Fake.name),
                      mock.patch.object(files, "keys_configured", side_effect=lambda: Fake.keys)):
            patch.start()
            self.addCleanup(patch.stop)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.stop()

    def make(self, demo=False, scenario="", state=None):
        if state is not None:
            S.save_state(files.state_path(), state)
        window = youtube_app.YouTube()
        window.setup(demo=demo, scenario=scenario)
        self.windows.append(window)
        return window

    def open(self, wait=True, **kw):
        window = self.make(**kw)
        window.onInit()
        if wait:
            self.assertTrue(wait_for(lambda: window.loads >= 1), "the first load")
        return window

    def shown(self, window):
        return [item.label for item in window.controls[GRID].items]

    def press(self, window, action_id):
        window.onAction(Action(action_id))

    def rec(self, *entries, more=None):
        self.site.routes[D.SECTIONS[0].route] = answer(*entries, *([folder(more, "Next Page")] if more else []))

    def go(self, window, key):
        """OK on a section of the rail."""
        window.focus = RAIL
        window.controls[RAIL].selected = D.SECTION_KEYS.index(key)
        before = window.loads
        window.onClick(RAIL)
        if key != D.SEARCH:
            self.assertTrue(wait_for(lambda: window.loads > before or window.mode == D.DATA and window.view.key == key))


class Sections(WindowCase):
    def test_the_first_section_is_asked_in_a_worker_and_shown_as_cards(self):
        self.rec(vid(1, "One", "Alpha", 61), vid(2, "Two", "Beta", 3700), folder(R + "playlist/P/", "Mix"))
        window = self.open()
        self.assertEqual((window.mode, window.getProperty("mode")), (D.DATA, "data"))
        self.assertEqual(self.shown(window), ["One", "Two", "Mix"])
        card = window.controls[GRID].items[1]
        self.assertEqual((card.props["meta"], card.props["meta2"], card.props["badge"], card.props["kind"]),
                         ("Beta", "", "1:01:40", "video"))
        self.assertEqual((card.props["title1"], card.props["title2"]), ("Two", ""))
        self.assertEqual(card.art, {"thumb": "https://i.ytimg.com/vi/v2/hq.jpg"})
        self.assertEqual(window.controls[GRID].items[2].props["meta"], "Playlist")
        self.assertEqual((window.getProperty("title"), window.getProperty("avatar"), window.getProperty("signed")),
                         ("Recommendations", "A", "1"))
        self.assertEqual((window.getProperty("demo"), window.getProperty("action")), ("", ""))
        self.assertEqual(window.focus, GRID)
        self.assertEqual(self.site.asked(), [R, D.SECTIONS[0].route])
        self.assertTrue(all(not in_main for _, in_main in self.site.calls), "JSON-RPC off the UI thread")
        self.assertEqual([i.props["active"] for i in window.controls[RAIL].items], ["1", "", "", "", "", "", ""])
        self.assertEqual([i.label for i in window.controls[RAIL].items],
                         ["Recommendations", "Subscriptions", "Watch later", "History", "Playlists", "Trending", "Search"])
        self.assertEqual([i.props["icon"] for i in window.controls[RAIL].items], list(D.SECTION_KEYS))

    def test_the_avatar_is_the_first_letter_of_the_profile_on_a_colour_taken_from_its_name(self):
        for name, letter in (("Anna", "A"), ("борис", "Б"), ("42nd", "4"), ("", "?"), ("  ", "?")):
            Fake.name = name
            window = self.open()
            self.assertEqual(window.getProperty("avatar"), letter, name)
            self.assertIn(window.getProperty("avatar_color"), profiles.PALETTE, name)
            self.assertEqual(window.getProperty("avatar_color"),
                             profiles.PALETTE[zlib.crc32(name.encode("utf-8")) % len(profiles.PALETTE)], name)
        colours = set()
        for name in ("Anna", "Boris", "Clara", "Dmytro", "Eve", "Frank", "Grace", "Hanna"):
            Fake.name = name
            colours.add(self.open().getProperty("avatar_color"))
        self.assertGreater(len(colours), 1, "the colour depends on the name")
        Fake.name = "Anna"
        self.assertEqual(self.open().getProperty("avatar_color"), self.open().getProperty("avatar_color"))   # and is the same each time

    def test_no_circle_while_nothing_is_known_and_a_grey_question_mark_when_signed_out(self):
        self.site.held[R] = hold = threading.Event()
        window = self.make()
        window.onInit()
        self.assertEqual((window.getProperty("avatar"), window.getProperty("signed")), ("", ""))   # before the first answer
        hold.set()
        self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual(window.getProperty("avatar"), "A")
        Fake.signed = False
        signed_out = self.open()
        self.assertEqual((signed_out.getProperty("avatar"), signed_out.getProperty("signed"),
                          signed_out.getProperty("avatar_color")), ("?", "0", youtube_app.SIGNED_OUT_COLOR))

    def test_the_route_comes_from_the_main_page_and_is_read_once(self):
        self.site.routes[LATER] = answer(vid(7, "Later one"))
        self.rec(vid(1))
        window = self.open()
        self.go(window, "later")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Later one"]))
        self.assertIn(LATER, self.site.asked())
        self.assertNotIn(D.SECTIONS[2].route, self.site.asked())
        self.assertEqual(self.site.asked().count(R), 1)
        self.assertEqual(window.getProperty("title"), "Watch later")

    def test_when_the_main_page_names_nothing_the_fallback_route_is_asked(self):
        self.site.routes[R] = answer()
        self.site.routes[D.SECTIONS[1].route] = answer(vid(5, "Fed"))
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Fed"]))

    def test_the_rail_follows_after_a_rest_and_a_section_seen_before_is_not_asked_again(self):
        self.rec(vid(1, "R1"))
        self.site.routes[D.SECTIONS[1].route] = answer(vid(2, "S1"))
        window = self.open()
        window.focus = RAIL
        window.controls[RAIL].selected = 1
        with mock.patch.object(youtube_app, "RAIL_DELAY", 0.02):
            self.press(window, 4)                                               # down: the grid follows after the delay
            self.assertTrue(wait_for(lambda: self.shown(window) == ["S1"]))
        self.assertEqual(window.focus, RAIL)                                    # the rail keeps the focus while moving
        self.assertEqual([i.props["active"] for i in window.controls[RAIL].items][:2], ["", "1"])   # the first two of seven
        window.controls[RAIL].selected = 0
        window.onClick(RAIL)
        self.assertEqual(self.shown(window), ["R1"])                            # from the cache, at once
        self.assertEqual(window.focus, GRID)
        self.assertEqual(self.site.asked().count(D.SECTIONS[0].route), 1)

    def test_a_slow_answer_shows_loading_and_an_older_answer_never_replaces_a_newer_one(self):
        self.rec(vid(1, "Slow"))
        self.site.routes[D.SECTIONS[1].route] = answer(vid(2, "Quick"))
        self.site.held[D.SECTIONS[0].route] = hold = threading.Event()
        window = self.open(wait=False)
        self.assertTrue(wait_for(lambda: window.getProperty("mode") == "loading"))
        self.assertEqual((window.getProperty("msg_title"), window.getProperty("action")), ("Loading…", ""))
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Quick"]))
        hold.set()
        self.assertTrue(wait_for(lambda: window.loads >= 2))
        time.sleep(0.05)
        self.assertEqual(self.shown(window), ["Quick"])
        self.assertEqual(window.view.key, "subs")

    def test_the_section_left_on_is_the_one_opened_next_time(self):
        self.site.routes[D.SECTIONS[3].route] = answer(vid(4, "Seen"))
        window = self.open()
        self.go(window, "history")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Seen"]))
        window.stop()
        self.assertEqual(S.load_state(files.state_path())["section"], "history")
        again = self.open()
        self.assertEqual((again.view.key, self.shown(again)), ("history", ["Seen"]))
        self.assertEqual(again.controls[RAIL].selected, 3)


class Cards(WindowCase):
    """The states that are not a list of videos."""

    def test_signed_out_says_so_asks_nothing_and_the_button_runs_the_existing_sign_in(self):
        Fake.signed = False
        window = self.open()
        self.assertEqual((window.mode, window.getProperty("avatar"), window.getProperty("signed")), (D.SIGNIN, "?", "0"))
        self.assertEqual(window.getProperty("action"), "Sign in to YouTube")
        self.assertEqual(window.focus, ACTION)
        self.assertEqual((self.site.calls, window.controls[GRID].items), ([], []))
        Fake.signed = True
        self.rec(vid(1, "After"))
        with mock.patch.object(accounts, "signin_service", return_value="done") as signin:
            window.onClick(ACTION)
        signin.assert_called_once_with("youtube")
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual((self.shown(window), window.getProperty("avatar")), (["After"], "A"))

    def test_a_sign_in_that_did_not_finish_changes_nothing(self):
        Fake.signed = False
        window = self.open()
        with mock.patch.object(accounts, "signin_service", return_value="cancelled"):
            window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: window.loads >= 2))
        self.assertEqual(window.mode, D.SIGNIN)

    def test_no_key_says_the_key_is_needed_and_where_to_put_it(self):
        Fake.keys = False
        window = self.open()
        self.assertEqual(window.mode, D.NEEDKEY)
        self.assertEqual(window.getProperty("msg_title"), "Set up your Google key")
        self.assertIn("Accounts > YouTube > Keys", window.getProperty("msg_text"))
        self.assertEqual((window.getProperty("action"), window.focus), ("Try again", ACTION))
        Fake.keys, Fake.signed = True, False                                 # with the key, signed out is a different card
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))

    def test_no_key_and_signed_out_is_the_key_first_and_search_is_asked_anyway(self):
        Fake.keys = Fake.signed = False
        window = self.open()
        self.assertEqual((window.mode, self.site.calls), (D.NEEDKEY, []))
        Fake.typed.append("jazz")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: window.loads >= 2))
        self.assertEqual((window.mode, self.site.asked()), (D.NEEDKEY, [R + "kodion/search/query/?q=jazz"]))

    def test_an_empty_answer_is_a_missing_key_only_when_the_key_is_known_missing(self):
        for keys, mode in ((False, D.NEEDKEY), (True, D.EMPTY), (None, D.EMPTY)):
            Fake.keys = keys
            window = self.open()
            self.assertEqual(window.mode, mode, keys)
            if mode == D.EMPTY:
                self.assertIn("Nothing is recommended", window.getProperty("msg_text"))
                self.assertEqual("Keys" in window.getProperty("msg_text"), keys is None)

    def test_an_error_says_so_and_try_again_asks_again(self):
        self.site.routes[D.SECTIONS[0].route] = {"error": {"code": -32100, "message": "Plugin crashed"}}
        window = self.open()
        self.assertEqual((window.mode, window.getProperty("msg_title")), (D.ERROR, "YouTube did not answer"))
        self.assertIn("Plugin crashed", window.getProperty("msg_text"))
        self.assertEqual(window.focus, ACTION)
        self.rec(vid(1, "Back again"))
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(self.shown(window), ["Back again"])
        self.assertEqual(self.site.asked().count(R), 2)                       # the main page is read again too

    def test_a_worker_that_breaks_still_ends_in_a_card(self):
        with mock.patch.object(files, "get_directory", side_effect=RuntimeError("boom")):
            window = self.open()
        self.assertEqual(window.mode, D.ERROR)

    def test_right_from_the_rail_goes_to_the_button_when_there_is_no_grid(self):
        Fake.signed = False
        window = self.open()
        window.focus = RAIL
        self.press(window, 2)
        self.assertEqual(window.focus, ACTION)
        window.focus = RAIL
        self.press(window, 3)                                                  # up and down only start the rest timer
        self.assertEqual(window.focus, RAIL)

    def test_a_listing_with_only_the_next_page_is_an_empty_card_not_a_blank_grid(self):
        self.rec(more=R + "special/recommendations/?page=2")
        window = self.open()
        self.assertEqual((window.mode, window.controls[GRID].items), (D.EMPTY, []))


class KeyCard(WindowCase):
    """"Set up your Google key": the QR of the phone page and the step the wizard on the phone has got to."""
    STEP = D.Step(2, 6, "Создайте проект", "Откройте страницу на телефоне")

    def setUp(self):
        super().setUp()
        Fake.keys = False

    def props(self, window, *names):
        return tuple(window.getProperty(name) for name in names)

    def test_the_card_has_its_title_text_button_and_the_phone_pages_qr_and_no_step_without_a_wizard(self):
        window = self.open()
        self.assertEqual(window.mode, D.NEEDKEY)
        self.assertEqual(self.props(window, "msg_title", "msg_text", "action"),
                         ("Set up your Google key", "Open the Media Stick page on your phone: Accounts > YouTube > Keys",
                          "Try again"))
        self.assertTrue(wait_for(lambda: window.getProperty("key_qr") == "/tmp/qr.png"))
        self.assertEqual(window.getProperty("key_url"), "192.168.1.20")
        time.sleep(0.1)
        self.assertEqual(self.props(window, "step", "step_hint1", "step_hint2"), ("", "", ""))
        self.assertEqual(window.focus, ACTION)

    def test_the_step_follows_the_file_and_only_the_step_properties_change(self):
        Fake.step = self.STEP
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("step") == "Step 2 of 6: Создайте проект"))
        self.assertEqual(self.props(window, "step_hint1", "step_hint2"), ("Откройте страницу на телефоне", ""))
        self.assertTrue(wait_for(lambda: window.getProperty("key_qr") != ""))
        changed = []
        real = window.setProperty
        window.setProperty = lambda key, value: (changed.append(key), real(key, value))
        Fake.step = D.Step(3, 6, "Ключ API", "Скопируйте ключ и вставьте его на странице")
        self.assertTrue(wait_for(lambda: window.getProperty("step") == "Step 3 of 6: Ключ API"))
        Fake.step = D.Step(4, 6, "", "")                                       # a step with no words
        self.assertTrue(wait_for(lambda: window.getProperty("step") == "Step 4 of 6"))
        self.assertEqual(self.props(window, "step_hint1", "step_hint2"), ("", ""))
        Fake.step = None                                                       # the wizard is finished or was left
        self.assertTrue(wait_for(lambda: window.getProperty("step") == ""))
        self.assertLessEqual(set(changed), {"step", "step_hint1", "step_hint2"})
        self.assertEqual((window.mode, window.focus), (D.NEEDKEY, ACTION))   # the window was not rebuilt

    def test_the_file_is_looked_at_from_a_worker_every_two_seconds_and_only_while_the_card_is_shown(self):
        self.assertEqual(REAL_KEYS_POLL, 2.0)
        looks = []
        with mock.patch.object(files, "read_step", side_effect=lambda now: looks.append(threading.current_thread()) or Fake.step):
            window = self.open()
            self.assertTrue(wait_for(lambda: len(looks) >= 3))
            self.assertTrue(all(t is not threading.main_thread() for t in looks), "off the UI thread")
            self.site.routes[D.SECTIONS[0].route] = answer(vid(1, "Back"))
            Fake.keys = True
            window.onClick(ACTION)                                              # Try again: the list comes
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            time.sleep(0.1)                                                     # a look that was under way ends
            seen = len(looks)
            time.sleep(0.2)                                                     # ten polls' time
            self.assertEqual(len(looks), seen)
        self.assertEqual(self.props(window, "step", "step_hint1", "step_hint2"), ("", "", ""))

    def test_one_watcher_at_a_time_and_a_new_one_when_the_card_comes_back(self):
        window = self.open()
        threads = threading.active_count()
        for _ in range(5):
            window._start_keys_watch()
        self.assertLessEqual(threading.active_count(), threads)                   # none was started
        Fake.keys = True
        self.rec(vid(1, "Back"))
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertTrue(wait_for(lambda: not window._watching))
        Fake.keys, Fake.step = False, self.STEP
        self.go(window, "subs")                                                 # nothing there and no key: the card again
        self.assertTrue(wait_for(lambda: window.mode == D.NEEDKEY))
        self.assertTrue(wait_for(lambda: window.getProperty("step") == "Step 2 of 6: Создайте проект"))

    def test_a_qr_that_cannot_be_made_is_left_out_and_tried_again_and_offline_has_neither(self):
        Fake.phone = ("http://192.168.1.20/", "")
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("key_url") == "192.168.1.20"))
        self.assertEqual(window.getProperty("key_qr"), "")                      # the skin hides the QR, the card stays
        Fake.phone = ("http://192.168.1.20/", "/tmp/qr.png")
        self.assertTrue(wait_for(lambda: window.getProperty("key_qr") == "/tmp/qr.png"))
        Fake.phone = ("", "")
        offline = self.open()
        time.sleep(0.1)
        self.assertEqual((offline.mode, offline.getProperty("action")), (D.NEEDKEY, "Try again"))
        self.assertEqual(self.props(offline, "key_url", "key_qr"), ("", ""))      # no address, no QR: the text is still there

    def test_a_look_that_breaks_does_not_end_the_card_or_the_watching(self):
        with mock.patch.object(files, "read_step", side_effect=RuntimeError("boom")):
            window = self.open()
            time.sleep(0.1)
            self.assertEqual((window.mode, window.getProperty("step"), window._watching), (D.NEEDKEY, "", True))
        Fake.step = self.STEP                                                   # the next look works
        self.assertTrue(wait_for(lambda: window.getProperty("step") == "Step 2 of 6: Создайте проект"))

    def test_the_other_cards_have_no_wizard_block_and_ask_nothing(self):
        Fake.keys, Fake.signed = True, False
        window = self.open()
        self.assertEqual(window.mode, D.SIGNIN)
        time.sleep(0.1)
        self.assertEqual((window.getProperty("key_qr"), window.getProperty("step"), window._watching), ("", "", False))


class RealWindow(WindowCase):
    """The window on what the add-on really sends: signed in, no personal Google key ("partially")."""
    TREND = R + "special/popular_right_now?category_label=Trending"

    def setUp(self):
        super().setUp()
        self.site.routes[R] = real_main_page()
        Fake.keys = False

    def test_the_cards_have_clean_text_the_wrapped_thumbnail_or_the_plate_and_no_empty_fields(self):
        self.site.routes[REAL_RECOMMENDATIONS] = answer(
            real_video(1, "[B]One[/B]"), real_video(2, thumbnail="", art={}), {**real_video(3), "artist": []},
            real_video(4, artist=["Real Channel"], runtime=125), real_video(5, thumbnail="image://DefaultVideo.png/", art={}))
        window = self.open()
        self.assertEqual((window.mode, window.getProperty("avatar"), window.getProperty("signed")), (D.DATA, "A", "1"))
        items = window.controls[GRID].items
        self.assertEqual([i.label for i in items], ["One", "Real video 2", "Real video 3", "Real video 4", "Real video 5"])
        self.assertEqual([i.props["meta"] for i in items], ["", "", "", "Real Channel", ""])      # no "Untitled", no filler
        self.assertEqual([i.props["meta2"] for i in items], [""] * 5)
        self.assertEqual([i.props["badge"] for i in items], ["", "", "", "2:05", ""])             # no length: no pill
        self.assertEqual([i.props["strip"] for i in items], ["", "", "", f"d{C.badge_width('2:05'):03d}-000", ""])
        self.assertEqual([i.props["title1"] for i in items], [i.label for i in items])
        self.assertEqual(items[0].art, {"thumb": "image://https%3a%2f%2fi.ytimg.com%2fvi%2fID1%2fhqdefault.jpg/"})
        for plain in (items[1], items[4]):
            self.assertEqual(plain.art, {"thumb": youtube_app.NO_THUMB})
        self.assertTrue(os.path.isfile(youtube_app.NO_THUMB))
        self.assertEqual(self.site.asked(), [R, REAL_RECOMMENDATIONS])        # the route as the main page lists it

    def test_a_section_is_asked_exactly_as_listed_and_never_with_a_slash_added(self):
        self.site.routes[R + "special/my_subscriptions/"] = INVALID           # the slash form is what the add-on refuses
        self.site.routes[REAL_SUBSCRIPTIONS] = answer(vid(5, "Fresh"))
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Fresh"]))
        self.assertEqual(window.mode, D.DATA)
        self.assertEqual(set(self.site.asked()), {R, REAL_RECOMMENDATIONS, REAL_SUBSCRIPTIONS})

    def test_a_refused_section_says_it_is_not_available_and_where_the_key_goes(self):
        self.site.routes[REAL_SUBSCRIPTIONS] = INVALID
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: window.mode == D.UNAVAILABLE))
        text = window.getProperty("msg_text")
        self.assertEqual(window.getProperty("msg_title"), "Not available right now")
        self.assertTrue(text.startswith("This section is not available right now."), text)
        self.assertIn("It needs a personal Google key. Phone: Accounts > YouTube > Keys", text)
        self.assertNotIn("network", text)
        self.assertEqual((window.getProperty("action"), window.focus), ("Try again", ACTION))
        self.assertEqual((window.getProperty("avatar"), window.getProperty("signed")), ("A", "1"))   # the avatar stays
        Fake.keys = True                                                       # with a key it only says it is not available
        self.site.routes[REAL_SUBSCRIPTIONS] = answer(vid(8, "Now served"))
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Now served"]))

    def test_a_failure_is_still_the_network_card(self):
        self.site.routes[REAL_SUBSCRIPTIONS] = {"error": {"code": -32100, "message": "Plugin crashed"}}
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: window.mode == D.ERROR))
        self.assertIn("Check the network", window.getProperty("msg_text"))

    def test_an_empty_section_without_a_key_asks_for_the_key(self):
        window = self.open()
        self.go(window, "later")                                               # the add-on answers with nothing
        self.assertTrue(wait_for(lambda: window.mode == D.NEEDKEY))
        self.assertEqual(window.getProperty("msg_text"),
                         "Open the Media Stick page on your phone: Accounts > YouTube > Keys")
        self.assertEqual(self.site.asked()[-1], LATER)

    def test_trending_is_shown_without_signing_in(self):
        Fake.signed = False
        self.site.routes[self.TREND] = answer(real_video(9, "Hit"))
        window = self.open()
        self.assertEqual((window.mode, self.site.calls), (D.NEEDKEY, []))       # no key: signing in is not offered yet
        self.go(window, "trend")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Hit"]))
        self.assertEqual((window.mode, window.focus, window.getProperty("avatar")), (D.DATA, GRID, "?"))
        self.assertEqual(self.site.asked(), [R, self.TREND])


class Focus(WindowCase):
    """The focus is asked for only once Kodi shows the control (asking earlier logs "asked to focus, but it can't")."""

    def setUp(self):
        super().setUp()
        self.shows = {GRID: True, ACTION: True}
        self.looks = []
        self.asked_for = []

    def visible(self, condition):
        found = re.fullmatch(r"Control\.IsVisible\((\d+)\)", condition)
        if not found:
            return True
        control_id = int(found.group(1))
        self.looks.append(control_id)
        return self.shows.get(control_id, True) is True or len(self.looks) > self.shows[control_id]

    def watch(self, window):
        real = window.setFocusId

        def record(control_id):
            self.asked_for.append((control_id, len(self.looks)))
            real(control_id)
        window.setFocusId = record

    def test_a_worker_waits_for_the_grid_to_be_shown_and_asks_once(self):
        self.shows[GRID] = 3                                                   # shown from the fourth look on
        self.rec(vid(1))
        window = self.make()
        self.watch(window)
        with mock.patch.object(xbmc, "getCondVisibility", self.visible):
            window.onInit()
            self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual(window.focus, GRID)
        self.assertEqual(self.asked_for, [(GRID, 4)])

    def test_a_worker_waits_for_the_button_of_a_card_too(self):
        Fake.signed = False
        self.shows[ACTION] = 2
        window = self.make()
        self.watch(window)
        with mock.patch.object(xbmc, "getCondVisibility", self.visible):
            window.onInit()
            self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual((window.mode, window.focus), (D.SIGNIN, ACTION))
        self.assertEqual(self.asked_for, [(ACTION, 3)])

    def test_a_worker_gives_up_when_the_control_is_never_shown(self):
        self.shows[GRID] = 10 ** 9
        self.rec(vid(1))
        window = self.make()
        self.watch(window)
        with mock.patch.object(xbmc, "getCondVisibility", self.visible), mock.patch.object(youtube_app, "FOCUS_WAIT", 0.05):
            window.onInit()
            self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual((window.mode, window.focus, self.asked_for), (D.DATA, 0, []))

    def test_the_ui_thread_does_not_wait_it_asks_again_from_a_timer(self):
        self.rec(vid(1, "R1"))
        self.site.routes[D.SECTIONS[1].route] = answer(vid(2, "S1"))
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["S1"]))
        window.focus = RAIL
        window.controls[RAIL].selected = 0
        self.shows[GRID] = 10 ** 9                                             # Kodi has not shown the grid yet
        with mock.patch.object(xbmc, "getCondVisibility", self.visible):
            started = time.monotonic()
            window.onClick(RAIL)                                               # R1 comes from the cache, at once
            self.assertLess(time.monotonic() - started, youtube_app.FOCUS_WAIT / 2, "the UI thread waited")
            self.assertEqual((self.shown(window), window.focus), (["R1"], RAIL))
            self.shows[GRID] = True                                            # now it is shown
            self.assertTrue(wait_for(lambda: window.focus == GRID))


class Playing(WindowCase):
    def test_ok_on_a_video_plays_it_through_player_open(self):
        self.rec(vid(1), vid(2))
        window = self.open()
        window.controls[GRID].selected = 1
        window.onClick(GRID)
        request = json.loads(Fake.rpc[-1])
        self.assertEqual((request["method"], request["params"]["item"]["file"]), ("Player.Open", R + "play/?video_id=v2"))
        self.assertEqual((Fake.notes, Fake.played), ([], []))

    def test_coming_back_from_the_player_stops_the_video(self):
        self.rec(vid(1))
        window = self.open()
        Fake.now = 1000.0
        window.onClick(GRID)
        Fake.now, Fake.playing = 1001.0, True
        window.onInit()                                                         # back at once: not a return
        self.assertEqual(Fake.stopped, 0)
        Fake.now = 1010.0
        window.onInit()
        self.assertEqual(Fake.stopped, 1)
        window.onInit()
        self.assertEqual(Fake.stopped, 1)


class Lists(WindowCase):
    def test_a_playlist_opens_and_back_returns_to_the_list_at_the_same_card(self):
        mix = R + "playlist/PL1/"
        self.site.routes[D.SECTIONS[4].route] = answer(folder(R + "playlist/PL0/", "First"), folder(mix, "Mix"))
        self.site.routes[mix] = answer(vid(1, "Inside"))
        window = self.open()
        self.go(window, "lists")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["First", "Mix"]))
        window.controls[GRID].selected = 1
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Inside"]))
        self.assertEqual(window.getProperty("title"), "Playlists › Mix")
        self.assertEqual(window.controls[RAIL].selected, 4)                     # the rail still shows where we are
        self.press(window, 92)
        self.assertEqual((self.shown(window), window.controls[GRID].selected), (["First", "Mix"], 1))
        self.assertEqual(window.getProperty("title"), "Playlists")
        self.assertFalse(window.closed)
        self.press(window, 92)
        self.assertTrue(window.closed)

    def test_back_leaves_the_app_from_the_top_and_from_a_card(self):
        for mode in ("data", "signin"):
            Fake.signed = mode == "data"
            self.rec(vid(1))
            window = self.open()
            self.press(window, 10)
            self.assertTrue(window.closed, mode)


class AutoLoad(WindowCase):
    """A long list loads its next page by itself, in a worker, when the cursor nears the last row: no card for it."""
    PAGE = D.SECTIONS[0].route + "?page=2"

    def numbered(self, first, last):
        return [vid(n) for n in range(first, last + 1)]

    def long_list(self, count=20):
        self.rec(*self.numbered(1, count), more=self.PAGE)
        self.site.routes[self.PAGE] = answer(*self.numbered(count + 1, count + 10))

    def move_to(self, window, position):
        window.controls[GRID].selected = position
        self.press(window, 4)                                              # down: the window looks at the cursor

    def asked_page(self):
        return self.site.asked().count(self.PAGE)

    def test_a_list_that_does_not_fill_the_screen_loads_its_next_page_at_once(self):
        self.rec(vid(1), vid(2), more=self.PAGE)
        self.site.routes[self.PAGE] = answer(vid(2), vid(3), vid(4))
        window = self.open()
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 4))
        self.assertEqual(self.shown(window), ["Video 1", "Video 2", "Video 3", "Video 4"])   # no "More videos" card
        self.assertEqual(window.controls[GRID].selected, 0)                                  # the cursor did not move
        self.assertTrue(wait_for(lambda: window.getProperty("notice") == ""))
        self.assertTrue(all(not in_main for _, in_main in self.site.calls), "JSON-RPC off the UI thread")
        self.assertEqual(self.asked_page(), 1)                                               # and there is no further page
        self.assertEqual(window.listing.more, "")

    def test_a_long_list_waits_until_the_cursor_is_within_two_rows_of_the_end(self):
        self.long_list()
        window = self.open()
        first = window.controls[GRID].items[0]
        self.assertEqual(youtube_app.AHEAD, 2 * youtube_app.COLUMNS)
        self.move_to(window, 20 - youtube_app.AHEAD - 1)
        time.sleep(0.05)
        self.assertEqual((self.asked_page(), len(window.controls[GRID].items)), (0, 20))
        self.move_to(window, 20 - youtube_app.AHEAD)                          # the third row from the end
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 30))
        self.assertEqual(window.controls[GRID].selected, 20 - youtube_app.AHEAD)             # the grid did not jump
        self.assertIs(window.controls[GRID].items[0], first)                   # appended, not rebuilt
        self.assertEqual(self.shown(window)[18:23], ["Video 19", "Video 20", "Video 21", "Video 22", "Video 23"])
        self.assertTrue(wait_for(lambda: window.getProperty("notice") == ""))
        self.assertTrue(all(not in_main for _, in_main in self.site.calls), "JSON-RPC off the UI thread")
        self.assertEqual(self.go_back_to_cache(window), [f"Video {n}" for n in range(1, 31)])   # the cache has the whole list

    def go_back_to_cache(self, window):
        self.go(window, "subs")
        self.go(window, "rec")
        return self.shown(window)

    def test_other_keys_and_other_controls_start_nothing(self):
        self.long_list()
        window = self.open()
        window.controls[GRID].selected = 19
        self.press(window, 7)                                                  # not a move
        window.focus = RAIL
        self.press(window, 4)                                                  # a move, but on the rail
        time.sleep(0.05)
        self.assertEqual(self.asked_page(), 0)

    def test_while_it_loads_a_thin_line_says_so_and_only_one_page_is_asked_for_at_a_time(self):
        self.long_list()
        self.site.held[self.PAGE] = hold = threading.Event()
        window = self.open()
        self.move_to(window, 19)
        self.assertTrue(wait_for(lambda: window.getProperty("notice") == youtube_app.LOADING_MORE))
        self.assertEqual(youtube_app.LOADING_MORE, "Loading…")
        for _ in range(3):
            self.press(window, 4)
        self.assertEqual(self.asked_page(), 1)
        hold.set()
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 30))
        self.assertTrue(wait_for(lambda: window.getProperty("notice") == ""))
        self.assertEqual(self.asked_page(), 1)

    def test_a_page_that_fails_is_silent_and_asked_for_again_after_a_pause(self):
        self.long_list()
        Fake.now = 1000.0
        self.site.routes[self.PAGE] = {"error": {"message": "no"}}
        window = self.open()
        self.move_to(window, 19)
        self.assertTrue(wait_for(lambda: window.more_retry > 0 and window.loading_more == 0))
        self.assertEqual(window.more_retry, 1000.0 + youtube_app.MORE_RETRY)
        self.assertEqual((self.shown(window)[-1], len(window.controls[GRID].items)), ("Video 20", 20))
        self.assertEqual((window.getProperty("notice"), Fake.notes, window.mode), ("", [], D.DATA))   # no message, no card
        Fake.now = 1005.0
        self.press(window, 4)
        time.sleep(0.05)
        self.assertEqual(self.asked_page(), 1)                                 # too soon
        Fake.now = 1009.0
        self.site.routes[self.PAGE] = answer(*self.numbered(21, 30))
        self.press(window, 4)
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 30))
        self.assertEqual(self.asked_page(), 2)

    def test_a_worker_that_breaks_is_silent_too(self):
        self.long_list()
        window = self.open()
        with mock.patch.object(files, "get_directory", side_effect=RuntimeError("boom")):
            self.move_to(window, 19)
            self.assertTrue(wait_for(lambda: window.more_retry > 0 and window.loading_more == 0))
        self.assertEqual((len(window.controls[GRID].items), window.getProperty("notice"), window.mode), (20, "", D.DATA))

    def test_a_page_that_adds_nothing_ends_the_list(self):
        self.rec(vid(1), vid(2), more=self.PAGE)
        self.site.routes[self.PAGE] = answer(vid(1), vid(2), folder(self.PAGE, "Next Page"))
        window = self.open()
        self.assertTrue(wait_for(lambda: self.asked_page() == 1 and window.loading_more == 0))
        time.sleep(0.05)
        self.assertEqual((self.shown(window), self.asked_page(), window.listing.more), (["Video 1", "Video 2"], 1, ""))

    def test_a_page_that_arrives_after_the_section_was_left_is_dropped(self):
        self.long_list()
        self.site.routes[D.SECTIONS[1].route] = answer(vid(90, "S1"))
        self.site.held[self.PAGE] = hold = threading.Event()
        window = self.open()
        self.move_to(window, 19)
        self.assertTrue(wait_for(lambda: self.asked_page() == 1))
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["S1"]))
        hold.set()
        self.assertTrue(wait_for(lambda: window.loading_more == 0))
        self.assertEqual(self.shown(window), ["S1"])
        self.assertEqual(window.getProperty("notice"), "")

    def test_a_playlist_inside_a_long_list_loads_by_itself_too(self):
        mix = R + "playlist/PL1/"
        self.site.routes[D.SECTIONS[4].route] = answer(folder(mix, "Mix"))
        self.site.routes[mix] = answer(*self.numbered(1, 12), folder(mix + "?page=2", "Next Page"))
        self.site.routes[mix + "?page=2"] = answer(*self.numbered(13, 14))
        window = self.open()
        self.go(window, "lists")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Mix"]))
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 12))
        self.move_to(window, 11)
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 14))


class Searching(WindowCase):
    def test_the_search_item_asks_for_words_and_shows_the_results_on_the_same_screen(self):
        self.rec(vid(1))
        results = R + "kodion/search/query/?q=cats+and+dogs"
        self.site.routes[results] = answer(vid(8, "Cats 1"), vid(9, "Dogs 1"))
        window = self.open()
        Fake.typed.append("  cats and dogs ")
        self.go(window, D.SEARCH)
        self.assertEqual(Fake.asked, ("Search YouTube", ""))
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cats 1", "Dogs 1"]))
        self.assertEqual((window.getProperty("title"), window.focus), ("Results for “cats and dogs”", GRID))
        self.assertEqual(window.controls[RAIL].selected, SEARCH_AT)
        self.assertEqual([i.props["active"] for i in window.controls[RAIL].items][-1], "1")
        self.assertEqual(S.load_state(files.state_path()), {"section": "search", "query": "cats and dogs", "kind": "video"})
        self.assertEqual(Fake.rpc, [])

    def test_typing_nothing_changes_nothing_and_the_last_words_are_offered_again(self):
        self.rec(vid(1, "Same"))
        window = self.open()
        Fake.typed.append("   ")
        self.go(window, D.SEARCH)
        self.assertEqual((self.shown(window), window.mode), (["Same"], D.DATA))
        Fake.typed.append("again")
        self.go(window, D.SEARCH)
        Fake.typed.append("")
        self.go(window, D.SEARCH)
        self.assertEqual(Fake.asked, ("Search YouTube", "again"))

    def test_resting_on_search_shows_the_last_results_or_the_search_card(self):
        self.rec(vid(1))
        window = self.open()
        window.focus = RAIL
        window.controls[RAIL].selected = SEARCH_AT
        with mock.patch.object(youtube_app, "RAIL_DELAY", 0.02):
            self.press(window, 4)
            self.assertTrue(wait_for(lambda: window.mode == D.PROMPT))
        self.assertEqual((window.getProperty("msg_title"), window.getProperty("action")), ("Search YouTube", "Search"))
        self.assertEqual(window.focus, RAIL)
        Fake.typed.append("tea")
        self.site.routes[R + "kodion/search/query/?q=tea"] = answer(vid(5, "Tea"))
        window.focus = ACTION
        window.onClick(ACTION)                                                  # the card's button asks too
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Tea"]))

    def test_no_results_offers_a_new_search(self):
        Fake.typed.append("zzz")
        window = self.open()
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: window.mode == D.EMPTY))
        self.assertEqual((window.getProperty("msg_title"), window.getProperty("action")), ("No videos found", "New search"))
        Fake.typed.append("zzz2")
        window.onClick(ACTION)
        self.assertEqual(Fake.asked[1], "zzz")
        self.assertTrue(wait_for(lambda: window.loads >= 3))

    def test_the_last_search_is_open_next_time(self):
        self.site.routes[R + "kodion/search/query/?q=owls"] = answer(vid(3, "Owls"))
        window = self.open(state={"section": "search", "query": "owls"})
        self.assertEqual((self.shown(window), window.getProperty("title")), (["Owls"], "Results for “owls”"))
        empty = self.open(wait=False, state={"section": "search", "query": ""})
        self.assertEqual(empty.mode, D.PROMPT)
        self.assertEqual(empty.focus, ACTION)


class SearchKinds(WindowCase):
    """What a search is for: the row 401-404 above the results (Videos, Channels, Playlists, Live)."""
    VIDEOS, CHANNELS, PLAYLISTS, LIVE = KIND_IDS

    def answer_for(self, query, kind, *entries):
        self.site.routes[D.search_route(query, kind)] = answer(*entries)

    def searched(self, text="cats", **state):
        """A window that has searched for `text` (typed on the rail's Search)."""
        self.answer_for(text, D.KIND_VIDEO, vid(1, "Cat video"))
        window = self.open(**state)
        Fake.typed.append(text)
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat video"]))
        return window

    def pick(self, window, button, then):
        window.focus = button
        window.onClick(button)
        self.assertTrue(wait_for(then), (button, self.shown(window), window.mode))

    def test_a_search_is_for_videos_until_another_type_is_picked_and_the_row_shows_only_with_the_search(self):
        window = self.open()
        self.assertEqual((window.getProperty("search"), window.getProperty("kind")), ("", ""))       # Recommendations: no row
        Fake.typed.append("cats")
        self.answer_for("cats", D.KIND_VIDEO, vid(1, "Cat video"))
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat video"]))
        self.assertEqual((window.getProperty("search"), window.getProperty("kind")), ("1", "video"))
        self.assertEqual(self.site.asked()[-1], R + "kodion/search/query/?q=cats")                  # nothing added for Videos
        self.go(window, "trend")
        self.assertEqual((window.getProperty("search"), window.getProperty("kind")), ("", ""))
        self.assertEqual(window.state["kind"], D.KIND_VIDEO)

    def test_the_prompt_before_anything_is_typed_has_the_row_too(self):
        window = self.open(wait=False, state={"section": "search", "query": ""})
        self.assertEqual((window.mode, window.getProperty("search"), window.getProperty("kind")), (D.PROMPT, "1", "video"))
        window.focus = ACTION
        self.press(window, UP)
        self.assertEqual(window.focus, self.VIDEOS)

    def test_picking_a_type_asks_for_the_same_words_again_with_that_type_and_keeps_the_focus_on_the_row(self):
        window = self.searched("cats")
        self.answer_for("cats", D.KIND_CHANNEL, folder(R + "channel/UC1/", "Cat Channel", art={"thumb": "x"}))
        self.answer_for("cats", D.KIND_LIVE, vid(2, "Cat live", seconds=0, live=True))
        asked = len(Fake.typed)
        self.pick(window, self.CHANNELS, lambda: self.shown(window) == ["Cat Channel"])
        self.assertEqual(self.site.asked()[-1], R + "kodion/search/query/?q=cats&search_type=channel")
        self.assertEqual((window.getProperty("kind"), window.getProperty("title"), window.focus),
                         ("channel", "Results for “cats”", self.CHANNELS))
        self.assertEqual((window.state["kind"], window.state["query"], window.stack), (D.KIND_CHANNEL, "cats", []))
        self.assertEqual(window.entries[0].kind, D.FOLDER)
        self.pick(window, self.LIVE, lambda: self.shown(window) == ["Cat live"])
        self.assertEqual(self.site.asked()[-1], R + "kodion/search/query/?q=cats&search_type=video&event_type=live")
        before = len(self.site.calls)
        self.pick(window, self.VIDEOS, lambda: self.shown(window) == ["Cat video"])                 # seen before: from the cache
        self.assertEqual((len(self.site.calls), window.getProperty("kind")), (before, "video"))
        self.assertEqual(len(Fake.typed), asked)                                                     # no dialog: the same words
        self.press(window, DOWN)
        self.assertEqual(window.focus, GRID)

    def test_the_same_type_again_asks_nothing_and_goes_to_the_results(self):
        window = self.searched("cats")
        before = len(self.site.calls)
        window.focus = self.VIDEOS
        window.onClick(self.VIDEOS)
        self.assertEqual((len(self.site.calls), window.focus, window.loads), (before, GRID, 2))

    def test_a_new_search_keeps_the_type_chosen(self):
        window = self.searched("cats")
        self.pick(window, self.PLAYLISTS, lambda: window.mode == D.EMPTY)
        self.answer_for("dogs", D.KIND_PLAYLIST, folder(R + "playlist/PL9/", "Dog mix"))
        Fake.typed.append("dogs")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Dog mix"]))
        self.assertEqual(self.site.asked()[-1], R + "kodion/search/query/?q=dogs&search_type=playlist")
        self.assertEqual((window.getProperty("kind"), window.state["kind"], window.state["query"]), ("playlist", "playlist", "dogs"))

    def test_a_type_picked_with_no_words_typed_only_changes_the_choice(self):
        window = self.open(wait=False, state={"section": "search", "query": ""})
        window.focus = self.LIVE
        window.onClick(self.LIVE)
        self.assertEqual((window.mode, window.getProperty("kind"), window.state["kind"]), (D.PROMPT, "live", D.KIND_LIVE))
        self.assertEqual(self.site.calls, [])
        self.answer_for("owls", D.KIND_LIVE, vid(3, "Owls live"))
        Fake.typed.append("owls")
        window.focus = ACTION
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Owls live"]))

    def test_the_type_is_not_kept_for_the_next_launch_only_the_words(self):
        window = self.searched("cats")
        self.pick(window, self.CHANNELS, lambda: window.mode == D.EMPTY)
        window.stop()
        with open(files.state_path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"section": "search", "query": "cats"})
        self.answer_for("cats", D.KIND_VIDEO, vid(1, "Cat video"))
        again = self.open(state={"section": "search", "query": "cats", "kind": "channel"})
        self.assertEqual((again.getProperty("kind"), again.state["kind"], self.shown(again)), ("video", "video", ["Cat video"]))
        self.assertEqual(self.site.asked()[-1], R + "kodion/search/query/?q=cats")

    def test_the_add_ons_switch_tiles_are_not_in_the_grid_and_channels_open_like_before(self):
        tiles = [folder(R + "kodion/search/query/?q=cats" + extra, name) for name, extra in (
            ("Videos", "&search_type=video"), ("Channels", "&search_type=channel"), ("Playlists", "&search_type=playlist"),
            ("Live broadcast", "&search_type=video&event_type=live"), ("Upcoming", "&search_type=video&event_type=upcoming"),
            ("Completed", "&search_type=video&event_type=completed"))]
        self.answer_for("cats", D.KIND_VIDEO, *tiles, vid(1, "Cat video"))
        self.answer_for("cats", D.KIND_CHANNEL, *tiles, folder(R + "channel/UC1/", "Cat Channel"))
        self.site.routes[R + "channel/UC1/"] = answer(vid(7, "Inside the channel"))
        window = self.open()
        Fake.typed.append("cats")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat video"]))                      # starts with the real result
        self.pick(window, self.CHANNELS, lambda: self.shown(window) == ["Cat Channel"])
        window.focus = GRID
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Inside the channel"]))
        self.assertEqual((window.getProperty("search"), window.getProperty("title")), ("", "Results for “cats” › Cat Channel"))
        self.press(window, 92)                                                                        # Back: the stack as before
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat Channel"]))
        self.assertEqual((window.getProperty("search"), window.getProperty("kind"), window.stack, window.closed),
                         ("1", "channel", [], False))
        self.press(window, 92)
        self.assertTrue(window.closed)

    def test_an_empty_answer_says_what_was_searched(self):
        window = self.searched("cats")
        for button, title in ((self.CHANNELS, "No channels found"), (self.PLAYLISTS, "No playlists found"),
                              (self.LIVE, "No live broadcasts found"), (self.VIDEOS, "")):
            if title:
                self.pick(window, button, lambda: window.getProperty("msg_title") == title)
                self.assertEqual((window.mode, window.getProperty("action")), (D.EMPTY, "New search"))
                self.assertEqual(window.focus, button)                                                # the row can be used at once
            else:
                self.pick(window, button, lambda: window.mode == D.DATA)

    def test_up_goes_to_the_row_from_the_first_row_and_from_the_card_and_down_comes_back(self):
        self.answer_for("cats", D.KIND_VIDEO, *[vid(n, f"Cat {n}") for n in range(1, 9)])
        window = self.open()
        Fake.typed.append("cats")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: len(self.shown(window)) == 8))
        window.focus = GRID
        window.controls[GRID].selected = 3                                                            # the first row, any column
        self.press(window, UP)
        self.assertEqual(window.focus, self.VIDEOS)
        self.press(window, DOWN)
        self.assertEqual((window.focus, window.controls[GRID].selected), (GRID, 3))
        window.focus, window.controls[GRID].selected = GRID, 4                                       # the second row: Up is the grid's own
        self.press(window, UP)
        self.assertEqual(window.focus, GRID)
        self.pick(window, self.PLAYLISTS, lambda: window.mode == D.EMPTY)
        window.focus = ACTION
        self.press(window, UP)
        self.assertEqual(window.focus, self.PLAYLISTS)                                                # the chosen one gets the focus
        self.press(window, UP)                                                                        # the skin may have moved there already: Up stays
        self.assertEqual(window.focus, self.PLAYLISTS)
        self.press(window, DOWN)
        self.assertEqual(window.focus, ACTION)

    def test_other_sections_and_folders_have_no_row_to_go_to(self):
        self.rec(*[vid(n) for n in range(1, 9)])
        window = self.open()
        window.focus = GRID
        window.controls[GRID].selected = 0
        self.press(window, UP)
        self.assertEqual(window.focus, GRID)
        window.focus = ACTION
        self.press(window, UP)
        self.assertEqual(window.focus, ACTION)
        window.focus = self.CHANNELS
        window.onClick(self.CHANNELS)                                                                 # a stray click: nothing
        self.assertEqual((window.getProperty("kind"), window.state["kind"]), ("", D.KIND_VIDEO))

    def test_the_demo_switches_type_too(self):
        for name in ("get_directory", "signed_in", "keys_configured", "profile_name", "profile_id", "read_step"):
            getattr(files, name).side_effect = AssertionError("real data in the demo")
        Fake.typed.append("stage")
        window = self.open(demo=True)
        self.go(window, D.SEARCH)
        stage = sum(1 for video in demo.VIDEOS if demo.CHANNELS[video[1]] == "Stage Notes")
        self.assertTrue(wait_for(lambda: len(self.shown(window)) == stage and window.mode == D.DATA))     # the videos of that channel
        self.pick(window, self.CHANNELS, lambda: self.shown(window) == ["Stage Notes"])
        self.pick(window, self.LIVE, lambda: self.shown(window) == ["Live: evening jazz from the old hall"])
        self.assertEqual(window.getProperty("kind"), "live")


class DemoWindow(WindowCase):
    def setUp(self):
        super().setUp()
        for name in ("get_directory", "signed_in", "keys_configured", "profile_name", "profile_id", "read_step"):
            getattr(files, name).side_effect = AssertionError("real data in the demo")

    def test_demo_is_marked_fills_from_the_fixture_and_never_touches_the_add_on(self):
        window = self.open(demo=True)
        self.assertEqual(window.mode, D.DATA)
        self.assertEqual((window.getProperty("demo"), window.getProperty("avatar"), window.getProperty("signed")), ("1", "D", "1"))
        self.assertIn(window.getProperty("avatar_color"), profiles.PALETTE)
        items = window.controls[GRID].items
        self.assertEqual(len(items), demo.PAGE)                                 # the next page is not a card
        self.assertNotIn("More videos", [i.label for i in items])
        pictures = [i.art["thumb"] for i in items]
        plates = [p for p in pictures if p == youtube_app.NO_THUMB]
        self.assertTrue(plates and len(plates) < len(items))                    # some have none: they get the plate
        self.assertTrue(any(i.props["badge"] for i in items) and any(not i.props["badge"] for i in items))
        self.assertTrue(any(i.props["meta2"] for i in items) and any(not i.props["meta2"] for i in items))
        self.assertTrue(any(i.props["strip"].endswith("-100") for i in items))
        self.assertTrue(all(pictures), "no card is left without a picture")
        for picture in set(pictures):
            self.assertTrue(os.path.isfile(picture), picture)
            self.assertLess(os.path.getsize(picture), 20000, picture)
        self.assertEqual(window.routes, demo.ROUTES)

    def test_demo_pages_sections_folders_and_search_all_work(self):
        window = self.open(demo=True)
        window.controls[GRID].selected = demo.PAGE - youtube_app.AHEAD            # near the end: the next page comes by itself
        self.press(window, 4)
        self.assertTrue(wait_for(lambda: len(window.controls[GRID].items) == 30))
        self.assertEqual(window.controls[GRID].selected, demo.PAGE - youtube_app.AHEAD)
        self.go(window, "later")
        self.assertTrue(wait_for(lambda: len(self.shown(window)) == len(demo.SECTION_VIDEOS["later"])))
        self.go(window, "lists")
        self.assertTrue(wait_for(lambda: self.shown(window)[:1] == [demo.PLAYLISTS[0][0]]))
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: len(self.shown(window)) == len(demo.PLAYLISTS[0][1])))
        Fake.typed.append("bread")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Bread without kneading"]))
        self.assertEqual(window.stack, [])

    def test_demo_never_plays_never_signs_in_never_saves_and_says_so(self):
        window = self.open(demo=True)
        window.onClick(GRID)
        self.assertEqual((Fake.rpc, Fake.played, Fake.builtins), ([], [], []))
        self.assertEqual(Fake.notes, [youtube_app.DEMO_NOTICE])
        Fake.typed.append("stars")
        self.go(window, D.SEARCH)
        window.stop()
        self.assertFalse(os.path.exists(files.state_path()))

    def test_each_scenario_shows_its_card(self):
        for scenario, mode in (("signin", D.SIGNIN), ("needkey", D.NEEDKEY), ("empty", D.EMPTY), ("error", D.ERROR),
                               ("unavailable", D.UNAVAILABLE)):
            window = self.open(demo=True, scenario=scenario)
            self.assertEqual(window.mode, mode, scenario)
            self.assertTrue(window.getProperty("msg_title"), scenario)
            self.assertEqual(window.focus, ACTION, scenario)
            self.assertEqual(window.controls[GRID].items, [], scenario)
        window = self.open(demo=True, scenario="signin")
        window.onClick(ACTION)                                                  # no real sign-in from the demo
        self.assertEqual(Fake.notes[-1], "Demo: nothing is signed in.")
        self.assertEqual((window.getProperty("avatar"), window.getProperty("demo")), ("?", "1"))
        self.assertEqual(window.getProperty("signed"), "0")

    def test_the_key_card_of_the_demo_shows_a_step_in_the_phone_pages_russian_and_reads_no_file(self):
        window = self.open(demo=True, scenario="needkey")
        self.assertTrue(wait_for(lambda: window.getProperty("step") != ""))
        self.assertEqual(window.getProperty("step"), "Step 3 of 6: Создайте проект в Google Cloud")
        self.assertTrue(window.getProperty("step_hint1").startswith("Откройте console.cloud.google.com"))
        self.assertTrue(wait_for(lambda: window.getProperty("key_qr") == "/tmp/qr.png"))
        self.assertEqual(files.read_step.call_count, 0)

    def test_the_loading_scenario_never_ends_and_stops_with_the_window(self):
        window = self.open(wait=False, demo=True, scenario="loading")
        self.assertTrue(wait_for(lambda: window.getProperty("mode") == "loading"))
        time.sleep(0.05)
        self.assertEqual((window.mode, window.loads), (D.LOADING, 0))
        window.stop()
        self.assertTrue(wait_for(lambda: window.loads == 1))
        self.assertEqual(window.mode, D.LOADING)

    def test_an_unknown_scenario_is_the_plain_demo(self):
        window = self.open(demo=True, scenario="what")
        self.assertEqual((window.scenario, window.mode), ("", D.DATA))
        self.assertEqual(self.make(demo=False, scenario="needkey").scenario, "")

    def test_demo_entry_point_through_main(self):
        seen = []
        with mock.patch.object(WindowXML, "doModal", lambda self: seen.append((self.demo, self.scenario))), \
                mock.patch.object(youtube_app.ui, "load", side_effect=lambda cls, xml: cls()):
            youtube_app.main(["demo"])
            youtube_app.main(["demo", "needkey"])
            youtube_app.main(["open", "needkey"])
            youtube_app.main([])
        self.assertEqual(seen, [(True, ""), (True, "needkey"), (False, ""), (False, "")])
        self.assertEqual(Fake.home.get(youtube_app.RUNNING), "")

    def test_a_second_launch_while_open_does_nothing(self):
        si = youtube_app.single_instance
        Fake.home[youtube_app.RUNNING] = si.encode(si.Flag("t", 14001, time.time() - 3600))      # Kodi says it is active
        with mock.patch.object(youtube_app.ui, "load") as load:
            self.assertFalse(youtube_app.main(["open"]))
        load.assert_not_called()

    def test_a_flag_of_a_window_that_is_gone_does_not_block_the_launch(self):
        si = youtube_app.single_instance
        Fake.home[youtube_app.RUNNING] = si.encode(si.Flag("t", 14001, time.time() - 3600))
        shown = []
        with mock.patch.object(si, "window_active", return_value=False), \
                mock.patch.object(si, "video_playing", return_value=False), \
                mock.patch.object(youtube_app.ui, "load", side_effect=lambda cls, xml: cls()), \
                mock.patch.object(WindowXML, "doModal", lambda self: shown.append(si.decode(Fake.home[youtube_app.RUNNING]))):
            self.assertTrue(youtube_app.main(["open"]))
        self.assertEqual(len(shown), 1)
        self.assertNotEqual(shown[0].token, "t")
        self.assertEqual(Fake.home.get(youtube_app.RUNNING), "")

    def test_the_window_tells_the_flag_its_id_when_it_opens(self):
        si = youtube_app.single_instance
        window = self.make(demo=True)
        window.instance = si.claim(xbmcgui.Window(youtube_app.ui.HOME), youtube_app.RUNNING)
        with mock.patch.object(xbmcgui, "getCurrentWindowId", create=True, return_value=14002):
            window.onInit()
        self.assertEqual(si.decode(Fake.home[youtube_app.RUNNING]).window_id, 14002)


class ProfileChange(WindowCase):
    """The window follows the add-on's current profile (current_user), as the phone's chips and its status line do."""

    def looks(self, window, n=3):
        """Wait for the window's profile timer to have looked n more times."""
        seen = []
        with mock.patch.object(files, "profile_id", side_effect=lambda log=True: seen.append(1) or Fake.profile):
            self.assertTrue(wait_for(lambda: len(seen) >= n), "the timer did not look")
        time.sleep(0.05)

    def test_a_changed_profile_clears_the_cache_the_circle_and_loads_the_section_again(self):
        self.rec(vid(1, "Anna's"))
        window = self.open()
        self.assertEqual((self.shown(window), window.getProperty("avatar"), window.profile), (["Anna's"], "A", "p1"))
        self.assertTrue(window.cache, "the section is cached")
        self.rec(vid(2, "Boris's"))
        Fake.profile, Fake.name = "p2", "Борис"
        self.assertTrue(wait_for(lambda: window.loads >= 2), "a second load")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris's"]))
        self.assertEqual((window.getProperty("avatar"), window.profile, window.view.key), ("Б", "p2", "rec"))
        self.assertEqual(self.site.asked().count(D.SECTIONS[0].route), 2, "asked again, not from the cache")
        self.assertEqual([i.props["active"] for i in window.controls[RAIL].items][:2], ["1", ""])

    def test_the_cache_does_not_serve_the_other_profiles_list(self):
        self.rec(vid(1, "Anna's"))
        window = self.open()
        self.site.routes[D.SECTIONS[1].route] = answer(vid(5, "Anna subs"))
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Anna subs"]))
        self.assertEqual(len(window.cache), 2)
        self.site.routes[D.SECTIONS[1].route] = answer(vid(6, "Boris subs"))
        Fake.profile = "p2"
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris subs"]))
        self.assertEqual((window.view.key, window.profile), ("subs", "p2"))
        self.assertNotIn("Anna's", [c[1].entries[0].title for c in window.cache.values() if c[1].entries])

    def test_the_circle_is_empty_until_the_new_profile_has_answered(self):
        self.rec(vid(1))
        window = self.open()
        self.site.held[D.SECTIONS[0].route] = hold = threading.Event()
        Fake.profile, Fake.name = "p2", "Борис"
        self.assertTrue(wait_for(lambda: window.getProperty("mode") == "loading"))
        self.assertEqual((window.getProperty("avatar"), window.getProperty("signed")), ("", ""))
        hold.set()
        self.assertTrue(wait_for(lambda: window.getProperty("avatar") == "Б"))

    def test_a_profile_that_did_not_change_loads_nothing(self):
        self.rec(vid(1))
        window = self.open()
        self.looks(window)
        self.assertEqual((window.loads, self.site.asked().count(D.SECTIONS[0].route)), (1, 1))

    def test_a_profile_that_cannot_be_told_is_not_a_change_and_comes_back_as_it_was(self):
        self.rec(vid(1))
        window = self.open()
        Fake.profile = None
        self.looks(window)
        Fake.profile = "p1"
        self.looks(window)
        self.assertEqual((window.loads, window.profile), (1, "p1"))

    def test_a_playlist_of_the_old_profile_is_left_for_the_section_it_came_from(self):
        mix = R + "playlist/PL1/"
        self.site.routes[D.SECTIONS[4].route] = answer(folder(mix, "Mix"))
        self.site.routes[mix] = answer(vid(1, "Inside"))
        window = self.open()
        self.go(window, "lists")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Mix"]))
        window.controls[GRID].selected = 0
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Inside"]))
        self.assertTrue(window.stack)
        self.site.routes[D.SECTIONS[4].route] = answer(folder(R + "playlist/PL9/", "Boris's list"))
        Fake.profile = "p2"
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris's list"]))
        self.assertEqual((window.stack, window.getProperty("title")), ([], "Playlists"))

    def test_the_timer_stops_with_the_window_and_the_demo_has_none(self):
        window = self.open()
        window.stop()
        loads = window.loads
        Fake.profile = "p2"
        time.sleep(0.2)
        self.assertEqual(window.loads, loads)
        self.assertTrue(window._timers["profile"].finished.is_set())
        demo = self.open(demo=True)
        self.assertNotIn("profile", demo._timers)

    def test_a_window_that_has_not_loaded_yet_has_nothing_to_compare(self):
        window = self.make()
        Fake.profile = "p2"
        window._profile_tick()                                                  # before any load has said which profile it is
        self.assertEqual((window.view, window.loads, window.profile_known), (None, 0, False))
        self.assertIn("profile", window._timers)                                # and it looks again later


class PickProfile(WindowCase):
    """OK on the circle: the picker of the Accounts screen; the window then follows the profile picked."""

    @staticmethod
    def profile(uid, name, signed=True):
        return {"id": str(uid), "name": name, "current": True, "tokens": 4 if signed else 0, "signed_in": signed}

    def switching(self, uid, name, signed=True):
        """A picker that switches the add-on to profile `uid`, as accounts.choose_profile does, and returns it."""
        def choose():
            Fake.profile, Fake.name, Fake.signed = f"p{uid}", name, signed
            return self.profile(uid, name, signed)
        return mock.patch.object(accounts, "choose_profile", side_effect=choose)

    def test_a_picked_profile_is_switched_to_and_the_window_shows_it(self):
        self.rec(vid(1, "Anna video"))
        window = self.open()
        self.assertEqual((self.shown(window), window.getProperty("avatar")), (["Anna video"], "A"))
        self.rec(vid(2, "Boris video"))
        loads = window.loads
        with self.switching(2, "Boris") as choose, mock.patch.object(accounts, "signin_service") as signin:
            window.onClick(AVATAR)
        choose.assert_called_once_with()
        signin.assert_not_called()
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris video"] and window.getProperty("avatar") == "B"))
        self.assertGreater(window.loads, loads)
        self.assertEqual(window.profile, "p2")

    def test_the_profile_is_followed_at_once_not_only_by_the_timer(self):
        self.rec(vid(1, "Anna video"))
        window = self.open()
        window._cancel("profile")
        self.rec(vid(2, "Boris video"))
        with self.switching(2, "Boris"):
            window.onClick(AVATAR)
        self.assertEqual(window.profile, "p2")                                      # the click itself looked (the timer was off)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris video"]))

    def test_backing_out_of_the_picker_changes_nothing(self):
        self.rec(vid(1, "Anna video"))
        window = self.open()
        loads = window.loads
        with mock.patch.object(accounts, "choose_profile", return_value=None) as choose, \
                mock.patch.object(accounts, "signin_service") as signin:
            window.onClick(AVATAR)
        choose.assert_called_once_with()
        signin.assert_not_called()
        time.sleep(0.1)
        self.assertEqual((window.loads, window.profile, window.getProperty("avatar")), (loads, "p1", "A"))

    def test_a_new_profile_with_no_account_is_offered_the_sign_in_with_a_way_past_it_and_then_looked_at_again(self):
        self.rec(vid(1, "Anna video"))
        window = self.open()
        with self.switching(3, "Clara", signed=False), mock.patch.object(accounts, "signin_service", return_value="skipped") as signin:
            window.onClick(AVATAR)
        signin.assert_called_once_with("youtube", allow_skip=True)
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN and window.getProperty("avatar") == "?"))

    def test_the_demo_switches_nothing_and_says_so(self):
        window = self.open(demo=True)
        with mock.patch.object(accounts, "choose_profile") as choose:
            window.onClick(AVATAR)
        choose.assert_not_called()
        self.assertEqual(Fake.notes, [youtube_app.DEMO_PICK_NOTICE])

    def test_a_picker_that_breaks_does_not_kill_the_window(self):
        self.rec(vid(1, "Anna video"))
        window = self.open()
        with mock.patch.object(accounts, "choose_profile", side_effect=RuntimeError("boom")):
            window.onClick(AVATAR)
        self.assertEqual(window.mode, D.DATA)


class PagesPure(unittest.TestCase):
    """youtube_pages: what a view is kept under and a listing as a JSON value."""

    def listing(self):
        return D.parse_reply(answer(vid(1, "One", seconds=61, views="1,234", dateadded="2026-11-20 10:00:00", live=True,
                                        resume={"position": 30, "total": 120}),
                                    folder(R + "playlist/P/", "Mix", videos=7), folder(R + "?page_token=abc", "Next")))

    def test_a_listing_goes_through_json_and_comes_back_equal(self):
        listing = self.listing()
        self.assertEqual((len(listing.entries), bool(listing.more)), (2, True))
        self.assertEqual(P.from_value(json.loads(json.dumps(P.to_value(listing)))), listing)

    def test_a_page_that_is_not_what_this_screen_wrote_is_no_page(self):
        good = P.to_value(self.listing())
        row = good["entries"][0]
        with_row = lambda *new: {**good, "entries": [list(new)]}      # noqa: E731
        for bad in (None, [], {}, "x", {"entries": [], "more": ""}, {"entries": "x", "more": ""}, {"entries": good["entries"]},
                    {**good, "more": 5}, {**good, "more": "http://evil/"}, {**good, "entries": [None]},
                    with_row(*row[:-1]), with_row(*row, 1), with_row("audio", *row[1:]), with_row(row[0], "file:///etc/passwd", *row[2:]),
                    with_row(*row[:4], "61", *row[5:]), with_row(*row[:4], True, *row[5:]), with_row(*row[:9], 1, *row[10:]),
                    with_row(*row[:11], "x"), {**good, "entries": good["entries"] * 150}):
            self.assertIsNone(P.from_value(bad), bad)

    def test_namespaces_keys_and_times(self):
        self.assertEqual((P.namespace("7"), P.namespace(""), P.namespace(None)), ("youtube:7", "youtube:anon", None))
        self.assertEqual(P.key_of(D.section_view("subs", {"subs": R + "other/"})), "s:subs")           # the route found at run time is no key
        cats, owls = (D.section_view(D.SEARCH, query="cats", kind=k) for k in (D.KIND_VIDEO, D.KIND_CHANNEL))
        self.assertNotEqual(P.key_of(cats), P.key_of(owls))
        self.assertEqual(P.key_of(D.folder_view(D.Entry(D.FOLDER, R + "playlist/P/", "Mix", "", 0, "", ""))), "r:" + R + "playlist/P/")
        self.assertLess(P.ttl_of(cats), P.ttl_of(D.section_view("rec")))
        self.assertLess(P.max_age_of(cats), P.max_age_of(D.section_view("rec")))

    def test_the_sections_to_fetch_follow_the_one_on_screen(self):
        self.assertEqual(P.warm_keys("rec"), ["subs", "later", "history", "lists", "trend"])
        self.assertEqual(P.warm_keys("history"), ["lists", "trend", "rec", "subs", "later"])
        self.assertEqual(P.warm_keys("trend"), ["rec", "subs", "later", "history", "lists"])
        for other in (D.SEARCH, D.FOLDER_KEY, ""):
            self.assertEqual(P.warm_keys(other), ["rec", "subs", "later", "history", "lists", "trend"], other)


class DiskCache(WindowCase):
    """The first pages kept on disk (page_cache) under the profile's namespace, and the sections fetched at start-up (prefetch)."""
    T0 = 1_800_000_000.0
    REC = D.SECTIONS[0].route

    def setUp(self):
        super().setUp()
        self.real_warm = prefetch.warm
        self.no_warm = mock.patch.object(prefetch, "warm", side_effect=lambda *a, **k: None)     # most tests are not about it
        for patch in (mock.patch.object(youtube_app, "PAGES", True), self.no_warm):
            patch.start()
            self.addCleanup(patch.stop)

    def warming(self):
        """Turn the start-up fetch on, without its pauses."""
        self.no_warm.stop()
        patch = mock.patch.object(prefetch, "warm", side_effect=lambda ns, jobs, **k: self.real_warm(ns, jobs, **{**k, "pause": 0, "nice": 0, "delay": 0}))
        patch.start()
        self.addCleanup(patch.stop)

    def kept(self, key, profile="p1"):
        return page_cache.get(P.namespace(profile), key, now=Fake.now or time.time())

    def titles(self, hit):
        return [row[2] for row in hit.value["entries"]]

    def stale_open(self, *first, more=None, then=None):
        """A window opened when the page of the first launch is older than its ttl; `then` changes the world before that."""
        page_cache.drop(P.namespace("p1"))
        Fake.now = self.T0
        self.rec(*(first or (vid(1, "One"), vid(2, "Two"))), more=more)
        self.open().stop()
        Fake.now = self.T0 + P.PAGE_TTL + 1
        if then:
            then()
        return self.open(wait=False)

    def test_a_page_seen_before_shows_at_once_in_the_next_launch_without_asking(self):
        self.rec(vid(1, "One"), vid(2, "Two"))
        self.open().stop()
        self.assertEqual(self.titles(self.kept("s:rec")), ["One", "Two"])
        self.site.calls.clear()
        again = self.open(wait=False)
        self.assertEqual((self.shown(again), again.mode, again.focus), (["One", "Two"], D.DATA, GRID))      # before onInit returned
        self.assertEqual(again.controls[GRID].items[0].art, {"thumb": "https://i.ytimg.com/vi/v1/hq.jpg"})
        time.sleep(0.1)
        self.assertEqual((self.site.asked(), again.loads), ([], 0))

    def test_a_page_never_seen_is_a_miss_and_says_loading_as_before(self):
        self.rec(vid(1, "One"))
        self.site.held[self.REC] = hold = threading.Event()
        window = self.open(wait=False)
        self.assertEqual((window.mode, self.shown(window), window.getProperty("msg_title")), (D.LOADING, [], "Loading…"))
        hold.set()
        self.assertTrue(wait_for(lambda: self.shown(window) == ["One"]))

    def test_a_stale_page_shows_at_once_then_is_swapped_when_it_changed_and_the_cursor_stays(self):
        window = self.stale_open(vid(1, "One"), vid(2, "Two"), vid(3, "Three"),
                                 then=lambda: (self.rec(vid(1, "One"), vid(9, "New"), vid(3, "Three"), vid(4, "Four")),
                                               self.site.held.update({self.REC: threading.Event()})))
        hold = self.site.held[self.REC]
        self.assertEqual((self.shown(window), window.mode), (["One", "Two", "Three"], D.DATA))
        window.controls[GRID].selected = 2
        self.assertTrue(wait_for(lambda: self.site.asked().count(self.REC) == 2), "asked again in the background")
        self.assertEqual(self.shown(window), ["One", "Two", "Three"])
        hold.set()
        self.assertTrue(wait_for(lambda: self.shown(window) == ["One", "New", "Three", "Four"]))
        self.assertEqual((window.controls[GRID].selected, window.focus, window.mode), (2, GRID, D.DATA))
        self.assertEqual(self.titles(self.kept("s:rec")), ["One", "New", "Three", "Four"])
        self.assertFalse(self.kept("s:rec").stale)

    def test_a_stale_page_that_did_not_change_stays_as_it_is_and_is_young_again(self):
        window = self.stale_open()
        before = list(window.controls[GRID].items)
        self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertTrue(all(a is b for a, b in zip(before, window.controls[GRID].items)), "no card was rebuilt")
        self.assertEqual(self.shown(window), ["One", "Two"])
        self.assertFalse(self.kept("s:rec").stale)

    def test_the_refresh_does_not_touch_a_screen_the_user_has_left(self):
        window = self.stale_open(then=lambda: (self.rec(vid(7, "Newer")), self.site.held.update({self.REC: threading.Event()})))
        hold = self.site.held[self.REC]
        self.site.routes[D.SECTIONS[1].route] = answer(vid(5, "Subs"))
        self.assertTrue(wait_for(lambda: self.site.asked().count(self.REC) == 2))
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Subs"]))
        hold.set()
        self.assertTrue(wait_for(lambda: window.loads >= 2))
        time.sleep(0.05)
        self.assertEqual((self.shown(window), window.view.key), (["Subs"], "subs"))
        self.assertEqual(self.titles(self.kept("s:rec")), ["Newer"])                  # but the disk has it for next time

    def test_a_failed_refresh_leaves_the_page_and_an_empty_or_signed_out_answer_replaces_and_drops_it(self):
        window = self.stale_open(then=lambda: self.site.routes.update({self.REC: {"id": 1, "error": {"code": 1, "message": "boom"}}}))
        self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual((self.shown(window), window.mode), (["One", "Two"], D.DATA))
        self.assertIsNotNone(self.kept("s:rec"))
        window = self.stale_open(then=lambda: self.site.routes.update({self.REC: INVALID}))
        self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual((self.shown(window), window.mode), (["One", "Two"], D.DATA))
        window = self.stale_open(then=lambda: self.site.routes.update({self.REC: answer()}))
        self.assertTrue(wait_for(lambda: window.mode == D.EMPTY))
        self.assertIsNone(self.kept("s:rec"))
        self.rec(vid(1, "One"))
        window = self.stale_open(then=lambda: setattr(Fake, "signed", False))
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        self.assertIsNone(self.kept("s:rec"))

    def test_nothing_that_is_not_a_list_of_cards_is_kept(self):
        error = {"id": 1, "error": {"code": 1, "message": "boom"}}
        for name, mode, world in (("error", D.ERROR, lambda: self.site.routes.update({self.REC: error})),
                                  ("refused", D.UNAVAILABLE, lambda: self.site.routes.update({self.REC: INVALID})),
                                  ("empty", D.EMPTY, lambda: self.site.routes.update({self.REC: answer()})),
                                  ("signin", D.SIGNIN, lambda: setattr(Fake, "signed", False)),
                                  ("needkey", D.NEEDKEY, lambda: (setattr(Fake, "signed", False), setattr(Fake, "keys", False)))):
            Fake.signed, Fake.keys = True, True
            self.site.routes.pop(self.REC, None)
            world()
            window = self.open()
            self.assertEqual(window.mode, mode, name)
            self.assertIsNone(self.kept("s:rec"), name)
            window.stop()
        page_dir = page_cache.directory()
        self.assertEqual([name for name in os.listdir(page_dir) if name.endswith(".json")] if os.path.isdir(page_dir) else [], [])

    def test_a_card_that_asks_again_forgets_the_page_it_shows(self):
        self.rec(vid(1, "One"))
        window = self.open()
        self.assertIsNotNone(self.kept("s:rec"))
        self.rec()
        window.mode = D.EMPTY                                                          # the screen's button is the card's
        window.onClick(ACTION)
        self.assertTrue(wait_for(lambda: window.loads >= 2))
        self.assertIsNone(self.kept("s:rec"))

    def test_a_profile_has_its_own_pages_and_the_other_ones_never_show(self):
        self.rec(vid(1, "Anna's"))
        self.open().stop()
        Fake.profile, Fake.name = "p2", "Boris"
        self.rec(vid(2, "Boris's"))
        self.site.held[self.REC] = hold = threading.Event()
        boris = self.open(wait=False)
        self.assertEqual((boris.mode, self.shown(boris)), (D.LOADING, []))                  # not Anna's
        hold.set()
        self.assertTrue(wait_for(lambda: self.shown(boris) == ["Boris's"]))
        boris.stop()
        self.assertEqual((self.titles(self.kept("s:rec", "p1")), self.titles(self.kept("s:rec", "p2"))), (["Anna's"], ["Boris's"]))
        Fake.profile = "p1"
        self.site.calls.clear()
        window = self.open(wait=False)
        self.assertEqual(self.shown(window), ["Anna's"])
        Fake.profile = "p2"                                                          # the phone switches the profile
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Boris's"]))
        self.assertEqual(self.site.asked().count(self.REC), 0, "both from the disk")
        self.assertEqual(self.shown(window), ["Boris's"])

    def test_a_profile_that_cannot_be_told_keeps_and_shows_nothing_and_the_demo_has_no_disk_cache(self):
        self.rec(vid(1, "One"))
        Fake.profile = None
        self.open().stop()
        page_dir = page_cache.directory()
        self.assertEqual(os.listdir(page_dir) if os.path.isdir(page_dir) else [], [])
        self.open(demo=True).stop()
        self.assertEqual(os.listdir(page_dir) if os.path.isdir(page_dir) else [], [])

    def test_no_profile_has_a_namespace_of_its_own(self):
        Fake.profile = ""
        self.rec(vid(1, "One"))
        self.open().stop()
        self.assertEqual(self.titles(page_cache.get("youtube:anon", "s:rec")), ["One"])

    def test_a_search_is_kept_by_its_words_and_its_type_for_a_short_time(self):
        Fake.now = self.T0
        self.rec(vid(1))
        for kind, title in ((D.KIND_VIDEO, "Cat video"), (D.KIND_CHANNEL, "Cat channel")):
            self.site.routes[D.search_route("cats", kind)] = answer(vid(5, title))
        window = self.open()
        Fake.typed.append("cats")
        self.go(window, D.SEARCH)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat video"]))
        window.focus = KIND_IDS[1]
        window.onClick(KIND_IDS[1])
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Cat channel"]))
        window.stop()
        state = {"section": "search", "query": "cats"}
        self.site.calls.clear()
        again = self.open(wait=False, state=state)                                   # the app starts on Videos
        self.assertEqual(self.shown(again), ["Cat video"])
        again.onClick(KIND_IDS[1])
        self.assertEqual(self.shown(again), ["Cat channel"])
        self.assertEqual(self.site.asked(), [])
        self.assertEqual(self.titles(self.kept("r:" + D.search_route("cats", D.KIND_CHANNEL))), ["Cat channel"])
        self.assertIsNone(self.kept("r:" + D.search_route("dogs", D.KIND_VIDEO)))
        again.stop()
        Fake.now = self.T0 + P.SEARCH_TTL + 1                                        # short: asked again, shown meanwhile
        self.site.routes[D.search_route("cats", D.KIND_VIDEO)] = answer(vid(5, "Cat video"), vid(6, "Cat video 2"))
        stale = self.open(wait=False, state=state)
        self.assertEqual(self.shown(stale)[:1], ["Cat video"])
        self.assertTrue(wait_for(lambda: self.shown(stale) == ["Cat video", "Cat video 2"]))
        stale.stop()
        Fake.now = self.T0 + P.SEARCH_MAX_AGE + P.SEARCH_TTL + 2                     # too old: not shown at all
        self.site.held[D.search_route("cats", D.KIND_VIDEO)] = hold = threading.Event()
        old = self.open(wait=False, state=state)
        self.assertEqual((old.mode, self.shown(old)), (D.LOADING, []))
        hold.set()

    def test_only_the_first_page_is_kept_and_the_next_page_is_asked_live_every_time(self):
        more = R + "special/recommendations/?page_token=2"
        self.rec(vid(1, "One"), more=more)
        self.site.routes[more] = answer(vid(2, "Two"))
        window = self.open()
        self.assertTrue(wait_for(lambda: self.shown(window) == ["One", "Two"]))
        window.stop()
        hit = self.kept("s:rec")
        self.assertEqual((self.titles(hit), hit.value["more"]), (["One"], more))
        again = self.open(wait=False)
        self.assertEqual(self.shown(again)[:1], ["One"])
        self.assertTrue(wait_for(lambda: self.shown(again) == ["One", "Two"]))
        self.assertEqual(self.site.asked().count(more), 2)
        self.assertEqual(self.titles(self.kept("s:rec")), ["One"])

    def test_a_next_page_is_not_asked_from_a_stale_first_page_until_that_was_asked_again(self):
        more1, more2 = (R + f"special/recommendations/?page_token={n}" for n in (2, 3))
        self.site.routes[more1] = answer(vid(8, "Old next"))
        self.site.routes[more2] = answer(vid(3, "Three"))
        window = self.stale_open(vid(1, "One"), more=more1,
                                 then=lambda: (self.rec(vid(1, "One"), more=more2), self.site.held.update({self.REC: threading.Event()})))
        self.assertTrue(wait_for(lambda: self.site.asked().count(self.REC) == 2))
        window._more_when_near()
        time.sleep(0.1)
        self.assertEqual(self.site.asked().count(more1), 1, "only the first launch asked for it")
        self.site.held[self.REC].set()
        self.assertTrue(wait_for(lambda: self.shown(window) == ["One", "Three"]))
        self.assertEqual((self.site.asked().count(more1), self.site.asked().count(more2)), (1, 1))

    def test_a_damaged_file_or_a_page_of_another_shape_is_a_miss(self):
        self.rec(vid(1, "One"))
        self.open().stop()
        folder_ = page_cache.directory()
        for name in os.listdir(folder_):
            put(os.path.join(folder_, name), "{not json")
        window = self.open()
        self.assertEqual(self.shown(window), ["One"])
        self.assertEqual(window.loads, 1)
        window.stop()
        page_cache.put(P.namespace("p1"), "s:rec", {"entries": [["x"]], "more": ""})
        window = self.open()
        self.assertEqual((self.shown(window), window.loads), (["One"], 1))

    def test_signing_out_drops_the_accounts_pages_and_leaves_other_apps(self):
        self.rec(vid(1, "One"))
        self.open().stop()
        page_cache.put("sweettv:me", "channels", {"x": 1})
        accounts.sign_out("youtube")
        self.assertIsNone(self.kept("s:rec"))
        self.assertEqual(page_cache.get("sweettv:me", "channels").value, {"x": 1})
        self.assertIn(accounts.SIGNOUT["youtube"], Fake.builtins[-1])

    # -- the fetch at start-up --

    def sections(self):
        for i, name in ((1, "S1"), (3, "S3"), (4, "S4"), (5, "S5")):
            self.site.routes[D.SECTIONS[i].route] = answer(vid(10 + i, name))
        self.site.routes[LATER] = answer(vid(20, "Later one"))
        self.rec(vid(1, "R"))

    def test_the_other_sections_are_fetched_right_after_the_window_opens_one_by_one(self):
        self.warming()
        self.sections()
        window = self.open()
        self.assertTrue(window.warming.wait(5))
        self.assertEqual(self.site.asked(), [R, self.REC, D.SECTIONS[1].route, LATER, D.SECTIONS[3].route,
                                              D.SECTIONS[4].route, D.SECTIONS[5].route])
        self.assertTrue(all(not in_main for _, in_main in self.site.calls), "off the UI thread")
        for key, title in (("rec", "R"), ("subs", "S1"), ("later", "Later one"), ("history", "S3"), ("lists", "S4"), ("trend", "S5")):
            self.assertEqual(self.titles(self.kept("s:" + key)), [title], key)
        window.stop()
        self.site.calls.clear()
        again = self.open(wait=False, state={"section": "history"})
        self.assertEqual(self.shown(again), ["S3"])                                   # the second launch of the day: at once
        self.assertTrue(again.warming.wait(5))
        self.assertEqual(self.site.asked(), [], "everything was fresh: nothing is fetched again")

    def test_the_visible_section_comes_first_and_the_others_follow_it_in_the_rails_order(self):
        self.warming()
        self.sections()
        self.site.routes[D.SECTIONS[3].route] = answer(vid(3, "S3"))
        window = self.open(state={"section": "history"})
        self.assertTrue(window.warming.wait(5))
        self.assertEqual(self.site.asked(), [R, D.SECTIONS[3].route, D.SECTIONS[4].route, D.SECTIONS[5].route, self.REC,
                                              D.SECTIONS[1].route, LATER])

    def test_signed_out_only_what_needs_no_account_is_fetched(self):
        self.warming()
        self.sections()
        Fake.signed = False
        window = self.open()
        self.assertEqual(window.mode, D.SIGNIN)
        self.assertTrue(window.warming.wait(5))
        self.assertEqual(self.site.asked(), [R, D.SECTIONS[5].route])
        self.assertEqual([self.kept("s:" + key) is not None for key in D.SECTION_KEYS[:6]], [False] * 5 + [True])

    def test_the_fetch_leaves_a_section_that_answers_nothing_and_goes_on(self):
        self.warming()
        self.sections()
        self.site.routes[D.SECTIONS[1].route] = answer()
        self.site.routes[LATER] = {"id": 1, "error": {"code": 1, "message": "boom"}}
        window = self.open()
        self.assertTrue(window.warming.wait(5))
        self.assertEqual([self.kept("s:" + key) is not None for key in ("subs", "later", "history", "lists", "trend")],
                         [False, False, True, True, True])

    def test_the_fetch_waits_while_the_window_is_waiting_for_its_own_page(self):
        self.warming()
        self.sections()
        self.site.held[self.REC] = hold = threading.Event()
        window = self.open(wait=False)
        time.sleep(0.5)
        self.assertEqual(self.site.asked(), [R, self.REC])                           # nothing competes with the Loading card
        hold.set()
        self.assertTrue(window.warming.wait(5))
        self.assertIn(D.SECTIONS[5].route, self.site.asked())

    def test_closing_the_window_stops_the_fetch(self):
        self.warming()
        self.sections()
        self.site.held[D.SECTIONS[1].route] = hold = threading.Event()
        window = self.open()
        handle = window.warming
        self.assertTrue(wait_for(lambda: D.SECTIONS[1].route in self.site.asked()))
        window.stop()
        hold.set()
        self.assertTrue(handle.wait(5))
        self.assertEqual((handle.cancelled, window.warming), (True, None))
        self.assertNotIn(D.SECTIONS[5].route, self.site.asked())

    def test_a_switched_profile_is_fetched_for_under_its_own_namespace(self):
        self.warming()
        self.sections()
        window = self.open()
        self.assertTrue(window.warming.wait(5))
        first = window.warming
        self.site.routes[D.SECTIONS[1].route] = answer(vid(31, "Boris subs"))
        Fake.profile, Fake.name = "p2", "Boris"
        self.assertTrue(wait_for(lambda: window.warming is not first and window.warming is not None and window.warming.wait(0.05)))
        self.assertEqual(window.warming.namespace, "youtube:p2")
        self.assertEqual(self.titles(self.kept("s:subs", "p2")), ["Boris subs"])
        self.assertEqual(self.titles(self.kept("s:subs", "p1")), ["S1"])


class Splash(WindowCase):
    """The launch splash: a cold start shows it instead of the empty grid and the Loading card, until the first page or card is
    shown; a warm start never does; the cache is warmed from the start of the launch in every case."""
    T0 = 1_800_000_000.0
    REC = D.SECTIONS[0].route
    COLD = ["", "1", ""]                         # what the splash property took: the empty start, the splash, the end of it

    def setUp(self):
        super().setUp()
        self.real_warm = prefetch.warm
        for patch in (mock.patch.object(youtube_app, "PAGES", True),
                      mock.patch.object(prefetch, "warm", side_effect=lambda ns, jobs, **k: self.real_warm(
                          ns, jobs, **{**k, "pause": 0, "nice": 0, "delay": 0}))):
            patch.start()
            self.addCleanup(patch.stop)
        page_cache.drop(P.namespace("p1"))

    def start(self, **kw):
        """A window opened, its first load not waited for, and the list of the values its splash property takes."""
        self.assertTrue(wait_for(lambda: not prefetch._running), "the fetch of an earlier window is over")
        window = self.make(**kw)
        seen = []
        set_property = window.setProperty

        def watch(key, value):
            if key == "splash":
                seen.append(value)
            set_property(key, value)
        window.setProperty = watch
        window.onInit()
        return window, seen

    def others(self):
        for i in (1, 3, 4, 5):
            self.site.routes[D.SECTIONS[i].route] = answer(vid(10 + i, f"S{i}"))
        self.site.routes[LATER] = answer(vid(20, "Later one"))

    def finish(self, window):
        self.assertTrue(wait_for(lambda: window.loads >= 1), "the first load")

    def test_a_cold_start_shows_the_splash_until_the_first_listing_is_shown(self):
        self.rec(vid(1, "One"))
        self.site.held[self.REC] = hold = threading.Event()
        window, seen = self.start()
        self.assertEqual((window.getProperty("splash"), window.splash, window.mode), ("1", True, D.LOADING))
        self.assertEqual((window.focus, youtube_app.SPLASH_CAP, window._timers["splash"].interval), (0, 15.0, 15.0))
        hold.set()
        self.finish(window)
        self.assertEqual((window.getProperty("splash"), window.splash, self.shown(window), window.focus), ("", False, ["One"], GRID))
        self.assertEqual(seen, self.COLD)
        self.assertNotIn("splash", window._timers, "the cap is cancelled with the splash")

    def test_a_warm_start_never_has_a_splash_fresh_or_stale(self):
        for name, age in (("fresh", 0), ("stale", P.PAGE_TTL + 1)):
            page_cache.drop(P.namespace("p1"))
            Fake.now = self.T0
            self.rec(vid(1, "One"))
            self.open().stop()
            Fake.now = self.T0 + age
            window, seen = self.start()
            self.assertEqual((self.shown(window), window.mode, window.focus), (["One"], D.DATA, GRID), name)   # before onInit returned
            self.assertEqual((window.getProperty("splash"), window.splash, "splash" in window._timers), ("", False, False), name)
            if name == "stale":
                self.finish(window)
            time.sleep(0.05)
            self.assertEqual(seen, [""], name)
            window.stop()

    def test_a_first_load_that_ends_in_a_card_drops_the_splash_and_shows_the_card(self):
        error = {"id": 1, "error": {"code": 1, "message": "boom"}}
        for name, mode, world in (("error", D.ERROR, lambda: self.site.routes.update({self.REC: error})),
                                  ("refused", D.UNAVAILABLE, lambda: self.site.routes.update({self.REC: INVALID})),
                                  ("empty", D.EMPTY, lambda: self.site.routes.update({self.REC: answer()})),
                                  ("signin", D.SIGNIN, lambda: setattr(Fake, "signed", False)),
                                  ("needkey", D.NEEDKEY, lambda: (setattr(Fake, "signed", False), setattr(Fake, "keys", False)))):
            Fake.signed, Fake.keys = True, True
            self.site.routes.pop(self.REC, None)
            world()
            window, seen = self.start()
            self.finish(window)
            self.assertEqual(window.mode, mode, name)
            self.assertEqual((seen, window.getProperty("splash"), window.splash), (self.COLD, "", False), name)
            self.assertTrue(window.getProperty("msg_title"), name)
            self.assertEqual(window.focus, ACTION if window.getProperty("action") else RAIL, name)
            window.stop()

    def test_the_splash_is_dropped_after_the_cap_whatever_the_load_does(self):
        self.rec(vid(1, "One"))
        self.site.held[self.REC] = hold = threading.Event()
        window, seen = self.start()
        timer = window._timers["splash"]
        timer.cancel()                                                         # not the 15 s: what the timer then runs
        timer.function(*timer.args)
        self.assertEqual((window.getProperty("splash"), window.mode, window.getProperty("msg_title")), ("", D.LOADING, "Loading…"))
        self.assertEqual(window.focus, RAIL, "the Loading card has no button: the focus is where the window had it")
        hold.set()                                                             # the answer that comes later is shown as always
        self.finish(window)
        self.assertEqual((self.shown(window), window.focus, seen), (["One"], GRID, self.COLD))

    def test_the_cap_is_a_timer_of_the_window_and_stops_with_it(self):
        self.site.held[self.REC] = hold = threading.Event()
        with mock.patch.object(youtube_app, "SPLASH_CAP", 0.05):
            window, seen = self.start()
            self.assertTrue(wait_for(lambda: window.getProperty("splash") == ""))
        self.assertEqual((window.mode, seen), (D.LOADING, self.COLD))
        window.stop()
        other, _ = self.start()
        timer = other._timers["splash"]
        other.stop()
        self.assertTrue(timer.finished.is_set(), "closing the window cancels the cap")
        hold.set()

    def test_back_and_home_during_the_splash_close_the_app(self):
        self.site.held[self.REC] = hold = threading.Event()
        window, seen = self.start()
        self.assertEqual(window.getProperty("splash"), "1")
        for action_id in youtube_app.ui.BACK_ACTIONS:
            window.closed = False
            self.press(window, action_id)
            self.assertTrue(window.closed, action_id)
        hold.set()

    def test_the_demo_has_no_splash_but_for_the_card_that_never_ends(self):
        for scenario in ("", "signin", "needkey", "empty", "error", "unavailable"):
            window, seen = self.start(demo=True, scenario=scenario)
            self.finish(window)
            self.assertEqual((seen, window.getProperty("splash"), window.warming), ([""], "", None), scenario)
            window.stop()
        window, seen = self.start(demo=True, scenario="loading")
        self.assertEqual((window.getProperty("splash"), window.mode, window.warming), ("1", D.LOADING, None))
        timer = window._timers["splash"]
        timer.cancel()
        timer.function(*timer.args)
        self.assertEqual((window.getProperty("splash"), window.mode, seen), ("", D.LOADING, self.COLD))

    def test_the_mode_is_set_before_onInit_returns_so_the_splash_of_an_unbuilt_window_comes_down(self):
        self.rec(vid(1, "One"))
        self.open().stop()                                                      # a warm start
        self.site.held[self.REC] = hold = threading.Event()
        window, _ = self.start()
        self.assertEqual((window.getProperty("mode"), window.getProperty("splash")), (D.DATA, ""))
        window.stop()
        page_cache.drop(P.namespace("p1"))                                      # a cold start
        window, _ = self.start()
        self.assertEqual((window.getProperty("mode"), window.getProperty("splash")), (D.LOADING, "1"))
        window.stop()
        for scenario in ("", "signin", "loading"):                              # the demo
            window, _ = self.start(demo=True, scenario=scenario)
            self.assertNotEqual(window.getProperty("mode"), "", scenario)
            window.stop()
        hold.set()

    def test_warming_begins_with_the_launch_and_still_waits_for_the_first_page(self):
        self.others()
        self.rec(vid(1, "R"))
        self.site.held[self.REC] = hold = threading.Event()
        window, _ = self.start()
        handle = window.warming
        self.assertTrue(handle is not None and handle.running, "begun with the splash up")
        time.sleep(0.5)
        self.assertEqual(self.site.asked(), [R, self.REC], "nothing competes with the window's own load")
        timer = window._timers["splash"]
        timer.cancel()
        timer.function(*timer.args)                                            # the splash is down, the Loading card is not
        time.sleep(0.5)
        self.assertEqual(self.site.asked(), [R, self.REC])
        hold.set()
        self.assertTrue(handle.wait(5))
        self.assertEqual(self.site.asked(), [R, self.REC, D.SECTIONS[1].route, LATER, D.SECTIONS[3].route,
                                              D.SECTIONS[4].route, D.SECTIONS[5].route])
        self.assertEqual([page_cache.get(P.namespace("p1"), "s:" + key) is not None for key in D.SECTION_KEYS[:6]], [True] * 6)

    def test_warming_goes_on_when_the_first_load_ends_in_a_card(self):
        error = {"id": 1, "error": {"code": 1, "message": "boom"}}
        for name, world, asked in (("error", lambda: self.site.routes.update({self.REC: error}), 7),
                                   ("empty", lambda: self.site.routes.update({self.REC: answer()}), 7),
                                   ("signin", lambda: setattr(Fake, "signed", False), 2)):      # signed out: only what needs no account
            Fake.signed = True
            self.site.calls.clear()
            self.others()
            world()
            window, seen = self.start()
            self.finish(window)
            self.assertEqual(seen, self.COLD, name)
            self.assertTrue(window.warming.wait(5), name)
            self.assertEqual(len(self.site.asked()), asked, (name, self.site.asked()))
            self.assertIn(D.SECTIONS[5].route, self.site.asked(), name)
            self.assertIsNotNone(page_cache.get(P.namespace("p1"), "s:trend"), name)
            window.stop()
            page_cache.drop(P.namespace("p1"))

    def test_warming_begins_on_a_warm_start_too(self):
        self.others()
        self.rec(vid(1, "R"))
        self.open().stop()
        self.site.calls.clear()
        window, seen = self.start()
        self.assertEqual((seen, self.shown(window)), ([""], ["R"]))
        self.assertTrue(window.warming is not None)
        self.assertTrue(window.warming.wait(5))


class Files(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.path.join(TMP, "addon_data"), ignore_errors=True)
        Fake.rpc.clear()

    def test_directory_and_play_calls_have_the_shape_json_rpc_wants(self):
        files.get_directory(R + "special/recommendations/")
        files.play(R + "play/?video_id=x")
        first, second = (json.loads(r) for r in Fake.rpc)
        self.assertEqual((first["method"], first["params"]["directory"]), ("Files.GetDirectory", R + "special/recommendations/"))
        self.assertEqual(first["params"]["properties"], D.PROPERTIES)
        self.assertEqual(first["params"]["sort"], {"method": "none"})
        self.assertEqual((second["method"], second["params"]), ("Player.Open", {"item": {"file": R + "play/?video_id=x"}}))
        with mock.patch.object(xbmc, "executeJSONRPC", return_value="not json"):
            self.assertEqual(files.get_directory(R), {})
        with mock.patch.object(xbmc, "executeJSONRPC", return_value="[1]"):
            self.assertEqual(files.get_directory(R), {})

    def test_signed_in_follows_the_current_profile(self):
        manager = os.path.join(TMP, "addon_data", "plugin.video.youtube", "access_manager.json")
        self.assertFalse(files.signed_in())                                       # no file: nobody is
        put(manager, json.dumps({"access_manager": {"current_user": "1", "users": {
            "0": {"name": "A", "refresh_token": "a|b|c|d"}, "1": {"name": "B", "refresh_token": ""}}}}))
        self.assertFalse(files.signed_in())
        put(manager, json.dumps({"access_manager": {"current_user": "0", "users": {"0": {"refresh_token": "a|b"}}}}))
        self.assertTrue(files.signed_in())
        with mock.patch.object(store.lib, "youtube_accounts", side_effect=OSError("gone")):
            self.assertIsNone(files.signed_in())

    def test_the_profile_name_is_the_current_ones_and_empty_when_it_cannot_be_told(self):
        manager = os.path.join(TMP, "addon_data", "plugin.video.youtube", "access_manager.json")
        self.assertEqual(files.profile_name(), "")
        put(manager, json.dumps({"access_manager": {"current_user": "1", "users": {
            "0": {"name": "Anna", "refresh_token": "a|b|c|d"}, "1": {"name": "Борис", "refresh_token": "a|b"}}}}))
        self.assertEqual(files.profile_name(), "Борис")
        with mock.patch.object(store.lib, "youtube_accounts", side_effect=OSError("gone")):
            self.assertEqual(files.profile_name(), "")

    def test_the_profile_name_is_the_one_of_the_phone_so_the_avatar_follows_the_channel(self):
        manager = os.path.join(TMP, "addon_data", "plugin.video.youtube", "access_manager.json")
        put(manager, json.dumps({"access_manager": {"current_user": "1", "users": {
            "0": {"name": "Default", "refresh_token": "a|b|c|d"}, "1": {"name": "Аккаунт 2", "refresh_token": "a|b|c|d"}}}}))
        titles = {"0": {"state": "unknown", "title": ""}, "1": {"state": "yes", "title": "Dmytro Hanzha"}}
        with mock.patch.object(store, "ytchannel", types.SimpleNamespace(peek=lambda pid: titles[pid])):
            self.assertEqual(files.profile_name(), "Dmytro Hanzha")
            self.assertEqual(profiles.initial(files.profile_name()), "D")
            put(manager, json.dumps({"access_manager": {"current_user": "0", "users": {
                "0": {"name": "Default", "refresh_token": "a|b|c|d"}}}}))
            self.assertEqual((files.profile_name(), profiles.initial(files.profile_name())), ("Основной", "О"))
        with mock.patch.object(store, "ytchannel", types.SimpleNamespace(peek=lambda pid: 1 / 0)):   # a look that breaks
            self.assertEqual(files.profile_name(), "Основной")
        with mock.patch.object(store, "ytchannel", None):
            self.assertEqual(files.profile_name(), "Основной")

    def test_the_profile_id_is_the_current_ones_empty_without_one_and_none_when_it_cannot_be_told(self):
        manager = os.path.join(TMP, "addon_data", "plugin.video.youtube", "access_manager.json")
        self.assertEqual(files.profile_id(), "")
        put(manager, json.dumps({"access_manager": {"current_user": "1", "users": {
            "0": {"name": "Anna", "refresh_token": "a|b|c|d"}, "1": {"name": "Борис", "refresh_token": "a|b"}}}}))
        self.assertEqual(files.profile_id(), "1")
        put(manager, json.dumps({"access_manager": {"current_user": "0", "users": {
            "0": {"name": "Anna", "refresh_token": "a|b|c|d"}, "1": {"name": "Борис", "refresh_token": "a|b"}}}}))
        self.assertEqual(files.profile_id(), "0")
        with mock.patch.object(store.lib, "youtube_accounts", side_effect=OSError("gone")):
            self.assertIsNone(files.profile_id())
            with mock.patch.object(files.ui, "log") as log:
                self.assertIsNone(files.profile_id(log=False))
                log.assert_not_called()

    def test_the_key_wizard_file_is_read_when_it_is_there_and_fresh(self):
        path = os.path.join(TMP, "run", "ytkeys.step.json")
        now = 1_800_000_000
        self.assertEqual(files.STEP_FILE, "/run/media-stick/ytkeys.step.json")
        self.assertIsNone(files.read_step(now, path))                                         # no file: no wizard
        body = {"step": 2, "total": 6, "title": "Проект", "hint": "Подсказка", "updated": now - 10}
        put(path, json.dumps(body, ensure_ascii=False))
        self.assertEqual(files.read_step(now, path), D.Step(2, 6, "Проект", "Подсказка"))
        put(path, json.dumps({**body, "step": 0}))
        self.assertIsNone(files.read_step(now, path))                                         # step 0: not started
        put(path, json.dumps({**body, "updated": now - 31 * 60}))
        self.assertIsNone(files.read_step(now, path))                                         # left behind
        put(path, json.dumps({"step": 4, "updated": now}))
        self.assertEqual(files.read_step(now, path), D.Step(4, 6, "", ""))                    # readable, no words
        for broken in ("", "{half", "[1]", "null", "12", '{"step": 2'):
            put(path, broken)
            self.assertIsNone(files.read_step(now, path), broken)
        with open(path, "wb") as f:
            f.write(b"\xff\xfe\x00{")
        self.assertIsNone(files.read_step(now, path))                                         # not even text
        os.remove(path)
        os.makedirs(path)
        self.assertIsNone(files.read_step(now, path))                                         # a folder where the file should be

    def test_the_phone_page_is_the_sweettv_look_and_never_raises(self):
        from resources.lib import sweettv_files
        with mock.patch.object(sweettv_files, "phone_page", return_value=("http://10.0.0.5/", "/tmp/q.png")):
            self.assertEqual(files.phone_page(), ("http://10.0.0.5/", "/tmp/q.png"))
        with mock.patch.object(sweettv_files, "phone_page", side_effect=RuntimeError("no network")):
            self.assertEqual(files.phone_page(), ("", ""))

    def test_directory_calls_pass_the_route_as_it_is_and_the_main_page_as_files(self):
        for route in (R, REAL_RECOMMENDATIONS, REAL_SUBSCRIPTIONS, R + "special/playlist/WL/", R + "channel/mine/playlists"):
            Fake.rpc.clear()
            files.get_directory(route)
            params = json.loads(Fake.rpc[0])["params"]
            self.assertEqual(params["directory"], route)                          # no slash added, no query dropped
            self.assertEqual(params["media"], "files" if route == R else "video", route)

    def test_the_key_file(self):
        path = os.path.join(TMP, "addon_data", "plugin.video.youtube", files.KEYS_FILE)
        self.assertFalse(files.keys_configured())                                 # none yet
        put(path, json.dumps({"keys": {"personal": {"api_key": "k", "client_id": "i", "client_secret": "s"}}}))
        self.assertTrue(files.keys_configured())
        put(path, json.dumps({"keys": {"personal": {"api_key": "", "client_id": "", "client_secret": ""}}}))
        self.assertFalse(files.keys_configured())
        put(path, "{half")
        self.assertIsNone(files.keys_configured())                                # cannot tell: no claim either way

    def test_the_personal_key_is_the_add_ons_settings_and_the_key_file_is_the_fallback(self):
        folder = os.path.join(TMP, "addon_data", "plugin.video.youtube")
        settings, keys = os.path.join(folder, files.SETTINGS_FILE), os.path.join(folder, files.KEYS_FILE)

        def xml(key="SECRET-K", ident="SECRET-I", secret="SECRET-S"):
            return ('<settings version="2"><setting id="youtube.setup_wizard" default="true">false</setting>'
                    f'<setting id="youtube.api.key">{key}</setting><setting id="youtube.api.id">{ident}</setting>'
                    f'<setting id="youtube.api.secret">{secret}</setting></settings>')
        logged = []
        with mock.patch.object(files.ui, "log", side_effect=lambda text, *a: logged.append(text)):
            self.assertFalse(files.keys_configured())                             # no files: no key
            put(settings, xml())
            self.assertTrue(files.keys_configured())
            for partial in (xml(key=""), xml(ident=""), xml(secret="")):
                put(settings, partial)
                self.assertFalse(files.keys_configured())                         # all three are needed
            put(settings, "<settings><setting id=\"youtube.api.key\">SECRET-K</setting>")
            self.assertIsNone(files.keys_configured())                            # not XML: cannot tell
            put(keys, json.dumps({"keys": {"personal": {"api_key": "SECRET-K", "client_id": "SECRET-I", "client_secret": "SECRET-S"}}}))
            self.assertTrue(files.keys_configured())                              # the old file still counts
            put(settings, xml())
            os.remove(keys)
            self.assertTrue(files.keys_configured())
            put(keys, "{\"keys\": {\"personal\": {\"api_key\": \"SECRET-K\"")
            self.assertTrue(files.keys_configured())                              # a key in one place is enough
            put(settings, xml(key=""))
            self.assertIsNone(files.keys_configured())
            with mock.patch("builtins.open", side_effect=PermissionError("no")):
                self.assertIsNone(files.keys_configured())
        for line in logged:
            self.assertFalse(any(value in str(line) for value in ("SECRET-K", "SECRET-I", "SECRET-S")), line)


# ---- the skin, the art and the entry points --------------------------------------------------

class Skin(unittest.TestCase):
    def tree(self, name="script-media-stick-youtube.xml"):
        return ET.parse(os.path.join(SKIN, name)).getroot()

    def test_well_formed_with_unique_ids_and_the_controls_the_python_uses(self):
        root = self.tree()
        self.assertEqual(root.tag, "window")
        ids = [c.get("id") for c in root.iter("control") if c.get("id")]
        self.assertEqual(len(ids), len(set(ids)))
        types_ = {int(c.get("id")): c.get("type") for c in root.iter("control") if c.get("id", "").isdigit()}
        self.assertEqual(types_, {RAIL: "list", AVATAR: "button", GRID: "panel", ACTION: "button", **{c: "button" for c in KIND_IDS}})

    def test_every_window_and_item_property_the_xml_reads_is_set_by_the_python(self):
        text = "".join(ET.tostring(self.tree(), encoding="unicode").split())
        window_props = set(re.findall(r"Window\.Property\((\w+)\)", text))
        item_props = set(re.findall(r"ListItem\.Property\((\w+)\)", text))
        card = C.card_props(D.parse_entry(vid(1)))
        self.assertLessEqual(item_props, set(card) | {"active", "icon"})
        self.assertLessEqual(set(card) - {"kind"}, item_props)                      # and every one of them is drawn
        window = youtube_app.YouTube()
        window.setup(demo=True, scenario="needkey")
        with mock.patch.object(files, "phone_page", return_value=("http://192.168.1.20/", "/tmp/qr.png")):
            window.onInit()
            try:
                self.assertTrue(wait_for(lambda: window.mode == D.NEEDKEY and window.getProperty("step") != ""))
                self.assertLessEqual(window_props, set(window._window_props))
                self.assertLessEqual({"mode", "msg_title", "msg_text", "action", "avatar", "avatar_color", "key_qr", "key_url",
                                      "step", "step_hint1", "step_hint2"}, window_props)
            finally:
                window.stop()

    def test_only_fonts_and_textures_the_launcher_already_has_and_no_animation(self):
        fonts = set()
        for name in ("script-media-stick-home.xml", "script-media-stick-remote.xml"):
            fonts |= {f.text for f in self.tree(name).iter("font")}
        root = self.tree()
        self.assertLessEqual({f.text for f in root.iter("font")}, fonts)
        for tag in ("texture", "texturefocus", "texturenofocus"):
            for node in root.iter(tag):
                if node.text and "$" not in node.text:                      # an empty texture is the point of nofocus
                    self.assertTrue(os.path.exists(os.path.join(MEDIA, node.text)), node.text)
                if node.get("fallback"):
                    self.assertTrue(os.path.exists(os.path.join(MEDIA, node.get("fallback"))), node.get("fallback"))
        self.assertEqual(list(root.iter("animation")), [])

    # -- what Kodi would show: a reader of the visibility conditions this skin uses (it fails on one it does not know) --

    ATOM = re.compile(r"(String\.IsEmpty|String\.IsEqual)\((Window|ListItem)\.Property\((\w+)\)(?:,(\w+))?\)|Control\.HasFocus\((\d+)\)")

    def holds(self, condition, window=None, item=None, focus=()):
        """Whether `condition` (!, + and | of String.IsEmpty, String.IsEqual and Control.HasFocus atoms) is true when the
        window has the properties `window`, the list item `item`, and the controls `focus` have the focus."""
        window, item = window or {}, item or {}
        for either in condition.split("|"):
            met = True
            for part in either.split("+"):
                part = part.strip()
                found = self.ATOM.fullmatch(part.lstrip("!"))
                self.assertIsNotNone(found, f"a condition this test cannot read: {part}")
                function, source, name, wanted, control = found.groups()
                if control:
                    truth = int(control) in focus
                else:
                    value = (window if source == "Window" else item).get(name, "")
                    truth = value == "" if function == "String.IsEmpty" else value == wanted
                met = met and (truth != part.startswith("!"))
            if met:
                return True
        return False

    def shown(self, parent, window=None, item=None, focus=(), clip=10 ** 6, top=0):
        """The controls inside `parent` that are shown (their own and their groups' conditions hold) and that start
        above `clip` px, as Kodi would draw them."""
        found = []
        for control in parent.findall("control"):
            visible = control.find("visible")
            offset = top + int(control.findtext("top", "0"))
            if (visible is not None and not self.holds(visible.text, window, item, focus)) or offset >= clip:
                continue
            found.append(control)
            if control.get("type") == "group":
                found += self.shown(control, window, item, focus, clip, offset)
        return found

    def pictures(self, parent, **kw):
        return sum(1 for c in self.shown(parent, **kw) if c.get("type") == "image")

    def worst(self, layout, control_id, clip):
        """The most pictures a list item can have in view, over every state of the item's properties and the focus."""
        names = sorted(set(re.findall(r"ListItem\.Property\((\w+)\)", " ".join(v.text for v in layout.iter("visible")))))
        return max(self.pictures(layout, item=dict(zip(names, values)), focus=focus, clip=clip)
                   for values in itertools.product(("", "x"), repeat=len(names)) for focus in ((), (control_id,)))

    def by_id(self, root, control_id):
        return next(c for c in root.iter("control") if c.get("id") == str(control_id))

    def test_the_pi_budget_is_the_pictures_in_view_at_the_worst_moment(self):
        root = self.tree()
        panel, rail = self.by_id(root, GRID), self.by_id(root, RAIL)
        width, height = int(panel.find("itemlayout").get("width")), int(panel.find("itemlayout").get("height"))
        columns, panel_height = int(panel.find("width").text) // width, int(panel.find("height").text)
        self.assertEqual((columns, panel_height // height), (4, 2))               # two whole rows ...
        self.assertGreater(panel_height % height, 0)                              # ... and the top of a third
        clips = [panel_height - row * height for row in range(-(-panel_height // height))]
        plain = [self.worst(panel.find("itemlayout"), GRID, clip) for clip in clips]
        focused = [self.worst(panel.find("focusedlayout"), GRID, clip) for clip in clips]
        self.assertEqual(plain, [2, 2, 1], "a thumbnail and a strip; the strip is below the screen in the third row")
        grid = columns * sum(plain) + max(f - p for f, p in zip(focused, plain))  # the ring is the focused card's extra
        items = len(D.SECTIONS)
        base = self.pictures(rail.find("itemlayout"), item={})
        marked = self.pictures(rail.find("itemlayout"), item={"active": "1"})
        under_focus = self.worst(rail.find("focusedlayout"), RAIL, 10 ** 6)
        sections = max((items - 2) * base + marked + under_focus, (items - 1) * base + under_focus)
        everything = {"mode": "data", "demo": "1", "avatar": "A", "notice": "Loading…", "avatar_color": "FF3E8EF7"}
        header = self.pictures(root.find("controls"), window=everything)
        self.assertEqual(header, 4, "mark, DEMO pill, avatar circle, loading pill")
        self.assertEqual(self.pictures(root.find("controls"), window={"mode": "data"}), 1)     # the mark
        total = sections + grid + header
        self.assertLessEqual(total, 34, f"rail {sections} + grid {grid} + header {header}")
        for mode in ("signin", "needkey", "empty", "error", "unavailable", "prompt", "loading"):    # no grid: far fewer
            states = {**everything, "mode": mode, "key_qr": "/tmp/q.png", "action": "Try again", "step": "Step 1 of 6"}
            self.assertLessEqual(sections + self.pictures(root.find("controls"), window=states) + 1, total - 10, mode)
        panel_art = [n for n in panel.iter("texture") if "ListItem.Art" in (n.text or "")]
        self.assertTrue(panel_art)
        for node in panel_art:
            self.assertEqual(node.get("background"), "true", "thumbnails load in the background")

    def test_the_focus_is_a_white_ring_with_bright_text_and_the_others_are_dimmer_with_no_white_card(self):
        root = self.tree()
        panel = self.by_id(root, GRID)
        for layout in (panel.find("itemlayout"), panel.find("focusedlayout")):
            for texture in (c.findtext("texture") for c in layout.iter("control") if c.get("type") == "image"):
                self.assertTrue(texture.startswith(("$INFO[ListItem.Art", "youtube-strip-", "youtube-ring")), texture)
        focused = panel.find("focusedlayout")
        item = {"title1": "A", "strip": "d096-000"}
        for focus, rings, title in (((GRID,), 1, "FFFFFFFF"), ((), 0, "B3FFFFFF")):
            shown = self.shown(focused, item=item, focus=focus)
            ring = [c for c in shown if c.findtext("texture") == "youtube-ring.png"]
            self.assertEqual(len(ring), rings, focus)
            for c in ring:
                self.assertEqual(c.findtext("colordiffuse"), "FFFFFFFF")
            titles = [c for c in shown if c.get("type") == "label" and "Property(title" in c.findtext("label")]
            self.assertEqual({c.findtext("label") for c in titles},
                             {"$INFO[ListItem.Property(title1)]", "$INFO[ListItem.Property(title2)]"}, focus)
            self.assertEqual({c.findtext("textcolor") for c in titles}, {title}, focus)
        plain = [c for c in self.shown(panel.find("itemlayout"), item=item) if c.get("type") == "label"
                 and "Property(title" in c.findtext("label")]
        self.assertEqual({c.findtext("textcolor") for c in plain}, {"B3FFFFFF"})

    def test_every_list_label_sets_selectedcolor_as_well_as_textcolor_and_a_white_fill_has_black_text(self):
        root = self.tree()
        for lst in (c for c in root.iter("control") if c.get("type") in ("list", "panel")):
            for layout in list(lst.findall("itemlayout")) + list(lst.findall("focusedlayout")):
                labels = [c for c in layout.iter("control") if c.get("type") in ("label", "textbox")]
                self.assertTrue(labels)
                for label in labels:
                    self.assertIsNotNone(label.find("selectedcolor"), (lst.get("id"), layout.tag, label.findtext("label")))
                    self.assertEqual(label.findtext("selectedcolor"), label.findtext("textcolor"))
        rail = self.by_id(root, RAIL)
        for item in ({}, {"active": "1"}):
            for focus in ((), (RAIL,)):
                for layout in (rail.find("itemlayout"), rail.find("focusedlayout")):
                    shown = self.shown(layout, item=item, focus=focus)
                    fills = [c for c in shown if c.findtext("texture") == "youtube-pill.png"]
                    white = [c for c in fills if c.findtext("colordiffuse") == "FFFFFFFF"]
                    for label in (c for c in shown if c.get("type") == "label"):
                        colour = label.findtext("textcolor")
                        if white:                                                  # on a white pill: dark text, dark icon
                            self.assertTrue(all(int(colour[i:i + 2], 16) <= 0x60 for i in (2, 4, 6)), (item, focus, colour))
                            icons = [c for c in shown if "youtube-icon-" in c.findtext("texture", "")]
                            self.assertEqual({c.findtext("colordiffuse") for c in icons}, {"FF000000"})
                        else:
                            self.assertTrue(all(int(colour[i:i + 2], 16) >= 0xB0 for i in (2, 4, 6)), (item, focus, colour))
        focused_item = self.shown(rail.find("focusedlayout"), focus=(RAIL,))
        self.assertEqual(sum(1 for c in focused_item if c.findtext("colordiffuse") == "FFFFFFFF"), 1)     # the pill
        button = self.by_id(root, ACTION)
        self.assertEqual((button.findtext("focusedcolor"), button.find("texturefocus").get("colordiffuse")), ("FF000000", "FFFFFFFF"))
        for text in re.findall(r"colordiffuse[^>]*>([0-9A-Fa-f]{8})<", ET.tostring(root, encoding="unicode")):
            self.assertNotEqual(text.upper(), "00000000", "that is white in Kodi")
        self.assertEqual(root.findtext("backgroundcolor"), "0xff0f0f0f")

    def test_a_card_is_a_rounded_picture_two_title_lines_and_two_grey_lines_cut_in_python(self):
        root = self.tree()
        self.assertEqual(list(root.iter("wrapmultiline")), [], "a label in a list takes no wrapmultiline")
        panel = self.by_id(root, GRID)
        size = lambda control: int(re.search(r"\d+", control.findtext("font")).group())      # noqa: E731
        for layout in (panel.find("itemlayout"), panel.find("focusedlayout")):
            self.assertEqual([c for c in layout.iter("control") if c.get("type") == "textbox"], [], "no textbox in a card")
            thumb = next(c for c in layout.iter("control") if "ListItem.Art" in c.findtext("texture", ""))
            self.assertEqual(thumb.find("texture").get("fallback"), "youtube-nothumb.png")
            self.assertEqual(thumb.find("texture").get("diffuse"), "youtube-mask.png")      # rounded corners, no box behind
            self.assertEqual(thumb.findtext("aspectratio"), "scale")
            self.assertEqual(thumb.find("aspectratio").get("scalediffuse"), "false")
            self.assertEqual((int(thumb.findtext("width")), int(thumb.findtext("height"))), (352, 198))     # 16:9
            labels = {re.search(r"Property\((\w+)\)", c.findtext("label")).group(1): c for c in layout.iter("control")
                      if c.get("type") == "label" and "ListItem.Property(" in c.findtext("label")}
            self.assertLessEqual({"title1", "title2", "meta", "meta2", "badge"}, set(labels))
            for key, limit, font in (("title1", C.TITLE_WIDTH, C.TITLE_SIZE), ("title2", C.TITLE_WIDTH, C.TITLE_SIZE),
                                     ("meta", C.META_WIDTH, C.META_SIZE), ("meta2", C.META_WIDTH, C.META_SIZE)):
                label = labels[key] if layout.tag == "itemlayout" else next(
                    c for c in layout.iter("control") if f"Property({key})" in c.findtext("label", ""))
                self.assertGreaterEqual(int(label.findtext("width")), limit, key)        # the cut text fits its label
                self.assertEqual(size(label), font, key)                                 # and the estimate is for this font
                self.assertGreaterEqual(int(label.findtext("height")), int(font * 1.2), key)
                self.assertGreaterEqual(int(label.findtext("top")), int(thumb.findtext("top")) + 198, key)   # below the picture
            self.assertEqual(size(labels["title1"]), 28)                               # Medium ~26-28 px, as on YouTube
            self.assertLessEqual(int(labels["title1"].findtext("top")) + 2 * 34, int(labels["meta"].findtext("top")) + 8)
            badge = labels["badge"]
            self.assertEqual((size(badge), badge.findtext("align")), (C.BADGE_SIZE, "right"))
            self.assertEqual(int(badge.findtext("width")), max(C.BADGE_WIDTHS))
            self.assertLessEqual(int(badge.findtext("left")) + int(badge.findtext("width")), 16 + 352)   # inside the picture
        self.assertEqual(root.findtext(".//control[@id='300']/font"), "Med32")

    def test_the_strip_and_the_picture_have_the_size_of_the_files_they_show(self):
        root = self.tree()
        panel = self.by_id(root, GRID)
        for layout in (panel.find("itemlayout"), panel.find("focusedlayout")):
            strip = next(c for c in layout.iter("control") if c.findtext("texture", "").startswith("youtube-strip-"))
            thumb = next(c for c in layout.iter("control") if "ListItem.Art" in c.findtext("texture", ""))
            self.assertEqual(strip.findtext("visible"), "!String.IsEmpty(ListItem.Property(strip))")
            wanted = (int(strip.findtext("width")), int(strip.findtext("height")))
            self.assertEqual(wanted, (int(thumb.findtext("width")), 52))
            for key in {C.strip_key(*variant) for variant in C.strip_variants()}:
                self.assertEqual(self.png_size(os.path.join(MEDIA, f"youtube-strip-{key}.png")), wanted, key)
            for name in ("youtube-mask.png", "youtube-nothumb.png"):
                self.assertEqual(self.png_size(os.path.join(MEDIA, name)), (352, 198), name)
        for section in D.SECTIONS:
            self.assertTrue(os.path.isfile(os.path.join(MEDIA, f"youtube-icon-{section.key}.png")), section.key)
            self.assertEqual(self.png_size(os.path.join(MEDIA, f"youtube-icon-{section.key}.png")), (40, 40))

    @staticmethod
    def png_size(path):
        with open(path, "rb") as f:
            head = f.read(24)
        assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")

    def test_a_nine_slice_picture_and_the_control_it_fills_are_at_least_twice_the_border(self):
        root = self.tree()
        parents = {child: parent for parent in root.iter() for child in parent}
        found = 0
        for tag in ("texture", "texturefocus", "texturenofocus"):
            for node in root.iter(tag):
                border = node.get("border")
                if not border:
                    continue
                found += 1
                edge = max(int(part) for part in border.split(","))
                self.assertNotIn("$", node.text)
                width, height = self.png_size(os.path.join(MEDIA, node.text))
                self.assertGreaterEqual(min(width, height), 2 * edge, f"{node.text}: the picture is smaller than two borders")
                control = parents[node]
                size = (int(control.findtext("width")), int(control.findtext("height")))
                self.assertGreaterEqual(min(size), 2 * edge, f"{node.text}: the control is smaller than two borders {size}")
        self.assertGreaterEqual(found, 8)

    def test_the_rail_has_room_for_every_section(self):
        rail = self.by_id(self.tree(), RAIL)
        self.assertGreaterEqual(int(rail.find("height").text), len(D.SECTIONS) * int(rail.find("itemlayout").get("height")))
        self.assertGreaterEqual(int(rail.findtext("width")), 260)                          # about 260 px, with the margins

    def test_the_search_types_are_a_row_of_four_pills_at_the_top_shown_with_the_search_only(self):
        root = self.tree()
        header = root.find("controls")
        buttons = [self.by_id(root, c) for c in KIND_IDS]
        self.assertEqual([b.findtext("label") for b in buttons], [k.name for k in D.KINDS])      # the labels are the data's
        search = {"mode": "data", "search": "1", "kind": "channel"}
        self.assertEqual([c.get("id") for c in self.shown(header, window=search) if c.get("id") in map(str, KIND_IDS)],
                         [str(c) for c in KIND_IDS])
        for window in ({"mode": "data"}, {"mode": "data", "kind": "channel"}, {"mode": "empty", "action": "Search"}):
            self.assertFalse([c for c in self.shown(header, window=window) if c.get("id") in map(str, KIND_IDS)], window)
        for kind in D.KIND_KEYS:                                                                  # one pill marks the chosen type
            marks = [c for c in self.shown(header, window={"mode": "data", "search": "1", "kind": kind})
                     if c.get("type") == "image" and c.findtext("colordiffuse") == "26FFFFFF"]
            self.assertEqual(len(marks), 1, kind)
            index = D.KIND_KEYS.index(kind)
            self.assertEqual(marks[0].findtext("left"), buttons[index].findtext("left"), kind)
        self.assertEqual(len([c for c in self.shown(header, window={"mode": "data", "search": "1"}) if c.get("type") == "image"
                              and c.findtext("colordiffuse") == "26FFFFFF"]), 0)                  # no type known: none marked
        for a, b in zip(buttons, buttons[1:]):                                                    # in a row, apart, left to right
            self.assertEqual(a.findtext("top"), b.findtext("top"))
            self.assertGreaterEqual(int(b.findtext("left")), int(a.findtext("left")) + int(a.findtext("width")) + 8)
        demo_mark = next(g for g in header.findall("control") if (g.findtext("visible") or "").startswith("!String.IsEmpty(Window.Property(demo))"))
        title = next(c for c in header.findall("control") if c.findtext("label") == "$INFO[Window.Property(title)]")
        logo = next(c for c in header.findall("control") if c.findtext("label") == "YouTube")
        last = buttons[-1]
        self.assertLessEqual(int(last.findtext("left")) + int(last.findtext("width")), int(demo_mark.findtext("left")))
        self.assertGreaterEqual(int(buttons[0].findtext("left")), int(logo.findtext("left")) + int(logo.findtext("width")))
        for button in buttons:
            self.assertLessEqual(int(button.findtext("top")) + int(button.findtext("height")), int(title.findtext("top")))   # above the title
            self.assertEqual((button.findtext("textcolor"), button.findtext("focusedcolor")), ("FFFFFFFF", "FF000000"))
            self.assertEqual(button.find("texturefocus").get("colordiffuse"), "FFFFFFFF")        # as the rail: white pill, black text
            nofocus = button.find("texturenofocus")                                               # else Kodi draws its own dark oval
            self.assertIsNotNone(nofocus, button.get("id"))
            self.assertEqual((nofocus.text or "").strip(), "", button.get("id"))
            self.assertEqual(nofocus.attrib, {}, button.get("id"))
            self.assertEqual(button.findtext("font"), "Reg25")
        self.assertEqual([b.findtext("onleft") for b in buttons], ["100", "401", "402", "403"])    # Left of the first is the rail
        self.assertEqual([b.findtext("onright") for b in buttons], ["402", "403", "404", str(AVATAR)])   # Right of the last is the circle
        rail = self.by_id(root, RAIL)
        self.assertLess(int(rail.findtext("left")) + int(rail.findtext("width")), int(buttons[0].findtext("left")))

    def test_up_from_the_first_row_and_from_the_card_is_the_skins_since_the_base_window_moves_before_python_does(self):
        root = self.tree()
        for control in (GRID, ACTION):
            ups = [(up.get("condition"), up.text) for up in self.by_id(root, control).findall("onup")]
            self.assertEqual(ups, [(f"String.IsEqual(Window.Property(kind),{key})", str(button)) for key, button in zip(D.KIND_KEYS, KIND_IDS)]
                             + [("!String.IsEmpty(Window.Property(avatar))", str(AVATAR))], control)      # no search row: the circle

    def goes(self, root, control, direction, window):
        """Where the base navigation of Kodi sends the focus from `control` on `direction` (up, down, left, right): the first
        on... tag whose condition holds; None when there is none (the focus stays)."""
        for node in self.by_id(root, control).findall("on" + direction):
            if node.get("condition") is None or self.holds(node.get("condition"), window):
                return int(node.text)
        return None

    def test_the_circle_is_a_button_reached_by_the_skin_from_the_rail_the_grid_the_card_and_the_search_row(self):
        root = self.tree()
        button = self.by_id(root, AVATAR)
        self.assertEqual(button.get("type"), "button")
        self.assertEqual(button.findtext("visible"),                                  # drawn with the circle only, and not under the splash
                         "!String.IsEmpty(Window.Property(avatar))+String.IsEmpty(Window.Property(splash))+!String.IsEmpty(Window.Property(mode))")
        circle = next(g for g in root.find("controls").findall("control") if g.findtext("left") == "1808" and g.get("type") == "group")
        box = [int(button.findtext(k)) for k in ("left", "top", "width", "height")]
        around = [int(circle.findtext(k)) for k in ("left", "top", "width", "height")]
        self.assertEqual((box[0] + box[2] // 2, box[1] + box[3] // 2), (around[0] + around[2] // 2, around[1] + around[3] // 2))
        self.assertGreater(box[2], around[2])                                       # a ring round the circle, not under it
        controls = list(root.find("controls"))
        self.assertLess(controls.index(button), controls.index(circle))             # drawn under the circle
        self.assertLessEqual(box[0] + box[2], 1920)
        self.assertEqual((button.find("texturenofocus").text or "").strip(), "")    # nothing drawn until it has the focus
        self.assertEqual(button.find("texturefocus").get("colordiffuse"), "FFFFFFFF")
        plain = {"mode": "data", "avatar": "A"}
        for control in (RAIL, GRID):
            self.assertEqual(self.goes(root, control, "up", plain), AVATAR, control)
        self.assertEqual(self.goes(root, ACTION, "up", {"mode": "signin", "avatar": "?", "action": "Sign in"}), AVATAR)
        self.assertIsNone(self.goes(root, GRID, "up", {"mode": "data"}), "no circle yet: nothing above the grid")
        self.assertEqual(self.goes(root, AVATAR, "left", plain), RAIL)
        self.assertEqual(self.goes(root, AVATAR, "down", plain), GRID)
        self.assertEqual(self.goes(root, AVATAR, "down", {"mode": "signin", "action": "Sign in"}), ACTION)
        self.assertEqual(self.goes(root, AVATAR, "down", {"mode": "loading"}), RAIL)
        self.assertEqual(self.goes(root, AVATAR, "down", {"mode": "needkey", "action": "Try again"}), ACTION)
        # a search keeps its row of types above the results and the button of the card; the circle is Right of the last type
        search = {"mode": "data", "avatar": "A", "search": "1", "kind": "channel"}
        self.assertEqual(self.goes(root, GRID, "up", search), 402)
        self.assertEqual(self.goes(root, ACTION, "up", {**search, "mode": "empty", "action": "New search"}), 402)
        self.assertEqual(self.goes(root, 404, "right", search), AVATAR)
        self.assertEqual(self.goes(root, AVATAR, "left", search), 404)
        self.assertEqual(self.goes(root, AVATAR, "down", search), GRID)
        folder_of_search = {"mode": "data", "avatar": "A", "kind": ""}               # no row of types there: the circle is above
        self.assertEqual(self.goes(root, GRID, "up", folder_of_search), AVATAR)

    def test_the_row_of_types_fits_the_pi_budget(self):
        root = self.tree()
        window = {"mode": "data", "demo": "1", "avatar": "A", "notice": "Loading…", "avatar_color": "FF3E8EF7", "search": "1", "kind": "live"}
        self.assertEqual(self.pictures(root.find("controls"), window=window), 5, "mark, DEMO pill, avatar circle, loading pill, the chosen type")
        plain = self.pictures(root.find("controls"), window={"mode": "data"})
        self.assertEqual(plain, 1)
        self.assertEqual(self.pictures(root.find("controls"), window={"mode": "data", "search": "1", "kind": "video"}), 2)

    def test_the_key_card_has_the_qr_the_step_block_and_room_for_russian(self):
        root = self.tree()
        group = next(g for g in root.iter("control") if g.get("type") == "group" and g.findtext("visible") ==
                     "String.IsEqual(Window.Property(mode),needkey)")
        labels = {c.findtext("label"): c for c in group.iter("control") if c.get("type") == "label"}
        for key in ("step", "step_hint1", "step_hint2"):
            label = labels[f"$INFO[Window.Property({key})]"]
            self.assertGreaterEqual(int(label.findtext("width")), C.STEP_WIDTH, key)
            self.assertEqual(int(re.search(r"\d+", label.findtext("font")).group()), C.STEP_SIZE if key == "step" else C.HINT_SIZE)
        qr = next(c for c in group.iter("control") if c.findtext("texture") == "$INFO[Window.Property(key_qr)]")
        self.assertEqual((qr.findtext("width"), qr.findtext("height"), qr.findtext("aspectratio")), ("300", "300", "keep"))
        qr_group = next(g for g in group.iter("control") if g.findtext("visible") == "!String.IsEmpty(Window.Property(key_qr))")
        self.assertIn(qr, list(qr_group.iter("control")))                                # no QR: no white plate either
        block = next(g for g in group.iter("control") if g.findtext("visible") == "!String.IsEmpty(Window.Property(step))")
        self.assertEqual(len([c for c in block.iter("control") if c.get("type") == "label"]), 3)
        # the fonts the card uses are the launcher's, which already show the phone page's Russian (see sweettv_text)
        self.assertEqual({c.findtext("font") for c in block.iter("control") if c.get("type") == "label"}, {"Med32", "Reg25"})

    def test_the_art_the_screen_needs_is_there_and_small(self):
        self.assertTrue(os.path.getsize(os.path.join(MEDIA, "youtube-nothumb.png")) < 4000)
        for n in range(1, demo.THUMBS + 1):
            path = os.path.join(ADDON, "resources", "media", "demo", f"yt-thumb-{n}.png")
            self.assertTrue(os.path.exists(path), path)
            self.assertLess(os.path.getsize(path), 20000, path)
            width, height = self.png_size(path)
            self.assertEqual((width * 9, width >= 352), (height * 16, True), path)          # 16:9, not smaller than the card's picture
        for name in os.listdir(MEDIA):
            if name.startswith("youtube-"):
                self.assertLess(os.path.getsize(os.path.join(MEDIA, name)), 6000, name)

    def test_the_splash_is_the_only_thing_shown_while_the_property_is_set_or_mode_is_not_yet_known(self):
        root = self.tree()
        top = root.find("controls").findall("control")
        splash = [c for c in top if c.findtext("visible") == "!String.IsEmpty(Window.Property(splash))|String.IsEmpty(Window.Property(mode))"]
        self.assertEqual(len(splash), 1)
        calm = "String.IsEmpty(Window.Property(splash))+!String.IsEmpty(Window.Property(mode))"
        for control in top:
            if control is not splash[0]:
                condition = control.findtext("visible") or ""
                self.assertTrue(condition == calm or condition.endswith("+" + calm), (control.get("id"), condition))
        for mode, splashing, search, avatar, demo_mark, notice, action in itertools.product(
                ("", "data", "signin", "loading", "needkey"), ("", "1"), ("", "1"), ("", "A"), ("", "1"), ("", "x"), ("", "Try again")):
            window = {"mode": mode, "splash": splashing, "search": search, "avatar": avatar, "demo": demo_mark, "notice": notice,
                      "action": action, "kind": "video", "key_qr": "/tmp/q.png", "step": "Step 1 of 6"}
            shown = self.shown(root.find("controls"), window=window)
            if mode == "" or splashing:                       # the window just built, or the load of a cold start: the splash alone
                self.assertEqual(set(shown), set(splash[0].iter("control")), window)
                self.assertEqual([c.get("id") for c in shown if c.get("id")], [], "nothing in it takes the focus")
                self.assertEqual([c.get("type") for c in shown].count("image"), 1, window)
            else:
                self.assertNotIn(splash[0], shown, window)
        mark = next(c for c in splash[0].iter("control") if c.get("type") == "image")
        logo = next(c for c in top if c.get("type") == "image")
        self.assertEqual((mark.findtext("texture"), logo.findtext("texture")), ("youtube-splash.png", "youtube-mark.png"))
        self.assertGreaterEqual(int(mark.findtext("width")), 2 * int(logo.findtext("width")))         # larger than the top bar's
        size = (int(mark.findtext("width")), int(mark.findtext("height")))
        picture = self.png_size(os.path.join(MEDIA, "youtube-splash.png"))
        self.assertEqual(picture[0] * size[1], picture[1] * size[0], "the picture has the control's proportions")
        self.assertGreaterEqual(picture[0], size[0], "drawn for this size, not a smaller one stretched")
        self.assertEqual(int(mark.findtext("left")) + int(mark.findtext("width")) // 2, 960)        # centred on 1920 x 1080
        labels = {c.findtext("label"): c for c in splash[0].iter("control") if c.get("type") == "label"}
        self.assertEqual(set(labels), {"YouTube", "Loading…"})
        for label in labels.values():
            self.assertEqual(int(label.findtext("left")) + int(label.findtext("width")) // 2, 960)
            self.assertEqual(label.findtext("align"), "center")
        for window in ({"mode": "data", "splash": "1"}, {}, {"avatar": "A", "demo": "1"}):
            self.assertEqual(self.pictures(root.find("controls"), window=window), 1, window)
        self.assertEqual(self.pictures(root.find("controls"), window={"mode": "data"}), 1, "and without it: the mark of the top bar")

    def test_demo_is_marked_on_screen(self):
        text = ET.tostring(self.tree(), encoding="unicode")
        self.assertIn("DEMO", text)
        self.assertIn("Window.Property(demo)", text)


class EntryPoints(unittest.TestCase):
    def setUp(self):
        Fake.builtins.clear()

    def run_default(self, argv, main=None):
        Fake.builtins.clear()
        with mock.patch.object(sys, "argv", ["default.py"] + argv), \
                mock.patch.object(youtube_app, "main", **(main or {"return_value": True})) as app:
            with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})
        return app, list(Fake.builtins)

    def test_open_and_demo_go_to_the_app(self):
        app, builtins = self.run_default(["youtube", "open"])
        app.assert_called_once_with(["open"])
        self.assertEqual(builtins, [])
        app, _ = self.run_default(["youtube", "demo", "needkey"])
        app.assert_called_once_with(["demo", "needkey"])
        app, _ = self.run_default(["youtube"])
        app.assert_called_once_with([])

    def test_a_broken_app_falls_back_to_the_plain_add_on_but_a_broken_demo_does_not(self):
        _, builtins = self.run_default(["youtube", "open"], {"side_effect": RuntimeError("no skin")})
        self.assertEqual(builtins, ["RunAddon(plugin.video.youtube)"])
        _, builtins = self.run_default(["youtube", "demo"], {"side_effect": RuntimeError("no skin")})
        self.assertEqual(builtins, [])

    def test_the_card_on_home_opens_the_app_after_the_accounts_step(self):
        profile = {"id": "0", "name": "Default", "current": True, "tokens": 4, "signed_in": True}
        for signed in (True, False):                                              # one profile: even signed out it opens, anonymous
            Fake.builtins.clear()
            with mock.patch.object(store.lib, "accounts", return_value=[
                    {"service": "youtube", "name": "YouTube", "profiles": [{**profile, "signed_in": signed}],
                     "signed_in": signed, "signin": None}]):
                accounts.launch_app("plugin.video.youtube")
            self.assertEqual(Fake.builtins, ["RunScript(script.media-stick.home,youtube,open)"])
        self.assertIn("plugin.video.youtube", apps.load_recent())                 # still counted as used

    def test_the_other_apps_keep_their_launch(self):
        Fake.builtins.clear()
        apps.launch("plugin.video.other")
        apps.launch("webapp:netflix")
        self.assertEqual(Fake.builtins, ["RunAddon(plugin.video.other)", "RunScript(script.media-stick.webapp,netflix)"])
        self.assertEqual(apps.OWN_SCREENS["plugin.video.sweettv"], "RunScript(script.media-stick.home,sweettv,open)")


class NoChannel(WindowCase):
    """A Google account with no YouTube channel: the add-on answers "Channel not found" to every "mine" request, so the
    sections of the account are empty. The card says why when mediastick_ytchannel knows ("no"), never otherwise."""
    ACCOUNT = ("subs", "later", "lists")
    CARD = ("No YouTube channel", "This Google account has no YouTube channel, so this is empty. Create one in the YouTube "
            "app on your phone (avatar → Create channel), or add another Google account on the phone remote.")

    def setUp(self):
        super().setUp()
        self.state = ["no"]
        patch = mock.patch.object(files, "channel_state", side_effect=lambda: self.state[0])
        patch.start()
        self.addCleanup(patch.stop)

    def card(self, window):
        return window.getProperty("msg_title"), window.getProperty("msg_text")

    def test_the_sections_of_the_account_say_there_is_no_channel(self):
        window = self.open()
        for key in self.ACCOUNT:
            self.go(window, key)
            self.assertTrue(wait_for(lambda: window.view.key == key and window.mode == D.EMPTY), key)
            self.assertEqual(self.card(window), self.CARD, key)
            self.assertEqual(window.getProperty("action"), "Try again")

    def test_recommendations_history_trending_and_search_stay_as_they_are(self):
        window = self.open()
        for key in ("history", "trend"):
            self.go(window, key)
            self.assertTrue(wait_for(lambda: window.view.key == key and window.mode == D.EMPTY), key)
            self.assertNotEqual(self.card(window)[0], "No YouTube channel", key)
            self.assertEqual(self.card(window)[1], D.EMPTY_TEXT[key])
        self.rec(vid(1, "One"))
        self.go(window, "rec")
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(self.shown(window), ["One"])

    def test_a_channel_or_an_unknown_answer_changes_nothing(self):
        for state in ("yes", "unknown", ""):
            self.state[0] = state
            window = self.open()
            self.go(window, "subs")
            self.assertTrue(wait_for(lambda: window.view.key == "subs" and window.mode == D.EMPTY), state)
            self.assertEqual(self.card(window), ("Nothing here", D.EMPTY_TEXT["subs"]), state)

    def test_a_section_that_has_videos_shows_them_whatever_the_state(self):
        self.site.routes[D.SECTIONS[1].route] = answer(vid(5, "Mine"))
        window = self.open()
        self.go(window, "subs")
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(self.shown(window), ["Mine"])

    def test_signed_out_and_no_key_cards_come_first(self):
        Fake.signed = False
        window = self.open()
        self.assertEqual((window.mode, window.getProperty("msg_title")), (D.SIGNIN, "Sign in to see your videos"))
        Fake.signed, Fake.keys = True, False
        window = self.open()
        self.assertEqual(window.mode, D.NEEDKEY)

    def test_the_demo_never_says_it(self):
        window = self.open(demo=True)
        self.assertEqual(window.channel, "unknown")

    def test_an_answer_that_comes_later_changes_the_card_and_a_wrong_section_is_left_alone(self):
        self.state[0] = "unknown"
        with mock.patch.object(youtube_app, "CHANNEL_RECHECK", 0.02):
            window = self.open()
            self.go(window, "later")
            self.assertTrue(wait_for(lambda: window.view.key == "later" and window.mode == D.EMPTY))
            self.assertEqual(self.card(window), ("Nothing here", D.EMPTY_TEXT["later"]))
            self.state[0] = "no"
            self.assertTrue(wait_for(lambda: self.card(window) == self.CARD), "the card was not updated")
            self.go(window, "history")
            self.assertTrue(wait_for(lambda: window.view.key == "history" and window.mode == D.EMPTY))
            self.assertEqual(self.card(window)[1], D.EMPTY_TEXT["history"])

    def test_an_answer_that_is_still_unknown_is_asked_a_few_times_and_then_left(self):
        self.state[0] = "unknown"
        asked = []
        with mock.patch.object(youtube_app, "CHANNEL_RECHECK", 0.01),                 mock.patch.object(files, "channel_state", side_effect=lambda: asked.append(1) or "unknown"):
            window = self.open()
            self.go(window, "subs")
            self.assertTrue(wait_for(lambda: len(asked) >= youtube_app.CHANNEL_TRIES + 2))
            time.sleep(0.1)
        self.assertEqual(len(asked), youtube_app.CHANNEL_TRIES + 2)      # the two loads (Recommendations, Subscriptions), then each try
        self.assertEqual(self.card(window)[0], "Nothing here")


class MenuKey(WindowCase):
    """The remote's Menu key (ACTION_CONTEXT_MENU = 117): toggles focus between content and the section rail."""
    MENU = 117

    def menu_id(self):
        return getattr(youtube_app, "ACTION_CONTEXT_MENU", self.MENU)

    def test_constant_is_117_and_adjacent_actions_leave_focus_alone(self):
        self.assertEqual(getattr(youtube_app, "ACTION_CONTEXT_MENU", None), 117)
        self.rec(vid(1, "One"), vid(2, "Two"))
        window = self.open()
        for action_id in (116, 118, 7):
            window.focus = GRID
            self.press(window, action_id)
            self.assertEqual(window.focus, GRID, action_id)
            window.focus = RAIL
            self.press(window, action_id)
            self.assertEqual(window.focus, RAIL, action_id)

    def test_menu_key_toggles_between_grid_and_rail_and_swallows_action(self):
        self.rec(vid(1, "One"), vid(2, "Two"), vid(3, "Three"))
        mix = R + "playlist/PL1/"
        self.site.routes[D.SECTIONS[4].route] = answer(folder(mix, "Mix"))
        self.site.routes[mix] = answer(vid(9, "Inside"))
        window = self.open()
        window.controls[GRID].selected = 2
        with mock.patch.object(WindowXML, "onAction") as base:
            self.press(window, self.menu_id())
            self.assertEqual((window.focus, window.controls[GRID].selected), (RAIL, 2))
            base.assert_not_called()
            self.press(window, self.menu_id())
            self.assertEqual((window.focus, window.controls[GRID].selected), (GRID, 2))
            base.assert_not_called()
        self.go(window, "lists")
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Mix"]))
        window.focus = GRID
        window.controls[GRID].selected = 0
        window.onClick(GRID)
        self.assertTrue(wait_for(lambda: self.shown(window) == ["Inside"]))
        self.press(window, self.menu_id())
        self.assertEqual((window.focus, window.closed, self.shown(window), window.controls[RAIL].selected),
                         (RAIL, False, ["Inside"], 4))
        self.press(window, self.menu_id())
        self.assertEqual((window.focus, window.closed, self.shown(window)), (GRID, False, ["Inside"]))
        window.stop()

        demo_win = self.open(demo=True)
        self.assertEqual(demo_win.focus, GRID)
        self.press(demo_win, self.menu_id())
        self.assertEqual(demo_win.focus, RAIL)
        self.press(demo_win, self.menu_id())
        self.assertEqual(demo_win.focus, GRID)

    def test_menu_key_focuses_rail_from_buttons_and_returns_to_content(self):
        cards = (
            (D.SIGNIN, lambda: setattr(Fake, "signed", False)),
            (D.NEEDKEY, lambda: setattr(Fake, "keys", False)),
            (D.ERROR, lambda: self.site.routes.update({D.SECTIONS[0].route: {"error": {"code": -32100, "message": "boom"}}})),
            (D.UNAVAILABLE, lambda: self.site.routes.update({D.SECTIONS[0].route: INVALID})),
        )
        for mode, setup_world in cards:
            Fake.signed, Fake.keys = True, True
            self.site.routes.pop(D.SECTIONS[0].route, None)
            setup_world()
            window = self.open()
            self.assertEqual((window.mode, window.focus), (mode, ACTION), mode)
            self.press(window, self.menu_id())
            self.assertEqual(window.focus, RAIL, mode)
            self.press(window, self.menu_id())
            self.assertEqual(window.focus, ACTION, mode)
            if mode == D.SIGNIN:
                window.focus = AVATAR
                self.press(window, self.menu_id())
                self.assertEqual(window.focus, RAIL)
                self.press(window, self.menu_id())
                self.assertEqual(window.focus, ACTION)
            window.stop()

        Fake.signed, Fake.keys = True, True
        self.site.routes.pop(D.SECTIONS[0].route, None)
        empty_search = self.open(state={"section": "search", "query": "zzz"})
        self.assertEqual((empty_search.mode, empty_search.focus), (D.EMPTY, ACTION))
        self.press(empty_search, self.menu_id())
        self.assertEqual(empty_search.focus, RAIL)
        self.press(empty_search, self.menu_id())
        self.assertEqual(empty_search.focus, ACTION)
        empty_search.focus = KIND_IDS[0]
        self.press(empty_search, self.menu_id())
        self.assertEqual(empty_search.focus, RAIL)
        self.press(empty_search, self.menu_id())
        self.assertEqual(empty_search.focus, ACTION)
        empty_search.stop()

        prompt = self.open(wait=False, state={"section": "search", "query": ""})
        self.assertEqual((prompt.mode, prompt.focus), (D.PROMPT, ACTION))
        self.press(prompt, self.menu_id())
        self.assertEqual(prompt.focus, RAIL)
        self.press(prompt, self.menu_id())
        self.assertEqual(prompt.focus, ACTION)
        prompt.focus = KIND_IDS[0]
        self.press(prompt, self.menu_id())
        self.assertEqual(prompt.focus, RAIL)
        self.press(prompt, self.menu_id())
        self.assertEqual(prompt.focus, ACTION)
        prompt.stop()

        self.site.routes[D.search_route("cats", D.KIND_VIDEO)] = answer(vid(1, "Cat"))
        search = self.open(state={"section": "search", "query": "cats"})
        self.assertEqual(search.focus, GRID)
        for button in KIND_IDS:
            search.focus = button
            self.press(search, self.menu_id())
            self.assertEqual(search.focus, RAIL, button)
            self.press(search, self.menu_id())
            self.assertEqual(search.focus, GRID, button)
        search.stop()

        self.rec(vid(1, "One"))
        data_win = self.open(state={"section": D.DEFAULT_SECTION})
        data_win.focus = AVATAR
        self.press(data_win, self.menu_id())
        self.assertEqual(data_win.focus, RAIL)
        self.press(data_win, self.menu_id())
        self.assertEqual(data_win.focus, GRID)
        data_win.focus = 0
        self.press(data_win, self.menu_id())
        self.assertEqual(data_win.focus, RAIL)
        data_win.focus = 0
        real_get_focus = data_win.getFocusId

        def focus_or_raise():
            if data_win.focus == 0:
                raise RuntimeError("no control focused")
            return real_get_focus()

        with mock.patch.object(data_win, "getFocusId", side_effect=focus_or_raise):
            self.press(data_win, self.menu_id())
        self.assertEqual(data_win.focus, RAIL)

    def test_menu_key_from_avatar_on_card_without_button_focuses_rail_and_stays_there(self):
        self.rec(vid(1, "One"))
        hold = threading.Event()
        self.addCleanup(hold.set)
        self.site.held[D.SECTIONS[1].route] = hold
        window = self.open()
        window.focus = RAIL
        window.controls[RAIL].selected = 1
        window.onClick(RAIL)
        self.assertTrue(wait_for(lambda: window.mode == D.LOADING))
        self.assertEqual((window.splash, window.getProperty("action"), window.focus), (False, "", RAIL))
        window.focus = AVATAR
        self.press(window, self.menu_id())
        self.assertEqual(window.focus, RAIL)
        self.press(window, self.menu_id())
        self.assertEqual(window.focus, RAIL)
        hold.set()
        self.assertTrue(wait_for(lambda: window.loads >= 2))

    def test_menu_key_focuses_rail_without_waiting_on_ui_thread(self):
        self.rec(vid(1, "One"))
        window = self.open()
        looks = []

        def visible(cond):
            match = re.fullmatch(r"Control\.IsVisible\((\d+)\)", cond)
            if match:
                control_id = int(match.group(1))
                looks.append(control_id)
                return control_id != RAIL
            return True

        with mock.patch.object(xbmc, "getCondVisibility", visible), \
                mock.patch.object(xbmc, "sleep", side_effect=AssertionError("UI thread must not wait")):
            self.press(window, self.menu_id())
        self.assertEqual(looks, [RAIL])
        self.assertEqual(window.focus, GRID)
        self.press(window, self.menu_id())
        self.assertEqual(window.focus, RAIL)

    def test_menu_key_is_ignored_during_splash_and_becomes_active_once_splash_ends(self):
        hold = threading.Event()
        self.addCleanup(hold.set)
        self.rec(vid(1, "One"))
        self.site.held[D.SECTIONS[0].route] = hold
        window = self.open(wait=False)
        self.assertTrue(window.splash)
        asked = []
        real_set_focus = window.setFocusId
        window.setFocusId = lambda cid: (asked.append(cid), real_set_focus(cid))
        self.press(window, self.menu_id())
        self.assertEqual((window.focus, asked), (0, []))
        window.focus = RAIL
        self.press(window, self.menu_id())
        self.assertEqual((window.focus, asked), (RAIL, []))
        window.focus = 0
        hold.set()
        self.assertTrue(wait_for(lambda: window.loads >= 1 and not window.splash))
        self.assertEqual(window.focus, GRID)
        self.press(window, self.menu_id())
        self.assertEqual(window.focus, RAIL)
        window.stop()

        demo_loading = self.open(wait=False, demo=True, scenario="loading")
        self.assertTrue(demo_loading.splash)
        self.press(demo_loading, self.menu_id())
        self.assertEqual(demo_loading.focus, 0)
        timer = demo_loading._timers["splash"]
        timer.cancel()
        timer.function(*timer.args)
        self.assertFalse(demo_loading.splash)
        demo_loading.focus = 0
        self.press(demo_loading, self.menu_id())
        self.assertEqual(demo_loading.focus, RAIL)

    def test_menu_key_is_ignored_when_mode_is_empty_and_works_after_init(self):
        self.rec(vid(1, "One"))
        window = self.make()
        self.assertEqual((window.mode, window.splash, window.focus), ("", False, 0))
        asked = []
        real_set_focus = window.setFocusId
        window.setFocusId = lambda cid: (asked.append(cid), real_set_focus(cid))
        self.press(window, self.menu_id())
        self.assertEqual((window.focus, asked), (0, []))
        for focused in (RAIL, GRID, ACTION):
            window.focus = focused
            self.press(window, self.menu_id())
            self.assertEqual((window.focus, asked), (focused, []), focused)
        window.focus = 0
        window.onInit()
        self.assertTrue(wait_for(lambda: window.loads >= 1))
        self.assertEqual((window.mode, window.focus), (D.DATA, GRID))
        self.press(window, self.menu_id())
        self.assertEqual(window.focus, RAIL)



class UiContext(WindowCase):
    def setUp(self):
        super().setUp()
        self.ctx_path = os.path.join(TMP, "ui-context.json")
        if os.path.exists(self.ctx_path):
            os.unlink(self.ctx_path)
        self.ctx_writes = []
        real_write = panel_ui_context.write_context

        def record_write(doc, path=None):
            self.ctx_writes.append(doc)
            return real_write(doc, path=self.ctx_path)

        patch = mock.patch.object(panel_ui_context, "write_context", side_effect=record_write)
        patch.start()
        self.addCleanup(patch.stop)

    def read_ctx(self):
        return panel_ui_context.read_context(self.ctx_path)

    def test_publishes_ui_context_on_open_and_preserves_fake_rpc(self):
        self.rec(vid(1, "One"))
        win = self.open()
        ctx = self.read_ctx()
        self.assertEqual(ctx["app"], "youtube")
        self.assertEqual(ctx["view"], "section")
        self.assertEqual(ctx["section"], D.DEFAULT_SECTION)
        self.assertTrue(ctx["can_search"])
        self.assertEqual(ctx["search_query"], "")
        self.assertEqual(ctx["search_hint"], "Поиск на YouTube")
        self.assertIsNone(ctx["modal"])
        self.assertEqual([s["id"] for s in ctx["sections"]], list(D.SECTION_KEYS))
        for sec, raw_sec in zip(ctx["sections"], D.SECTIONS):
            self.assertTrue(re.search(r"[\u0400-\u04ff]", sec["label"]), f"expected Russian label for {sec}")
            self.assertNotEqual(sec["label"], raw_sec.name)
        self.assertEqual(ctx["chips"], [])
        self.assertEqual(Fake.rpc, [])
        self.assertIsNotNone(win)

    def test_publishes_updated_context_on_section_search_and_kind_changes(self):
        self.rec(vid(1, "One"))
        self.site.routes[D.SECTIONS[5].route] = answer(vid(2, "Trend"))
        self.site.routes[D.search_route("cats", D.KIND_VIDEO)] = answer(vid(3, "Cat Video"))
        self.site.routes[D.search_route("cats", D.KIND_CHANNEL)] = answer(folder(R + "channel/c1/", "Cat Channel"))
        win = self.open()

        self.go(win, "trend")
        ctx = self.read_ctx()
        self.assertEqual(ctx["section"], "trend")
        self.assertEqual(ctx["chips"], [])

        Fake.typed.append("cats")
        before = win.loads
        self.go(win, D.SEARCH)
        self.assertTrue(wait_for(lambda: win.loads > before))
        ctx = self.read_ctx()
        self.assertEqual(ctx["section"], D.SEARCH)
        self.assertEqual(ctx["search_query"], "cats")
        self.assertEqual([c["id"] for c in ctx["chips"]], list(D.KIND_KEYS))
        self.assertEqual([c["id"] for c in ctx["chips"] if c.get("active")], [D.KIND_VIDEO])

        before = win.loads
        win.onClick(KIND_IDS[1])
        self.assertTrue(wait_for(lambda: win.loads > before))
        ctx = self.read_ctx()
        self.assertEqual(ctx["section"], D.SEARCH)
        self.assertEqual(ctx["search_query"], "cats")
        self.assertEqual([c["id"] for c in ctx["chips"] if c.get("active")], [D.KIND_CHANNEL])

    def test_ui_cmd_set_section_set_filter_search_and_play(self):
        self.rec(vid(1, "One"))
        self.site.routes[D.SECTIONS[5].route] = answer(vid(2, "Trend"))
        self.site.routes[D.search_route("jazz", D.KIND_VIDEO)] = answer(vid(3, "Jazz"))
        self.site.routes[D.search_route("jazz", D.KIND_PLAYLIST)] = answer(folder(R + "playlist/p1/", "Jazz Mix"))
        win = self.open()
        self.assertIsNotNone(getattr(win, "_cmd_monitor", None))

        before = win.loads
        win._cmd_monitor.onNotification(
            "media-stick.panel",
            "Other.mediastick.ui_cmd",
            json.dumps({"app": "youtube", "cmd": "set_section", "section": "trend"}),
        )
        self.assertTrue(wait_for(lambda: win.loads > before))
        self.assertEqual(self.read_ctx()["section"], "trend")

        with mock.patch.object(Dialog, "input", side_effect=AssertionError("Dialog.input must not be called")):
            before = win.loads
            win._cmd_monitor.onNotification(
                "media-stick.panel",
                "Other.mediastick.ui_cmd",
                json.dumps({"app": "youtube", "cmd": "search", "query": "jazz"}),
            )
            self.assertTrue(wait_for(lambda: win.loads > before))
        ctx = self.read_ctx()
        self.assertEqual(ctx["section"], D.SEARCH)
        self.assertEqual(ctx["search_query"], "jazz")
        self.assertEqual(self.shown(win), ["Jazz"])

        before = win.loads
        win._cmd_monitor.onNotification(
            "media-stick.panel",
            "Other.mediastick.ui_cmd",
            json.dumps({"app": "youtube", "cmd": "set_filter", "id": "playlist", "active": True}),
        )
        self.assertTrue(wait_for(lambda: win.loads > before))
        ctx = self.read_ctx()
        self.assertEqual([c["id"] for c in ctx["chips"] if c.get("active")], ["playlist"])

        before = win.loads
        win._cmd_monitor.onNotification(
            "media-stick.panel",
            "Other.mediastick.ui_cmd",
            json.dumps({"app": "youtube", "cmd": "set_section", "section": "rec"}),
        )
        self.assertTrue(wait_for(lambda: win.loads > before or (win.mode == D.DATA and win.view is not None and win.view.key == D.DEFAULT_SECTION)))
        played = []
        with mock.patch.object(files, "play", side_effect=lambda p: played.append(p)):
            win._cmd_monitor.onNotification(
                "media-stick.panel",
                "Other.mediastick.ui_cmd",
                json.dumps({"app": "youtube", "cmd": "play"}),
            )
            self.assertTrue(wait_for(lambda: len(played) == 1))
        self.assertEqual(played, [R + "play/?video_id=v1"])

    def test_ui_cmd_ignores_wrong_app_wrong_method_and_invalid_payloads(self):
        self.rec(vid(1, "One"))
        win = self.open()
        self.assertIsNotNone(getattr(win, "_cmd_monitor", None))
        for method, data in (
            ("Other.mediastick.other", json.dumps({"app": "youtube", "cmd": "set_section", "section": "trend"})),
            ("Other.mediastick.ui_cmd", json.dumps({"app": "sweettv", "cmd": "set_section", "section": "tv"})),
            ("Other.mediastick.ui_cmd", "{not-json"),
            ("Other.mediastick.ui_cmd", json.dumps({"app": "youtube", "cmd": "unknown_cmd"})),
            ("Other.mediastick.ui_cmd", json.dumps({"app": "youtube", "cmd": "set_section"})),
            ("Other.mediastick.ui_cmd", json.dumps({"app": "youtube", "cmd": "set_section", "section": "nonexistent"})),
        ):
            win._cmd_monitor.onNotification("media-stick.panel", method, data)
        time.sleep(0.05)
        self.assertEqual(win.view.key, D.DEFAULT_SECTION)
        self.assertEqual(self.read_ctx()["section"], D.DEFAULT_SECTION)

    def test_wakeup_notify_emitted_only_when_xbmc_monitor_exists(self):
        self.rec(vid(1, "One"))
        DummyMonitor = type("DummyMonitor", (), {})
        with mock.patch.object(xbmc, "Monitor", DummyMonitor, create=True):
            self.open()
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 1))
            req = json.loads(Fake.rpc[0])
            self.assertEqual(req["method"], "JSONRPC.NotifyAll")
            self.assertEqual(req["params"]["sender"], "script.media-stick.home")
            self.assertEqual(req["params"]["message"], "mediastick.ui_context")

    def test_oserror_and_missing_module_are_guarded(self):
        self.rec(vid(1, "One"))
        with mock.patch.object(panel_ui_context, "write_context", side_effect=OSError("read-only")):
            win = self.open()
            self.go(win, "trend")
        with mock.patch.object(youtube_app, "panel_ui_context", None, create=True):
            win2 = self.open()
            self.assertEqual(win2.view.key, D.DEFAULT_SECTION)

    def test_main_clears_ui_context_in_finally_and_on_exception(self):
        created = []

        def fake_load(cls, xml):
            win = cls()
            created.append(win)
            return win

        def fake_do_modal(win):
            win.onInit()
            self.assertTrue(wait_for(lambda: win.loads >= 1))
            self.assertEqual(self.read_ctx()["app"], "youtube")

        with mock.patch.object(xbmcgui, "getCurrentWindowId", lambda: 13001, create=True), \
                mock.patch.object(youtube_app.ui, "load", side_effect=fake_load), \
                mock.patch.object(youtube_app.YouTube, "doModal", fake_do_modal):
            self.assertTrue(youtube_app.main(["demo"]))
        self.assertEqual(self.read_ctx(), mediastick_ui_context.empty_context())
        self.assertIsNone(getattr(created[-1], "_cmd_monitor", None))

        def failing_do_modal(win):
            win.onInit()
            self.assertTrue(wait_for(lambda: win.loads >= 1))
            raise RuntimeError("boom")

        with mock.patch.object(xbmcgui, "getCurrentWindowId", lambda: 13001, create=True), \
                mock.patch.object(youtube_app.ui, "load", side_effect=fake_load), \
                mock.patch.object(youtube_app.YouTube, "doModal", failing_do_modal):
            with self.assertRaises(RuntimeError):
                youtube_app.main(["demo"])
        self.assertEqual(self.read_ctx(), mediastick_ui_context.empty_context())

if __name__ == "__main__":
    unittest.main()
