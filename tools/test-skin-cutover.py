#!/usr/bin/env python3
"""Offline tests for Issue #36: skin.media-stick cutover, skin.ftv removal,
bloat addon retirement, and event-driven service.py with displayd notifications.

Run: python3 tools/test-skin-cutover.py
"""
import sys

sys.dont_write_bytecode = True

import os  # noqa: E402
import re  # noqa: E402
import runpy  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKIN_FTV_OVERLAY = os.path.join(ROOT, "device", "skin-overlay", "skin.ftv")
SKIN_MEDIA_STICK = os.path.join(ROOT, "device", "kodi-addons", "skin.media-stick")
ADDONS_WANT = os.path.join(ROOT, "device", "kodi-addons.want")
ADDONS_LIST = os.path.join(ROOT, "device", "kodi-addons.list")
BOOTSTRAP_SH = os.path.join(ROOT, "device", "bootstrap.sh")
SERVICE_PY = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "service.py")

RETIRED_ADDONS = (
    "skin.ftv",
    "screensaver.bing",
    "plugin.video.themoviedb.helper",
    "script.skinshortcuts",
    "script.skinvariables",
    "script.module.jurialmunkey",
    "script.module.infotagger",
    "script.module.beautifulsoup4",
    "script.module.soupsieve",
    "script.module.simpleeval",
    "script.module.unidecode",
    "script.favourites",
    "script.globalsearch",
    "resource.images.weatherfanart.single",
    "resource.uisounds.ftv",
    "script.module.addon.signals",
)

KEPT_WANT = (
    "plugin.video.youtube",
    "script.plex",
    "plugin.video.sweettv",
)

KEPT_DEPS = (
    "script.module.certifi",
    "script.module.chardet",
    "script.module.idna",
    "script.module.urllib3",
    "script.module.requests",
    "script.module.six",
    "script.module.kodi-six",
    "script.module.routing",
    "script.module.iso8601",
    "script.module.inputstreamhelper",
)


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_addons_list(path):
    entries = []
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line.split())
    return entries


def _parse_addons_want(path):
    ids = []
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line.split()[0])
    return ids


class TestSkinFtvOverlayRemoved(unittest.TestCase):
    def test_skin_ftv_overlay_directory_deleted(self):
        self.assertFalse(
            os.path.exists(SKIN_FTV_OVERLAY),
            f"{SKIN_FTV_OVERLAY} must be deleted",
        )
        self.assertTrue(
            os.path.isdir(SKIN_MEDIA_STICK),
            f"{SKIN_MEDIA_STICK} must exist",
        )


class TestKodiAddonsListAndWant(unittest.TestCase):
    def test_kodi_addons_want_drops_skin_ftv_and_screensaver_bing(self):
        wanted = _parse_addons_want(ADDONS_WANT)
        for dropped in ("skin.ftv", "screensaver.bing"):
            with self.subTest(dropped=dropped):
                self.assertNotIn(dropped, wanted)
        for kept in KEPT_WANT:
            with self.subTest(kept=kept):
                self.assertIn(kept, wanted)

    def test_kodi_addons_list_drops_all_16_bloat_addons(self):
        entries = _parse_addons_list(ADDONS_LIST)
        ids = {parts[0] for parts in entries}
        for retired in RETIRED_ADDONS:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, ids, f"{retired} must be removed from kodi-addons.list")

    def test_kodi_addons_list_retains_services_and_deps_with_valid_format(self):
        entries = _parse_addons_list(ADDONS_LIST)
        for parts in entries:
            self.assertEqual(len(parts), 4, f"Expected 4 fields in kodi-addons.list: {parts}")
            self.assertRegex(parts[3], r"^[0-9a-f]{64}$", f"Invalid sha256 for {parts[0]}")
        ids = {parts[0] for parts in entries}
        for kept in KEPT_WANT + KEPT_DEPS:
            with self.subTest(kept=kept):
                self.assertIn(kept, ids, f"Required addon/dep {kept} missing from kodi-addons.list")


class TestBootstrapSkinCutover(unittest.TestCase):
    def test_bootstrap_sets_skin_media_stick_and_checks_it(self):
        text = _read_text(BOOTSTRAP_SH)
        self.assertIn("lookandfeel.skin=skin.media-stick", text)
        self.assertNotIn("lookandfeel.skin=skin.ftv", text)
        self.assertRegex(
            text,
            r'Settings\.GetSettingValue[^\n]*lookandfeel\.skin[^\n]*grep -q skin\.media-stick',
        )
        self.assertNotIn("not on skin.ftv", text)

    def test_bootstrap_retires_all_16_removed_addons(self):
        text = _read_text(BOOTSTRAP_SH)
        m = re.search(r"^retired_addons=\(([^)]+)\)", text, re.MULTILINE)
        self.assertIsNotNone(m, "retired_addons=(...) not found in device/bootstrap.sh")
        retired = set(m.group(1).split())
        self.assertIn("service.media-stick.qr", retired)
        for addon_id in RETIRED_ADDONS:
            with self.subTest(addon_id=addon_id):
                self.assertIn(
                    addon_id,
                    retired,
                    f"{addon_id} must be listed in retired_addons in device/bootstrap.sh",
                )


def _run_service_with_script(wait_callbacks, display_client_cls=None, launcher_cls=None):
    """Execute service.py in-memory with mocked Kodi & displayd modules."""
    wait_calls = []
    players = []

    class FakePlayer:
        def __init__(self, *args, **kwargs):
            players.append(self)

    class FakeMonitor:
        def __init__(self):
            self._idx = 0

        def abortRequested(self):
            return self._idx >= len(wait_callbacks)

        def waitForAbort(self, timeout):
            wait_calls.append(timeout)
            idx = self._idx
            self._idx += 1
            if idx < len(wait_callbacks):
                cb = wait_callbacks[idx]
                if callable(cb):
                    return bool(cb(players))
                return bool(cb)
            return True

    fake_xbmc = types.ModuleType("xbmc")
    fake_xbmc.LOGINFO = 1
    fake_xbmc.LOGWARNING = 2
    fake_xbmc.LOGERROR = 3
    fake_xbmc.log = lambda *a, **k: None
    fake_xbmc.getCondVisibility = lambda cond: False
    fake_xbmc.Monitor = FakeMonitor
    fake_xbmc.Player = FakePlayer

    fake_xbmcgui = types.ModuleType("xbmcgui")
    fake_xbmcgui.getCurrentWindowId = lambda: 10000

    if launcher_cls is None:
        class FakeLauncher:
            def __init__(self, *args, **kwargs):
                pass

            def show(self):
                pass

            def close(self):
                pass

            def window_id(self):
                return 13000

            def refresh_idle(self, active):
                pass

            def refresh_status(self):
                pass

        launcher_cls = FakeLauncher

    fake_launcher_mod = types.ModuleType("resources.lib.launcher")
    fake_launcher_mod.ADDON_PATH = "/tmp/addon"
    fake_launcher_mod.Launcher = launcher_cls

    fake_lang = types.ModuleType("resources.lib.lang")
    fake_lang.reconcile = lambda: None

    fake_resume = types.ModuleType("resources.lib.resume_recorder")
    fake_resume.start = lambda: None

    fake_lib = types.ModuleType("resources.lib")
    fake_lib.launcher = fake_launcher_mod
    fake_lib.lang = fake_lang
    fake_lib.resume_recorder = fake_resume

    fake_resources = types.ModuleType("resources")
    fake_resources.lib = fake_lib

    modules = {
        "xbmc": fake_xbmc,
        "xbmcgui": fake_xbmcgui,
        "resources": fake_resources,
        "resources.lib": fake_lib,
        "resources.lib.launcher": fake_launcher_mod,
        "resources.lib.lang": fake_lang,
        "resources.lib.resume_recorder": fake_resume,
    }
    if display_client_cls is not None:
        fake_md = types.ModuleType("mediastick_display")
        fake_md.DisplayClient = display_client_cls
        modules["mediastick_display"] = fake_md

    with mock.patch.dict(sys.modules, modules):
        ns = runpy.run_path(SERVICE_PY, run_name="service_under_test")
    return ns, wait_calls, players, FakePlayer


class TestServiceEventDrivenAndDisplayd(unittest.TestCase):
    def test_service_has_no_015_busy_poll(self):
        src = _read_text(SERVICE_PY)
        self.assertNotIn("waitForAbort(0.15)", src)

    def test_playback_notifier_notifies_displayd_on_start_stop_and_ended(self):
        calls = []

        class RecordingDisplayClient:
            def set_kodi_playing(self, playing):
                calls.append(playing)

        ns, _waits, players, fake_player_cls = _run_service_with_script(
            [True],
            display_client_cls=RecordingDisplayClient,
        )
        notifier_cls = ns.get("PlaybackNotifier")
        self.assertIsNotNone(notifier_cls, "service.py must define PlaybackNotifier")
        self.assertTrue(
            issubclass(notifier_cls, fake_player_cls),
            "PlaybackNotifier must subclass xbmc.Player",
        )
        self.assertTrue(players, "service.py must instantiate PlaybackNotifier")
        player = players[0]

        player.onAVStarted()
        player.onPlayBackStopped()
        player.onAVStarted()
        player.onPlayBackEnded()
        self.assertEqual(calls, [True, False, True, False])

    def test_playback_notifier_safe_offline_fallback_when_displayd_absent(self):
        class FailingDisplayClient:
            def __init__(self, *args, **kwargs):
                raise FileNotFoundError("no display.sock")

        ns, _waits, players, _ = _run_service_with_script(
            [True],
            display_client_cls=FailingDisplayClient,
        )
        self.assertIn("PlaybackNotifier", ns)
        self.assertTrue(players)
        player = players[0]
        # Must not raise when displayd socket is unavailable
        player.onAVStarted()
        player.onPlayBackStopped()
        player.onPlayBackEnded()


    def test_home_monitor_wakes_launcher_immediately_on_notification(self):
        shown = []

        class RecordingLauncher:
            def __init__(self, *args, **kwargs):
                pass
            def show(self):
                shown.append(True)
            def close(self):
                pass
            def window_id(self):
                return 13000
            def refresh_idle(self, active):
                pass
            def refresh_status(self):
                pass

        monitors = []
        class FakeMonitor:
            def __init__(self):
                monitors.append(self)
            def abortRequested(self):
                return True
            def waitForAbort(self, timeout):
                return True

        fake_xbmc = types.ModuleType("xbmc")
        fake_xbmc.LOGINFO = fake_xbmc.LOGWARNING = fake_xbmc.LOGERROR = 0
        fake_xbmc.log = lambda *a, **k: None
        fake_xbmc.Monitor = FakeMonitor
        fake_xbmc.Player = type("Player", (), {})
        fake_xbmc.getCondVisibility = lambda expr: False
        fake_xbmcgui = types.ModuleType("xbmcgui")
        fake_xbmcgui.getCurrentWindowId = lambda: 13000
        fake_xbmcgui.Window = lambda wid: types.SimpleNamespace(setProperty=lambda k, v: None)
        fake_launcher_mod = types.ModuleType("resources.lib.launcher")
        fake_launcher_mod.ADDON_PATH = "/tmp/addon"
        fake_launcher_mod.Launcher = RecordingLauncher
        fake_lang = types.ModuleType("resources.lib.lang")
        fake_lang.reconcile = lambda: None
        fake_resume = types.ModuleType("resources.lib.resume_recorder")
        fake_resume.start = lambda: None
        fake_lib = types.ModuleType("resources.lib")
        fake_lib.launcher = fake_launcher_mod
        fake_lib.lang = fake_lang
        fake_lib.resume_recorder = fake_resume
        fake_resources = types.ModuleType("resources")
        fake_resources.lib = fake_lib
        modules = {
            "xbmc": fake_xbmc, "xbmcgui": fake_xbmcgui, "resources": fake_resources,
            "resources.lib": fake_lib, "resources.lib.launcher": fake_launcher_mod,
            "resources.lib.lang": fake_lang, "resources.lib.resume_recorder": fake_resume,
        }
        with mock.patch.dict(sys.modules, modules):
            runpy.run_path(SERVICE_PY, run_name="service_under_test")
        self.assertTrue(monitors)
        monitors[0].onNotification("skin", "Other.home_shown", "")
        self.assertEqual(shown, [True])

    def test_service_adaptive_polling_idle_vs_playing(self):
        calls = []

        class RecordingDisplayClient:
            def set_kodi_playing(self, playing):
                calls.append(playing)

        def step1_start_playback(players):
            if not players:
                return True
            players[0].onAVStarted()
            return False

        def step2_stop_playback(players):
            if not players:
                return True
            players[0].onPlayBackStopped()
            return False

        _ns, wait_calls, players, _ = _run_service_with_script(
            [step1_start_playback, step2_stop_playback, True],
            display_client_cls=RecordingDisplayClient,
        )
        self.assertTrue(players, "service.py must instantiate PlaybackNotifier")
        self.assertEqual(len(wait_calls), 3)
        idle_poll, playing_poll, resumed_idle_poll = wait_calls
        self.assertGreaterEqual(idle_poll, 1.0, "Home idle poll must be >= 1.0s")
        self.assertGreaterEqual(playing_poll, 5.0, "Playing poll must be >= 5.0s")
        self.assertGreaterEqual(resumed_idle_poll, 1.0, "Resumed idle poll must be >= 1.0s")
        self.assertLess(resumed_idle_poll, playing_poll)
        self.assertEqual(calls, [True, False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
