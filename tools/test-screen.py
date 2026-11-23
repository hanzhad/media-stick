#!/usr/bin/env python3
"""mediastick_screen: the phone is told a cast has the TV, not that Kodi is broken."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick"))
import mediastick_screen as screen  # noqa: E402


class Screen(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.environ["MEDIASTICK_SCREEN_DIR"] = self.dir.name
        self.no_app = mock.patch.object(screen, "_web_app", return_value=False)
        self.no_app.start()

    def tearDown(self):
        mock.patch.stopall()
        self.dir.cleanup()
        os.environ.pop("MEDIASTICK_SCREEN_DIR", None)

    def flag(self, name):
        os.mkdir(os.path.join(self.dir.name, name))

    def test_nobody_has_the_screen_kodi_is_down(self):
        self.assertEqual(screen.kodi_down(), screen.KODI_DOWN)

    def test_win_k_cast(self):
        self.flag("miracast")
        self.assertIn("Win+K", screen.kodi_down())

    def test_airplay(self):
        open(os.path.join(self.dir.name, "airplay"), "w").close()
        self.assertIn("AirPlay", screen.kodi_down())

    def test_web_app(self):
        self.no_app.stop()
        with mock.patch.object(screen, "_web_app", return_value=True):
            self.assertIn("приложение", screen.kodi_down())

    def test_systemctl_missing_is_not_a_crash(self):
        self.no_app.stop()
        with mock.patch.object(subprocess, "run", side_effect=OSError):
            self.assertEqual(screen.kodi_down(), screen.KODI_DOWN)

    def test_a_broken_check_still_answers(self):
        with mock.patch.object(screen, "owner", side_effect=RuntimeError):
            self.assertEqual(screen.kodi_down(), screen.KODI_DOWN)

    def test_modules_use_it(self):
        lib = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
        for name in ("panel_accounts.py", "panel_watch.py", "panel_ytkeys.py"):
            src = open(os.path.join(lib, name), encoding="utf-8").read()
            self.assertNotIn("Refused(KODI_DOWN", src, name)
            self.assertIn("screen.kodi_down()", src, name)


if __name__ == "__main__":
    unittest.main()
