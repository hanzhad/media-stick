#!/usr/bin/env python3
"""Offline test of the SWEET.TV app (no Kodi, no device, no network): python3 tools/test-sweettv-app.py

The pure part (sweettv_data, sweettv_view, sweettv_state, sweettv_play, sweettv_demo) is tested directly; the window
runs on stubbed xbmc, xbmcgui, xbmcaddon and xbmcvfs, with the sign-in library the real one on a temp directory."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

import ast  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
SKIN = os.path.join(ADDON, "resources", "skins", "default", "1080i")
MEDIA = os.path.join(ADDON, "resources", "skins", "default", "media")
XML = os.path.join(SKIN, "script-media-stick-sweettv.xml")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_ADDON_LIB"] = os.path.join(ADDON, "resources", "lib")     # where the phone page finds the TV's texts
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")        # the device's language lives here (mediastick_lang)
os.environ["MEDIASTICK_RESUME_DIR"] = os.path.join(TMP, "resume")      # local resume & favourites live here (mediastick_resume)
os.makedirs(os.environ["MEDIASTICK_PREFS_DIR"])
with open(os.path.join(os.environ["MEDIASTICK_PREFS_DIR"], "language"), "w", encoding="utf-8") as f:
    f.write("en" + chr(10))                                                     # English unless a test says otherwise: the strings read as the code spells them
os.environ["TZ"] = "UTC"
time.tzset()


class Fake:
    """What the stubbed Kodi shows and does."""
    builtins, notes, rpc, rpc_threads, played, seeks = [], [], [], [], [], []
    playing = False
    stopped = 0
    position, length = 0.0, 0.0
    ip = "192.168.1.20"
    home = {}
    typed, asked = "", []                  # what the person types on the on-screen keyboard; what it was asked with: (heading, default)


class Control:
    def __init__(self):
        self.items, self.selected, self.label = [], 0, ""

    def reset(self):
        self.items, self.selected = [], 0

    def addItems(self, items):
        self.items = list(items)

    def selectItem(self, i):
        self.selected = i

    def getSelectedPosition(self):
        return self.selected if self.items else -1

    def size(self):
        return len(self.items)

    def setLabel(self, label):
        self.label = label

    def getLabel(self):
        return self.label


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2, self.props, self.art = label, label2, {}, {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def setLabel2(self, value):
        self.label2 = value

    def setArt(self, art):
        self.art = dict(art)


class WindowXML:
    def __init__(self, *a):
        self._props, self.focus = {}, 0
        self.controls = {100: Control(), 200: Control(), 210: Control(), 211: Control(), 212: Control(), 213: Control(),
                         300: Control(), 301: Control(), 400: Control(), 410: Control(),
                         **{i: Control() for i in range(401, 409)}}
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
        Fake.playing = False

    def play(self, *a, **k):
        Fake.played.append((a, k))

    def getTime(self):
        if not Fake.playing:
            raise RuntimeError("Kodi is not playing any media file")
        return Fake.position

    def getTotalTime(self):
        return Fake.length

    def seekTime(self, seconds):
        Fake.seeks.append(seconds)


def translate(path):
    for special, name in (("special://temp", "temp"), ("special://profile", "profile")):
        if path.startswith(special):
            return TMP + "/" + name + path[len(special):]
    return path


def execute_rpc(request):
    Fake.rpc.append(request)
    Fake.rpc_threads.append(threading.current_thread())
    return "{}"


xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: Fake.builtins.append(cmd)
xbmc.executeJSONRPC = execute_rpc
xbmc.getCondVisibility = lambda cond: True
xbmc.getIPAddress = lambda: Fake.ip
xbmc.sleep = lambda ms: None
xbmc.Player = Player
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = translate
xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = lambda *a: types.SimpleNamespace(getAddonInfo=lambda key: ADDON)


class Dialog:
    def notification(self, heading, text, *a, **k):
        Fake.notes.append(text)

    def input(self, heading, defaultt="", *a, **k):
        Fake.asked.append((heading, defaultt))
        return Fake.typed


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

from resources.lib import accounts, apps, store, sweettv_app, sweettv_data as data, sweettv_demo, sweettv_files as files  # noqa: E402
from resources.lib import sweettv_play as play, sweettv_state as S, sweettv_text as W, sweettv_view as V  # noqa: E402
from resources.lib import sweettv_writer  # noqa: E402
from resources.lib import page_cache, prefetch, sweettv_items as IT, sweettv_pages as PG, textfit  # noqa: E402
from resources.lib import sweettv_search as SRCH  # noqa: E402
import mediastick_resume as MR  # noqa: E402
import mediastick_sweetlive as ML  # noqa: E402
import mediastick_sweetapi as API  # noqa: E402

W.set_language("en")                     # the pure parts of the screen (the windows set it from the file above)
REAL_WARM = prefetch.warm                # the start-up run itself; a test case replaces the module's by one that does nothing
D = data
MIDNIGHT = 1_799_971_200                 # 2027-01-15 00:00:00 UTC
NOW = MIDNIGHT + 8 * 3600
MENU, ROW, ACTIONS, RESUME = sweettv_app.MENU, sweettv_app.ROW, sweettv_app.ACTIONS, sweettv_app.RESUME
GUIDE_BUTTON, GUIDE, SIGNIN = sweettv_app.GUIDE_BUTTON, sweettv_app.GUIDE, sweettv_app.SIGNIN_BUTTON
KEY_UP, KEY_DOWN, KEY_RIGHT = 3, 4, 2
EMPTY_STATE = {"favourites": [], "recent": [], "last": "", "resume": {}}


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def prog(start, stop, text="Show", pid=1, **extra):
    return {"id": pid, "time_start": start, "time_stop": stop, "text": text, "available": True, **extra}


def chan(cid, name=None, **extra):
    return {"id": cid, "name": name if name is not None else f"Chan {cid}", "available": True, "category": [],
            "catchup": False, "icon_v2_url": "", "epg": [], **extra}


def answer(*channels, categories=()):
    return {"status": "OK", "categories": list(categories), "list": list(channels)}


def demo_raw(now=NOW):
    return sweettv_demo.demo_data(now, "/logos")


def demo_catalog(now=NOW):
    return D.parse_catalog(demo_raw(now), now)


def recent(*ids, at=NOW):
    return [{"id": cid, "at": at - 60 * n} for n, cid in enumerate(ids)]


# ---- the pure part ---------------------------------------------------------------------------

class Parser(unittest.TestCase):
    def test_demo_fixture_has_the_real_shape_and_parses_whole(self):
        raw = demo_raw()
        self.assertEqual(raw["status"], "OK")
        catalog = D.parse_catalog(raw, NOW)
        self.assertEqual(len(catalog.channels), len(raw["list"]))
        self.assertEqual(catalog.skipped, 0)
        self.assertGreaterEqual(len(catalog.channels), 40)
        self.assertEqual([n for _, n in catalog.categories],
                         ["News", "Movies & Series", "Sport", "Kids", "Music & Lifestyle", "Documentary"])   # 1000 is left out
        self.assertEqual([c.number for c in catalog.channels], list(range(1, len(catalog.channels) + 1)))
        self.assertEqual(len({c.cid for c in catalog.channels}), len(catalog.channels))
        state = S.normalize_state({})
        self.assertEqual([e.count for e in D.rail(catalog, state)][7:], [9, 8, 8, 8, 8, 8])           # the genres, after the heading
        loose = next(c for c in catalog.channels if c.name == sweettv_demo.NO_CATEGORY[0])
        self.assertEqual(loose.cats, ("1000",))                               # in All, in no category
        self.assertEqual([c.cid for c in D.channels_for(catalog, "c:1", state)].count(loose.cid), 0)
        self.assertIn(loose.cid, [c.cid for c in D.channels_for(catalog, D.ALL, state)])
        self.assertTrue(any(c.logo for c in catalog.channels) and any(not c.logo for c in catalog.channels))

    def test_demo_has_a_gap_a_channel_without_programmes_and_unicode(self):
        catalog = demo_catalog()
        by_name = {c.name: c for c in catalog.channels}
        now, nxt = D.now_next(by_name[sweettv_demo.GAP], NOW)
        self.assertIsNone(now)
        self.assertIsNotNone(nxt)
        self.assertEqual(D.now_next(by_name[sweettv_demo.NO_EPG], NOW), (None, None))
        busy = [c for c in catalog.channels if c.name not in (sweettv_demo.GAP, sweettv_demo.NO_EPG)]
        self.assertTrue(all(D.now_next(c, NOW)[0] and D.now_next(c, NOW)[1] for c in busy))
        self.assertIn("Новини Країни", by_name)

    def test_demo_programmes_have_descriptions_and_the_archive_has_programmes_to_play(self):
        catalog = demo_catalog()
        busy = [c for c in catalog.channels if c.name not in (sweettv_demo.GAP, sweettv_demo.NO_EPG)]
        described = [c for c in busy if D.now_next(c, NOW)[0].desc]
        self.assertGreaterEqual(len(described), len(busy) * 0.7)
        archived = [c for c in catalog.channels if c.catchup and c.epg]
        self.assertGreaterEqual(len(archived), 20)
        self.assertTrue(any(not c.catchup for c in catalog.channels))
        counts = [sum(1 for r in V.guide_rows(channel, NOW) if r.kind == "archive") for channel in archived]
        self.assertGreaterEqual(min(counts), 1)                                   # every archive has something to play
        self.assertGreaterEqual(sum(1 for n in counts if n >= 2), len(counts) * 0.7)
        self.assertTrue(all(len(c.epg) <= D.MAX_PROGRAMMES for c in catalog.channels))

    def test_demo_state_has_favourites_recent_channels_and_one_place_to_continue(self):
        raw = demo_raw()
        catalog = D.parse_catalog(raw, NOW)
        state = S.normalize_state(sweettv_demo.demo_state(raw, NOW))
        ids = {c.cid for c in catalog.channels}
        self.assertTrue(set(state["favourites"]) <= ids and len(state["favourites"]) >= 4)
        self.assertGreaterEqual(len(state["recent"]), 4)
        self.assertEqual([e["id"] for e in state["recent"]][0], state["last"])
        self.assertEqual([e["at"] for e in state["recent"]], sorted((e["at"] for e in state["recent"]), reverse=True))
        self.assertEqual(len(D.channels_for(catalog, D.RECENT, state)), len(state["recent"]))
        self.assertEqual(D.default_category(catalog, state), D.RECENT)
        channel = next(c for c in catalog.channels if c.name == sweettv_demo.RESUME_ON)
        entry = V.resume_for(state, channel, NOW)
        self.assertIsNotNone(entry)
        self.assertTrue(V.resume_label(entry).startswith("Continue from "))

    def test_odd_input_never_raises(self):
        junk = [None, 5, "x", [], {}, {"id": None}, {"id": "abc"}, {"id": True}, {"id": -3}, {"id": 0}, {"id": 1.5},
                {"id": {"a": 1}}, {"id": 10 ** 30}, {"id": 7, "epg": "no", "category": 3, "name": 42, "icon_url": 9},
                {"id": 8, "name": "x" * 500, "epg": [None, 1, "a", {}, {"time_start": "x"}]},
                {"id": 9, "catchup": True, "catchup_duration": "many", "epg": [{"id": 1, "time_start": NOW - 5, "time_stop": NOW + 5}]}]
        for item in junk:
            D.parse_catalog(answer(item), NOW)
        catalog = D.parse_catalog(answer(*junk), NOW)
        self.assertEqual(sorted(c.cid for c in catalog.channels), sorted(["7", "8", "9", str(10 ** 30)]))     # a huge id is still a number
        self.assertEqual(len(next(c for c in catalog.channels if c.cid == "8").name), 80)
        for raw in (None, [], "x", 5, {}, {"status": "OK"}, {"status": "OK", "list": "no"}, {"list": None},
                    {"status": "ERROR", "list": [chan(1)]}, {"status": 3, "list": [chan(1)]}):
            D.parse_catalog(raw, NOW)
        self.assertEqual(D.parse_catalog({"status": "ERROR", "list": [chan(1)]}, NOW), D.SERVICE_ERROR)
        self.assertEqual(D.parse_catalog([chan(1)], NOW), D.FORMAT_ERROR)
        self.assertEqual((D.SERVICE_ERROR.channels, D.SERVICE_ERROR.error, D.EMPTY_CATALOG.error), ((), "service", ""))
        self.assertEqual(D.parse_catalog(answer(), NOW), D.EMPTY_CATALOG)               # an empty list is not an error
        self.assertEqual(len(D.parse_catalog({"list": [chan(1)]}, NOW).channels), 1)       # a missing status is fine

    def test_missing_fields_get_sensible_values(self):
        catalog = D.parse_catalog({"list": [{"id": 5}, {"id": "6", "name": "  Six  ", "number": "3"}]}, NOW)
        five = next(c for c in catalog.channels if c.cid == "5")
        self.assertEqual((five.name, five.number, five.logo, five.cats, five.catchup, five.epg, five.days),
                         ("Channel 5", 0, "", (), False, (), 0))
        six = catalog.channels[0]
        self.assertEqual((six.cid, six.name, six.number), ("6", "Six", 3))                 # numbered ones first
        self.assertEqual(V.card_props(five, NOW)["now"], "No programme information")

    def test_unavailable_bad_and_duplicate_channels_are_skipped_the_first_duplicate_wins(self):
        catalog = D.parse_catalog(answer(chan(1, "One"), chan(2, "Two", available=False), chan(1, "Again"),
                                         {"name": "no id"}, chan(3, "Three")), NOW)
        self.assertEqual([(c.cid, c.name) for c in catalog.channels], [("1", "One"), ("3", "Three")])
        self.assertEqual(catalog.skipped, 3)
        self.assertEqual(D.parse_catalog(answer(chan(4, available=None)), NOW).channels[0].cid, "4")

    def test_ids_numbers_and_times_are_read_leniently(self):
        self.assertEqual([D.as_int(v) for v in (7, "7", " 7 ", 7.0, 7.5, True, None, "7a", "", float("nan"), [7])],
                         [7, 7, 7, 7, None, None, None, None, None, None, None])
        self.assertEqual(D.as_time(NOW), NOW)
        self.assertEqual(D.as_time(NOW * 1000), NOW)                    # milliseconds
        self.assertEqual(D.as_time(str(NOW)), NOW)
        for bad in (0, -5, 12345, "x", None, 1e30, True):
            self.assertIsNone(D.as_time(bad), bad)

    def test_categories(self):
        raw = answer(chan(1, category=[1, 1000]), chan(2, category=[2]), chan(3, category=[]), chan(4, category=[9]),
                     chan(5, category=["2", None, "x"]),
                     categories=[{"id": 1, "caption": "News"}, {"id": 2, "caption": "Films"}, {"id": 1000, "caption": "All"},
                                 {"id": 3, "caption": "Empty"}, {"id": 2, "caption": "Dup"}, {"id": 4, "caption": ""},
                                 {"id": "x", "caption": "Bad id"}, "junk", {"id": 9}, {"id": 5, "name": "Unused"}])
        catalog = D.parse_catalog(raw, NOW)
        self.assertEqual(catalog.categories, (("c:1", "News"), ("c:2", "Films")))       # data order; hidden, empty, unnamed gone
        state = S.normalize_state({})
        self.assertEqual([e.name for e in D.rail(catalog, state)], ["Continue", "Favourites", "All", D.SEARCH_NAME, D.SHOWS_NAME, D.FILMS_NAME, D.GENRES_NAME, "News", "Films"])
        self.assertEqual([c.cid for c in D.channels_for(catalog, "c:2", state)], ["2", "5"])
        self.assertEqual([c.cid for c in D.channels_for(catalog, "c:77", state)], [])   # an unknown one is empty, not an error
        self.assertEqual(D.channels_for(catalog, "bogus", state), [])

    def test_unicode_and_markup_in_texts(self):
        raw = answer(chan(1, "Новини [COLOR red]24[/COLOR]\n", epg=[prog(NOW - 60, NOW + 60, "Ранок\t[B]з[/B]  Анею")]))
        channel = D.parse_catalog(raw, NOW).channels[0]
        self.assertEqual(channel.name, "Новини (COLOR red)24(/COLOR)")
        self.assertEqual(channel.epg[0].title, "Ранок (B)з(/B) Анею")
        props = V.card_props(channel, NOW)
        self.assertTrue(all("[" not in v and "\n" not in v for v in props.values()))
        self.assertEqual(V.initials("Новини Країни"), "НК")
        self.assertEqual(V.initials("  "), "")
        self.assertEqual(V.initials("24 Kanal"), "2K")
        self.assertEqual(V.initials("---"), "--")

    def test_programmes_odd_times_duplicates_and_order(self):
        epg = [prog(NOW + 7200, NOW + 9000, "Late", 3), prog(NOW, NOW + 3600, "A", 1), prog(NOW, NOW + 3600, "A again", 9),
               prog(NOW + 3600, NOW + 3600, "Empty", 4), prog(NOW + 3600, NOW + 100, "Backwards", 5),
               prog("x", NOW, "Text", 6), prog(None, None, "None", 7), prog(NOW + 3600, (NOW + 7200) * 1000, "Ms", 8),
               prog(NOW - 10 * 86400, NOW - 10 * 86400 + 60, "Long ago", 10), prog(NOW + 5000, NOW + 5000 + 10 ** 7, "Huge", 11),
               "junk", None, prog(NOW + 3700, NOW + 7200, "", 12)]
        channel = D.parse_catalog(answer(chan(1, epg=epg)), NOW).channels[0]
        self.assertEqual([(p.title, p.epg_id) for p in channel.epg],
                         [("A", "1"), ("Ms", "8"), ("Programme", "12"), ("Late", "3")])        # in time order, milliseconds read
        self.assertEqual(channel.epg[1].stop, NOW + 7200)
        self.assertEqual([p.title for p in channel.epg if p.start == NOW], ["A"])             # the first duplicate wins
        self.assertEqual([p.start for p in channel.epg], sorted(p.start for p in channel.epg))
        self.assertNotIn("Long ago", [p.title for p in channel.epg])
        self.assertNotIn("Huge", [p.title for p in channel.epg])
        self.assertNotIn("Backwards", [p.title for p in channel.epg])
        many = [prog(NOW + i * 60, NOW + i * 60 + 60, f"P{i}", i + 1) for i in range(500)]
        self.assertEqual(len(D.parse_catalog(answer(chan(1, epg=many)), NOW).channels[0].epg), D.MAX_AHEAD)

    def test_finished_programmes_are_kept_for_the_archive_and_only_as_far_as_it_reaches(self):
        past = [prog(NOW - 3600 * (n + 1), NOW - 3600 * n - 60, f"P{n}", n + 1) for n in range(1, 30)]     # 1h..29h back
        ahead = [prog(NOW + 600, NOW + 1200, "Next", 99)]
        plain = D.parse_catalog(answer(chan(1, epg=past + ahead)), NOW).channels[0]
        self.assertEqual([p.title for p in plain.epg], ["P1", "Next"])                    # no archive: only the last two hours
        again = [prog(NOW - 5000, NOW - 4000, "Recent", 50), prog(NOW - 600, NOW + 60, "Now", 51)] + ahead
        self.assertEqual([p.title for p in D.parse_catalog(answer(chan(1, epg=again)), NOW).channels[0].epg], ["Recent", "Now", "Next"])
        for catchup in (dict(catchup=True, catchup_duration=1), dict(catchup=True, catchup_duration=2), dict(catchup=True)):
            channel = D.parse_catalog(answer(chan(1, epg=past + ahead, **catchup)), NOW).channels[0]
            days = max(1, catchup.get("catchup_duration", 0))
            kept = [p for p in channel.epg if p.stop <= NOW]
            self.assertLessEqual(len(kept), D.MAX_PAST)
            self.assertTrue(all(p.start >= NOW - days * 86400 - 3600 for p in kept))
            self.assertEqual(channel.days, days)
            self.assertEqual(channel.epg[-1].title, "Next")
            self.assertEqual(list(kept), sorted(kept, key=lambda p: p.start))
        self.assertEqual(D.parse_catalog(answer(chan(1, catchup=True, catchup_duration=500)), NOW).channels[0].days, D.MAX_DAYS)
        self.assertEqual(D.parse_catalog(answer(chan(1, catchup=True, catchup_duration="x")), NOW).channels[0].days, D.DEFAULT_DAYS)
        self.assertEqual(D.parse_catalog(answer(chan(1, catchup=False, catchup_duration=3)), NOW).channels[0].days, 0)

    def test_order_numbered_first_then_as_sent(self):
        catalog = D.parse_catalog(answer(chan(1, "a"), chan(2, "b", number=5), chan(3, "c"), chan(4, "d", number=2),
                                         chan(5, "e", number=5)), NOW)
        self.assertEqual([c.cid for c in catalog.channels], ["4", "2", "5", "1", "3"])

    def test_catch_up_and_logo(self):
        catalog = D.parse_catalog(answer(chan(1, catchup=True, icon_v2_url="https://x/y.png"),
                                         chan(2, icon_v2_url="javascript:alert(1)", icon_url="http://z/i.png"),
                                         chan(3, icon_v2_url="", icon_url=5)), NOW)
        self.assertEqual([(c.catchup, c.logo) for c in catalog.channels],
                         [(True, "https://x/y.png"), (False, "http://z/i.png"), (False, "")])


class NowAndNext(unittest.TestCase):
    """The clock is UTC here. A programme runs from its start up to, not including, its stop."""

    def setUp(self):
        h = 3600
        self.channel = D.parse_catalog(answer(chan(1, epg=[
            prog(MIDNIGHT - h, MIDNIGHT, "Late show", 1), prog(MIDNIGHT, MIDNIGHT + h, "Night news", 2),
            prog(MIDNIGHT + 2 * h, MIDNIGHT + 3 * h, "Film", 3)])), MIDNIGHT).channels[0]

    def title(self, p):
        return p.title if p else None

    def at(self, ts):
        now, nxt = D.now_next(self.channel, ts)
        return self.title(now), self.title(nxt)

    def test_around_midnight_and_a_gap(self):
        h = 3600
        self.assertEqual(self.at(MIDNIGHT - h - 1), (None, "Late show"))                  # before the first
        self.assertEqual(self.at(MIDNIGHT - h), ("Late show", "Night news"))
        self.assertEqual(self.at(MIDNIGHT - 1), ("Late show", "Night news"))              # 23:59:59
        self.assertEqual(self.at(MIDNIGHT), ("Night news", "Film"))                       # 00:00:00 is the next one's
        self.assertEqual(self.at(MIDNIGHT + h - 1), ("Night news", "Film"))
        self.assertEqual(self.at(MIDNIGHT + h), (None, "Film"))                           # the gap: nothing now, Film next
        self.assertEqual(self.at(MIDNIGHT + h + 1800), (None, "Film"))
        self.assertEqual(self.at(MIDNIGHT + 2 * h), ("Film", None))
        self.assertEqual(self.at(MIDNIGHT + 3 * h), (None, None))                         # past the last
        self.assertEqual(D.now_next(D.Channel("1", "x", 0, "", (), False, ()), NOW), (None, None))

    def test_the_texts_for_the_card_and_the_preview(self):
        props = V.card_props(self.channel, MIDNIGHT - 1800)
        self.assertEqual((props["now"], props["nowline"], props["next"], props["nextline"]),
                         ("Late show", "Now   23:00 – 00:00", "Night news", "Next   00:00 – 01:00   Night news"))
        self.assertEqual((props["bar"], props["pbar"]), ("sweettv-bar-10.png", "sweettv-pbar-10.png"))
        gap = V.card_props(self.channel, MIDNIGHT + 3600 + 5)
        self.assertEqual((gap["now"], gap["nowline"], gap["bar"], gap["pbar"]), ("No programme information", "", "", ""))
        self.assertTrue(gap["nextline"].startswith("Next   02:00 – 03:00   "), gap["nextline"])
        after = V.card_props(self.channel, MIDNIGHT + 4 * 3600)
        self.assertEqual((after["next"], after["nextline"]), ("", ""))

    def test_progress_steps(self):
        p = D.Programme(1000, 2000, "x", "", True, "")
        self.assertEqual([D.progress_step(p, t) for t in (1000, 1024, 1026, 1500, 1975, 1999, 2000, 5000, 0)],
                         [0, 0, 1, 10, 20, 20, 20, 20, 0])
        self.assertEqual(D.progress_step(None, 5), 0)
        self.assertEqual(D.progress_step(D.Programme(5, 5, "x", "", True, ""), 5), 0)
        self.assertEqual((D.bar_name(0), D.bar_name(20), D.bar_name(99), D.bar_name(-4)),
                         ("sweettv-bar-00.png", "sweettv-bar-20.png", "sweettv-bar-20.png", "sweettv-bar-00.png"))
        self.assertEqual((D.bar_name(3, wide=True), D.bar_name(99, wide=True)), ("sweettv-pbar-03.png", "sweettv-pbar-20.png"))


class View(unittest.TestCase):
    """sweettv_view: what the screen says about a channel."""

    def archive_channel(self, **extra):
        epg = [prog(NOW - 9000, NOW - 5400, "Not offered", 5, available=False), prog(NOW - 5400, NOW - 1800, "Early show", 7),
               prog(NOW - 1800, NOW - 600, "Late show", 8), prog(NOW - 600, NOW + 600, "Now ten", 9),
               prog(NOW + 600, NOW + 1200, "Then ten", 10)]
        return D.parse_catalog(answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=3, category=[1, 2, 3],
                                           epg=epg, **extra)), NOW).channels[0]

    def test_colours_are_opaque_and_belong_to_the_channel(self):
        for name in ("Aurora News 24", "Cinema Nova", "Новини Країни", "", "x" * 80):
            colours = V.colours(name)
            self.assertEqual(set(colours), {"tint", "plate", "plate_hi", "bg"})
            for key, value in colours.items():
                self.assertRegex(value, r"^FF[0-9A-F]{6}$", key)             # alpha 00 would read as white
            self.assertEqual(colours, V.colours(name))
        self.assertEqual(V.mix("FF000000", "FFFFFFFF", 0.5), "FF808080")
        self.assertEqual(V.mix("FF102030", "FF102030", 0.9), "FF102030")
        self.assertEqual(V.mix("FF000000", "FFFFFFFF", 0), "FF000000")
        self.assertEqual(V.mix("FF000000", "FFFFFFFF", 1), "FFFFFFFF")
        self.assertNotEqual(V.colours("Aurora News 24")["tint"], V.colours("Arena Sport 1")["tint"])
        bg = V.colours("Aurora News 24")["bg"]
        self.assertLess(int(bg[2:4], 16) + int(bg[4:6], 16) + int(bg[6:], 16), 3 * 110)       # a backdrop is dark

    def test_the_card_and_the_preview_come_from_one_set_of_properties(self):
        channel = self.archive_channel()
        props = V.card_props(channel, NOW, favourite=True, cat_names={"c:1": "News", "c:2": "Sport", "c:3": "Kids"})
        self.assertEqual(props["meta"], "Channel 10  ·  News  ·  Sport")
        self.assertEqual((props["fav"], props["catchup"], props["guide"], props["resume"]), ("1", "1", "1", ""))
        self.assertEqual((props["now"], props["nowline"], props["next"], props["nextline"]),
                         ("Now ten", "Now   07:50 – 08:10", "Then ten", "Next   08:10 – 08:20   Then ten"))
        self.assertEqual(props["bar"], "sweettv-bar-10.png")
        plain = V.card_props(channel, NOW)
        self.assertEqual((plain["fav"], plain["meta"]), ("", "Channel 10"))
        entry = {"epg": "7", "title": "Early show", "start": NOW - 5400, "stop": NOW - 1800, "pos": 900, "at": NOW}
        self.assertEqual(V.card_props(channel, NOW, resume=entry)["resume"], "Continue from 06:45")
        nothing = D.parse_catalog(answer(chan(1, "One")), NOW).channels[0]
        self.assertEqual((V.card_props(nothing, NOW)["guide"], V.card_props(nothing, NOW)["catchup"]), ("", ""))

    def test_the_guide_lists_what_is_on_and_what_the_archive_holds_newest_first(self):
        channel = self.archive_channel()
        rows = V.guide_rows(channel, NOW)
        self.assertEqual([(r.title, r.kind) for r in rows], [("Now ten", "live"), ("Late show", "archive"), ("Early show", "archive")])
        self.assertEqual(rows[1].when, "07:30 – 07:50")
        self.assertEqual(rows[2].epg_id, "7")
        self.assertTrue(V.has_archive(channel, NOW))
        later = V.guide_rows(channel, NOW + 4 * 86400)                       # four days on: nothing is inside the 3-day archive
        self.assertEqual([r.kind for r in later], [])
        long_ago = V.guide_rows(channel, NOW + 2 * 86400 + 3600)
        self.assertTrue(all(r.start >= NOW + 3600 - 86400 for r in long_ago if r.kind == "archive"))
        yesterday = D.Channel("1", "x", 0, "", (), True, (D.Programme(NOW - 86400, NOW - 86400 + 3600, "Old", "3", True, ""),), 3)
        self.assertEqual(V.guide_rows(yesterday, NOW)[0].when, "14.01  08:00 – 09:00")      # the date when it is not today
        no_archive = D.parse_catalog(answer(chan(1, epg=[prog(NOW - 5400, NOW - 1800, "Early", 7), prog(NOW - 600, NOW + 600, "Now", 9)])), NOW).channels[0]
        self.assertEqual([r.kind for r in V.guide_rows(no_archive, NOW)], ["live"])
        self.assertFalse(V.has_archive(no_archive, NOW))
        no_id = D.Channel("1", "x", 0, "", (), True, (D.Programme(NOW - 5400, NOW - 1800, "Early", "", True, ""),), 3)
        self.assertEqual(V.guide_rows(no_id, NOW), [])                          # no id: nothing to ask the service for

    def test_a_place_to_continue_from_counts_only_inside_the_archive(self):
        channel = self.archive_channel()
        state = S.normalize_state({"resume": {"10": {"epg": "7", "title": "Early show", "start": NOW - 5400, "stop": NOW - 1800,
                                                     "pos": 900, "at": NOW}}})
        self.assertEqual(V.resume_for(state, channel, NOW)["pos"], 900)
        self.assertIsNone(V.resume_for(state, channel, NOW + 4 * 86400))        # fell out of the archive
        self.assertIsNone(V.resume_for(S.normalize_state({}), channel, NOW))
        plain = D.parse_catalog(answer(chan(10, "Ten")), NOW).channels[0]
        self.assertIsNone(V.resume_for(state, plain, NOW))                      # a channel without an archive
        self.assertEqual(V.category_heading("News", 9), "News  ·  9 channels")
        self.assertEqual(V.category_heading("News", 1), "News  ·  1 channel")


class Saved(unittest.TestCase):
    """sweettv_state: favourites, recent channels, the last one, places in the archive."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "addon_data", "sweettv.json")

    def test_toggle_record_save_load(self):
        state = S.normalize_state({})
        state, added = S.toggle_favourite(state, "5")
        self.assertTrue(added)
        state, added = S.toggle_favourite(state, "7")
        state, added = S.toggle_favourite(state, "5")
        self.assertFalse(added)
        self.assertEqual(state["favourites"], ["7"])
        for n, cid in enumerate(("1", "2", "1", "3")):
            state = S.record_played(state, cid, NOW + n)
        self.assertEqual(([e["id"] for e in state["recent"]], state["last"]), (["3", "1", "2"], "3"))
        self.assertEqual(state["recent"][0], {"id": "3", "at": NOW + 3})
        self.assertEqual({e["id"]: e["at"] for e in state["recent"]}, {"3": NOW + 3, "1": NOW + 2, "2": NOW + 1})   # when each was last seen
        self.assertTrue(S.save_state(self.path, state))
        self.assertEqual(S.load_state(self.path), state)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["sweettv.json"])      # no temp file left behind

    def test_recent_is_bounded_to_twelve_and_the_newest_comes_first(self):
        state = S.normalize_state({})
        for cid in range(1, 60):
            state = S.record_played(state, str(cid), NOW + cid)
        self.assertEqual(len(state["recent"]), S.MAX_RECENT)
        self.assertEqual(S.MAX_RECENT, 12)
        self.assertEqual([e["id"] for e in state["recent"]][:3], ["59", "58", "57"])
        self.assertEqual(state["last"], "59")
        self.assertEqual(D.recent_ids(state)[0], "59")

    def test_a_broken_or_odd_file_is_an_empty_state_never_an_error(self):
        self.assertEqual(S.load_state(self.path), EMPTY_STATE)                         # missing
        for text in ("", "{", "[1, 2]", "null", '"x"', "{\"favourites\": 5}", "\x00\x01"):
            put(self.path, text)
            self.assertEqual(S.load_state(self.path), EMPTY_STATE, text)
        put(self.path, json.dumps({"favourites": ["3", 3, "x", None, -1, True, "4"], "recent": "no", "last": "9"}))
        self.assertEqual(S.load_state(self.path), {**EMPTY_STATE, "favourites": ["3", "4"], "last": "9"})
        put(self.path, json.dumps({"recent": [{"id": "8", "at": 5}, {"id": "9"}]}))
        self.assertEqual(S.load_state(self.path)["last"], "8")                          # no explicit last: the newest

    def test_the_older_file_format_with_bare_ids_is_still_read(self):
        put(self.path, json.dumps({"favourites": ["3"], "recent": ["8", 9, "8", "x", None, {"id": "7", "at": "bad"}], "last": "9"}))
        state = S.load_state(self.path)
        self.assertEqual(state["recent"], [{"id": "8", "at": 0}, {"id": "9", "at": 0}, {"id": "7", "at": 0}])
        self.assertEqual((state["favourites"], state["last"]), (["3"], "9"))

    def test_the_place_in_an_archived_programme_is_kept_only_when_it_is_worth_it(self):
        state = S.normalize_state({})
        programme = {"epg": "7", "title": "Early show", "start": NOW - 5400, "stop": NOW - 1800}      # 3600 s long
        state = S.record_position(state, "10", programme, 900, 3600, NOW)
        self.assertEqual(state["resume"]["10"], {**programme, "pos": 900, "at": NOW})
        for pos, total in ((30, 3600), (0, 0), (3600 - S.END_MARGIN + 1, 3600), (3600, 3600), (3550, 0)):
            self.assertNotIn("10", S.record_position(state, "10", programme, pos, total, NOW)["resume"], (pos, total))   # forgotten
        self.assertIn("10", S.record_position(state, "10", programme, S.MIN_RESUME, 3600, NOW)["resume"])
        self.assertIn("10", S.record_position(state, "10", programme, 3600 - S.END_MARGIN, 3600, NOW)["resume"])
        self.assertEqual(S.record_position(state, "10", programme, 1200, 0, NOW)["resume"]["10"]["pos"], 1200)   # length from the times
        self.assertNotIn("10", S.forget_position(state, "10")["resume"])
        for cid in range(1, 40):
            state = S.record_position(state, str(cid), programme, 900, 3600, NOW + cid)
        self.assertEqual(len(state["resume"]), S.MAX_RESUME)
        self.assertIn("39", state["resume"])
        self.assertNotIn("1", state["resume"])
        self.assertTrue(S.save_state(self.path, state))
        self.assertEqual(S.load_state(self.path), state)

    def test_odd_resume_entries_are_dropped(self):
        good = {"epg": "7", "title": "T", "start": NOW - 5400, "stop": NOW - 1800, "pos": 900, "at": NOW}
        raw = {"resume": {"1": good, "2": {**good, "pos": 99999}, "3": {**good, "stop": NOW - 6000}, "4": "x", "x": good,
                          "5": {**good, "epg": ""}, "6": {**good, "pos": True}, "7": {**good, "title": "[B]x"}}}
        resume = S.normalize_state(raw)["resume"]
        self.assertEqual(sorted(resume), ["1", "7"])
        self.assertEqual(resume["7"]["title"], "(B)x")
        self.assertEqual(S.normalize_state({"resume": [good]})["resume"], {})

    def test_a_save_that_cannot_happen_returns_false_and_leaves_the_old_file(self):
        S.save_state(self.path, {"favourites": ["1"], "recent": [], "last": ""})
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(S.save_state(self.path, {"favourites": ["2"], "recent": [], "last": ""}))
        self.assertEqual(S.load_state(self.path)["favourites"], ["1"])
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["sweettv.json"])
        self.assertFalse(S.save_state(os.path.join(self.path, "sub", "x.json"), {}))      # a file where a folder should be

    def test_rail_counts_and_lists_follow_the_state(self):
        catalog = D.parse_catalog(answer(chan(1, number=1), chan(2, number=2), chan(3, number=3)), NOW)
        state = S.normalize_state({"favourites": ["3", "99"], "recent": recent("2", "1", "88")})
        self.assertEqual([(e.key, e.count) for e in D.rail(catalog, state)],
                         [("recent", 2), ("fav", 1), ("all", 3), (D.SEARCH, None), (D.SHOWS, None), (D.FILMS, None)])
        self.assertEqual([c.cid for c in D.channels_for(catalog, D.RECENT, state)], ["2", "1"])       # most recent first
        self.assertEqual([c.cid for c in D.channels_for(catalog, D.FAVOURITES, state)], ["3"])
        self.assertEqual(D.default_category(catalog, state), D.RECENT)
        self.assertEqual(D.default_category(catalog, S.normalize_state({"recent": recent("88")})), D.ALL)      # nothing of it is on offer now
        self.assertEqual(D.default_category(catalog, S.normalize_state({})), D.ALL)
        self.assertEqual(D.focus_index(catalog.channels, "3"), 2)
        self.assertEqual(D.focus_index(catalog.channels, "77"), 0)
        self.assertEqual(D.focus_index([], "1"), 0)


class Writer(unittest.TestCase):
    """sweettv_writer: the state is written by a thread of its own."""

    def test_writes_on_its_own_thread_and_a_burst_costs_one_write(self):
        seen, gate = [], threading.Event()

        def save(path, state):
            seen.append((threading.current_thread(), state))
            gate.wait(2)
        writer = sweettv_writer.StateWriter("x", save)
        writer.start()
        writer.submit({"n": 1})
        self.assertTrue(wait_for(lambda: len(seen) == 1))                     # the first is being written, held at the gate
        for n in (2, 3, 4):
            writer.submit({"n": n})
        gate.set()
        writer.stop()
        self.assertEqual([s["n"] for _, s in seen], [1, 4])                   # what came in while it wrote is written once, newest
        self.assertTrue(all(t is not threading.main_thread() for t, _ in seen))
        self.assertEqual(writer.writes, 2)

    def test_stop_writes_what_is_waiting(self):
        seen = []
        writer = sweettv_writer.StateWriter("x", lambda path, state: seen.append(state))
        writer.submit({"n": 1})
        writer.start()
        writer.stop()
        self.assertEqual(seen, [{"n": 1}])
        idle = sweettv_writer.StateWriter("x", lambda path, state: seen.append(state))
        idle.start()
        idle.stop()
        self.assertEqual(seen, [{"n": 1}])

    def test_the_default_is_the_atomic_save_of_the_state_module(self):
        path = os.path.join(tempfile.mkdtemp(), "w", "sweettv.json")
        writer = sweettv_writer.StateWriter(path)
        writer.start()
        writer.submit(S.record_played(S.normalize_state({}), "5", NOW))
        writer.stop()
        self.assertEqual(S.load_state(path)["last"], "5")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["sweettv.json"])


class Following(unittest.TestCase):
    """sweettv_play.follow: remember where an archived programme stopped."""
    SESSION = play.Session("10", "7", "Early show", NOW - 5400, NOW - 1800)

    class Io:
        def __init__(self, script):
            self.script, self.seeks, self.calls = list(script), [], 0

        def _now(self):
            self.calls += 1
            return self.script[min(self.calls - 1, len(self.script) - 1)]

        def playing(self):
            self.current = self._now()
            return self.current is not None

        def position(self):
            return self.current

        def seek(self, seconds):
            self.seeks.append(seconds)

    def run_follow(self, script, seek_to=0, stopped=None):
        reports, io = [], self.Io(script)
        play.follow(self.SESSION, io, stopped or threading.Event(), lambda *a: reports.append(a), seek_to, poll=0.001)
        return reports, io

    def test_the_last_position_seen_is_reported_when_the_player_stops(self):
        reports, _ = self.run_follow([None, (10.0, 3600.0), (500.0, 3600.0), (900.0, 3600.0), None])
        self.assertEqual(reports, [(self.SESSION, 900.0, 3600.0)])
        self.assertEqual(self.SESSION.programme(), {"epg": "7", "title": "Early show", "start": NOW - 5400, "stop": NOW - 1800})

    def test_a_stream_that_never_starts_reports_nothing(self):
        with mock.patch.object(play, "START_WAIT", 0.003):
            reports, _ = self.run_follow([None])
        self.assertEqual(reports, [])

    def test_it_seeks_once_when_the_stream_is_long_enough(self):
        reports, io = self.run_follow([(0.0, 0.0), (1.0, 100.0), (2.0, 3600.0), (901.0, 3600.0), None], seek_to=900)
        self.assertEqual(io.seeks, [900])
        self.assertEqual(reports[0][1:], (901.0, 3600.0))
        reports, io = self.run_follow([(1.0, 3600.0), None], seek_to=0)
        self.assertEqual(io.seeks, [])

    def test_a_stop_request_ends_the_watch_with_the_position_so_far(self):
        stopped = threading.Event()
        stopped.set()
        reports, _ = self.run_follow([(30.0, 100.0)], stopped=stopped)
        self.assertEqual(reports, [])                                            # it never looked: nothing started
        io = self.Io([(300.0, 3600.0)] * 3)
        stopped = threading.Event()
        reports = []

        def report(*a):
            reports.append(a)
        thread = threading.Thread(target=play.follow, args=(self.SESSION, io, stopped, report), kwargs={"poll": 0.001})
        thread.start()
        self.assertTrue(wait_for(lambda: io.calls >= 2))
        stopped.set()
        thread.join(2)
        self.assertEqual(reports[0][1:], (300.0, 3600.0))

    def test_the_player_io_never_raises(self):
        Fake.playing = False
        io = play.PlayerIO()
        self.assertFalse(io.playing())
        self.assertIsNone(io.position())                                         # the stub raises like Kodi does
        Fake.playing, Fake.position, Fake.length = True, 12.0, 60.0
        self.assertEqual(io.position(), (12.0, 60.0))
        Fake.playing = False
        self.assertEqual(json.loads(play.open_request("plugin://x"))["params"], {"item": {"file": "plugin://x"}})


class Keys(unittest.TestCase):
    def test_digits(self):
        self.assertEqual([D.digit_of(58 + n) for n in range(10)], list(range(10)))
        self.assertEqual([D.digit_of(0, 0xF000 + ord(c)) for c in "0159"], [0, 1, 5, 9])
        for action, code in ((57, 0), (68, 0), (0, 0), (3, 0), (0, 0xF000 + ord("a")), (0, 0xF000 + ord("/"))):
            self.assertIsNone(D.digit_of(action, code))

    def test_typing_a_number(self):
        self.assertEqual(D.push_digit("", 0), "")
        self.assertEqual(D.push_digit("", 4), "4")
        self.assertEqual(D.push_digit("4", 0), "40")
        self.assertEqual(D.push_digit("1234", 5), "5")
        channels = D.parse_catalog(answer(chan(1, number=1), chan(2, number=12), chan(3, number=40)), NOW).channels
        self.assertEqual(D.channel_numbered(channels, "12").cid, "2")
        self.assertIsNone(D.channel_numbered(channels, "13"))
        self.assertIsNone(D.channel_numbered(channels, ""))
        self.assertTrue(D.could_grow(channels, "1"))        # 12 could follow
        self.assertFalse(D.could_grow(channels, "12"))
        self.assertTrue(D.could_grow(channels, "4"))        # 40 could follow
        self.assertFalse(D.could_grow(channels, "40"))
        self.assertFalse(D.could_grow(channels, "7"))
        self.assertFalse(D.could_grow(channels, ""))


class Small(unittest.TestCase):
    def test_play_urls(self):
        self.assertEqual(D.play_url(123), "plugin://plugin.video.sweettv/playvid/123|null")
        self.assertEqual(D.play_url("123", 4567), "plugin://plugin.video.sweettv/playvid/123|4567")
        for bad in (("1/../2", None), ("12 ", None), ("", None), ("1)", None), ("1", "x"), ("1", "1|2"), ("-1", None)):
            self.assertEqual(D.play_url(*bad), "", bad)

    def test_which_view(self):
        full, none = demo_catalog(), D.EMPTY_CATALOG
        self.assertEqual(D.view_mode(False, full), D.SIGNIN)
        self.assertEqual(D.view_mode(False, None), D.SIGNIN)
        self.assertEqual(D.view_mode(True, full), D.DATA)
        self.assertEqual(D.view_mode(True, none), D.EMPTY)
        self.assertEqual(D.view_mode(True, None), D.EMPTY)

    def test_messages_and_staleness(self):
        self.assertFalse(D.is_stale(None, NOW))
        self.assertFalse(D.is_stale(NOW - D.STALE_AFTER, NOW))
        self.assertTrue(D.is_stale(NOW - D.STALE_AFTER - 1, NOW))

    def test_polling_is_slow_and_slower_while_channels_are_shown(self):
        self.assertGreaterEqual(D.POLL_EMPTY, 3)
        self.assertEqual(D.poll_interval(False), D.POLL_EMPTY)
        self.assertEqual(D.poll_interval(True), 60)

    def test_live_video_in_the_preview_is_off(self):
        self.assertIs(sweettv_app.PREVIEW_VIDEO, False)


class PhonePage(unittest.TestCase):
    def setUp(self):
        files.QR_FAILED.clear()

    def test_the_address_and_the_qr_of_the_phone_page(self):
        from resources.lib import net, remote
        with mock.patch.object(net, "address", return_value="192.168.1.20"), \
                mock.patch.object(remote, "page_url", return_value="http://192.168.1.20/"), \
                mock.patch.object(remote, "qr_png", return_value="/tmp/q.png") as qr:
            self.assertEqual(files.phone_page(), ("http://192.168.1.20/", "/tmp/q.png"))
        qr.assert_called_once_with("http://192.168.1.20/")
        with mock.patch.object(net, "address", return_value=""), mock.patch.object(remote, "qr_png") as qr:
            self.assertEqual(files.phone_page(), ("", ""))                       # offline: no address, no QR
        qr.assert_not_called()

    def test_a_qr_that_cannot_be_made_is_tried_once_per_address_and_the_link_stays(self):
        from resources.lib import net, remote
        with mock.patch.object(net, "address", return_value="192.168.1.20"), \
                mock.patch.object(remote, "page_url", return_value="http://192.168.1.20/"), \
                mock.patch.object(remote, "qr_png", side_effect=OSError("no qrencode")) as qr:
            self.assertEqual(files.phone_page(), ("http://192.168.1.20/", ""))
            self.assertEqual(files.phone_page(), ("http://192.168.1.20/", ""))
        self.assertEqual(qr.call_count, 1)
        with mock.patch.object(net, "address", side_effect=RuntimeError("no network stack")):
            self.assertEqual(files.phone_page(), ("", ""))

    def test_the_network_pill_has_the_address_and_the_kind_or_nothing(self):
        from resources.lib import net
        with mock.patch.object(net, "address", return_value="192.168.1.20"), mock.patch.object(net, "kind", return_value="wifi"):
            self.assertEqual(files.network(), ("192.168.1.20", "wifi"))
        with mock.patch.object(net, "address", return_value=""):
            self.assertEqual(files.network(), ("", ""))
        with mock.patch.object(net, "address", side_effect=RuntimeError("x")):
            self.assertEqual(files.network(), ("", ""))


class Words(unittest.TestCase):
    """sweettv_text: the strings of the screen."""

    def test_key_hints_leave_out_what_would_do_nothing(self):
        everything, bare = W.hint_line(True, True), W.hint_line(False, False)
        for key in ("OK", "Menu", "0-9", "Up"):
            self.assertIn(key + "[/COLOR]", everything)
        self.assertNotIn("0-9", bare)
        self.assertNotIn("Up", bare)
        self.assertIn("Favourite", bare)
        self.assertNotIn("Up", W.hint_line(True, False))
        self.assertNotIn("0-9", W.hint_line(False, True))
        self.assertEqual(everything.count("[COLOR"), everything.count("[/COLOR]"))

    def test_the_chip_says_demo_only_in_the_demo(self):
        self.assertEqual([W.chip(False, True), W.chip(False, False), W.chip(True, True), W.chip(True, False)],
                         ["Signed in", "Sign in", "Demo", "Demo"])

    def test_phone_steps_name_the_page_and_the_tab(self):
        for url, shown in (("http://192.168.1.20/", "192.168.1.20"), ("https://my-tv.duckdns.org/", "my-tv.duckdns.org")):
            steps = W.phone_steps(url)
            self.assertEqual(steps["phone_url"], shown)
            self.assertIn("SWEET.TV", steps["phone_step2"])
            self.assertIn(W.PHONE_TAB, steps["phone_step2"])
            self.assertIn(f"{W.PHONE_TAB}  >  SWEET.TV", steps["phone_step2"])
            for text in steps.values():
                self.assertNotIn("→", text)                 # the TV font draws an arrow as an empty square
        offline = W.phone_steps("")
        self.assertEqual(offline["phone_url"], "")
        self.assertIn("network", offline["phone_step1"])

    def test_the_status_card_for_each_case(self):
        loading = W.status("", False, False, 0)
        self.assertEqual((loading.kind, loading.title), ("loading", "Loading channels"))
        self.assertEqual(W.status("", True, True, 10).kind, "loading")                    # half written
        self.assertEqual(W.status("", True, False, 0), W.status("", True, False, 9999))   # a file with nothing in it
        self.assertEqual(W.status("", True, False, 0).kind, "empty")
        for waited, has_file in ((W.WAIT_LIMIT + 1, False), (W.WAIT_LIMIT + 1, True)):
            self.assertEqual(W.status("", has_file, True, waited).kind, "error")
        self.assertEqual(W.status("", False, False, W.WAIT_LIMIT).kind, "loading")        # the limit itself is still patience
        for error in ("service", "format", "something new"):
            status = W.status(error, True, False, 0)
            self.assertEqual((status.kind, status.title), ("error", "Cannot load the channels"))
            self.assertIn("!", status.glyph)
        self.assertEqual(len({W.status("", False, False, 0).tint, W.status("", True, False, 0).tint,
                              W.status("service", True, False, 0).tint}), 3)
        for status in (loading, W.status("", True, False, 0), W.status("service", True, False, 0)):
            self.assertTrue(all(status[1:]), status)
            self.assertNotIn("[", status.text + status.title + status.note)

    def test_ru_and_uk_translations_exist_for_all_msgids(self):
        for msgid, table in W.TEXT.items():
            self.assertTrue(table.get("ru"), f"missing ru translation for {msgid!r}")
            self.assertTrue(table.get("uk"), f"missing uk translation for {msgid!r}")


# ---- the window ------------------------------------------------------------------------------

def sign(signed):
    put(os.path.join(TMP, "addon_data", "plugin.video.sweettv", "settings.xml"),
        f'<settings version="2"><setting id="logged">{"true" if signed else "false"}</setting></settings>')


def write_list(raw, age=0):
    path = os.path.join(TMP, "temp", "channelList.json")
    put(path, raw if isinstance(raw, str) else json.dumps(raw))
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class WindowCase(unittest.TestCase):
    def setUp(self):
        for name in ("temp", "profile", "addon_data", "resume"):
            import shutil
            shutil.rmtree(os.path.join(TMP, name), ignore_errors=True)
        for name in ("builtins", "notes", "rpc", "rpc_threads", "played", "seeks"):
            getattr(Fake, name).clear()
        Fake.playing, Fake.stopped = False, 0
        Fake.position, Fake.length = 0.0, 0.0
        Fake.typed, Fake.asked = "", []
        Fake.home.clear()
        Fake.now = None                                             # the real clock unless a test sets one
        patch = mock.patch.object(sweettv_app, "clock", lambda: Fake.now or time.time())
        patch.start()
        self.addCleanup(patch.stop)
        poll = mock.patch.object(play, "POLL", 0.01)
        poll.start()
        self.addCleanup(poll.stop)
        patch = mock.patch.object(prefetch, "warm", side_effect=lambda *a, **k: None)      # most tests are not about the start-up run
        patch.start()
        self.addCleanup(patch.stop)
        sign(True)
        self.addCleanup(W.set_language, "en")                       # a window follows the device's language: put the tests' English back
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.stop()

    def make(self, demo=False, state=None):
        """A window set up, not yet opened."""
        if state is not None:
            S.save_state(files.state_path(), state)
        window = sweettv_app.SweetTV()
        window.setup(demo=demo)
        self.windows.append(window)
        return window

    def open(self, **kw):
        window = self.make(**kw)
        window.onInit()
        self.assertTrue(wait_for(lambda: window.looks >= 1), "the first look at the data")
        return window

    def shown(self, window):
        return [item.label for item in window.controls[ROW].items]

    def press(self, window, action_id, button=0):
        window.onAction(Action(action_id, button))

    def saved(self):
        return S.load_state(files.state_path())


class SignedOutAndEmpty(WindowCase):
    def test_signed_out_shows_one_sign_in_card_that_runs_the_existing_screen_and_reloads(self):
        sign(False)
        write_list(answer(chan(1, number=1)))                     # an old list of an old account is not shown
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        self.assertEqual((window.getProperty("mode"), window.getProperty("chip"), window.getProperty("signed")),
                         ("signin", "Sign in", ""))
        self.assertEqual(window.focus, SIGNIN)
        self.assertEqual(window.controls[ROW].items, [])
        sign(True)
        with mock.patch.object(accounts, "signin_service", return_value="done") as signin:
            window.onClick(SIGNIN)
        signin.assert_called_once_with("sweettv")
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual((window.getProperty("chip"), window.getProperty("signed")), ("Signed in", "1"))
        self.assertEqual(Fake.rpc, [])

    def test_a_sign_in_that_did_not_finish_changes_nothing(self):
        sign(False)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        with mock.patch.object(accounts, "signin_service", return_value="cancelled"):
            window.onClick(SIGNIN)
        time.sleep(0.05)
        self.assertEqual(window.mode, D.SIGNIN)

    def test_signed_in_without_a_file_says_so_and_picks_the_file_up_when_it_appears(self):
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_title") == "Loading channels"))
        self.assertEqual(window.mode, D.EMPTY)
        window._look()
        self.assertEqual(window.mode, D.EMPTY)
        write_list(answer(chan(1, "One", number=1), chan(2, "Two", number=2)))
        window._look()
        self.assertEqual(window.mode, D.DATA)
        self.assertEqual(self.shown(window), ["One", "Two"])
        self.assertEqual(window.focus, ROW)

    def test_a_half_written_or_empty_file_is_loading_then_no_channels(self):
        write_list('{"status": "OK", "list": [{"id": 1, "na')
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_title") == "Loading channels"))
        window._look()
        self.assertEqual(window.mode, D.EMPTY)
        write_list(answer())
        window._look()
        self.assertEqual((window.mode, window.getProperty("msg_title")), (D.EMPTY, "No channels yet"))
        write_list(answer(chan(1, "One")))                          # (a new size is a new stamp, whatever the clock says)
        window._look()
        self.assertEqual(window.mode, D.DATA)

    def test_a_list_that_goes_unreadable_keeps_what_is_shown(self):
        path = write_list(answer(chan(1, "One")))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        put(path, '{"status": "OK", "list": [')
        os.utime(path, (time.time() + 20, time.time() + 20))
        window._look()
        self.assertEqual((window.mode, self.shown(window)), (D.DATA, ["One"]))

    def test_a_stale_file_is_shown_with_a_notice(self):
        write_list(answer(chan(1, "One")), age=D.STALE_AFTER + 600)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(window.getProperty("notice"), sweettv_app.STALE_NOTICE)
        write_list(answer(chan(1, "One")), age=5)
        window._look()
        self.assertEqual(window.getProperty("notice"), "")

    def test_signed_out_card_gives_the_phone_page_and_its_qr(self):
        sign(False)
        with mock.patch.object(files, "phone_page", return_value=("http://192.168.1.20/", "/tmp/qr.png")):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        self.assertEqual((window.getProperty("phone_url"), window.getProperty("phone_qr")), ("192.168.1.20", "/tmp/qr.png"))
        self.assertIn(W.PHONE_TAB, window.getProperty("phone_step2"))
        self.assertEqual(window.getProperty("msg_kind"), "")
        with mock.patch.object(files, "phone_page", return_value=("", "")):             # no network: no link, no QR
            window._look()
        self.assertEqual((window.getProperty("phone_url"), window.getProperty("phone_qr")), ("", ""))
        self.assertIn("network", window.getProperty("phone_step1"))

    def test_loading_has_text_and_nothing_to_press(self):
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_kind") == "loading"))
        self.assertEqual((window.mode, window.getProperty("msg_glyph")), (D.EMPTY, "…"))
        self.assertNotEqual(window.focus, sweettv_app.RETRY)

    def test_an_empty_list_and_an_error_can_be_retried(self):
        write_list(answer())
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_kind") == "empty"))
        self.assertEqual((window.getProperty("msg_title"), window.focus), ("No channels yet", sweettv_app.RETRY))
        write_list({"status": "ERROR", "list": []})
        os.utime(files.channel_path(), (time.time() + 20, time.time() + 20))
        window._look()
        self.assertEqual((window.getProperty("msg_kind"), window.getProperty("msg_glyph")), ("error", "!"))
        self.assertEqual((window.mode, window.focus), (D.EMPTY, sweettv_app.RETRY))
        self.assertEqual(window.getProperty("msg_tint"), W.RED)
        write_list(answer(chan(1, "One", number=1)))
        os.utime(files.channel_path(), (time.time() + 40, time.time() + 40))
        window.onClick(sweettv_app.RETRY)                                               # in the background, like the poll
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(self.shown(window), ["One"])

    def test_a_list_that_never_arrives_turns_into_an_error_after_the_patience_runs_out(self):
        Fake.now = NOW
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_kind") == "loading"))
        Fake.now = NOW + W.WAIT_LIMIT - 1
        window._look()
        self.assertEqual(window.getProperty("msg_kind"), "loading")
        Fake.now = NOW + W.WAIT_LIMIT + 1
        window._look()
        self.assertEqual(window.getProperty("msg_kind"), "error")
        self.assertEqual(window.focus, sweettv_app.RETRY)
        write_list(answer(chan(1, "One")))
        window._look()
        self.assertEqual(window.mode, D.DATA)
        self.assertIsNone(window.waiting_since)

    def test_a_service_error_after_channels_were_shown_keeps_them(self):
        path = write_list(answer(chan(1, "One")))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        put(path, json.dumps({"status": "ERROR", "list": []}))
        os.utime(path, (time.time() + 20, time.time() + 20))
        window._look()
        self.assertEqual((window.mode, self.shown(window)), (D.DATA, ["One"]))
        write_list(answer(chan(1, "One"), chan(2, "Two")))
        os.utime(path, (time.time() + 40, time.time() + 40))
        window._look()
        self.assertEqual(self.shown(window), ["One", "Two"])

    def test_the_normal_screen_never_says_demo_and_the_hint_follows_the_numbers(self):
        write_list(answer(chan(1, "One", number=1)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual((window.getProperty("demo"), window.getProperty("chip")), ("", "Signed in"))
        self.assertIn("0-9", window.getProperty("hint"))
        self.assertNotIn("Up", window.getProperty("hint"))                       # no archive on this channel
        for key, value in window._window_props.items():
            if key != "demo":
                self.assertNotIn("demo", str(value).lower(), key)
        write_list(answer(chan(1, "One")))
        os.utime(files.channel_path(), (time.time() + 20, time.time() + 20))
        window._look()
        self.assertNotIn("0-9", window.getProperty("hint"))
        self.assertFalse(Fake.notes)

    def test_a_long_name_goes_to_the_card_whole_and_the_skin_cuts_it(self):
        write_list(answer(chan(1, "Sci-Fi Orbit and Beyond Network", number=1)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(self.shown(window), ["Sci-Fi Orbit and Beyond Network"])

    def test_the_network_pill_follows_the_connection(self):
        write_list(answer(chan(1, "One")))
        with mock.patch.object(files, "network", return_value=("192.168.1.20", "ethernet")):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual((window.getProperty("ip"), window.getProperty("net")), ("192.168.1.20", "ethernet"))
        with mock.patch.object(files, "network", return_value=("", "")):
            window._look()
        self.assertEqual((window.getProperty("ip"), window.getProperty("net")), ("", ""))


class Channels(WindowCase):
    def setUp(self):
        super().setUp()
        Fake.now = NOW

    def raw(self):
        return answer(chan(10, "Ten", number=10, category=[1], epg=[prog(NOW - 600, NOW + 600, "Now ten", 1, description="About ten"),
                                                                    prog(NOW + 600, NOW + 1200, "Then ten", 2)]),
                      chan(20, "Twenty", number=20, category=[2]), chan(30, "Thirty", number=30, category=[1, 2]),
                      categories=[{"id": 1, "caption": "News"}, {"id": 2, "caption": "Films"}])

    def ready(self, state=None, raw=None):
        write_list(raw or self.raw())
        window = self.open(state=state)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        return window

    def test_the_recent_channels_are_the_last_twelve_played_the_newest_first(self):
        raw = answer(*[chan(100 + n, f"C{n}", number=n + 1) for n in range(15)])
        window = self.ready(raw=raw)
        for n in range(15):
            window.controls[ROW].selected = n
            Fake.now = NOW + n
            window.onClick(ROW)
        self.assertEqual([e["id"] for e in window.state["recent"]], [str(100 + n) for n in range(14, 2, -1)])
        self.assertTrue(wait_for(lambda: self.saved()["last"] == "114"))
        self.assertEqual([e["id"] for e in self.saved()["recent"]], [str(100 + n) for n in range(14, 2, -1)])

    def test_the_file_is_read_once_per_change_and_off_the_ui_thread(self):
        write_list(self.raw())
        seen = []
        real = files.read_catalog

        def spy(path, now):
            seen.append(threading.current_thread() is threading.main_thread())
            return real(path, now)
        with mock.patch.object(files, "read_catalog", side_effect=spy):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            for _ in range(5):
                window._look()
            self.assertEqual(seen, [False])
            write_list(self.raw())
            os.utime(files.channel_path(), (time.time() + 30, time.time() + 30))
            window._look()
            self.assertEqual(len(seen), 2)

    def test_a_look_while_another_runs_does_nothing(self):
        window = self.ready()
        with mock.patch.object(files, "file_stamp") as stamp:
            window._loading.acquire()
            try:
                window._look()
            finally:
                window._loading.release()
        stamp.assert_not_called()

    def test_the_minute_tick_moves_the_programmes_on_without_touching_the_list(self):
        window = self.ready()
        card, menu_item = window.controls[ROW].items[0], window.controls[MENU].items[0]
        self.assertTrue(card.props["now"].startswith("Now ten"))
        before = window.controls[ROW].items
        Fake.now = NOW + 700
        window._look()
        self.assertEqual(card.props["now"], "Then ten")
        self.assertIs(window.controls[ROW].items, before)
        self.assertIs(window.controls[MENU].items[0], menu_item)

    def test_a_burst_of_key_presses_in_the_menu_changes_the_row_once(self):
        window = self.ready()
        window.focus = MENU
        fills = []
        real = window._open_section
        window._open_section = lambda *a, **k: (fills.append(a), real(*a, **k))[1]
        with mock.patch.object(sweettv_app, "MENU_DELAY", 0.05):
            for position in (1, 2, 1, 2):
                window.controls[MENU].selected = position
                self.press(window, KEY_DOWN)
            self.assertTrue(wait_for(lambda: fills))
            time.sleep(0.15)
        self.assertEqual([a[0] for a in fills], ["favourites"])

    def test_ok_plays_live_through_player_open_on_a_worker_thread_and_remembers_it(self):
        window = self.ready()
        window.controls[ROW].selected = 1
        window.onClick(ROW)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        request = json.loads(Fake.rpc[-1])
        self.assertEqual((request["method"], request["params"]["item"]["file"]),
                         ("Player.Open", "plugin://plugin.video.sweettv/playvid/20|null"))
        self.assertIsNot(Fake.rpc_threads[-1], threading.main_thread())
        self.assertEqual(Fake.played, [])
        self.assertTrue(wait_for(lambda: self.saved()["last"] == "20"))
        saved = self.saved()
        self.assertEqual(saved["recent"], [{"id": "20", "at": NOW}])
        self.assertIsNone(window.session)                            # live: nothing to follow

    def test_the_state_is_written_only_on_the_writers_thread_and_whole(self):
        calls, real = [], S.save_state

        def spy(path, state):
            calls.append(threading.current_thread())
            return real(path, state)
        with mock.patch.object(S, "save_state", spy):
            window = self.ready()
            window.controls[ROW].selected = 1
            window.onClick(ROW)
            window.focus = ROW
            self.press(window, 117)
            self.assertTrue(wait_for(lambda: "ch:20" in MR.fav_keys() and self.saved()["last"] == "20"))
            window.stop()
        self.assertTrue(calls)
        self.assertTrue(all(t is not threading.main_thread() for t in calls))
        self.assertEqual(len({t for t in calls}), 1)                    # one thread for all of it
        self.assertEqual(os.listdir(os.path.dirname(files.state_path())), ["sweettv.json"])      # whole file, no temp left

    def test_coming_back_from_the_player_stops_the_stream_and_keeps_the_place(self):
        window = self.ready()
        window.controls[ROW].selected = 2
        window.onClick(ROW)
        window.onInit()                                             # at once: not a return yet
        Fake.playing = True
        window.onInit()
        time.sleep(0.05)
        self.assertEqual(Fake.stopped, 0)
        window.play_at -= 10
        window.onInit()
        self.assertTrue(wait_for(lambda: Fake.stopped == 1))
        self.assertEqual(window.controls[ROW].selected, 2)
        window.onInit()
        time.sleep(0.05)
        self.assertEqual(Fake.stopped, 1)

    def test_back_from_the_player_puts_the_focus_back_where_kodi_lost_it(self):
        window = self.ready()
        window.controls[ROW].selected = 1
        window.onClick(ROW)
        window.focus = 0
        window.play_at -= 10
        window.onInit()
        self.assertTrue(wait_for(lambda: window.focus == ROW))
        self.assertEqual(window.controls[ROW].selected, 1)

    def test_the_menu_key_toggles_the_star_and_it_survives_a_restart(self):
        window = self.ready()
        window.controls[ROW].selected = 1
        window.focus = ROW
        self.press(window, 117)
        self.assertEqual(window.controls[ROW].items[1].props["fav"], "1")
        self.assertEqual(window.controls[MENU].items[2].label2, "1")
        self.assertTrue(wait_for(lambda: "ch:20" in MR.fav_keys()))
        window.stop()
        again = self.open()
        self.assertTrue(wait_for(lambda: again.mode == D.DATA))
        self.assertEqual(again.controls[ROW].items[1].props["fav"], "1")
        self.assertEqual(again.controls[ROW].items[0].props["fav"], "")
        again.controls[MENU].selected = 2
        again.onClick(MENU)
        self.assertEqual(self.shown(again), ["Twenty"])
        again.focus = ROW
        self.press(again, 117)                                      # off again, in the favourites view
        self.assertEqual(self.shown(again), [])
        self.assertTrue(wait_for(lambda: "ch:20" not in MR.fav_keys()))
        again.focus = MENU
        self.press(again, 117)                                      # on the menu the key does nothing
        self.assertEqual(self.shown(again), [])

    def test_removing_a_favourite_keeps_the_focus_close(self):
        window = self.ready(state={"favourites": ["10", "20", "30"], "recent": [], "last": ""})
        window.controls[MENU].selected = 2
        window.onClick(MENU)
        window.controls[ROW].selected = 1
        window.focus = ROW
        self.press(window, 117)
        self.assertEqual((self.shown(window), window.controls[ROW].selected), (["Ten", "Thirty"], 1))
        window.controls[ROW].selected = 1
        self.press(window, 117)
        self.assertEqual((self.shown(window), window.controls[ROW].selected), (["Ten"], 0))

    def test_number_keys_jump_to_a_channel_when_the_data_has_numbers(self):
        window = self.ready(raw=answer(chan(1, "A", number=1, category=[1]), chan(2, "B", number=12, category=[2]),
                                       chan(3, "C", number=40, category=[1]),
                                       categories=[{"id": 1, "caption": "X"}, {"id": 2, "caption": "Y"}]))
        window.onClick(404)
        self.assertEqual(self.shown(window), ["A", "C"])
        self.press(window, 58 + 4)
        self.press(window, 0, 0xF000 + ord("0"))                    # "40": a keyboard digit
        self.assertEqual(window.controls[ROW].selected, 1)
        self.assertEqual(window.getProperty("jump"), "")
        self.press(window, 58 + 1)                                  # "1": 12 could follow, so it waits
        self.assertEqual(window.getProperty("jump"), "Channel 1")
        self.assertEqual(window.controls[ROW].selected, 1)
        self.press(window, 58 + 2)                                  # "12" is in another category: All opens
        self.assertEqual(self.shown(window), ["A", "B", "C"])
        self.assertEqual(window.controls[ROW].selected, 1)
        self.assertEqual(window.controls[MENU].selected, 6)         # and the menu is on TV Channels
        self.assertEqual([i.props["active"] for i in window.controls[MENU].items][6], "1")
        self.assertEqual(window.getProperty("jump"), "")
        self.assertEqual(window.focus, ROW)
        self.press(window, 58 + 7)
        self.assertEqual(window.getProperty("jump"), "No channel 7")
        self.assertEqual(window.controls[ROW].selected, 1)

    def test_a_single_digit_waits_then_goes(self):
        window = self.ready(raw=answer(chan(1, "A", number=1), chan(2, "B", number=12)))
        window.controls[ROW].selected = 1
        with mock.patch.object(D, "DIGIT_WAIT", 0.03):
            self.press(window, 58 + 1)
            self.assertTrue(wait_for(lambda: window.controls[ROW].selected == 0 and window.getProperty("jump") == ""))

    def test_back_clears_a_typed_number_first_then_leaves(self):
        window = self.ready(raw=answer(chan(1, "A", number=1), chan(2, "B", number=12)))
        self.press(window, 58 + 1)
        self.press(window, 92)
        self.assertEqual((window.getProperty("jump"), window.closed), ("", False))
        self.press(window, 92)
        self.assertEqual((window.closed, window.focus), (False, MENU))             # up to the menu
        self.press(window, 92)
        self.assertTrue(window.closed)
        window = self.open()
        self.press(window, 10)                                                    # the other Back key goes up one step as well
        self.assertEqual((window.closed, window.focus), (False, MENU))
        self.press(window, 10)
        self.assertTrue(window.closed)

    def test_digits_do_nothing_when_no_channel_has_a_number(self):
        window = self.ready(raw=answer(chan(1, "A"), chan(2, "B")))
        self.press(window, 58 + 2)
        self.assertEqual((window.getProperty("jump"), window.controls[ROW].selected), ("", 0))

    def test_a_catalog_that_changes_keeps_the_focused_channel_and_category(self):
        window = self.ready()
        window.onClick(404)
        window.controls[ROW].selected = 1
        write_list(self.raw())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        window._look()
        self.assertEqual((self.shown(window), window.controls[ROW].selected), (["Ten", "Thirty"], 1))
        self.assertEqual(window.filter_key, "c:1")
        write_list(answer(chan(10, "Ten", number=10)))              # the categories are gone: back to the default
        os.utime(files.channel_path(), (time.time() + 90, time.time() + 90))
        window._look()
        self.assertEqual(self.shown(window), ["Ten"])
        self.assertEqual(window.filter_key, "all")

    def test_only_the_polling_the_budget_allows(self):
        waits = []

        class Stop:
            def __init__(self, window):
                self.window = window

            def wait(self, timeout):
                waits.append((timeout, self.window.mode))
                return len(waits) >= 3

            def is_set(self):
                return False

            def set(self):
                pass
        write_list(self.raw())
        window = self.make()
        window._stop = Stop(window)
        with mock.patch.object(sweettv_app, "playing", return_value=False), \
                mock.patch.object(window, "_look", side_effect=lambda: setattr(window, "mode", D.DATA)):
            window.mode = D.EMPTY
            window._watch()
        self.assertEqual(waits, [(D.POLL_EMPTY, D.EMPTY), (D.POLL_DATA, D.DATA), (D.POLL_DATA, D.DATA)])
        self.assertTrue(all(t >= 3 for t, _ in waits))

    def test_nothing_is_parsed_while_a_stream_plays(self):
        window = self.make()
        beats = []
        window._stop = types.SimpleNamespace(wait=lambda t: bool(beats) or beats.append(t), is_set=lambda: False,
                                             set=lambda: None)
        with mock.patch.object(sweettv_app, "playing", return_value=True), mock.patch.object(window, "_look") as look:
            window._watch()
        look.assert_not_called()

    def test_a_second_launch_while_open_does_nothing(self):
        write_list(self.raw())
        shown = []
        si = sweettv_app.single_instance
        with mock.patch.object(sweettv_app.ui, "load", side_effect=lambda cls, xml: self.make()), \
                mock.patch.object(WindowXML, "doModal", lambda self: shown.append(1)):
            Fake.home[sweettv_app.RUNNING] = si.encode(si.Flag("t", 14001, time.time() - 3600))   # Kodi says it is active
            self.assertFalse(sweettv_app.main(["open"]))
            Fake.home.clear()
            self.assertTrue(sweettv_app.main(["open"]))
            self.assertEqual(Fake.home[sweettv_app.RUNNING], "")
        self.assertEqual(shown, [1])

    def test_a_video_that_plays_keeps_the_app_open_behind_it(self):
        si = sweettv_app.single_instance
        Fake.home[sweettv_app.RUNNING] = si.encode(si.Flag("t", 14001, time.time() - 3600))
        with mock.patch.object(si, "window_active", return_value=False), \
                mock.patch.object(si, "video_playing", return_value=True), \
                mock.patch.object(sweettv_app.ui, "load") as load:
            self.assertFalse(sweettv_app.main(["open"]))
        load.assert_not_called()

    def test_a_flag_of_a_window_that_is_gone_does_not_block_the_launch(self):
        si = sweettv_app.single_instance
        Fake.home[sweettv_app.RUNNING] = si.encode(si.Flag("t", 14001, time.time() - 3600))
        shown = []
        with mock.patch.object(si, "window_active", return_value=False), \
                mock.patch.object(si, "video_playing", return_value=False), \
                mock.patch.object(sweettv_app.ui, "load", side_effect=lambda cls, xml: self.make()), \
                mock.patch.object(WindowXML, "doModal", lambda self: shown.append(si.decode(Fake.home[sweettv_app.RUNNING]))):
            self.assertTrue(sweettv_app.main(["open"]))
        self.assertEqual(len(shown), 1)
        self.assertNotEqual(shown[0].token, "t")
        self.assertEqual(Fake.home.get(sweettv_app.RUNNING), "")

    def test_an_old_flag_that_is_not_in_the_new_format_is_stale(self):
        Fake.home[sweettv_app.RUNNING] = "1"        # what the app set before the flag knew its window
        si = sweettv_app.single_instance
        with mock.patch.object(si, "window_active", return_value=False), \
                mock.patch.object(si, "video_playing", return_value=False), \
                mock.patch.object(sweettv_app.ui, "load", side_effect=lambda cls, xml: self.make()), \
                mock.patch.object(WindowXML, "doModal", lambda self: None):
            self.assertTrue(sweettv_app.main(["open"]))

    def test_the_window_tells_the_flag_its_id_when_it_opens(self):
        si = sweettv_app.single_instance
        window = self.make(demo=True)
        window.instance = si.claim(xbmcgui.Window(sweettv_app.ui.HOME), sweettv_app.RUNNING)
        with mock.patch.object(xbmcgui, "getCurrentWindowId", create=True, return_value=14002):
            window.onInit()
        self.assertEqual(si.decode(Fake.home[sweettv_app.RUNNING]).window_id, 14002)


class Language(WindowCase):
    """The strings of the window follow the device's language (mediastick_lang): the launcher's Home property, else the file."""

    def raw(self):
        return answer(chan(10, "Ten", number=10, category=[1], catchup=True,
                           epg=[prog(NOW - 7200, NOW - 3600, "Old ten", 3), prog(NOW - 600, NOW + 600, "Now ten", 1),
                                prog(NOW + 600, NOW + 1200, "Then ten", 2)]),
                      chan(20, "Twenty", number=20, category=[1]), categories=[{"id": 1, "caption": "News"}])

    def window(self, lang, **kw):
        Fake.now = NOW
        Fake.home["media-stick.lang"] = lang
        write_list(self.raw())
        window = self.open(**kw)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        return window

    def test_the_language_is_the_launchers_property_then_the_file_then_russian(self):
        self.assertEqual(files.language(), "en")                                    # the file of these tests
        for chosen, said in (("ru", "ru"), ("uk", "uk"), ("be", "ru"), ("de", "en"), ("en_US", "en"), ("pl", "pl"), ("xx", "ru")):
            Fake.home["media-stick.lang"] = chosen
            self.assertEqual(files.language(), said, chosen)
        Fake.home.clear()
        with mock.patch.dict(os.environ), mock.patch("mediastick_lang.DIR", os.path.join(TMP, "nothing")):
            self.assertEqual(files.language(), "ru")                                  # no choice was ever made
        with mock.patch.dict(sys.modules, {"mediastick_lang": None}):
            self.assertEqual(files.language(), "ru")                                  # no library: the device's default

    def test_in_russian_the_menu_the_hint_and_the_chip_are_russian(self):
        window = self.window("ru", state={"favourites": [], "recent": recent("10"), "last": "10"})
        menu = window.controls[MENU].items
        self.assertEqual([i.label for i in menu], ["Поиск", "Продолжить", "Избранное", "Шоу", "Сериалы", "Фильмы", "ТВ-каналы"])
        self.assertEqual(window.getProperty("hint"),
                         W.hint_line(True, True))
        for word in ("Смотреть", "Меню", "Избранное", "0-9", "Номер канала", "Вверх", "Программа и продолжение"):
            self.assertIn(word, window.getProperty("hint"))
        for word in ("Watch", "Favourite", "Channel number", "Guide and continue"):
            self.assertNotIn(word, window.getProperty("hint"))
        self.assertEqual(window.getProperty("chip"), "Вход выполнен")
        self.assertEqual((window.getProperty("l_catchup"), window.getProperty("l_favourite"), window.getProperty("l_guide")),
                         ("Архив", "Избранное", "Программа передач"))
        card = window.controls[ROW].items[0]
        self.assertEqual((card.props["meta"], card.props["nowline"], card.props["nextline"], card.props["resume"]),
                         ("Канал 10  ·  News", "Сейчас   07:50 – 08:10", "Далее   08:10 – 08:20   Then ten", ""))
        self.assertEqual(window.controls[MENU].selected, 6)
        menu_empty = window.controls[MENU]
        menu_empty.selected = 2
        window.onClick(MENU)
        self.assertTrue(window.getProperty("emptycat").startswith("Избранного пока нет"))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.press(window, 58 + 1)
        self.assertEqual(window.getProperty("jump"), "Канал 1")
        self.assertEqual(W.LANG, "ru")

    def test_the_resume_button_and_the_guide_are_russian(self):
        doc = MR.record(MR.empty(), "plugin://plugin.video.sweettv/playvid/10|3", 900, 3600, NOW,
                        {"title": "Old ten", "start": NOW - 7200, "stop": NOW - 3600})
        MR.save(doc)
        window = self.window("ru")
        self.assertEqual(window.controls[ROW].items[0].props["resume"], "Продолжить с 15:00")
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        window.focus = ROW
        with mock.patch.object(API, "day", return_value={
                "ok": True, "cid": "10", "name": "Ten", "date": "2027-01-15", "now": NOW,
                "archive_days": 1, "future_days": 3,
                "items": [{"epg": "1", "cid": "10", "title": "Now ten", "start": NOW - 600, "stop": NOW + 600,
                           "when": "07:50", "live": True, "playable_in_archive": True, "available": True,
                           "preview": "", "season": 0, "episode": 0, "show_id": ""}]}):
            window._guide_show()
            self.assertTrue(wait_for(lambda: len(window.controls[GUIDE].items) >= 1))
        self.assertEqual([i.label2 for i in window.controls[GUIDE].items][:1], ["В эфире"])

    def test_in_ukrainian_the_same(self):
        window = self.window("uk")
        self.assertEqual([i.label for i in window.controls[MENU].items],
                         ["Пошук", "Продовжити", "Обране", "Шоу", "Серіали", "Фільми", "ТБ-канали"])
        self.assertEqual((window.getProperty("chip"), window.getProperty("l_retry")), ("Вхід виконано", "Повторити"))

    def test_in_english_and_in_any_language_without_translation_the_strings_are_the_msgids(self):
        for lang in ("en", "de"):
            window = self.window(lang)
            self.assertEqual([i.label for i in window.controls[MENU].items],
                             ["Search", "Continue", "Favourites", "Shows", "Series", "Movies", "TV Channels"])
            self.assertEqual((window.getProperty("chip"), window.getProperty("l_guide")), ("Signed in", "Programme guide"))
            self.assertEqual(window.controls[ROW].items[0].props["meta"], "Channel 10  ·  News")
            window.stop()

    def test_the_status_and_the_sign_in_card_and_the_notices_are_russian(self):
        Fake.home["media-stick.lang"] = "ru"
        window = self.open()                                                    # signed in, no list yet
        self.assertEqual((window.getProperty("msg_kind"), window.getProperty("msg_title")), ("loading", "Загрузка каналов"))
        sign(False)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        self.assertEqual(window.getProperty("chip"), "Войти")
        self.assertIn("Вкладка", window.getProperty("phone_step2"))
        self.assertIn(W.PHONE_TAB, window.getProperty("phone_step2"))
        sign(True)
        write_list(self.raw(), age=3 * 3600)
        stale = self.open()
        self.assertTrue(wait_for(lambda: stale.mode == D.DATA))
        self.assertEqual(stale.getProperty("notice"), "Список каналов устарел. Обновляется…")
        demo = self.open(demo=True)
        self.assertTrue(wait_for(lambda: demo.mode == D.DATA))
        self.assertEqual(demo.getProperty("chip"), "Демо")
        demo.controls[ROW].selected = 0
        demo.onClick(ROW)
        self.assertEqual(Fake.notes[-1:], ["Демо: ничего не воспроизводится."])


class Demo(WindowCase):
    def test_demo_is_marked_fills_all_seven_sections_and_never_touches_real_data(self):
        write_list(answer(chan(1, "Real")))
        with mock.patch.object(files, "file_stamp", side_effect=AssertionError("real file")), \
                mock.patch.object(files, "signed_in", side_effect=AssertionError("real login")), \
                mock.patch.object(API, "top_search", side_effect=AssertionError("network")), \
                mock.patch.object(API, "shows", side_effect=AssertionError("network")), \
                mock.patch.object(API, "catalog_page", side_effect=AssertionError("network")):
            window = self.open(demo=True)
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertEqual((window.getProperty("demo"), window.getProperty("chip")), ("1", "Demo"))
            self.assertEqual([i.getProperty("section") or i.getProperty("key") for i in window.controls[MENU].items],
                             ["search", "continue", "favourites", "shows", "series", "movies", "channels"])
            for idx in range(7):
                window.controls[MENU].selected = idx
                window.onClick(MENU)
                self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0), f"demo section {idx} empty")
                self.assertNotIn("Real", self.shown(window))
            window._look()
            self.assertEqual(window.mode, D.DATA)

    def test_demo_opens_show_episodes_modal_and_channel_guide_modal_offline(self):
        with mock.patch.object(API, "show_detail", side_effect=AssertionError("network")), \
                mock.patch.object(API, "day", side_effect=AssertionError("network")):
            window = self.open(demo=True)
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            # Shows section (index 3) -> OK opens Show Episodes modal (400 + 410)
            window.controls[MENU].selected = 3
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) > 0))
            self.assertGreater(len(window.controls[410].items), 0)
            self.press(window, 92)
            # Channels section (index 6) -> Hero 212 opens 7-day Channel Guide modal (400 + 410)
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
            window.controls[ROW].selected = 0
            window.onClick(212)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) > 0))
            self.assertGreater(len(window.controls[410].items), 0)

    def test_demo_logos_exist_where_the_cards_point(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
        logos = {i.art["icon"] for i in window.controls[ROW].items if i.art and i.art.get("icon")}
        self.assertEqual(len(logos), sweettv_demo.LOGOS)
        for logo in logos:
            self.assertTrue(os.path.isfile(logo), logo)
            self.assertLess(os.path.getsize(logo), 20000, logo)
        self.assertTrue(any(not i.art for i in window.controls[ROW].items))      # the badge case

    def test_demo_never_plays_never_saves_and_says_so(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertIsNone(window.writer)
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
        window.controls[ROW].selected = 0
        window.onClick(ROW)
        window.focus = ROW
        self.press(window, 117)
        window.onClick(212)
        window.controls[GUIDE].selected = 1
        window.onClick(GUIDE)
        time.sleep(0.05)
        self.assertEqual(Fake.rpc, [])
        self.assertEqual(Fake.played, [])
        self.assertEqual(Fake.builtins, [])
        self.assertTrue(all(n == "Demo: nothing is played." for n in Fake.notes) and Fake.notes)
        self.assertFalse(os.path.exists(files.state_path()))
        self.assertEqual(window.play_at, 0.0)
        self.assertIsNone(window.session)

    def test_the_star_works_in_the_demo_and_is_gone_with_it(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
        was = window.controls[ROW].items[0].props.get("fav", "")
        window.focus = ROW
        self.press(window, 117)
        self.assertEqual(window.controls[ROW].items[0].props.get("fav", ""), "" if was else "1")
        self.assertFalse(os.path.exists(files.state_path()))

    def test_demo_entry_point_through_main(self):
        seen = []
        with mock.patch.object(WindowXML, "doModal", lambda self: seen.append(self.demo)), \
                mock.patch.object(sweettv_app.ui, "load", side_effect=lambda cls, xml: cls()):
            sweettv_app.main(["demo"])
            sweettv_app.main(["open"])
            sweettv_app.main([])
        self.assertEqual(seen, [True, False, False])


class PreviewVideo(WindowCase):
    """The switch is off; with it on the pieces are there (unverified on the device)."""

    def setUp(self):
        super().setUp()
        Fake.now = NOW
        write_list(answer(chan(10, "Ten", number=10), chan(20, "Twenty", number=20)))

    def test_off_nothing_plays_in_the_preview_and_the_skin_has_no_video_window_to_show(self):
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.press(window, 2)
        time.sleep(0.05)
        self.assertEqual((window.getProperty("preview_video"), Fake.played), ("", []))

    def test_on_the_focused_channel_plays_in_the_window_and_ok_makes_it_big(self):
        with mock.patch.object(sweettv_app, "PREVIEW_VIDEO", True), mock.patch.object(sweettv_app, "PREVIEW_DELAY", 0.01):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertEqual(window.getProperty("preview_video"), "1")
            window.controls[ROW].selected = 1
            self.press(window, KEY_RIGHT)
            self.assertTrue(wait_for(lambda: Fake.played))
            self.assertEqual(Fake.played[-1], (("plugin://plugin.video.sweettv/playvid/20|null", None, True), {}))
            Fake.playing = True
            window.onClick(ROW)
            self.assertEqual(Fake.builtins, ["Action(FullScreen)"])
            self.assertEqual(Fake.rpc, [])
            window.play_at -= 10
            window.onInit()
            time.sleep(0.05)
            self.assertEqual(Fake.stopped, 0)                        # coming back leaves the preview running


# ---- the sections: channels, shows and series, films -----------------------------------------

BACK = 92
NS = PG.namespace()


def _sample_movie(mid=501, title="Inception", year=2010, imdb=8.8, duration=8880, owner_id=10, genres=(12,)):
    return {"id": mid, "title": title, "owner_id": owner_id, "poster": f"https://img/{mid}.jpg",
            "banner": f"https://img/{mid}-bg.jpg", "year": year, "duration": duration, "imdb": imdb,
            "genres": list(genres), "vod_url": f"plugin://plugin.video.sweettv/playvod/{mid}|null|{owner_id}", "available": True}


def _sample_config():
    return {"ok": True,
            "genres": [{"id": 12, "name": "Sci-Fi"}, {"id": 14, "name": "Comedy"}],
            "sort_modes": [{"id": 1, "name": "Popular"}, {"id": 3, "name": "IMDb Rating"},
                           {"id": 2, "name": "Newest"}, {"id": 5, "name": "A-Z"}]}


def _sample_shows():
    return {"ok": True, "items": [
        {"kind": "show_vod", "id": "vod:701", "movie_id": "701", "owner_id": 11, "title": "Holostyak",
         "poster": "https://img/701.jpg", "banner": "https://img/701-bg.jpg", "year": 2025, "imdb": 7.5,
         "vod_url": "plugin://plugin.video.sweettv/playvod/701|null|11"},
        {"kind": "show_epg", "id": "epg:801", "collection_id": "801", "channel_ids": ["10"],
         "curated_epg_ids": ["901"], "title": "MasterChef",
         "poster": "https://img/801.jpg", "banner": "https://img/801-bg.jpg"},
    ]}


class NetflixRail(WindowCase):
    """Left navigation rail (id=100): 7 fixed top-level sections, no 18 genre rows."""

    def test_rail_has_seven_fixed_sections_in_order(self):
        write_list(answer(chan(10, "Ten", number=10, category=[1]), chan(20, "Twenty", number=20, category=[2]),
                          categories=[{"id": 1, "caption": "News"}, {"id": 2, "caption": "Films"}]))
        with mock.patch.object(API, "top_search", return_value={"ok": True, "items": [], "count": 0}), \
                mock.patch.object(API, "shows", return_value={"ok": True, "items": []}), \
                mock.patch.object(API, "catalog_page", return_value={"ok": True, "section": "movies", "items": [], "total": 0}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            items = window.controls[MENU].items
            self.assertEqual(len(items), 7)
            self.assertEqual([i.getProperty("section") or i.getProperty("key") for i in items],
                             ["search", "continue", "favourites", "shows", "series", "movies", "channels"])
            self.assertNotIn("Genres", [i.label for i in items])

    def test_filter_chips_visible_only_on_filtered_sections(self):
        write_list(answer(chan(10, "Ten", number=10, category=[1]), categories=[{"id": 1, "caption": "News"}]))
        with mock.patch.object(API, "top_search", return_value={"ok": True, "items": [], "count": 0}), \
                mock.patch.object(API, "shows", return_value={"ok": True, "items": []}), \
                mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", return_value={"ok": True, "section": "movies", "items": [_sample_movie()], "total": 1}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            expected_visible = {"search": True, "continue": False, "favourites": False,
                                "shows": False, "series": True, "movies": True, "channels": True}
            for idx, sec in enumerate(["search", "continue", "favourites", "shows", "series", "movies", "channels"]):
                window.controls[MENU].selected = idx
                window.onClick(MENU)
                self.assertEqual(bool(window.getProperty("filters")), expected_visible[sec], sec)


class SearchSection(WindowCase):
    """Search section: top_search before typing, keyboard -> search()."""

    def test_search_shows_top_search_before_typing(self):
        write_list(answer(chan(10, "Ten", number=10)))
        top = {"ok": True, "items": [
            {"kind": "movie", "id": "501", "title": "Top Film", "subtitle": "2024", "cid": "", "epg": "",
             "start": 0, "stop": 0, "channel_name": "", "when": "", "live": False, "playable_in_archive": False,
             "playable": True, "available": True, "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|0",
             "preview": "", "image_url": "https://img/501.jpg", "repeats": 0, "more": ""},
        ], "count": 1}
        with mock.patch.object(API, "top_search", return_value=top) as m_top:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 0
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 1))
            m_top.assert_called()
            self.assertEqual(window.controls[ROW].items[0].label, "Top Film")

    def test_search_ok_opens_keyboard_and_queries_sweetapi_search(self):
        write_list(answer(chan(10, "Ten", number=10)))
        Fake.typed = "Matrix"
        found = {"ok": True, "query": "Matrix", "items": [
            {"kind": "programme", "id": "77", "title": "Matrix Reloaded", "subtitle": "", "cid": "10", "epg": "77",
             "start": NOW - 3600, "stop": NOW - 1800, "channel_name": "Ten", "when": "07:00", "live": False,
             "playable_in_archive": True, "playable": True, "available": True, "preview": "", "image_url": "",
             "repeats": 0, "more": ""},
        ], "count": 1}
        with mock.patch.object(API, "top_search", return_value={"ok": True, "items": [], "count": 0}), \
                mock.patch.object(API, "search", return_value=found) as m_search:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 0
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: m_search.called or window.focus == ROW))
            if not m_search.called:
                window.onClick(MENU)
            self.assertTrue(wait_for(lambda: m_search.called))
            self.assertEqual(window.controls[ROW].items[0].label, "Matrix Reloaded")


class ContinueAndFavourites(WindowCase):
    """Continue & Favourites use item-level mediastick_resume without per-channel overwrite."""

    def test_continue_reads_item_level_resume_without_per_channel_overwrite(self):
        write_list(answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=3,
                               epg=[prog(NOW - 7200, NOW - 3600, "Show Ep 1", 101),
                                    prog(NOW - 3600, NOW - 1800, "Show Ep 2", 102)])))
        doc = MR.empty()
        doc = MR.record(doc, "plugin://plugin.video.sweettv/playvid/10|101", 600, 3600, NOW - 100,
                        {"title": "Show Ep 1", "start": NOW - 7200, "stop": NOW - 3600})
        doc = MR.record(doc, "plugin://plugin.video.sweettv/playvid/10|102", 400, 1800, NOW - 50,
                        {"title": "Show Ep 2", "start": NOW - 3600, "stop": NOW - 1800})
        doc = MR.record(doc, "plugin://plugin.video.sweettv/playvod/501|null|10", 1200, 7200, NOW - 20,
                        {"title": "Inception"})
        doc = MR.record(doc, "plugin://plugin.video.sweettv/playvod/502|9001|10", 300, 2400, NOW - 10,
                        {"title": "Series S1 E1"})
        MR.save(doc)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 1
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) >= 4))
        labels = [i.label for i in window.controls[ROW].items]
        self.assertIn("Show Ep 1", labels)
        self.assertIn("Show Ep 2", labels)
        self.assertIn("Inception", labels)
        self.assertIn("Series S1 E1", labels)

    def test_favourites_loads_mediastick_resume_favs_and_migrates_legacy_state(self):
        write_list(answer(chan(10, "Ten", number=10), chan(20, "Twenty", number=20)))
        window = self.open(state={"favourites": ["10", "20"], "recent": [], "last": "", "resume": {}})
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertTrue({"ch:10", "ch:20"}.issubset(MR.fav_keys()))
        MR.toggle_fav("vod:501", {"title": "Inception"}, now=NOW)
        window.controls[MENU].selected = 2
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) >= 3))
        labels = [i.label for i in window.controls[ROW].items]
        self.assertIn("Ten", labels)
        self.assertIn("Twenty", labels)
        self.assertIn("Inception", labels)

    def test_favourite_toggle_via_hero_213_and_context_menu(self):
        write_list(answer(chan(10, "Ten", number=10)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 1))
        window.focus = ROW
        window.controls[ROW].selected = 0
        window.onClick(213)
        self.assertTrue(wait_for(lambda: "ch:10" in MR.fav_keys()))
        self.press(window, 117)
        self.assertTrue(wait_for(lambda: "ch:10" not in MR.fav_keys()))


class ShowsSection(WindowCase):
    """Shows section: unified VOD + EPG shows and Seasons/Episodes modal."""

    def test_shows_loads_unified_vod_and_epg_shows(self):
        write_list(answer(chan(10, "Ten", number=10)))
        with mock.patch.object(API, "shows", return_value=_sample_shows()) as m_shows:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 3
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 2))
            m_shows.assert_called()
            self.assertEqual([i.label for i in window.controls[ROW].items], ["Holostyak", "MasterChef"])

    def test_ok_on_show_opens_seasons_and_episodes_modal(self):
        write_list(answer(chan(10, "Ten", number=10)))
        detail = {"ok": True, "id": "vod:701", "movie_id": "701", "title": "Holostyak",
                  "poster": "", "banner": "", "year": 2025, "duration": 0, "imdb": 7.5, "owner_id": 11,
                  "favourite": False, "resume": 0, "watched": False, "vod_url": "",
                  "seasons": [
                      {"id": 1, "title": "Season 1", "owner_id": 11,
                       "episodes": [{"id": 7011, "episode_id": 7011, "number": 1, "title": "Ep 1",
                                     "duration": 3600, "preview": "", "owner_id": 11,
                                     "vod_url": "plugin://plugin.video.sweettv/playvod/701|7011|11",
                                     "resume": 0, "watched": False}]},
                  ]}
        with mock.patch.object(API, "shows", return_value=_sample_shows()), \
                mock.patch.object(API, "show_detail", return_value=detail) as m_det:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 3
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 2))
            window.focus = ROW
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) == 1))
            m_det.assert_called()
            self.assertEqual(len(window.controls[410].items), 1)
            self.assertEqual(window.controls[400].items[0].label, "Ep 1")


class CatalogSections(WindowCase):
    """Series & Movies: catalog_page, filter chips, infinite pagination, and playback."""

    def test_movies_flat_grid_and_series_paginated_via_catalog_page(self):
        write_list(answer(chan(10, "Ten", number=10)))
        movies = {"ok": True, "section": "movies", "items": [_sample_movie(501, "Film A")], "total": 1}
        series = {"ok": True, "section": "series", "items": [_sample_movie(601, "Series A")], "total": 1}
        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", side_effect=lambda sec, **kw: series if sec == "series" else movies) as m_cat:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Film A"]))
            window.controls[MENU].selected = 4
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Series A"]))
            self.assertGreaterEqual(m_cat.call_count, 2)

    def test_filter_chips_load_genres_from_configuration_and_cycle_sort_mode(self):
        write_list(answer(chan(10, "Ten", number=10)))
        seen_calls = []

        def fake_cat(sec, genre_id=0, sort_mode_id=1, offset=0, limit=30, **kw):
            seen_calls.append((sec, genre_id, sort_mode_id, offset))
            return {"ok": True, "section": sec, "items": [_sample_movie(501, "Film A")], "total": 1}

        with mock.patch.object(API, "configuration", return_value=_sample_config()) as m_cfg, \
                mock.patch.object(API, "catalog_page", side_effect=fake_cat):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(seen_calls) >= 1))
            m_cfg.assert_called()
            window.onClick(402)
            self.assertTrue(wait_for(lambda: any(c[1] != 0 or c[2] != 1 for c in seen_calls)), seen_calls)

    def test_infinite_pagination_loads_next_page_when_focusing_last_row(self):
        write_list(answer(chan(10, "Ten", number=10)))
        page1 = [_sample_movie(100 + i, f"Film {i}") for i in range(8)]
        page2 = [_sample_movie(200 + i, f"Film {8 + i}") for i in range(4)]

        def fake_cat(sec, genre_id=0, sort_mode_id=1, offset=0, limit=30, **kw):
            return {"ok": True, "section": sec, "items": page2 if offset > 0 else page1, "total": 12}

        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", side_effect=fake_cat):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 8))
            window.focus = ROW
            window.controls[ROW].selected = 7
            self.press(window, KEY_DOWN)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 12))

    def test_ok_on_movie_plays_vod_and_ok_on_series_opens_modal(self):
        write_list(answer(chan(10, "Ten", number=10)))
        movies = {"ok": True, "section": "movies", "items": [_sample_movie(501, "Film A")], "total": 1}
        series = {"ok": True, "section": "series", "items": [_sample_movie(601, "Series A")], "total": 1}
        detail = {"ok": True, "id": "vod:601", "movie_id": "601", "title": "Series A",
                  "poster": "", "banner": "", "year": 2024, "duration": 0, "imdb": 8.0, "owner_id": 10,
                  "favourite": False, "resume": 0, "watched": False, "vod_url": "",
                  "seasons": [{"id": 1, "title": "Season 1", "owner_id": 10, "episodes": [
                      {"id": 6011, "episode_id": 6011, "number": 1, "title": "Pilot", "duration": 2400,
                       "preview": "", "owner_id": 10, "vod_url": "plugin://plugin.video.sweettv/playvod/601|6011|10",
                       "resume": 0, "watched": False}]}]}
        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", side_effect=lambda sec, **kw: series if sec == "series" else movies), \
                mock.patch.object(API, "vod_detail", return_value=detail):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Film A"]))
            window.focus = ROW
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 1))
            self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"],
                             "plugin://plugin.video.sweettv/playvod/501|null|10")
            window.controls[MENU].selected = 4
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Series A"]))
            window.focus = ROW
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) == 1))
            self.assertEqual(window.controls[400].items[0].label, "Pilot")


class ChannelsSection(WindowCase):
    """Channels section: all playable channels, 24/7 FAST chip, Hero 211/212, and 0-9 jump."""

    def test_channels_shows_all_playable_and_filters_fast_24_7_and_genres(self):
        raw = answer(
            chan(10, "Live One", number=1, category=[1], is_fast_channel=False, tariff_id=0),
            chan(20, "Premium Two", number=2, category=[1], is_fast_channel=False, tariff_id=99),
            chan(30, "24/7 Comedy", number=3, category=[2], is_fast_channel=True),
            categories=[{"id": 1, "caption": "News"}, {"id": 2, "caption": "Comedy"}],
        )
        write_list(raw)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 3))
        self.assertEqual(self.shown(window), ["Live One", "Premium Two", "24/7 Comedy"])
        fast_chip = next((cid for cid in range(401, 409) if "24/7" in window.controls[cid].getLabel()), None)
        self.assertIsNotNone(fast_chip, "24/7 FAST chip missing from 401..408")
        window.onClick(fast_chip)
        self.assertEqual(self.shown(window), ["24/7 Comedy"])

    def test_ok_on_channel_plays_live_and_hero_211_starts_from_zero_and_212_opens_guide(self):
        Fake.now = NOW
        raw = answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=7,
                          epg=[prog(NOW - 600, NOW + 600, "Now ten", 9)]))
        write_list(raw)
        with mock.patch.object(API, "day", return_value={
                "ok": True, "cid": "10", "name": "Ten", "date": "2027-01-15", "now": NOW,
                "archive_days": 7, "future_days": 3,
                "items": [{"epg": "9", "cid": "10", "title": "Now ten", "start": NOW - 600, "stop": NOW + 600,
                           "when": "07:50", "live": True, "playable_in_archive": True, "available": True,
                           "preview": "", "season": 0, "episode": 0, "show_id": ""}]}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Ten"]))
            window.focus = ROW
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 1))
            self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"],
                             "plugin://plugin.video.sweettv/playvid/10|null")
            window.onClick(211)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 2))
            self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"],
                             "plugin://plugin.video.sweettv/playvid/10|9")
            window.onClick(212)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) >= 1))
            self.assertGreater(len(window.controls[410].items), 1)


class HeroBanner(WindowCase):
    """Top Netflix Hero Banner (210..213) reflects focused item and contextual actions."""

    def test_hero_displays_focused_item_metadata_and_contextual_buttons(self):
        write_list(answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=3,
                               epg=[prog(NOW - 600, NOW + 600, "Now ten", 9, description="Live desc")])))
        movies = {"ok": True, "section": "movies", "items": [_sample_movie(501, "Inception", year=2010, imdb=8.8)], "total": 1}
        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", return_value=movies):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Inception"]))
            window.focus = ROW
            window.controls[ROW].selected = 0
            self.assertIn("Inception", window.getProperty("hero_title") or window.controls[ROW].items[0].props.get("title", ""))
            self.assertTrue(window.controls[210].getLabel() or window.getProperty("l_play") or window.getProperty("hero_play"))
            self.assertTrue(window.controls[213].getLabel() or window.getProperty("hero_fav"))


class Modals(WindowCase):
    """Modal overlay (400 + 410): Back closes modal and restores exact grid focus."""

    def test_back_closes_modal_and_restores_exact_grid_focus(self):
        write_list(answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=3,
                               epg=[prog(NOW - 600, NOW + 600, "Now ten", 9)]),
                          chan(20, "Twenty", number=20, catchup=True, catchup_duration=3,
                               epg=[prog(NOW - 600, NOW + 600, "Now twenty", 21)])))
        with mock.patch.object(API, "day", return_value={
                "ok": True, "cid": "20", "name": "Twenty", "date": "2027-01-15", "now": NOW,
                "archive_days": 3, "future_days": 3,
                "items": [{"epg": "21", "cid": "20", "title": "Now twenty", "start": NOW - 600, "stop": NOW + 600,
                           "when": "07:50", "live": True, "playable_in_archive": True, "available": True,
                           "preview": "", "season": 0, "episode": 0, "show_id": ""}]}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 2))
            window.focus = ROW
            window.controls[ROW].selected = 1
            window.onClick(212)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) >= 1))
            self.press(window, BACK)
            self.assertFalse(window.getProperty("guide") or window.getProperty("modal"))
            self.assertEqual((window.focus, window.controls[ROW].selected), (ROW, 1))


class PageValues(unittest.TestCase):
    """sweettv_pages: VERSION 4, paginated slices <= 50 items, page_cache < 512 KB."""

    def test_version_4_and_paginated_slices_under_50_items_and_512kb(self):
        self.assertEqual(PG.VERSION, 4)
        self.assertEqual(NS, "sweettv:main")
        for bad in (None, "", 7, "a b", "x" * 41, "a:b", "../x"):
            self.assertIsNone(PG.namespace(bad), bad)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(page_cache, "DIR", folder):
            slice_50 = [_sample_movie(i, f"Film {i}") for i in range(1, 51)]
            val = PG.to_value("Movies", slice_50, 200)
            self.assertIsNotNone(PG.from_value("movies", val))
            slice_51 = [_sample_movie(i, f"Film {i}") for i in range(1, 52)]
            self.assertIsNone(PG.from_value("movies", PG.to_value("Movies", slice_51, 200)))
            self.assertTrue(page_cache.put(NS, "movies:0:1:0", val))
            names = os.listdir(folder)
            self.assertEqual(len(names), 1)
            size = os.path.getsize(os.path.join(folder, names[0]))
            self.assertLess(size, 512 * 1024)


def count_pictures(node):
    """Pictures a node draws at once: images and buttons (one texture each), not looking inside lists/panels."""
    total = 0
    for child in node:
        if child.tag != "control":
            continue
        kind = child.get("type")
        if kind in ("image", "button"):
            total += 1
        elif kind not in ("list", "panel"):
            total += count_pictures(child)
    return total


class Skin(unittest.TestCase):
    def tree(self, name="script-media-stick-sweettv.xml"):
        return ET.parse(os.path.join(SKIN, name)).getroot()

    def control(self, root, control_id):
        return next(c for c in root.iter("control") if c.get("id") == str(control_id))

    def test_panel_grid_4x2_rail_hero_buttons_filter_chips_and_modal(self):
        root = self.tree()
        self.assertEqual(root.tag, "window")
        types_ = {int(c.get("id")): c.get("type") for c in root.iter("control") if c.get("id", "").isdigit()}
        self.assertEqual(types_[100], "list")
        self.assertEqual(types_[200], "panel")
        for btn in (210, 211, 212, 213, 300, 301):
            self.assertEqual(types_.get(btn), "button", btn)
        self.assertEqual(types_[400], "list")
        self.assertIn(types_.get(410), ("list", "grouplist"))
        for cid in range(401, 409):
            self.assertIn(cid, types_, cid)
        panel = self.control(root, 200)
        self.assertEqual(panel.findtext("orientation"), "vertical")
        cols = int(panel.findtext("width")) // int(panel.find("itemlayout").get("width"))
        rows = int(panel.findtext("height")) // int(panel.find("itemlayout").get("height"))
        self.assertEqual((cols, rows), (4, 2))
        for node in panel.iter("texture"):
            if "ListItem.Art" in (node.text or ""):
                self.assertEqual(node.get("background"), "true")

    def test_visible_textures_at_most_34_in_all_states(self):
        root = self.tree()
        top = [c for c in root.find("controls") if c.tag == "control"]
        static_pics = sum(1 for c in top if c.get("type") in ("image", "button"))
        panel = self.control(root, 200)
        panel_pics_per_card = count_pictures(panel.find("focusedlayout"))
        self.assertLessEqual(static_pics + 8 * panel_pics_per_card, 34)

    def test_brand_palette_navy_and_turquoise_no_netflix_red(self):
        text = ET.tostring(self.tree(), encoding="unicode")
        self.assertNotIn("E50914", text.upper())
        self.assertIn("0C111B", text.upper())
        self.assertTrue("00D2C6" in text.upper() or "14E0C8" in text.upper())

    def test_selectedcolor_on_every_panel_and_list_label(self):
        root = self.tree()
        for container in list(root.iter("control")):
            if container.get("type") not in ("list", "panel"):
                continue
            for layout in list(container.iter("itemlayout")) + list(container.iter("focusedlayout")):
                for label in (c for c in layout.iter("control") if c.get("type") == "label"):
                    self.assertIsNotNone(label.find("selectedcolor"), label.findtext("label"))
                    self.assertEqual(label.findtext("selectedcolor"), label.findtext("textcolor"))

    def test_zero_literal_xml_text_and_l_property_parity(self):
        root = self.tree()
        for node in root.iter("label"):
            val = (node.text or "").strip()
            self.assertTrue(val == "" or val in ("SWEET.TV", "DEMO") or "$" in val, f"literal XML label: {val!r}")
        text = "".join(ET.tostring(root, encoding="unicode").split())
        xml_l_props = set(re.findall(r"Window\.Property\((l_\w+)\)", text))
        self.assertEqual(xml_l_props, set(W.labels()))

    def test_9_slice_borders(self):
        root = self.tree()
        for node in root.iter("control"):
            texture = node.find("texture")
            if node.get("type") == "image" and texture is not None and texture.get("border"):
                border = int(texture.get("border"))
                self.assertLessEqual(2 * border, int(node.findtext("width")), texture.text)
                self.assertLessEqual(2 * border, int(node.findtext("height")), texture.text)

    def test_no_character_the_tv_font_cannot_draw(self):
        """ASCII (< 128), middle dot (U+00B7), en dash (U+2013), ellipsis (U+2026), and Cyrillic (0x400..0x4FF) only."""
        allowed = lambda c: ord(c) < 128 or c in "·–…" or 0x400 <= ord(c) <= 0x4FF  # noqa: E731
        lib = os.path.join(ADDON, "resources", "lib")
        paths = [XML, os.path.join(ROOT, "tools", "make-sweettv-art.py")] + \
            [os.path.join(lib, n) for n in sorted(os.listdir(lib)) if n.startswith("sweettv_") and n.endswith(".py")]
        for path in paths:
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    bad = [c for c in line if not allowed(c)]
                    self.assertEqual(bad, [], f"{os.path.basename(path)}:{number}")


class EntryPoints(unittest.TestCase):
    def setUp(self):
        Fake.builtins.clear()
        sign(True)

    def run_default(self, argv, main=None):
        Fake.builtins.clear()
        with mock.patch.object(sys, "argv", ["default.py"] + argv), \
                mock.patch.object(sweettv_app, "main", **(main or {"return_value": True})) as app:
            with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})
        return app, list(Fake.builtins)

    def test_open_and_demo_go_to_the_app(self):
        app, builtins = self.run_default(["sweettv", "open"])
        app.assert_called_once_with(["open"])
        self.assertEqual(builtins, [])
        app, builtins = self.run_default(["sweettv", "demo"])
        app.assert_called_once_with(["demo"])
        app, builtins = self.run_default(["sweettv"])
        app.assert_called_once_with([])

    def test_a_broken_app_falls_back_to_the_plain_launch_but_a_broken_demo_does_not(self):
        app, builtins = self.run_default(["sweettv", "open"], {"side_effect": RuntimeError("no skin")})
        self.assertEqual(builtins, ["RunAddon(plugin.video.sweettv)"])
        app, builtins = self.run_default(["sweettv", "demo"], {"side_effect": RuntimeError("no skin")})
        self.assertEqual(builtins, [])

    def test_the_card_on_home_opens_the_app_after_the_accounts_step(self):
        with mock.patch.object(store.lib, "accounts", return_value=[
                {"service": "sweettv", "name": "SWEET.TV", "profiles": [], "signed_in": True, "signin": None}]):
            accounts.launch_app("plugin.video.sweettv")
        self.assertEqual(Fake.builtins, ["RunScript(script.media-stick.home,sweettv,open)"])
        self.assertIn("plugin.video.sweettv", apps.load_recent())               # still counted as used
        Fake.builtins.clear()
        with mock.patch.object(store.lib, "accounts", return_value=[
                {"service": "sweettv", "name": "SWEET.TV", "profiles": [], "signed_in": False, "signin": None}]), \
                mock.patch.object(accounts, "signin_service", return_value="cancelled") as signin:
            accounts.launch_app("plugin.video.sweettv")
        signin.assert_called_once_with("sweettv")
        self.assertEqual(Fake.builtins, [])                                      # signed out and backed out: nothing opens

    def test_other_apps_launch_as_before(self):
        apps.launch("plugin.video.other")                                        # YouTube has a screen of its own too (youtube_app.py)
        apps.launch("webapp:netflix")
        self.assertEqual(Fake.builtins, ["RunAddon(plugin.video.other)", "RunScript(script.media-stick.webapp,netflix)"])


if __name__ == "__main__":
    unittest.main()
