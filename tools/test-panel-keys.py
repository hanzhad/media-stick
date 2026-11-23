#!/usr/bin/env python3
"""Offline test of the phone remote's arrow keys in the player (no Kodi, no device):
python3 tools/test-panel-keys.py

In Kodi's bare fullscreen video the arrows sent as Input.ExecuteAction "left" etc. do nothing, so
the panel sends the player's own actions there (and select as the OSD); with the OSD or a dialog
up, and in every other window, the buttons go out as they were."""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

loader = importlib.machinery.SourceFileLoader("panel_under_test", PANEL)
spec = importlib.util.spec_from_loader(loader.name, loader)
panel = importlib.util.module_from_spec(spec)
loader.exec_module(panel)

PLAYER = {"left": "stepback", "right": "stepforward", "up": "chapterorbigstepforward",
          "down": "chapterorbigstepback", "select": "osd"}
BUTTONS = ["up", "down", "left", "right", "select", "back", "contextmenu", "info", "playpause",
           "stop", "volumeup", "volumedown", "mute", "fastforward", "rewind", "osd", "skipnext",
           "skipprevious", "fullscreen"]


def booleans(**on):
    """Kodi's answer to PLAYER_BOOLS: everything false except the names in `on`
    (win_fullscreenvideo=True ... ; the dots of Kodi's names are written as underscores)."""
    out = {k: False for k in panel.PLAYER_BOOLS}
    for k, v in on.items():
        name = {"fullscreenvideo": "Window.IsActive(fullscreenvideo)",
                "modal": "System.HasModalDialog"}.get(k) or "Window.IsActive(%s)" % k
        assert name in out, name
        out[name] = v
    return out


class FakeKodi:
    def __init__(self):
        self.calls, self.flags, self.fail = [], booleans(), None

    def __call__(self, method, params=None, timeout=3):
        if method.startswith("Player."):
            return []
        if method in ("GUI.GetProperties", "XBMC.GetInfoLabels"):
            return {}
        self.calls.append((method, params))
        if method == "XBMC.GetInfoBooleans":
            if self.fail:
                raise self.fail
            return self.flags
        return "OK"

    def sent(self):
        return [p["action"] for m, p in self.calls if m == "Input.ExecuteAction"]


class Mapping(unittest.TestCase):
    def test_bare_fullscreen_video_gets_the_players_actions(self):
        for a, want in PLAYER.items():
            self.assertEqual(panel.player_action(a, booleans(fullscreenvideo=True)), want, a)

    def test_every_other_button_stays_in_the_player(self):
        for a in set(BUTTONS) - set(PLAYER):
            self.assertEqual(panel.player_action(a, booleans(fullscreenvideo=True)), a, a)

    def test_outside_the_player_nothing_changes(self):
        for a in PLAYER:
            self.assertEqual(panel.player_action(a, booleans()), a, a)

    def test_the_osd_and_every_dialog_over_the_video_keep_the_move_actions(self):
        over = ["modal"] + list(panel.PLAYER_DIALOGS)
        self.assertIn("videoosd", over)
        for d in over:
            for a in PLAYER:
                self.assertEqual(panel.player_action(a, booleans(fullscreenvideo=True, **{d: True})), a, (d, a))

    def test_a_reply_that_is_not_a_full_answer_changes_nothing(self):
        for bad in (None, "OK", [], {}, {"Window.IsActive(fullscreenvideo)": True}):
            self.assertEqual(panel.player_action("left", bad), "left", bad)

    def test_the_names_asked_are_kodis_and_all_there(self):
        self.assertEqual(panel.PLAYER_BOOLS[0], "Window.IsActive(fullscreenvideo)")
        self.assertIn("System.HasModalDialog", panel.PLAYER_BOOLS)
        self.assertIn("Window.IsActive(videoosd)", panel.PLAYER_BOOLS)
        self.assertEqual(len(set(panel.PLAYER_BOOLS)), len(panel.PLAYER_BOOLS))

    def test_the_players_actions_are_buttons_the_panel_knows_by_kodis_names(self):
        # sent as Input.ExecuteAction names: lower case, no spaces
        for v in PLAYER.values():
            self.assertEqual(v, v.lower().replace(" ", ""))


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kodi = FakeKodi()
        panel.kodi = cls.kodi
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.kodi.calls.clear()
        self.kodi.flags, self.kodi.fail = booleans(), None
        panel.web_app_on = lambda: False

    def key(self, a):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/key", json.dumps({"action": a}),
                  {"Host": "localhost:%d" % self.port, "X-Panel": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_in_the_player_the_arrows_go_out_as_player_actions(self):
        self.kodi.flags = booleans(fullscreenvideo=True)
        for a, want in PLAYER.items():
            self.kodi.calls.clear()
            self.assertEqual(self.key(a), 200)
            self.assertEqual(self.kodi.sent(), [want], a)

    def test_elsewhere_and_over_the_osd_they_go_out_as_they_are(self):
        for flags in (booleans(), booleans(fullscreenvideo=True, videoosd=True)):
            self.kodi.flags = flags
            for a in PLAYER:
                self.kodi.calls.clear()
                self.assertEqual(self.key(a), 200)
                self.assertEqual(self.kodi.sent(), [a], a)

    def test_other_buttons_ask_nothing_extra(self):
        self.kodi.flags = booleans(fullscreenvideo=True)
        for a in ("back", "playpause", "osd", "volumeup"):
            self.kodi.calls.clear()
            self.assertEqual(self.key(a), 200)
            self.assertEqual([m for m, _ in self.kodi.calls], ["Input.ExecuteAction"], a)
            self.assertEqual(self.kodi.sent(), [a])

    def test_home_stays_a_window_switch(self):
        self.kodi.flags = booleans(fullscreenvideo=True)
        self.assertEqual(self.key("home"), 200)
        self.assertEqual(self.kodi.calls, [("GUI.ActivateWindow", {"window": "home"})])

    def test_when_kodi_cannot_answer_the_question_the_button_goes_as_it_is(self):
        self.kodi.fail = ConnectionResetError("gone")
        self.assertEqual(self.key("left"), 200)
        self.assertEqual(self.kodi.sent(), ["left"])

    def test_unknown_actions_are_still_refused(self):
        self.assertEqual(self.key("stepback"), 400)


if __name__ == "__main__":
    unittest.main(verbosity=1)
