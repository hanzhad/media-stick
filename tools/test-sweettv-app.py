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
os.environ["MEDIASTICK_SWEETSTORE_DB"] = os.path.join(TMP, "sweettv", "sweettv.db")
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
        self.items.extend(items)

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

    def setLabel(self, value):
        self.label = value

    def setLabel2(self, value):
        self.label2 = value

    def setArt(self, art):
        self.art = dict(art)


class WindowXML:
    def __init__(self, *a):
        self._props, self.focus = {}, 0
        self.controls = {100: Control(), 200: Control(), 201: Control(), 209: Control(), 210: Control(), 211: Control(), 212: Control(), 213: Control(),
                         300: Control(), 301: Control(), 400: Control(), 409: Control(), 410: Control(), 415: Control(), 416: Control(),
                         417: Control(), 418: Control(), 419: Control(), 420: Control(), 421: Control()}
        self.closed = False

    def setProperty(self, key, value):
        self._props[key] = value

    def getProperty(self, key):
        return self._props.get(key, "")

    def getControl(self, control_id):
        if control_id not in self.controls:
            self.controls[control_id] = Control()
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
import mediastick_sweetplay as SP  # noqa: E402
import mediastick_sweetstore as sweetstore  # noqa: E402

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

    def test_it_never_seeks_because_resident_controller_owns_seeking(self):
        reports, io = self.run_follow([(0.0, 0.0), (1.0, 100.0), (2.0, 3600.0), (901.0, 3600.0), None], seek_to=900)
        self.assertEqual(io.seeks, [])
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
        self.assertNotIn("Favourite", bare)
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


_WRITE_SEQ = 0


def write_list(raw, age=0):
    global _WRITE_SEQ
    _WRITE_SEQ += 1
    st = sweetstore.default_store()
    base = Fake.now if getattr(Fake, "now", None) else time.time()
    when = (int(base) + _WRITE_SEQ) if age == 0 else int(base - age)
    if isinstance(raw, str):
        try:
            doc = json.loads(raw)
        except ValueError:
            return st.db_path
    else:
        doc = raw
    if isinstance(doc, dict) and doc.get("status") not in (None, "OK"):
        existing = st.get_channels_payload(now=when)
        if not existing.get("list"):
            st.clear()
            st.record_sync_error(str(doc.get("status") or "ERROR"), now=when)
            return st.db_path
    st.upsert_channels(doc, now=when)
    return st.db_path


def wait_for(condition, timeout=0.5):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class WindowCase(unittest.TestCase):
    def setUp(self):
        global _WRITE_SEQ
        _WRITE_SEQ = 0
        sweetstore.reset_default_store()
        for name in ("temp", "profile", "addon_data", "resume", "sweettv"):
            import shutil
            shutil.rmtree(os.path.join(TMP, name), ignore_errors=True)
        sweetstore.reset_default_store()
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
        with mock.patch.object(
            accounts,
            "signin_service",
            side_effect=lambda svc: (write_list(answer(chan(1, number=1))), "done")[1],
        ) as signin:
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
        self.assertEqual(window.focus, window._grid_id())

    def test_a_half_written_or_empty_file_is_loading_then_no_channels(self):
        window = self.open()
        self.assertTrue(wait_for(lambda: window.getProperty("msg_title") == "Loading channels"))
        window._look()
        self.assertEqual(window.mode, D.EMPTY)
        write_list(answer())
        window._look()
        self.assertEqual((window.mode, window.getProperty("msg_title")), (D.EMPTY, "No channels yet"))
        write_list(answer(chan(1, "One")))
        window._look()
        self.assertEqual(window.mode, D.DATA)

    def test_a_list_that_goes_unreadable_keeps_what_is_shown(self):
        write_list(answer(chan(1, "One")))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        with mock.patch.object(sweetstore.SweetStore, "get_channels_payload", side_effect=OSError("db locked")):
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
        window._look()
        self.assertEqual((window.getProperty("msg_kind"), window.getProperty("msg_glyph")), ("error", "!"))
        self.assertEqual((window.mode, window.focus), (D.EMPTY, sweettv_app.RETRY))
        self.assertEqual(window.getProperty("msg_tint"), W.RED)
        write_list(answer(chan(1, "One", number=1)))
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
        write_list(answer(chan(1, "One")))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        write_list({"status": "ERROR", "list": []})
        window._look()
        self.assertEqual((window.mode, self.shown(window)), (D.DATA, ["One"]))
        write_list(answer(chan(1, "One"), chan(2, "Two")))
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
            window.controls[window._grid_id()].selected = n
            Fake.now = NOW + n
            window.onClick(417)
        self.assertEqual([e["id"] for e in window.state["recent"]], [str(100 + n) for n in range(14, 2, -1)])
        self.assertTrue(wait_for(lambda: self.saved()["last"] == "114"))
        self.assertEqual([e["id"] for e in self.saved()["recent"]], [str(100 + n) for n in range(14, 2, -1)])

    def test_the_file_is_read_once_per_change_and_off_the_ui_thread(self):
        write_list(self.raw())
        seen = []
        real = D.parse_catalog

        def spy(raw_doc, now):
            seen.append(threading.current_thread() is threading.main_thread())
            return real(raw_doc, now)
        with mock.patch.object(D, "parse_catalog", side_effect=spy):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            for _ in range(5):
                window._look()
            self.assertEqual(seen, [False])
            write_list(self.raw())
            window._look()
            self.assertEqual(len(seen), 2)

    def test_a_look_while_another_runs_does_nothing(self):
        window = self.ready()
        with mock.patch.object(window, "_snapshot") as snap:
            window._loading.acquire()
            try:
                window._look()
            finally:
                window._loading.release()
        snap.assert_not_called()

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



    def test_try_instant_start_continue_sets_wide_grid_and_focuses_201(self):
        doc = MR.record(MR.empty(), "plugin://plugin.video.sweettv/playvod/501|null|10", 1200, 7200, NOW - 20, {"title": "Inception"})
        MR.save(doc)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertEqual(window.section, "continue")
        self.assertEqual(window.getProperty("wide_grid"), "1")
        self.assertTrue(window.getProperty("section_title"))
        self.assertEqual(window.focus, 201)


    def test_page_search_channels_filters_locally_and_back_restores(self):
        window = self.ready()
        self.assertIn("TV Channels", window.getProperty("page_search_label"))
        Fake.typed = "Twenty"
        window.onClick(415)
        self.assertEqual(window.section, "channels")
        self.assertEqual(self.shown(window), ["Twenty"])
        self.assertEqual(window.getProperty("page_search_label"), "Twenty [x]")
        window.focus = 201
        self.press(window, 10)
        self.assertEqual(window.page_query, "")
        self.assertEqual(len(self.shown(window)), 3)

    def test_page_search_movies_filters_to_movies_only(self):
        write_list(answer(chan(10, "Ten", number=10)))
        Fake.typed = "Matrix"
        found = {"ok": True, "query": "Matrix", "items": [
            {"kind": "movie", "id": "500", "title": "Matrix Film", "subtitle": "1999", "cid": "", "epg": "",
             "start": 0, "stop": 0, "channel_name": "", "when": "", "live": False, "playable_in_archive": False,
             "playable": True, "available": True, "vod_url": "plugin://plugin.video.sweettv/playvod/500|null|0",
             "preview": "", "image_url": "", "repeats": 0, "more": ""},
            {"kind": "channel", "id": "10", "title": "Matrix TV", "subtitle": "", "cid": "10", "epg": "",
             "start": 0, "stop": 0, "channel_name": "Matrix TV", "when": "", "live": False,
             "playable_in_archive": False, "playable": True, "available": False, "preview": "", "image_url": "",
             "repeats": 0, "more": ""},
        ], "count": 2}
        with mock.patch.object(sweettv_app.Shelf, "_load_catalog", lambda *a, **k: None),                 mock.patch.object(API, "search", return_value=found) as m_search:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window._open_section("movies")
            window.onClick(415)
            self.assertTrue(wait_for(lambda: m_search.called and len(window.cards) == 1))
            self.assertEqual([c.kind for c in window.cards], ["movie"])
            self.assertEqual(window.cards[0].title, "Matrix Film")

    def test_page_search_shows_filters_to_shows_only(self):
        write_list(answer(chan(10, "Ten", number=10)))
        Fake.typed = "Master"
        found = {"ok": True, "query": "Master", "items": [
            {"kind": "show_tv", "id": "tv:1", "title": "MasterChef", "subtitle": "10 ep", "cid": "10", "epg": "1",
             "start": NOW - 3600, "stop": NOW - 1800, "channel_name": "Ten", "when": "", "live": False,
             "playable_in_archive": True, "playable": True, "available": True, "preview": "", "image_url": "",
             "repeats": 0, "more": "", "episodes_count": 10, "episodes": []},
            {"kind": "movie", "id": "99", "title": "Master Film", "subtitle": "", "cid": "", "epg": "",
             "start": 0, "stop": 0, "channel_name": "", "when": "", "live": False, "playable_in_archive": False,
             "playable": True, "available": True, "vod_url": "plugin://plugin.video.sweettv/playvod/99|null|0",
             "preview": "", "image_url": "", "repeats": 0, "more": ""},
        ], "count": 2}
        with mock.patch.object(API, "shows", return_value={"ok": True, "items": []}),                 mock.patch.object(API, "search", return_value=found) as m_search:
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window._open_section("shows")
            window.onClick(415)
            self.assertTrue(wait_for(lambda: m_search.called and len(window.cards) == 1))
            self.assertEqual(window.cards[0].kind, "show_tv")


    def test_show_modal_auto_selects_next_up_season_episode_and_refreshes_on_return(self):
        write_list(answer(chan(10, "Ten", number=10)))
        detail = {
            "ok": True, "id": "vod:500", "movie_id": "500", "title": "Futurama",
            "seasons": [
                {"id": 1, "title": "Season 1", "episodes": [
                    {"id": 101, "episode_id": 101, "number": 1, "title": "Ep 1", "duration": 1400, "vod_url": "plugin://plugin.video.sweettv/playvod/500|101|10", "resume": 0, "watched": True, "resume_at": 100},
                ]},
                {"id": 2, "title": "Season 2", "episodes": [
                    {"id": 201, "episode_id": 201, "number": 1, "title": "Ep 1", "duration": 1400, "vod_url": "plugin://plugin.video.sweettv/playvod/500|201|10", "resume": 320, "watched": False, "resume_at": 200},
                    {"id": 202, "episode_id": 202, "number": 2, "title": "Ep 2", "duration": 1400, "vod_url": "plugin://plugin.video.sweettv/playvod/500|202|10", "resume": 0, "watched": False, "resume_at": 0},
                ]},
            ],
            "next_up": {"season_index": 1, "episode_index": 0, "season_number": 2, "episode_number": 1, "season_title": "Season 2",
                        "episode_id": 201, "owner_id": 10, "cid": "", "epg": "", "title": "Ep 1",
                        "vod_url": "plugin://plugin.video.sweettv/playvod/500|201|10", "url": "plugin://plugin.video.sweettv/playvod/500|201|10",
                        "resume": 320, "mode": "resume"},
        }
        with mock.patch.object(API, "vod_detail", return_value=detail):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            from resources.lib import sweettv_sections as sections
            card = sections.Card(
                kind="series", key="500", fav_key="vod:500", title="Futurama", art="https://img/f.jpg",
                banner="", meta="", desc="", play_url="", alt_url="", cid="", epg="", start=0, stop=0,
                resume_pos=0, bar="", pbar="", fav=False, catchup=False, playable=True, dim=False, num="",
                initials="FU", plate="", plate_hi="", bg="", tint="", now="", nowline="", next="", nextline="",
                resume_label="", small=False,
            )
            window._open_show_modal(card)
            self.assertTrue(wait_for(lambda: len(window.modal_seasons) == 2 and window.focus == 421))
            self.assertEqual(window.modal_tab_idx, 1)
            self.assertEqual(window.controls[410].selected, 1)
            self.assertEqual(window.controls[421].selected, 0)
            self.assertIn("2", window.controls[210].label)
            # Click 210 dispatches sweettv.play NotifyAll for S2E1 from 320s with episode_mode=True
            window.onClick(210)
            self.assertTrue(wait_for(lambda: Fake.rpc))
            req = json.loads(Fake.rpc[-1])
            self.assertEqual(req["method"], "JSONRPC.NotifyAll")
            self.assertEqual(req["params"]["message"], "sweettv.play")
            self.assertEqual(
                (req["params"]["data"]["kind"], req["params"]["data"]["movie_id"],
                 req["params"]["data"]["episode_id"], req["params"]["data"]["start_offset"],
                 req["params"]["data"]["episode_mode"]),
                ("vod", "500", "201", 320, True),
            )
            self.assertEqual((window.session.season, window.session.episode), (2, 1))
            # Finish S2E1 -> refresh advances modal to S2E2
            window._report(window.session, 1390, 1400)
            window._refresh_show_modal_progress()
            self.assertEqual(window.modal_tab_idx, 1)
            self.assertEqual(window.controls[421].selected, 1)
            saved_ep = MR.load()["items"]["sw:vod:500|201"]
            self.assertEqual((saved_ep["season"], saved_ep["episode"]), (2, 1))
            self.assertTrue(saved_ep["done"])

    def test_hero_guide_button_416_opens_guide_modal(self):
        with mock.patch.object(API, "day", return_value={"ok": True, "cid": "10", "items": []}):
            window = self.ready()
            window.onClick(416)
            self.assertTrue(window._modal_open())
            self.assertIn(window.getProperty("modal"), ("guide", "channel"))

    def test_wide_sections_focus_and_click_use_wide_row_201(self):
        with mock.patch.object(API, "day", return_value={"ok": True, "cid": "20", "items": []}):
            window = self.ready()
            self.assertEqual(window.section, "channels")
            self.assertEqual(window.getProperty("wide_grid"), "1")
            self.assertEqual(window.focus, 201)
            window.controls[201].selected = 1
            self.assertEqual(window._focused_card().cid, "20")
            window.onClick(201)
            self.assertTrue(window._modal_open())
            window.onClick(210)
            self.assertTrue(wait_for(lambda: Fake.rpc))
            request = json.loads(Fake.rpc[-1])
            self.assertEqual(request["method"], "JSONRPC.NotifyAll")
            self.assertEqual((request["params"]["message"], request["params"]["data"]["kind"], request["params"]["data"]["cid"]),
                             ("sweettv.play", "live", "20"))

    def test_ok_plays_live_through_notify_all_on_a_worker_thread_and_remembers_it(self):
        window = self.ready()
        window.controls[window._grid_id()].selected = 1
        window.onClick(417)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        request = json.loads(Fake.rpc[-1])
        self.assertEqual((request["method"], request["params"]["message"],
                          request["params"]["data"]["kind"], request["params"]["data"]["cid"]),
                         ("JSONRPC.NotifyAll", "sweettv.play", "live", "20"))
        self.assertIsNot(Fake.rpc_threads[-1], threading.main_thread())
        self.assertEqual(Fake.played, [])
        self.assertTrue(wait_for(lambda: self.saved()["last"] == "20"))
        saved = self.saved()
        self.assertEqual(saved["recent"], [{"id": "20", "at": NOW}])

    def test_the_state_is_written_only_on_the_writers_thread_and_whole(self):
        calls, real = [], S.save_state

        def spy(path, state):
            calls.append(threading.current_thread())
            return real(path, state)
        with mock.patch.object(S, "save_state", spy):
            window = self.ready()
            window.controls[window._grid_id()].selected = 1
            window.onClick(417)
            window.focus = window._grid_id()
            window.onClick(420)
            self.assertTrue(wait_for(lambda: "ch:20" in MR.fav_keys() and self.saved()["last"] == "20"))
            window.stop()
        self.assertTrue(calls)
        self.assertTrue(all(t is not threading.main_thread() for t in calls))
        self.assertEqual(len({t for t in calls}), 1)                    # one thread for all of it
        self.assertEqual(os.listdir(os.path.dirname(files.state_path())), ["sweettv.json"])      # whole file, no temp left

    def test_coming_back_from_the_player_stops_the_stream_and_keeps_the_place(self):
        window = self.ready()
        window.controls[window._grid_id()].selected = 2
        window.onClick(417)
        window.onInit()                                             # at once: not a return yet
        Fake.playing = True
        window.onInit()
        time.sleep(0.05)
        self.assertEqual(Fake.stopped, 0)
        window.play_at -= 10
        window.onInit()
        self.assertTrue(wait_for(lambda: Fake.stopped == 1))
        self.assertEqual(window.controls[window._grid_id()].selected, 2)
        window.onInit()
        time.sleep(0.05)
        self.assertEqual(Fake.stopped, 1)

    def test_back_from_the_player_puts_the_focus_back_where_kodi_lost_it(self):
        window = self.ready()
        window.controls[window._grid_id()].selected = 1
        window.onClick(417)
        window.focus = 0
        window.play_at -= 10
        window.onInit()
        self.assertTrue(wait_for(lambda: window.focus == window._grid_id()))
        self.assertEqual(window.controls[window._grid_id()].selected, 1)

    def test_hero_favourite_button_toggles_star_and_it_survives_a_restart(self):
        window = self.ready()
        window.controls[window._grid_id()].selected = 1
        window.focus = window._grid_id()
        window.onClick(420)
        self.assertEqual(window.controls[window._grid_id()].items[1].props["fav"], "1")
        self.assertEqual(window.controls[MENU].items[2].label2, "1")
        self.assertTrue(wait_for(lambda: "ch:20" in MR.fav_keys()))
        window.stop()
        again = self.open()
        self.assertTrue(wait_for(lambda: again.mode == D.DATA))
        self.assertEqual(again.controls[again._grid_id()].items[1].props["fav"], "1")
        self.assertEqual(again.controls[again._grid_id()].items[0].props["fav"], "")
        again.controls[MENU].selected = 2
        again.onClick(MENU)
        self.assertEqual([i.label for i in again.controls[again._grid_id()].items], ["Twenty"])
        again.focus = again._grid_id()
        again.onClick(420)                                          # off again, in the favourites view
        self.assertEqual([i.label for i in again.controls[again._grid_id()].items], [])
        self.assertTrue(wait_for(lambda: "ch:20" not in MR.fav_keys()))

    def test_removing_a_favourite_keeps_the_focus_close(self):
        window = self.ready(state={"favourites": ["10", "20", "30"], "recent": [], "last": ""})
        window.controls[MENU].selected = 2
        window.onClick(MENU)
        gid = window._grid_id()
        window.controls[gid].selected = 1
        window.focus = gid
        window.onClick(420)
        self.assertEqual(([i.label for i in window.controls[gid].items], window.controls[gid].selected), (["Ten", "Thirty"], 1))
        window.controls[gid].selected = 1
        window.onClick(420)
        self.assertEqual(([i.label for i in window.controls[gid].items], window.controls[gid].selected), (["Ten"], 0))

    def test_number_keys_jump_to_a_channel_when_the_data_has_numbers(self):
        window = self.ready(raw=answer(chan(1, "A", number=1, category=[1]), chan(2, "B", number=12, category=[2]),
                                       chan(3, "C", number=40, category=[1]),
                                       categories=[{"id": 1, "caption": "X"}, {"id": 2, "caption": "Y"}]))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[201].items) == 3))
        idx_c1 = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "c:1")
        window.controls[409].selectItem(idx_c1)
        window.onClick(409)
        self.assertEqual([i.label for i in window.controls[201].items], ["A", "C"])
        self.press(window, 58 + 4)
        self.press(window, 0, 0xF000 + ord("0"))                    # "40": a keyboard digit
        self.assertEqual(window.controls[201].selected, 1)
        self.assertEqual(window.getProperty("jump"), "")
        self.press(window, 58 + 1)                                  # "1": 12 could follow, so it waits
        self.assertEqual(window.getProperty("jump"), "Channel 1")
        self.assertEqual(window.controls[201].selected, 1)
        self.press(window, 58 + 2)                                  # "12" is in another category: All opens
        self.assertEqual([i.label for i in window.controls[201].items], ["A", "B", "C"])
        self.assertEqual(window.controls[201].selected, 1)
        self.assertEqual(window.controls[MENU].selected, 6)         # and the menu is on TV Channels
        self.assertEqual([i.props["active"] for i in window.controls[MENU].items][6], "1")
        self.assertEqual(window.getProperty("jump"), "")
        self.assertEqual(window.focus, 201)
        self.press(window, 58 + 7)
        self.assertEqual(window.getProperty("jump"), "No channel 7")
        self.assertEqual(window.controls[201].selected, 1)

    def test_a_single_digit_waits_then_goes(self):
        window = self.ready(raw=answer(chan(1, "A", number=1), chan(2, "B", number=12)))
        window.controls[201].selected = 1
        with mock.patch.object(D, "DIGIT_WAIT", 0.03):
            self.press(window, 58 + 1)
            self.assertTrue(wait_for(lambda: window.controls[201].selected == 0 and window.getProperty("jump") == ""))

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
        window.controls[409].selectItem(1); window.onClick(409)
        window.controls[window._grid_id()].selected = 1
        write_list(self.raw())
        window._look()
        self.assertEqual((self.shown(window), window.controls[window._grid_id()].selected), (["Ten", "Thirty"], 1))
        self.assertEqual(window.filter_key, "c:1")
        write_list(answer(chan(10, "Ten", number=10)))              # the categories are gone: back to the default
        window._look()
        self.assertEqual(self.shown(window), ["Ten"])
        self.assertEqual(window.filter_key, "main")

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
        for word in ("Смотреть", "Меню", "Разделы", "0-9", "Номер канала", "Вверх", "Программа и продолжение"):
            self.assertIn(word, window.getProperty("hint"))
        for word in ("Watch", "Favourite", "Channel number", "Guide and continue"):
            self.assertNotIn(word, window.getProperty("hint"))
        self.assertEqual(window.getProperty("chip"), "Вход выполнен")
        self.assertEqual((window.getProperty("l_catchup"), window.getProperty("l_favourite")), ("Архив", "Избранное"))
        self.assertTrue(window.getProperty("l_guide").startswith("Программа"))
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
                           "when": "07:50", "live": True, "can_archive": True, "playable_in_archive": True, "available": True,
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
            self.assertEqual(window.getProperty("chip"), "Signed in")
            self.assertIn(window.getProperty("l_guide"), ("Programme guide", "Programme", "Schedule"))
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
        demo.controls[demo._grid_id()].selected = 0
        demo.onClick(417)
        self.assertEqual(Fake.notes[-1:], ["Демо: ничего не воспроизводится."])


class Demo(WindowCase):
    def test_demo_is_marked_fills_all_seven_sections_and_never_touches_real_data(self):
        write_list(answer(chan(1, "Real")))
        with mock.patch.object(sweetstore.SweetStore, "get_channels_payload", side_effect=AssertionError("real store")), \
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
            # Shows section (index 3) -> OK opens Show Episodes modal (421 + 410)
            window.controls[MENU].selected = 3
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: window.cards and window.cards[0].kind != 'skeleton'))
            window.controls[ROW].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) > 0))
            self.assertGreater(len(window.controls[410].items), 0)
            self.press(window, 92)
            # Channels section (index 6) -> clicking channel / 416 opens 7-day Channel Hub (400 + 410)
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0))
            window.controls[window._grid_id()].selected = 0
            window.onClick(201)
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
        window.controls[window._grid_id()].selected = 0
        window.focus = window._grid_id()
        window.onClick(420)
        window.onClick(417)
        window.onClick(201)
        self.assertTrue(wait_for(lambda: len(window.controls[GUIDE].items) > 0))
        if not any(i.props.get("kind") in ("live", "archive") for i in window.controls[GUIDE].items):
            tabs = window.controls[sweettv_app.MODAL_TABS]
            tabs.selected = max(0, tabs.selected - 1)
            window.controls[GUIDE].items.clear()
            window.onClick(sweettv_app.MODAL_TABS)
            self.assertTrue(wait_for(lambda: len(window.controls[GUIDE].items) > 0))
        window.controls[GUIDE].selected = next(
            i for i, item in enumerate(window.controls[GUIDE].items)
            if item.props.get("kind") in ("live", "archive")
        )
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
        was = window.controls[window._grid_id()].items[0].props.get("fav", "")
        window.focus = window._grid_id()
        window.onClick(420)
        self.assertEqual(window.controls[window._grid_id()].items[0].props.get("fav", ""), "" if was else "1")
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
    """Live TV hover preview in Hero via resident SweetPlayerController and videowindow."""

    def setUp(self):
        super().setUp()
        Fake.now = NOW
        write_list(answer(chan(10, "Ten", number=10), chan(20, "Twenty", number=20)))

    def _rpc_messages(self):
        out = []
        for raw in Fake.rpc:
            req = json.loads(raw) if isinstance(raw, str) else raw
            params = req.get("params") or {}
            out.append((params.get("message"), params.get("data") or {}))
        return out

    def _start_preview_on(self, window, idx=0):
        window.setFocusId(sweettv_app.WIDE_ROW)
        window.controls[sweettv_app.WIDE_ROW].selected = idx
        window._last_hover_cid = ""
        self.press(window, 107)
        self.assertTrue(wait_for(lambda: any(m == "sweettv.play" and d.get("preview") for m, d in self._rpc_messages())))
        Fake.rpc.clear()

    def test_off_nothing_plays_in_the_preview_and_the_skin_has_no_video_window_to_show(self):
        self.assertEqual(sweettv_app.PREVIEW_DELAY, 1.0)
        self.assertFalse(hasattr(sweettv_app, "PREVIEW_VIDEO"))
        MR.write_preview_video(False)
        with mock.patch.object(sweettv_app, "PREVIEW_DELAY", 0.01):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.press(window, KEY_RIGHT)
            time.sleep(0.05)
            self.assertEqual((window.getProperty("preview_video"), Fake.played, Fake.rpc), ("", [], []))

    def test_on_the_focused_channel_plays_in_the_window_and_ok_makes_it_big(self):
        MR.write_preview_video(True)
        with mock.patch.object(sweettv_app, "PREVIEW_DELAY", 0.01):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertEqual(window.getProperty("preview_video"), "1")
            window.setFocusId(sweettv_app.WIDE_ROW)
            window.controls[sweettv_app.WIDE_ROW].selected = 1
            self.press(window, KEY_RIGHT)
            self.assertTrue(wait_for(lambda: any(m == "sweettv.play" for m, _ in self._rpc_messages())))
            self.assertEqual(Fake.played, [])
            msg, payload = self._rpc_messages()[-1]
            self.assertEqual((msg, payload["kind"], payload["cid"], payload["preview"]), ("sweettv.play", "live", "20", True))
            self.assertEqual(window.getProperty("preview_active"), "1")

            # Non-nav event (e.g. mouse move) on same channel does not restart preview
            count_before = len(Fake.rpc)
            self.press(window, 107)
            time.sleep(0.03)
            self.assertEqual(len(Fake.rpc), count_before)

            # Promotion on Play: no Action(FullScreen), no stop_preview, dispatches preview=False
            Fake.rpc.clear()
            Fake.playing = True
            window.onClick(417)
            self.assertEqual(Fake.builtins, [])
            msgs = self._rpc_messages()
            self.assertFalse(any(m == "sweettv.ctl" and d.get("op") == "stop_preview" for m, d in msgs))
            self.assertEqual(msgs[-1][0], "sweettv.play")
            self.assertEqual((msgs[-1][1]["cid"], msgs[-1][1]["preview"]), ("20", False))
            self.assertEqual(window.getProperty("preview_active"), "")

    def test_preview_dwell_gates_focus_section_demo_mode_and_hero_ctas(self):
        MR.write_preview_video(True)
        with mock.patch.object(sweettv_app, "PREVIEW_DELAY", 0.01):
            # Demo mode suppresses preview
            demo_win = self.open(demo=True)
            self.assertTrue(wait_for(lambda: demo_win.mode == D.DATA))
            demo_win.setFocusId(sweettv_app.WIDE_ROW)
            self.press(demo_win, 107)
            time.sleep(0.03)
            self.assertEqual(Fake.rpc, [])
            demo_win.stop()

            # Non-channels section or non-channel focus suppresses preview
            Fake.rpc.clear()
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.setFocusId(sweettv_app.MENU)
            self.press(window, 107)
            time.sleep(0.03)
            self.assertEqual(Fake.rpc, [])

            # Hero CTA focus on channels starts preview
            for hero_id in (sweettv_app.HERO_PLAY, sweettv_app.HERO_ALT, sweettv_app.HERO_GUIDE, sweettv_app.HERO_FAV):
                Fake.rpc.clear()
                window._preview_stop(send_stop=False)
                window.setFocusId(hero_id)
                window._last_hover_cid = ""
                self.press(window, 107)
                self.assertTrue(
                    wait_for(lambda: any(m == "sweettv.play" and d.get("preview") for m, d in self._rpc_messages())),
                    f"Expected preview start on hero focus {hero_id}",
                )

    def test_preview_stop_all_eight_triggers(self):
        MR.write_preview_video(True)
        with mock.patch.object(sweettv_app, "PREVIEW_DELAY", 0.01):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))

            def assert_stopped(label):
                self.assertTrue(
                    any(m == "sweettv.ctl" and d.get("op") == "stop_preview" for m, d in self._rpc_messages()),
                    f"Expected stop_preview on {label}, got {self._rpc_messages()}",
                )
                self.assertEqual(window.getProperty("preview_active"), "")
                self.assertEqual(window.previewing, "")

            # 1. Channel change
            self._start_preview_on(window, 0)
            window.controls[sweettv_app.WIDE_ROW].selected = 1
            self.press(window, KEY_RIGHT)
            assert_stopped("channel change")

            # 2. Focus leaving channel row / hero CTA
            self._start_preview_on(window, 0)
            window.setFocusId(sweettv_app.MENU)
            self.press(window, 1)
            assert_stopped("focus leaving channel row")

            # 3. Switching section / filter chip / scoped search
            self._start_preview_on(window, 0)
            window.onClick(sweettv_app.PAGE_SEARCH)
            assert_stopped("scoped search")

            # 4. Opening any modal
            self._start_preview_on(window, 0)
            window._open_channel_hub(window.cards[0])
            assert_stopped("open channel hub modal")
            window._close_modal()

            # 5. Typing channel digits
            self._start_preview_on(window, 0)
            self.press(window, 59)
            assert_stopped("typing channel digits")

            # 6. Pressing Back / exit
            self._start_preview_on(window, 0)
            self.press(window, BACK)
            assert_stopped("pressing Back")

            # 7. Mode leaving data
            self._start_preview_on(window, 0)
            window._show_mode(D.EMPTY, {})
            assert_stopped("mode leaving data")

            # 8. Window teardown
            window._show_mode(D.DATA, {})
            self._start_preview_on(window, 0)
            window.stop()
            assert_stopped("window teardown")


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
                                "shows": True, "series": True, "movies": True, "channels": True}
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
            self.assertTrue(wait_for(lambda: m_search.called or window.section == "search"))
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
        window.focus = window._grid_id()
        window.controls[window._grid_id()].selected = 0
        window.onClick(420)
        self.assertTrue(wait_for(lambda: "ch:10" in MR.fav_keys()))
        window.onClick(420)
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
            gid = window._grid_id()
            window.focus = gid
            window.controls[gid].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) == 1))
            m_det.assert_called()
            self.assertEqual(len(window.controls[410].items), 1)
            self.assertEqual(window.controls[421].items[0].label, "Ep 1")


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
            window.controls[409].selectItem(1); window.onClick(409)
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
        detail_movie = {"ok": True, "id": "vod:501", "movie_id": "501", "title": "Film A",
                        "duration": 5400, "owner_id": 10,
                        "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|10"}
        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", side_effect=lambda sec, **kw: series if sec == "series" else movies), \
                mock.patch.object(API, "vod_detail", side_effect=lambda k, **kw: detail_movie if "501" in str(k) else detail):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Film A"]))
            gid = window._grid_id()
            window.focus = gid
            window.controls[gid].selected = 0
            window.onClick(ROW)
            self.assertEqual(window.getProperty('modal'), 'detail')
            window.onClick(210)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 1))
            rpc_mov = json.loads(Fake.rpc[-1])
            self.assertEqual(rpc_mov["method"], "JSONRPC.NotifyAll")
            self.assertEqual((rpc_mov["params"]["message"], rpc_mov["params"]["data"]["kind"],
                              rpc_mov["params"]["data"]["movie_id"], rpc_mov["params"]["data"]["owner_id"]),
                             ("sweettv.play", "vod", "501", 10))
            window.controls[MENU].selected = 4
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Series A"]))
            gid = window._grid_id()
            window.focus = gid
            window.controls[gid].selected = 0
            window.onClick(ROW)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) == 1))
            self.assertEqual(window.controls[421].items[0].label, "Pilot")

    def test_catalog_chips_skips_umbrella_genre_ids_and_falls_back_on_empty_sort_modes(self):
        live_genres = [
            {"id": 61, "name": "Все фильмы"},
            {"id": 1, "name": "Сериалы"},
            {"id": 3, "name": "Шоу"},
            {"id": 57, "name": "4K UHD"},
            {"id": 2, "name": "Драмы"},
            {"id": 4, "name": "Комедии"},
            {"id": 56, "name": "Боевики"},
            {"id": 58, "name": "Триллеры"},
            {"id": 60, "name": "Фантастика"},
            {"id": 62, "name": "Приключения"},
            {"id": 70, "name": "Семейные"},
        ]
        chips = sweettv_app.sections.catalog_chips(live_genres, [{"id": 1, "name": "По умолчанию"}], 0)
        self.assertEqual(
            chips,
            [
                ("all", "All items"),
                ("sort", "По умолчанию"),
                ("g:2", "Драмы"),
                ("g:4", "Комедии"),
                ("g:56", "Боевики"),
                ("g:58", "Триллеры"),
                ("g:60", "Фантастика"),
                ("g:62", "Приключения"),
                ("g:70", "Семейные"),
            ],
        )

        # Fallback to SORT_MODES_DEFAULT when sort_modes is empty or has no non-empty mode name
        for empty_modes in ([], None, [{"id": 1, "name": ""}, {"id": 2, "name": "   "}], [{"id": 1}]):
            c0 = sweettv_app.sections.catalog_chips(live_genres[:5], empty_modes, 0)
            c1 = sweettv_app.sections.catalog_chips(live_genres[:5], empty_modes, 1)
            self.assertEqual(c0[1], ("sort", "Popular"), empty_modes)
            self.assertEqual(c1[1], ("sort", "IMDb Rating"), empty_modes)
            self.assertEqual([k for k, _ in c0[2:]], ["g:2"], empty_modes)

        # Valid non-empty sort_modes still cycle normally
        valid_modes = [{"id": 1, "name": "По умолчанию"}, {"id": 2, "name": "По рейтингу"}]
        self.assertEqual(sweettv_app.sections.catalog_chips([], valid_modes, 0)[1], ("sort", "По умолчанию"))
        self.assertEqual(sweettv_app.sections.catalog_chips([], valid_modes, 1)[1], ("sort", "По рейтингу"))


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
        self.assertTrue(wait_for(lambda: len(window.controls[201].items) == 2))
        self.assertEqual(self.shown(window), ["Live One", "Premium Two"])
        window.controls[409].selectItem(len(window.controls[409].items) - 1); window.onClick(409)
        fast_idx = next((i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "fast"), None)
        self.assertIsNotNone(fast_idx, "24/7 FAST chip missing from 409 list")
        window.controls[409].selectItem(fast_idx)
        window.onClick(409)
        self.assertEqual(self.shown(window), ["24/7 Comedy"])

    def test_ok_on_channel_opens_hub_and_browse_hero_417_live_418_from_start_416_guide(self):
        Fake.now = NOW
        raw = answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=7,
                          epg=[prog(NOW - 600, NOW + 600, "Now ten", 9)]))
        write_list(raw)
        with mock.patch.object(API, "day", return_value={
                "ok": True, "cid": "10", "name": "Ten", "date": "2027-01-15", "now": NOW,
                "archive_days": 7, "future_days": 3,
                "items": [{"epg": "9", "cid": "10", "title": "Now ten", "start": NOW - 600, "stop": NOW + 600,
                           "when": "07:50", "live": True, "can_archive": True, "playable_in_archive": True, "available": True,
                           "preview": "", "season": 0, "episode": 0, "show_id": ""}]}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Ten"]))
            gid = window._grid_id()
            window.focus = gid
            window.controls[gid].selected = 0
            window.onClick(417)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 1))
            r1 = json.loads(Fake.rpc[-1])
            self.assertEqual((r1["method"], r1["params"]["data"]["kind"], r1["params"]["data"]["cid"], r1["params"]["data"]["from_start"]),
                             ("JSONRPC.NotifyAll", "live", "10", False))
            window.onClick(418)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 2))
            r2 = json.loads(Fake.rpc[-1])
            self.assertEqual((r2["method"], r2["params"]["data"]["kind"], r2["params"]["data"]["cid"],
                              r2["params"]["data"]["epg_id"], r2["params"]["data"]["from_start"]),
                             ("JSONRPC.NotifyAll", "epg", "10", "9", True))
            window.onClick(201)
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
            gid = window._grid_id()
            window.focus = gid
            window.controls[gid].selected = 0
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
                           "when": "07:50", "live": True, "can_archive": True, "playable_in_archive": True, "available": True,
                           "preview": "", "season": 0, "episode": 0, "show_id": ""}]}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 2))
            window.focus = window._grid_id()
            window.controls[window._grid_id()].selected = 1
            window.onClick(416)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) >= 1))
            self.press(window, BACK)
            self.assertFalse(window.getProperty("guide") or window.getProperty("modal"))
            self.assertEqual((window.focus, window.controls[window._grid_id()].selected), (window._grid_id(), 1))


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
    """Pictures a node draws at once: images, buttons, and togglebuttons."""
    total = 0
    for child in node:
        if child.tag != "control":
            continue
        kind = child.get("type")
        if kind in ("image", "button", "togglebutton"):
            total += 1
        elif kind not in ("list", "panel"):
            total += count_pictures(child)
    return total


def _eval_kodi_cond(expr: str, win_props: dict, item_props: dict = None, focus_id: int = 0,
                    item_art: str = "https://img/x.jpg", container_counts: dict = None) -> bool:
    """Deterministic evaluator for Kodi skin <visible> boolean expressions."""
    if not expr or not expr.strip():
        return True
    s = expr.strip()
    item_props = item_props or {}
    container_counts = container_counts or {}

    def _val(ref: str) -> str:
        ref = ref.strip()
        m = re.fullmatch(r"Window\.Property\(([^)]+)\)", ref)
        if m:
            return str(win_props.get(m.group(1), ""))
        m = re.fullmatch(r"ListItem\.Property\(([^)]+)\)", ref)
        if m:
            return str(item_props.get(m.group(1), ""))
        if ref == "ListItem.Art(icon)":
            return str(item_art)
        if ref == "ListItem.Label":
            return str(item_props.get("title", "Item"))
        if ref == "ListItem.Label2":
            return str(item_props.get("label2", ""))
        m = re.fullmatch(r"Container\((\d+)\)\.NumItems", ref)
        if m:
            return str(container_counts.get(int(m.group(1)), 1))
        return ref

    def _split_top(text: str, op_char: str) -> list:
        parts, depth, start = [], 0, 0
        for idx, ch in enumerate(text):
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth = max(0, depth - 1)
            elif ch == op_char and depth == 0:
                parts.append(text[start:idx])
                start = idx + 1
        parts.append(text[start:])
        return parts

    or_parts = _split_top(s, "|")
    if len(or_parts) > 1:
        return any(_eval_kodi_cond(p, win_props, item_props, focus_id, item_art, container_counts) for p in or_parts)

    and_parts = _split_top(s, "+")
    if len(and_parts) > 1:
        return all(_eval_kodi_cond(p, win_props, item_props, focus_id, item_art, container_counts) for p in and_parts)

    if s.startswith("!"):
        return not _eval_kodi_cond(s[1:].strip(), win_props, item_props, focus_id, item_art, container_counts)

    if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
        inner = s[1:-1]
        if len(_split_top(inner, ")")) == 1 and len(_split_top(inner, "]")) == 1:
            return _eval_kodi_cond(inner, win_props, item_props, focus_id, item_art, container_counts)

    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if s == "Player.HasVideo":
        return bool(win_props.get("_player_has_video", False))
    m = re.fullmatch(r"Control\.HasFocus\((\d+)\)", s)
    if m:
        return int(m.group(1)) == int(focus_id)
    m = re.fullmatch(r"String\.IsEmpty\((.+)\)", s)
    if m:
        return _val(m.group(1)) == ""
    m = re.fullmatch(r"String\.IsEqual\((.+),([^,]+)\)", s)
    if m:
        return _val(m.group(1)) == m.group(2).strip()
    m = re.fullmatch(r"Integer\.IsGreater\((.+),(-?\d+)\)", s)
    if m:
        try:
            return int(_val(m.group(1)) or 0) > int(m.group(2))
        except ValueError:
            return False
    return True


def _resolve_info_tex(tex_text: str, win_props: dict, item_props: dict, item_art: str) -> str:
    t = (tex_text or "").strip()
    if not t:
        return ""
    m = re.fullmatch(r"\$INFO\[Window\.Property\(([^)]+)\)\]", t)
    if m:
        return str(win_props.get(m.group(1), ""))
    m = re.fullmatch(r"\$INFO\[ListItem\.Property\(([^)]+)\)\]", t)
    if m:
        return str(item_props.get(m.group(1), ""))
    if t == "$INFO[ListItem.Art(icon)]":
        return str(item_art)
    return t


def count_visible_textures(node, win_props: dict, focus_id: int, item_props: dict = None,
                           item_art: str = "https://img/x.jpg", container_items: dict = None) -> int:
    """Count GPU textures visible simultaneously in `node` for a given window/focus state."""
    container_items = container_items or {}
    counts = {k: len(v) for k, v in container_items.items()}
    if node.tag == "control":
        vis = node.findtext("visible") or ""
        if not _eval_kodi_cond(vis, win_props, item_props, focus_id, item_art, counts):
            return 0
        for anim in node.findall("animation"):
            if anim.get("effect") == "slide" and "end" in anim.attrib:
                dx = int(anim.get("end", "0,0").split(",")[0])
                w = int(node.findtext("width") or 0)
                cond = anim.get("condition") or ""
                if dx <= -max(280, w) and cond and _eval_kodi_cond(cond, win_props, item_props, focus_id, item_art, counts):
                    return 0
        kind = node.get("type")
        if kind == "image":
            tex_node = node.find("texture")
            tex = _resolve_info_tex(tex_node.text if tex_node is not None else "", win_props, item_props or {}, item_art)
            return 1 if tex else 0
        if kind in ("button", "togglebutton"):
            return 1
        if kind in ("list", "panel"):
            cid = int(node.get("id") or 0)
            w = int(node.findtext("width") or 0)
            h = int(node.findtext("height") or 0)
            il = node.find("itemlayout")
            fl = node.find("focusedlayout")
            iw = int(il.get("width")) if (il is not None and il.get("width")) else w
            ih = int(il.get("height")) if (il is not None and il.get("height")) else h
            slots = max(1, w // max(1, iw)) * max(1, h // max(1, ih))
            c_items = container_items.get(cid)
            if c_items is None:
                c_items = [(item_props or {}, item_art)] * slots
            shown = c_items[:slots]
            if not shown:
                return 0
            total = 0
            for idx, (ip, ia) in enumerate(shown):
                layout = fl if (idx == 0 and fl is not None) else il
                if layout is not None:
                    for ch in layout:
                        total += count_visible_textures(ch, win_props, focus_id, ip, ia, container_items)
            return total
    return sum(count_visible_textures(ch, win_props, focus_id, item_props, item_art, container_items) for ch in node)


class Skin(unittest.TestCase):
    def tree(self, name="script-media-stick-sweettv.xml"):
        return ET.parse(os.path.join(SKIN, name)).getroot()

    def control(self, root, control_id):
        found = next((c for c in root.iter("control") if c.get("id") == str(control_id)), None)
        self.assertIsNotNone(found, f"Missing control id={control_id}")
        return found

    def test_panel_grid_4x2_rail_hero_buttons_filter_chips_and_modal(self):
        root = self.tree()
        self.assertEqual(root.tag, "window")
        types_ = {int(c.get("id")): c.get("type") for c in root.iter("control") if c.get("id", "").isdigit()}
        self.assertEqual(types_[100], "list")
        self.assertEqual(types_[200], "panel")
        for btn in (210, 211, 213, 300, 301, 415, 416, 417, 418, 420):
            self.assertEqual(types_.get(btn), "button", btn)
        self.assertEqual(types_[400], "list")
        self.assertIn(types_.get(410), ("list", "grouplist"))
        for cid in range(401, 409):
            self.assertNotIn(cid, types_, f"Legacy togglebutton {cid} must be removed")
        self.assertEqual(types_.get(209), "grouplist")
        self.assertEqual(types_.get(409), "list")
        chips_ctrl = self.control(root, 409)
        self.assertEqual((chips_ctrl.findtext("orientation") or "").strip(), "horizontal")
        self.assertEqual((chips_ctrl.findtext("scrolltime") or "").strip(), "180")
        self.assertEqual((chips_ctrl.findtext("onleft") or "").strip(), "100")
        self.assertEqual((chips_ctrl.findtext("onup") or "").strip(), "415")
        self.assertEqual((chips_ctrl.findtext("visible") or "").strip(), "!String.IsEmpty(Window.Property(filters))")
        self.assertEqual(
            (int(chips_ctrl.findtext("left")), int(chips_ctrl.findtext("top")),
             int(chips_ctrl.findtext("width")), int(chips_ctrl.findtext("height"))),
            (96, 86, 1776, 48),
        )
        self.assertEqual(types_.get(419), "grouplist")
        self.assertEqual(types_[201], "panel")
        panel = self.control(root, 200)
        self.assertEqual(panel.findtext("orientation"), "vertical")
        cols = int(panel.findtext("width")) // int(panel.find("itemlayout").get("width"))
        rows = int(panel.findtext("height")) // int(panel.find("itemlayout").get("height"))
        self.assertEqual((cols, rows), (5, 2))
        wide = self.control(root, 201)
        wcols = int(wide.findtext("width")) // int(wide.find("itemlayout").get("width"))
        wrows = int(wide.findtext("height")) // int(wide.find("itemlayout").get("height"))
        self.assertEqual(wide.findtext("orientation"), "horizontal")
        self.assertEqual((wcols, wrows), (4, 1))
        self.assertEqual(types_.get(415), "button")
        self.assertEqual(types_.get(416), "button")
        self.assertEqual(self.control(root, 415).findtext("label"), "$INFO[Window.Property(page_search_label)]")
        for ar in root.iter("aspectratio"):
            if ar.text == "scale":
                self.assertEqual(ar.get("align"), "center")
                self.assertEqual(ar.get("aligny"), "center")
        for node in panel.iter("texture"):
            if "ListItem.Art" in (node.text or ""):
                self.assertEqual(node.get("background"), "true")


    def test_diffused_card_images_disable_scalediffuse_and_use_concentric_ring(self):
        root = self.tree()
        for img in root.findall(".//control[@type='image']"):
            tex = img.find("texture")
            if tex is not None and tex.get("diffuse"):
                ar = img.find("aspectratio")
                self.assertIsNotNone(ar, f"Missing aspectratio on diffused image {tex.text}")
                self.assertEqual(ar.get("scalediffuse"), "false")
        for panel_id in (200, 201):
            panel = self.control(root, panel_id)
            focused = panel.find("focusedlayout")
            rings = [c for c in focused.findall("control") if c.findtext("texture") == "youtube-ring.png"]
            self.assertEqual(len(rings), 1, f"Expected youtube-ring.png in panel {panel_id}")
            self.assertEqual(rings[0].findtext("visible"), f"Control.HasFocus({panel_id})")

    def test_visible_textures_at_most_34_in_all_states(self):
        root = self.tree()
        chip_items = [({"title": f"Chip {i}", "active": "1" if i == 0 else ""}, "") for i in range(8)]
        poster_items = {
            100: [({"title": f"Sec {i}"}, "") for i in range(7)],
            409: chip_items,
            200: [({"title": f"Film {i}", "meta": "2025", "bar": ""}, f"https://img/{i}.jpg") for i in range(10)],
        }
        wide_items = {
            100: [({"title": f"Sec {i}"}, "") for i in range(7)],
            409: chip_items,
            201: [({"title": f"Ch {i}", "now": "Live", "bar": "sweettv-bar-10.png"}, f"https://img/{i}.png") for i in range(4)],
        }
        hub_items = {
            410: [({"title": f"Tab {i}", "active": "1" if i == 0 else ""}, "") for i in range(7)],
            400: [({"title": f"Row {i}", "when": "20:00", "kind": "archive"}, "") for i in range(8)],
        }
        show_hub_items = {
            410: [({"title": f"Season {i}", "active": "1" if i == 0 else ""}, "") for i in range(4)],
            421: [({"title": f"Ep {i}", "now": f"E{i}", "bar": "sweettv-bar-10.png", "badge": "Soon" if i == 3 else ""}, f"https://img/ep{i}.jpg") for i in range(4)],
        }
        states = (
            ("poster_browse", {"mode": "data", "modal": "", "wide_grid": "", "filters": "1"}, 200, poster_items),
            ("wide_hero_still", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1", "hero_art": "https://img/bg.jpg",
                                 "hero_is_logo": "", "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                 "has_guide": "1", "has_fav": "1"}, 201, wide_items),
            ("wide_hero_logo", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1", "hero_art": "https://img/logo.png",
                                "hero_is_logo": "1", "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                "has_guide": "1", "has_fav": "1"}, 201, wide_items),
            ("wide_hero_preview", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1", "preview_video": "1",
                                   "preview_active": "1", "_player_has_video": True, "hero_art": "https://img/bg.jpg",
                                   "hero_is_logo": "", "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                   "has_guide": "1", "has_fav": "1"}, 201, wide_items),
            ("movie_detail_hub", {"mode": "data", "modal": "detail", "guide": "", "hero_art": "https://img/m.jpg",
                                  "hero_is_logo": "", "has_play": "1", "has_alt": "1", "has_guide": "", "has_fav": "1"}, 210, {}),
            ("show_series_hub", {"mode": "data", "modal": "show", "guide": "1", "hero_art": "https://img/s.jpg",
                                 "hero_is_logo": "", "has_play": "1", "has_alt": "1", "has_guide": "", "has_fav": "1"}, 421, show_hub_items),
            ("channel_hub", {"mode": "data", "modal": "guide", "guide": "1", "hero_art": "https://img/logo.png",
                             "hero_is_logo": "1", "has_play": "1", "has_alt": "1", "has_guide": "", "has_fav": "1"}, 400, hub_items),
        )
        # Verify texture counter catches >34 budget overflow on a synthetic window
        synth = ET.fromstring("<window><controls>" + "".join(
            "<control type='image'><texture>white.png</texture></control>" for _ in range(35)
        ) + "</controls></window>")
        self.assertEqual(count_visible_textures(synth, {}, 0), 35)
        # Require Unified Hero Hub + Hero Action Row 419 + sweettv-menu.png to be part of the <=34 budget
        self.control(root, 419)
        for state_name, wprops, focus_id, c_items in states:
            with self.subTest(state=state_name):
                vis_count = count_visible_textures(root, wprops, focus_id, container_items=c_items)
                self.assertGreater(vis_count, 0, f"{state_name} rendered 0 textures")
                self.assertLessEqual(vis_count, 34, f"{state_name} exceeded 34 GPU textures: {vis_count}")

    def test_hero_videowindow_bounds_order_visibility_and_single_bracket_depth(self):
        root = self.tree()
        controls = list(root.findall("./controls/control"))
        vw_indices = [i for i, c in enumerate(controls) if c.attrib.get("type") == "videowindow"]
        self.assertEqual(len(vw_indices), 1, "Expected exactly one top-level <control type='videowindow'>")
        vw_idx = vw_indices[0]
        vw = controls[vw_idx]
        self.assertNotIn("id", vw.attrib, "videowindow must have no numeric id")
        self.assertEqual(
            (vw.findtext("left"), vw.findtext("top"), vw.findtext("width"), vw.findtext("height")),
            ("520", "0", "1400", "788"),
        )
        self.assertGreater(vw_idx, 0)
        self.assertIn("hero_art", controls[vw_idx - 1].findtext("texture") or "")
        self.assertEqual(controls[vw_idx + 1].attrib.get("type"), "image")

        vw_vis = vw.findtext("visible") or ""
        base_props = {"wide_grid": "1", "emptycat": "", "preview_video": "1", "preview_active": "1", "_player_has_video": True}
        self.assertTrue(_eval_kodi_cond(vw_vis, base_props))
        for key, bad_val in (("wide_grid", ""), ("emptycat", "1"), ("preview_video", ""), ("preview_active", ""), ("_player_has_video", False)):
            p_copy = dict(base_props)
            p_copy[key] = bad_val
            self.assertFalse(_eval_kodi_cond(vw_vis, p_copy), f"videowindow must hide when {key}={bad_val!r}")

        preview_props = {
            "wide_grid": "1", "emptycat": "", "preview_video": "1", "preview_active": "1",
            "_player_has_video": True, "hero_art": "https://img/bg.jpg", "hero_is_logo": "",
        }
        hero_art_ctrl = controls[vw_idx - 1]
        self.assertFalse(_eval_kodi_cond(hero_art_ctrl.findtext("visible") or "", preview_props))
        fade_ctrl = controls[vw_idx + 1]
        self.assertTrue(_eval_kodi_cond(fade_ctrl.findtext("visible") or "", preview_props))

        for elem in root.iter():
            for expr in (elem.text if elem.tag == "visible" else None, elem.attrib.get("condition")):
                if not expr:
                    continue
                depth = 0
                for ch in expr:
                    if ch == "[":
                        depth += 1
                        self.assertLessEqual(depth, 1, f"Nested '[' in expression: {expr}")
                    elif ch == "]":
                        depth = max(0, depth - 1)

    def test_art_assets_poster_mask_240x356_burger_menu_64x64_and_chip_active_48x48(self):
        from PIL import Image
        import numpy as np

        poster_mask_path = os.path.join(MEDIA, "sweettv-poster-mask.png")
        menu_path = os.path.join(MEDIA, "sweettv-menu.png")
        chip_active_path = os.path.join(MEDIA, "sweettv-chip-active.png")

        self.assertTrue(os.path.isfile(poster_mask_path))
        with Image.open(poster_mask_path) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.size, (240, 356))
            arr = np.asarray(im)
            self.assertEqual(int(arr[0, 0, 3]), 0)
            self.assertEqual(int(arr[355, 239, 3]), 0)
            self.assertEqual(int(arr[178, 120, 3]), 255)

        self.assertTrue(os.path.isfile(menu_path), "Missing sweettv-menu.png")
        with Image.open(menu_path) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.size, (64, 64))
            arr = np.asarray(im)
            self.assertEqual(int(arr[0, 0, 3]), 0)
            col_alpha = arr[:, 32, 3] > 128
            bars = 0
            in_bar = False
            for opaque in col_alpha:
                if opaque and not in_bar:
                    bars += 1
                    in_bar = True
                elif not opaque:
                    in_bar = False
            self.assertEqual(bars, 3, f"Expected 3 burger bars in sweettv-menu.png, got {bars}")

        self.assertTrue(os.path.isfile(chip_active_path), "Missing sweettv-chip-active.png")
        with Image.open(chip_active_path) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.size, (48, 48))
            arr = np.asarray(im)
            cx_r, cx_g, cx_b, cx_a = (int(v) for v in arr[24, 24])
            self.assertEqual(cx_a, 255)
            self.assertLessEqual(abs(cx_r - 0x24), 4)
            self.assertLessEqual(abs(cx_g - 0x34), 4)
            self.assertLessEqual(abs(cx_b - 0x4D), 4)
            # 2px #00D2C6 outline near top midpoint (y=0..1, x=24)
            edge = arr[1, 24]
            self.assertGreater(int(edge[3]), 180)
            self.assertLess(int(edge[0]), 25)
            self.assertGreater(int(edge[1]), 180)
            self.assertGreater(int(edge[2]), 170)

    def test_collapsed_rail_burger_filter_togglebuttons_and_poster_grid_200_layout(self):
        root = self.tree()
        # 1. Collapsed rail burger replaces empty label
        burgers = [
            c for c in root.findall(".//control[@type='image']")
            if (c.findtext("texture") or "").strip() == "sweettv-menu.png"
        ]
        self.assertEqual(len(burgers), 1)
        b = burgers[0]
        self.assertEqual(
            (int(b.findtext("left")), int(b.findtext("top")), int(b.findtext("width")), int(b.findtext("height"))),
            (18, 36, 32, 32),
        )
        b_col = (b.findtext("colordiffuse") or b.find("texture").get("colordiffuse") or "").upper()
        self.assertEqual(b_col, "FF00D2C6")
        self.assertEqual((b.findtext("visible") or "").strip(), "!Control.HasFocus(100)")
        empty_collapsed_labels = [
            c for c in root.findall(".//control[@type='label']")
            if (c.findtext("visible") or "").strip() == "!Control.HasFocus(100)" and not (c.findtext("label") or "").strip()
        ]
        self.assertEqual(empty_collapsed_labels, [])

        # 2. Filter chips list 409: itemlayout & focusedlayout (222x48), pill 210x48, label 14..196, mutually-exclusive textures
        chips_list = self.control(root, 409)
        self.assertEqual(chips_list.get("type"), "list")
        for lname in ("itemlayout", "focusedlayout"):
            layout = chips_list.find(lname)
            self.assertIsNotNone(layout, lname)
            self.assertEqual((int(layout.get("width")), int(layout.get("height"))), (222, 48), lname)
            imgs = layout.findall("control[@type='image']")
            self.assertGreaterEqual(len(imgs), 2, lname)
            for im in imgs:
                self.assertEqual((int(im.findtext("width")), int(im.findtext("height"))), (210, 48), lname)
                tex = im.find("texture")
                self.assertIsNotNone(tex)
                self.assertEqual(tex.get("border"), "24", lname)
                self.assertIn((tex.text or "").strip(), ("sweettv-chip.png", "sweettv-chip-active.png"))
            for focus_id in (409, 200):
                for active_val in ("", "1"):
                    vis_imgs = [
                        im for im in imgs
                        if _eval_kodi_cond(im.findtext("visible") or "", {"filters": "1"}, {"active": active_val}, focus_id=focus_id)
                    ]
                    self.assertEqual(len(vis_imgs), 1, f"{lname} focus={focus_id} active={active_val!r} must show exactly 1 chip bg")
            lbls = layout.findall("control[@type='label']")
            self.assertGreaterEqual(len(lbls), 1, lname)
            for lbl in lbls:
                self.assertEqual(int(lbl.findtext("left")), 14, lname)
                self.assertEqual(int(lbl.findtext("width")), 182, lname)
                self.assertEqual((lbl.findtext("label") or "").strip(), "$INFO[ListItem.Label]", lname)
                self.assertEqual((lbl.findtext("selectedcolor") or "").strip(), (lbl.findtext("textcolor") or "").strip(), lname)

        # 3. Poster Grid 200: centered 240x356 poster, concentric focus ring, <onright>415</onright>, and padded logo mode
        panel = self.control(root, 200)
        self.assertEqual((panel.findtext("onright") or "").strip(), "415")
        cell_w = int(panel.find("itemlayout").get("width"))
        for layout_name in ("itemlayout", "focusedlayout"):
            layout = panel.find(layout_name)
            posters = [
                c for c in layout.findall("control[@type='image']")
                if c.find("texture") is not None and c.find("texture").get("diffuse") == "sweettv-poster-mask.png"
            ]
            self.assertGreaterEqual(len(posters), 1, layout_name)
            for p_img in posters:
                pw, ph, pleft, ptop = (int(p_img.findtext(k)) for k in ("width", "height", "left", "top"))
                self.assertEqual((pw, ph), (240, 356))
                self.assertEqual(pleft, (cell_w - 240) // 2)
                self.assertEqual(p_img.find("aspectratio").get("scalediffuse"), "false")
            if layout_name == "focusedlayout":
                ring = next(c for c in layout.findall("control[@type='image']") if c.findtext("texture") == "youtube-ring.png")
                rleft, rtop, rw, rh = (int(ring.findtext(k)) for k in ("left", "top", "width", "height"))
                p0 = posters[0]
                pleft, ptop = int(p0.findtext("left")), int(p0.findtext("top"))
                self.assertEqual(pleft - rleft, (rleft + rw) - (pleft + 240))
                self.assertEqual(ptop - rtop, (rtop + rh) - (ptop + 356))
        keep_logos_in_200 = [
            c for c in panel.findall(".//control[@type='image']")
            if c.find("aspectratio") is not None and (c.findtext("aspectratio") or "").strip() == "keep"
        ]
        self.assertGreaterEqual(len(keep_logos_in_200), 1, "Grid 200 must render padded keep logos for art_mode=logo cards")

    def test_section_title_hides_when_rail_focused_and_backdrop_fa080c14_within_34_textures(self):
        root = self.tree()
        sec_labels = [
            c for c in root.findall(".//control[@type='label']")
            if (c.findtext("label") or "").strip() == "$INFO[Window.Property(section_title)]"
        ]
        self.assertEqual(len(sec_labels), 1, "Expected single top-left section_title label")
        sec_lbl = sec_labels[0]
        self.assertEqual((int(sec_lbl.findtext("left")), int(sec_lbl.findtext("top"))), (96, 28))
        sec_vis = (sec_lbl.findtext("visible") or "").strip()
        self.assertIn("!Control.HasFocus(100)", sec_vis)

        rail_titles = [
            c for c in root.findall(".//control[@type='label']")
            if (c.findtext("label") or "").strip() == "SWEET.TV"
        ]
        self.assertEqual(len(rail_titles), 1)
        rail_vis = (rail_titles[0].findtext("visible") or "").strip()

        # Mutual exclusion between SWEET.TV rail header and section_title across focus states
        base_props = {"mode": "data", "modal": ""}
        self.assertFalse(_eval_kodi_cond(sec_vis, base_props, focus_id=100))
        self.assertTrue(_eval_kodi_cond(rail_vis, base_props, focus_id=100))
        for grid_focus in (200, 201, 409, 415):
            self.assertTrue(_eval_kodi_cond(sec_vis, base_props, focus_id=grid_focus), grid_focus)
            self.assertFalse(_eval_kodi_cond(rail_vis, base_props, focus_id=grid_focus), grid_focus)

        rail_backdrops = [
            c for c in root.findall(".//control[@type='image']")
            if (c.findtext("width") or "").strip() == "340"
            and (c.findtext("visible") or "").strip() == "Control.HasFocus(100)"
        ]
        self.assertEqual(len(rail_backdrops), 1, "Expected expanded width=340 rail backdrop")
        bg_col = (rail_backdrops[0].findtext("colordiffuse") or "").strip().upper()
        self.assertEqual(bg_col, "FA080C14")

        chip_items = [({"title": f"Chip {i}", "active": "1" if i == 0 else ""}, "") for i in range(8)]
        poster_items = {
            100: [({"title": f"Sec {i}"}, "") for i in range(7)],
            409: chip_items,
            200: [({"title": f"Film {i}", "meta": "2025", "bar": ""}, f"https://img/{i}.jpg") for i in range(10)],
        }
        wide_items = {
            100: [({"title": f"Sec {i}"}, "") for i in range(7)],
            409: chip_items,
            201: [({"title": f"Ch {i}", "now": "Live", "bar": "sweettv-bar-10.png"}, f"https://img/{i}.jpg") for i in range(4)],
        }
        for state_name, wprops, focus_id, c_items in (
            ("poster_rail_focused", {"mode": "data", "modal": "", "wide_grid": "", "filters": "1"}, 100, poster_items),
            ("wide_still_rail_focused", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1",
                                         "hero_art": "https://img/bg.jpg", "hero_is_logo": "",
                                         "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                         "has_guide": "1", "has_fav": "1"}, 100, wide_items),
            ("wide_logo_rail_focused", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1",
                                        "hero_art": "https://img/logo.png", "hero_is_logo": "1",
                                        "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                        "has_guide": "1", "has_fav": "1"}, 100, wide_items),
            ("poster_grid_focused", {"mode": "data", "modal": "", "wide_grid": "", "filters": "1"}, 200, poster_items),
            ("wide_grid_focused", {"mode": "data", "modal": "", "wide_grid": "1", "filters": "1",
                                   "hero_art": "https://img/bg.jpg", "hero_is_logo": "",
                                   "hero_pbar": "sweettv-pbar-10.png", "has_play": "1", "has_alt": "1",
                                   "has_guide": "1", "has_fav": "1"}, 201, wide_items),
        ):
            with self.subTest(state=state_name):
                vis_count = count_visible_textures(root, wprops, focus_id, container_items=c_items)
                self.assertGreater(vis_count, 0, state_name)
                self.assertLessEqual(vis_count, 34, f"{state_name} exceeded 34 GPU textures: {vis_count}")

    def test_framed_browse_hero_419_and_mutually_exclusive_logo_vs_still(self):
        root = self.tree()
        row_419 = self.control(root, 419)
        self.assertEqual(row_419.get("type"), "grouplist")
        child_ids = [int(c.get("id")) for c in row_419.findall("control") if (c.get("id") or "").isdigit()]
        self.assertEqual(child_ids, [417, 418, 416, 420])

        main_group = next(
            g for g in root.find("controls").findall("control[@type='group']")
            if "String.IsEmpty(Window.Property(modal))" in (g.findtext("visible") or "")
        )
        browse_hero_imgs = [
            c for c in main_group.findall(".//control[@type='image']")
            if "Window.Property(hero_art)" in (c.findtext("texture") or "")
            or (c.findtext("texture") or "").strip() in ("sweettv-fade-left.png", "sweettv-fade-bottom.png", "sweettv-fade-top.png")
        ]
        hero_group = next(
            (g for g in main_group.findall("control[@type='group']")
             if "Window.Property(wide_grid)" in (g.findtext("visible") or "")),
            None,
        )
        if hero_group is not None:
            card_masks = [
                c for c in hero_group.findall(".//control[@type='image']")
                if (c.findtext("texture") or "").strip() == "card-mask.png"
            ]
            self.assertEqual(card_masks, [], "Boxed card-mask.png must be removed from browse Hero")

        hero_art_imgs = [
            c for c in browse_hero_imgs
            if "Window.Property(hero_art)" in (c.findtext("texture") or "")
        ]
        grad_left = [c for c in browse_hero_imgs if (c.findtext("texture") or "").strip() == "sweettv-fade-left.png"]
        grad_bottom = [c for c in browse_hero_imgs if (c.findtext("texture") or "").strip() == "sweettv-fade-bottom.png"]
        grad_top = [c for c in browse_hero_imgs if (c.findtext("texture") or "").strip() == "sweettv-fade-top.png"]
        self.assertGreaterEqual(len(hero_art_imgs), 2, "Expected keep logo and scale still hero_art branches")
        self.assertGreaterEqual(len(grad_left), 1, "Expected sweettv-fade-left.png in Full-Bleed Browse Hero")
        self.assertGreaterEqual(len(grad_bottom), 1, "Expected sweettv-fade-bottom.png in Full-Bleed Browse Hero")
        self.assertGreaterEqual(len(grad_top), 1, "Expected sweettv-fade-top.png in Full-Bleed Browse Hero")

        props_logo = {"mode": "data", "modal": "", "wide_grid": "1", "emptycat": "", "hero_art": "https://img/l.png", "hero_is_logo": "1"}
        props_still = {"mode": "data", "modal": "", "wide_grid": "1", "emptycat": "", "hero_art": "https://img/s.jpg", "hero_is_logo": ""}
        vis_logo = [c for c in hero_art_imgs if _eval_kodi_cond(c.findtext("visible") or "", props_logo, focus_id=201)]
        vis_still = [c for c in hero_art_imgs if _eval_kodi_cond(c.findtext("visible") or "", props_still, focus_id=201)]
        self.assertEqual(len(vis_logo), 1)
        self.assertEqual((vis_logo[0].findtext("aspectratio") or "").strip(), "keep")
        self.assertEqual(
            (int(vis_logo[0].findtext("left")), int(vis_logo[0].findtext("top")),
             int(vis_logo[0].findtext("width")), int(vis_logo[0].findtext("height"))),
            (1240, 160, 520, 280),
        )
        self.assertEqual(len(vis_still), 1)
        self.assertEqual((vis_still[0].findtext("aspectratio") or "").strip(), "scale")
        self.assertEqual(
            (int(vis_still[0].findtext("left")), int(vis_still[0].findtext("top")),
             int(vis_still[0].findtext("width")), int(vis_still[0].findtext("height"))),
            (520, 0, 1400, 788),
        )
        for g_list, exp_geom, exp_col in (
            (grad_left, (520, 0, 880, 788), "FF0C111B"),
            (grad_bottom, (520, 320, 1400, 468), "FF0C111B"),
            (grad_top, (520, 0, 1400, 160), "FF0C111B"),
        ):
            self.assertFalse(any(_eval_kodi_cond(c.findtext("visible") or "", props_logo, focus_id=201) for c in g_list))
            vis_g = [c for c in g_list if _eval_kodi_cond(c.findtext("visible") or "", props_still, focus_id=201)]
            self.assertEqual(len(vis_g), 1)
            self.assertEqual(
                (int(vis_g[0].findtext("left")), int(vis_g[0].findtext("top")),
                 int(vis_g[0].findtext("width")), int(vis_g[0].findtext("height"))),
                exp_geom,
            )
            self.assertEqual((vis_g[0].findtext("colordiffuse") or "").upper(), exp_col)

    def test_rail_100_label2_width_and_browse_hero_419_button_geometry(self):
        root = self.tree()
        rail = self.control(root, 100)
        for layout_name in ("itemlayout", "focusedlayout"):
            layout = rail.find(layout_name)
            self.assertIsNotNone(layout, layout_name)
            rail_w = int(layout.get("width"))
            lbl1 = next(c for c in layout.findall("control[@type='label']") if c.findtext("label") == "$INFO[ListItem.Label]")
            lbl2 = next(c for c in layout.findall("control[@type='label']") if c.findtext("label") == "$INFO[ListItem.Label2]")
            left1 = int(lbl1.findtext("left"))
            w1 = int(lbl1.findtext("width"))
            left2 = int(lbl2.findtext("left"))
            w2 = int(lbl2.findtext("width"))
            self.assertEqual(w1, 168, layout_name)
            self.assertEqual(left2, 192, layout_name)
            self.assertGreaterEqual(w2, 68, layout_name)
            self.assertEqual(w2, 72, layout_name)
            self.assertLessEqual(left1 + w1, left2, layout_name)
            self.assertLessEqual(left2 + w2, rail_w, layout_name)

        row_419 = self.control(root, 419)
        w_419 = int(row_419.findtext("width"))
        self.assertEqual(w_419, 1320)
        self.assertEqual(int(row_419.findtext("itemgap")), 12)

        btn_416 = self.control(root, 416)
        w_416 = btn_416.find("width")
        self.assertIsNotNone(w_416)
        self.assertEqual((w_416.text or "").strip(), "auto")
        self.assertEqual((int(w_416.get("min")), int(w_416.get("max"))), (180, 340))

        for cid in (417, 418, 416, 420):
            btn = self.control(root, cid)
            self.assertEqual(int(btn.findtext("textoffsetx")), 18, cid)

        hero_props = {
            "mode": "data", "modal": "", "wide_grid": "1", "filters": "1", "emptycat": "",
            "hero_art": "https://img/bg.jpg", "hero_is_logo": "", "hero_pbar": "sweettv-pbar-10.png",
            "has_play": "1", "has_alt": "1", "has_guide": "1", "has_fav": "1",
        }
        wide_items = {
            100: [({"title": f"Sec {i}"}, "") for i in range(7)],
            409: [({"title": f"Chip {i}", "active": "1" if i == 0 else ""}, "") for i in range(8)],
            201: [({"title": f"Ch {i}", "now": "Live", "bar": "sweettv-bar-10.png"}, f"https://img/{i}.png") for i in range(4)],
        }
        vis_419 = count_visible_textures(root, hero_props, 419, container_items=wide_items)
        self.assertGreater(vis_419, 0)
        self.assertLessEqual(vis_419, 34, f"Browse Hero 419 state exceeded 34 GPU textures: {vis_419}")

    def test_unified_fullscreen_hero_hubs_and_strict_single_focus_410_400(self):
        root = self.tree()
        modal_group = next(
            g for g in root.find("controls").findall("control[@type='group']")
            if "!String.IsEmpty(Window.Property(modal))" in (g.findtext("visible") or "")
        )
        # No cramped 1480x900 popup box remains
        cramped = [
            g for g in modal_group.iter("control")
            if g.findtext("width") == "1480" and g.findtext("height") == "900"
        ]
        self.assertEqual(cramped, [], "Cramped 1480x900 popup box must be replaced by full-screen 1920x1080 Hero Hub")
        full_bg = [
            c for c in modal_group.findall("control[@type='image']")
            if c.findtext("width") == "1920" and c.findtext("height") == "1080"
            and "0C111B" in ((c.findtext("colordiffuse") or c.find("texture").get("colordiffuse") or "").upper())
        ]
        self.assertGreaterEqual(len(full_bg), 1, "Hub must have full-screen 1920x1080 #0C111B background")

        ms_titles = [
            c for c in modal_group.findall(".//control[@type='label']")
            if (c.findtext("font") or "").strip() == "MsTitle"
        ]
        self.assertGreaterEqual(len(ms_titles), 1, "Hub title must use MsTitle font")

        textboxes = [
            c for c in modal_group.findall(".//control[@type='textbox']")
            if "Window.Property(hero_desc)" in (c.findtext("label") or "")
        ]
        self.assertGreaterEqual(len(textboxes), 1)
        detail_props = {"mode": "data", "modal": "detail", "guide": "", "hero_desc": "Plot"}
        vis_detail_tb = [c for c in textboxes if _eval_kodi_cond(c.findtext("visible") or "", detail_props, focus_id=210)]
        self.assertGreaterEqual(len(vis_detail_tb), 1)
        self.assertGreaterEqual(int(vis_detail_tb[0].findtext("height")), 140, "Movie Hub textbox must expand for full synopsis")

        # Strict single-focus (#00D2C6) on tabs 410 and list 400
        tabs_410 = self.control(root, 410)
        list_400 = self.control(root, 400)
        for cid, container in ((410, tabs_410), (400, list_400)):
            il_str = ET.tostring(container.find("itemlayout"), encoding="unicode").upper()
            self.assertNotIn("00D2C6", il_str, f"Container {cid} itemlayout must not glow #00D2C6")
            fl = container.find("focusedlayout")
            teal_imgs = [
                c for c in fl.findall("control[@type='image']")
                if "00D2C6" in ((c.findtext("colordiffuse") or c.find("texture").get("colordiffuse") or "").upper())
            ]
            self.assertGreaterEqual(len(teal_imgs), 1, f"Container {cid} focusedlayout needs #00D2C6 focus image")
            for t_img in teal_imgs:
                vis_expr = (t_img.findtext("visible") or "").strip()
                self.assertTrue(
                    _eval_kodi_cond(vis_expr, {"mode": "data", "modal": "show", "guide": "1"}, focus_id=cid),
                    f"Container {cid} teal image must be visible when Control.HasFocus({cid})",
                )
                self.assertFalse(
                    _eval_kodi_cond(vis_expr, {"mode": "data", "modal": "show", "guide": "1"}, focus_id=210),
                    f"Container {cid} teal image must be hidden when !Control.HasFocus({cid})",
                )

        # Inactive selected tab in 410 uses sweettv-chip-active.png + white text (FFFFFFFF)
        fl_410 = tabs_410.find("focusedlayout")
        inactive_chip = [
            c for c in fl_410.findall("control[@type='image']")
            if (c.findtext("texture") or "").strip() == "sweettv-chip-active.png"
            and _eval_kodi_cond(c.findtext("visible") or "", {"mode": "data", "modal": "show", "guide": "1"}, focus_id=400)
            and not _eval_kodi_cond(c.findtext("visible") or "", {"mode": "data", "modal": "show", "guide": "1"}, focus_id=410)
        ]
        self.assertEqual(len(inactive_chip), 1, "Inactive selected tab in 410 must render sweettv-chip-active.png")
        inactive_white_lbl = [
            c for c in fl_410.findall("control[@type='label']")
            if (c.findtext("textcolor") or "").upper() == "FFFFFFFF"
            and _eval_kodi_cond(c.findtext("visible") or "", {"mode": "data", "modal": "show", "guide": "1"}, focus_id=400)
        ]
        self.assertGreaterEqual(len(inactive_white_lbl), 1, "Inactive selected tab in 410 must use white textcolor FFFFFFFF")

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



class SysPathRegressionTest(unittest.TestCase):
    def test_home_addon_and_sweettv_app_prepend_mediastick_lib_dir(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in (
            "device/kodi-addons/script.media-stick.home/default.py",
            "device/kodi-addons/script.media-stick.home/resources/lib/sweettv_app.py",
        ):
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("/usr/local/lib/media-stick", text, rel)
            self.assertIn("sys.path.insert(0,", text, rel)
        with open(os.path.join(root, "device/kodi-addons/script.media-stick.home/resources/lib/sweettv_app.py"), encoding="utf-8") as f:
            app_text = f.read()
        self.assertLess(app_text.index("sys.path.insert(0,"), app_text.index("import mediastick_resume"))

class FieldFixesAppTest(unittest.TestCase):
    def test_play_url_start_and_follow_skips_seek(self):
        self.assertEqual(data.play_url("15", "931394511", start=120), "plugin://plugin.video.sweettv/playvid/15|931394511?start=120")
        seeks = []
        class FakeIO:
            def __init__(self):
                self.n = 0
            def playing(self):
                self.n += 1
                return self.n == 1
            def position(self):
                return (120.0, 3600.0)
            def seek(self, s):
                seeks.append(s)
        ev = threading.Event()
        reported = []
        play.follow(play.Session("15", "931394511", "T", 0, 3600, url="u"), FakeIO(), ev, lambda s, p, t: reported.append((p, t)), seek_to=120, poll=0.0)
        self.assertEqual(seeks, [])
        self.assertEqual(reported, [(120.0, 3600.0)])

    def test_shows_split_chips_and_filter(self):
        from resources.lib import sweettv_sections as sections
        chips = sections.show_chips()
        self.assertEqual([k for k, _ in chips], ["all", "special", "tv"])
        rows = [
            {"id": "vod:1", "kind": "show_vod", "special": True, "title": "Orig"},
            {"id": "epg:2", "kind": "show_epg", "special": False, "title": "Bachelor"},
            {"id": "tv:3", "kind": "show_tv", "special": False, "title": "MasterChef"},
        ]
        self.assertEqual([r["id"] for r in sections.filter_shows(rows, "special")], ["vod:1"])
        self.assertEqual([r["id"] for r in sections.filter_shows(rows, "tv")], ["epg:2", "tv:3"])
        self.assertEqual(len(sections.filter_shows(rows, "all")), 3)






class SweetStoreCutoverTests(WindowCase):
    """Criterion 1A: SweetStore cutover, zero channelList.json/CHANNEL_FILE, and SweetStore.clear() on sign-out."""

    def test_zero_channellist_json_or_channel_file_references_in_home_addon(self):
        forbidden = re.compile(r"channelList\.json|CHANNEL_FILE")
        offenders = []
        for dirpath, dirnames, filenames in os.walk(ADDON):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if not fn.endswith((".py", ".xml")):
                    continue
                full = os.path.join(dirpath, fn)
                with open(full, encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        if forbidden.search(line):
                            offenders.append(f"{os.path.relpath(full, ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [], f"Forbidden channelList.json / CHANNEL_FILE references remain: {offenders}")

    def test_files_snapshot_reads_sweetstore_preserves_contract_and_reuses_stamp(self):
        st = sweetstore.default_store()
        st.clear()
        with mock.patch.object(files, "signed_in", return_value=True):
            snap_empty = files.snapshot(NOW, None, None, None)
            self.assertEqual((snap_empty.signed, snap_empty.catalog, snap_empty.has_file, snap_empty.unreadable),
                             (True, None, False, False))

            st.upsert_channels(answer(chan(10, "Ten", number=10), chan(20, "Twenty", number=20)), now=NOW - 30)
            snap_ok = files.snapshot(NOW, None, None, None)
            self.assertTrue(snap_ok.signed and snap_ok.has_file and not snap_ok.unreadable)
            self.assertIsNotNone(snap_ok.catalog)
            self.assertEqual([c.name for c in snap_ok.catalog.channels], ["Ten", "Twenty"])
            self.assertEqual(int(snap_ok.mtime), NOW - 30)

            # Unchanged store stamp reuses catalog without calling parse_catalog again
            with mock.patch.object(D, "parse_catalog", side_effect=AssertionError("must not re-parse unchanged store")):
                snap_reused = files.snapshot(NOW + 5, snap_ok.catalog, snap_ok.stamp, snap_ok.mtime)
            self.assertIs(snap_reused.catalog, snap_ok.catalog)

            # Transient SQLite / I/O error keeps previous catalog and marks unreadable=True
            with mock.patch.object(sweetstore.SweetStore, "get_channels_payload", side_effect=OSError("db busy")):
                snap_err = files.snapshot(NOW + 10, snap_ok.catalog, snap_ok.stamp, snap_ok.mtime)
            self.assertIs(snap_err.catalog, snap_ok.catalog)
            self.assertTrue(snap_err.unreadable)

    def test_signout_clears_sweetstore(self):
        st = sweetstore.default_store()
        st.upsert_channels(answer(chan(10, "Ten", number=10)), now=NOW)
        st.upsert_title_detail({"ok": True, "id": "vod:501", "title": "Film"}, now=NOW)
        st.put_swr("movies:0:1:0", {"items": [1]}, ttl_s=300, now=NOW)
        self.assertTrue(st.get_channels_payload(now=NOW).get("list"))

        sign(False)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.SIGNIN))
        self.assertEqual(st.get_channels_payload(now=NOW), {})
        self.assertIsNone(st.get_title_detail("vod:501"))
        self.assertIsNone(st.get_swr("movies:0:1:0", now=NOW))


class ResidentPlayerAndAutoplayTests(WindowCase):
    """Criterion 1B & 1C: NotifyAll playback dispatch, canonical can_archive, and 5s episode autoplay."""

    def _boot_in_memory(self, raw_doc=None):
        Fake.now = NOW
        raw_doc = raw_doc or answer(
            chan(10, "Ten", number=10, catchup=True, catchup_duration=7,
                 epg=[prog(NOW - 1800, NOW - 600, "Past ten", 8), prog(NOW - 600, NOW + 600, "Now ten", 9)]),
            chan(20, "LiveOnly", number=20, catchup=False,
                 epg=[prog(NOW - 600, NOW + 600, "Live twenty", 21)]),
        )
        sweetstore.default_store().upsert_channels(raw_doc, now=NOW)
        window = self.make()
        window.signed = True
        window.mode = D.DATA
        window.raw_catalog = raw_doc
        window._install(D.parse_catalog(raw_doc, NOW), NOW)
        return window

    def test_playback_dispatches_build_play_notify_for_live_from_start_vod_and_episodes(self):
        window = self._boot_in_memory()
        # 0. Existing 210 primary CTA in Movie Detail Hub must dispatch JSONRPC.NotifyAll sweettv.play (not Player.Open)
        init_card = sweettv_app.sections.vod_card(_sample_movie(501, "Film", owner_id=10), "movie")
        window._open_detail_modal(init_card)
        window.onClick(210)
        self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 1))
        r0 = json.loads(Fake.rpc[-1])
        self.assertEqual(r0["method"], "JSONRPC.NotifyAll")
        self.assertEqual(r0["params"]["message"], "sweettv.play")
        Fake.rpc.clear()
        # 1. Live channel via Browse Hero 417 -> kind=live, from_start=False
        window._open_section("channels")
        window.controls[201].selected = 0
        window._sync_hero()
        window.onClick(417)
        self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 1))
        d1 = json.loads(Fake.rpc[-1])["params"]["data"]
        self.assertEqual((d1["kind"], d1["cid"], d1["from_start"], d1["episode_mode"]), ("live", "10", False, False))

        # 2. «С начала (0:00)» via Browse Hero 418 -> kind=epg, from_start=True
        window.onClick(418)
        self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 2))
        d2 = json.loads(Fake.rpc[-1])["params"]["data"]
        self.assertEqual((d2["kind"], d2["cid"], d2["epg_id"], d2["from_start"], d2["episode_mode"]),
                         ("epg", "10", "9", True, False))

        # 3. Movie Detail Hub: 210 resumes at saved offset; 211 starts from 0:00 with from_start=True
        doc = MR.record(MR.empty(), "plugin://plugin.video.sweettv/playvod/501|null|10", 240, 7200, NOW - 10, {"title": "Film"})
        MR.save(doc)
        window.resume_doc = MR.load()
        mov_card = sweettv_app.sections.vod_card(_sample_movie(501, "Film", owner_id=10), "movie", window.resume_doc, set())
        with mock.patch.object(API, "vod_detail", return_value={"ok": True, "id": "vod:501", "movie_id": "501",
                                                                "title": "Film", "description": "Synopsis", "owner_id": 10,
                                                                "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|10",
                                                                "resume": 240, "seasons": []}):
            window._open_detail_modal(mov_card)
            window.onClick(210)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 3))
            d3 = json.loads(Fake.rpc[-1])["params"]["data"]
            self.assertEqual((d3["kind"], d3["movie_id"], d3["start_offset"], d3["from_start"], d3["episode_mode"]),
                             ("vod", "501", 240, False, False))

        with mock.patch.object(API, "vod_detail", return_value={"ok": True, "id": "vod:501", "movie_id": "501",
                                                                "title": "Film", "description": "Synopsis", "owner_id": 10,
                                                                "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|10",
                                                                "resume": 240, "seasons": []}):
            window._open_detail_modal(mov_card)
            window.onClick(211)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 4))
            d4 = json.loads(Fake.rpc[-1])["params"]["data"]
            self.assertEqual((d4["kind"], d4["movie_id"], d4["start_offset"], d4["from_start"], d4["episode_mode"]),
                             ("vod", "501", 0, True, False))

        # 4. EPG Show Hub episode click -> kind=epg, episode_mode=True
        epg_show_detail = {
            "ok": True, "id": "epg:801", "title": "MasterChef",
            "episodes": [{"epg": "8", "cid": "10", "title": "Ep 1", "start": NOW - 1800, "stop": NOW - 600,
                          "can_archive": True, "playable": True, "url": "plugin://plugin.video.sweettv/playvid/10|8"}],
        }
        show_card = sweettv_app.sections.show_card({"id": "epg:801", "kind": "show_epg", "title": "MasterChef"})
        with mock.patch.object(API, "show_detail", return_value=epg_show_detail):
            window._open_show_modal(show_card)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) == 1))
            window.controls[421].selected = 0
            window.onClick(421)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 5))
            d5 = json.loads(Fake.rpc[-1])["params"]["data"]
            self.assertEqual((d5["kind"], d5["cid"], d5["epg_id"], d5["episode_mode"]), ("epg", "10", "8", True))

    def test_show_hub_5s_autoplay_countdown_cancel_completion_and_negative_boundaries(self):
        window = self._boot_in_memory()
        detail = {
            "ok": True, "id": "vod:600", "movie_id": "600", "title": "TestSeries",
            "seasons": [{"id": 1, "number": 1, "title": "Season 1", "episodes": [
                {"id": 101, "episode_id": 101, "number": 1, "title": "Ep 1", "duration": 1400,
                 "owner_id": 10, "vod_url": "plugin://plugin.video.sweettv/playvod/600|101|10", "resume": 0, "watched": False},
                {"id": 102, "episode_id": 102, "number": 2, "title": "Ep 2", "duration": 1400,
                 "owner_id": 10, "vod_url": "plugin://plugin.video.sweettv/playvod/600|102|10", "resume": 0, "watched": False},
            ]}],
        }
        card = sweettv_app.sections.vod_card({"id": 600, "title": "TestSeries", "vod_url": "u"}, "series")
        with mock.patch.object(API, "vod_detail", return_value=detail):
            window._open_show_modal(card)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) == 2))

            # Adjacent negative 1: stopping early at 300s/1400s must NOT trigger autoplay countdown
            Fake.rpc.clear()
            window.controls[421].selected = 0
            window.onClick(421)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 1 and window.session is not None))
            window._report(window.session, 300, 1400)
            window._focus_back()
            self.assertEqual(window.getProperty("autoplay_text"), "")

            # Natural end of Ep 1 (1390s/1400s) -> sets autoplay_text; pressing Back cancels countdown without playing Ep 2
            window.controls[421].selected = 0
            window.onClick(421)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 2 and window.session is not None))
            window._report(window.session, 1390, 1400)
            window._focus_back()
            self.assertTrue(bool(window.getProperty("autoplay_text")), "Natural episode end must set autoplay_text countdown")
            self.press(window, BACK)
            self.assertEqual(window.getProperty("autoplay_text"), "")
            time.sleep(0.05)
            self.assertEqual(len(Fake.rpc), 2, "Canceled autoplay must not dispatch next episode")

            # Natural end allowed to finish countdown -> auto-dispatches Ep 2 with episode_mode=True
            real_later = window._later
            with mock.patch.object(window, "_later", side_effect=lambda name, delay, fn: real_later(name, min(delay, 0.01), fn)):
                ep1_row = dict(window.modal_seasons[0]["episodes"][0], resume=0, watched=False)
                window._play_modal_row(ep1_row, season_num=1)
                self.assertTrue(wait_for(lambda: len(Fake.rpc) == 3 and window.session is not None))
                window._report(window.session, 1390, 1400)
                window._focus_back()
                self.assertTrue(wait_for(lambda: len(Fake.rpc) >= 4, timeout=6.0), "5s autoplay did not dispatch Ep 2")
            d_auto = json.loads(Fake.rpc[-1])["params"]["data"]
            self.assertEqual((d_auto["kind"], d_auto["movie_id"], d_auto["episode_id"], d_auto["episode_mode"]),
                             ("vod", "600", "102", True))
            self.assertEqual(window.getProperty("autoplay_text"), "")

            # Adjacent negative 2: natural end of final episode Ep 2 -> no next episode, autoplay_text stays empty
            if window.session is not None:
                window._report(window.session, 1390, 1400)
                window._focus_back()
            self.assertEqual(window.getProperty("autoplay_text"), "")

    def test_canonical_can_archive_across_items_sections_and_guide(self):
        for fname in ("sweettv_items.py", "sweettv_sections.py", "sweettv_guide.py"):
            path = os.path.join(ADDON, "resources", "lib", fname)
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("playable_in_archive", f.read(), f"{fname} must use canonical can_archive")

        # Pure table check on guide_items & search_card with ONLY can_archive present
        g_items = IT.guide_items([
            {"title": "OnAir", "live": True, "can_archive": True, "start": NOW - 300, "when": "07:55"},
            {"title": "Archived", "live": False, "can_archive": True, "start": NOW - 3600, "when": "07:00"},
            {"title": "NoCatchupPast", "live": False, "can_archive": False, "start": NOW - 3600, "when": "07:00"},
            {"title": "Upcoming", "live": False, "can_archive": False, "start": NOW + 3600, "when": "09:00"},
        ])
        self.assertEqual([li.getProperty("kind") for li in g_items], ["live", "archive", "future", "future"])

        s_yes = sweettv_app.sections.search_card({
            "kind": "programme", "id": "8", "title": "Past ten", "cid": "10", "epg": "8",
            "start": NOW - 1800, "stop": NOW - 600, "channel_name": "Ten", "when": "07:30",
            "live": False, "can_archive": True, "playable": True, "available": True,
        })
        s_no = sweettv_app.sections.search_card({
            "kind": "programme", "id": "22", "title": "Future", "cid": "10", "epg": "22",
            "start": NOW + 1800, "stop": NOW + 3600, "channel_name": "Ten", "when": "08:30",
            "live": False, "can_archive": False, "playable": False, "available": True,
        })
        self.assertTrue(s_yes.catchup)
        self.assertFalse(s_no.catchup)

        # Guide row click with ONLY can_archive
        window = self._boot_in_memory()
        day_rows = [
            {"epg": "8", "cid": "10", "title": "Past ten", "start": NOW - 1800, "stop": NOW - 600,
             "when": "07:30", "live": False, "can_archive": True, "available": True},
            {"epg": "22", "cid": "10", "title": "Future ten", "start": NOW + 1800, "stop": NOW + 3600,
             "when": "08:30", "live": False, "can_archive": False, "available": True},
        ]
        with mock.patch.object(API, "day", return_value={"ok": True, "cid": "10", "items": day_rows}):
            window._open_section("channels")
            window.controls[201].selected = 0
            window.onClick(201)
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) == 2))
            Fake.rpc.clear()
            Fake.notes.clear()
            window.controls[400].selected = 0
            window.onClick(400)
            self.assertTrue(wait_for(lambda: len(Fake.rpc) == 1))
            self.assertEqual(json.loads(Fake.rpc[-1])["params"]["data"]["epg_id"], "8")

            window.controls[400].selected = 1
            window.onClick(400)
            self.assertEqual(len(Fake.rpc), 1)
            self.assertTrue(Fake.notes)


class HubsNavigationAndFixesTests(WindowCase):
    """Section 3: D-pad Left/Right on 400, Right->415 Search jump, Channel Hub deep-links, Poster race fix, and RU localization."""

    def _boot_in_memory(self, raw_doc=None, lang="en"):
        Fake.now = NOW
        Fake.home["media-stick.lang"] = lang
        W.set_language(lang)
        raw_doc = raw_doc or answer(
            chan(15, "Новый Канал", number=1, catchup=True, catchup_duration=7, icon_v2_url="https://img/nk-logo.png",
                 epg=[prog(NOW - 3600, NOW - 1800, "Ранок", 500),
                      prog(NOW - 600, NOW + 1800, "Холостяк", 501, description="Романтичне реаліті")]),
            chan(16, "Прямий", number=2, catchup=False, icon_v2_url="https://img/pr-logo.png",
                 epg=[prog(NOW - 600, NOW + 1800, "Новини", 601)]),
        )
        sweetstore.default_store().upsert_channels(raw_doc, now=NOW)
        window = self.make()
        window.signed = True
        window.mode = D.DATA
        window.raw_catalog = raw_doc
        window._install(D.parse_catalog(raw_doc, NOW), NOW)
        for k, v in W.labels().items():
            window._prop(k, v)
        return window

    def test_dpad_left_right_on_list_400_switches_season_and_day_tabs_without_leaving_400(self):
        window = self._boot_in_memory()
        detail = {
            "ok": True, "id": "vod:700", "movie_id": "700", "title": "ThreeSeasons",
            "seasons": [
                {"id": 1, "number": 1, "title": "S1", "episodes": [{"id": 11, "episode_id": 11, "number": 1, "title": "S1E1", "duration": 1200, "vod_url": "plugin://plugin.video.sweettv/playvod/700|11|1"}]},
                {"id": 2, "number": 2, "title": "S2", "episodes": [{"id": 21, "episode_id": 21, "number": 1, "title": "S2E1", "duration": 1200, "vod_url": "plugin://plugin.video.sweettv/playvod/700|21|1"}]},
                {"id": 3, "number": 3, "title": "S3", "episodes": [{"id": 31, "episode_id": 31, "number": 1, "title": "S3E1", "duration": 1200, "vod_url": "plugin://plugin.video.sweettv/playvod/700|31|1"}]},
            ],
        }
        card = sweettv_app.sections.vod_card({"id": 700, "title": "ThreeSeasons", "vod_url": "u"}, "series")
        with mock.patch.object(API, "vod_detail", return_value=detail):
            window._open_show_modal(card)
            self.assertTrue(wait_for(lambda: len(window.modal_seasons) == 3 and window.focus == 421))
            self.assertEqual(window.modal_tab_idx, 0)

            # Left/Right on horizontal episode panel 421 must NOT switch season tabs (421 scrolls episodes horizontally)
            self.press(window, 2)  # ACTION_MOVE_RIGHT
            self.assertEqual((window.modal_tab_idx, window.focus), (0, 421))
            self.press(window, 1)  # ACTION_MOVE_LEFT
            self.assertEqual((window.modal_tab_idx, window.focus), (0, 421))

            # Explicit season tab switch updates 421 items
            window._modal_select_tab(1, keep_focus=True)
            self.assertEqual((window.modal_tab_idx, window.controls[410].selected, window.controls[421].items[0].label),
                             (1, 1, "S2E1"))

        # Also verify Left/Right on 400 switches day tabs in Channel Hub
        self.press(window, BACK)
        with mock.patch.object(API, "day", side_effect=lambda cid, day_ts, *a, **kw: {
            "ok": True, "cid": str(cid), "items": [{"epg": str(day_ts), "cid": str(cid), "title": f"Day {day_ts}",
                                                    "start": int(day_ts), "stop": int(day_ts) + 600, "when": "12:00",
                                                    "live": False, "can_archive": True, "available": True}],
        }):
            window._open_section("channels")
            window.controls[201].selected = 0
            window.onClick(201)
            self.assertTrue(wait_for(lambda: len(window.controls[410].items) > 2 and window.focus == 400))
            start_tab = window.modal_tab_idx
            self.press(window, 1)  # Left -> previous day
            self.assertEqual((window.modal_tab_idx, window.focus), (start_tab - 1, 400))
            self.press(window, 2)  # Right -> back to today
            self.assertEqual((window.modal_tab_idx, window.focus), (start_tab, 400))

    def test_poster_grid_right_jumps_to_search_415_and_back_restores_pre_search_pos(self):
        window = self._boot_in_memory()
        movies = [_sample_movie(100 + i, f"Film {i}") for i in range(12)]
        with mock.patch.object(API, "configuration", return_value=_sample_config()),                 mock.patch.object(API, "catalog_page", return_value={"ok": True, "section": "movies", "items": movies, "total": 12}):
            window._open_section("movies")
            self.assertTrue(wait_for(lambda: len(window.controls[200].items) == 12))
            window.focus = 200

            # Adjacent negative: middle column (index 2 of 5-column row) pressing Right does NOT jump to 415
            window.controls[200].selected = 2
            self.press(window, KEY_RIGHT)
            self.assertEqual(window.focus, 200)

            # Rightmost column (index 9: row 1, col 4) pressing Right jumps to top Search 415
            window.controls[200].selected = 9
            self.press(window, KEY_RIGHT)
            self.assertEqual(window.focus, 415)

            # Even if grid selection moved, Back from 415 restores exact _pre_search_pos (9) and focus 200
            window.controls[200].selected = 0
            self.press(window, BACK)
            self.assertEqual(window.focus, 200)
            self.assertEqual(window.controls[200].selected, 9)

    def test_movie_detail_hub_hydrates_rich_synopsis_age_genres_countries_never_blank(self):
        window = self._boot_in_memory(lang="ru")
        rich_detail = {
            "ok": True, "id": "vod:501", "movie_id": "501", "title": "Начало",
            "description": "Кобб крадет тайны из подсознания во время сна.",
            "age_rating": "16+", "genres": [12], "genre_names": ["Фантастика", "Триллер"],
            "countries": ["США", "Великобритания"], "year": 2010, "duration": 8880, "imdb": 8.8,
            "owner_id": 10, "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|10",
            "poster": "https://img/501.jpg", "banner": "https://img/501-bg.jpg", "seasons": [],
        }
        bare_card = sweettv_app.sections.vod_card(_sample_movie(501, "Начало", year=2010, imdb=8.8), "movie")
        self.assertEqual(bare_card.desc, "")
        with mock.patch.object(API, "vod_detail", return_value=rich_detail):
            window._open_detail_modal(bare_card)
            self.assertTrue(wait_for(lambda: "Кобб крадет тайны" in window.getProperty("hero_desc")))
        self.assertEqual(window.getProperty("modal"), "detail")
        self.assertEqual(window.getProperty("has_guide"), "")
        combined = f"{window.getProperty('hero_meta')} {window.getProperty('hero_desc')}"
        for expected in ("16+", "Фантастика", "США", "Кобб крадет тайны"):
            self.assertIn(expected, combined)

    def test_channel_hub_hydration_spoiler_safe_ctas_and_search_archive_deeplinks(self):
        window = self._boot_in_memory(lang="ru")
        st = sweetstore.default_store()
        yesterday_ts = NOW - 86400
        st.upsert_epg("15", [
            {"id": 450, "text": "Вечерний выпуск", "time_start": yesterday_ts - 1800, "time_stop": yesterday_ts, "available": True},
            {"id": 451, "text": "МастерШеф", "time_start": yesterday_ts, "time_stop": yesterday_ts + 3600, "available": True},
        ], now=NOW)

        # 1. Search archive & live airing formatting (time/status first) + art_mode="logo"
        live_airing = sweettv_app.sections.search_card({
            "kind": "programme", "id": "501", "title": "Холостяк", "cid": "15", "epg": "501",
            "start": NOW - 600, "stop": NOW + 1800, "channel_name": "Новый Канал", "when": "07:50",
            "live": True, "can_archive": True, "playable": True, "available": True, "image_url": "https://img/nk-logo.png",
        })
        arch_airing = sweettv_app.sections.search_card({
            "kind": "programme", "id": "451", "title": "МастерШеф", "cid": "15", "epg": "451",
            "start": yesterday_ts, "stop": yesterday_ts + 3600, "channel_name": "Новый Канал", "when": "21:00",
            "live": False, "can_archive": True, "playable": True, "available": True, "image_url": "https://img/nk-logo.png",
        })
        vod_movie = sweettv_app.sections.search_card({
            "kind": "movie", "id": "900", "title": "Дюна", "subtitle": "2021", "cid": "", "epg": "",
            "start": 0, "stop": 0, "channel_name": "", "when": "", "live": False, "can_archive": False,
            "playable": True, "available": True, "vod_url": "plugin://plugin.video.sweettv/playvod/900|null|10",
            "image_url": "https://img/dune.jpg",
        })
        self.assertTrue(" ".join(live_airing.meta.split()).startswith("В эфире · Новый Канал"), live_airing.meta)
        self.assertTrue(" ".join(arch_airing.meta.split()).startswith("21:00 · Новый Канал"), arch_airing.meta)
        self.assertEqual(IT.card_props(live_airing).get("art_mode"), "logo")
        self.assertEqual(IT.card_props(arch_airing).get("art_mode"), "logo")
        self.assertNotEqual(IT.card_props(vod_movie).get("art_mode"), "logo")

        # 2. Immediate SweetStore.channel_day hydration before async sweetapi.day() completes + RU spoiler-safe CTAs
        self.assertTrue(callable(getattr(window, "_open_channel_hub", None)), "Missing _open_channel_hub")
        api_gate = threading.Event()

        def slow_day(cid, day_unix, *a, **kw):
            api_gate.wait(1.0)
            return {
                "ok": True, "cid": str(cid), "items": [
                    {"epg": "500", "cid": "15", "title": "Ранок", "start": NOW - 3600, "stop": NOW - 1800,
                     "when": "07:00", "live": False, "can_archive": True, "available": True},
                    {"epg": "501", "cid": "15", "title": "Холостяк (API)", "start": NOW - 600, "stop": NOW + 1800,
                     "when": "07:50", "live": True, "can_archive": True, "available": True},
                ],
            }

        with mock.patch.object(API, "day", side_effect=slow_day):
            window._open_section("channels")
            window.controls[201].selected = 0
            window.onClick(201)
            # Hydrated synchronously from SweetStore BEFORE api_gate is set!
            self.assertTrue(window._modal_open())
            self.assertGreaterEqual(len(window.controls[400].items), 1, "Channel Hub must hydrate immediately from SweetStore.channel_day")
            self.assertEqual(window.getProperty("has_guide"), "")
            self.assertEqual(window.controls[210].getLabel() or window.getProperty("hero_play"), "Смотреть эфир")
            self.assertEqual(window.controls[211].getLabel() or window.getProperty("hero_alt"), "С начала (0:00)")
            self.assertEqual((window.getProperty("has_play"), window.getProperty("has_alt")), ("1", "1"))
            api_gate.set()
            self.assertTrue(wait_for(lambda: any("Холостяк (API)" in i.label for i in window.controls[400].items)))

        # Adjacent negative: channel 16 without catchup hides 211 (has_alt == "")
        self.press(window, BACK)
        with mock.patch.object(API, "day", return_value={"ok": True, "cid": "16", "items": []}):
            window.controls[201].selected = 1
            window.onClick(201)
            self.assertEqual(window.getProperty("has_alt"), "")
        self.press(window, BACK)

        # 3. Clicking an archived programme in Search deep-links into Channel Hub on target_day ("Вчера") & target_epg ("451")
        Fake.rpc.clear()
        with mock.patch.object(API, "day", return_value={
            "ok": True, "cid": "15", "items": [
                {"epg": "450", "cid": "15", "title": "Вечерний выпуск", "start": yesterday_ts - 1800, "stop": yesterday_ts,
                 "when": "07:30", "live": False, "can_archive": True, "available": True},
                {"epg": "451", "cid": "15", "title": "МастерШеф", "start": yesterday_ts, "stop": yesterday_ts + 3600,
                 "when": "08:00", "live": False, "can_archive": True, "available": True},
            ],
        }):
            window.section = "search"
            window._prop("wide_grid", "")
            window._apply_cards([arch_airing])
            window.focus = 200
            window.controls[200].selected = 0
            window.onClick(200)
            self.assertEqual(Fake.rpc, [], "Clicking Search archive airing must open Channel Hub, not raw playback")
            self.assertTrue(window._modal_open())
            self.assertTrue(wait_for(lambda: len(window.controls[400].items) == 2))
            self.assertEqual(window.controls[410].items[window.modal_tab_idx].label, "Вчера")
            self.assertEqual(window.controls[400].selected, 1)
            self.assertEqual(window.controls[400].items[1].label, "МастерШеф")

    def test_poster_race_fix_sync_hero_ignores_none_in_modal_and_cancels_timer_on_immediate(self):
        window = self._boot_in_memory()
        card_a = sweettv_app.sections.vod_card(_sample_movie(101, "Card A"), "movie")
        card_b = sweettv_app.sections.vod_card(_sample_movie(102, "Hub B"), "movie")
        window._apply_cards([card_a, card_b])
        # First hero_art sets initial banner; moving selection schedules 0.18s hero_art timer
        window.controls[200].selected = 1
        window._sync_hero()
        window.controls[200].selected = 0
        window._sync_hero()
        self.assertIn("hero_art", window._timers)

        # Opening Hub (or calling _sync_hero(..., immediate=True)) cancels pending 0.18s timer immediately
        with mock.patch.object(API, "vod_detail", return_value={"ok": True, "id": "vod:102", "movie_id": "102",
                                                                "title": "Hub B", "description": "Plot B",
                                                                "banner": card_b.banner, "seasons": []}):
            window._open_detail_modal(card_b)
        self.assertNotIn("hero_art", window._timers)
        self.assertEqual(window.getProperty("hero_art"), card_b.banner)
        time.sleep(0.22)
        self.assertEqual(window.getProperty("hero_art"), card_b.banner, "Pending grid hero_art timer leaked into open Hub")

        # While _modal_open(), _sync_hero(card=None) is a no-op
        window._sync_hero()
        self.assertEqual(window.getProperty("hero_title"), "Hub B")
        self.assertEqual(window.getProperty("hero_art"), card_b.banner)

        # Explicit card with immediate=True inside modal DOES update immediately without scheduling timer
        updated_b = card_b._replace(banner="https://img/102-hd.jpg", desc="Updated Plot")
        window._sync_hero(updated_b, immediate=True)
        self.assertNotIn("hero_art", window._timers)
        self.assertEqual(window.getProperty("hero_art"), "https://img/102-hd.jpg")

    def test_russian_day_tabs_ascending_season_labels_and_episode_fallback(self):
        # Mon 2026-11-23 12:00 UTC -> offset -3 is Fri 20.11, -1 Вчера, 0 Сегодня, +1 Завтра
        mon_2026_11_23 = 1795435200
        W.set_language("ru")
        ru_tabs = [lbl for _, lbl in sweettv_app.sections.day_tabs(3, 2, mon_2026_11_23)]
        self.assertEqual(ru_tabs, ["Пт 20.11", "Сб 21.11", "Вчера", "Сегодня", "Завтра", "Ср 25.11"])
        self.assertEqual([lbl for _, lbl in sweettv_app.sections.day_tabs(0, 0, mon_2026_11_23)], ["Сегодня"])

        W.set_language("uk")
        uk_tabs = [lbl for _, lbl in sweettv_app.sections.day_tabs(1, 1, mon_2026_11_23)]
        self.assertEqual(uk_tabs, ["Вчора", "Сьогодні", "Завтра"])

        W.set_language("en")
        en_tabs = [lbl for _, lbl in sweettv_app.sections.day_tabs(3, 1, mon_2026_11_23)]
        self.assertEqual(en_tabs, ["Fri 20.11", "Sat 21.11", "Yesterday", "Today", "Tomorrow"])

        # Episode fallback "1 серия".."N серия" in Russian when title is missing, preserving real titles
        W.set_language("ru")
        ep_items = IT.episode_items([
            {"id": 1, "number": 1, "title": "", "duration": 1800},
            {"id": 2, "number": 2, "title": "   ", "duration": 1800},
            {"id": 3, "number": 3, "title": "Финал", "duration": 2400},
        ])
        self.assertEqual([li.label for li in ep_items], ["1 серия", "2 серия", "Финал"])

        # Ascending season labels ("1 сезон", "2 сезон") in Show/Series Hub
        window = self._boot_in_memory(lang="ru")
        unsorted_detail = {
            "ok": True, "id": "vod:888", "movie_id": "888", "title": "Сериал",
            "seasons": [
                {"id": 20, "number": 2, "title": "", "episodes": [{"id": 201, "episode_id": 201, "number": 1, "title": "", "duration": 1500, "vod_url": "plugin://plugin.video.sweettv/playvod/888|201|1"}]},
                {"id": 10, "number": 1, "title": "", "episodes": [{"id": 101, "episode_id": 101, "number": 1, "title": "", "duration": 1500, "vod_url": "plugin://plugin.video.sweettv/playvod/888|101|1"}]},
            ],
        }
        card = sweettv_app.sections.vod_card({"id": 888, "title": "Сериал", "vod_url": "u"}, "series")
        with mock.patch.object(API, "vod_detail", return_value=unsorted_detail):
            window._open_show_modal(card)
            self.assertTrue(wait_for(lambda: len(window.controls[410].items) == 2))
        self.assertEqual([li.label for li in window.controls[410].items], ["1 сезон", "2 сезон"])
        self.assertEqual(window.controls[421].items[0].label, "1 серия")


class SectionSwitchWideGridAndHydrationTests(WindowCase):
    """Issue #72: togglebutton RuntimeError safety, independent 200/201 ListItems, 16:9 banners, and Continue hydration."""

    def test_togglebutton_runtime_error_across_all_seven_sections_and_stub_fallback(self):
        Fake.now = NOW
        raw = answer(
            chan(10, "СТБ HD", number=1, category=[1], catchup=True, catchup_duration=7,
                 icon_v2_url="https://img/stb-logo.png", banner_url="https://img/stb-ban.jpg",
                 epg=[prog(NOW - 600, NOW + 1200, "МастерШеф", 101)]),
            chan(20, "24/7 Комедия", number=2, category=[2], is_fast_channel=True,
                 icon_v2_url="https://img/fast-logo.png", banner_url="https://img/fast-ban.jpg"),
            categories=[{"id": 1, "caption": "Шоу"}, {"id": 2, "caption": "Комедия"}],
        )
        write_list(raw)
        doc = MR.record(MR.empty(), "plugin://plugin.video.sweettv/playvod/501|null|10", 600, 3600, NOW - 15,
                        {"title": "Continue Film", "thumb": "https://img/501.jpg"})
        MR.save(doc)
        MR.toggle_fav("vod:502", {"title": "Fav Film", "thumb": "https://img/502.jpg"}, now=NOW)

        movies_resp = {"ok": True, "section": "movies", "items": [_sample_movie(501, "Film One")], "total": 1}
        series_resp = {"ok": True, "section": "series", "items": [_sample_movie(601, "Series One")], "total": 1}
        top_resp = {"ok": True, "items": [
            {"kind": "movie", "id": "701", "title": "Top Search Hit", "subtitle": "2025", "cid": "", "epg": "",
             "start": 0, "stop": 0, "channel_name": "", "when": "", "live": False, "playable_in_archive": False,
             "playable": True, "available": True, "vod_url": "plugin://plugin.video.sweettv/playvod/701|null|0",
             "preview": "", "image_url": "https://img/701.jpg", "repeats": 0, "more": ""},
        ], "count": 1}

        with mock.patch.object(API, "shows", return_value=_sample_shows()), \
                mock.patch.object(API, "configuration", return_value=_sample_config()), \
                mock.patch.object(API, "catalog_page", side_effect=lambda sec, **kw: series_resp if sec == "series" else movies_resp), \
                mock.patch.object(API, "top_search", return_value=top_resp):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))

            rail_order = [k for k, _ in sweettv_app.sections.RAIL]
            expected_by_section = (
                ("shows", 200, ["Holostyak", "MasterChef"], "1"),
                ("series", 200, ["Series One"], "1"),
                ("movies", 200, ["Film One"], "1"),
                ("channels", 201, ["СТБ HD"], "1"),
                ("continue", 201, ["Continue Film"], ""),
                ("favourites", 201, ["Fav Film"], ""),
                ("search", 200, ["Top Search Hit"], "1"),
            )
            for sec, grid_cid, expected_labels, expected_filters in expected_by_section:
                with self.subTest(section=sec):
                    window.controls[MENU].selected = rail_order.index(sec)
                    window.onClick(MENU)
                    self.assertTrue(
                        wait_for(lambda g=grid_cid, exp=expected_labels: [i.label for i in window.controls[g].items] == exp),
                        f"Section {sec!r} failed to populate expected cards; got {[i.label for i in window.controls[grid_cid].items]}",
                    )
                    self.assertEqual(window.section, sec)
                    self.assertEqual(window.getProperty("filters"), expected_filters)
                    if expected_filters:
                        self.assertTrue(window.controls[409].items)
                        active_keys = [i.getProperty("key") for i in window.controls[409].items if i.getProperty("active") == "1"]
                        self.assertEqual(len(active_keys), 1)
                    else:
                        self.assertEqual(window.controls[409].items, [])

            # Clicking "fast" ("24/7") chip in 409 list on channels filters to 24/7 channels
            window.controls[MENU].selected = rail_order.index("channels")
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[201].items) == 1))
            fast_idx = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "fast")
            window.controls[409].selectItem(fast_idx)
            window.onClick(409)
            self.assertEqual([i.label for i in window.controls[201].items], ["24/7 Комедия"])
            self.assertEqual(window.controls[409].items[fast_idx].getProperty("active"), "1")

    def test_channel_banner_hero_logo_mode_and_wide_vs_poster_card_props(self):
        import inspect

        ch_banner = D.parse_channel({
            "id": 15, "name": "СТБ HD", "number": 1, "available": True, "catchup": True, "catchup_duration": 7,
            "icon_v2_url": "https://img/stb-sq.png", "banner_url": "https://img/stb-wide.jpg", "epg": [],
        }, NOW)
        self.assertTrue(hasattr(ch_banner, "banner"), "Channel NamedTuple must expose trailing banner field")
        self.assertEqual(ch_banner.logo, "https://img/stb-sq.png")
        self.assertEqual(ch_banner.banner, "https://img/stb-wide.jpg")

        for bad_banner in ("", None, "   ", "ftp://bad.example/x.jpg", 123):
            ch_no_ban = D.parse_channel({
                "id": 16, "name": "Demo Ch", "number": 2, "available": True,
                "icon_v2_url": "https://img/demo-sq.png", "banner_url": bad_banner, "epg": [],
            }, NOW)
            self.assertEqual(ch_no_ban.banner, "", repr(bad_banner))
        self.assertEqual(D.Channel("1", "C", 1, "https://img/l.png", (), False, ()).banner, "")

        c_with_ban = sweettv_app.sections.channel_card(ch_banner, {}, NOW)
        ch_bannerless = D.parse_channel({
            "id": 16, "name": "Demo Ch", "number": 2, "available": True,
            "icon_v2_url": "https://img/demo-sq.png", "epg": [],
        }, NOW)
        c_no_ban = sweettv_app.sections.channel_card(ch_bannerless, {}, NOW)
        self.assertTrue(hasattr(c_with_ban, "wide_art"), "Card NamedTuple must expose trailing wide_art field")
        self.assertEqual((c_with_ban.art, c_with_ban.art_mode, c_with_ban.wide_art, c_with_ban.banner),
                         ("https://img/stb-sq.png", "logo", "https://img/stb-wide.jpg", "https://img/stb-wide.jpg"))
        self.assertEqual((c_no_ban.art, c_no_ban.art_mode, c_no_ban.wide_art, c_no_ban.banner),
                         ("https://img/demo-sq.png", "logo", "", "https://img/demo-sq.png"))

        c_vod = sweettv_app.sections.vod_card(_sample_movie(501, "Dune"), "movie")
        for label, card_obj, expected_is_logo in (
            ("channel_with_banner", c_with_ban, ""),
            ("channel_bannerless_logo", c_no_ban, "1"),
            ("vod_movie_backdrop", c_vod, ""),
            ("none_card", None, ""),
        ):
            with self.subTest(hero=label):
                self.assertEqual(sweettv_app.sections.hero_info(card_obj)["hero_is_logo"], expected_is_logo)

        for fn_name, fn in (("card_props", IT.card_props), ("apply_card", IT.apply_card), ("card_item", IT.card_item)):
            self.assertIn("wide", inspect.signature(fn).parameters, f"{fn_name} must accept wide=False")

        # Combinatoric wide=False vs wide=True artwork & art_mode matrix
        cases = (
            ("channel_with_banner_poster", c_with_ban, False, "https://img/stb-sq.png", "logo"),
            ("channel_with_banner_wide", c_with_ban, True, "https://img/stb-wide.jpg", ""),
            ("channel_bannerless_poster", c_no_ban, False, "https://img/demo-sq.png", "logo"),
            ("channel_bannerless_wide", c_no_ban, True, "https://img/demo-sq.png", "logo"),
            ("vod_poster", c_vod, False, "https://img/501.jpg", ""),
            ("vod_wide", c_vod, True, "https://img/501-bg.jpg", ""),
        )
        for name, card_obj, is_wide, exp_icon, exp_mode in cases:
            with self.subTest(case=name):
                props = IT.card_props(card_obj, wide=is_wide)
                self.assertEqual(props["art_mode"], exp_mode)
                li = IT.card_item(card_obj, wide=is_wide)
                self.assertEqual(li.art.get("icon"), exp_icon)
                self.assertEqual(li.getProperty("art_mode"), exp_mode)

        # show_card passes art_mode and wide_art through and integrates with sweetapi.shows() inline EPG shows
        sc_direct = sweettv_app.sections.show_card({
            "id": "tv:444", "kind": "show_tv", "title": "Супермама",
            "poster": "https://img/stb-sq.png", "banner": "https://img/stb-wide.jpg",
            "art_mode": "logo", "wide_art": "https://img/stb-wide.jpg",
        })
        self.assertEqual((sc_direct.art, sc_direct.art_mode, sc_direct.wide_art, sc_direct.banner),
                         ("https://img/stb-sq.png", "logo", "https://img/stb-wide.jpg", "https://img/stb-wide.jpg"))
        self.assertEqual(sweettv_app.sections.hero_info(sc_direct)["hero_is_logo"], "")

        raw_for_shows = {"list": [
            {
                "id": 15, "name": "СТБ HD", "catchup": True, "catchup_duration": 7, "available": True,
                "icon_v2_url": "https://img/stb-sq.png", "banner_url": "https://img/stb-wide.jpg",
                "epg": [{"id": 701, "text": "Супермама Випуск 2", "time_start": NOW - 3600, "time_stop": NOW - 1800,
                         "tv_show_id": 301, "available": True}],
            },
            {
                "id": 16, "name": "LogoOnly", "catchup": True, "catchup_duration": 7, "available": True,
                "icon_v2_url": "https://img/only-sq.png",
                "epg": [{"id": 702, "text": "Нічний ефір Випуск 1", "time_start": NOW - 3600, "time_stop": NOW - 1800,
                         "tv_show_id": 302, "available": True}],
            },
        ]}
        fake_client = API.Client(token=lambda: "Bearer T", send=lambda *a, **k: (200, b'{"status":"OK"}'))
        shows_res = API.shows(raw_for_shows, now=NOW, client=fake_client, tr=lambda s: s)
        by_sid = {x["id"]: sweettv_app.sections.show_card(x) for x in shows_res["items"]}
        self.assertEqual((by_sid["tv:301"].art, by_sid["tv:301"].art_mode, by_sid["tv:301"].banner),
                         ("https://img/stb-sq.png", "logo", "https://img/stb-wide.jpg"))
        self.assertEqual(sweettv_app.sections.hero_info(by_sid["tv:301"])["hero_is_logo"], "")
        self.assertEqual((by_sid["tv:302"].art, by_sid["tv:302"].art_mode, by_sid["tv:302"].wide_art),
                         ("https://img/only-sq.png", "logo", ""))
        self.assertEqual(sweettv_app.sections.hero_info(by_sid["tv:302"])["hero_is_logo"], "1")

    def test_separate_listitems_per_grid_and_label_sync_on_refresh(self):
        c1 = sweettv_app.sections.vod_card(_sample_movie(501, "New Title"), "movie")
        stale_li = ListItem("Stale Label")
        IT.apply_card(stale_li, c1)
        self.assertEqual(stale_li.label, "New Title", "apply_card must sync ListItem.setLabel(card.title)")

        # Adjacent boundary: minimal item stub without setLabel must not raise
        class MinimalItem:
            def __init__(self):
                self.props, self.art = {}, {}

            def setProperty(self, k, v):
                self.props[k] = v

            def setArt(self, d):
                self.art = dict(d)

        minimal = MinimalItem()
        IT.apply_card(minimal, c1)
        self.assertEqual(minimal.props.get("title"), "New Title")

        Fake.now = NOW
        raw = answer(
            chan(15, "СТБ HD", number=1, catchup=True, catchup_duration=7,
                 icon_v2_url="https://img/15-sq.png", banner_url="https://img/15-wide.jpg",
                 epg=[prog(NOW - 600, NOW + 600, "Ранок", 501), prog(NOW + 600, NOW + 2400, "День", 502)]),
            chan(16, "Новий Канал", number=2, catchup=True, catchup_duration=7,
                 icon_v2_url="https://img/16-sq.png", banner_url="https://img/16-wide.jpg",
                 epg=[prog(NOW - 600, NOW + 600, "Шоу", 601), prog(NOW + 600, NOW + 2400, "Кіно", 602)]),
        )
        write_list(raw)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window._open_section("channels")

        items_200 = window.controls[200].items
        items_201 = window.controls[201].items
        self.assertEqual(len(items_200), 2)
        self.assertEqual(len(items_201), 2)
        self.assertTrue(
            {id(x) for x in items_200}.isdisjoint({id(y) for y in items_201}),
            "controls[200] and controls[201] must never share ListItem object references",
        )
        self.assertEqual((items_200[0].art.get("icon"), items_200[0].getProperty("art_mode")),
                         ("https://img/15-sq.png", "logo"))
        self.assertEqual((items_201[0].art.get("icon"), items_201[0].getProperty("art_mode")),
                         ("https://img/15-wide.jpg", ""))

        # Mutate in-place order + advance clock via _refresh_channels: labels & per-grid wide/poster props stay isolated
        window.shown = list(reversed(window.shown))
        window._refresh_channels(NOW + 700)
        self.assertEqual([x.label for x in window.controls[200].items], ["Новий Канал", "СТБ HD"])
        self.assertEqual([x.label for x in window.controls[201].items], ["Новий Канал", "СТБ HD"])
        self.assertEqual((window.controls[200].items[0].art.get("icon"), window.controls[200].items[0].getProperty("art_mode")),
                         ("https://img/16-sq.png", "logo"))
        self.assertEqual((window.controls[201].items[0].art.get("icon"), window.controls[201].items[0].getProperty("art_mode")),
                         ("https://img/16-wide.jpg", ""))
        self.assertEqual(window.controls[201].items[0].getProperty("now"), "Кіно")

    def test_continue_cards_hydrates_sweetstore_skips_expired_deduplicates_generic_and_sets_now(self):
        import inspect

        raw = answer(
            chan(15, "СТБ HD", number=1, catchup=True, catchup_duration=3,
                 icon_v2_url="https://img/15-logo.png", banner_url="https://img/15-ban.jpg",
                 epg=[prog(NOW - 3600, NOW - 1800, "Холостяк", 301)]),
            chan(16, "1+1", number=2, catchup=False,
                 icon_v2_url="https://img/16-logo.png", banner_url="https://img/16-ban.jpg"),
            chan(17, "ICTV2", number=3, catchup=True, catchup_duration=3,
                 icon_v2_url="https://img/17-logo.png", banner_url="https://img/17-ban.jpg"),
        )
        catalog = D.parse_catalog(raw, NOW)
        resume_doc = {
            "v": 1,
            "items": {
                # 1. Saved with channel-only title 'СТБ HD' and start=0 -> hydrates 'Холостяк' from ch.epg
                "sw:15|301": {"cid": "15", "epg": "301", "title": "СТБ HD", "start": 0, "stop": 0,
                              "pos": 600, "total": 1800, "done": False, "at": NOW - 10},
                # 2. Expired DVR entry (> 3 days old on 3-day catchup channel) -> skipped
                "sw:15|299": {"cid": "15", "epg": "299", "title": "Старий ефір",
                              "start": NOW - 4 * 86400, "stop": NOW - 4 * 86400 + 1800,
                              "pos": 500, "total": 1800, "done": False, "at": NOW - 20},
                # 3. Inside 3-day catchup window with distinct title -> kept alongside 15|301
                "sw:15|298": {"cid": "15", "epg": "298", "title": "МастерШеф",
                              "start": NOW - 3 * 86400 + 60, "stop": NOW - 3 * 86400 + 1860,
                              "pos": 300, "total": 1800, "done": False, "at": NOW - 25},
                # 4. Non-catchup channel with start > 0 -> skipped
                "sw:16|401": {"cid": "16", "epg": "401", "title": "Новини",
                              "start": NOW - 1800, "stop": NOW - 900,
                              "pos": 300, "total": 900, "done": False, "at": NOW - 30},
                # 5 & 6. Two unnamed/channel-named entries on cid=15 -> deduplicated to 1 generic entry without 'СТБ HD · ...'
                "sw:15|991": {"cid": "15", "epg": "991", "title": "", "start": 0, "stop": 0,
                              "pos": 120, "total": 1800, "done": False, "at": NOW - 40},
                "sw:15|992": {"cid": "15", "epg": "992", "title": "СТБ HD", "start": 0, "stop": 0,
                              "pos": 240, "total": 1800, "done": False, "at": NOW - 50},
                # 7. Generic entry on a DIFFERENT channel cid=17 -> also kept (dedup is per-cid)
                "sw:17|701": {"cid": "17", "epg": "701", "title": "ICTV2", "start": 0, "stop": 0,
                              "pos": 180, "total": 1800, "done": False, "at": NOW - 55},
                # 8. Unknown channel not in catalog (ch is None) -> boundary: NOT dropped by catchup check
                "sw:99|888": {"cid": "99", "epg": "888", "title": "Archived Special",
                              "start": NOW - 10 * 86400, "stop": NOW - 10 * 86400 + 1800,
                              "pos": 300, "total": 1800, "done": False, "at": NOW - 60},
            },
            "live": {},
        }
        cards = sweettv_app.sections.continue_cards(resume_doc, catalog, NOW)
        by_key = {c.key: c for c in cards}

        self.assertNotIn("15|299", by_key, "Expired DVR catchup item must be skipped")
        self.assertNotIn("16|401", by_key, "Non-catchup channel DVR item with start > 0 must be skipped")
        self.assertIn("15|301", by_key)
        self.assertEqual(by_key["15|301"].title, "Холостяк")
        self.assertEqual(by_key["15|301"].meta, "СТБ HD  ·  Continue from 10:00")
        self.assertEqual(by_key["15|301"].now, "СТБ HD  ·  Continue from 10:00")
        self.assertEqual(by_key["15|301"].wide_art, "https://img/15-ban.jpg")
        self.assertEqual(by_key["15|301"].banner, "https://img/15-ban.jpg")

        self.assertIn("15|298", by_key)
        self.assertEqual(by_key["15|298"].title, "МастерШеф")
        self.assertEqual(by_key["15|298"].now, "СТБ HD  ·  Continue from 05:00")

        # Generic channel-named entries: at most 1 per cid, meta == resume_label (no 'СТБ HD · Continue...' repetition)
        self.assertIn("15|991", by_key)
        self.assertNotIn("15|992", by_key)
        self.assertEqual(by_key["15|991"].title, "СТБ HD")
        self.assertEqual(by_key["15|991"].meta, "Continue from 02:00")
        self.assertEqual(by_key["15|991"].now, "Continue from 02:00")
        self.assertNotIn("СТБ HD", by_key["15|991"].meta)
        self.assertIn("17|701", by_key)
        self.assertEqual(by_key["17|701"].meta, "Continue from 03:00")
        self.assertIn("99|888", by_key)

        # Injectable recall_prog & recall_title hydration (Pure Core)
        sig = inspect.signature(sweettv_app.sections.continue_cards).parameters
        self.assertIn("recall_prog", sig)
        self.assertIn("recall_title", sig)

        prog_db = {
            ("15", "555"): {"title": "Супермама", "start": NOW - 7200, "stop": NOW - 3600, "preview": "https://img/555-prev.jpg"},
            ("15", "556"): {"title": "Прострочений", "start": NOW - 9 * 86400, "stop": NOW - 9 * 86400 + 1800, "preview": ""},
        }
        title_db = {
            "vod:501": {"title": "Дюна", "poster": "https://img/dune-p.jpg", "banner": "https://img/dune-b.jpg", "seasons": []},
            "vod:9558": {
                "title": "Зрадники", "poster": "https://img/zr-p.jpg", "banner": "https://img/zr-b.jpg",
                "seasons": [{"number": 1, "episodes": [
                    {"id": 102, "episode_id": 102, "number": 2, "title": "Епізод 2", "preview": "https://img/zr-ep102.jpg"},
                    {"id": 103, "episode_id": 103, "number": 3, "title": "Епізод 3", "preview": ""},
                ]}],
            },
        }
        recall_doc = {
            "v": 1,
            "items": {
                "sw:15|555": {"cid": "15", "epg": "555", "title": "", "start": 0, "stop": 0,
                              "pos": 900, "total": 3600, "done": False, "at": NOW - 5},
                "sw:15|556": {"cid": "15", "epg": "556", "title": "СТБ HD", "start": 0, "stop": 0,
                              "pos": 300, "total": 1800, "done": False, "at": NOW - 6},
                "sw:vod:501": {"movie_id": "501", "episode_id": "", "title": "", "thumb": "",
                               "pos": 900, "total": 5400, "done": False, "at": NOW - 7},
                "sw:vod:9558|102": {"movie_id": "9558", "episode_id": "102", "title": "", "thumb": "",
                                    "pos": 420, "total": 2400, "done": False, "at": NOW - 8},
                "sw:vod:9558|103": {"movie_id": "9558", "episode_id": "103", "title": "Зрадники S1E3", "thumb": "",
                                    "pos": 300, "total": 2400, "done": False, "at": NOW - 9},
            },
            "live": {},
        }
        hydrated = {
            c.key: c for c in sweettv_app.sections.continue_cards(
                recall_doc, catalog, NOW,
                recall_prog=lambda cid, epg: prog_db.get((str(cid), str(epg))),
                recall_title=lambda tkey: title_db.get(str(tkey)),
            )
        }
        self.assertNotIn("15|556", hydrated, "Hydrated start outside catchup_duration must be skipped")
        self.assertEqual(hydrated["15|555"].title, "Супермама")
        self.assertEqual((hydrated["15|555"].start, hydrated["15|555"].stop), (NOW - 7200, NOW - 3600))
        self.assertEqual((hydrated["15|555"].wide_art, hydrated["15|555"].banner),
                         ("https://img/555-prev.jpg", "https://img/15-ban.jpg"))
        self.assertEqual(hydrated["15|555"].now, "СТБ HD  ·  Continue from 15:00")

        self.assertEqual(hydrated["501|"].title, "Дюна")
        self.assertEqual((hydrated["501|"].art, hydrated["501|"].wide_art, hydrated["501|"].banner),
                         ("https://img/dune-p.jpg", "https://img/dune-b.jpg", "https://img/dune-b.jpg"))
        self.assertEqual(hydrated["501|"].now, "Continue from 15:00")

        self.assertNotEqual(hydrated["9558|102"].title, "VOD 9558")
        self.assertTrue("Зрадники" in hydrated["9558|102"].title or "Епізод 2" in hydrated["9558|102"].title)
        self.assertEqual((hydrated["9558|102"].art, hydrated["9558|102"].wide_art, hydrated["9558|102"].banner),
                         ("https://img/zr-p.jpg", "https://img/zr-ep102.jpg", "https://img/zr-ep102.jpg"))
        self.assertEqual(hydrated["9558|102"].now, "Continue from 07:00")
        # Episode without preview falls back wide_art to title banner
        self.assertEqual((hydrated["9558|103"].wide_art, hydrated["9558|103"].banner),
                         ("https://img/zr-b.jpg", "https://img/zr-b.jpg"))

        # Thin SweetStore recall wrappers in sweettv_files + SweetTV Continue wiring
        self.assertTrue(hasattr(files, "recall_programme"), "sweettv_files must define recall_programme(cid, epg, now=None)")
        self.assertTrue(hasattr(files, "recall_title_detail"), "sweettv_files must define recall_title_detail(title_key)")

        Fake.now = NOW
        write_list(raw)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))

        st = sweetstore.default_store()
        st.upsert_epg("15", [{
            "id": 888, "text": "Вечірнє шоу", "time_start": NOW - 5400, "time_stop": NOW - 1800,
            "preview_url": "https://img/888-prev.jpg", "available": True,
        }], now=NOW, catchup=True, catchup_duration=3)
        st.upsert_title_detail({
            "ok": True, "id": "vod:501", "kind": "movie", "title": "Дюна",
            "poster": "https://img/dune-p.jpg", "banner": "https://img/dune-b.jpg", "seasons": [],
        }, now=NOW)

        rec_p = files.recall_programme("15", "888", now=NOW)
        self.assertIsNotNone(rec_p)
        self.assertEqual((rec_p["title"], rec_p["preview"]), ("Вечірнє шоу", "https://img/888-prev.jpg"))
        self.assertIsNone(files.recall_programme("16", "888", now=NOW))
        rec_t = files.recall_title_detail("vod:501")
        self.assertIsNotNone(rec_t)
        self.assertEqual((rec_t["title"], rec_t["banner"]), ("Дюна", "https://img/dune-b.jpg"))
        self.assertIsNone(files.recall_title_detail("vod:404"))

        with mock.patch.object(sweetstore, "default_store", side_effect=OSError("db unavailable")):
            self.assertIsNone(files.recall_programme("15", "888", now=NOW))
            self.assertIsNone(files.recall_title_detail("vod:501"))

        live_resume = MR.empty()
        live_resume = MR.record(live_resume, "plugin://plugin.video.sweettv/playvid/15|888", 600, 3600, NOW - 5,
                                {"title": "СТБ HD", "start": 0, "stop": 0})
        live_resume = MR.record(live_resume, "plugin://plugin.video.sweettv/playvod/501|null|0", 900, 5400, NOW - 10,
                                {"title": "", "thumb": ""})
        MR.save(live_resume)

        window._open_section("continue")
        w_items = window.controls[201].items
        self.assertEqual([li.label for li in w_items], ["Вечірнє шоу", "Дюна"])
        self.assertEqual((w_items[0].art.get("icon"), w_items[0].getProperty("art_mode"), w_items[0].getProperty("now")),
                         ("https://img/888-prev.jpg", "", "СТБ HD  ·  Continue from 10:00"))
        self.assertEqual((w_items[1].art.get("icon"), w_items[1].getProperty("art_mode"), w_items[1].getProperty("now")),
                         ("https://img/dune-b.jpg", "", "Continue from 15:00"))

    def test_set_chips_updates_list_409_in_place_without_reset_when_keys_unchanged(self):
        window = self.make()
        window.genre_id = 4
        window._set_chips("movies", [("all", "All items"), ("sort", "Popular"), ("g:4", "Комедии")])
        ctrl = window.controls[409]
        self.assertEqual([i.label for i in ctrl.items], ["All items", "Popular", "Комедии"])
        self.assertEqual([i.getProperty("key") for i in ctrl.items], ["all", "sort", "g:4"])
        self.assertEqual([i.getProperty("active") for i in ctrl.items], ["", "", "1"])

        ctrl.selectItem(1)
        orig_items = list(ctrl.items)
        with mock.patch.object(ctrl, "reset", wraps=ctrl.reset) as m_reset:
            window.genre_id = 0
            window._set_chips("movies", [("all", "All items"), ("sort", "Newest"), ("g:4", "Комедии")])
        m_reset.assert_not_called()
        self.assertIs(ctrl.items[1], orig_items[1])
        self.assertEqual(ctrl.items[1].label, "Newest")
        self.assertEqual([i.getProperty("active") for i in ctrl.items], ["1", "", ""])
        self.assertEqual(ctrl.getSelectedPosition(), 1)

        window._set_chips("continue", [])
        self.assertEqual(window.getProperty("filters"), "")
        self.assertEqual(ctrl.items, [])



class Issue79HeroFavouritesEpisodesAndEpgArtTests(WindowCase):
    """Issue #79: full-bleed Hero + widened metadata, Favourites wide row + banner persistence,
    horizontal 421 episode cards with 1-soon badge/toast, and live EPG artwork/title hydration."""

    def test_skin_full_bleed_hero_labels_hub_meta_and_horizontal_421_panel(self):
        root = ET.parse(os.path.join(SKIN, "script-media-stick-sweettv.xml")).getroot()

        # Issue #84: 3 deterministic fade PNGs must exist in resources/skins/default/media/
        for fname in ("sweettv-fade-left.png", "sweettv-fade-bottom.png", "sweettv-fade-top.png"):
            self.assertTrue(os.path.isfile(os.path.join(MEDIA, fname)), f"Missing fade asset {fname}")

        # Browse Hero: 419 at (96, 512, 1320, 56, itemgap=12); labels narrowed to width=780; fade textures
        row_419 = next(c for c in root.iter("control") if c.get("id") == "419")
        self.assertEqual(
            (int(row_419.findtext("left")), int(row_419.findtext("top")),
             int(row_419.findtext("width")), int(row_419.findtext("height")), int(row_419.findtext("itemgap"))),
            (96, 512, 1320, 56, 12),
        )
        main_group = next(
            g for g in root.find("controls").findall("control[@type='group']")
            if "String.IsEmpty(Window.Property(modal))" in (g.findtext("visible") or "")
        )
        main_xml = ET.tostring(main_group, encoding="unicode")
        for tex in ("sweettv-fade-left.png", "sweettv-fade-bottom.png", "sweettv-fade-top.png"):
            self.assertIn(tex, main_xml)
        self.assertIn("330C111B", main_xml)
        for prop_expr in (
            "$INFO[Window.Property(hero_title)]",
            "$INFO[Window.Property(hero_meta)]",
            "$INFO[Window.Property(hero_desc)]",
            "$INFO[Window.Property(hero_sub)]",
        ):
            lbl = next((c for c in main_group.findall(".//control[@type='label']") if c.findtext("label") == prop_expr), None)
            self.assertIsNotNone(lbl, f"Missing browse label {prop_expr}")
            self.assertEqual(int(lbl.findtext("left")), 96, prop_expr)
            self.assertEqual(int(lbl.findtext("width")), 780, prop_expr)

        # Unified Full-Screen Hero Hub: fade textures, wash, meta (96, 132, 900), and bottom-anchored 421 at top=680
        modal_group = next(
            g for g in root.find("controls").findall("control[@type='group']")
            if "!String.IsEmpty(Window.Property(modal))" in (g.findtext("visible") or "")
        )
        modal_xml = ET.tostring(modal_group, encoding="unicode")
        for tex in ("sweettv-fade-left.png", "sweettv-fade-bottom.png"):
            self.assertIn(tex, modal_xml)
        self.assertIn("380C111B", modal_xml)
        hub_meta = next(
            (c for c in modal_group.findall(".//control[@type='label']")
             if c.findtext("label") == "$INFO[Window.Property(hero_meta)]"),
            None,
        )
        self.assertIsNotNone(hub_meta, "Missing hero_meta label in Full-Screen Hub")
        self.assertEqual(
            (int(hub_meta.findtext("left")), int(hub_meta.findtext("top")), int(hub_meta.findtext("width"))),
            (96, 132, 900),
        )

        # 400 gated to modal=guide at (96, 504, 1728, 512); 421 horizontal 444x310 panel gated to modal=show at (96, 680, 1776, 344)
        list_400 = next(c for c in root.iter("control") if c.get("id") == "400")
        self.assertEqual(
            (int(list_400.findtext("left")), int(list_400.findtext("top")),
             int(list_400.findtext("width")), int(list_400.findtext("height"))),
            (96, 504, 1728, 512),
        )
        vis_400 = list_400.findtext("visible") or ""
        self.assertTrue(_eval_kodi_cond(vis_400, {"mode": "data", "modal": "guide", "guide": "1"}, focus_id=400))
        self.assertFalse(_eval_kodi_cond(vis_400, {"mode": "data", "modal": "show", "guide": "1"}, focus_id=421))

        panel_421 = next((c for c in root.iter("control") if c.get("id") == "421"), None)
        self.assertIsNotNone(panel_421, "Missing horizontal episode panel id=421")
        self.assertEqual(panel_421.get("type"), "panel")
        self.assertEqual((panel_421.findtext("orientation") or "").strip(), "horizontal")
        self.assertEqual((panel_421.findtext("onup") or "").strip(), "410")
        self.assertEqual(
            (int(panel_421.findtext("left")), int(panel_421.findtext("top")),
             int(panel_421.findtext("width")), int(panel_421.findtext("height"))),
            (96, 680, 1776, 344),
        )
        vis_421 = panel_421.findtext("visible") or ""
        self.assertTrue(_eval_kodi_cond(vis_421, {"mode": "data", "modal": "show", "guide": "1"}, focus_id=421))
        self.assertFalse(_eval_kodi_cond(vis_421, {"mode": "data", "modal": "guide", "guide": "1"}, focus_id=400))

        for layout_name in ("itemlayout", "focusedlayout"):
            layout = panel_421.find(layout_name)
            self.assertIsNotNone(layout, layout_name)
            self.assertEqual((int(layout.get("width")), int(layout.get("height"))), (444, 310), layout_name)
            xml_str = ET.tostring(layout, encoding="unicode")
            self.assertIn("sweettv-wide-mask.png", xml_str, layout_name)
            self.assertIn("ListItem.Property(bar)", xml_str, layout_name)
            self.assertIn("ListItem.Property(badge)", xml_str, layout_name)
            self.assertIn("ListItem.Property(coming_soon)", xml_str, layout_name)
            self.assertIn("ListItem.Property(now)", xml_str, layout_name)
            self.assertIn("ListItem.Property(when)", xml_str, layout_name)

        tabs_410 = next(c for c in root.iter("control") if c.get("id") == "410")
        self.assertEqual(
            (int(tabs_410.findtext("left")), int(tabs_410.findtext("top")),
             int(tabs_410.findtext("width")), int(tabs_410.findtext("height"))),
            (96, 432, 1728, 56),
        )
        ondowns = [(od.get("condition") or "", (od.text or "").strip()) for od in tabs_410.findall("ondown")]
        self.assertTrue(
            any("show" in cond and target == "421" for cond, target in ondowns),
            f"410 must have <ondown> to 421 for modal=show, got {ondowns}",
        )
        self.assertTrue(
            any("guide" in cond and target == "400" for cond, target in ondowns),
            f"410 must have <ondown> to 400 for modal=guide, got {ondowns}",
        )

        # 209 base (96, 352, 1120, 56) with modal=show and modal=detail conditional slides
        grp_209 = next(c for c in root.iter("control") if c.get("id") == "209")
        self.assertEqual(
            (int(grp_209.findtext("left")), int(grp_209.findtext("top")),
             int(grp_209.findtext("width")), int(grp_209.findtext("height"))),
            (96, 352, 1120, 56),
        )
        grp_209_xml = ET.tostring(grp_209, encoding="unicode")
        self.assertIn("0,140", grp_209_xml)
        self.assertIn("0,-132", grp_209_xml)

    def test_favourites_wide_section_and_banner_wide_art_persistence(self):
        self.assertIn("favourites", sweettv_app.WIDE_SECTIONS)
        self.assertEqual(sweettv_app.WIDE_SECTIONS, frozenset(("continue", "favourites", "channels")))

        # Pure Core: favourites_cards accepts recall_title and hydrates show:* & vod:* banner/wide_art/meta/desc
        raw = answer(chan(15, "СТБ HD", number=1, icon_v2_url="https://img/15-sq.png", banner_url="https://img/15-ban.jpg"))
        catalog = D.parse_catalog(raw, NOW)
        favs_doc = {
            "v": 1,
            "items": {
                "show:vod:10": {"title": "Saved Show", "thumb": "https://img/10-sq.jpg", "at": NOW - 10},
                "vod:501": {"title": "Saved Movie", "thumb": "https://img/501-sq.jpg",
                            "banner": "https://img/501-saved-ban.jpg", "wide_art": "https://img/501-saved-wide.jpg", "at": NOW - 20},
                "ch:999": {"title": "Offline Ch", "thumb": "https://img/999-sq.png",
                           "banner": "https://img/999-ban.jpg", "wide_art": "https://img/999-wide.jpg", "at": NOW - 30},
            },
        }
        recalled = {
            "show:vod:10": {"title": "Holostyak", "poster": "https://img/10-sq.jpg", "banner": "https://img/10-ban.jpg",
                            "wide_art": "https://img/10-wide.jpg", "year": 2025, "description": "Romantic reality"},
        }
        cards = sweettv_app.sections.favourites_cards(
            favs_doc, catalog, {}, NOW, resume_doc=None, recall_title=lambda k: recalled.get(k)
        )
        by_fav = {c.fav_key: c for c in cards}
        self.assertEqual(by_fav["show:vod:10"].banner, "https://img/10-ban.jpg")
        self.assertEqual(by_fav["show:vod:10"].wide_art, "https://img/10-wide.jpg")
        self.assertIn("Romantic reality", by_fav["show:vod:10"].desc)
        self.assertIn("2025", by_fav["show:vod:10"].meta)
        self.assertEqual(by_fav["vod:501"].banner, "https://img/501-saved-ban.jpg")
        self.assertEqual(by_fav["vod:501"].wide_art, "https://img/501-saved-wide.jpg")
        self.assertEqual(by_fav["ch:999"].banner, "https://img/999-ban.jpg")
        self.assertEqual(by_fav["ch:999"].wide_art, "https://img/999-wide.jpg")

        # Fallback to thumb when banner/wide_art absent
        fallback_cards = sweettv_app.sections.favourites_cards(
            {"v": 1, "items": {"vod:777": {"title": "Thumb Only", "thumb": "https://img/777.jpg", "at": NOW}}},
            catalog, {}, NOW,
        )
        self.assertEqual(fallback_cards[0].banner, "https://img/777.jpg")
        self.assertEqual(fallback_cards[0].wide_art, "https://img/777.jpg")

        # App: _toggle_favourite persists banner and wide_art to mr.toggle_fav, and _show_favourites uses 201 + recall_title
        Fake.now = NOW
        write_list(raw)
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        fav_calls = []
        with mock.patch.object(MR, "toggle_fav", side_effect=lambda k, m=None, **kw: (fav_calls.append((k, dict(m or {}))) or (True, True))):
            card = sweettv_app.sections.vod_card({
                "id": 501, "title": "Dune", "poster": "https://img/501.jpg",
                "banner": "https://img/501-bg.jpg", "wide_art": "https://img/501-wide.jpg", "vod_url": "u",
            }, "movie")
            window.cards = [card]
            window.focus = 200
            window.controls[200].selected = 0
            window._toggle_favourite()
        self.assertEqual(len(fav_calls), 1)
        self.assertEqual(fav_calls[0][1].get("banner"), "https://img/501-bg.jpg")
        self.assertEqual(fav_calls[0][1].get("wide_art"), "https://img/501-wide.jpg")

        with mock.patch.object(MR, "load_favs", return_value=favs_doc), \
             mock.patch.object(files, "recall_title_detail", side_effect=lambda k: recalled.get(k)) as recall_spy:
            window._open_section("favourites")
            self.assertEqual(window.getProperty("wide_grid"), "1")
            self.assertGreaterEqual(len(window.controls[201].items), 1)
            self.assertTrue(recall_spy.called)

    def test_episode_items_coming_soon_badge_toast_and_autoplay_skip(self):
        from resources.lib import sweettv_guide
        self.assertEqual(sweettv_guide.SHOW_EPISODES, 421)

        W.set_language("ru")
        self.assertEqual(W.tr("This episode has not been released yet."), "Эта серия ещё не вышла.")
        W.set_language("uk")
        self.assertEqual(W.tr("This episode has not been released yet."), "Ця серія ще не вийшла.")
        W.set_language("en")

        eps = [
            {"id": 1, "number": 1, "title": "First", "duration": 2000, "resume": 500, "preview": "https://img/e1.jpg"},
            {"id": 2, "number": 2, "title": "Second", "duration": 2000, "watched": True},
            {"id": 3, "number": 3, "title": "Next Week", "duration": 0, "coming_soon": True, "playable": False,
             "release_date": "2026-12-01", "vod_url": ""},
            {"id": 4, "number": 4, "title": "Soon No Date", "duration": 0, "coming_soon": True, "playable": False},
        ]
        lis = IT.episode_items(eps, fallback_art="https://img/fallback.jpg")
        self.assertEqual(lis[0].art.get("icon"), "https://img/e1.jpg")
        self.assertTrue(lis[0].getProperty("bar").startswith("sweettv-bar-"))
        self.assertEqual(lis[0].getProperty("coming_soon"), "")
        self.assertEqual(lis[1].art.get("icon"), "https://img/fallback.jpg")
        self.assertEqual(lis[1].getProperty("badge"), W.tr("Watched"))
        self.assertEqual(lis[1].getProperty("coming_soon"), "")
        self.assertEqual(lis[2].getProperty("coming_soon"), "1")
        self.assertEqual(lis[2].getProperty("bar"), "")
        self.assertIn("2026-12-01", lis[2].getProperty("badge"))
        self.assertIn(W.tr("Soon"), lis[2].getProperty("badge"))
        self.assertEqual(lis[3].getProperty("coming_soon"), "1")
        self.assertEqual(lis[3].getProperty("badge"), W.tr("Soon"))

        # Clicking a coming_soon episode shows toast and does NOT start playback; _next_episode_after skips coming_soon
        Fake.now = NOW
        write_list(answer(chan(15, "СТБ HD", number=1)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        detail = {
            "ok": True, "id": "vod:600", "movie_id": "600", "title": "Series", "banner": "https://img/s-ban.jpg",
            "seasons": [{"id": 1, "number": 1, "title": "Season 1", "episodes": [
                {"id": 101, "episode_id": 101, "number": 1, "title": "Ep 1", "duration": 1400,
                 "owner_id": 10, "vod_url": "plugin://plugin.video.sweettv/playvod/600|101|10", "resume": 0, "watched": False},
                {"id": 102, "episode_id": 102, "number": 2, "title": "Ep 2 Soon", "duration": 0,
                 "coming_soon": True, "playable": False, "release_date": "2026-12-01", "vod_url": ""},
            ]}],
        }
        card = sweettv_app.sections.vod_card({"id": 600, "title": "Series", "vod_url": "u", "banner": "https://img/s-ban.jpg"}, "series")
        with mock.patch.object(API, "vod_detail", return_value=detail):
            window._open_show_modal(card)
            self.assertTrue(wait_for(lambda: len(window.controls[421].items) == 2))
            self.assertEqual(window.focus, 421)

            Fake.rpc.clear()
            Fake.notes.clear()
            window.controls[421].selected = 1
            window.onClick(421)
            self.assertEqual(Fake.rpc, [], "Clicking coming_soon episode must not start playback")
            self.assertIn(W.tr("This episode has not been released yet."), Fake.notes)

            sess = sweettv_app.play.Session(
                "", "", "Ep 1", 0, 0,
                url="plugin://plugin.video.sweettv/playvod/600|101|10",
                season=1, episode=1, episode_mode=True,
            )
            self.assertIsNone(window._next_episode_after(sess))

            window._guide_close()
            self.assertEqual(window.controls[421].items, [])

    def test_detail_modal_promotes_to_show_when_vod_detail_has_seasons(self):
        # Opening a kind="movie" card (e.g. from Search) whose vod_detail() returns seasons
        # must promote the open modal from "detail" to "show", populate 410 & 421, and focus 421.
        Fake.now = NOW
        write_list(answer(chan(15, "СТБ HD", number=1)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        detail = {
            "ok": True,
            "id": "vod:33871",
            "movie_id": "33871",
            "title": "Зрадники",
            "description": "Реалити-шоу с интригами.",
            "banner": "https://img/33871-ban.jpg",
            "seasons": [
                {
                    "id": 2,
                    "number": 2,
                    "title": "Сезон 2",
                    "episodes": [
                        {
                            "id": 201, "episode_id": 201, "number": 1, "title": "Выпуск 1",
                            "duration": 3720, "owner_id": 69,
                            "vod_url": "plugin://plugin.video.sweettv/playvod/33871|201|69",
                            "resume": 0, "watched": False,
                        },
                        {
                            "id": 202, "episode_id": 202, "number": 2, "title": "Выпуск 2",
                            "duration": 4000, "owner_id": 69,
                            "vod_url": "plugin://plugin.video.sweettv/playvod/33871|202|69",
                            "resume": 0, "watched": False,
                        },
                    ],
                },
            ],
        }
        movie_card = sweettv_app.sections.vod_card(
            {"id": 33871, "title": "Зрадники", "vod_url": "plugin://plugin.video.sweettv/playvod/33871|null|0"},
            "movie",
        )
        with mock.patch.object(API, "vod_detail", return_value=detail):
            window._open_detail_modal(movie_card)
            self.assertTrue(wait_for(lambda: window.getProperty("modal") == "show"))
        self.assertEqual(window.getProperty("guide"), "1")
        self.assertEqual(len(window.controls[410].items), 1)
        self.assertEqual(len(window.controls[421].items), 2)
        self.assertEqual(window.focus, 421)

    def test_epg_programme_image_parsing_cards_and_nonblocking_worker_hydration(self):
        # Part 4.1: Programme.image default & parse_programme extraction
        self.assertEqual(D.Programme(1000, 2000, "x", "", True, "").image, "")
        p_img = D.parse_programme({"id": 50, "text": "News", "time_start": NOW - 600, "time_stop": NOW + 1200,
                                   "image_url": "https://img/epg50.jpg"}, NOW)
        self.assertEqual(p_img.image, "https://img/epg50.jpg")
        p_ext = D.parse_programme({"id": 51, "text": "Show", "time_start": NOW - 600, "time_stop": NOW + 1200,
                                   "preview_url_ext": "https://img/ext51.jpg"}, NOW)
        self.assertEqual(p_ext.image, "https://img/ext51.jpg")
        p_bad = D.parse_programme({"id": 52, "text": "Bad", "time_start": NOW - 600, "time_stop": NOW + 1200,
                                   "image_url": "ftp://bad/x.jpg"}, NOW)
        self.assertEqual(p_bad.image, "")

        # Part 4.2: channel_card prefers current.image for wide_art and banner; vod_card accepts wide_art
        ch_with_epg_img = D.parse_channel({
            "id": 15, "name": "СТБ HD", "number": 1, "available": True,
            "icon_v2_url": "https://img/15-sq.png", "banner_url": "https://img/15-ban.jpg",
            "epg": [{"id": 501, "text": "МастерШеф", "time_start": NOW - 600, "time_stop": NOW + 1200,
                     "image_url": "https://img/epg501.jpg"}],
        }, NOW)
        c_epg = sweettv_app.sections.channel_card(ch_with_epg_img, {}, NOW)
        self.assertEqual(c_epg.wide_art, "https://img/epg501.jpg")
        self.assertEqual(c_epg.banner, "https://img/epg501.jpg")

        v_card = sweettv_app.sections.vod_card({
            "id": 800, "title": "Movie", "poster": "https://img/800-sq.jpg",
            "banner": "https://img/800-ban.jpg", "wide_art": "https://img/800-wide.jpg",
        })
        self.assertEqual(v_card.wide_art, "https://img/800-wide.jpg")

        # Part 4.3: files.enrich_epg_art delegates to sweetapi.enrich_epg_records
        with mock.patch.object(API, "enrich_epg_records", return_value={"501": {"image_url": "https://img/501.jpg"}}) as api_spy:
            res = files.enrich_epg_art(["501"], now=NOW)
        self.assertEqual(res, {"501": {"image_url": "https://img/501.jpg"}})
        self.assertTrue(api_spy.called)

        # Part 4.3: Non-blocking worker in SweetTV enriches channels missing current.image, deduplicates, and skips in demo
        Fake.now = NOW
        raw_no_img = answer(
            chan(15, "СТБ HD", number=1, icon_v2_url="https://img/15-sq.png", banner_url="https://img/15-ban.jpg",
                 epg=[prog(NOW - 600, NOW + 1200, "МастерШеф", 501)]),
        )
        write_list(raw_no_img)
        enriched_calls = []

        def fake_enrich(epg_ids, now=None):
            enriched_calls.append(list(epg_ids))
            sweetstore.default_store().upsert_channels(answer(
                chan(15, "СТБ HD", number=1, icon_v2_url="https://img/15-sq.png", banner_url="https://img/15-ban.jpg",
                     epg=[prog(NOW - 600, NOW + 1200, "МастерШеф Live", 501, image_url="https://img/epg501-live.jpg")]),
            ), now=NOW)
            return {"501": {"id": "501", "image_url": "https://img/epg501-live.jpg", "title": "МастерШеф Live"}}

        with mock.patch.object(files, "enrich_epg_art", side_effect=fake_enrich):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window._open_section("channels")
            self.assertTrue(wait_for(lambda: len(enriched_calls) >= 1 and window.controls[201].items[0].art.get("icon") == "https://img/epg501-live.jpg"))
            prev_count = len(enriched_calls)
            window._refresh_channels(NOW + 5)
            time.sleep(0.05)
            self.assertEqual(len(enriched_calls), prev_count)

        # Demo mode must NOT call enrich_epg_art
        demo_calls = []
        with mock.patch.object(files, "enrich_epg_art", side_effect=lambda *a, **kw: demo_calls.append(1) or {}):
            demo_win = self.open(demo=True)
            self.assertTrue(wait_for(lambda: demo_win.mode == D.DATA))
            demo_win._open_section("channels")
            time.sleep(0.05)
            self.assertEqual(demo_calls, [])




class Issue103FilterListTaxonomyDebounceAndMenuKeyTests(WindowCase):
    """Issue #103: horizontal list 409, 9-tab curated TV taxonomy, auto-apply debounce,
    OK-only action chips, DigitJump 201, Quick Resume v2, and 117 Menu key."""

    def test_chip_items_builder_and_catalog_chips_16_genre_cap(self):
        self.assertTrue(hasattr(IT, "chip_items"), "sweettv_items.chip_items is missing")
        chips = [(f"k{i}", f"Label {i}") for i in range(10)]
        items = IT.chip_items(chips, "k8")
        self.assertEqual(len(items), 10)
        self.assertEqual(items[8].label, "Label 8")
        self.assertEqual(items[8].getProperty("key"), "k8")
        self.assertEqual(items[8].getProperty("active"), "1")
        self.assertEqual(items[0].getProperty("active"), "")
        self.assertEqual(IT.chip_items([], "k0"), [])
        self.assertEqual([i.getProperty("active") for i in IT.chip_items(chips[:3], "missing")], ["", "", ""])

        genres = [{"id": 100 + i, "name": f"Genre {i}"} for i in range(20)]
        cat_chips = sweettv_app.sections.catalog_chips(genres, [{"id": 1, "name": "Popular"}], 0)
        self.assertGreaterEqual(len(cat_chips), 16)
        self.assertLessEqual(len(cat_chips), 18)

    def test_channel_card_skips_hero_skip_meta_cats_with_fallback(self):
        import mediastick_sweetchannels as sc

        cat_names = {"c:12": "Top", "c:23": "National", "c:1000": "All", "c:4": "Cinema"}
        ch_mixed = D.parse_channel(chan(1, "Film TV", number=1, category=[12, 23, 1000, 4]), NOW)
        card_mixed = sweettv_app.sections.channel_card(ch_mixed, cat_names, NOW)
        self.assertIn("Cinema", card_mixed.meta)
        for skip_id in ("12", "23", "1000"):
            self.assertNotIn(cat_names[f"c:{skip_id}"], card_mixed.meta)

        ch_only_meta = D.parse_channel(chan(2, "Meta Only", number=2, category=[23, 27]), NOW)
        card_fallback = sweettv_app.sections.channel_card(ch_only_meta, {"c:23": "National", "c:27": "HD"}, NOW)
        self.assertIn("National", card_fallback.meta)
        self.assertTrue(sc.HERO_SKIP_META_CATS >= frozenset({"12", "23", "27", "40", "1000"}))

    def test_shared_9_tab_taxonomy_and_demo_categories(self):
        import mediastick_sweetchannels as sc

        demo_raw_data = sweettv_demo.demo_data(NOW, "")
        cat_ids = {c["id"] for c in demo_raw_data["categories"] if c["id"] != sweettv_demo.HIDDEN}
        self.assertEqual(cat_ids, {8, 4, 16, 2, 6, 9})
        all_ch_cats = {cid for ch in demo_raw_data["list"] for cid in ch.get("category", ())}
        self.assertTrue(all_ch_cats & {20, 23, 29}, "Demo channels must tag 20/23/29 for Main tab")
        self.assertTrue(any(ch.get("is_fast_channel") for ch in demo_raw_data["list"]))


        write_list(demo_raw_data); window = self.open(); self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[409].items) >= 9))
        keys = [i.getProperty("key") for i in window.controls[409].items]
        self.assertEqual(
            keys[:9],
            ["main", "g:cinema", "g:knowledge", "g:kids", "g:sport", "g:news", "g:music", "fast", "all"],
        )
        self.assertEqual(window.filter_key, "main")

        parsed = D.parse_catalog(demo_raw_data, NOW)
        filtered_main = sweettv_app.sections.filter_channels(parsed.channels, "main", cat_names=parsed.categories)
        filtered_live = sweettv_app.sections.filter_channels(parsed.channels, "live", cat_names=parsed.categories)
        self.assertEqual([c.cid for c in filtered_main], [c.cid for c in filtered_live])
        self.assertEqual(
            [c.cid for c in filtered_main],
            [c.cid for c in sc.filter_channels_for_tab(parsed.channels, "main", cat_names=parsed.categories)],
        )

    def test_shelf_constants_and_auto_apply_debounce_and_ok_only_actions(self):
        from resources.lib import sweettv_shelf

        self.assertEqual(getattr(sweettv_shelf, "CHIPS", None), 409)
        self.assertEqual(sweettv_shelf.CHIP_LOCAL_DELAY, 0.12)
        self.assertEqual(sweettv_shelf.CHIP_REMOTE_DELAY, 0.28)
        self.assertEqual(sweettv_shelf.ACTION_CHIPS, frozenset(("new", "sort")))

        movies_all = {"ok": True, "section": "movies", "items": [_sample_movie(501, "All Film")], "total": 1}
        movies_drama = {"ok": True, "section": "movies", "items": [_sample_movie(502, "Drama Film")], "total": 1}
        write_list(answer(chan(10, "Ten", number=10, category=[20]),
                          chan(20, "Fast 24/7", number=20, category=[4], is_fast_channel=True),
                          categories=[{"id": 20, "caption": "Main"}, {"id": 4, "caption": "Cinema"}]))
        with mock.patch.object(API, "configuration", return_value=_sample_config()),                 mock.patch.object(API, "catalog_page", side_effect=lambda sec, genre_id=0, **kw: movies_drama if genre_id else movies_all),                 mock.patch.object(API, "top_search", return_value={"ok": True, "items": [], "count": 0}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertEqual(window.filter_key, "main")

            # 1. Local debounce (0.12s) on channels + page_query clear
            window.controls[MENU].selected = 6
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[409].items) >= 2))
            window.page_query = "old_q"
            window.focus = 409
            fast_idx = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "fast")
            scheduled = []
            orig_later = window._later

            def spy_later(name, delay, fn):
                if name == "chip":
                    scheduled.append(delay)
                return orig_later(name, delay, fn)

            with mock.patch.object(window, "_later", side_effect=spy_later):
                window.controls[409].selectItem(fast_idx)
                self.press(window, 2)                               # ACTION_MOVE_RIGHT
            self.assertEqual(scheduled, [0.12])
            self.assertTrue(wait_for(lambda: window.filter_key == "fast"))
            self.assertEqual(window.page_query, "")
            self.assertEqual([i.label for i in window.controls[201].items], ["Fast 24/7"])

            # Moving onto already active chip cancels/does not schedule
            scheduled.clear()
            with mock.patch.object(window, "_later", side_effect=spy_later):
                self.press(window, 2)
            self.assertEqual(scheduled, [])

            # 2. Remote debounce (0.28s) on movies, idempotent g:<gid>, and "sort" is OK-only
            window.controls[MENU].selected = 5
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[409].items) >= 3))
            sort_idx = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "sort")
            g_idx = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key").startswith("g:"))
            g_id = int(window.controls[409].items[g_idx].getProperty("key")[2:])

            window.focus = 409
            prev_sort = window.sort_idx
            window.controls[409].selectItem(sort_idx)
            self.press(window, 2)
            time.sleep(0.05)
            self.assertEqual(window.sort_idx, prev_sort, "sort chip must NOT run on focus move")

            scheduled.clear()
            with mock.patch.object(window, "_later", side_effect=spy_later):
                window.controls[409].selectItem(g_idx)
                self.press(window, 2)
            self.assertEqual(scheduled, [0.28])
            self.assertTrue(wait_for(lambda: window.genre_id == g_id))
            # Idempotent: clicking active g:<gid> does NOT toggle back to 0
            window.onClick(409)
            self.assertEqual(window.genre_id, g_id)

            # OK on sort chip cycles sort_idx
            window.controls[409].selectItem(sort_idx)
            window.onClick(409)
            self.assertNotEqual(window.sort_idx, prev_sort)

            # 3. "new" chip on search is OK-only
            window.controls[MENU].selected = 0
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[409].items) >= 2))
            window.focus = 409
            window.controls[409].selectItem(0)
            with mock.patch.object(window, "_ask_search") as m_ask:
                self.press(window, 1)
                time.sleep(0.05)
                m_ask.assert_not_called()
                window.onClick(409)
                m_ask.assert_called_once()

    def test_down_from_409_flushes_pending_chip_and_keeps_focus_if_empty(self):
        write_list(answer(chan(10, "Ten", number=10, category=[20]),
                          chan(20, "News", number=20, category=[8]),
                          categories=[{"id": 20, "caption": "Main"}, {"id": 8, "caption": "News"}]))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window.controls[MENU].selected = 6
        window.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(window.controls[409].items) >= 2))

        news_idx = next(i for i, item in enumerate(window.controls[409].items) if item.getProperty("key") == "g:news")
        window.focus = 409
        window.controls[409].selectItem(news_idx)
        self.press(window, 2)                                       # schedules 0.12s timer
        # Simulate Kodi moving focus down to 201 on super().onAction -> flush runs before leave
        with mock.patch.object(WindowXML, "onAction", lambda self_, act: setattr(self_, "focus", 201)):
            self.press(window, KEY_DOWN)
        self.assertEqual(window.filter_key, "g:news")
        self.assertEqual([i.label for i in window.controls[201].items], ["News"])

        # If resulting grid is empty, focus stays on 409
        window.focus = 409
        window.controls[409].selectItem(0)
        with mock.patch.object(sweettv_app.sections, "filter_channels", return_value=[]),                 mock.patch.object(WindowXML, "onAction", lambda self_, act: setattr(self_, "focus", 201)):
            self.press(window, KEY_DOWN)
        self.assertEqual(window.focus, 409)

    def test_quick_resume_v2_and_menu_key_117_toggles_menu_and_closes_modal(self):
        from resources.lib import quick_resume as qr

        write_list(answer(chan(10, "Ten", number=10, category=[20]),
                          categories=[{"id": 20, "caption": "Main"}]))
        # Pre-v2 snapshot with filter="all" on channels maps to "main"
        snap_v1 = {"schema_v": 1, "section": "channels", "filter": "all", "sort": "",
                   "search_query": "", "nav_stack": [], "focused_control": 201, "focused_index": 0,
                   "focused_key": "", "scroll_offset": 0, "cards": [{"key": "10", "kind": "channel", "title": "Ten"}], "media_ref": None}
        with mock.patch.object(qr, "load_snapshot", return_value=snap_v1):
            w1 = self.open()
            self.assertTrue(wait_for(lambda: w1.mode == D.DATA))
            self.assertEqual(w1.filter_key, "main")

        # v2 snapshot with invalid filter falls back to "main"
        snap_bad = dict(snap_v1, schema_v=2, filter="c:999999")
        with mock.patch.object(qr, "load_snapshot", return_value=snap_bad):
            w2 = self.open()
            self.assertTrue(wait_for(lambda: w2.mode == D.DATA))
            self.assertEqual(w2.filter_key, "main")

        # 117 toggles MENU <-> grid (or 415 when empty), and closes modal if open
        w2.controls[MENU].selected = 6
        w2.onClick(MENU)
        self.assertTrue(wait_for(lambda: len(w2.controls[201].items) == 1))
        w2.focus = 201
        self.press(w2, 117)
        self.assertEqual(w2.focus, MENU)
        self.assertEqual(w2.controls[201].items[0].props["fav"], "", "117 must NOT toggle favourite")
        self.press(w2, 117)
        self.assertEqual(w2.focus, 201)

        # When modal is open, 117 closes modal first and focuses MENU
        w2._prop("modal", "detail")
        w2.focus = 210
        self.press(w2, 117)
        self.assertEqual(w2.getProperty("modal"), "")
        self.assertEqual(w2.focus, MENU)

        # When cards is empty, 117 toggles MENU -> PAGE_SEARCH (415)
        w2.cards = []
        w2.focus = MENU
        self.press(w2, 117)
        self.assertEqual(w2.focus, 415)


class Issue108PaginationWarmEmptyShowAndHeroArtTests(WindowCase):
    """Issue #108: incremental addItems pagination, startup warm + top_search cache,
    empty-show 38838 focus & Coming soon badge, and high-res TV Hero art."""

    def test_pages_optional_next_offset_and_has_more_with_v4_compat(self):
        items = [_sample_movie(i, f"Film {i}") for i in range(1, 11)]
        val_with_meta = PG.to_value("Movies", items, 100, next_offset=25, has_more=True)
        self.assertEqual(val_with_meta["v"], PG.VERSION)
        self.assertEqual(val_with_meta["next_offset"], 25)
        self.assertIs(val_with_meta["has_more"], True)
        self.assertEqual(PG.from_value("movies", val_with_meta), ("Movies", items, 100))

        val_legacy = PG.to_value("Movies", items, 100)
        self.assertNotIn("next_offset", val_legacy)
        self.assertNotIn("has_more", val_legacy)
        self.assertEqual(PG.from_value("movies", val_legacy), ("Movies", items, 100))

    def test_incremental_additems_pagination_without_reset_or_selection_loss(self):
        p1 = [_sample_movie(100 + i, f"Page1 {i}") for i in range(20)]
        p2 = [_sample_movie(200 + i, f"Page2 {i}") for i in range(15)]
        offsets = []

        def fake_catalog(section, genre_id=0, sort_mode_id=1, offset=0, limit=30, tr=None):
            offsets.append(offset)
            if offset == 0:
                return {"ok": True, "section": section, "items": p1, "total": 90,
                        "next_offset": 45, "has_more": True}
            if offset == 45:
                return {"ok": True, "section": section, "items": p2, "total": 90,
                        "next_offset": 60, "has_more": False}
            return {"ok": True, "section": section, "items": [], "total": 90,
                    "next_offset": offset, "has_more": False}

        write_list(answer(chan(10, "Ten", number=10)))
        with mock.patch.object(API, "configuration", return_value=_sample_config()), \
             mock.patch.object(API, "catalog_page", side_effect=fake_catalog):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 5  # movies
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 20))
            self.assertEqual(window.cat_next_offset, 45)
            self.assertIs(window.cat_has_more, True)

            ctrl = window.controls[ROW]
            ctrl.selectItem(17)
            with mock.patch.object(ctrl, "reset", wraps=ctrl.reset) as m_reset, \
                 mock.patch.object(ctrl, "addItems", wraps=ctrl.addItems) as m_add:
                window._maybe_paginate()
                self.assertTrue(wait_for(lambda: len(ctrl.items) == 35))
                m_reset.assert_not_called()
                m_add.assert_called_once()
                self.assertEqual(len(m_add.call_args[0][0]), 15)

            self.assertEqual(offsets, [0, 45], "Second page must request next_offset=45, not len(cat_items)=20")
            self.assertEqual(ctrl.getSelectedPosition(), 17)
            self.assertEqual(window.cat_next_offset, 60)
            self.assertIs(window.cat_has_more, False)

            # Boundary: has_more=False must stop further pagination even when len(items) < total
            window._maybe_paginate()
            time.sleep(0.05)
            self.assertEqual(offsets, [0, 45])

            # Empty append is a safe no-op
            with mock.patch.object(ctrl, "reset", wraps=ctrl.reset) as m_reset:
                window._append_cards([])
                m_reset.assert_not_called()
                self.assertEqual(ctrl.getSelectedPosition(), 17)

    def test_startup_warm_order_auth_gating_playback_pause_and_50_slice_cap(self):
        write_list(answer(chan(10, "Ten", number=10)))
        warm_calls = []

        def capture_warm(ns, tasks, idle=None, **kw):
            warm_calls.append((ns, list(tasks), idle))
            return mock.Mock()

        many_shows = [{"id": f"s{i}", "kind": "show_vod", "title": f"Show {i}",
                       "poster": f"https://img/s{i}.jpg"} for i in range(65)]
        many_top = [{"kind": "movie", "id": str(500 + i), "title": f"Top {i}",
                     "subtitle": "2024", "cid": "", "epg": "", "start": 0, "stop": 0,
                     "channel_name": "", "when": "", "live": False,
                     "playable_in_archive": False, "playable": True, "available": True,
                     "vod_url": f"plugin://plugin.video.sweettv/playvod/{500 + i}|null|0",
                     "preview": "", "image_url": f"https://img/t{i}.jpg",
                     "repeats": 0, "more": ""} for i in range(65)]

        with mock.patch.object(prefetch, "warm", side_effect=capture_warm), \
             mock.patch.object(API, "shows", return_value={"ok": True, "items": many_shows}), \
             mock.patch.object(API, "catalog_page", return_value={"ok": True, "items": [_sample_movie()], "total": 1}), \
             mock.patch.object(API, "top_search", return_value={"ok": True, "items": many_top, "count": 65}):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertTrue(wait_for(lambda: len(warm_calls) == 1))

            # Calling _start_warm() again must not duplicate startup warm
            window._start_warm()
            self.assertEqual(len(warm_calls), 1)

            ns, tasks, idle_fn = warm_calls[0]
            self.assertEqual(ns, NS)
            self.assertEqual(
                [k for k, _ in tasks],
                [PG.catalog_key("shows"), PG.catalog_key("series", 0, 1, 0),
                 PG.catalog_key("movies", 0, 1, 0), PG.catalog_key("top_search")],
            )

            # Playback pauses warming
            Fake.playing = False
            self.assertTrue(idle_fn())
            Fake.playing = True
            self.assertFalse(idle_fn())
            Fake.playing = False

            # shows and top_search tasks slice to MAX_SLICE (50) with total=50 so from_value accepts them
            task_map = dict(tasks)
            shows_val = task_map[PG.catalog_key("shows")]()
            self.assertEqual(len(shows_val["items"]), PG.MAX_SLICE)
            self.assertEqual(shows_val["total"], PG.MAX_SLICE)
            self.assertIsNotNone(PG.from_value("shows", shows_val))

            top_val = task_map[PG.catalog_key("top_search")]()
            self.assertEqual(len(top_val["items"]), PG.MAX_SLICE)
            self.assertEqual(top_val["total"], PG.MAX_SLICE)
            self.assertIsNotNone(PG.from_value("top_search", top_val))

        # Negative: demo mode and signed-out state must not start warm
        warm_calls.clear()
        with mock.patch.object(prefetch, "warm", side_effect=capture_warm):
            w_demo = self.open(demo=True)
            self.assertTrue(wait_for(lambda: w_demo.mode == D.DATA))
            w_demo._start_warm()
            self.assertEqual(warm_calls, [])

            sign(False)
            w_out = self.open(demo=False)
            self.assertTrue(wait_for(lambda: w_out.mode == D.SIGNIN))
            w_out._start_warm()
            self.assertEqual(warm_calls, [])

    def test_top_search_page_cache_hit_swr_and_skeletons(self):
        write_list(answer(chan(10, "Ten", number=10)))
        cached_row = {"kind": "movie", "id": "701", "title": "Cached Top", "subtitle": "2024",
                      "cid": "", "epg": "", "start": 0, "stop": 0, "channel_name": "", "when": "",
                      "live": False, "playable_in_archive": False, "playable": True, "available": True,
                      "vod_url": "plugin://plugin.video.sweettv/playvod/701|null|0",
                      "preview": "", "image_url": "https://img/701.jpg", "repeats": 0, "more": ""}
        fresh_row = dict(cached_row, id="702", title="Fresh Top", image_url="https://img/702.jpg")

        # 1. Fresh cache hit renders without calling API.top_search
        page_cache.put(NS, PG.catalog_key("top_search"), PG.to_value("top_search", [cached_row], 1), now=time.time())
        with mock.patch.object(API, "top_search", side_effect=AssertionError("fresh cache must not hit API")):
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 0  # search
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Cached Top"]))

        # 2. Stale cache hit (SWR) renders stale immediately and refreshes in background
        stale_ts = time.time() - (PG.PAGE_TTL + 30)
        page_cache.put(NS, PG.catalog_key("top_search"), PG.to_value("top_search", [cached_row], 1), now=stale_ts)
        refreshed = threading.Event()

        def fake_swr_top(*_a, **_kw):
            refreshed.set()
            return {"ok": True, "items": [fresh_row], "count": 1}

        with mock.patch.object(API, "top_search", side_effect=fake_swr_top):
            window.stop()
            sweettv_app.quick_resume.drop_snapshots("sweettv")
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 0
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Cached Top"]))
            self.assertTrue(refreshed.wait(1.5))
            self.assertTrue(wait_for(
                lambda: (page_cache.get(NS, PG.catalog_key("top_search"),
                                        ttl=PG.PAGE_TTL, max_age=PG.PAGE_MAX_AGE) or mock.Mock(value={})
                         ).value.get("items", [{}])[0].get("id") == "702"
            ))

        # 3. Uncached miss shows skeleton cards while loading, then caches <= MAX_SLICE
        page_cache.drop_namespace(NS)
        gate = threading.Event()
        many_top = [dict(cached_row, id=str(800 + i), title=f"Top {i}") for i in range(60)]

        def slow_top(*_a, **_kw):
            gate.wait(2.0)
            return {"ok": True, "items": many_top, "count": 60}

        with mock.patch.object(API, "top_search", side_effect=slow_top):
            window.stop()
            sweettv_app.quick_resume.drop_snapshots("sweettv")
            window = self.open()
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            window.controls[MENU].selected = 0
            window.onClick(MENU)
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) > 0 and window.cards[0].key.startswith("skel:")))
            gate.set()
            self.assertTrue(wait_for(lambda: len(window.controls[ROW].items) == 60))
            hit = page_cache.get(NS, PG.catalog_key("top_search"), ttl=PG.PAGE_TTL, max_age=PG.PAGE_MAX_AGE)
            self.assertIsNotNone(hit)
            parsed = PG.from_value("top_search", hit.value)
            self.assertIsNotNone(parsed)
            self.assertEqual((len(parsed[1]), parsed[2]), (PG.MAX_SLICE, PG.MAX_SLICE))

    def test_empty_show_38838_focus_fav_coming_soon_badge_and_movie_detail_untouched(self):
        # Text dictionary must have symmetric ru/uk strings with TV-font-safe en-dash U+2013
        ru_str = W.TEXT["Coming soon \u2013 no episodes yet"]["ru"]
        uk_str = W.TEXT["Coming soon \u2013 no episodes yet"]["uk"]
        self.assertEqual(ru_str, "Скоро \u2013 серий пока нет")
        self.assertEqual(uk_str, "Незабаром \u2013 серій ще немає")

        # Skin XML: 209 <ondown> must guard Container(410).NumItems > 0
        root = ET.parse(XML).getroot()
        grp_209 = next(c for c in root.iter("control") if c.get("id") == "209")
        ondown_cond = grp_209.find("ondown").get("condition") or ""
        self.assertIn("Container(410).NumItems", ondown_cond)
        self.assertFalse(_eval_kodi_cond(ondown_cond, {"guide": "1"}, container_counts={410: 0}))
        self.assertTrue(_eval_kodi_cond(ondown_cond, {"guide": "1"}, container_counts={410: 2}))
        self.assertFalse(_eval_kodi_cond(ondown_cond, {"guide": ""}, container_counts={410: 2}))

        write_list(answer(chan(10, "Ten", number=10)))
        window = self.open()
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))

        # Empty show 38838 (released=False, seasons=[] and seasons=[{"episodes": []}])
        for seasons in ([], [{"id": 1, "number": 1, "title": "S1", "episodes": []}]):
            detail_38838 = {
                "ok": True, "id": "vod:38838", "movie_id": "38838",
                "title": "Танцюють всі", "released": False, "seasons": seasons,
            }
            card = sweettv_app.sections.vod_card(
                {"id": 38838, "title": "Танцюють всі", "poster": "https://img/38838.jpg"}, "series",
            )
            for lang, expected_badge in (("ru", ru_str), ("uk", uk_str)):
                W.set_language(lang)
                with mock.patch.object(API, "vod_detail", return_value=detail_38838):
                    window._open_show_modal(card)
                    self.assertTrue(wait_for(lambda: window.focus == 213))
                    self.assertEqual(window.getProperty("has_play"), "")
                    self.assertEqual(window.getProperty("hero_play"), "")
                    self.assertEqual(window.getProperty("has_alt"), "")
                    self.assertEqual(window.getProperty("has_guide"), "")
                    self.assertEqual(window.getProperty("guide"), "")
                    self.assertEqual(window.getProperty("hero_meta"), expected_badge)

        # Regular Movie Detail (modal == "detail" with vod_url) stays untouched
        movie_detail = {
            "ok": True, "id": "vod:501", "movie_id": "501", "title": "Inception",
            "year": 2010, "duration": 8880, "imdb_rating": 8.8, "description": "Dream",
            "vod_url": "plugin://plugin.video.sweettv/playvod/501|null|10",
        }
        m_card = sweettv_app.sections.vod_card(_sample_movie(501, "Inception"), "movie")
        with mock.patch.object(API, "vod_detail", return_value=movie_detail):
            window._open_detail_modal(m_card)
            self.assertTrue(wait_for(lambda: window.getProperty("has_play") == "1" and window.focus == 210))

    def test_high_res_hero_art_cdn_cgi_strip_priority_continue_and_search(self):
        # 1. logo_of strips /cdn-cgi/image/.../ wrapper while keeping plain URLs
        self.assertEqual(
            D.logo_of("https://static.sweet.tv/cdn-cgi/image/width=340,height=160/https://static.sweet.tv/epg/1.jpg"),
            "https://static.sweet.tv/epg/1.jpg",
        )
        self.assertEqual(
            D.logo_of("https://static.sweet.tv/cdn-cgi/image/f=auto,w=340/epg/2.png"),
            "https://static.sweet.tv/epg/2.png",
        )
        self.assertEqual(D.logo_of("https://static.sweet.tv/plain.jpg"), "https://static.sweet.tv/plain.jpg")

        # 2. Programme.hero_image uses image_url only while Programme.image is preserved
        ch_both = D.parse_channel(chan(
            1, "One", number=1,
            icon_v2_url="https://img/logo1.png",
            banner_url="https://img/banner1.jpg",
            epg=[{"id": 11, "time_start": NOW - 600, "time_stop": NOW + 600, "text": "Live",
                  "available": True,
                  "image_url": "https://img/hero_960.jpg",
                  "preview_url_ext": "https://static.sweet.tv/cdn-cgi/image/w=340/https://img/prev_340.jpg"}],
        ), NOW)
        self.assertEqual(ch_both.epg[0].hero_image, "https://img/hero_960.jpg")
        self.assertTrue(ch_both.epg[0].image)

        ch_no_img_url = D.parse_channel(chan(
            2, "Two", number=2,
            icon_v2_url="https://img/logo2.png",
            banner_url="https://img/banner2.jpg",
            epg=[{"id": 12, "time_start": NOW - 600, "time_stop": NOW + 600, "text": "Live2",
                  "available": True, "preview_url_ext": "https://img/prev2.jpg"}],
        ), NOW)
        self.assertEqual(ch_no_img_url.epg[0].hero_image, "")
        self.assertEqual(ch_no_img_url.epg[0].image, "https://img/prev2.jpg")

        # 3. channel_card banner priority: image_url > banner_url > preview_url_ext > logo
        self.assertEqual(sweettv_app.sections.channel_card(ch_both, {}, NOW).banner, "https://img/hero_960.jpg")
        self.assertEqual(sweettv_app.sections.channel_card(ch_no_img_url, {}, NOW).banner, "https://img/banner2.jpg")

        ch_prev_only = D.parse_channel(chan(
            3, "Three", number=3, icon_v2_url="https://img/logo3.png",
            epg=[{"id": 13, "time_start": NOW - 600, "time_stop": NOW + 600, "text": "Live3",
                  "available": True, "preview_url_ext": "https://img/prev3.jpg"}],
        ), NOW)
        self.assertEqual(sweettv_app.sections.channel_card(ch_prev_only, {}, NOW).banner, "https://img/prev3.jpg")

        ch_logo_only = D.parse_channel(chan(4, "Four", number=4, icon_v2_url="https://img/logo4.png", epg=[]), NOW)
        self.assertEqual(sweettv_app.sections.channel_card(ch_logo_only, {}, NOW).banner, "https://img/logo4.png")

        # 4. _continue_epg_card prefers image_url > ch.banner > preview
        cat = D.parse_catalog(answer(
            chan(10, "Ten", number=10, catchup=True, catchup_duration=3, icon_v2_url="https://img/l10.png", banner_url="https://img/b10.jpg"),
            chan(11, "Eleven", number=11, catchup=True, catchup_duration=3, icon_v2_url="https://img/l11.png"),
        ), NOW)
        resume_doc = {
            "v": 1,
            "items": {
                "sw:10|901": {"cid": "10", "epg": "901", "pos": 120, "total": 1800, "done": False,
                              "at": NOW - 10, "title": "With Image", "start": NOW - 3000, "stop": NOW - 1200,
                              "image_url": "https://img/epg_960.jpg", "preview": "https://img/epg_340.jpg"},
                "sw:10|902": {"cid": "10", "epg": "902", "pos": 120, "total": 1800, "done": False,
                              "at": NOW - 20, "title": "With Ch Banner", "start": NOW - 3000, "stop": NOW - 1200,
                              "preview": "https://img/epg_340.jpg"},
                "sw:11|903": {"cid": "11", "epg": "903", "pos": 120, "total": 1800, "done": False,
                              "at": NOW - 30, "title": "Preview Fallback", "start": NOW - 3000, "stop": NOW - 1200,
                              "preview": "https://img/epg_340.jpg"},
            },
        }
        cont = sweettv_app.sections.continue_cards(resume_doc, cat, NOW)
        by_title = {c.title: c for c in cont}
        self.assertEqual(by_title["With Image"].banner, "https://img/epg_960.jpg")
        self.assertEqual(by_title["With Ch Banner"].banner, "https://img/b10.jpg")
        self.assertEqual(by_title["Preview Fallback"].banner, "https://img/epg_340.jpg")

        # 5. search_card propagates banner_url / wide_art on search channel cards
        sc = sweettv_app.sections.search_card({
            "kind": "channel", "id": "10", "title": "Ten", "subtitle": "HD",
            "cid": "10", "epg": "", "start": 0, "stop": 0, "channel_name": "Ten",
            "when": "", "live": True, "playable_in_archive": False, "playable": True,
            "available": True, "preview": "https://img/logo10.png",
            "banner_url": "https://img/ch_banner10.jpg", "wide_art": "https://img/ch_wide10.jpg",
            "image_url": "", "repeats": 0, "more": "",
        })
        self.assertEqual(sc.banner, "https://img/ch_banner10.jpg")
        self.assertEqual(sc.wide_art, "https://img/ch_wide10.jpg")

if __name__ == "__main__":
    unittest.main()
