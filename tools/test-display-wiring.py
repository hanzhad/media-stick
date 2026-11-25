#!/usr/bin/env python3
"""Offline tests for Issue #32: displayd wiring, DRM splash deduplication, and PipeWire config.

Run: python3 tools/test-display-wiring.py
"""
import sys

sys.dont_write_bytecode = True

import ast  # noqa: E402
import asyncio  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB_DIR = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
DRM_PATH = os.path.join(LIB_DIR, "mediastick_drm.py")
DISPLAYD_PATH = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "mediastick-displayd")
AIRPLAY_PATH = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "airplay")
MIRACAST_PATH = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "miracast")

AIRPLAY_SERVICE = os.path.join(ROOT, "device", "files", "etc", "systemd", "system", "airplay.service")
MIRACAST_SERVICE = os.path.join(ROOT, "device", "files", "etc", "systemd", "system", "miracast.service")
WEBAPP_SERVICE = os.path.join(ROOT, "device", "files", "etc", "systemd", "system", "web-app@.service")

WEBAPP_ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.webapp", "default.py")
PIPEWIRE_CONF = os.path.join(ROOT, "device", "files", "etc", "pipewire", "pipewire.conf.d", "10-media-stick.conf")
WIREPLUMBER_CONF = os.path.join(
    ROOT, "device", "files", "etc", "wireplumber", "wireplumber.conf.d", "50-media-stick-no-bt.conf"
)
ASOUND_CONF = os.path.join(ROOT, "device", "files", "etc", "asound.conf")
BOOTSTRAP_SH = os.path.join(ROOT, "device", "bootstrap.sh")

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_script(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _FakeSystemExecutor:
    """In-memory DisplayServer executor for offline wiring tests."""

    def __init__(self):
        self.calls = []

    async def stop_unit(self, unit):
        self.calls.append(("stop_unit", unit))

    async def start_unit(self, unit):
        self.calls.append(("start_unit", unit))

    async def draw_splash(self):
        self.calls.append(("draw_splash", None))

    async def flush(self):
        self.calls.append(("flush", None))

    async def cec_standby(self):
        self.calls.append(("cec_standby", None))

    async def cec_wake(self):
        self.calls.append(("cec_wake", None))

    async def kms_dpms(self, on):
        self.calls.append(("kms_dpms", bool(on)))

    async def set_governor(self, governor):
        self.calls.append(("set_governor", governor))

    async def p2p_pause(self):
        self.calls.append(("p2p_pause", None))

    async def p2p_resume(self):
        self.calls.append(("p2p_resume", None))


class _LiveDisplayServer:
    """Context manager running mediastick-displayd on a temporary Unix socket."""

    def __init__(self):
        self.tmpdir = None
        self.sock_path = None
        self.loop = None
        self.thread = None
        self.server = None
        self.executor = _FakeSystemExecutor()
        self._old_env = None

    def __enter__(self):
        daemon = _load_script("mediastick_displayd_wiring", DISPLAYD_PATH)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sock_path = os.path.join(self.tmpdir.name, "display.sock")
        self._old_env = os.environ.get("DISPLAYD_SOCK")
        os.environ["DISPLAYD_SOCK"] = self.sock_path
        self.loop = asyncio.new_event_loop()
        self.server = daemon.DisplayServer(sock_path=self.sock_path, executor=self.executor)
        self.loop.run_until_complete(self.server.start())
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        if self.server is not None and self.loop is not None:
            fut = asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
            fut.result(timeout=2.0)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.loop is not None:
            self.loop.close()
        if self._old_env is None:
            os.environ.pop("DISPLAYD_SOCK", None)
        else:
            os.environ["DISPLAYD_SOCK"] = self._old_env
        if self.tmpdir is not None:
            self.tmpdir.cleanup()


class DrmDeduplicationTests(unittest.TestCase):
    """Shared mediastick_drm module and removal of inline DRM/splash code from airplay & miracast."""

    REQUIRED_SYMBOLS = (
        "ModeInfo",
        "Resources",
        "Connector",
        "Encoder",
        "CreateDumb",
        "MapDumb",
        "splash_pixels",
        "put_rows",
        "paint_splash",
        "light_screen",
        "SPLASH",
        "SPLASH_CACHE",
        "CARD",
    )

    INLINE_CLASSES = {"ModeInfo", "Resources", "Connector", "Encoder", "CreateDumb", "MapDumb"}
    INLINE_FUNCS = {"splash_pixels", "put_rows", "paint_splash", "light_screen"}

    def _load_drm(self):
        self.assertTrue(os.path.exists(DRM_PATH), f"missing {DRM_PATH}")
        return _load_script("mediastick_drm", DRM_PATH)

    def test_mediastick_drm_exports_required_symbols(self):
        drm = self._load_drm()
        for sym in self.REQUIRED_SYMBOLS:
            with self.subTest(symbol=sym):
                self.assertTrue(hasattr(drm, sym), f"mediastick_drm missing {sym}")

    def test_put_rows_padded_and_unpadded(self):
        drm = self._load_drm()
        data = bytes(range(2 * 4)) * 2
        mem_padded = bytearray(2 * 12)
        drm.put_rows(mem_padded, data, 2, 2, 12)
        self.assertEqual(bytes(mem_padded), data[:8] + b"\0" * 4 + data[8:] + b"\0" * 4)

        unpadded = b"\x01\x02\x03\x00" * 6
        mem_exact = bytearray(len(unpadded))
        drm.put_rows(mem_exact, unpadded, 3, 2, 12)
        self.assertEqual(bytes(mem_exact), unpadded)

    def test_splash_pixels_cache_and_missing(self):
        drm = self._load_drm()
        with tempfile.TemporaryDirectory() as d:
            png = os.path.join(d, "splash.png")
            with open(png, "wb"):
                pass
            os.utime(png, (1000, 1000))
            raw = os.path.join(d, "splash-2x1.xrgb")
            with open(raw, "wb") as f:
                f.write(b"\x10\x12\x18\x00" * 2)
            self.assertEqual(drm.splash_pixels(2, 1, png, d), b"\x10\x12\x18\x00" * 2)
            self.assertIsNone(drm.splash_pixels(2, 1, os.path.join(d, "none.png"), d))

    def test_airplay_and_miracast_do_not_define_drm_structs_or_splash_inline(self):
        for label, path in (("airplay", AIRPLAY_PATH), ("miracast", MIRACAST_PATH)):
            tree = ast.parse(_read_text(path), filename=path)
            defined_classes = {
                node.name for node in tree.body if isinstance(node, ast.ClassDef)
            }
            defined_funcs = {
                node.name for node in tree.body if isinstance(node, ast.FunctionDef)
            }
            with self.subTest(script=label, kind="classes"):
                overlap = sorted(defined_classes & self.INLINE_CLASSES)
                self.assertEqual(
                    overlap, [], f"{label} still defines inline DRM classes: {overlap}"
                )
            with self.subTest(script=label, kind="functions"):
                overlap = sorted(defined_funcs & self.INLINE_FUNCS)
                self.assertEqual(
                    overlap, [], f"{label} still defines inline splash/DRM functions: {overlap}"
                )

    def test_airplay_and_miracast_reexport_drm_symbols(self):
        drm = self._load_drm()
        airplay = _load_script("airplay_drm_check", AIRPLAY_PATH)
        miracast = _load_script("miracast_drm_check", MIRACAST_PATH)
        for label, mod in (("airplay", airplay), ("miracast", miracast)):
            for sym in self.REQUIRED_SYMBOLS:
                with self.subTest(script=label, symbol=sym):
                    self.assertTrue(hasattr(mod, sym), f"{label} must re-export {sym}")
                    self.assertIs(
                        getattr(mod, sym),
                        getattr(drm, sym),
                        f"{label}.{sym} must be imported from mediastick_drm",
                    )


class AirPlayWiringTests(unittest.TestCase):
    """AirPlay displayd wiring, audio-only Kodi pause, 256 KB rolling log, and no setpriv as media."""

    def setUp(self):
        self.airplay = _load_script("airplay_wiring_test", AIRPLAY_PATH)

    def test_audio_only_connection_does_not_trigger_screen_take(self):
        self.assertIsNone(
            self.airplay.START.search("changed audio connection"),
            "audio-only AirPlay must not match START (which takes the DRM screen)",
        )
        for video_line in (
            "connection request from 192.168.1.50",
            "Begin streaming to GStreamer video pipeline",
        ):
            with self.subTest(line=video_line):
                self.assertIsNotNone(self.airplay.START.search(video_line))

        src = _read_text(AIRPLAY_PATH)
        self.assertIn("changed audio connection", src)
        self.assertRegex(
            src,
            r"Player\.PlayPause|Player\.GetActivePlayers",
            "airplay must pause Kodi via JSON-RPC on audio-only connection",
        )

    def test_airplay_log_cap_is_256kb_and_rolls_over(self):
        self.assertEqual(
            self.airplay.LOG_MAX,
            256 << 10,
            f"airplay LOG_MAX should be 256 KB (262144), got {self.airplay.LOG_MAX}",
        )
        src = _read_text(AIRPLAY_PATH)
        self.assertNotIn(
            "if log.tell() < LOG_MAX:",
            src,
            "airplay must roll/truncate airplay.log instead of freezing output at LOG_MAX",
        )

    def test_airplay_drops_setpriv_when_running_as_media(self):
        with mock.patch("os.geteuid", return_value=1000):
            self.assertNotIn("setpriv", self.airplay.uxplay(7))
            self.assertNotIn("setpriv", self.airplay.drawer())

    def test_airplay_screen_take_and_give_back_via_displayd(self):
        import mediastick_display as md

        with _LiveDisplayServer() as srv, tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "airplay.flag")
            sys_calls = []

            def fake_systemctl(*args):
                sys_calls.append(args)
                return subprocess.CompletedProcess(["systemctl", *args], 0, stdout="", stderr="")

            relay = self.airplay.Relay()
            screen = self.airplay.Screen(relay)
            with mock.patch.object(self.airplay, "FLAG", flag), \
                 mock.patch.object(self.airplay, "systemctl", side_effect=fake_systemctl), \
                 mock.patch.object(self.airplay, "light_screen", side_effect=lambda: (os.open(os.devnull, os.O_RDONLY), 1920, 1080)), \
                 mock.patch.object(screen, "draw"):
                screen.take()
                st_taken = md.DisplayClient(srv.sock_path).status()
                self.assertEqual(st_taken["state"], "CAST_AIRPLAY")
                self.assertFalse(
                    any(c[:2] == ("stop", "kodi.service") for c in sys_calls),
                    f"airplay must not stop kodi.service directly when displayd is up: {sys_calls}",
                )

                screen.give_back()
                st_back = md.DisplayClient(srv.sock_path).status()
                self.assertEqual(st_back["state"], "KODI")
                self.assertFalse(
                    any("kodi.service" in c for c in sys_calls if c[0] == "start"),
                    f"airplay must not start kodi.service directly when displayd is up: {sys_calls}",
                )

    def test_airplay_screen_falls_back_to_systemctl_when_displayd_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_sock = os.path.join(tmp, "missing.sock")
            flag = os.path.join(tmp, "airplay.flag")
            sys_calls = []

            def fake_systemctl(*args):
                sys_calls.append(args)
                return subprocess.CompletedProcess(["systemctl", *args], 0, stdout="", stderr="")

            old_env = os.environ.get("DISPLAYD_SOCK")
            os.environ["DISPLAYD_SOCK"] = missing_sock
            try:
                relay = self.airplay.Relay()
                screen = self.airplay.Screen(relay)
                with mock.patch.object(self.airplay, "FLAG", flag), \
                     mock.patch.object(self.airplay, "systemctl", side_effect=fake_systemctl), \
                     mock.patch.object(self.airplay, "light_screen", side_effect=lambda: (os.open(os.devnull, os.O_RDONLY), 1920, 1080)), \
                     mock.patch.object(screen, "draw"):
                    screen.take()
                    self.assertIn(("stop", "kodi.service"), sys_calls)
                    screen.give_back()
                    self.assertTrue(
                        any(c[0] == "start" and "kodi.service" in c for c in sys_calls),
                        f"fallback give_back must start kodi.service: {sys_calls}",
                    )
            finally:
                if old_env is None:
                    os.environ.pop("DISPLAYD_SOCK", None)
                else:
                    os.environ["DISPLAYD_SOCK"] = old_env


class MiracastWiringTests(unittest.TestCase):
    """Miracast displayd wiring and p2p_allowed subscription."""

    def setUp(self):
        self.miracast = _load_script("miracast_wiring_test", MIRACAST_PATH)

    def test_miracast_screen_take_and_give_back_via_displayd(self):
        import mediastick_display as md

        with _LiveDisplayServer() as srv, tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "miracast.flag")
            sys_calls = []

            def fake_systemctl(*args):
                sys_calls.append(args)
                return subprocess.CompletedProcess(["systemctl", *args], 0, stdout="", stderr="")

            screen = self.miracast.Screen(
                systemctl=fake_systemctl,
                light=lambda: (os.open(os.devnull, os.O_RDONLY), 1920, 1080),
            )
            with mock.patch.object(self.miracast, "FLAG", flag):
                screen.take()
                st_taken = md.DisplayClient(srv.sock_path).status()
                self.assertEqual(st_taken["state"], "CAST_MIRACAST")
                self.assertFalse(
                    any(c[:2] == ("stop", "kodi.service") for c in sys_calls),
                    f"miracast must not stop kodi.service directly when displayd is up: {sys_calls}",
                )

                screen.give_back()
                st_back = md.DisplayClient(srv.sock_path).status()
                self.assertEqual(st_back["state"], "KODI")
                self.assertFalse(
                    any("kodi.service" in c for c in sys_calls if c[0] == "start"),
                    f"miracast must not start kodi.service directly when displayd is up: {sys_calls}",
                )

    def test_miracast_screen_falls_back_to_systemctl_when_displayd_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_sock = os.path.join(tmp, "missing.sock")
            flag = os.path.join(tmp, "miracast.flag")
            sys_calls = []

            def fake_systemctl(*args):
                sys_calls.append(args)
                return subprocess.CompletedProcess(["systemctl", *args], 0, stdout="", stderr="")

            old_env = os.environ.get("DISPLAYD_SOCK")
            os.environ["DISPLAYD_SOCK"] = missing_sock
            try:
                screen = self.miracast.Screen(
                    systemctl=fake_systemctl,
                    light=lambda: (os.open(os.devnull, os.O_RDONLY), 1920, 1080),
                )
                with mock.patch.object(self.miracast, "FLAG", flag):
                    screen.take()
                    self.assertIn(("stop", "kodi.service"), sys_calls)
                    screen.give_back()
                    self.assertTrue(
                        any(c[0] == "start" and "kodi.service" in c for c in sys_calls),
                        f"fallback give_back must start kodi.service: {sys_calls}",
                    )
            finally:
                if old_env is None:
                    os.environ.pop("DISPLAYD_SOCK", None)
                else:
                    os.environ["DISPLAYD_SOCK"] = old_env

    def test_miracast_subscribes_to_p2p_allowed_events(self):
        src = _read_text(MIRACAST_PATH)
        self.assertIn("subscribe", src, "miracast must subscribe to mediastick-displayd events")
        self.assertIn("p2p_allowed", src, "miracast must react to p2p_allowed events")

        # Verify Advertiser pauses p2p_listen when paused=True and resumes when paused=False
        wpa_calls = []

        def fake_run(cmd):
            wpa_calls.append(cmd)
            if cmd[:2] == ["ip", "-4"]:
                return (0, "2: wlan0    inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0")
            if cmd[:2] == ["busctl", "call"]:
                return (0, 'o "/fi/w1/wpa_supplicant1/Interfaces/0"')
            if cmd[-2:] == ["get", "wifi_display"]:
                return (0, "1\n")
            return (0, "OK\n")

        adv = self.miracast.Advertiser(fake_run, "Media Stick", "mediastick")
        adv.pause()
        self.assertTrue(adv.paused)
        wpa_calls.clear()
        adv.tick(10.0)
        self.assertEqual(wpa_calls, [], "paused Advertiser must not issue p2p_listen")

        adv.resume()
        self.assertFalse(adv.paused)
        adv.tick(10.0)
        self.assertTrue(
            any("p2p_listen" in c for c in wpa_calls),
            f"resumed Advertiser must issue p2p_listen: {wpa_calls}",
        )


class SystemdUnitWiringTests(unittest.TestCase):
    """Systemd unit ordering, user drop, and web-app@.service race removal."""

    def test_airplay_service_runs_as_media_after_displayd(self):
        text = _read_text(AIRPLAY_SERVICE)
        for directive in (
            "User=media",
            "Group=media",
            "SupplementaryGroups=video render audio input",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, text)
        self.assertRegex(text, r"^After=.*mediastick-displayd\.service", re.MULTILINE)

    def test_miracast_service_orders_after_displayd(self):
        text = _read_text(MIRACAST_SERVICE)
        self.assertRegex(text, r"^After=.*mediastick-displayd\.service", re.MULTILINE)

    def test_webapp_service_has_no_kodi_race_and_notifies_displayd(self):
        text = _read_text(WEBAPP_SERVICE)
        conflicts = re.findall(r"^Conflicts=(.*)$", text, re.MULTILINE)
        for line in conflicts:
            self.assertNotIn(
                "kodi.service",
                line,
                "web-app@.service must not declare Conflicts=kodi.service",
            )
        exec_stop_post = re.findall(r"^ExecStopPost=(.*)$", text, re.MULTILINE)
        self.assertTrue(exec_stop_post, "web-app@.service must have ExecStopPost notifying displayd")
        joined = "\n".join(exec_stop_post)
        self.assertNotIn("systemctl", joined, "ExecStopPost must not run systemctl start kodi.service")
        self.assertNotIn("kodi.service", joined, "ExecStopPost must not directly start kodi.service")
        self.assertRegex(
            joined,
            r"mediastick_display|DisplayClient|display\.sock",
            "ExecStopPost must notify mediastick-displayd on stop",
        )


class WebAppAddonTests(unittest.TestCase):
    """Kodi script.media-stick.webapp allowlist and DisplayClient routing with fallback."""

    def _run_addon(self, app_arg, acquire_side_effect=None):
        acquire_calls = []
        popen_calls = []
        notif_calls = []

        class FakeDialog:
            def notification(self, *args, **kwargs):
                notif_calls.append((args, kwargs))

        fake_xbmcgui = types.SimpleNamespace(Dialog=FakeDialog)

        class FakeDisplayClient:
            def acquire(self, target, owner=None, app=None):
                acquire_calls.append((target, owner, app))
                if acquire_side_effect is not None:
                    raise acquire_side_effect

        fake_md = types.SimpleNamespace(DisplayClient=FakeDisplayClient)

        def fake_popen(cmd, *args, **kwargs):
            popen_calls.append(cmd)
            return mock.MagicMock()

        src = _read_text(WEBAPP_ADDON)
        code = compile(src, WEBAPP_ADDON, "exec")
        with mock.patch.dict(sys.modules, {"xbmcgui": fake_xbmcgui, "mediastick_display": fake_md}), \
             mock.patch.object(sys, "argv", [WEBAPP_ADDON, app_arg]), \
             mock.patch("subprocess.Popen", side_effect=fake_popen):
            exec(code, {"__name__": "__main__", "__file__": WEBAPP_ADDON})

        return acquire_calls, popen_calls, notif_calls

    def test_webapp_addon_accepts_only_five_allowed_apps_via_displayd(self):
        for app in ("netflix", "disney", "prime", "max", "youtube"):
            with self.subTest(app=app):
                acq, popen, _ = self._run_addon(app)
                self.assertEqual(acq, [("WEB_APP", "kodi", app)])
                self.assertEqual(popen, [], f"displayd launch should not call Popen for {app}")

    def test_webapp_addon_falls_back_to_systemctl_when_displayd_fails(self):
        acq, popen, _ = self._run_addon("netflix", acquire_side_effect=OSError("no socket"))
        self.assertEqual(acq, [("WEB_APP", "kodi", "netflix")])
        self.assertEqual(len(popen), 1)
        self.assertEqual(
            popen[0][-3:],
            ["start", "--no-block", "web-app@netflix.service"],
        )

    def test_webapp_addon_rejects_unknown_apps(self):
        bad_apps = ["", "hulu", "twitch", "Netflix", "netflix ", "../netflix", "foo-bar", "youtube;id"]
        for app in bad_apps:
            with self.subTest(app=app):
                acq, popen, _ = self._run_addon(app)
                self.assertEqual(acq, [], f"unknown app {app!r} must not call DisplayClient.acquire")
                self.assertEqual(popen, [], f"unknown app {app!r} must not call subprocess.Popen")


class PipeWireAudioConfigTests(unittest.TestCase):
    """Minimal PipeWire + WirePlumber + ALSA config and bootstrap packages."""

    def test_pipewire_10_media_stick_conf(self):
        self.assertTrue(os.path.exists(PIPEWIRE_CONF), f"missing {PIPEWIRE_CONF}")
        text = _read_text(PIPEWIRE_CONF)
        self.assertIn("48000", text)

    def test_wireplumber_50_no_bt_conf(self):
        self.assertTrue(os.path.exists(WIREPLUMBER_CONF), f"missing {WIREPLUMBER_CONF}")
        text = _read_text(WIREPLUMBER_CONF)
        for token in ("bluez", "v4l2", "libcamera"):
            with self.subTest(monitor=token):
                self.assertIn(token, text)
        self.assertRegex(text, r"(disabled|false)")

    def test_asound_conf_routes_through_pipewire(self):
        text = _read_text(ASOUND_CONF)
        self.assertRegex(text, r'pcm\.!default\s+["\']?pipewire')
        self.assertRegex(text, r'ctl\.!default\s+["\']?pipewire')
        self.assertIn("vc4hdmi", text)

    def test_bootstrap_installs_pipewire_packages(self):
        text = _read_text(BOOTSTRAP_SH)
        m = re.search(r"^pkgs=\(([^)]+)\)", text, re.MULTILINE)
        self.assertIsNotNone(m, "pkgs=(...) not found in device/bootstrap.sh")
        pkgs = m.group(1).split()
        for pkg in ("pipewire", "wireplumber", "pipewire-alsa", "v4l-utils"):
            with self.subTest(pkg=pkg):
                self.assertIn(pkg, pkgs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
