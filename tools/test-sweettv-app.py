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


class Control:
    def __init__(self):
        self.items, self.selected = [], 0

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
        self.controls = {100: Control(), 200: Control(), 300: Control(), 400: Control(), 500: Control(), 600: Control()}
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
from resources.lib import page_cache, prefetch, sweettv_pages as PG, sweettv_sections as SEC, textfit  # noqa: E402
import mediastick_sweetlive as ML  # noqa: E402
import panel_sweettv as ps  # noqa: E402

sweettv_app.PAGES = False                # most tests are not about the disk cache; SectionPages turns it on
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
        self.assertEqual([e.count for e in D.rail(catalog, state)][3:], [9, 8, 8, 8, 8, 8])
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
        self.assertEqual([e.name for e in D.rail(catalog, state)], ["Continue", "Favourites", "All", "News", "Films"])
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
        self.assertEqual((props["now"], props["nowrange"], props["next"], props["nextrange"]),
                         ("Late show", "23:00 – 00:00", "Night news", "00:00 – 01:00"))
        self.assertEqual((props["bar"], props["pbar"]), ("sweettv-bar-10.png", "sweettv-pbar-10.png"))
        gap = V.card_props(self.channel, MIDNIGHT + 3600 + 5)
        self.assertEqual((gap["now"], gap["bar"], gap["pbar"], gap["nextrange"]), ("No programme information", "", "", "02:00 – 03:00"))
        after = V.card_props(self.channel, MIDNIGHT + 4 * 3600)
        self.assertEqual((after["next"], after["nextrange"]), ("", ""))

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
        self.assertEqual((props["now"], props["nowrange"], props["next"], props["nextrange"]),
                         ("Now ten", "07:50 – 08:10", "Then ten", "08:10 – 08:20"))
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
        self.assertEqual([(e.key, e.count) for e in D.rail(catalog, state)], [("recent", 2), ("fav", 1), ("all", 3)])
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
        for name in ("temp", "profile", "addon_data"):
            import shutil
            shutil.rmtree(os.path.join(TMP, name), ignore_errors=True)
        for name in ("builtins", "notes", "rpc", "rpc_threads", "played", "seeks"):
            getattr(Fake, name).clear()
        Fake.playing, Fake.stopped = False, 0
        Fake.position, Fake.length = 0.0, 0.0
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
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.stop()

    def make(self, demo=False, state=None, screen=sweettv_app.CHANNELS):
        """A window set up, on the channels (as the screen was before the sections) unless a test asks for the first screen."""
        if state is not None:
            S.save_state(files.state_path(), state)
        window = sweettv_app.SweetTV()
        window.setup(demo=demo)
        window.screen = screen
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

    def test_the_row_the_menu_and_the_preview_come_from_the_file(self):
        window = self.ready()
        self.assertEqual(self.shown(window), ["Ten", "Twenty", "Thirty"])
        self.assertEqual([(i.label, i.label2) for i in window.controls[MENU].items],
                         [("Continue", "0"), ("Favourites", "0"), ("All", "3"), ("News", "2"), ("Films", "2")])
        self.assertEqual((window.cat_key, window.controls[MENU].selected, window.focus), (D.ALL, 2, ROW))   # nothing watched yet
        self.assertEqual(window.controls[MENU].items[3].props["heading"], "News  ·  2 channels")
        card = window.controls[ROW].items[0]
        self.assertEqual((card.props["num"], card.props["now"], card.props["next"], card.props["desc"]),
                         ("10", "Now ten", "Then ten", "About ten"))
        self.assertEqual((card.props["nowrange"], card.props["nextrange"], card.props["meta"]),
                         ("07:50 – 08:10", "08:10 – 08:20", "Channel 10  ·  News"))
        self.assertTrue(card.props["bar"].endswith("sweettv-bar-10.png") and card.props["pbar"].endswith("sweettv-pbar-10.png"))
        self.assertTrue(os.path.isabs(card.props["bar"]))
        self.assertEqual(window.getProperty("demo"), "")

    def test_the_preview_shows_the_data_of_the_channel_under_the_focus(self):
        window = self.ready()
        items = window.controls[ROW].items
        for position, channel in enumerate(window.shown):
            window.controls[ROW].selected = position                        # the skin reads the focused item's own properties
            focused = items[window.controls[ROW].getSelectedPosition()]
            self.assertEqual(focused.label, channel.name)
            self.assertEqual(focused.props, window._shown_props[channel.cid])
            expected = V.card_props(channel, NOW, False, window.cat_names)
            expected["bar"], expected["pbar"] = (os.path.join(sweettv_app.ui.MEDIA, expected[k]) if expected[k] else "" for k in ("bar", "pbar"))
            self.assertEqual(focused.props, expected)
        self.assertEqual(items[1].props["now"], "No programme information")
        self.assertEqual(items[1].props["bar"], "")

    def test_it_opens_on_continue_with_the_channel_watched_last_under_the_focus(self):
        window = self.ready(state={"favourites": [], "recent": recent("30", "10"), "last": "30"})
        self.assertEqual((window.cat_key, self.shown(window)), (D.RECENT, ["Thirty", "Ten"]))
        self.assertEqual((window.controls[ROW].selected, window.focus, window.controls[MENU].selected), (0, ROW, 0))
        self.assertEqual(window.controls[MENU].items[0].props["heading"], "Continue  ·  2 channels")
        self.assertEqual([i.props["active"] for i in window.controls[MENU].items], ["1", "", "", "", ""])
        other = self.open(state={"favourites": [], "recent": recent("999"), "last": "999"})
        self.assertTrue(wait_for(lambda: other.mode == D.DATA))
        self.assertEqual((other.cat_key, other.controls[ROW].selected), (D.ALL, 0))          # nothing of it is on offer
        again = self.open(state={"favourites": [], "recent": recent("20", "10", "30"), "last": "10"})
        self.assertTrue(wait_for(lambda: again.mode == D.DATA))
        self.assertEqual((self.shown(again), again.controls[ROW].selected), (["Twenty", "Ten", "Thirty"], 1))   # the last played is focused

    def test_the_recent_channels_are_the_last_twelve_played_the_newest_first(self):
        raw = answer(*[chan(100 + n, f"C{n}", number=n + 1) for n in range(15)])
        window = self.ready(raw=raw)
        for n in range(15):
            window.controls[ROW].selected = n
            Fake.now = NOW + n
            window.onClick(ROW)
        self.assertEqual([e["id"] for e in window.state["recent"]], [str(100 + n) for n in range(14, 2, -1)])
        self.assertEqual(window.controls[MENU].items[0].label2, "12")
        window.cat_key = ""
        window._fill_row(D.RECENT)
        self.assertEqual(self.shown(window)[:3], ["C14", "C13", "C12"])
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

    def test_a_category_in_the_menu_changes_the_row_after_a_short_rest(self):
        window = self.ready()
        menu = window.controls[MENU]
        window.focus, menu.selected = MENU, 3
        with mock.patch.object(sweettv_app, "MENU_DELAY", 0.02):
            self.press(window, KEY_DOWN)                            # the row follows after the delay
            self.assertTrue(wait_for(lambda: self.shown(window) == ["Ten", "Thirty"]))
        self.assertEqual([i.props["active"] for i in menu.items], ["", "", "", "1", ""])
        self.assertEqual((window.controls[ROW].selected, window.cat_key), (0, "c:1"))                   # its first channel
        self.assertEqual(window.getProperty("emptycat"), "")

    def test_a_burst_of_key_presses_in_the_menu_changes_the_row_once(self):
        window = self.ready()
        window.focus = MENU
        fills = []
        real = window._fill_row
        window._fill_row = lambda *a, **k: (fills.append(a), real(*a, **k))[1]
        with mock.patch.object(sweettv_app, "MENU_DELAY", 0.05):
            for position in (3, 4, 3, 4):
                window.controls[MENU].selected = position
                self.press(window, KEY_DOWN)
            self.assertTrue(wait_for(lambda: fills))
            time.sleep(0.15)
        self.assertEqual([a[0] for a in fills], ["c:2"])

    def test_right_goes_into_the_row_with_what_the_menu_shows_and_ok_does_too(self):
        window = self.ready()
        menu = window.controls[MENU]
        window.focus, menu.selected = MENU, 4
        self.press(window, KEY_RIGHT)                                # before the rest is over
        self.assertEqual(self.shown(window), ["Twenty", "Thirty"])
        window.onClick(MENU)
        self.assertEqual(window.focus, ROW)
        menu.selected = 1                                           # nobody has favourites yet
        window.onClick(MENU)
        self.assertEqual(self.shown(window), [])
        self.assertIn("No favourites", window.getProperty("emptycat"))
        self.assertEqual(window.focus, ROW)                          # (an empty row takes no focus on the device: Kodi keeps it)
        menu.selected = 0
        window.onClick(MENU)
        self.assertIn("Nothing watched", window.getProperty("emptycat"))
        menu.selected = 2
        window.onClick(MENU)
        self.assertEqual(window.getProperty("emptycat"), "")

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
        self.assertEqual(window.controls[MENU].items[0].label2, "1")
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
            self.assertTrue(wait_for(lambda: self.saved()["favourites"] == ["20"] and self.saved()["last"] == "20"))
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
        self.assertEqual(window.controls[MENU].items[1].label2, "1")
        self.assertTrue(wait_for(lambda: self.saved()["favourites"] == ["20"]))
        window.stop()
        again = self.open()
        self.assertTrue(wait_for(lambda: again.mode == D.DATA))
        self.assertEqual(again.controls[ROW].items[1].props["fav"], "1")
        self.assertEqual(again.controls[ROW].items[0].props["fav"], "")
        again.controls[MENU].selected = 1
        again.onClick(MENU)
        self.assertEqual(self.shown(again), ["Twenty"])
        again.focus = ROW
        self.press(again, 117)                                      # off again, in the favourites view
        self.assertEqual(self.shown(again), [])
        self.assertTrue(wait_for(lambda: self.saved()["favourites"] == []))
        again.focus = MENU
        self.press(again, 117)                                      # on the menu the key does nothing
        self.assertEqual(self.shown(again), [])

    def test_removing_a_favourite_keeps_the_focus_close(self):
        window = self.ready(state={"favourites": ["10", "20", "30"], "recent": [], "last": ""})
        window.controls[MENU].selected = 1
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
        window.controls[MENU].selected = 3
        window.onClick(MENU)
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
        self.assertEqual(window.controls[MENU].selected, 2)         # and the menu is on All
        self.assertEqual([i.props["active"] for i in window.controls[MENU].items][2], "1")
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
        self.assertEqual((window.closed, window.screen, window.focus), (False, sweettv_app.HOME, sweettv_app.SECTIONS))   # up to the sections
        self.press(window, 92)
        self.assertTrue(window.closed)
        window = self.open()
        self.press(window, 10)                                                    # the other Back key goes up one step as well
        self.assertEqual((window.closed, window.screen), (False, sweettv_app.HOME))
        self.press(window, 10)
        self.assertTrue(window.closed)

    def test_digits_do_nothing_when_no_channel_has_a_number(self):
        window = self.ready(raw=answer(chan(1, "A"), chan(2, "B")))
        self.press(window, 58 + 2)
        self.assertEqual((window.getProperty("jump"), window.controls[ROW].selected), ("", 0))

    def test_a_catalog_that_changes_keeps_the_focused_channel_and_category(self):
        window = self.ready()
        window.controls[MENU].selected = 3
        window.onClick(MENU)
        window.controls[ROW].selected = 1
        write_list(self.raw())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        window._look()
        self.assertEqual((self.shown(window), window.controls[ROW].selected), (["Ten", "Thirty"], 1))
        self.assertEqual(window.controls[MENU].selected, 3)
        write_list(answer(chan(10, "Ten", number=10)))              # the categories are gone: back to the default
        os.utime(files.channel_path(), (time.time() + 90, time.time() + 90))
        window._look()
        self.assertEqual(self.shown(window), ["Ten"])
        self.assertEqual(window.cat_key, D.ALL)

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


class Archive(WindowCase):
    """Programme guide, catch-up and "continue from"."""

    def setUp(self):
        super().setUp()
        Fake.now = NOW

    def raw(self):
        epg = [prog(NOW - 9000, NOW - 5400, "Not offered", 5, available=False), prog(NOW - 5400, NOW - 1800, "Early show", 7),
               prog(NOW - 1800, NOW - 600, "Late show", 8), prog(NOW - 600, NOW + 600, "Now ten", 9),
               prog(NOW + 600, NOW + 1200, "Then ten", 10)]
        return answer(chan(10, "Ten", number=10, catchup=True, catchup_duration=3, epg=epg),
                      chan(20, "Twenty", number=20, epg=[prog(NOW - 600, NOW + 600, "Now twenty", 21)]))

    def ready(self, **kw):
        write_list(self.raw())
        window = self.open(**kw)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        return window

    def start_guide(self, window):
        window.focus = ROW
        window.controls[ROW].selected = 0
        self.press(window, KEY_UP)
        self.assertEqual(window.focus, GUIDE_BUTTON)
        window.onClick(GUIDE_BUTTON)

    def test_up_from_a_channel_with_an_archive_goes_to_the_guide_button_and_other_channels_stay_put(self):
        window = self.ready()
        self.assertTrue(window.controls[ROW].items[0].props["guide"])
        self.assertIn("Up", window.getProperty("hint"))
        self.start_guide(window)
        window.focus = ROW
        window.controls[ROW].selected = 1
        self.press(window, KEY_UP)
        self.assertEqual(window.focus, ROW)                          # no archive, nothing to go up to

    def test_the_guide_lists_the_live_programme_and_the_archive_and_back_closes_it(self):
        window = self.ready()
        self.start_guide(window)
        self.assertEqual((window.getProperty("guide"), window.getProperty("guide_title"), window.focus), ("1", "Ten", GUIDE))
        guide = window.controls[GUIDE]
        self.assertEqual([(i.label, i.label2) for i in guide.items], [("Now ten", "Live"), ("Late show", ""), ("Early show", "")])
        self.assertEqual([i.props["when"] for i in guide.items], ["07:50 – 08:10", "07:30 – 07:50", "06:30 – 07:30"])
        self.assertEqual(guide.selected, 0)
        self.assertTrue(window.guide_open)
        self.press(window, 117)                                      # the menu key and the digits do nothing in the guide
        self.press(window, 58 + 2)
        self.assertEqual((window.getProperty("jump"), window.state["favourites"]), ("", []))
        self.press(window, 92)
        self.assertEqual((window.getProperty("guide"), window.closed, window.focus), ("", False, GUIDE_BUTTON))
        self.assertFalse(window.guide_open)

    def test_ok_in_the_guide_plays_the_archive_or_the_live_programme(self):
        window = self.ready()
        self.start_guide(window)
        window.controls[GUIDE].selected = 2
        window.onClick(GUIDE)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"], "plugin://plugin.video.sweettv/playvid/10|7")
        self.assertEqual((window.session.cid, window.session.epg, window.session.title), ("10", "7", "Early show"))
        self.assertEqual((window.session.start, window.session.stop), (NOW - 5400, NOW - 1800))
        self.assertTrue(wait_for(lambda: self.saved()["last"] == "10"))
        window.controls[GUIDE].selected = 0                          # the live one
        window.onClick(GUIDE)
        self.assertTrue(wait_for(lambda: len(Fake.rpc) == 2))
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"], "plugin://plugin.video.sweettv/playvid/10|null")
        self.assertIsNone(window.session)
        self.assertEqual(window.getProperty("guide"), "1")           # back from the player it is still there

    def test_the_place_an_archived_programme_stopped_at_is_kept_and_offered_again(self):
        window = self.ready()
        self.start_guide(window)
        window.controls[GUIDE].selected = 2
        Fake.playing, Fake.position, Fake.length = True, 900.0, 3600.0
        window.onClick(GUIDE)
        self.assertTrue(wait_for(lambda: window.session is not None and Fake.rpc))
        time.sleep(0.05)
        Fake.playing = False                                         # the player stopped
        self.assertTrue(wait_for(lambda: window.session is None))
        self.assertTrue(wait_for(lambda: "10" in self.saved()["resume"]))
        self.assertEqual(self.saved()["resume"]["10"], {"epg": "7", "title": "Early show", "start": NOW - 5400,
                                                         "stop": NOW - 1800, "pos": 900, "at": NOW})
        item = window.controls[ROW].items[0]
        self.assertEqual(item.props["resume"], "Continue from 06:45")
        window.onClick(GUIDE)                                        # nothing changes while the guide is open on a live row
        self.press(window, 92)
        window.focus = ROW
        self.press(window, KEY_UP)
        self.assertEqual(window.focus, RESUME)                       # the continue button comes first, then the guide
        Fake.rpc.clear()
        Fake.playing, Fake.position, Fake.length = True, 0.0, 3600.0
        window.onClick(RESUME)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"], "plugin://plugin.video.sweettv/playvid/10|7")
        self.assertTrue(wait_for(lambda: Fake.seeks == [900.0]))     # on to where it stopped
        Fake.playing = False
        self.assertTrue(wait_for(lambda: window.session is None))
        self.assertEqual(window.controls[ROW].items[1].props["resume"], "")

    def test_a_programme_left_at_its_start_has_nothing_to_continue(self):
        window = self.ready()
        self.start_guide(window)
        window.controls[GUIDE].selected = 2
        Fake.playing, Fake.position, Fake.length = True, 20.0, 3600.0
        window.onClick(GUIDE)
        self.assertTrue(wait_for(lambda: window.session is not None))
        time.sleep(0.05)
        Fake.playing = False
        self.assertTrue(wait_for(lambda: window.session is None))
        self.assertEqual(window.state["resume"], {})
        self.assertEqual(window.controls[ROW].items[0].props["resume"], "")

    def test_coming_back_to_the_screen_notes_the_place_before_it_stops_the_player(self):
        window = self.ready()
        self.start_guide(window)
        window.controls[GUIDE].selected = 1
        Fake.playing, Fake.position, Fake.length = True, 100.0, 1200.0
        window.onClick(GUIDE)
        self.assertTrue(wait_for(lambda: window.session is not None))
        Fake.position = 700.0                                        # moved on since the last look
        window.play_at -= 10
        window.onInit()
        self.assertTrue(wait_for(lambda: Fake.stopped == 1))
        self.assertTrue(wait_for(lambda: window.state["resume"].get("10", {}).get("pos") == 700))
        self.assertTrue(wait_for(lambda: self.saved()["resume"].get("10", {}).get("epg") == "8"))

    def test_the_continue_button_goes_away_when_the_programme_leaves_the_archive(self):
        state = {"favourites": [], "recent": [], "last": "",
                 "resume": {"10": {"epg": "7", "title": "Early show", "start": NOW - 5400, "stop": NOW - 1800, "pos": 900, "at": NOW}}}
        window = self.ready(state=state)
        self.assertEqual(window.controls[ROW].items[0].props["resume"], "Continue from 06:45")
        Fake.now = NOW + 4 * 86400
        write_list(self.raw())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        window._look()
        self.assertEqual(window.controls[ROW].items[0].props["resume"], "")


class Demo(WindowCase):
    def test_demo_is_marked_fills_from_the_fixture_and_never_touches_real_data(self):
        write_list(answer(chan(1, "Real")))
        with mock.patch.object(files, "file_stamp", side_effect=AssertionError("real file")), \
                mock.patch.object(files, "signed_in", side_effect=AssertionError("real login")):
            window = self.open(demo=True)
            self.assertTrue(wait_for(lambda: window.mode == D.DATA))
            self.assertEqual((window.getProperty("demo"), window.getProperty("chip")), ("1", "Demo"))
            self.assertEqual(len(window.catalog.channels), len(sweettv_demo.names()))
            self.assertEqual([i.label for i in window.controls[MENU].items],
                             ["Continue", "Favourites", "All", "News", "Movies & Series", "Sport", "Kids",
                              "Music & Lifestyle", "Documentary"])
            self.assertEqual(window.cat_key, D.RECENT)               # it opens on what was watched last
            self.assertEqual(self.shown(window)[:2], ["Cinema Nova", "Aurora News 24"])
            self.assertNotIn("Real", self.shown(window))
            card = window.controls[ROW].items[0]
            self.assertTrue(card.props["now"] and card.props["next"] and card.props["bar"] and card.props["resume"])
            self.assertEqual(window.controls[MENU].items[1].label2, str(len(sweettv_demo.FAVOURITES)))
            window._look()                                          # the minute tick
            self.assertEqual(window.mode, D.DATA)

    def test_demo_logos_exist_where_the_cards_point(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        window._fill_row(D.ALL)
        logos = {i.art["icon"] for i in window.controls[ROW].items if i.art}
        self.assertEqual(len(logos), sweettv_demo.LOGOS)
        for logo in logos:
            self.assertTrue(os.path.isfile(logo), logo)
            self.assertLess(os.path.getsize(logo), 20000, logo)
        self.assertTrue(any(not i.art for i in window.controls[ROW].items))      # the badge case

    def test_demo_never_plays_never_saves_and_says_so(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        self.assertIsNone(window.writer)
        window.onClick(ROW)
        window.focus = ROW
        self.press(window, 117)
        self.press(window, KEY_UP)
        self.assertEqual(window.focus, RESUME)                       # the demo has a place to continue from, on the first card
        window.onClick(RESUME)
        window.focus = ROW
        window.controls[ROW].selected = 0
        window.focus = GUIDE_BUTTON
        window.onClick(GUIDE_BUTTON)
        self.assertEqual(window.getProperty("guide"), "1")
        window.controls[GUIDE].selected = 1
        window.onClick(GUIDE)
        time.sleep(0.05)
        self.assertEqual(Fake.rpc, [])
        self.assertEqual(Fake.played, [])
        self.assertEqual(Fake.builtins, [])
        self.assertEqual(Fake.notes, ["Demo: nothing is played."] * 3)
        self.assertFalse(os.path.exists(files.state_path()))
        self.assertEqual(window.play_at, 0.0)
        self.assertIsNone(window.session)

    def test_the_star_works_in_the_demo_and_is_gone_with_it(self):
        window = self.open(demo=True)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        first = window.shown[0]
        was = first.cid in window.state["favourites"]
        window.focus = ROW
        self.press(window, 117)
        self.assertEqual(window.controls[ROW].items[0].props["fav"], "" if was else "1")
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

with open(os.path.join(ROOT, "tools", "fixtures", "sweettv-channel-list.json"), encoding="utf-8") as _f:
    FIXTURE = json.load(_f)                          # five channels of a real list: shows (with and without tv_show_id), films
T = 1795473564                                       # the moment that list was taken
HOME, LIST, SECTIONS, ITEMS = sweettv_app.HOME, sweettv_app.LIST, sweettv_app.SECTIONS, sweettv_app.ITEMS
BACK = 92


def cast(cid, epg, name="Cast", catchup=True, **extra):
    return chan(cid, name, number=cid, catchup=catchup, catchup_duration=7, category=[4, 1000], epg=epg, **extra)


def small_list():
    """One channel with an archive: a show of three episodes (the first out of the archive, the second to watch, the third still
    to come), a film aired twice and a film aired once; and a channel without an archive."""
    return answer(
        cast(10, [prog(T - 90000, T - 87300, "Alpha Season 1 Episode 1", 101, available=False, tv_show_id=5),
                  prog(T - 9000, T - 6300, "Alpha Season 1 Episode 2", 102, tv_show_id=5),
                  prog(T + 9000, T + 11700, "Alpha Season 1 Episode 3", 103, tv_show_id=5),
                  prog(T - 30000, T - 22800, "Hugo", 111), prog(T - 100000, T - 92800, "Hugo", 112),
                  prog(T - 20000, T - 14000, "Solo", 113)], name="Ten"),
        cast(20, [prog(T - 600, T + 600, "Live only", 201)], name="Twenty", catchup=False))


def loaded_library(raw=None):
    library = SEC.Library()
    library.load(("test",), lambda: ps.slim(FIXTURE if raw is None else raw))
    return library


class SectionRows(unittest.TestCase):
    """sweettv_sections: the rows of the lists, made from the same index as the phone page's."""

    def setUp(self):
        self.library = SEC.Library()
        self.assertTrue(self.library.load(("fixture",), lambda: FIXTURE))

    def test_the_three_cards_say_what_is_behind_them_and_how_many_when_that_is_known(self):
        entries = SEC.home_entries(5, None)
        self.assertEqual([e.key for e in entries], ["channels", "shows", "films"])
        self.assertEqual([e.title for e in entries], [W.tr(n) for n in ("Channels", "Shows and series", "Films")])
        self.assertEqual([e.count for e in entries], [W.tr("Channels: {n}").format(n=5), "", ""])
        counted = SEC.home_entries(5, (12, 0))
        self.assertEqual([e.count for e in counted][1:], [W.tr("Shows: {n}").format(n=12), W.tr("Films: {n}").format(n=0)])
        self.assertEqual(len({e.plate for e in entries}), 3)                     # three colours, apart from each other
        for entry in entries:
            self.assertRegex(entry.plate + entry.plate_hi, r"^[0-9A-F]{16}$")
            self.assertNotEqual(entry.plate, entry.plate_hi)
            self.assertTrue(entry.desc)

    def test_the_shows_are_the_phones_shows(self):
        rows, total = self.library.shows(T)
        phone = ps.shows_view(ps.slim(FIXTURE), T)["items"]
        self.assertEqual((len(rows), total), (len(phone), len(phone)))
        self.assertEqual(len(phone), 12)
        self.assertEqual([(r.key, r.title, r.sub) for r in rows],
                         [(s["id"], s["title"], W.tr("Episodes: {n}").format(n=s["episodes"])) for s in phone])
        self.assertEqual({r.side for r in rows}, {""})
        self.assertTrue(all(r.playable and not r.future for r in rows))

    def test_the_episodes_are_the_phones_episodes_in_the_same_order(self):
        phone = ps.slim(FIXTURE)
        for show in ps.shows_view(phone, T)["items"]:
            title, rows, total = self.library.episodes(show["id"], T, {})
            theirs = ps.show_view(phone, show["id"], T)
            self.assertEqual((title, total), (theirs["title"], len(theirs["episodes"])), show["id"])
            self.assertEqual([(r.cid, r.epg, r.start, r.stop, r.playable) for r in rows],
                             [(str(e["cid"]), str(e["epg"]), e["start"], e["stop"], bool(e["available"])) for e in theirs["episodes"]])

    def test_the_films_are_the_phones_films(self):
        rows, total = self.library.films(T, {})
        phone = ps.films_view(ps.slim(FIXTURE), T)["items"]
        self.assertEqual((len(rows), total, len(phone)), (12, 12, 12))
        self.assertEqual([(r.title, r.cid, r.epg, r.start, r.stop) for r in rows],
                         [(f["title"], str(f["cid"]), str(f["epg"]), f["start"], f["stop"]) for f in phone])
        hugo = next(r for r in rows if r.title == "Hugo")
        self.assertEqual(hugo.side, W.tr("Airings: {n}").format(n=2))
        self.assertTrue(hugo.sub.startswith("SWEET MOVIES HD  ·  " + W.tr("{n} min").format(n=134)), hugo.sub)
        self.assertEqual([r.side for r in rows if r.title != "Hugo"], [W.tr("Airings: {n}").format(n=f["airings"]) if f["airings"] > 1 else ""
                                                                         for f in phone if f["title"] != "Hugo"])

    def test_the_rules_are_shared_with_the_phone_not_copied(self):
        self.assertIs(ps.archive_ok.__module__, ps.__name__)
        for channel in FIXTURE["list"]:
            for p in channel["epg"]:
                for now in (T, T - 3 * 86400, T + 3 * 86400, T + 30 * 86400):
                    self.assertEqual(ps.archive_ok(channel, p, now), ML.archive_ok(channel, p, now))
        self.assertEqual(ps.slim(FIXTURE), ML.slim(FIXTURE))
        rows, _ = self.library.films(T, {})
        for row in rows:                                            # what OK plays is what the phone's play route plays at the start
            self.assertEqual(D.play_url(row.cid, row.epg), ML.url(row.cid, row.epg, 0))

    def test_an_episode_to_come_or_out_of_the_archive_is_dimmed_and_says_why(self):
        library = loaded_library(small_list())
        shows = library.shows(T)[0]
        self.assertEqual([(r.title, r.sub) for r in shows], [("Alpha", W.tr("Episodes: {n}").format(n=1))])
        title, rows, total = library.episodes(shows[0].key, T, {"10": ""})
        self.assertEqual((title, total), ("Alpha", 3))
        self.assertEqual([r.playable for r in rows], [False, True, False])
        self.assertEqual([r.future for r in rows], [False, False, True])
        self.assertEqual([r.side for r in rows], [W.tr("Not in the archive"), "", W.tr("Soon")])
        self.assertEqual(rows[1].title, W.tr("Episode {n}").format(n=2))
        self.assertTrue(rows[1].sub.startswith(W.tr("Season {n}").format(n=1) + "  ·  "), rows[1].sub)
        self.assertTrue(rows[1].sub.endswith("  ·  Ten"), rows[1].sub)
        self.assertEqual(SEC.first_playable(rows), 1)                # the cursor starts on what can be watched
        self.assertEqual(SEC.first_playable(rows[:1]), 0)            # nothing to watch: the top
        self.assertEqual((rows[1].cid, rows[1].epg, rows[1].start, rows[1].stop), ("10", "102", T - 9000, T - 6300))

    def test_the_second_line_of_a_film_and_the_note_for_a_film_aired_once(self):
        rows, total = loaded_library(small_list()).films(T, {})
        self.assertEqual([(r.title, r.side) for r in rows], [("Hugo", W.tr("Airings: {n}").format(n=2)), ("Solo", "")])
        solo = rows[1]
        self.assertEqual(solo.sub, "Ten  ·  " + W.tr("{n} min").format(n=100) + "  ·  " + SEC._when(T - 20000, T))
        self.assertEqual((solo.cid, solo.epg), ("10", "113"))
        self.assertEqual(total, 2)

    def test_a_logo_of_the_channel_goes_on_the_row_and_without_one_the_badge_is_made_of_its_name(self):
        library = loaded_library(small_list())
        rows, _ = library.films(T, {"10": "/logos/ten.png"})
        self.assertEqual({r.icon for r in rows}, {data.logo_of("/logos/ten.png")})
        rows, _ = library.films(T, {})
        self.assertEqual({(r.icon, r.mark) for r in rows}, {("", "Ten")})

    def test_a_long_title_is_cut_to_the_room_it_has(self):
        long = "Очень длинное название передачи которое никак не поместится в одну строку экрана телевизора " * 2
        cut = SEC.fit(long, SEC.TITLE_PX, 28)
        self.assertTrue(cut.endswith("…"))
        self.assertLessEqual(textfit.text_px(cut, 28), SEC.TITLE_PX)
        self.assertEqual(SEC.fit("Short", SEC.TITLE_PX, 28), "Short")
        raw = answer(cast(10, [prog(T - 9000, T - 1800, long, 301), prog(T - 20000, T - 12800, long + " 2", 302)], name="Ten"))
        rows, _ = loaded_library(raw).films(T, {})
        for row in rows:
            self.assertLessEqual(textfit.text_px(row.title, 28), SEC.TITLE_PX)
            self.assertLessEqual(textfit.text_px(row.sub, 22), SEC.SUB_PX)
            self.assertEqual(row.name, row.name.strip())

    def test_the_cap_drops_what_cannot_be_watched_first_and_keeps_the_order(self):
        rows = [SEC.Row("", str(i), "", "", "", "", playable=ok) for i, ok in enumerate((False, True, True, False, True))]
        self.assertEqual([r.title for r in SEC.capped(rows, 9)], ["0", "1", "2", "3", "4"])
        self.assertEqual([r.title for r in SEC.capped(rows, 4)], ["0", "1", "2", "4"])
        self.assertEqual([r.title for r in SEC.capped(rows, 3)], ["1", "2", "4"])
        self.assertEqual([r.title for r in SEC.capped(rows, 2)], ["1", "2"])
        self.assertEqual(SEC.capped([], 3), [])

    def test_the_lists_are_capped_and_say_how_many_there_were(self):
        many = [prog(T - 100000 + 100 * i, T - 100000 + 100 * i + 3000, f"Show {i} Episode 1", 1000 + i) for i in range(SEC.MAX_SHOWS + 40)]
        films = [prog(T - 600000 + 8000 * i, T - 600000 + 8000 * i + 7200, f"Film {i:03d}", 5000 + i) for i in range(70)]
        library = loaded_library(answer(cast(10, many, name="Many"), cast(11, films, name="Films")))
        rows, total = library.shows(T)
        self.assertEqual((len(rows), total), (SEC.MAX_SHOWS, SEC.MAX_SHOWS + 40))
        episodes = [prog(T - 600000 + 2000 * i, T - 600000 + 2000 * i + 1500, f"Long Season 1 Episode {i}", 9000 + i, tv_show_id=77)
                    for i in range(SEC.MAX_EPISODES + 30)]
        late = [prog(T + 1000 * (i + 1), T + 1000 * (i + 1) + 900, f"Long Season 2 Episode {i}", 9500 + i, tv_show_id=77)
                for i in range(30)]
        library = loaded_library(answer(cast(10, episodes + late, name="Long")))
        title, rows, total = library.episodes("77", T, {})
        self.assertEqual(total, SEC.MAX_EPISODES + 60)
        self.assertEqual(len(rows), SEC.MAX_EPISODES)
        self.assertTrue(all(r.playable for r in rows))              # the capped ones are the episodes that could not be played


class SectionLibrary(unittest.TestCase):
    """The index: built once for a version of the file, asked cheaply, let go of."""

    def test_the_index_is_built_once_per_version_of_the_file(self):
        library, reads = SEC.Library(), []
        read = lambda: reads.append(1) or FIXTURE           # noqa: E731
        self.assertFalse(library.loaded)
        self.assertTrue(library.load(("a",), read))
        self.assertTrue(library.load(("a",), read))
        self.assertEqual((len(reads), library.loaded), (1, True))
        self.assertTrue(library.load(("b",), read))
        self.assertEqual(len(reads), 2)
        library.release()
        self.assertEqual((library.loaded, library.key, library.shows(T)), (False, None, None))
        self.assertIsNone(library.films(T, {}))
        self.assertIsNone(library.episodes("x", T, {}))

    def test_a_file_that_cannot_be_read_keeps_the_index_there_is(self):
        library = SEC.Library()
        self.assertFalse(library.load(("a",), lambda: None))     # nothing to show yet
        self.assertFalse(library.loaded)
        self.assertTrue(library.load(("a",), lambda: FIXTURE))
        self.assertTrue(library.load(("b",), lambda: None))      # being rewritten now: the old one is better than none
        self.assertEqual(library.key, ("a",))
        self.assertEqual(library.shows(T)[1], 12)

    def test_without_the_phones_modules_there_is_nothing_to_load(self):
        library = SEC.Library(libs=(None, None))
        self.assertFalse(library.available())
        self.assertFalse(library.load(("a",), lambda: self.fail("read")))
        with mock.patch.object(SEC, "_libs", return_value=(None, ML)):
            self.assertFalse(SEC.Library().available())
        self.assertTrue(SEC.Library().available())

    def test_what_was_found_is_kept_for_a_minute_and_the_counts_never_work_it_out(self):
        counted = []
        real = ps.sections

        class Counting:
            build = staticmethod(real.build)
            films = staticmethod(real.films)
            show = staticmethod(real.show)

            @staticmethod
            def shows(index, ok):
                counted.append(1)
                return real.shows(index, ok)
        library = SEC.Library(libs=(Counting, ML))
        library.load(("a",), lambda: FIXTURE)
        self.assertIsNone(library.counts(T))                  # asked on the UI thread: it only looks, it does not work
        self.assertEqual(counted, [])
        library.shows(T)
        library.shows(T + 30)
        self.assertEqual(len(counted), 1)                     # the second look is the same minute
        self.assertIsNone(library.counts(T))                  # the films were not asked
        library.warm(T)
        self.assertEqual((library.counts(T), len(counted)), ((12, 12), 1))
        self.assertIsNone(library.counts(T + 120))            # a later minute: not known until it is warmed again
        library.shows(T + 120)
        self.assertEqual(len(counted), 2)
        library.release()
        self.assertIsNone(library.counts(T + 120))

    def test_the_clock_decides_what_can_be_watched_so_a_later_minute_asks_again(self):
        library = loaded_library(small_list())
        self.assertEqual(library.films(T, {})[1], 2)
        self.assertEqual(library.films(T + 8 * 86400, {})[1], 0)    # a week later the archive has let them go
        self.assertEqual(library.shows(T + 8 * 86400)[1], 0)


class SectionWindow(WindowCase):
    """The first screen, the lists, and what the keys do on them."""

    def setUp(self):
        super().setUp()
        Fake.now = T
        write_list(FIXTURE)

    def home(self, **kw):
        window = self.open(screen=HOME, **kw)
        self.assertTrue(wait_for(lambda: window.mode == D.DATA))
        return window

    def card(self, window, key):
        window.controls[SECTIONS].selected = SEC.ORDER.index(key)
        window.onClick(SECTIONS)

    def settled(self, window):
        self.assertTrue(wait_for(lambda: window.getProperty("list_msg") != W.tr("Loading…")), "the list is made")

    def go(self, window, key):
        self.card(window, key)
        self.settled(window)
        return window.controls[ITEMS].items

    def labels(self, window):
        return [i.label for i in window.controls[ITEMS].items]

    def play(self, window, position):
        window.controls[ITEMS].selected = position
        Fake.rpc.clear()
        window.onClick(ITEMS)

    def test_it_opens_on_three_cards_with_the_focus_on_the_first_and_no_list_read(self):
        window = self.home()
        self.assertEqual((window.getProperty("screen"), window.focus, window.screen), ("home", SECTIONS, HOME))
        cards = window.controls[SECTIONS].items
        self.assertEqual([c.label for c in cards], [W.tr(n) for n in ("Channels", "Shows and series", "Films")])
        self.assertEqual([c.props["count"] for c in cards], [W.tr("Channels: {n}").format(n=5), "", ""])
        self.assertEqual(window.controls[SECTIONS].selected, 0)
        self.assertEqual(window.getProperty("home_title"), W.tr("What to watch?"))
        for word in ("Open", "Back"):
            self.assertIn(W.tr(word), window.getProperty("hint"))
        self.assertFalse(window.library.loaded)                    # the 5 MB list is read when a list is asked for, not before
        self.assertEqual(Fake.rpc, [])

    def test_the_channels_card_shows_the_channel_screen_and_back_comes_back_to_the_cards(self):
        window = self.home()
        self.card(window, "channels")
        self.assertEqual((window.getProperty("screen"), window.focus), ("channels", ROW))
        self.assertEqual(window.getProperty("hint"), W.hint_line(window.numbered, window.archive_any))   # the channel screen's own keys
        self.press(window, BACK)
        self.assertEqual((window.getProperty("screen"), window.focus, window.closed), ("home", SECTIONS, False))
        self.assertEqual(window.controls[SECTIONS].selected, 0)
        self.press(window, BACK)
        self.assertTrue(window.closed)                            # Back on the first screen leaves

    def test_the_channel_keys_do_nothing_on_the_first_screen_and_on_a_list(self):
        window = self.home()
        self.press(window, 58 + 2)
        self.press(window, 117)
        self.assertEqual((window.getProperty("jump"), window.state["favourites"]), ("", []))
        self.go(window, "films")
        self.press(window, 58 + 2)
        self.press(window, 117)
        self.assertEqual((window.getProperty("jump"), window.state["favourites"], window.screen), ("", [], LIST))

    def test_the_shows_list_is_empty_and_says_loading_until_the_index_is_built(self):
        gate, real = threading.Event(), SEC.Library.load

        def slow(library, key, read):
            gate.wait(3)
            return real(library, key, read)
        window = self.home()
        with mock.patch.object(SEC.Library, "load", slow):
            self.card(window, "shows")
            self.assertEqual((window.getProperty("screen"), window.focus, window.screen), ("list", ITEMS, LIST))
            self.assertEqual((window.getProperty("list_title"), window.getProperty("list_msg")), (W.tr("Shows and series"), W.tr("Loading…")))
            self.assertEqual((window.controls[ITEMS].items, window.getProperty("list_sub")), ([], ""))
            self.assertIn(W.tr("Open"), window.getProperty("hint"))
            gate.set()
            self.settled(window)
        self.assertEqual(len(window.controls[ITEMS].items), 12)
        self.assertEqual((window.getProperty("list_msg"), window.getProperty("list_sub")), ("", W.tr("Shows: {n}").format(n=12)))
        self.assertEqual(window.controls[ITEMS].selected, 0)

    def test_the_shows_are_the_phones_shows_with_their_episodes_counted_and_the_channel_picture(self):
        window = self.home()
        items_ = self.go(window, "shows")
        phone = ps.shows_view(ps.slim(FIXTURE), T)["items"]
        self.assertEqual([i.label for i in items_], [s["title"] for s in phone])
        self.assertEqual([i.props["sub"] for i in items_], [W.tr("Episodes: {n}").format(n=s["episodes"]) for s in phone])
        self.assertTrue(all(i.props["dim"] == "" and i.label2 == "" for i in items_))
        self.assertTrue(all(i.props["initials"] and i.props["plate"] for i in items_))
        self.assertEqual(sum(1 for i in items_ if i.art.get("icon")), sum(1 for s in phone if s["thumb"]))

    def test_a_show_opens_its_episodes_and_ok_plays_the_one_from_its_start_in_the_archive(self):
        window = self.home()
        self.go(window, "shows")
        window.controls[ITEMS].selected = self.labels(window).index("Destination X")
        window.onClick(ITEMS)
        self.settled(window)
        self.assertEqual((window.getProperty("list_title"), window.screen, window.focus), ("Destination X", LIST, ITEMS))
        self.assertEqual(window.getProperty("list_sub"), W.tr("Episodes: {n}").format(n=3))
        items_ = window.controls[ITEMS].items
        self.assertEqual([i.label for i in items_], [W.tr("Episode {n}").format(n=n) for n in (1, 2, 3)])
        self.assertEqual([i.label2 for i in items_], ["", "", W.tr("Soon")])
        self.assertEqual([i.props["dim"] for i in items_], ["", "", "1"])
        self.assertEqual(window.controls[ITEMS].selected, 0)
        phone = ps.show_view(ps.slim(FIXTURE), self.show_id("Destination X"), T)["episodes"][1]
        self.play(window, 1)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"], f"plugin://plugin.video.sweettv/playvid/{phone['cid']}|{phone['epg']}")
        self.assertEqual(ML.url(phone["cid"], phone["epg"], 0), f"plugin://plugin.video.sweettv/playvid/{phone['cid']}|{phone['epg']}")
        self.assertEqual((window.session.cid, window.session.epg), (str(phone["cid"]), str(phone["epg"])))
        self.assertEqual((window.session.start, window.session.stop), (phone["start"], phone["stop"]))
        self.assertIn("Destination X", window.session.title)
        self.assertTrue(wait_for(lambda: self.saved()["last"] == str(phone["cid"])))
        self.assertEqual((window.screen, Fake.seeks), (LIST, []))   # from its first second; the list is still there on coming back

    def show_id(self, title):
        return next(s["id"] for s in ps.shows_view(ps.slim(FIXTURE), T)["items"] if s["title"] == title)

    def test_an_episode_still_to_come_does_not_play_and_says_so(self):
        window = self.home()
        self.go(window, "shows")
        window.controls[ITEMS].selected = self.labels(window).index("Destination X")
        window.onClick(ITEMS)
        self.settled(window)
        self.play(window, 2)
        time.sleep(0.05)
        self.assertEqual((Fake.rpc, window.session, Fake.notes[-1:]), ([], None, [W.tr("This programme has not aired yet.")]))

    def test_an_episode_out_of_the_archive_does_not_play_and_says_so_and_the_cursor_starts_on_what_can_be_watched(self):
        write_list(small_list())
        window = self.home()
        self.go(window, "shows")
        window.onClick(ITEMS)
        self.settled(window)
        self.assertEqual((window.getProperty("list_title"), window.controls[ITEMS].selected), ("Alpha", 1))
        items_ = window.controls[ITEMS].items
        self.assertEqual([i.label2 for i in items_], [W.tr("Not in the archive"), "", W.tr("Soon")])
        self.play(window, 0)
        self.assertEqual((Fake.rpc, Fake.notes[-1:]), ([], [W.tr("This programme is not in the archive.")]))
        self.play(window, 1)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"], "plugin://plugin.video.sweettv/playvid/10|102")
        self.assertEqual(window.session.title, "Alpha  ·  " + W.tr("Episode {n}").format(n=2))

    def test_back_goes_from_the_episodes_to_the_shows_on_the_same_line_then_to_the_cards_then_leaves(self):
        window = self.home()
        self.go(window, "shows")
        position = self.labels(window).index("Реванш")
        window.controls[ITEMS].selected = position
        window.onClick(ITEMS)
        self.settled(window)
        self.assertEqual(window.getProperty("list_title"), "Реванш")
        self.press(window, BACK)
        self.settled(window)
        self.assertEqual((window.getProperty("list_title"), window.controls[ITEMS].selected, window.focus),
                         (W.tr("Shows and series"), position, ITEMS))
        self.assertEqual(len(window.controls[ITEMS].items), 12)
        self.press(window, BACK)
        self.assertEqual((window.getProperty("screen"), window.focus, window.controls[ITEMS].items, window.closed),
                         ("home", SECTIONS, [], False))
        self.assertEqual(window.controls[SECTIONS].selected, 1)       # the cursor stays on the card that was opened
        self.press(window, BACK)
        self.assertTrue(window.closed)

    def test_the_films_are_the_phones_films_and_ok_plays_one_from_its_start(self):
        window = self.home()
        items_ = self.go(window, "films")
        phone = ps.films_view(ps.slim(FIXTURE), T)["items"]
        self.assertEqual((window.getProperty("list_title"), window.getProperty("list_sub")),
                         (W.tr("Films"), W.tr("Films: {n}").format(n=len(phone))))
        self.assertEqual([i.label for i in items_], [f["title"] for f in phone])
        self.assertEqual([i.label2 for i in items_], [W.tr("Airings: {n}").format(n=f["airings"]) if f["airings"] > 1 else "" for f in phone])
        self.assertTrue(all(i.props["dim"] == "" for i in items_))
        position = [f["title"] for f in phone].index("Hugo")
        self.play(window, position)
        self.assertTrue(wait_for(lambda: Fake.rpc))
        film = phone[position]
        self.assertEqual(json.loads(Fake.rpc[-1])["params"]["item"]["file"],
                         f"plugin://plugin.video.sweettv/playvid/{film['cid']}|{film['epg']}")
        self.assertEqual((window.session.title, window.session.start), ("Hugo", film["start"]))
        self.assertEqual(Fake.seeks, [])
        self.assertTrue(wait_for(lambda: self.saved()["last"] == str(film["cid"])))

    def test_when_the_player_stops_the_place_is_kept_like_for_any_archived_programme(self):
        window = self.home()
        self.go(window, "films")
        Fake.playing, Fake.position, Fake.length = True, 900.0, 7200.0
        self.play(window, 0)
        self.assertTrue(wait_for(lambda: window.session is not None and Fake.rpc))
        time.sleep(0.05)
        Fake.playing = False
        self.assertTrue(wait_for(lambda: window.session is None))
        self.assertTrue(wait_for(lambda: self.saved()["resume"]))

    def test_the_counts_on_the_cards_appear_once_the_lists_have_been_made(self):
        window = self.home()
        self.go(window, "shows")
        self.assertTrue(wait_for(lambda: window.library.counts(T)))
        self.press(window, BACK)
        self.assertEqual([c.props["count"] for c in window.controls[SECTIONS].items],
                         [W.tr("Channels: {n}").format(n=5), W.tr("Shows: {n}").format(n=12), W.tr("Films: {n}").format(n=12)])

    def test_no_shows_and_no_films_say_so(self):
        write_list(answer(cast(10, [prog(T - 600, T + 600, "Live only", 201)], name="Ten", catchup=False)))
        window = self.home()
        self.assertEqual(self.go(window, "shows"), [])
        self.assertEqual((window.getProperty("list_msg"), window.getProperty("list_sub")), (W.tr("No shows with episodes in the archive yet."), ""))
        self.press(window, BACK)
        self.assertEqual(self.go(window, "films"), [])
        self.assertEqual(window.getProperty("list_msg"), W.tr("No films in the archive yet."))
        self.assertEqual(window.focus, ITEMS)                          # Back is still there to press
        self.press(window, BACK)
        self.assertEqual((window.screen, window.getProperty("list_msg")), (HOME, ""))

    def test_a_list_that_cannot_be_read_says_so_and_a_show_that_is_gone_says_so(self):
        window = self.home()
        write_list('{"status": "OK", "list": [{"id": 1, "na')
        self.assertEqual(self.go(window, "shows"), [])
        self.assertEqual(window.getProperty("list_msg"), W.tr(sweettv_app.LOAD_FAILED))
        self.press(window, BACK)
        write_list(FIXTURE)
        window._open_list(SEC.EPISODES, "no-such-show", "Gone")
        self.settled(window)
        self.assertEqual((window.getProperty("list_title"), window.getProperty("list_msg")), ("Gone", W.tr("This show has no episodes to show.")))

    def test_without_the_phones_modules_the_lists_say_it_is_not_available(self):
        window = self.home()
        with mock.patch.object(SEC, "_libs", return_value=(None, None)):
            self.assertEqual(self.go(window, "films"), [])
        self.assertEqual(window.getProperty("list_msg"), W.tr("SWEET.TV is not available on this device."))

    def test_a_list_that_fails_to_build_does_not_kill_the_screen(self):
        window = self.home()
        with mock.patch.object(SEC.Library, "shows", side_effect=RuntimeError("boom")):
            self.assertEqual(self.go(window, "shows"), [])
        self.assertEqual((window.getProperty("list_msg"), window.focus), (W.tr(sweettv_app.LOAD_FAILED), ITEMS))
        self.press(window, BACK)
        self.assertEqual(window.screen, HOME)

    def test_a_list_made_for_a_screen_the_person_has_left_is_dropped(self):
        gate, real = threading.Event(), SEC.Library.load

        def slow(library, key, read):
            gate.wait(3)
            return real(library, key, read)
        window = self.home()
        with mock.patch.object(SEC.Library, "load", slow):
            self.card(window, "shows")
            self.press(window, BACK)
            self.assertEqual((window.screen, window.getProperty("list_msg")), (HOME, ""))
            gate.set()
            time.sleep(0.1)
        self.assertEqual((window.screen, window.controls[ITEMS].items, window.getProperty("list_msg")), (HOME, [], ""))

    def test_the_index_is_let_go_a_while_after_the_lists_are_left_and_kept_when_the_person_comes_back(self):
        with mock.patch.object(sweettv_app, "LIBRARY_KEEP", 0.15):
            window = self.home()
            self.go(window, "shows")
            self.assertTrue(window.library.loaded)
            self.press(window, BACK)
            self.assertTrue(window.library.loaded)
            self.card(window, "films")                                # back in a list before the time is up
            self.settled(window)
            time.sleep(0.3)
            self.assertTrue(window.library.loaded)
            self.press(window, BACK)
            self.assertTrue(wait_for(lambda: not window.library.loaded))
            self.assertEqual(window.library.counts(T), None)
            self.go(window, "shows")                                  # and it is built again when it is wanted
            self.assertTrue(window.library.loaded)

    def test_the_same_file_is_read_once_for_the_shows_the_episodes_and_the_films(self):
        window = self.home()
        with mock.patch.object(files, "read_raw", wraps=files.read_raw) as read:
            self.go(window, "shows")
            window.onClick(ITEMS)
            self.settled(window)
            self.press(window, BACK)
            self.settled(window)
            self.press(window, BACK)
            self.go(window, "films")
        self.assertEqual(read.call_count, 1)

    def test_a_new_list_file_is_read_again(self):
        window = self.home()
        self.go(window, "films")
        self.press(window, BACK)
        write_list(small_list())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        self.assertEqual(self.labels_of(window, "films"), ["Hugo", "Solo"])

    def labels_of(self, window, key):
        self.go(window, key)
        return self.labels(window)

    def test_a_new_channel_list_while_a_list_is_open_changes_nothing_on_the_screen(self):
        window = self.home()
        self.go(window, "films")
        before = self.labels(window)
        write_list(small_list())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        window._look()
        self.assertEqual((window.screen, window.getProperty("screen"), window.focus, self.labels(window)), (LIST, "list", ITEMS, before))
        self.press(window, BACK)
        self.assertEqual(window.controls[SECTIONS].selected, 2)

    def test_the_demo_lists_work_and_play_nothing(self):
        window = self.home(demo=True)
        items_ = self.go(window, "films")                           # the demo's guide may have no films: then it says so
        self.assertEqual(window.getProperty("list_msg") == "", bool(items_))
        window._play_row(SEC.Row("", "Film", "", "", "", "Film", cid="10", epg="5", start=T - 100, stop=T + 3000))
        time.sleep(0.05)
        self.assertEqual((Fake.rpc, window.session, Fake.notes[-1:]), ([], None, ["Demo: nothing is played."]))
        self.press(window, BACK)
        self.go(window, "shows")
        self.assertEqual((window.screen, Fake.rpc), (LIST, []))

    def test_closing_the_window_lets_the_index_go(self):
        window = self.home()
        self.go(window, "shows")
        self.assertTrue(window.library.loaded)
        window.stop()
        self.assertFalse(window.library.loaded)


NS = PG.namespace()                                  # "sweettv:main"


class PageValues(unittest.TestCase):
    """sweettv_pages: what is kept on disk, and read back strictly."""

    def setUp(self):
        self.library = loaded_library()

    def good(self, kind=SEC.SHOWS):
        rows, total = self.library.shows(T) if kind == SEC.SHOWS else self.library.films(T, {})
        return PG.to_value("", rows, total)

    def test_the_namespace_is_the_accounts_and_nothing_is_kept_for_one_that_cannot_be_told(self):
        self.assertEqual(NS, "sweettv:main")
        self.assertEqual(PG.namespace("other"), "sweettv:other")
        for bad in (None, "", 7, "a b", "x" * 41, "a:b", "../x"):
            self.assertIsNone(PG.namespace(bad), bad)

    def test_the_keys_are_the_section_and_the_show(self):
        self.assertEqual([PG.key_of(SEC.SHOWS), PG.key_of(SEC.FILMS), PG.key_of(SEC.EPISODES, "242551"), PG.key_of(SEC.EPISODES, "t63a67f2171")],
                         ["shows", "films", "show:242551", "show:t63a67f2171"])
        for sid in ("", "../x", "a b", "t12", "1" * 13, None, 5):
            self.assertIsNone(PG.key_of(SEC.EPISODES, sid), sid)
        self.assertIsNone(PG.key_of("other"))

    def test_a_list_goes_to_json_and_comes_back_the_same(self):
        for kind in (SEC.SHOWS, SEC.FILMS):
            rows, total = self.library.shows(T) if kind == SEC.SHOWS else self.library.films(T, {"553": "/logos/a.png"})
            value = json.loads(json.dumps(PG.to_value("", rows, total)))
            self.assertEqual(PG.from_value(kind, value), ("", rows, total))
        for show in self.library.shows(T)[0]:
            title, rows, total = self.library.episodes(show.key, T, {})
            value = json.loads(json.dumps(PG.to_value(title, rows, total)))
            self.assertEqual(PG.from_value(SEC.EPISODES, value), (title, rows, total))
        self.assertEqual(PG.counts_from_value(json.loads(json.dumps(PG.counts_value(12, 3)))), (12, 3))

    def test_a_page_that_is_not_what_this_screen_wrote_is_a_miss(self):
        good = self.good()
        self.assertIsNotNone(PG.from_value(SEC.SHOWS, good))
        row = list(good["rows"][0])

        def with_row(page=good, row=row, **changes):
            """`page` with one line only: `row` with some fields changed."""
            names = [name for name, _ in PG._ROW]
            return {**page, "rows": [[changes.get(name, value) for name, value in zip(names, row)]]}
        bad = {"not a dict": [], "none": None, "another version": {**good, "v": 2}, "another language": {**good, "lang": "xx"},
               "no rows": {**good, "rows": []}, "rows not a list": {**good, "rows": "x"}, "total below the rows": {**good, "total": 1},
               "total a bool": {**good, "total": True}, "huge total": {**good, "total": 10 ** 9}, "title a number": {**good, "title": 5},
               "missing field": {k: v for k, v in good.items() if k != "total"}, "short row": {**good, "rows": [row[:5]]},
               "row not a list": {**good, "rows": [{"title": "x"}]}, "title not text": with_row(title=5), "empty title": with_row(title=""),
               "id not a show id": with_row(key="../x"), "a show with a programme": with_row(cid="10", epg="5"),
               "playable a string": with_row(playable="yes"), "start a bool": with_row(start=True), "negative start": with_row(start=-1),
               "icon not an address": with_row(icon="javascript:x"), "control character": with_row(title="a\x00b"),
               "too long": with_row(sub="x" * 301), "future but playable": with_row(future=True),
               "too many rows": {**good, "rows": good["rows"] * 40, "total": 10 ** 4}}
        for name, value in bad.items():
            self.assertIsNone(PG.from_value(SEC.SHOWS, value), name)
        films = self.good(SEC.FILMS)
        film = list(films["rows"][0])
        self.assertIsNotNone(PG.from_value(SEC.FILMS, with_row(films, film)))        # the one line is a good page
        self.assertIsNone(PG.from_value(SEC.SHOWS, with_row(films, film)))           # a film is no show
        for name, value in {"a film with a show id": with_row(films, film, key="5"), "ids not numbers": with_row(films, film, cid="1/../2"),
                            "epg missing": with_row(films, film, epg=""), "stop before start": with_row(films, film, start=10, stop=5)}.items():
            self.assertIsNone(PG.from_value(SEC.FILMS, value), name)
        self.assertIsNone(PG.from_value("other", good))
        for value in (None, [], {"v": 1}, {"v": 1, "lang": W.LANG, "shows": -1, "films": 0}, {"v": 1, "lang": W.LANG, "shows": True, "films": 0},
                      {"v": 1, "lang": "xx", "shows": 1, "films": 1}):
            self.assertIsNone(PG.counts_from_value(value), value)

    def test_what_is_kept_is_accepted_by_the_cache_and_holds_no_secret_or_stream(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(page_cache, "DIR", folder):
            for kind in (SEC.SHOWS, SEC.FILMS):
                self.assertTrue(page_cache.put(NS, PG.key_of(kind), self.good(kind)), kind)
            for show in self.library.shows(T)[0]:
                title, rows, total = self.library.episodes(show.key, T, {})
                self.assertTrue(page_cache.put(NS, PG.key_of(SEC.EPISODES, show.key), PG.to_value(title, rows, total)), show.key)
            names = os.listdir(folder)
            self.assertEqual(len(names), 1)
            with open(os.path.join(folder, names[0]), encoding="utf-8") as f:
                text = f.read().lower()
            for word in ("token", "cookie", "password", "bearer", "playvid", "plugin://", "m3u8", "hls-dvr"):
                self.assertNotIn(word, text, word)


class SectionPages(WindowCase):
    """The lists kept on disk (page_cache, "sweettv:main"): shown at once, asked for again when old, never wrong."""
    home, card, settled, go, labels, play = (SectionWindow.__dict__[n] for n in ("home", "card", "settled", "go", "labels", "play"))

    def setUp(self):
        super().setUp()
        Fake.now = T
        write_list(FIXTURE)
        for patch in (mock.patch.object(sweettv_app, "PAGES", True),
                      mock.patch.object(page_cache, "time", types.SimpleNamespace(time=lambda: Fake.now or time.time()))):    # one clock
            patch.start()
            self.addCleanup(patch.stop)

    def kept(self, key):
        return page_cache.get(NS, key, now=Fake.now)

    def gated(self):
        """A Library.load that waits until the test lets it: the list is being asked for again."""
        gate, real = threading.Event(), SEC.Library.load

        def slow(library, key, read):
            gate.wait(3)
            return real(library, key, read)
        patch = mock.patch.object(SEC.Library, "load", slow)
        patch.start()
        self.addCleanup(patch.stop)
        return gate

    def made(self, window):
        self.assertTrue(wait_for(lambda: window.list_loading == 0), "the worker is done")

    def first_launch(self, key="shows"):
        window = self.home()
        self.go(window, key)
        self.assertTrue(wait_for(lambda: self.kept("home")))
        window.stop()

    def changed_list(self):
        write_list(small_list())
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))

    def test_a_list_made_is_kept_and_shows_at_once_in_the_next_launch_without_reading_the_file(self):
        window = self.home()
        first = self.go(window, "shows")
        titles = self.labels(window)
        self.assertEqual(len(first), 12)
        self.assertTrue(wait_for(lambda: self.kept("shows") and self.kept("home")))
        self.assertEqual(self.kept("shows").value["total"], 12)
        window.stop()
        again = self.home()
        self.assertEqual([c.props["count"] for c in again.controls[SECTIONS].items],           # the cards have their numbers at launch
                         [W.tr("Channels: {n}").format(n=5), W.tr("Shows: {n}").format(n=12), W.tr("Films: {n}").format(n=12)])
        with mock.patch.object(files, "read_raw", side_effect=AssertionError("the file is read")):
            self.card(again, "shows")
            self.assertEqual((self.labels(again), again.getProperty("list_msg"), again.focus), (titles, "", ITEMS))   # before any worker
            self.assertEqual((again.list_loading, again.library.loaded, again.getProperty("list_sub")), (0, False, W.tr("Shows: {n}").format(n=12)))
            self.assertEqual(again.getProperty("list_title"), W.tr("Shows and series"))
            time.sleep(0.05)
        self.assertEqual(self.labels(again), titles)

    def test_a_show_page_is_kept_too_and_back_still_goes_to_the_shows_on_the_same_line(self):
        window = self.home()
        self.go(window, "shows")
        position = self.labels(window).index("Реванш")
        window.controls[ITEMS].selected = position
        window.onClick(ITEMS)
        self.settled(window)
        key = PG.key_of(SEC.EPISODES, self.show_id("Реванш"))
        self.assertTrue(wait_for(lambda: self.kept(key)))
        episodes = self.labels(window)
        window.stop()
        again = self.home()
        with mock.patch.object(files, "read_raw", side_effect=AssertionError("the file is read")):
            self.card(again, "shows")
            again.controls[ITEMS].selected = position
            again.onClick(ITEMS)
            self.assertEqual((self.labels(again), again.getProperty("list_title"), again.getProperty("list_msg")), (episodes, "Реванш", ""))
            self.press(again, BACK)
            self.assertEqual((again.getProperty("list_title"), again.controls[ITEMS].selected), (W.tr("Shows and series"), position))

    def show_id(self, title):
        return next(s["id"] for s in ps.shows_view(ps.slim(FIXTURE), T)["items"] if s["title"] == title)

    def test_an_old_page_shows_at_once_and_is_asked_for_again_and_a_changed_list_replaces_it_with_the_cursor_kept(self):
        self.first_launch()
        Fake.now = T + PG.PAGE_TTL + 1
        extra = {**FIXTURE, "list": FIXTURE["list"] + [cast(99, [prog(T - 9000, T - 6300, "Aaa Season 1 Episode 1", 9001, tv_show_id=1234)],
                                                           name="Extra")]}
        write_list(extra)
        os.utime(files.channel_path(), (time.time() + 60, time.time() + 60))
        again = self.home()
        gate = self.gated()
        self.card(again, "shows")
        old = self.labels(again)
        self.assertEqual((len(old), again.getProperty("list_msg"), again.list_loading), (12, "", 1))     # the old page, no Loading card
        again.controls[ITEMS].selected = old.index("Реванш")
        gate.set()
        self.assertTrue(wait_for(lambda: len(self.labels(again)) == 13))
        new = self.labels(again)
        self.assertEqual((new[0], again.controls[ITEMS].selected, again.focus), ("Aaa", new.index("Реванш"), ITEMS))
        self.assertEqual(again.getProperty("list_sub"), W.tr("Shows: {n}").format(n=13))
        self.assertTrue(wait_for(lambda: self.kept("shows").value["total"] == 13))
        self.assertFalse(self.kept("shows").stale)

    def test_an_old_page_that_is_still_right_is_not_drawn_again_and_is_kept_young(self):
        self.first_launch()
        Fake.now = T + PG.PAGE_TTL + 1
        self.assertTrue(self.kept("shows").stale)
        again = self.home()
        gate = self.gated()
        self.card(again, "shows")
        before = again.controls[ITEMS].items
        again.controls[ITEMS].selected = 4
        gate.set()
        self.made(again)
        self.assertIs(again.controls[ITEMS].items, before)
        self.assertEqual(again.controls[ITEMS].selected, 4)
        self.assertTrue(wait_for(lambda: not self.kept("shows").stale))

    def test_an_old_page_stays_when_the_list_cannot_be_made_now(self):
        self.first_launch()
        Fake.now = T + PG.PAGE_TTL + 1
        again = self.home()
        write_list('{"status": "OK", "list": [{"id": 1, "na')
        gate = self.gated()
        self.card(again, "shows")
        before = self.labels(again)
        gate.set()
        self.made(again)
        self.assertEqual((self.labels(again), again.getProperty("list_msg")), (before, ""))
        self.assertEqual(self.kept("shows").value["total"], 12)           # and the page on disk is the one that was good
        self.assertTrue(self.kept("shows").stale)

    def test_a_section_that_is_empty_now_says_so_and_drops_its_page(self):
        self.first_launch("films")
        self.assertIsNotNone(self.kept("films"))
        Fake.now = T + PG.PAGE_TTL + 1
        write_list(answer(cast(10, [prog(T - 600, T + 600, "Live only", 201)], name="Ten", catchup=False)))
        again = self.home()
        gate = self.gated()
        self.card(again, "films")
        self.assertEqual(len(self.labels(again)), 12)
        gate.set()
        self.assertTrue(wait_for(lambda: self.labels(again) == []))
        self.assertEqual((again.getProperty("list_msg"), again.getProperty("list_sub")), (W.tr("No films in the archive yet."), ""))
        self.assertIsNone(self.kept("films"))

    def test_a_list_the_person_has_left_is_not_drawn_but_its_page_is_kept_for_next_time(self):
        self.first_launch()
        Fake.now = T + PG.PAGE_TTL + 1
        self.changed_list()
        again = self.home()
        gate = self.gated()
        self.card(again, "shows")
        self.press(again, BACK)
        gate.set()
        self.made(again)
        self.assertEqual((again.screen, again.controls[ITEMS].items, again.getProperty("list_msg")), (HOME, [], ""))
        self.assertTrue(wait_for(lambda: self.kept("shows").value["total"] == 1))

    def test_a_page_of_the_wrong_shape_is_a_miss_and_says_loading_as_before(self):
        good = PG.to_value("", *loaded_library().shows(T))
        broken = {"a row of the wrong shape": {**good, "rows": [["x"]]}, "another language": {**good, "lang": "xx"},
                  "an id that is not a number": {**good, "rows": [good["rows"][0][:8] + ["x", "y", 0, 0, ""]]},
                  "no rows": {**good, "rows": []}, "not a page": {"entries": [], "more": ""}}
        for name, value in broken.items():
            with self.subTest(name):
                self.assertTrue(page_cache.put(NS, "shows", value, now=T))
                window = self.home()
                gate = self.gated()
                self.card(window, "shows")
                self.assertEqual((window.getProperty("list_msg"), self.labels(window)), (W.tr("Loading…"), []))
                gate.set()
                self.settled(window)
                self.assertEqual(len(self.labels(window)), 12)
                window.stop()
                page_cache.drop(NS)

    def test_another_accounts_pages_are_never_shown(self):
        good = PG.to_value("", *loaded_library().shows(T))
        self.assertTrue(page_cache.put(PG.namespace("other"), "shows", good, now=T))
        window = self.home()
        gate = self.gated()
        self.card(window, "shows")
        self.assertEqual((window.getProperty("list_msg"), self.labels(window)), (W.tr("Loading…"), []))
        gate.set()
        self.settled(window)
        self.assertIsNotNone(page_cache.get(PG.namespace("other"), "shows", now=T))      # and not touched either

    def test_signing_out_drops_the_pages_and_stops_the_start_up_run_and_nothing_is_kept_signed_out(self):
        self.first_launch()
        window = self.home()
        self.assertTrue(self.kept("shows"))
        sign(False)
        window._look()
        self.assertEqual(window.mode, D.SIGNIN)
        self.assertEqual([self.kept(k) for k in ("shows", "films", "home")], [None, None, None])
        self.assertFalse(window.library.loaded)
        self.assertIsNone(window._ns())
        sign(True)
        window._look()
        self.assertEqual(window.mode, D.DATA)
        self.assertEqual(window._ns(), NS)
        self.assertIsNone(self.kept("shows"))                                    # a new account starts with none

    def test_the_services_sign_out_drops_what_this_screen_kept_and_only_that(self):
        self.first_launch()
        page_cache.put("youtube:p1", "s:rec", {"entries": [], "more": ""})
        page_cache.drop_service("sweettv")
        self.assertEqual([self.kept(k) for k in ("shows", "home")], [None, None])
        self.assertIsNotNone(page_cache.get("youtube:p1", "s:rec"))

    def test_the_demo_keeps_and_shows_nothing_from_the_disk(self):
        window = self.home(demo=True)
        self.go(window, "films")
        self.assertEqual((window._ns(), window.warming, os.path.isdir(page_cache.directory())), (None, None, False))

    def warming(self):
        patch = mock.patch.object(prefetch, "warm", side_effect=lambda ns, jobs, **k: REAL_WARM(ns, jobs, **{**k, "pause": 0, "nice": 0}))
        patch.start()
        self.addCleanup(patch.stop)

    def test_at_start_up_the_shows_and_films_are_made_and_kept_and_the_cards_say_how_many(self):
        self.warming()
        with mock.patch.object(sweettv_app, "LIBRARY_KEEP", 0.1):
            window = self.home()
            self.assertTrue(wait_for(lambda: window.warming is not None and window.warming.wait(0.01)), "the run ends")
            handle = window.warming
            self.assertEqual((handle.stored, handle.failed, handle.note), (["shows", "films"], 0, ""))
            self.assertEqual([self.kept(k).value["total"] for k in ("shows", "films")], [12, 12])
            self.assertEqual(self.kept("home").value, PG.counts_value(12, 12))
            self.assertTrue(wait_for(lambda: [c.props["count"] for c in window.controls[SECTIONS].items][1:] ==
                                     [W.tr("Shows: {n}").format(n=12), W.tr("Films: {n}").format(n=12)]))
            self.assertTrue(wait_for(lambda: not window.library.loaded), "nobody is looking at the lists: the index goes")
            self.assertEqual(window.controls[SECTIONS].selected, 0)

    def test_a_page_that_is_fresh_is_not_made_again_and_a_run_stops_when_the_window_closes(self):
        self.warming()
        first = self.home()
        self.assertTrue(wait_for(lambda: first.warming.wait(0.01)))
        first.stop()
        self.assertIsNone(first.warming)
        with mock.patch.object(files, "read_raw", side_effect=AssertionError("the file is read")):
            second = self.home()
            self.assertTrue(wait_for(lambda: second.warming.wait(0.01)))
            self.assertEqual((second.warming.stored, second.warming.skipped), ([], 2))
        gate = self.gated()
        Fake.now = T + PG.PAGE_TTL + 1
        third = self.home()
        handle = third.warming
        third.stop()
        self.assertTrue(handle.cancelled)
        gate.set()
        self.assertTrue(handle.wait(3))

    def test_the_start_up_run_waits_while_a_list_is_being_made_or_a_video_plays(self):
        window = self.home()
        self.assertTrue(window._idle())
        window.list_loading = 1
        self.assertFalse(window._idle())
        window.list_loading = 0
        Fake.playing = True
        self.assertFalse(window._idle())
        Fake.playing = False
        window.stop()
        self.assertFalse(window._idle())

    def test_a_list_that_cannot_be_made_at_start_up_keeps_nothing_and_an_empty_one_drops_its_page(self):
        self.warming()
        write_list(answer(cast(10, [prog(T - 600, T + 600, "Live only", 201)], name="Ten", catchup=False)))
        page_cache.put(NS, "films", PG.to_value("", *loaded_library().films(T, {})), now=T - 10 * PG.PAGE_TTL)
        window = self.home()
        self.assertTrue(wait_for(lambda: window.warming.wait(0.01)))
        self.assertEqual((self.kept("shows"), self.kept("films")), (None, None))
        self.assertEqual(window.warming.stored, [])


class SectionWords(unittest.TestCase):
    """The strings of the new screens: in both languages, and short enough for the places they are drawn in."""

    def msgids(self):
        lib = os.path.join(ADDON, "resources", "lib")
        found = set()
        for name in sorted(os.listdir(lib)):
            if name.startswith("sweettv_") and name.endswith(".py"):
                with open(os.path.join(lib, name), encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and node.args and \
                            (getattr(node.func, "id", None) == "tr" or getattr(node.func, "attr", None) == "tr"):
                        found |= {n.value for n in ast.walk(node.args[0]) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        found |= set(SEC.NAMES.values()) | set(SEC.BLURBS.values()) | set(SEC.COUNTS.values())
        found |= set(sweettv_app.LIST_COUNTS.values()) | {sweettv_app.LOAD_FAILED}
        return found

    def test_every_msgid_has_russian_and_ukrainian_with_the_same_placeholders(self):
        found = self.msgids()
        self.assertGreater(len(found), 20)
        for msgid in sorted(found):
            self.assertIn(msgid, W.TEXT, msgid)
            for lang in ("ru", "uk"):
                text = W.TEXT[msgid].get(lang)
                self.assertTrue(text, (msgid, lang))
                self.assertEqual(sorted(re.findall(r"\{\w*\}", text)), sorted(re.findall(r"\{\w*\}", msgid)), (msgid, lang))
                self.assertNotEqual(text, msgid, (msgid, lang))
        self.assertLessEqual({"What to watch?", "Loading…", "Soon", "Not in the archive", "Airings: {n}", "Season {n}"}, found)

    def test_the_titles_and_the_notes_fit_where_the_skin_draws_them(self):
        for lang in ("ru", "uk"):
            with mock.patch.object(W, "LANG", lang):
                for entry in SEC.home_entries(999, (999, 999)):
                    self.assertLessEqual(textfit.text_px(entry.title, 60), 500, (lang, entry.title))
                    self.assertLessEqual(textfit.text_px(entry.count, 32), 500, (lang, entry.count))
                    self.assertNotIn("…", textfit.wrap_name(entry.desc, 440, 25, 4)[-1], (lang, entry.desc))
                for note in (W.tr("Soon"), W.tr("Not in the archive"), W.tr("Airings: {n}").format(n=99)):
                    self.assertLessEqual(textfit.text_px(note, 22), 210, (lang, note))
                for text in (W.tr("Shows: {n}").format(n=300), W.tr("Films: {n}").format(n=300), W.tr("Episodes: {n}").format(n=200)):
                    self.assertLessEqual(textfit.text_px(text, 25), 400, (lang, text))
                self.assertLessEqual(textfit.text_px(W.tr("Shows and series"), 60), SEC.HEADING_PX)
                for line in (W.section_hint("home"), W.section_hint(SEC.SHOWS), W.section_hint(SEC.FILMS)):
                    self.assertEqual(line.count("[COLOR"), line.count("[/COLOR]"), line)

    def test_the_hint_names_open_for_the_cards_and_the_shows_and_watch_for_what_plays(self):
        self.assertIn(W.tr("Open"), W.section_hint("home"))
        self.assertIn(W.tr("Open"), W.section_hint(SEC.SHOWS))
        for kind in (SEC.EPISODES, SEC.FILMS):
            self.assertIn(W.tr("Watch"), W.section_hint(kind))
            self.assertNotIn(W.tr("Open"), W.section_hint(kind))
        for kind in ("home", SEC.SHOWS, SEC.EPISODES, SEC.FILMS):
            self.assertIn(W.tr("Back"), W.section_hint(kind))


# ---- the skin, the art and the entry points --------------------------------------------------

def count_pictures(node):
    """Pictures a node draws at once: images and buttons (one texture each), not looking inside lists."""
    total = 0
    for child in node:
        if child.tag != "control":
            continue
        kind = child.get("type")
        if kind in ("image", "button"):
            total += 1
        elif kind != "list":
            total += count_pictures(child)
    return total


class Skin(unittest.TestCase):
    def tree(self, name="script-media-stick-sweettv.xml"):
        return ET.parse(os.path.join(SKIN, name)).getroot()

    def control(self, root, control_id):
        return next(c for c in root.iter("control") if c.get("id") == str(control_id))

    def test_well_formed_and_the_controls_the_python_uses_exist(self):
        root = self.tree()
        self.assertEqual(root.tag, "window")
        types_ = {int(c.get("id")): c.get("type") for c in root.iter("control") if c.get("id", "").isdigit()}
        self.assertEqual(types_, {MENU: "list", ROW: "list", ACTIONS: "grouplist", RESUME: "button", GUIDE_BUTTON: "button",
                                  GUIDE: "list", SIGNIN: "button", sweettv_app.RETRY: "button",
                                  sweettv_app.SECTIONS: "list", sweettv_app.ITEMS: "list"})
        row = self.control(root, ROW)
        self.assertEqual((row.findtext("orientation"), self.control(root, MENU).findtext("orientation")), ("horizontal", "vertical"))
        self.assertEqual((row.findtext("onleft"), self.control(root, MENU).findtext("onright")), (str(MENU), str(ROW)))   # left from the first card, right from the menu
        self.assertEqual((self.control(root, ACTIONS).findtext("ondown"), self.control(root, ACTIONS).findtext("onleft")), (str(ROW), str(MENU)))

    def test_every_window_and_item_property_the_xml_reads_is_set_by_the_python(self):
        text = "".join(ET.tostring(self.tree(), encoding="unicode").split())
        window_props = set(re.findall(r"Window\.Property\((\w+)\)", text))
        item_props = set(re.findall(r"ListItem\.Property\((\w+)\)", text))
        channel = demo_catalog().channels[0]
        self.assertLessEqual(item_props, set(V.card_props(channel, NOW)) | {"active", "heading", "when", "kind", "sub", "count", "dim"})
        for name in ("channelList.json",):
            if os.path.exists(os.path.join(TMP, "temp", name)):
                os.remove(os.path.join(TMP, "temp", name))
        seen = set()
        for demo, signed, listing in ((True, True, None), (False, False, None), (False, True, None),
                                      (False, True, {"status": "ERROR", "list": []})):
            sign(signed)
            if listing:
                write_list(listing)
            window = sweettv_app.SweetTV()
            window.setup(demo=demo)
            with mock.patch.object(files, "phone_page", return_value=("http://192.168.1.20/", "/tmp/qr.png")):
                window.onInit()
                try:
                    self.assertTrue(wait_for(lambda: window.looks >= 1))
                    window._prop("jump", "Channel 1")
                    if demo:
                        window.focus = ROW
                        window._guide_show()
                    seen |= set(window._window_props)
                finally:
                    window.stop()
        sign(True)
        self.assertLessEqual(window_props, seen)
        self.assertLessEqual({"guide", "guide_title", "preview_video", "ip", "net"}, seen)

    def test_the_preview_reads_the_row_and_the_heading_reads_the_menu(self):
        text = ET.tostring(self.tree(), encoding="unicode")
        containers = set(re.findall(r"Container\((\d+)\)", text))
        self.assertEqual(containers, {str(MENU), str(ROW)})
        for prop in ("nowrange", "now", "pbar", "desc", "nextrange", "meta", "bg"):
            self.assertIn(f"Container({ROW}).ListItem.Property({prop})", text, prop)
        self.assertIn(f"Container({MENU}).ListItem.Property(heading)", text)

    def test_only_fonts_and_textures_the_launcher_already_has_and_no_animation_but_the_cards_zoom(self):
        fonts = set()
        for name in ("script-media-stick-home.xml", "script-media-stick-remote.xml"):
            fonts |= {f.text for f in self.tree(name).iter("font")}
        root = self.tree()
        self.assertLessEqual({f.text for f in root.iter("font")}, fonts)
        for tag in ("texture", "texturefocus", "texturenofocus"):
            for node in root.iter(tag):
                if "$" not in node.text:
                    self.assertTrue(os.path.exists(os.path.join(MEDIA, node.text)), node.text)
        animations = list(root.iter("animation"))
        self.assertEqual([(a.get("effect"), a.text) for a in animations], [("zoom", "Focus")])         # as the launcher's cards
        self.assertLessEqual(int(animations[0].get("time")), 300)

    def test_the_row_shows_five_cards_and_the_menu_seven_entries(self):
        root = self.tree()
        row = self.control(root, ROW)
        cards = int(row.findtext("width")) // int(row.find("itemlayout").get("width"))
        self.assertEqual(cards, 5)
        menu = self.control(root, MENU)
        self.assertGreaterEqual(int(menu.findtext("height")) // int(menu.find("itemlayout").get("height")), 6)
        for node in row.iter("texture"):
            if "ListItem.Art" in (node.text or ""):
                self.assertEqual(node.get("background"), "true", "logos load in the background")
        self.assertEqual(count_pictures(row.find("itemlayout")), 3)                    # plate, logo, progress bar
        self.assertEqual(count_pictures(row.find("focusedlayout")), 4)                 # and the frame
        self.assertEqual(int(row.findtext("top")) + int(row.findtext("height")), 1020)   # along the bottom like the launcher's
        self.assertEqual(int(row.findtext("left")) + int(row.findtext("width")), 1900)

    def test_the_art_the_screen_needs_is_there_and_small(self):
        names = ["icon-star.png", "sweettv-chip.png"] + [D.bar_name(i, wide) for i in range(D.BAR_STEPS + 1) for wide in (False, True)]
        for name in names:
            path = os.path.join(MEDIA, name)
            self.assertTrue(os.path.exists(path), name)
            self.assertLess(os.path.getsize(path), 4000, name)
        self.assertEqual(len(set(names)), 2 * (D.BAR_STEPS + 1) + 2)
        for n in range(1, sweettv_demo.LOGOS + 1):
            self.assertTrue(os.path.exists(os.path.join(ADDON, "resources", "media", "demo", f"logo-{n}.png")))

    def test_demo_is_marked_on_screen_only_in_the_demo(self):
        root = self.tree()
        parent = {child: node for node in root.iter() for child in node}
        marks = [n for n in root.iter("label") if "demo" in (n.text or "").lower() and "$" not in n.text]
        self.assertEqual([n.text for n in marks], ["DEMO"])      # the one literal "Demo" on the screen
        gates, node = [], parent[marks[0]]
        while node is not None:                                  # and every condition on the way up to it
            if node.findtext("visible"):
                gates.append(node.findtext("visible"))
            node = parent.get(node)
        self.assertEqual(gates, ["!String.IsEmpty(Window.Property(demo))"])
        self.assertEqual(ET.tostring(root, encoding="unicode").count("Window.Property(demo)"), 1)

    def test_ids_are_unique_and_every_picture_exists(self):
        root = self.tree()
        ids = [c.get("id") for c in root.iter("control") if c.get("id")]
        self.assertEqual(len(ids), len(set(ids)))
        for node in root.iter("colordiffuse"):                   # alpha 00 does not hide a picture in this skin: it is white
            self.assertFalse(re.match(r"^00", node.text or ""), node.text)
        for tag in ("texturefocus", "texturenofocus"):
            for node in root.iter(tag):
                self.assertFalse(re.match(r"^00", node.get("colordiffuse", "FF")))
        for tag in ("textcolor", "selectedcolor", "focusedcolor"):
            for node in root.iter(tag):
                self.assertFalse(re.match(r"^00", node.text or ""), node.text)

    def test_a_9_slice_picture_is_never_smaller_than_its_borders(self):
        """Border 40 on a 72 high picture: the halves overlap and a translucent one shows a stripe through the row."""
        root = self.tree()
        sizes = []
        for node in root.iter("control"):
            texture = node.find("texture")
            if node.get("type") == "image" and texture is not None and texture.get("border"):
                sizes.append((texture.text, int(texture.get("border")), node.findtext("width"), node.findtext("height")))
        self.assertGreater(len(sizes), 20)
        for name, border, width, height in sizes:
            self.assertLessEqual(2 * border, int(width), (name, width))
            self.assertLessEqual(2 * border, int(height), (name, height))
        buttons = 0
        for button in (c for c in root.iter("control") if c.get("type") == "button"):
            for node in (button.find("texturefocus"), button.find("texturenofocus")):
                buttons += 1
                self.assertLessEqual(2 * int(node.get("border")), int(button.findtext("height")))
                self.assertLessEqual(2 * int(node.get("border")), int(button.findtext("width")))
        self.assertGreaterEqual(buttons, 8)
        for name, size, border in (("pill-80.png", 80, 40), ("pill.png", 96, 47), ("card-mask.png", 256, 28), ("sweettv-chip.png", 48, 24)):
            from PIL import Image                                # the art itself is not smaller than its borders either
            with Image.open(os.path.join(MEDIA, name)) as image:
                self.assertEqual(image.size, (size, size), name)
                self.assertLessEqual(2 * border, min(image.size))

    def test_the_text_of_a_selected_list_row_has_its_own_colour_and_is_never_white_on_white(self):
        """In a list the selected row takes <selectedcolor>, and the skin's default for it is not ours."""
        root = self.tree()
        labels = 0
        for layout in list(root.iter("itemlayout")) + list(root.iter("focusedlayout")):
            for label in (c for c in layout.iter("control") if c.get("type") == "label"):
                labels += 1
                self.assertIsNotNone(label.find("selectedcolor"), label.findtext("label"))
                self.assertEqual(label.findtext("selectedcolor"), label.findtext("textcolor"))
        self.assertGreater(labels, 12)
        for list_id in (MENU, GUIDE):
            focused = self.control(root, list_id).find("focusedlayout")
            pill = next(c for c in focused.iter("control") if c.get("type") == "image" and "!" not in (c.findtext("visible") or ""))
            self.assertEqual(pill.findtext("colordiffuse"), "FFFFFFFF")
            for label in (c for c in focused.iter("control") if c.get("type") == "label"):
                if "!" not in (label.findtext("visible") or "") and label.findtext("textcolor")[:2] == "99":
                    continue                                    # the dim secondary text of a focused row
                if "!" not in (label.findtext("visible") or ""):
                    self.assertNotEqual(label.findtext("selectedcolor")[2:], "FFFFFF", label.findtext("label"))
        for node in root.iter("control"):
            if node.get("type") == "button":
                self.assertEqual(node.findtext("focusedcolor")[2:], "10141A")        # dark on the white focused pill

    def test_the_menu_pill_is_white_only_with_the_focus_and_dim_otherwise(self):
        focused = self.control(self.tree(), MENU).find("focusedlayout")
        pills = {c.findtext("visible"): c.findtext("colordiffuse") for c in focused.iter("control") if c.get("type") == "image"}
        self.assertEqual(pills, {"Control.HasFocus(100)": "FFFFFFFF", "!Control.HasFocus(100)": "26FFFFFF"})
        frame = [c for c in self.control(self.tree(), ROW).find("focusedlayout").iter("control")
                 if "card-glow" in (c.findtext("texture") or "")]
        self.assertEqual([c.findtext("visible") for c in frame], ["Control.HasFocus(200)"])       # the white frame of the launcher

    def test_the_hint_row_is_text_from_the_python_and_costs_no_picture(self):
        text = ET.tostring(self.tree(), encoding="unicode")
        self.assertIn("Window.Property(hint)", text)
        self.assertNotIn("OK watch", text)

    def test_the_status_and_sign_in_cards_exist_and_the_retry_hides_while_loading(self):
        root = self.tree()
        retry = self.control(root, sweettv_app.RETRY)
        self.assertIn("loading", retry.findtext("visible"))
        self.assertIn("!", retry.findtext("visible"))
        text = ET.tostring(root, encoding="unicode")
        for prop in ("msg_kind", "msg_title", "msg_text", "msg_note", "msg_glyph", "msg_tint", "phone_url", "phone_qr"):
            self.assertIn(f"Window.Property({prop})", text)

    def test_the_guide_replaces_the_menu_the_row_and_the_preview(self):
        root = self.tree()
        data_group = next(c for c in root.find("controls") if "mode),data" in (c.findtext("visible") or "") and c.find("control") is not None
                          and any(x.get("id") == str(MENU) for x in c.iter("control")))
        main, guide = [c for c in data_group if c.tag == "control"]
        self.assertEqual(main.findtext("visible"), "String.IsEmpty(Window.Property(guide))")
        self.assertEqual(guide.findtext("visible"), "!String.IsEmpty(Window.Property(guide))")
        self.assertEqual({MENU, ROW, ACTIONS, RESUME, GUIDE_BUTTON}, {int(c.get("id")) for c in main.iter("control") if c.get("id")})
        self.assertEqual({GUIDE}, {int(c.get("id")) for c in guide.iter("control") if c.get("id")})

    def test_the_pictures_on_screen_stay_within_the_pi_budget(self):
        """Steady state with the channels shown, the worst case: every picture that can be drawn at the same time.
        Pairs that exclude each other are counted once (a logo or its badge, wifi or ethernet, the menu cursor's
        white or dim pill); a card without a logo draws its name and initials as text."""
        root = self.tree()
        top = [c for c in root.find("controls") if c.tag == "control"]
        by_mode = lambda mode: [c for c in top if c.get("type") == "group" and f"mode),{mode}" in (c.findtext("visible") or "")]  # noqa: E731
        backdrop, content = by_mode("data")[0], by_mode("data")[1]
        gradients = [c for c in top if c.get("type") == "image"]
        header = [c for c in top if c.get("type") == "group" and not c.findtext("visible", "").startswith("String.IsEqual")]
        exclusive_backdrop, exclusive_net = 1, 1                       # logo | badge ; wifi | ethernet
        backdrop_pictures = count_pictures(backdrop) - exclusive_backdrop
        header_groups = sum(count_pictures(c) for c in header) - exclusive_net
        main = next(c for c in content if c.tag == "control" and c.findtext("visible") == "String.IsEmpty(Window.Property(guide))")
        menu, row = self.control(root, MENU), self.control(root, ROW)
        cards = int(row.findtext("width")) // int(row.find("itemlayout").get("width"))
        menu_pictures = count_pictures(menu.find("focusedlayout")) - 1 + count_pictures(menu.find("itemlayout"))
        row_pictures = (cards - 1) * count_pictures(row.find("itemlayout")) + count_pictures(row.find("focusedlayout"))
        preview = count_pictures(main)
        self.assertEqual((backdrop_pictures, len(gradients), header_groups, menu_pictures, row_pictures, preview), (2, 2, 5, 2, 16, 6))
        total = backdrop_pictures + len(gradients) + header_groups + menu_pictures + row_pictures + preview
        self.assertLessEqual(total, 34, total)
        self.assertEqual(total, 33)                                    # with the DEMO chip and the number chip showing
        guide_group = next(c for c in content if c.tag == "control" and c is not main)
        guide_state = backdrop_pictures + len(gradients) + header_groups + count_pictures(guide_group) \
            + count_pictures(self.control(root, GUIDE).find("focusedlayout"))
        self.assertLessEqual(guide_state, 34)
        for mode in ("signin", "empty"):
            card = by_mode(mode)[0]
            self.assertLessEqual(len(gradients) + header_groups + count_pictures(card), 34)

    def data_groups(self, root):
        return [c for c in root.find("controls") if c.tag == "control" and c.get("type") == "group"
                and "mode),data" in (c.findtext("visible") or "")]

    def test_the_channel_screen_and_the_two_new_ones_are_gated_by_the_screen_property(self):
        root = self.tree()
        groups = self.data_groups(root)
        gate = lambda screen: f"String.IsEqual(Window.Property(mode),data) + String.IsEqual(Window.Property(screen),{screen})"  # noqa: E731
        self.assertEqual([g.findtext("visible") for g in groups], [gate("channels"), gate("channels"), gate("home"), gate("list")])
        ids = [{int(c.get("id")) for c in g.iter("control") if c.get("id")} for g in groups]
        self.assertEqual(ids[2], {SECTIONS})
        self.assertTrue({ITEMS} <= ids[3])
        self.assertTrue({MENU, ROW} <= ids[1] | ids[0])
        self.assertFalse((ids[2] | ids[3]) & {MENU, ROW, ACTIONS, RESUME, GUIDE_BUTTON, GUIDE})
        text = ET.tostring(root, encoding="unicode")
        for prop in ("screen", "home_title", "list_title", "list_sub", "list_msg"):
            self.assertIn(f"Window.Property({prop})", text)
        for prop in ("desc", "count", "plate", "plate_hi", "sub", "initials", "dim"):
            self.assertIn(f"ListItem.Property({prop})", text)

    def test_the_first_screen_shows_three_cards_and_a_list_shows_six_lines(self):
        root = self.tree()
        cards, lines = self.control(root, SECTIONS), self.control(root, ITEMS)
        self.assertEqual((cards.findtext("orientation"), lines.findtext("orientation")), ("horizontal", "vertical"))
        self.assertEqual(int(cards.findtext("width")) // int(cards.find("itemlayout").get("width")), 3)
        self.assertEqual(int(lines.findtext("height")) // int(lines.find("itemlayout").get("height")), 6)
        self.assertLessEqual(int(cards.findtext("left")) + int(cards.findtext("width")), 1920)
        self.assertLessEqual(int(cards.findtext("top")) + int(cards.findtext("height")), 1080)
        for node in lines.iter("texture"):
            if "ListItem.Art" in (node.text or ""):
                self.assertEqual(node.get("background"), "true", "logos load in the background")

    def test_the_pictures_of_the_first_screen_and_of_the_lists_stay_within_the_pi_budget(self):
        root = self.tree()
        top = [c for c in root.find("controls") if c.tag == "control"]
        gradients = [c for c in top if c.get("type") == "image"]
        header = [c for c in top if c.get("type") == "group" and not c.findtext("visible", "").startswith("String.IsEqual")]
        header_groups = sum(count_pictures(c) for c in header) - 1               # wifi | ethernet
        for list_id in (SECTIONS, ITEMS):
            group = next(g for g in self.data_groups(root) if any(c.get("id") == str(list_id) for c in g.iter("control")))
            listing = self.control(root, list_id)
            vertical = listing.findtext("orientation") == "vertical"
            shown = int(listing.findtext("height" if vertical else "width")) // int(listing.find("itemlayout").get("height" if vertical else "width"))
            total = len(gradients) + header_groups + count_pictures(group) + (shown - 1) * count_pictures(listing.find("itemlayout")) \
                + count_pictures(listing.find("focusedlayout"))
            self.assertLessEqual(total, 34, (list_id, total))

    def test_no_character_the_tv_font_cannot_draw(self):
        """The skin's font has no emoji and no arrows. Everything the screen can say (the XML, the Python that makes the
        texts, the demo's words) uses ASCII, the middle dot, the en dash, the ellipsis and Cyrillic."""
        allowed = lambda c: ord(c) < 128 or c in "·–…" or 0x400 <= ord(c) <= 0x4FF  # noqa: E731
        lib = os.path.join(ADDON, "resources", "lib")
        paths = [XML, os.path.join(ROOT, "tools", "make-sweettv-art.py")] + \
            [os.path.join(lib, n) for n in sorted(os.listdir(lib)) if n.startswith("sweettv_") and n.endswith(".py")]
        for path in paths:
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    bad = [c for c in line if not allowed(c)]
                    self.assertEqual(bad, [], f"{os.path.basename(path)}:{number}")
        texts = []
        for name in ("Aurora News 24", "Cinema Nova"):
            channel = next(c for c in demo_catalog().channels if c.name == name)
            texts += list(V.card_props(channel, NOW).values()) + [r.when for r in V.guide_rows(channel, NOW)]
        texts += [V.resume_label({"start": NOW, "pos": 90}), W.hint_line(True, True), V.category_heading("News", 3)]
        for text in texts:
            self.assertEqual([c for c in text if not allowed(c)], [], text)


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
