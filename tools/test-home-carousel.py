#!/usr/bin/env python3
"""Offline test of the home carousel helpers (no Kodi needed): python3 tools/test-home-carousel.py"""
import json
import os
import sys
import tempfile
import types
import unittest

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "device", "kodi-addons", "script.media-stick.home")
TMP = tempfile.mkdtemp()
calls = []

xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: calls.append(cmd)
xbmc.executeJSONRPC = lambda req: "{}"
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: TMP + "/"
xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.WindowXMLDialog = type("WindowXMLDialog", (), {})
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui)
sys.path.insert(0, ADDON)

from resources.lib import apps, remote  # noqa: E402


def recent_ids():
    return set(apps.load_recent())


class Carousel(unittest.TestCase):
    def setUp(self):
        calls.clear()
        try:
            os.unlink(apps._recent_path())
        except OSError:
            pass

    def ids(self, n):
        return [apps.App(f"app{i}", f"App {i}", "") for i in range(n)]

    def test_card_first_and_index_math(self):
        for n in (0, 1, 2, 12):
            items = apps.carousel(self.ids(n))
            self.assertEqual(items[0].id, apps.CARD_ID)
            self.assertEqual(len(items), n + 1)
            index = apps.first_app_index(len(items) - 1)
            self.assertEqual(index, 1 if n else 0)
            if n:
                self.assertEqual(items[index].id, "app0")      # the most recently used app

    def test_card_never_recorded_or_launched(self):
        apps.record(apps.CARD_ID)
        apps.record("")
        self.assertEqual(recent_ids(), set())
        self.assertFalse(os.path.exists(apps._recent_path()))
        apps.launch(apps.CARD_ID)
        self.assertEqual(calls, [])
        self.assertEqual(recent_ids(), set())

    def test_launch_moves_apps_not_the_card(self):
        everything = self.ids(3)
        apps.launch("app2")
        self.assertEqual(calls, ["RunAddon(app2)"])
        items = apps.carousel(apps.order(everything, apps.load_recent()))
        self.assertEqual([a.id for a in items], [apps.CARD_ID, "app2", "app0", "app1"])
        self.assertEqual(items[apps.first_app_index(3)].id, "app2")
        self.assertNotIn(apps.CARD_ID, recent_ids())
        with open(apps._recent_path()) as f:
            self.assertNotIn(apps.CARD_ID, json.load(f))

    def test_card_in_input_is_not_duplicated(self):
        items = apps.carousel([apps.CARD] + self.ids(1))
        self.assertEqual([a.id for a in items], [apps.CARD_ID, "app0"])


class PageUrl(unittest.TestCase):
    def url(self, ip, panel=None):
        remote.STATE = tempfile.mkdtemp()
        if panel is not None:
            with open(os.path.join(remote.STATE, "panel-url"), "w") as f:
                f.write(panel + "\n")
        return remote.page_url(ip)

    def test_urls(self):
        self.assertEqual(self.url("10.0.0.5"), "http://10.0.0.5/")
        self.assertEqual(self.url("10.0.0.5", "https://tv.example.org/"), "https://tv.example.org/")
        self.assertEqual(self.url("10.0.0.5", "http://other/"), "http://10.0.0.5/")
        self.assertEqual(self.url("", "https://tv.example.org/"), "")


if __name__ == "__main__":
    unittest.main()
