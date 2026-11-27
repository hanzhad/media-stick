#!/usr/bin/env python3
"""Offline tests for HDMI / 3.5mm audio output switcher (Issue #122):
python3 tools/test-audio.py

Covers:
  - mediastick_audio Pure Core: stdlib-only / zero-xbmc, normalize_output,
    parse_wpctl_sinks (section boundaries + HDMI/headphones/other classification),
    pick_sink_id, build_set_default_cmd, build_set_volume_cmd
  - mediastick_audio Thin I/O Shell: MEDIASTICK_PREFS_DIR/audio-output atomic
    persistence (0644), strict write_output validation, wpctl_env, apply_output
    (set-default, ensure_full_volume, missing/stopped PipeWire resilience)
  - panel_audio & panel_audio_ui: /api/audio validation & persistence, marker
    injection, Звук row/page in bin/panel, balanced scripts
  - script.media-stick.home/service.py: startup apply_audio() reconciliation
"""
import sys

sys.dont_write_bytecode = True

import ast  # noqa: E402
import importlib  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
SERVICE_PY = os.path.join(ADDON, "service.py")
AUDIO_PY = os.path.join(LIB, "mediastick_audio.py")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")

TMP = tempfile.mkdtemp(prefix="test-audio-")
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["MEDIASTICK_SCREEN_DIR"] = os.path.join(TMP, "screen")

if LIB not in sys.path:
    sys.path.insert(0, LIB)


SAMPLE_WPCTL_PI = """\
PipeWire 'pipewire-0' [1.2.4, media@mediastick, cookie:2948104]
 └─ Clients:
        32. WirePlumber                         [1.2.4, media@mediastick, pid:612]
        45. kodi.bin                            [1.2.4, media@mediastick, pid:701]

Audio
 ├─ Devices:
 │      42. Built-in Audio                      [alsa]
 │      43. Built-in Audio                      [alsa]
 │
 ├─ Sinks:
 │  *   47. Built-in Audio Stereo               [vol: 0.40]
 │      48. Built-in Audio Digital Stereo (HDMI) [vol: 0.40]
 │
 ├─ Sources:
 │      49. Built-in Audio Analog Mono          [vol: 1.00]
 │
 ├─ Filters:
 │
 └─ Streams:
        58. kodi.bin
             60. output_FL       > bcm2835 Headphones:playback_FL\t[active]
             61. output_FR       > vc4-hdmi:playback_FR\t[active]

Video
 ├─ Devices:
 └─ Sinks:
        70. Dummy HDMI Video Sink

Settings
 └─ Default Configured Devices:
         0. Audio/Sink    alsa_output.platform-bcm2835_audio.analog-stereo
"""


class _CmdResult(tuple):
    """Compatible with both `(rc, stdout)` tuple unpacking and CompletedProcess attributes."""

    def __new__(cls, rc, stdout="", stderr=""):
        obj = super().__new__(cls, (rc, stdout))
        obj.returncode = rc
        obj.stdout = stdout
        obj.stderr = stderr
        return obj


def _require_module(tc: unittest.TestCase, dotted_name: str):
    try:
        return importlib.import_module(dotted_name)
    except ImportError as exc:
        tc.fail(f"{dotted_name} is not implemented: {exc}")


class TestAudioModuleHygiene(unittest.TestCase):
    """Pure Core stdlib-only and zero-xbmc import invariants."""

    def test_mediastick_audio_exists_and_has_zero_xbmc_imports(self):
        self.assertTrue(os.path.isfile(AUDIO_PY), f"Missing module: {AUDIO_PY}")
        with open(AUDIO_PY, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, filename=AUDIO_PY)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        xbmc_mods = {m for m in imported if m.startswith("xbmc")}
        self.assertEqual(xbmc_mods, set(), f"mediastick_audio must not import xbmc*: {xbmc_mods}")

        saved_xbmc = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("xbmc")}
        try:
            ma = _require_module(self, "mediastick_audio")
            self.assertEqual(tuple(ma.VALID_OUTPUTS), ("hdmi", "headphones"))
            self.assertEqual(ma.DEFAULT_OUTPUT, "hdmi")
            self.assertFalse(any(k.startswith("xbmc") for k in sys.modules))
        finally:
            sys.modules.update(saved_xbmc)


class TestAudioPureCore(unittest.TestCase):
    """In-memory combinatoric & boundary tests for mediastick_audio Pure Core."""

    def test_normalize_output_valid_and_boundary_inputs(self):
        ma = _require_module(self, "mediastick_audio")
        valid_headphones = (
            "headphones",
            "HEADPHONES",
            "  HEADPHONES\n",
            "\tHeadPhones  ",
        )
        for raw in valid_headphones:
            with self.subTest(raw=raw):
                self.assertEqual(ma.normalize_output(raw), "headphones")

        fallback_hdmi = (
            "hdmi",
            "  HDMI\n",
            "",
            "   ",
            None,
            "optical",
            "bluetooth",
            "headphone",          # adjacent singular boundary
            "headphones2",        # adjacent suffix boundary
            "headphones\nhdmi",   # multi-line injection boundary
            "3.5mm",
            0,
            1,
            True,
            False,
            ["headphones"],
            {"output": "headphones"},
        )
        for raw in fallback_hdmi:
            with self.subTest(raw=raw):
                self.assertEqual(ma.normalize_output(raw), "hdmi")

    def test_parse_wpctl_sinks_and_pick_sink_id_on_raspberry_pi_output(self):
        ma = _require_module(self, "mediastick_audio")
        sinks = ma.parse_wpctl_sinks(SAMPLE_WPCTL_PI)
        self.assertEqual([s["id"] for s in sinks], [47, 48])
        by_id = {s["id"]: s for s in sinks}

        self.assertTrue(by_id[47]["default"])
        self.assertEqual(by_id[47]["kind"], "headphones")
        self.assertIn("Built-in Audio Stereo", by_id[47]["name"])

        self.assertFalse(by_id[48]["default"])
        self.assertEqual(by_id[48]["kind"], "hdmi")
        self.assertIn("HDMI", by_id[48]["name"])

        # Must never leak Devices (42, 43), Sources (49), Streams (60, 61), Video Sinks (70), or Settings (0)
        for forbidden_id in (0, 42, 43, 49, 58, 60, 61, 70):
            self.assertNotIn(forbidden_id, by_id)

        self.assertEqual(ma.pick_sink_id(sinks, "hdmi"), 48)
        self.assertEqual(ma.pick_sink_id(sinks, "headphones"), 47)
        self.assertEqual(ma.pick_sink_id(sinks, "  HEADPHONES\n"), 47)
        self.assertEqual(ma.pick_sink_id(sinks, "optical"), 48)  # normalizes unknown -> hdmi

    def test_parse_wpctl_sinks_classification_and_section_stop_boundaries(self):
        ma = _require_module(self, "mediastick_audio")
        varied = "\n".join(
            [
                "Audio",
                " ├─ Sinks:",
                " │      51. vc4-hdmi                            [vol: 1.00]",
                " │  *   52. bcm2835 Headphones                  [vol: 1.00]",
                " │      53. Built-in Audio Analog Stereo        [vol: 0.85]",
                " │      54. Platform Mailbox Stereo             [vol: 1.00]",
                " │      55. Built-in Audio Digital Stereo (IEC958) [vol: 1.00]",
                " │      56. USB Audio DAC                       [vol: 0.70]",
                " └─ Filters:",
                "        88. filter-sink-that-must-be-ignored    [vol: 1.00]",
            ]
        )
        sinks = ma.parse_wpctl_sinks(varied)
        self.assertEqual([s["id"] for s in sinks], [51, 52, 53, 54, 55, 56])
        kinds = {s["id"]: s["kind"] for s in sinks}
        self.assertEqual(kinds[51], "hdmi")
        self.assertEqual(kinds[52], "headphones")
        self.assertEqual(kinds[53], "headphones")
        self.assertEqual(kinds[54], "headphones")
        # Digital IEC958 contains "digital" without "hdmi": must NOT be classified as "headphones" or "hdmi"
        self.assertEqual(kinds[55], "other")
        self.assertEqual(kinds[56], "other")

        # Stop cleanly at Streams: or Settings even when Sources:/Filters: are absent
        direct_streams = (
            "Audio\n"
            "  Sinks:\n"
            "  * 11. vc4-hdmi-0 [vol: 1.00]\n"
            "  Streams:\n"
            "    22. bcm2835 Headphones:playback_FL\n"
        )
        sinks_ds = ma.parse_wpctl_sinks(direct_streams)
        self.assertEqual(len(sinks_ds), 1)
        self.assertEqual((sinks_ds[0]["id"], sinks_ds[0]["default"], sinks_ds[0]["kind"]), (11, True, "hdmi"))
        self.assertIsNone(ma.pick_sink_id(sinks_ds, "headphones"))

        # Empty / missing Sinks block
        self.assertEqual(ma.parse_wpctl_sinks(""), [])
        self.assertEqual(ma.parse_wpctl_sinks("Audio\n ├─ Sinks:\n └─ Sources:\n"), [])
        self.assertIsNone(ma.pick_sink_id([], "hdmi"))

    def test_wpctl_command_builders(self):
        ma = _require_module(self, "mediastick_audio")
        self.assertEqual(ma.build_set_default_cmd(48), ["wpctl", "set-default", "48"])
        self.assertEqual(ma.build_set_default_cmd("47"), ["wpctl", "set-default", "47"])
        self.assertEqual(ma.build_set_volume_cmd(48), ["wpctl", "set-volume", "48", "1.0"])
        self.assertEqual(ma.build_set_volume_cmd(47, "0.75"), ["wpctl", "set-volume", "47", "0.75"])


class TestAudioThinIoShell(unittest.TestCase):
    """Thin I/O tests for prefs persistence, wpctl_env, and apply_output."""

    def setUp(self):
        self.prefs_dir = tempfile.mkdtemp(prefix="test-audio-prefs-")
        self.addCleanup(shutil.rmtree, self.prefs_dir, ignore_errors=True)

    def _patch_prefs(self, ma):
        stack = [mock.patch.dict(os.environ, {"MEDIASTICK_PREFS_DIR": self.prefs_dir})]
        if hasattr(ma, "PREFS_DIR"):
            stack.append(mock.patch.object(ma, "PREFS_DIR", self.prefs_dir))
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def test_read_and_write_output_atomic_0644_and_strict_validation(self):
        ma = _require_module(self, "mediastick_audio")
        self._patch_prefs(ma)

        # Missing file defaults to "hdmi"
        self.assertEqual(ma.read_output(), "hdmi")

        self.assertEqual(ma.write_output("headphones"), "headphones")
        self.assertEqual(ma.read_output(), "headphones")
        target = os.path.join(self.prefs_dir, "audio-output")
        self.assertTrue(os.path.isfile(target))
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o644)
        self.assertEqual(os.listdir(self.prefs_dir), ["audio-output"])  # no leftover temp files

        self.assertEqual(ma.write_output("hdmi"), "hdmi")
        self.assertEqual(ma.read_output(), "hdmi")

        # Strict validation rejects unknown values with ValueError and preserves existing file
        ma.write_output("headphones")
        for bad in ("", "optical", "bluetooth", "HDMI", "headphones\n", "../etc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ma.write_output(bad)
        self.assertEqual(ma.read_output(), "headphones")

        # Corrupt / unknown file content falls back to "hdmi" on read_output()
        with open(target, "w", encoding="utf-8") as f:
            f.write("spdif\n")
        self.assertEqual(ma.read_output(), "hdmi")

    def test_wpctl_env_sets_default_xdg_runtime_dir(self):
        ma = _require_module(self, "mediastick_audio")
        clean_env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with mock.patch.dict(os.environ, clean_env, clear=True):
            env_default = ma.wpctl_env()
            self.assertEqual(env_default["XDG_RUNTIME_DIR"], f"/run/user/{os.getuid()}")
            env_1000 = ma.wpctl_env(uid=1000)
            self.assertEqual(env_1000["XDG_RUNTIME_DIR"], "/run/user/1000")

    def test_apply_output_runs_wpctl_and_handles_missing_pipewire_gracefully(self):
        ma = _require_module(self, "mediastick_audio")
        self._patch_prefs(ma)
        ma.write_output("headphones")

        seen = []

        def fake_run(cmd, **kw):
            seen.append((list(cmd), kw))
            if cmd[:2] == ["wpctl", "status"]:
                return _CmdResult(0, SAMPLE_WPCTL_PI)
            return _CmdResult(0, "")

        # Uses saved preference when output=None, sets default without set-volume when ensure_full_volume=False
        res = ma.apply_output(run_cmd=fake_run, env={"XDG_RUNTIME_DIR": "/run/user/1000"})
        self.assertEqual(res, {"ok": True, "output": "headphones", "applied": True, "sink_id": 47})
        self.assertEqual(
            [c for c, _ in seen],
            [["wpctl", "status"], ["wpctl", "set-default", "47"]],
        )
        self.assertEqual(seen[0][1].get("timeout"), 3)

        # Explicit output="hdmi" + ensure_full_volume=True also sets volume to 1.0
        seen.clear()
        res_vol = ma.apply_output("hdmi", ensure_full_volume=True, run_cmd=fake_run)
        self.assertEqual(res_vol, {"ok": True, "output": "hdmi", "applied": True, "sink_id": 48})
        self.assertEqual(
            [c for c, _ in seen],
            [
                ["wpctl", "status"],
                ["wpctl", "set-default", "48"],
                ["wpctl", "set-volume", "48", "1.0"],
            ],
        )

        # Missing wpctl / stopped PipeWire / missing sink never raises -> applied=False, sink_id=None
        for failing_run in (
            lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("wpctl missing")),
            lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 3)),
            lambda cmd, **kw: _CmdResult(1, ""),
            lambda cmd, **kw: _CmdResult(0, "Audio\n ├─ Sinks:\n └─ Sources:\n"),
        ):
            res_down = ma.apply_output("headphones", ensure_full_volume=True, run_cmd=failing_run)
            self.assertIsInstance(res_down["ok"], bool)
            self.assertEqual(res_down["output"], "headphones")
            self.assertFalse(res_down["applied"])
            self.assertIsNone(res_down["sink_id"])


class TestPanelAudioAndServiceWiring(unittest.TestCase):
    """Tests for panel_audio, panel_audio_ui, bin/panel injection, and Kodi service.py startup."""

    def setUp(self):
        self.prefs_dir = tempfile.mkdtemp(prefix="test-panel-audio-")
        self.addCleanup(shutil.rmtree, self.prefs_dir, ignore_errors=True)

    def test_panel_audio_api_validates_persists_and_applies(self):
        ma = _require_module(self, "mediastick_audio")
        pa = _require_module(self, "panel_audio")
        self.assertEqual(pa.PATH, "/api/audio")

        stack = [mock.patch.dict(os.environ, {"MEDIASTICK_PREFS_DIR": self.prefs_dir})]
        if hasattr(ma, "PREFS_DIR"):
            stack.append(mock.patch.object(ma, "PREFS_DIR", self.prefs_dir))
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

        self.assertEqual(pa.current(), "hdmi")

        with mock.patch.object(
            ma,
            "apply_output",
            side_effect=lambda out=None, **kw: {"ok": True, "output": out, "applied": True, "sink_id": 47},
        ) as mock_apply:
            reply, code = pa.post("/api/audio", {"output": "headphones"})
            self.assertEqual((code, reply), (200, {"ok": True, "output": "headphones", "applied": True}))
            self.assertEqual(pa.current(), "headphones")
            mock_apply.assert_called_once()

            reply_hdmi, code_hdmi = pa.post("/api/audio", {"output": "hdmi"})
            self.assertEqual((code_hdmi, reply_hdmi), (200, {"ok": True, "output": "hdmi", "applied": True}))
            self.assertEqual(pa.current(), "hdmi")

        # When PipeWire is down (applied=False), preference is still saved and 200 ok=True returned
        with mock.patch.object(
            ma,
            "apply_output",
            return_value={"ok": True, "output": "headphones", "applied": False, "sink_id": None},
        ):
            reply_offline, code_offline = pa.post("/api/audio", {"output": "headphones"})
            self.assertEqual((code_offline, reply_offline), (200, {"ok": True, "output": "headphones", "applied": False}))
            self.assertEqual(pa.current(), "headphones")

        # Unknown / malformed payloads rejected with 400 and error="bad output"; choice unchanged
        for bad_body in (
            {"output": "bluetooth"},
            {"output": "optical"},
            {"output": ""},
            {"output": None},
            {"output": 42},
            {},
            [],
            "hdmi",
        ):
            with self.subTest(body=bad_body):
                reply_bad, code_bad = pa.post("/api/audio", bad_body)
                self.assertEqual(code_bad, 400)
                self.assertEqual(reply_bad, {"ok": False, "error": "bad output"})
        self.assertEqual(pa.current(), "headphones")

    def test_panel_audio_inject_and_page_markup(self):
        pa = _require_module(self, "panel_audio")
        _require_module(self, "panel_audio_ui")

        base = "<x>@@AUDIO_ROW@@@@AUDIO_SECTION@@@@AUDIO_TAIL@@</x>"
        injected = pa.inject(base)
        self.assertNotIn("@@", injected)
        for marker in ("@@AUDIO_ROW@@", "@@AUDIO_SECTION@@", "@@AUDIO_TAIL@@"):
            with self.assertRaises(ValueError):
                pa.inject(base.replace(marker, ""))

        loader = importlib.machinery.SourceFileLoader("panel_audio_page_check", PANEL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        panel_mod = importlib.util.module_from_spec(spec)
        loader.exec_module(panel_mod)
        page = panel_mod.PAGE
        src = open(PANEL, encoding="utf-8").read()

        lst = page.split('id="t-setlist"', 1)[1].split("</section>", 1)[0]
        self.assertIn('data-sp="audio"', lst)
        self.assertIn('<span class="sname">Звук</span>', lst)
        self.assertIn('id="sv-audio"', lst)

        self.assertRegex(page, r'<section id="t-audio"[^>]*data-tab="settings"[^>]*data-spage="audio"')
        audio_sec_and_tail = page.split('id="t-audio"', 1)[1]
        self.assertIn("HDMI (телевизор)", audio_sec_and_tail)
        self.assertIn("3.5 мм (наушники / колонки)", audio_sec_and_tail)
        self.assertIn("/api/audio", page)
        self.assertIn("3.5 мм", page)
        self.assertIn('s["audio_out"] = panel_audio.current()', src)
        self.assertIn("PAGE = panel_audio.inject(PAGE)", src)
        self.assertIn("panel_audio.PATH", src)

        tabs_spec = importlib.util.spec_from_file_location("tabs_check", os.path.join(ROOT, "tools", "test-panel-tabs.py"))
        tabs = importlib.util.module_from_spec(tabs_spec)
        tabs_spec.loader.exec_module(tabs)
        for script in re.findall(r"<script>(.*?)</script>", page, re.S):
            self.assertIsNone(tabs.unbalanced(script))

    def test_kodi_service_py_reconciles_audio_at_startup(self):
        with open(SERVICE_PY, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def apply_audio():", src)
        self.assertIn("    apply_audio()\n", src)
        self.assertLess(src.index("    apply_audio()\n"), src.index("monitor = HomeMonitor("))

        # Execute service.py module body without top-level main() call to test apply_audio() behaviorally
        tree = ast.parse(src, filename=SERVICE_PY)
        tree.body = [
            n for n in tree.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "main")
        ]
        logs = []
        fake_xbmc = types.ModuleType("xbmc")
        fake_xbmc.LOGINFO, fake_xbmc.LOGWARNING, fake_xbmc.LOGERROR = 1, 2, 3
        fake_xbmc.log = lambda msg, level=1: logs.append((msg, level))
        fake_xbmcgui = types.ModuleType("xbmcgui")
        fake_launcher = types.ModuleType("resources.lib.launcher")
        fake_launcher.ADDON_PATH = ADDON
        fake_launcher.Launcher = object
        fake_ma = types.ModuleType("mediastick_audio")
        calls = []
        fake_ma.apply_output = lambda *a, **kw: calls.append((a, kw)) or {"ok": True, "applied": True}

        ns = {"__name__": "service_audio_test", "__file__": SERVICE_PY}
        with mock.patch.dict(
            sys.modules,
            {
                "xbmc": fake_xbmc,
                "xbmcgui": fake_xbmcgui,
                "resources": types.ModuleType("resources"),
                "resources.lib": types.ModuleType("resources.lib"),
                "resources.lib.launcher": fake_launcher,
                "mediastick_audio": fake_ma,
            },
        ):
            exec(compile(tree, SERVICE_PY, "exec"), ns)
            ns["apply_audio"]()
            self.assertEqual(len(calls), 1)

            # Exceptions inside apply_output are caught & logged, never raised out of startup
            fake_ma.apply_output = mock.Mock(side_effect=RuntimeError("wpctl boom"))
            ns["apply_audio"]()
            self.assertTrue(any("RuntimeError" in m or "audio" in m for m, _ in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
