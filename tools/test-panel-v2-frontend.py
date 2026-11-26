#!/usr/bin/env python3
"""Offline unit + live-socket tests for Panel v2 static ES-module PWA frontend (Issue #40):
python3 tools/test-panel-v2-frontend.py

Covers:
  - panel_core.static_files: Pure Core + Thin File Server, gzip, strong ETag, 304 Not Modified,
    immutable Cache-Control for ?v=<hash> assets, strict path-traversal rejection
  - PWA assets: /manifest.webmanifest, /sw.js, /icon-192.png, /icon-512.png
  - Six /static/*.js ES modules: ws-client.js, trackpad.js, power-banner.js, screen-v2.js,
    diagnostics.js, v2-boot.js (balanced syntax, binary <Bff> encoder, /shot.jpg, /api/power,
    /api/logs, /api/pin, SW registration)
  - panel.H: mounted static routes, gzip+ETag on GET /, manifest + apple-touch-icon + v2-boot.js,
    document.hidden polling pause, Trackpad, Active-Screen Switcher + Standby/Wake, Diagnostics & LAN PIN UI
"""
import gzip
import http.client
import importlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
WEB_DIR = os.path.join(ROOT, "device", "files", "usr", "local", "share", "media-stick", "web")

TMP = tempfile.mkdtemp(prefix="test-panel-v2-fe-")
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["MEDIASTICK_SCREEN_DIR"] = os.path.join(TMP, "screen")
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

loader = importlib.machinery.SourceFileLoader("panel_v2_fe_under_test", PANEL)
spec = importlib.util.spec_from_loader(loader.name, loader)
panel = importlib.util.module_from_spec(spec)
loader.exec_module(panel)


def _require_module(testcase, dotted_name):
    """Import a panel_core module; fail with AssertionError if not yet implemented."""
    try:
        return importlib.import_module(dotted_name)
    except ImportError as exc:
        testcase.fail(f"{dotted_name} is not implemented: {exc}")


def _unbalanced(js):
    """Return snippet of the first mismatched bracket, or None if balanced."""
    stack, i, n, prev = [], 0, len(js), ""
    pairs = {")": "(", "]": "[", "}": "{"}
    while i < n:
        c = js[i]
        if c in "'\"`":
            j = i + 1
            while j < n and js[j] != c:
                j += 2 if js[j] == "\\" else 1
            i, prev = j + 1, "x"
            continue
        if js.startswith("//", i):
            i = js.find("\n", i)
            i = n if i < 0 else i
            continue
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            if end < 0:
                return js[i:i + 40]
            i = end + 2
            continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};"):
            j, cls = i + 1, False
            while j < n and (cls or js[j] != "/"):
                if js[j] == "\\":
                    j += 1
                elif js[j] == "[":
                    cls = True
                elif js[j] == "]":
                    cls = False
                j += 1
            i, prev = j + 1, "x"
            continue
        if c in "([{":
            stack.append((c, i))
        elif c in pairs:
            if not stack or stack.pop()[0] != pairs[c]:
                return js[max(0, i - 60):i + 20]
        if not c.isspace():
            prev = c
        i += 1
    return js[stack[-1][1]:stack[-1][1] + 80] if stack else None


def _hdr_ci(headers, name):
    """Case-insensitive header lookup."""
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None


class _PanelServerMixin:
    @classmethod
    def start_panel_server(cls):
        panel.kodi = lambda m, p=None, timeout=3: [] if m == "Player.GetActivePlayers" else {}
        panel.web_app_on = lambda: False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def stop_panel_server(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"Host": f"localhost:{self.port}"}
        if headers:
            hdrs.update(headers)
        c.request("GET", path, headers=hdrs)
        r = c.getresponse()
        raw = r.read()
        resp_hdrs = dict(r.getheaders())
        c.close()
        return r.status, resp_hdrs, raw


# ---- 1. panel_core.static_files ----

class TestStaticFilesModule(unittest.TestCase):
    def test_static_files_module_and_pure_core(self):
        sf = _require_module(self, "panel_core.static_files")
        self.assertTrue(os.path.isdir(WEB_DIR), f"missing web dir {WEB_DIR}")
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "static"), exist_ok=True)
            sample = b"console.log('hello media-stick');\n" * 20
            with open(os.path.join(tmp, "static", "app.js"), "wb") as f:
                f.write(sample)
            with open(os.path.join(tmp, "manifest.webmanifest"), "wb") as f:
                f.write(b'{"name":"Media Stick","display":"standalone"}')

            if hasattr(sf, "StaticAssets"):
                assets = sf.StaticAssets(root=tmp)
                res = assets.serve("/static/app.js?v=abc123", headers={"Accept-Encoding": "gzip"})
            elif hasattr(sf, "serve_static"):
                res = sf.serve_static("/static/app.js?v=abc123", headers={"Accept-Encoding": "gzip"}, root=tmp)
            else:
                self.fail("panel_core.static_files must expose StaticAssets or serve_static")

            code, hdrs, body = res[0], dict(res[1]), res[2]
            self.assertEqual(code, 200)
            self.assertEqual(_hdr_ci(hdrs, "Content-Encoding"), "gzip")
            self.assertEqual(gzip.decompress(body), sample)
            etag = _hdr_ci(hdrs, "ETag")
            self.assertTrue(etag and etag.startswith('"') and not etag.startswith("W/"), f"expected strong ETag, got {etag!r}")
            cc = _hdr_ci(hdrs, "Cache-Control") or ""
            self.assertIn("public", cc)
            self.assertIn("max-age=31536000", cc)
            self.assertIn("immutable", cc)

            if hasattr(sf, "StaticAssets"):
                res304 = assets.serve("/static/app.js?v=abc123", headers={"Accept-Encoding": "gzip", "If-None-Match": etag})
            else:
                res304 = sf.serve_static("/static/app.js?v=abc123", headers={"Accept-Encoding": "gzip", "If-None-Match": etag}, root=tmp)
            self.assertEqual(res304[0], 304)
            self.assertEqual(res304[2], b"")


# ---- 2. Live HTTP serving of static PWA assets & traversal rejection ----

class TestStaticRoutesServed(_PanelServerMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_panel_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_panel_server()

    def test_path_traversal_rejected(self):
        for bad in (
            "/static/../../etc/passwd",
            "/static/%2e%2e/panel",
            "/static/..%2f..%2fetc/passwd",
            "/static/sub/../../../etc/shadow",
            "/static/nonexistent-file-404.js",
        ):
            code, _, _ = self._get(bad)
            self.assertIn(code, (403, 404), f"{bad} returned {code}, expected 403/404")

    def test_manifest_webmanifest_valid_json_and_pwa_fields(self):
        code, hdrs, raw = self._get("/manifest.webmanifest")
        self.assertEqual(code, 200)
        ctype = (_hdr_ci(hdrs, "Content-Type") or "").lower()
        self.assertTrue(
            "manifest+json" in ctype or "application/json" in ctype,
            f"unexpected manifest Content-Type: {ctype!r}",
        )
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data.get("name") or data.get("short_name"))
        self.assertEqual(data.get("display"), "standalone")
        self.assertEqual((data.get("theme_color") or "").lower(), "#121620")
        self.assertEqual((data.get("background_color") or "").lower(), "#121620")
        icons = data.get("icons") or []
        sizes = {ic.get("sizes"): ic for ic in icons}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        self.assertEqual(sizes["192x192"].get("type"), "image/png")
        self.assertEqual(sizes["512x512"].get("type"), "image/png")

    def test_pwa_icons_are_real_pngs_with_exact_dimensions(self):
        for path, expected_size in (("/icon-192.png", (192, 192)), ("/icon-512.png", (512, 512))):
            code, hdrs, raw = self._get(path)
            self.assertEqual(code, 200, path)
            self.assertEqual(_hdr_ci(hdrs, "Content-Type"), "image/png", path)
            self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"), f"{path} is not PNG")
            im = Image.open(io.BytesIO(raw))
            self.assertEqual(im.format, "PNG", path)
            self.assertEqual(im.size, expected_size, path)

    def test_service_worker_served_and_has_offline_shell(self):
        code, hdrs, raw = self._get("/sw.js")
        self.assertEqual(code, 200)
        ctype = (_hdr_ci(hdrs, "Content-Type") or "").lower()
        self.assertIn("javascript", ctype)
        src = raw.decode("utf-8")
        self.assertIsNone(_unbalanced(src), "sw.js has unbalanced brackets")
        self.assertEqual(re.findall(r"@@\w+@@", src), [])
        self.assertIn("Ищу приставку…", src)
        self.assertIn("/static/", src)

    def test_service_worker_cache_version_bumped(self):
        code, _, raw = self._get("/sw.js")
        self.assertEqual(code, 200)
        src = raw.decode("utf-8")
        self.assertIn("ms-panel-v2-4", src)
        self.assertNotIn("ms-panel-v2-3", src)
        self.assertIn("/static/touchbar.js", src)
        self.assertIn("apple-mobile-web-app-capable", src)
        self.assertIn("black-translucent", src)
        self.assertIn("env(safe-area-inset-", src)
        self.assertIn("100svh", src)

    def test_gzip_etag_304_and_immutable_cache_headers(self):
        code, hdrs, raw = self._get("/static/ws-client.js?v=test123", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(code, 200)
        self.assertEqual(_hdr_ci(hdrs, "Content-Encoding"), "gzip")
        etag = _hdr_ci(hdrs, "ETag")
        self.assertTrue(etag and etag.startswith('"') and not etag.startswith("W/"))
        cc = _hdr_ci(hdrs, "Cache-Control") or ""
        self.assertIn("public", cc)
        self.assertIn("max-age=31536000", cc)
        self.assertIn("immutable", cc)
        plain = gzip.decompress(raw).decode("utf-8")
        self.assertIn("WebSocket", plain)

        code304, _, body304 = self._get(
            "/static/ws-client.js?v=test123",
            headers={"Accept-Encoding": "gzip", "If-None-Match": etag},
        )
        self.assertEqual(code304, 304)
        self.assertEqual(body304, b"")

        code200, _, _ = self._get(
            "/static/ws-client.js?v=test123",
            headers={"Accept-Encoding": "gzip", "If-None-Match": '"stale-etag"'},
        )
        self.assertEqual(code200, 200)


# ---- 3. Six /static/*.js ES modules ----

class TestStaticEsModules(_PanelServerMixin, unittest.TestCase):
    MODULES = (
        "ws-client.js",
        "trackpad.js",
        "power-banner.js",
        "screen-v2.js",
        "diagnostics.js",
        "touchbar.js",
        "v2-boot.js",
    )

    @classmethod
    def setUpClass(cls):
        cls.start_panel_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_panel_server()

    def _fetch_js(self, name):
        code, hdrs, raw = self._get(f"/static/{name}")
        self.assertEqual(code, 200, f"/static/{name} returned {code}")
        ctype = (_hdr_ci(hdrs, "Content-Type") or "").lower()
        self.assertIn("javascript", ctype, f"/static/{name} Content-Type={ctype!r}")
        src = raw.decode("utf-8")
        self.assertIsNone(_unbalanced(src), f"/static/{name} has unbalanced brackets")
        self.assertEqual(re.findall(r"@@\w+@@", src), [])
        return src

    def test_all_six_modules_served_and_valid_syntax(self):
        for name in self.MODULES:
            src = self._fetch_js(name)
            self.assertRegex(src, r"\b(export|import)\b", f"{name} must be an ES module")

    def test_ws_client_protocol_and_binary_frame_encoder(self):
        src = self._fetch_js("ws-client.js")
        self.assertIn("/ws", src)
        self.assertIn("ArrayBuffer(9)", src)
        self.assertIn("DataView", src)
        self.assertIn("setUint8", src)
        self.assertIn("setFloat32", src)
        for ev in ("now", "vol", "kb", "screen_owner", "status", "ui_context"):
            self.assertIn(ev, src, f"ws-client.js missing event {ev!r}")

    def test_touchbar_module_contract(self):
        src = self._fetch_js("touchbar.js")
        self.assertIn("export function initTouchBar", src)
        for token in (
            "tb-on",
            "tb-chips",
            "ui_cmd",
            "play_episode",
            "play_epg",
            "can_archive",
            "alt_label",
            "/api/sweettv/show",
            "/api/sweettv/vod",
            "/api/sweettv/guide",
            "/api/sweettv/day",
        ):
            self.assertIn(token, src, f"touchbar.js missing {token!r}")

    def test_trackpad_gestures_and_rest_fallback_without_https(self):
        src = self._fetch_js("trackpad.js")
        self.assertIn("/api/pointer", src)
        for act in ("move_by", "click", "right", "scroll"):
            self.assertIn(act, src, f"trackpad.js missing {act!r}")
        self.assertNotIn("DeviceOrientationEvent", src)
        self.assertNotIn("requestPermission", src)

    def test_power_banner_cast_switcher_and_cec_standby(self):
        src = self._fetch_js("power-banner.js")
        self.assertIn("/api/power", src)
        self.assertIn("Вернуться в Kodi", src)
        for act in ("standby", "wake", "return_kodi"):
            self.assertIn(act, src, f"power-banner.js missing {act!r}")

    def test_screen_v2_shot_jpg_409_and_hidden_pause(self):
        src = self._fetch_js("screen-v2.js")
        self.assertIn("/shot.jpg", src)
        self.assertIn("409", src)
        self.assertIn("Вернуться в Kodi", src)
        self.assertIn("document.hidden", src)

    def test_screen_v2_screenshot_share_and_sheet(self):
        src = self._fetch_js("screen-v2.js")
        for token in (
            "/shot.png",
            "fresh=1",
            "takeScreenshot",
            "saveBusy",
            "canShare",
            "navigator.share",
            "AbortError",
            "NotAllowedError",
            "mediastick-",
        ):
            self.assertIn(token, src, f"screen-v2.js missing {token!r}")

    def test_diagnostics_logs_and_lan_pin_modal(self):
        src = self._fetch_js("diagnostics.js")
        self.assertIn("/api/logs", src)
        for unit in ("kodi", "panel", "update", "displayd"):
            self.assertIn(unit, src, f"diagnostics.js missing log unit {unit!r}")
        self.assertIn("/api/pin", src)

    def test_v2_boot_wires_modules_and_service_worker(self):
        src = self._fetch_js("v2-boot.js")
        for mod in ("ws-client.js", "trackpad.js", "power-banner.js", "screen-v2.js", "diagnostics.js", "touchbar.js"):
            self.assertIn(mod, src, f"v2-boot.js must import {mod}")
        self.assertIn("initTouchBar", src)
        self.assertIn("ui_context", src)
        self.assertIn("serviceWorker", src)
        self.assertIn("/sw.js", src)

    def test_v2_boot_wires_screenshot_buttons_and_sheet(self):
        src = self._fetch_js("v2-boot.js")
        self.assertNotIn("shot-save-rc", src)
        for elem_id in (
            "shot-save-act",
            "shot-save-btn",
            "f-shot",
            "shot-sheet",
            "shot-sheet-back",
            "shot-sheet-img",
            "shot-sheet-share",
            "shot-sheet-dl",
            "shot-sheet-close",
        ):
            self.assertIn(elem_id, src, f"v2-boot.js must wire {elem_id!r}")


# ---- 4. panel GET / HTML & gzip/ETag integration ----

class TestPanelRootPageV2(_PanelServerMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_panel_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_panel_server()

    def test_root_supports_gzip_etag_and_304(self):
        code, hdrs, raw = self._get("/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(code, 200)
        self.assertEqual(_hdr_ci(hdrs, "Content-Encoding"), "gzip")
        etag = _hdr_ci(hdrs, "ETag")
        self.assertTrue(etag and etag.startswith('"') and not etag.startswith("W/"))
        html = gzip.decompress(raw).decode("utf-8")
        self.assertIn("<!doctype html>", html.lower())

        code304, _, body304 = self._get("/", headers={"Accept-Encoding": "gzip", "If-None-Match": etag})
        self.assertEqual(code304, 304)
        self.assertEqual(body304, b"")

    def test_root_injects_pwa_links_v2_boot_and_ui_containers(self):
        code, _, raw = self._get("/")
        self.assertEqual(code, 200)
        html = raw.decode("utf-8")

        self.assertRegex(html, r'<link[^>]+rel="manifest"[^>]+href="/manifest\.webmanifest"')
        self.assertRegex(html, r'<link[^>]+rel="apple-touch-icon"[^>]+href="/icon-(?:192|512)\.png"')
        self.assertRegex(html, r'<script[^>]+type="module"[^>]+src="/static/v2-boot\.js\?v=[^"]+"')

        # Polling pause when document.hidden is true
        self.assertRegex(html, r"if\s*\(\s*document\.hidden\s*\)\s*return|!document\.hidden")

        # UI containers for Trackpad, Standby/Wake, Cast switcher, Diagnostics & LAN PIN
        self.assertRegex(html, r"trackpad|tp-pad|air-trackpad", "missing Trackpad container in panel HTML")
        self.assertRegex(html, r"standby|Standby|Питание|ТВ", "missing Standby/Wake UI in panel HTML")
        self.assertRegex(html, r"diag|logs|Журнал|Логи", "missing Diagnostics UI in panel HTML")
        self.assertRegex(html, r"pin|PIN|ПИН", "missing LAN PIN UI in panel HTML")

    def test_root_contains_screenshot_buttons_icon_and_sheet(self):
        code, _, raw = self._get("/")
        self.assertEqual(code, 200)
        html = raw.decode("utf-8")

        self.assertRegex(html, r'<symbol[^>]+id="i-cam"[^>]+viewBox="0 0 24 24"')
        self.assertNotIn('id="shot-save-rc"', html)
        for elem_id in (
            "shot-save-act",
            "shot-save-btn",
            "f-shot",
            "shot-sheet",
            "shot-sheet-back",
            "shot-sheet-img",
            "shot-sheet-share",
            "shot-sheet-dl",
            "shot-sheet-close",
        ):
            self.assertIn(f'id="{elem_id}"', html, f"panel HTML missing id={elem_id!r}")

    def test_root_contains_touchbar_and_contextual_search(self):
        code, _, raw = self._get("/")
        self.assertEqual(code, 200)
        html = raw.decode("utf-8")

        self.assertRegex(html, r'<symbol[^>]+id="i-search"[^>]+viewBox="0 0 24 24"')
        self.assertIn('id="btn-search-rc"', html)
        self.assertIn('id="touchbar"', html)
        self.assertIn('class="rc-shell"', html)
        self.assertIn('class="mode-corners"', html)
        self.assertIn('data-mode-go="', html)
        self.assertNotIn('class="modes"', html)


if __name__ == "__main__":
    unittest.main(verbosity=1)
