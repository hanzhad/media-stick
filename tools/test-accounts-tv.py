#!/usr/bin/env python3
"""Offline test of the TV side of sign-in and accounts (no Kodi, no device): python3 tools/test-accounts-tv.py

Stubs xbmc, xbmcgui, xbmcaddon and xbmcvfs; the sign-in library is the real one on a temp directory."""
import json
import os
import re
import sys
import tempfile
import threading
import time
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
SKIN = os.path.join(ADDON, "resources", "skins", "default", "1080i")
MEDIA = os.path.join(ADDON, "resources", "skins", "default", "media")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")


class Fake:
    """What the stubbed Kodi shows and does, one place for every test to look at and set."""
    builtins, notes = [], []
    enabled = True
    top = 0                       # the topmost dialog id
    typed = ""                    # what the keyboard dialog returns
    opened = 0                    # how many sign-in windows were opened
    home = {}                     # properties of the Home window
    asked = []                    # the yes/no questions put to the person: (heading, message, nolabel, yeslabel)
    sure = False                  # what they answer


xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: Fake.builtins.append(cmd)
xbmc.executeJSONRPC = lambda req: "{}"
xbmc.getCondVisibility = lambda cond: Fake.enabled
xbmc.sleep = lambda ms: None
xbmc.getIPAddress = lambda: ""
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: TMP + "/"
xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = lambda *a: types.SimpleNamespace(getAddonInfo=lambda key: ADDON)


class Control:
    """A list or a chip slot of the stubbed window: remembers what it was given."""

    def __init__(self):
        self.items, self.selected, self.position, self.width = [], -1, None, None

    def reset(self):
        self.items = []

    def addItems(self, items):
        self.items += list(items)

    def selectItem(self, n):
        self.selected = n

    def setPosition(self, x, y):
        self.position = (x, y)

    def setWidth(self, w):
        self.width = w


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.props = label, {}

    def setProperty(self, key, value):
        self.props[key] = value


class Window:
    def __init__(self, *a):
        self._props = {}
        self.controls = {}

    def getControl(self, control_id):
        return self.controls.setdefault(control_id, Control())

    def setProperty(self, key, value):
        self._props[key] = value

    def getProperty(self, key):
        return self._props.get(key, "")

    def setFocusId(self, control_id):
        self.focus = control_id

    def close(self):
        self.closed = True

    def onAction(self, action):
        pass


class WindowXMLDialog(Window):
    def doModal(self):
        """Opens like Kodi (becomes the topmost dialog, onInit), then waits until closed."""
        Fake.opened += 1
        self.closed = False
        Fake.top = 13000 + Fake.opened
        self.onInit()
        end = time.monotonic() + 8
        while not self.closed and time.monotonic() < end:
            time.sleep(0.005)
        self.closed = True


class HomeWindow(Window):
    def __init__(self, *a):
        self._props = Fake.home


class Dialog:
    def input(self, heading, *a, **k):
        return Fake.typed

    def notification(self, heading, text, *a, **k):
        Fake.notes.append(text)

    def yesno(self, heading, message, nolabel="", yeslabel="", autoclose=0, defaultbutton=0):
        Fake.asked.append((heading, message, nolabel, yeslabel))
        return Fake.sure


xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.WindowXMLDialog = WindowXMLDialog
xbmcgui.WindowXML = Window
xbmcgui.Window = HomeWindow
xbmcgui.Dialog = Dialog
xbmcgui.ListItem = ListItem
xbmcgui.NOTIFICATION_INFO = "info"
xbmcgui.getCurrentWindowDialogId = lambda: Fake.top
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui, xbmcaddon=xbmcaddon)
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

from resources.lib import accounts, accounts_screen, apps, launcher, profiles, remote, signin, store, ui  # noqa: E402

lib = store.lib


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def prof(uid, name, tokens=4, current=False):
    return {"id": str(uid), "name": name, "current": current, "tokens": tokens, "signed_in": tokens > 0}


def acct(service, profile_list=(), signed_in=False, state=None):
    return {"service": service, "name": service, "profiles": list(profile_list), "signed_in": signed_in, "signin": state}


YT, SW = "plugin.video.youtube", "plugin.video.sweettv"


def waiting(code="ABC-DEF", step=2, steps=4, updated=1000, url="https://www.youtube.com/activate"):
    return {"service": "youtube", "state": "waiting", "code": code, "step": step, "steps": steps, "updated": updated,
            "url": url, "link": f"{url}?user_code={code}"}


def ended(kind, updated=1000):
    return {"service": "youtube", "state": kind, "step": 1, "steps": 1, "updated": updated}


class Decision(unittest.TestCase):
    def test_which_screen_for_which_accounts(self):
        two = [prof(0, "Default", 4, True), prof(1, "Anna", 0)]
        one_in, one_out = [prof(0, "Default", 4, True)], [prof(0, "Default", 0, True)]
        cases = [
            (SW, [acct("sweettv", signed_in=False)], ("sweettv", accounts.SIGNIN)),
            (SW, [acct("sweettv", signed_in=True)], ("sweettv", accounts.LAUNCH)),
            (YT, [acct("youtube", two, True)], ("youtube", accounts.PICK)),
            (YT, [acct("youtube", one_in, True)], ("youtube", accounts.LAUNCH)),
            (YT, [acct("youtube", one_out, False)], ("youtube", accounts.LAUNCH)),     # anonymous YouTube works
            (YT, [acct("youtube", [], False)], ("youtube", accounts.LAUNCH)),
            ("webapp:netflix", [acct("youtube", two, True)], (None, accounts.LAUNCH)),
            ("plugin.video.other", [acct("sweettv")], (None, accounts.LAUNCH)),
            (YT, [], (None, accounts.LAUNCH)),
        ]
        for app_id, accts, want in cases:
            self.assertEqual(accounts.plan(app_id, accts), want, app_id)

    def test_after_the_pick(self):
        self.assertEqual(accounts.after_pick(prof(1, "A", 4)), accounts.LAUNCH)
        self.assertEqual(accounts.after_pick(prof(1, "A", 0)), accounts.SIGNIN_OPTIONAL)
        self.assertEqual(accounts.after_pick(prof(1, "A", 2)), accounts.LAUNCH)      # partly signed in counts as in


class Launching(unittest.TestCase):
    def setUp(self):
        Fake.builtins.clear()
        Fake.notes.clear()
        Fake.enabled = True

    def run_launch(self, app_id, accts, **patches):
        with mock.patch.object(lib, "accounts", return_value=accts), \
                mock.patch.object(apps, "launch") as launch, \
                mock.patch.object(accounts, "signin_service", **patches.get("signin", {"return_value": "done"})) as sign, \
                mock.patch.object(accounts, "choose_profile", **patches.get("choose", {"return_value": None})) as choose:
            accounts.launch_app(app_id)
        return launch, sign, choose

    def test_sweettv_signed_out_signs_in_then_launches_only_when_it_worked(self):
        accts = [acct("sweettv")]
        launch, sign, _ = self.run_launch(SW, accts)
        sign.assert_called_once_with("sweettv")
        launch.assert_called_once_with(SW)
        for result in ("failed", "cancelled", "gone", "closed", "shown", "missing", "busy"):
            launch, _, _ = self.run_launch(SW, accts, signin={"return_value": result})
            launch.assert_not_called()

    def test_signed_in_and_other_apps_launch_without_any_screen(self):
        for app_id, accts in ((SW, [acct("sweettv", signed_in=True)]), ("webapp:netflix", [acct("sweettv")]),
                              (YT, [acct("youtube", [prof(0, "D", 4, True)], True)])):
            launch, sign, choose = self.run_launch(app_id, accts)
            launch.assert_called_once_with(app_id)
            sign.assert_not_called()
            choose.assert_not_called()

    def test_other_apps_read_no_account_file_at_all(self):
        with mock.patch.object(lib, "accounts") as read, mock.patch.object(apps, "launch") as launch:
            accounts.launch_app("webapp:netflix")
            accounts.launch_app("plugin.video.other")
        read.assert_not_called()
        self.assertEqual(launch.call_count, 2)

    def test_youtube_with_several_profiles_asks_who_is_watching(self):
        accts = [acct("youtube", [prof(0, "D", 4, True), prof(1, "Anna", 0)], True)]
        launch, sign, choose = self.run_launch(YT, accts, choose={"return_value": prof(0, "D", 4, True)})
        choose.assert_called_once_with()
        sign.assert_not_called()
        launch.assert_called_once_with(YT)
        launch, sign, _ = self.run_launch(YT, accts, choose={"return_value": None})     # backed out
        launch.assert_not_called()

    def test_a_profile_without_account_gets_the_sign_in_with_a_way_past_it(self):
        accts = [acct("youtube", [prof(0, "D", 4, True), prof(1, "Anna", 0)], True)]
        for result, launched in (("done", True), ("skipped", True), ("cancelled", False), ("failed", False)):
            launch, sign, _ = self.run_launch(YT, accts, choose={"return_value": prof(1, "Anna", 0, True)},
                                              signin={"return_value": result})
            sign.assert_called_once_with("youtube", allow_skip=True)
            self.assertEqual(launch.called, launched, result)

    def test_any_exception_is_a_plain_launch(self):
        with mock.patch.object(lib, "accounts", side_effect=OSError("boom")), mock.patch.object(apps, "launch") as launch:
            accounts.launch_app(YT)
        launch.assert_called_once_with(YT)
        with mock.patch.object(accounts, "launch_app", side_effect=ImportError("no lib")), \
                mock.patch.object(apps, "launch") as launch:
            launcher.Launcher._launch(SW)                  # the carousel's own guard, in case even the import fails
        launch.assert_called_once_with(SW)

    def test_the_picker_flow_switches_adds_and_goes_back(self):
        known = [prof(0, "D", 4, True), prof(1, "Anna", 0)]
        with mock.patch.object(lib, "youtube_accounts", return_value=known), \
                mock.patch.object(profiles, "pick", side_effect=["1"]), \
                mock.patch.object(accounts, "switch_profile", return_value=True) as switch:
            self.assertEqual(accounts.choose_profile()["name"], "Anna")
            switch.assert_called_once_with("1")
        with mock.patch.object(lib, "youtube_accounts", return_value=known), \
                mock.patch.object(profiles, "pick", side_effect=["0"]), \
                mock.patch.object(accounts, "switch_profile") as switch:     # already the current one
            self.assertEqual(accounts.choose_profile()["id"], "0")
            switch.assert_not_called()
        # Add account: no name typed goes back to the cards; a name adds and returns the new current profile
        added = [prof(0, "D", 4), prof(2, "Boris", 0, True)]
        with mock.patch.object(lib, "youtube_accounts", return_value=known), \
                mock.patch.object(profiles, "pick", side_effect=[profiles.ADD_ID, profiles.ADD_ID, None]), \
                mock.patch.object(accounts, "ask_name", side_effect=["", "Boris"]), \
                mock.patch.object(accounts, "add_profile", return_value=True) as add, \
                mock.patch.object(accounts, "current_profile", return_value=added[1]):
            self.assertEqual(accounts.choose_profile()["id"], "2")
            add.assert_called_once_with("Boris")
        with mock.patch.object(lib, "youtube_accounts", return_value=known), \
                mock.patch.object(profiles, "pick", return_value=None):
            self.assertIsNone(accounts.choose_profile())
        with mock.patch.object(lib, "youtube_accounts", return_value=known), \
                mock.patch.object(profiles, "pick", return_value="1"), \
                mock.patch.object(accounts, "switch_profile", return_value=False):
            self.assertIsNone(accounts.choose_profile())        # a switch that did not happen must not sign in the wrong one


class Arguments(unittest.TestCase):
    def test_good_actions(self):
        self.assertEqual(accounts.parse(["signin", "youtube"]), ("signin", "youtube", ""))
        self.assertEqual(accounts.parse(["signin", "sweettv"]), ("signin", "sweettv", ""))
        self.assertEqual(accounts.parse(["signout", "youtube"]), ("signout", "youtube", ""))
        self.assertEqual(accounts.parse(["switch", "youtube", "12"]), ("switch", "youtube", "12"))
        self.assertEqual(accounts.parse(["add", "youtube", "Anna"]), ("add", "youtube", "Anna"))
        self.assertEqual(accounts.parse(["add", "youtube", "Anna", "Maria"]), ("add", "youtube", "Anna Maria"))
        self.assertEqual(accounts.parse(["add", "youtube", "  Zoë  O'Neil-2 "]), ("add", "youtube", "Zoë O'Neil-2"))
        self.assertEqual(accounts.parse(["add", "youtube", "Аня"]).arg, "Аня")

    def test_bad_actions_are_refused(self):
        bad = [[], [""], ["launch", "youtube"], ["signin"], ["signin", "netflix"], ["signin", "youtube", "x"],
               ["signin", "YouTube"], ["signin", "../youtube"], ["signout", "plugin.video.youtube"],
               ["switch", "sweettv", "1"], ["switch", "youtube"], ["switch", "youtube", "abc"],
               ["switch", "youtube", "-1"], ["switch", "youtube", "1.5"], ["switch", "youtube", "1234567"],
               ["switch", "youtube", "1)"], ["switch", "youtube", "١"], ["switch", "youtube", "1", "2"],
               ["add", "sweettv", "Anna"], ["add", "youtube"], ["add", "youtube", ""], ["add", "youtube", "   "],
               ["add", "youtube", "A" * 25], ["add", "youtube", "a&ms_user=0"], ["add", "youtube", "a,b"],
               ["add", "youtube", "a)b"], ["add", "youtube", "a=b"], ["add", "youtube", "a%20b"],
               ["add", "youtube", "$INFO[System.Time]"], ["add", "youtube", "a\u0000b"], ["add", "youtube", "..."],
               ["add", "youtube", "a;rm"], ["add", "youtube", "a/b"], ["add", "youtube", "a" * 20, "b" * 20]]
        for args in bad:
            with self.assertRaises(ValueError, msg=repr(args)):
                accounts.parse(args)

    def test_a_bad_call_does_nothing_and_never_raises(self):
        Fake.builtins.clear()
        with mock.patch.object(accounts, "perform") as perform:
            self.assertFalse(accounts.main(["switch", "youtube", "1;Quit"]))
            perform.assert_not_called()
        with mock.patch.object(accounts, "perform", side_effect=RuntimeError("x")):
            self.assertFalse(accounts.main(["signin", "youtube"]))
        self.assertEqual(Fake.builtins, [])

    def test_the_commands_sent_to_the_add_ons(self):
        Fake.builtins.clear()
        Fake.enabled = True
        with mock.patch.object(accounts, "wait_for", return_value=True), \
                mock.patch.object(lib, "youtube_accounts", return_value=[]):
            accounts.perform(accounts.parse(["switch", "youtube", "3"]))
            accounts.perform(accounts.parse(["add", "youtube", "Zoë O'Neil"]))
        accounts.perform(accounts.parse(["signout", "youtube"]))
        accounts.perform(accounts.parse(["signout", "sweettv"]))
        self.assertEqual(Fake.builtins, [
            "RunScript(plugin.video.youtube,users/switch?ms_user=3)",
            "RunScript(plugin.video.youtube,users/add?ms_name=Zo%C3%AB%20O%27Neil&ms_switch=1)",
            "RunPlugin(plugin://plugin.video.youtube/sign/out/?confirmed=true)",
            "RunPlugin(plugin://plugin.video.sweettv/logout)"])

    def test_nothing_is_sent_to_an_add_on_that_is_not_there(self):
        Fake.builtins.clear()
        Fake.enabled = False
        try:
            for args in (["signin", "youtube"], ["signout", "sweettv"], ["switch", "youtube", "1"]):
                self.assertFalse(accounts.perform(accounts.parse(args)) in (True, "done"))
        finally:
            Fake.enabled = True
        self.assertEqual(Fake.builtins, [])

    def test_names_are_cleaned(self):
        self.assertEqual(accounts.clean_name(" Anna \n Maria "), "Anna Maria")
        self.assertEqual(accounts.clean_name(None), "")
        self.assertEqual(accounts.clean_name("x" * 24), "x" * 24)
        self.assertEqual(accounts.clean_name("x" * 25), "")


class SigninStart(unittest.TestCase):
    def setUp(self):
        Fake.builtins.clear()
        Fake.notes.clear()
        Fake.enabled = True
        Fake.home.clear()
        lib.begin("youtube")
        lib.begin("sweettv")

    def test_starts_the_add_on_and_shows_the_screen(self):
        with mock.patch.object(signin, "run", return_value="done") as run:
            self.assertEqual(accounts.signin_service("sweettv"), "done")
        run.assert_called_once_with("sweettv", False, False)
        self.assertEqual(Fake.builtins, ["RunPlugin(plugin://plugin.video.sweettv/login)"])

    def test_a_sign_in_that_is_already_waiting_is_shown_not_started_again(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        with mock.patch.object(signin, "run", return_value="done") as run:
            accounts.signin_service("youtube")
        run.assert_called_once_with("youtube", True, False)
        self.assertEqual(Fake.builtins, [])

    def test_a_screen_that_is_up_is_not_opened_twice_and_another_service_waits(self):
        signin.mark_showing("youtube", time.time())
        with mock.patch.object(signin, "run") as run:
            self.assertEqual(accounts.signin_service("youtube"), "shown")
            self.assertEqual(accounts.signin_service("sweettv"), "busy")
        run.assert_not_called()
        self.assertEqual(Fake.builtins, [])
        self.assertTrue(Fake.notes)
        signin.mark_showing("youtube", time.time() - 60)        # a screen that stopped refreshing is gone
        with mock.patch.object(signin, "run", return_value="cancelled") as run:
            accounts.signin_service("youtube")
        run.assert_called_once()

    def test_the_showing_property(self):
        now = 1000
        self.assertEqual(signin.parse_showing("youtube:1000", now), "youtube")
        self.assertEqual(signin.parse_showing("youtube:990", now), "")
        for junk in ("", None, "youtube", "youtube:x", "netflix:1000", ":1000"):
            self.assertEqual(signin.parse_showing(junk, now), "", junk)
        self.assertTrue(signin.can_attach(waiting(updated=995), 1000))
        self.assertFalse(signin.can_attach(waiting(updated=900), 1000))
        self.assertFalse(signin.can_attach(ended("done", 999), 1000))
        self.assertFalse(signin.can_attach(None, 1000))


class FollowState(unittest.TestCase):
    def follow(self, attach=False):
        return signin.Follow("YouTube", 1000.0, attach)

    def test_starting_then_the_code_with_its_step(self):
        f = self.follow()
        frame = f.feed(None, 1001)
        self.assertEqual((frame.props["headline"], frame.result, frame.link), ("Getting a code…", None, ""))
        frame = f.feed(waiting(updated=1002), 1002)
        self.assertEqual(frame.props["headline"], "")
        self.assertEqual(frame.props["code"], "A B C  -  D E F")
        self.assertEqual(frame.props["step"], "Code 2 of 4")
        self.assertEqual(frame.props["site"], "Or open youtube.com/activate and type the code")
        self.assertEqual(frame.link, "https://www.youtube.com/activate?user_code=ABC-DEF")
        frame = f.feed(waiting(code="GHI-JKL", step=3, updated=1010), 1010)      # YouTube moved on by itself
        self.assertEqual((frame.props["code"], frame.props["step"]), ("G H I  -  J K L", "Code 3 of 4"))
        self.assertTrue(frame.link.endswith("GHI-JKL"))

    def test_one_code_services_have_no_step_line_and_long_codes_get_a_smaller_font(self):
        f = self.follow()
        frame = f.feed(waiting(code="12345678", step=1, steps=1, updated=1001, url="https://sweet.tv/addDevice"), 1001)
        self.assertEqual(frame.props["step"], "")
        self.assertEqual(frame.props["site"], "Or open sweet.tv/addDevice and type the code")
        self.assertEqual(frame.props["codelong"], "")
        frame = f.feed(waiting(code="ABCDEFGHIJKLMNOPQ", updated=1002), 1002)
        self.assertEqual(frame.props["codelong"], "1")

    def test_done_is_shown_for_a_moment_then_closes(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        frame = f.feed(ended("done", 1005), 1005)
        self.assertEqual((frame.result, frame.props["headline"], frame.close), ("done", "Signed in", False))
        self.assertFalse(f.feed(ended("done", 1005), 1006.5).close)
        self.assertTrue(f.feed(ended("done", 1005), 1005 + signin.LINGER["done"]).close)
        self.assertEqual(f.feed(waiting(updated=1008), 1008).result, "done")        # sticky

    def test_failed_and_cancelled_say_so_and_close(self):
        for kind, text in (("failed", "Sign-in did not work"), ("cancelled", "Sign-in cancelled")):
            f = self.follow()
            frame = f.feed(ended(kind, 1003), 1003)
            self.assertEqual((frame.result, frame.props["headline"]), (kind, text))
            self.assertTrue(f.feed(None, 1003 + signin.LINGER[kind]).close)

    def test_the_state_disappearing_closes_the_screen(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        frame = f.feed(None, 1003)
        self.assertEqual((frame.result, frame.props["headline"]), ("gone", "Sign-in stopped"))
        self.assertTrue(f.feed(None, 1003 + signin.LINGER["gone"]).close)

    def test_no_state_at_all_gives_up(self):
        f = self.follow()
        self.assertIsNone(f.feed(None, 1000 + signin.START_WAIT - 1).result)
        frame = f.feed(None, 1000 + signin.START_WAIT)
        self.assertEqual(frame.result, "failed")
        self.assertIn("No code came", frame.props["status"])

    def test_a_result_left_over_from_before_is_ignored_unless_it_is_this_one(self):
        f = self.follow()
        self.assertEqual(f.feed(ended("done", 900), 1001).props["headline"], "Getting a code…")
        self.assertEqual(f.feed(waiting(updated=900), 1001).props["headline"], "Getting a code…")     # a dead one
        self.assertEqual(f.feed(ended("cancelled", 999), 1001).result, "cancelled")                  # within the slack
        attached = self.follow(attach=True)
        self.assertEqual(attached.feed(waiting(updated=900), 1001).props["code"], "A B C  -  D E F")
        again = self.follow(attach=True)
        self.assertEqual(again.feed(ended("done", 900), 1002).props["headline"], "Getting a code…")   # an old result still not

    def test_cancel_waits_for_the_add_on_to_stop(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        f.cancel(1002)
        self.assertTrue(f.cancelling)
        frame = f.feed(waiting(updated=1002), 1003)
        self.assertEqual((frame.props["headline"], frame.link, frame.result), ("Cancelling…", "", None))
        frame = f.feed(ended("cancelled", 1004), 1004)
        self.assertEqual((frame.result, f.cancelling), ("cancelled", False))

    def test_cancel_gives_up_waiting_and_a_second_back_leaves_at_once(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        f.cancel(1002)
        self.assertIsNone(f.feed(waiting(updated=1005), 1000 + 2 + signin.CANCEL_WAIT - 1).result)
        self.assertEqual(f.feed(waiting(updated=1005), 1002 + signin.CANCEL_WAIT).result, "cancelled")
        g = self.follow()
        g.cancel(1001)
        g.force(1001.1)
        self.assertEqual(g.feed(None, 1001.1).result, "cancelled")

    def test_continue_without_account_is_its_own_result_and_waits_like_a_cancel(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        f.cancel(1002, skip=True)
        self.assertIsNone(f.feed(waiting(updated=1003), 1003).result)
        self.assertEqual(f.feed(ended("cancelled", 1004), 1004).result, "skipped")
        f.cancel(1005, skip=False)                                  # too late to change its mind
        self.assertEqual(f.result, "skipped")

    def test_a_done_that_arrives_while_cancelling_is_not_a_launch(self):
        f = self.follow()
        f.feed(waiting(updated=1001), 1001)
        f.cancel(1002)
        self.assertEqual(f.feed(ended("done", 1003), 1003).result, "cancelled")

    def test_cancel_before_any_state_waits_for_the_add_on_to_start_then_stops(self):
        f = self.follow()
        f.cancel(1001)
        self.assertIsNone(f.feed(None, 1003).result)
        self.assertEqual(f.feed(ended("cancelled", 1004), 1004).result, "cancelled")

    def test_pure_helpers(self):
        self.assertEqual(signin.spaced("ABC-DEF-GHIJ"), "A B C  -  D E F  -  G H I J")
        self.assertEqual(signin.spaced("12345"), "1 2 3 4 5")
        self.assertEqual(signin.site("https://www.youtube.com/activate"), "youtube.com/activate")
        self.assertEqual(signin.site("sweet.tv/addDevice/"), "sweet.tv/addDevice")
        mine = 13005
        self.assertTrue(signin.covered(signin.PROGRESS_DIALOG, mine))            # YouTube's code dialog
        self.assertTrue(signin.covered(13006, mine))                             # SWEET.TV's popup (a script window)
        self.assertFalse(signin.covered(mine, mine))
        self.assertFalse(signin.covered(0, mine))
        self.assertFalse(signin.covered(12002, mine))                            # an OK dialog the person must answer
        self.assertFalse(signin.covered(10100, mine))
        self.assertFalse(signin.covered(10138, mine))                            # Kodi's busy dialog
        self.assertFalse(signin.covered(13006, 0))                               # our own id unknown: never churn


class SigninScreen(unittest.TestCase):
    """The real dialog class and run() on the stubbed windows, with short times."""

    def setUp(self):
        Fake.home.clear()
        Fake.opened = 0
        Fake.top = 0
        lib.begin("youtube")
        self.patches = [mock.patch.object(signin, "TICK", 0.01), mock.patch.object(signin, "START_WAIT", 0.5),
                        mock.patch.object(signin, "CANCEL_WAIT", 0.5),
                        mock.patch.object(signin, "LINGER", {k: 0.05 for k in signin.LINGER}),
                        mock.patch.object(remote, "qr_png", side_effect=lambda link: f"/tmp/qr-{len(link)}.png")]
        for p in self.patches:
            p.start()
        self.shown = []
        original = signin.SigninDialog._apply

        def spy(dialog, frame):
            original(dialog, frame)
            self.shown.append(dict(dialog._props))
        self.spy = mock.patch.object(signin.SigninDialog, "_apply", spy)
        self.spy.start()

    def tearDown(self):
        for p in self.patches + [self.spy]:
            p.stop()

    def later(self, seconds, fn):
        timer = threading.Timer(seconds, fn)
        timer.start()
        self.addCleanup(timer.cancel)

    def test_a_sign_in_that_succeeds_shows_the_code_and_a_qr_and_ends_done(self):
        self.later(0.1, lambda: lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate",
                                            step=2, steps=4))
        self.later(0.3, lambda: lib.publish("youtube", "waiting", code="GHI-JKL", url="https://www.youtube.com/activate",
                                            step=3, steps=4))
        self.later(0.5, lambda: lib.publish("youtube", "done"))
        self.assertEqual(signin.run("youtube"), "done")
        codes = [p.get("code") for p in self.shown if p.get("code")]
        self.assertIn("A B C  -  D E F", codes)
        self.assertIn("G H I  -  J K L", codes)
        self.assertTrue(any(p.get("qr", "").startswith("/tmp/qr-") for p in self.shown))
        self.assertEqual(self.shown[-1]["headline"], "Signed in")
        self.assertEqual(Fake.home.get(signin.SHOWING), "")                 # the "screen is up" mark is cleared

    def test_cancel_asks_the_add_on_to_stop(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        original = signin.SigninDialog.onInit

        def on_init(dialog):
            self.dialog = dialog
            original(dialog)
        with mock.patch.object(signin.SigninDialog, "onInit", on_init):
            self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_CANCEL))
            self.later(0.2, lambda: lib.publish("youtube", "cancelled"))       # the add-on obeys
            self.assertEqual(signin.run("youtube", attach=True), "cancelled")
        self.assertTrue(lib.cancel_requested("youtube"))

    def test_skip_ends_as_skipped(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        original = signin.SigninDialog.onInit

        def on_init(dialog):
            self.dialog = dialog
            original(dialog)
        with mock.patch.object(signin.SigninDialog, "onInit", on_init):
            self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_SKIP))
            self.later(0.2, lambda: lib.publish("youtube", "cancelled"))
            self.assertEqual(signin.run("youtube", attach=True, allow_skip=True), "skipped")
        self.assertEqual(self.shown[0].get("skip"), "1")

    def test_an_add_on_dialog_on_top_makes_the_screen_open_again_above_it(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        self.later(0.1, lambda: setattr(Fake, "top", signin.PROGRESS_DIALOG))     # YouTube's code dialog appears
        self.later(0.4, lambda: lib.publish("youtube", "done"))
        self.assertEqual(signin.run("youtube", attach=True), "done")
        self.assertGreaterEqual(Fake.opened, 2)

    def test_the_state_vanishing_closes_it(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        self.later(0.15, lambda: lib.begin("youtube"))
        self.assertEqual(signin.run("youtube", attach=True), "gone")

    def test_an_add_on_that_never_answers_ends_as_failed(self):
        self.assertEqual(signin.run("youtube"), "failed")

    def test_a_screen_that_keeps_getting_covered_is_left_alone_in_the_end(self):
        lib.publish("youtube", "waiting", code="ABC-DEF", url="https://www.youtube.com/activate")
        with mock.patch.object(signin, "MAX_REOPEN", 3), \
                mock.patch.object(signin, "covered", return_value=True):
            self.later(0.5, lambda: lib.publish("youtube", "done"))
            self.assertEqual(signin.run("youtube", attach=True), "done")
        self.assertEqual(Fake.opened, 4)

    def test_nothing_can_leave_the_home_mark_behind(self):
        signin.mark_showing("youtube", time.time())
        with mock.patch.object(signin.SigninDialog, "doModal", side_effect=RuntimeError("no skin")):
            with self.assertRaises(RuntimeError):
                signin.run("youtube")
        self.assertEqual(Fake.home.get(signin.SHOWING, ""), "")


def partner_state(code="12345", updated=1000, left=21540):
    return dict(waiting(code=code, step=1, steps=1, updated=updated, url="https://sweet.tv/addDevice"),
                service="sweettv", mode="partner", left=left)


class PartnerFollow(unittest.TestCase):
    """The pure part of the partner screen: what it says and which buttons it names."""

    def follow(self, **kw):
        return signin.Follow("SWEET.TV", 1000.0, **kw)

    def test_the_time_left_is_hours_and_minutes_and_a_started_minute_still_counts(self):
        self.assertEqual([signin.hours(s) for s in (21600, 21540, 3600, 61, 60, 1, 0)],
                         ["6:00", "5:59", "1:00", "0:02", "0:01", "0:01", "0:00"])
        self.assertEqual([signin.hours(s) for s in (None, "", -5)], ["0:00"] * 3)

    def test_a_partner_wait_says_so_in_russian_and_english_counts_down_and_has_no_qr(self):
        frame = self.follow().feed(partner_state(), 1001)
        p = frame.props
        self.assertEqual((p["partner"], p["left"], p["headline"]), ("1", "5:59", ""))
        self.assertEqual(p["status"], "Ждём подключения специалистом партнёра. Не выключайте ТВ.")
        self.assertEqual(p["status2"], "Waiting for the partner's specialist to connect. Keep the TV on.")
        self.assertEqual(p["code"], "1 2 3 4 5")
        self.assertEqual((frame.link, p["site"], p["step"]), ("", "", ""))             # no QR, no "scan" hint
        self.assertEqual(self.follow().feed(partner_state(left=3 * 3600 + 1), 1001).props["left"], "3:01")

    def test_the_buttons_name_wait_and_cancel_in_partner_mode_and_cancel_and_continue_otherwise(self):
        normal = self.follow().feed(waiting(updated=1001), 1001).props
        self.assertEqual((normal["partner"], normal["btn1"], normal["btn2"], normal["left"]),
                         ("", "Cancel", "Continue without account", ""))
        partner = self.follow().feed(partner_state(), 1001).props
        self.assertEqual((partner["btn1"], partner["btn2"]), ("Ждать / Wait", "Отмена / Cancel"))
        self.assertNotIn("Cancel", partner["btn1"])                                     # what has the focus never cancels

    def test_the_mode_comes_from_the_state_and_from_the_phones_request_before_any_state(self):
        asked = self.follow(partner=True)
        self.assertEqual(asked.feed(None, 1001).props["btn1"], "Ждать / Wait")          # still "Getting a code…"
        self.assertEqual(asked.feed(None, 1001).props["headline"], "Getting a code…")
        self.assertEqual(asked.feed(waiting(updated=1002), 1002).props["btn1"], "Cancel")   # the state is what is true
        again = self.follow()
        self.assertEqual(again.feed(None, 1001).props["btn1"], "Cancel")
        self.assertEqual(again.feed(partner_state(updated=1002), 1002).props["btn1"], "Ждать / Wait")

    def test_a_result_keeps_the_partner_buttons_it_had(self):
        f = self.follow()
        f.feed(partner_state(), 1001)
        frame = f.feed(dict(ended("done", 1005), mode="normal"), 1005)
        self.assertEqual((frame.result, frame.props["headline"], frame.props["partner"]), ("done", "Signed in", "1"))

    def test_a_partner_state_that_expired_or_died_ends_the_screen_like_any_other(self):
        f = self.follow()
        f.feed(partner_state(), 1001)
        self.assertEqual(f.feed(None, 1003).result, "gone")

    def test_cancelling_a_partner_wait_shows_the_usual_cancelling_screen(self):
        f = self.follow()
        f.feed(partner_state(), 1001)
        f.cancel(1002)
        frame = f.feed(partner_state(updated=1002), 1003)
        self.assertEqual((frame.props["headline"], frame.props["left"], frame.link), ("Cancelling…", "", ""))

    def test_the_screensaver_is_held_at_once_every_minute_and_let_go_when_it_is_not_wanted(self):
        hold = signin.ScreensaverHold()
        self.assertIsNone(hold.step(False, 0))                                          # nothing to give back
        self.assertEqual(hold.step(True, 100), "InhibitScreensaver(true)")
        self.assertIsNone(hold.step(True, 100.5))
        self.assertIsNone(hold.step(True, 100 + signin.INHIBIT_EVERY - 1))
        self.assertEqual(hold.step(True, 100 + signin.INHIBIT_EVERY), "InhibitScreensaver(true)")
        self.assertEqual(hold.step(False, 200), "InhibitScreensaver(false)")
        self.assertIsNone(hold.step(False, 201))
        self.assertEqual(hold.step(True, 202), "InhibitScreensaver(true)")              # and again for the next one
        self.assertEqual(signin.INHIBIT_EVERY, 60)

    def test_the_request_of_the_phone_is_read_from_the_library_and_a_broken_library_is_no(self):
        lib.clear_mode("sweettv")
        self.assertFalse(signin.asked_partner("sweettv"))
        lib.request_mode("sweettv", "partner")
        self.addCleanup(lib.clear_mode, "sweettv")
        self.assertTrue(signin.asked_partner("sweettv"))
        self.assertFalse(signin.asked_partner("youtube"))
        with mock.patch.object(lib, "requested_mode", side_effect=AttributeError("old library")):
            self.assertFalse(signin.asked_partner("sweettv"))


class PartnerScreen(unittest.TestCase):
    """The real dialog class and run() on the stubbed windows, a partner waiting for a code."""

    def setUp(self):
        Fake.home.clear()
        Fake.opened = 0
        Fake.top = 0
        Fake.asked = []
        Fake.sure = False
        Fake.builtins.clear()
        lib.begin("sweettv")
        lib.clear_mode("sweettv")
        self.patches = [mock.patch.object(signin, "TICK", 0.01), mock.patch.object(signin, "START_WAIT", 0.5),
                        mock.patch.object(signin, "CANCEL_WAIT", 0.5), mock.patch.object(signin, "INHIBIT_EVERY", 0.05),
                        mock.patch.object(signin, "LINGER", {k: 0.05 for k in signin.LINGER}),
                        mock.patch.object(remote, "qr_png", side_effect=lambda link: f"/tmp/qr-{len(link)}.png")]
        for p in self.patches:
            p.start()
        self.shown = []
        original, original_init = signin.SigninDialog._apply, signin.SigninDialog.onInit

        def spy(dialog, frame):
            original(dialog, frame)
            self.shown.append(dict(dialog._props))

        def on_init(dialog):
            self.dialog = dialog
            original_init(dialog)
        self.patches += [mock.patch.object(signin.SigninDialog, "_apply", spy),
                         mock.patch.object(signin.SigninDialog, "onInit", on_init)]
        for p in self.patches[-2:]:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        lib.begin("sweettv")
        lib.clear_mode("sweettv")

    def later(self, seconds, fn):
        timer = threading.Timer(seconds, fn)
        timer.start()
        self.addCleanup(timer.cancel)

    def publish(self, state="waiting", **kw):
        lib.publish("sweettv", state, code="12345", url="https://sweet.tv/addDevice", mode="partner", **kw)

    def back(self):
        self.dialog.onAction(types.SimpleNamespace(getId=lambda: ui.ACTION_NAV_BACK))

    def test_the_screen_shows_the_partner_text_the_countdown_the_code_and_no_qr_and_the_focus_is_on_wait(self):
        self.publish()
        self.later(0.1, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv", attach=True), "done")
        first = next(p for p in self.shown if p.get("code"))
        self.assertEqual((first["partner"], first["code"], first["btn1"]), ("1", "1 2 3 4 5", "Ждать / Wait"))
        self.assertRegex(first["left"], r"^[56]:\d\d$")
        self.assertIn("Ждём подключения специалистом партнёра. Не выключайте ТВ.", first["status"])
        self.assertIn("Keep the TV on.", first["status2"])
        self.assertEqual(first["skip"], "1")                                            # the second button (Cancel) is shown
        self.assertFalse(any(p.get("qr") for p in self.shown))
        self.assertEqual(self.dialog.focus, signin.CONTROL_CANCEL)                      # the first button, which says Wait

    def test_the_first_button_keeps_waiting_whatever_is_pressed(self):
        self.publish()
        self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_CANCEL))
        self.later(0.15, lambda: self.dialog.onClick(signin.CONTROL_CANCEL))
        self.later(0.3, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv", attach=True), "done")
        self.assertEqual(Fake.asked, [])
        self.assertFalse(lib.cancel_requested("sweettv"))

    def test_the_cancel_button_asks_first_and_a_no_changes_nothing(self):
        self.publish()
        Fake.sure = False
        self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_SKIP))
        self.later(0.3, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv", attach=True), "done")
        self.assertEqual(len(Fake.asked), 1)
        heading, message, no, yes = Fake.asked[0]
        self.assertIn("Отменить вход?", heading)
        self.assertIn("Cancel sign-in?", heading)
        self.assertIn("The partner's specialist", message)
        self.assertEqual((no, yes), ("Ждать / Wait", "Отмена / Cancel"))
        self.assertFalse(lib.cancel_requested("sweettv"))
        self.assertEqual(self.dialog.focus, signin.CONTROL_CANCEL)                      # back on Wait

    def test_a_yes_cancels(self):
        self.publish()
        Fake.sure = True
        self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_SKIP))
        self.later(0.2, lambda: lib.publish("sweettv", "cancelled"))
        self.assertEqual(signin.run("sweettv", attach=True), "cancelled")
        self.assertEqual(len(Fake.asked), 1)
        self.assertTrue(lib.cancel_requested("sweettv"))

    def test_back_asks_too_and_does_not_close_the_screen_on_a_no(self):
        self.publish()
        Fake.sure = False
        self.later(0.1, self.back)
        self.later(0.2, self.back)
        self.later(0.4, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv", attach=True), "done")
        self.assertEqual(len(Fake.asked), 2)
        self.assertFalse(lib.cancel_requested("sweettv"))

    def test_back_with_a_yes_cancels_and_a_second_back_does_not_ask_again(self):
        self.publish()
        Fake.sure = True
        self.later(0.1, self.back)
        self.later(0.2, self.back)                                 # while cancelling: leave without waiting for the add-on
        self.assertEqual(signin.run("sweettv", attach=True), "cancelled")
        self.assertEqual(len(Fake.asked), 1)
        self.assertTrue(lib.cancel_requested("sweettv"))

    def test_a_normal_sign_in_cancels_without_a_question_as_before(self):
        lib.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice")
        self.later(0.1, lambda: self.dialog.onClick(signin.CONTROL_CANCEL))
        self.later(0.2, lambda: lib.publish("sweettv", "cancelled"))
        self.assertEqual(signin.run("sweettv", attach=True), "cancelled")
        self.assertEqual(Fake.asked, [])
        self.assertEqual(self.shown[0]["btn1"], "Cancel")
        self.assertFalse(any(c.startswith("InhibitScreensaver") for c in Fake.builtins))

    def test_the_screensaver_is_held_every_minute_while_it_is_up_and_given_back_when_it_closes(self):
        self.publish()
        self.later(0.3, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv", attach=True), "done")
        held = [c for c in Fake.builtins if c.startswith("InhibitScreensaver")]
        self.assertGreaterEqual(held.count("InhibitScreensaver(true)"), 3)              # repeated, not once
        self.assertEqual(held[-1], "InhibitScreensaver(false)")
        self.assertEqual(held.count("InhibitScreensaver(false)"), 1)

    def test_the_screensaver_is_given_back_even_when_the_window_breaks(self):
        self.publish()
        with mock.patch.object(signin.SigninDialog, "doModal", side_effect=RuntimeError("no skin")):
            with self.assertRaises(RuntimeError):
                signin.run("sweettv", attach=True)
        self.assertEqual([c for c in Fake.builtins if c.startswith("InhibitScreensaver")], [])   # never held, nothing to give back
        Fake.builtins.clear()
        original = signin.SigninDialog.doModal

        def modal_then_break(dialog):
            original(dialog)
            raise RuntimeError("boom")
        self.later(0.1, lambda: lib.publish("sweettv", "done"))
        with mock.patch.object(signin.SigninDialog, "doModal", modal_then_break):
            with self.assertRaises(RuntimeError):
                signin.run("sweettv", attach=True)
        self.assertEqual([c for c in Fake.builtins if c.startswith("InhibitScreensaver")][-1], "InhibitScreensaver(false)")

    def test_the_phones_request_makes_the_first_seconds_partner_before_any_state_exists(self):
        lib.request_mode("sweettv", "partner")
        self.later(0.1, lambda: self.publish())
        self.later(0.3, lambda: lib.publish("sweettv", "done"))
        self.assertEqual(signin.run("sweettv"), "done")
        self.assertEqual(self.shown[0]["headline"], "Getting a code…")
        self.assertEqual(self.shown[0]["btn1"], "Ждать / Wait")
        self.assertEqual(self.dialog.focus, signin.CONTROL_CANCEL)


class Lists(unittest.TestCase):
    def test_cards(self):
        cards = profiles.cards([prof(0, "Default", 4, True), prof(7, "anna", 0)])
        self.assertEqual([c["id"] for c in cards], ["0", "7", profiles.ADD_ID])
        self.assertEqual([c["initial"] for c in cards], ["D", "A", "+"])
        self.assertEqual([c["mark"] for c in cards], ["Signed in", "Not signed in", ""])
        self.assertEqual(cards[1]["color"], profiles.PALETTE[7 % len(profiles.PALETTE)])
        self.assertEqual(cards[-1]["name"], "Add account")
        self.assertEqual(profiles.first_index(cards), 0)
        cards = profiles.cards([prof(0, "D", 4), prof(1, "Anna", 0, True)])
        self.assertEqual(profiles.first_index(cards), 1)
        self.assertEqual(profiles.initial("  "), "?")
        self.assertEqual(profiles.initial("-Ωmega"), "Ω")
        self.assertEqual(profiles.cards([])[0]["id"], profiles.ADD_ID)

    def labels(self, accts, pending=None):
        return [(r.service, r.action, r.label, r.detail) for r in accounts_screen.rows(accts, pending)]

    def test_accounts_rows(self):
        out = self.labels([acct("youtube", [prof(0, "Default", 4, True), prof(1, "Anna", 0)], True), acct("sweettv")])
        self.assertEqual(out, [
            ("youtube", "signout", "Sign out of YouTube", "Default: signed in"),
            ("youtube", "switch", "Switch profile or add one", "2 profiles: Default, Anna"),
            ("sweettv", "signin", "Sign in to SWEET.TV", "Not signed in")])
        out = self.labels([acct("youtube", [prof(0, "Default", 0, True)]), acct("sweettv", signed_in=True)])
        self.assertEqual(out[0], ("youtube", "signin", "Sign in to YouTube", "Default: not signed in"))
        self.assertEqual(out[-1], ("sweettv", "signout", "Sign out of SWEET.TV", "Signed in"))

    def test_partial_youtube_sign_in_is_said_plainly(self):
        out = self.labels([acct("youtube", [prof(0, "Default", 2, True)], True)])
        self.assertEqual(out[0][2:], ("Finish signing in to YouTube", "Default: 2 of 4 codes entered"))
        self.assertEqual([r[1] for r in out], ["signin", "signout", "switch"])

    def test_sign_out_needs_a_second_press(self):
        accts = [acct("youtube", [prof(0, "Default", 4, True)], True)]
        first = accounts_screen.rows(accts)[0]
        again = accounts_screen.rows(accts, ("youtube", "signout"))[0]
        self.assertEqual((first.confirm, again.confirm), (False, True))
        self.assertIn("again", again.label)

    def test_a_running_sign_in_is_offered_back_instead_of_a_second_start(self):
        out = self.labels([acct("youtube", [prof(0, "Default", 0, True)], False, {"state": "waiting"}),
                           acct("sweettv", state={"state": "waiting"})])
        self.assertEqual(out[0][2], "Show the sign-in code")
        self.assertEqual(out[-1][2], "Show the sign-in code")

    def test_the_real_library_feeds_the_list(self):
        put(os.path.join(os.environ["MEDIASTICK_ADDON_DATA"], "plugin.video.youtube", "access_manager.json"), json.dumps(
            {"access_manager": {"current_user": "1", "users": {"0": {"name": "Default", "refresh_token": "a|b|c|d"},
                                                                 "1": {"name": "Anna", "refresh_token": ""}}}}))
        put(os.path.join(os.environ["MEDIASTICK_ADDON_DATA"], "plugin.video.sweettv", "settings.xml"),
            '<settings><setting id="logged">true</setting></settings>')
        lib.begin("youtube")
        lib.begin("sweettv")
        out = self.labels(lib.accounts())
        self.assertEqual(out[0], ("youtube", "signin", "Sign in to YouTube", "Anna: not signed in"))
        self.assertEqual(out[-1][:2], ("sweettv", "signout"))
        self.assertEqual(accounts.plan(YT, lib.accounts()), ("youtube", accounts.PICK))
        self.assertEqual(accounts.current_profile()["name"], "Anna")


class Skin(unittest.TestCase):
    NEW = ("script-media-stick-signin.xml", "script-media-stick-profiles.xml", "script-media-stick-accounts.xml",
           "script-media-stick-onboarding.xml")

    def tree(self, name):
        return ET.parse(os.path.join(SKIN, name)).getroot()

    def test_every_xml_is_well_formed(self):
        for name in sorted(os.listdir(SKIN)):
            if name.endswith(".xml"):
                self.assertEqual(self.tree(name).tag, "window", name)

    @staticmethod
    def control_ids(root):
        return {int(c.get("id")) for c in root.iter("control") if c.get("id", "").isdigit()}

    def test_every_control_the_python_uses_is_in_its_xml(self):
        want = {"script-media-stick-signin.xml": {signin.CONTROL_CANCEL, signin.CONTROL_SKIP},
                "script-media-stick-profiles.xml": {profiles.LIST},
                "script-media-stick-accounts.xml": {accounts_screen.LIST},
                "script-media-stick-home.xml": {launcher.CAROUSEL, launcher.DRAWER, launcher.EDGE_LEFT,
                                                launcher.EDGE_RIGHT, 401, 402, 403, 404, 405}}
        for name, ids in want.items():
            self.assertLessEqual(ids, self.control_ids(self.tree(name)), name)
        for name, first in (("script-media-stick-signin.xml", signin.CONTROL_CANCEL),
                            ("script-media-stick-profiles.xml", profiles.LIST),
                            ("script-media-stick-accounts.xml", accounts_screen.LIST)):
            self.assertEqual(int(self.tree(name).find("defaultcontrol").text), first, name)

    def test_every_window_name_the_xml_reads_is_set_by_the_python(self):
        texts = lambda name: "".join(ET.tostring(self.tree(name), encoding="unicode").split())   # noqa: E731
        read = set(re.findall(r"Window\.Property\((\w+)\)", texts("script-media-stick-signin.xml")))
        props, _ = signin.Follow("YouTube", 0).feed(None, 1)[:2]
        self.assertLessEqual(read, set(props) | {"qr", "skip", "ob_qr"})
        items = set(re.findall(r"ListItem\.Property\((\w+)\)", texts("script-media-stick-profiles.xml")))
        self.assertLessEqual(items, set(profiles.cards([])[0]))
        self.assertEqual(set(re.findall(r"ListItem\.Property\((\w+)\)", texts("script-media-stick-accounts.xml"))), {"confirm"})

    def test_the_signin_screen_has_a_partner_layout_and_its_buttons_are_named_by_the_python(self):
        root = self.tree("script-media-stick-signin.xml")
        self.assertEqual(root.find("defaultcontrol").text, "10")
        buttons = {c.get("id"): c for c in root.iter("control") if c.get("type") == "button"}
        self.assertEqual(buttons["10"].find("label").text, "$INFO[Window.Property(btn1)]")
        self.assertEqual(buttons["11"].find("label").text, "$INFO[Window.Property(btn2)]")
        for button in buttons.values():                     # black text on the white focus, in lists and buttons alike
            self.assertEqual(button.find("focusedcolor").text, "FF000000")
            self.assertEqual(button.find("selectedcolor").text, "FF000000")
        text = ET.tostring(root, encoding="unicode")
        for want in ("Window.Property(left)", "Window.Property(status2)", "Осталось / Time left"):
            self.assertIn(want, text)
        qr = next(c for c in root.iter("control") if c.get("type") == "group" and "Property(qr)" in (c.findtext("visible") or ""))
        self.assertIn("String.IsEmpty(Window.Property(partner))", qr.findtext("visible"))     # no QR in partner mode

    def test_only_fonts_and_textures_the_launcher_already_has(self):
        fonts = set()
        for name in ("script-media-stick-home.xml", "script-media-stick-remote.xml"):
            fonts |= {f.text for f in self.tree(name).iter("font")}
        fonts.add("MsTitle")             # the skin's own title font (skin.ftv Font.xml): loaded at start, whoever draws with it
        for name in self.NEW:
            root = self.tree(name)
            self.assertLessEqual({f.text for f in root.iter("font")}, fonts, name)
            for tag in ("texture", "texturefocus", "texturenofocus"):
                for node in root.iter(tag):
                    if "$" not in node.text:
                        self.assertTrue(os.path.exists(os.path.join(MEDIA, node.text)), f"{name}: {node.text}")

    def test_no_big_textures_and_no_animation_in_the_new_screens(self):
        for name in self.NEW:
            self.assertEqual(list(self.tree(name).iter("animation")), [], name)
        for png in ("pill.png", "white.png", "card-shadow.png", "icon-accounts.png"):
            self.assertLess(os.path.getsize(os.path.join(MEDIA, png)), 20000, png)

    def test_the_accounts_entry_is_in_the_drawer_with_its_icon(self):
        labels = [label for label, _ in launcher.DRAWER_ITEMS]
        self.assertIn("Accounts", labels)
        self.assertEqual(len(labels), len(set(labels)))
        for _, icon in launcher.DRAWER_ITEMS:
            self.assertTrue(os.path.exists(os.path.join(launcher.MEDIA, icon)), icon)

    def test_each_drawer_entry_goes_where_its_label_says(self):
        window = launcher.Launcher()
        targets = {"Search": "_search", "Phone & network": "_remote", "Accounts": "_accounts", "Power": "_power"}
        for position, (label, _) in enumerate(launcher.DRAWER_ITEMS):
            if label in targets:
                with mock.patch.object(launcher.Launcher, targets[label]) as target:
                    window._drawer(position)
                target.assert_called_once_with()
        Fake.builtins.clear()
        window._drawer([label for label, _ in launcher.DRAWER_ITEMS].index("Settings"))
        self.assertEqual(Fake.builtins, ["ActivateWindow(Settings)"])
        window._drawer(99)                                       # nothing
        window._drawer(-1)
        self.assertEqual(Fake.builtins, ["ActivateWindow(Settings)"])

    def test_the_drawer_has_these_five_rows_in_this_order_and_the_list_fits_them(self):
        self.assertEqual([label for label, _ in launcher.DRAWER_ITEMS],
                         ["Search", "Accounts", "Phone & network", "Settings", "Power"])
        self.assertNotIn("Add-ons", [label for label, _ in launcher.DRAWER_ITEMS])
        listing = next(c for c in self.tree("script-media-stick-home.xml").iter("control") if c.get("id") == "201")
        row = int(listing.find("itemlayout").get("height"))
        self.assertEqual(int(listing.find("height").text), row * len(launcher.DRAWER_ITEMS))
        window = launcher.Launcher()
        Fake.builtins.clear()
        with mock.patch.object(launcher.Launcher, "_power") as power:
            window._drawer(len(launcher.DRAWER_ITEMS) - 1)
        power.assert_called_once_with()
        with open(os.path.join(ADDON, "resources", "lib", "launcher.py"), encoding="utf-8") as f:
            self.assertNotIn("AddonBrowser", f.read())

    def test_the_accounts_entry_survives_a_broken_screen(self):
        Fake.notes.clear()
        with mock.patch.object(accounts_screen, "show", side_effect=RuntimeError("no skin")):
            launcher.Launcher._accounts()
        self.assertEqual(Fake.notes, ["Accounts are not available."])


class Dispatch(unittest.TestCase):
    """default.py: the accounts arguments go to accounts.main, everything else is as it was."""

    def run_default(self, argv):
        Fake.builtins.clear()
        seen = []
        with mock.patch.object(sys, "argv", ["default.py"] + argv), \
                mock.patch.object(accounts, "main", side_effect=lambda a: seen.append(a)), \
                mock.patch.object(apps, "launch", side_effect=lambda a: seen.append(("launch", a))):
            with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})
        return seen, list(Fake.builtins)

    def test_arguments(self):
        self.assertEqual(self.run_default(["accounts", "signin", "youtube"]), ([["signin", "youtube"]], []))
        self.assertEqual(self.run_default(["launch", SW]), ([("launch", SW)], []))
        self.assertEqual(self.run_default([]), ([], ["ActivateWindow(Home)"]))
        self.assertEqual(self.run_default(["launch"]), ([], ["ActivateWindow(Home)"]))
        self.assertEqual(self.run_default(["bogus"]), ([], ["ActivateWindow(Home)"]))


if __name__ == "__main__":
    unittest.main()
