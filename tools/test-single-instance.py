#!/usr/bin/env python3
"""Offline test of the single-instance flag (no Kodi, no device): python3 tools/test-single-instance.py

A stubbed xbmc answers Window.IsActive(<id>) and Player.HasVideo from what the test sets; the Home window is a dict."""
import os
import sys
import types
import unittest

sys.dont_write_bytecode = True

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")


class Kodi:
    """What the stubbed Kodi shows: the ids of the active windows, and whether a video plays."""
    active, video = set(), False


def cond(text):
    if text == "Player.HasVideo":
        return Kodi.video
    if text.startswith("Window.IsActive(") and text.endswith(")"):
        return int(text[len("Window.IsActive("):-1]) in Kodi.active
    raise AssertionError(f"unexpected condition {text!r}")


xbmc = types.ModuleType("xbmc")
xbmc.getCondVisibility = cond
sys.modules["xbmc"] = xbmc
sys.path.insert(0, ADDON)

from resources.lib import single_instance as si  # noqa: E402

KEY = "media-stick.test"
WINDOW = 14001


class Home:
    def __init__(self):
        self.props = {}

    def getProperty(self, key):
        return self.props.get(key, "")

    def setProperty(self, key, value):
        self.props[key] = value


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        return self.now


class Flag(unittest.TestCase):
    def setUp(self):
        Kodi.active, Kodi.video = set(), False
        self.home, self.clock = Home(), Clock()

    def claim(self):
        return si.claim(self.home, KEY, clock=self.clock)

    def open_window(self):
        """A launch that got as far as its window: claimed, bound, and Kodi shows the window."""
        inst = self.claim()
        self.assertIsNotNone(inst)
        inst.bind(WINDOW)
        Kodi.active.add(WINDOW)
        return inst

    def test_a_free_flag_is_taken_and_names_its_window(self):
        inst = self.claim()
        flag = si.decode(self.home.getProperty(KEY))
        self.assertEqual((flag.token, flag.window_id, flag.started), (inst.token, 0, self.clock.now))
        inst.bind(WINDOW)
        self.assertEqual(si.decode(self.home.getProperty(KEY)).window_id, WINDOW)
        inst.release()
        self.assertEqual(self.home.getProperty(KEY), "")

    def test_a_stale_flag_of_a_dead_window_is_taken_over(self):
        self.open_window()
        Kodi.active.clear()                       # the window went away; nothing cleared the flag
        self.clock.now += si.GRACE + 1
        second = self.claim()
        self.assertIsNotNone(second)
        self.assertEqual(si.decode(self.home.getProperty(KEY)).token, second.token)

    def test_a_live_window_refuses_a_second_launch(self):
        first = self.open_window()
        self.clock.now += 3600
        self.assertIsNone(self.claim())
        self.assertEqual(si.decode(self.home.getProperty(KEY)).token, first.token)

    def test_the_start_grace_refuses_a_second_launch_before_the_window_is_known(self):
        first = self.claim()                      # not bound yet: a double press on the card
        self.clock.now += si.GRACE - 1
        self.assertIsNone(self.claim())
        self.assertEqual(si.decode(self.home.getProperty(KEY)).token, first.token)
        self.clock.now += 2                       # the window never opened: the flag goes stale
        self.assertIsNotNone(self.claim())

    def test_the_grace_holds_even_when_the_window_is_bound_but_not_shown_yet(self):
        inst = self.claim()
        inst.bind(WINDOW)
        self.clock.now += 1
        self.assertIsNone(self.claim())

    def test_a_video_over_the_window_keeps_it_alive(self):
        self.open_window()
        Kodi.active = {12005}                     # the player's fullscreen window is the active one
        Kodi.video = True
        self.clock.now += 3600
        self.assertIsNone(self.claim())
        Kodi.video = False                        # the video ended and the window is gone
        Kodi.active.clear()
        self.assertIsNotNone(self.claim())

    def test_a_background_video_on_home_without_fullscreen_reclaims_the_stale_flag(self):
        self.open_window()
        Kodi.active = {13000}                     # back on Home; video still plays in background without 12005
        Kodi.video = True
        self.clock.now += si.GRACE + 1
        second = self.claim()
        self.assertIsNotNone(second)
        self.assertEqual(si.decode(self.home.getProperty(KEY)).token, second.token)

    def test_a_late_finally_of_an_old_instance_does_not_clear_a_newer_flag(self):
        old = self.open_window()
        Kodi.active.clear()
        self.clock.now += si.GRACE + 1
        new = self.claim()
        new.bind(WINDOW + 1)
        old.release()                             # the old script's `finally`, running late
        self.assertEqual(si.decode(self.home.getProperty(KEY)).token, new.token)
        old.bind(WINDOW)                          # nor may it rewrite the flag's window
        self.assertEqual(si.decode(self.home.getProperty(KEY)).window_id, WINDOW + 1)
        new.release()
        self.assertEqual(self.home.getProperty(KEY), "")

    def test_a_value_that_is_not_ours_is_stale(self):
        for value in ("1", "x:y:z", "a:b", ":::"):
            self.home.props[KEY] = value
            self.clock.now += 1
            inst = self.claim()
            self.assertIsNotNone(inst, value)
            inst.release()
            self.assertEqual(self.home.getProperty(KEY), "", value)

    def test_a_release_of_a_foreign_value_leaves_it(self):
        inst = self.claim()
        self.home.props[KEY] = "1"
        inst.release()
        self.assertEqual(self.home.getProperty(KEY), "1")

    def test_two_launches_at_once_leave_one(self):
        class Racing(Home):
            def setProperty(self, key, value):
                super().setProperty(key, value)
                if value and not self.raced:
                    self.raced = True
                    super().setProperty(key, si.encode(si.Flag("other", 0, 0.0)))     # the other one wrote after

        home = Racing()
        home.raced = False
        self.assertIsNone(si.claim(home, KEY, clock=self.clock))


class Kodi_questions(unittest.TestCase):
    def test_the_defaults_ask_kodi(self):
        Kodi.active, Kodi.video = {5}, False
        self.assertTrue(si.window_active(5))
        self.assertFalse(si.window_active(6))
        Kodi.video = True
        self.assertFalse(si.video_playing())      # background video without fullscreen 12005 is not active playback
        Kodi.active = {12005}
        self.assertTrue(si.video_playing())
        Kodi.video = False
        self.assertFalse(si.video_playing())


if __name__ == "__main__":
    unittest.main(verbosity=1)
