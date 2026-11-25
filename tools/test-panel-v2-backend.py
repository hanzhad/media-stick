#!/usr/bin/env python3
"""Offline unit + live-socket tests for the panel v2 backend core (Issue #38):
python3 tools/test-panel-v2-backend.py

Covers:
  - panel_core.kodi_bus: persistent JSON-RPC 2.0 TCP client, id correlation, push dispatch, auto-reconnect
  - panel_core.state_hub: zero-fork /proc & /sys telemetry, long-TTL caches, /api/status compatibility
  - panel_core.input_bus: dual uinput devices, zero-sleep move_by, wpctl volume, UTF-8 text fallback
  - panel_core.screen_cap: Kodi Pillow JPEG <=960x540, web-app grim, fast 409 on airplay/miracast
  - panel_core.ws_hub: RFC 6455 handshake, Origin+Host validation, text/9-byte <Bff binary frames, hub broadcast
  - panel_core.auth_pin: optional 4-digit PBKDF2 PIN, HttpOnly+SameSite=Strict cookie, transparent when off
  - panel_core.tls_reload: mtime-watched hot-reloading SSLContext via sni_callback
  - media-stick-cert: skips hard systemctl restart panel.service when HTTPS is already active
  - panel.H: /ws, /shot.jpg (+ /shot.png), /api/power, /api/logs, /api/pin, json_body bounds, no bad-Host nmcli DoS, no FOCUS.after() sleep
"""
import base64
import hashlib
import http.client
import importlib
import importlib.machinery
import importlib.util
import io
import json
import math
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
CERT_SCRIPT = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-cert")

TMP = tempfile.mkdtemp(prefix="test-panel-v2-")
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["MEDIASTICK_SCREEN_DIR"] = os.path.join(TMP, "screen")
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

loader = importlib.machinery.SourceFileLoader("panel_v2_under_test", PANEL)
spec = importlib.util.spec_from_loader(loader.name, loader)
panel = importlib.util.module_from_spec(spec)
loader.exec_module(panel)


def _require_module(testcase, dotted_name):
    """Import a new panel_core module; fail with AssertionError if not yet implemented."""
    try:
        return importlib.import_module(dotted_name)
    except ImportError as exc:
        testcase.fail(f"{dotted_name} is not implemented: {exc}")


def _ws_frame(opcode, payload=b"", mask=True):
    """Build an RFC 6455 frame (masked client->server by default)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    b0 = 0x80 | (opcode & 0x0F)
    n = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if n < 126:
        hdr = struct.pack("!BB", b0, mask_bit | n)
    elif n < 65536:
        hdr = struct.pack("!BBH", b0, mask_bit | 126, n)
    else:
        hdr = struct.pack("!BBQ", b0, mask_bit | 127, n)
    if not mask:
        return hdr + payload
    key = b"\x37\xfa\x21\x3d"
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return hdr + key + masked


def _read_ws_frame(sock):
    """Read a single unmasked server->client RFC 6455 frame from a socket."""
    def recv_exact(k):
        buf = bytearray()
        while len(buf) < k:
            chunk = sock.recv(k - len(buf))
            if not chunk:
                raise EOFError("socket closed")
            buf.extend(chunk)
        return bytes(buf)

    b0, b1 = struct.unpack("!BB", recv_exact(2))
    opcode = b0 & 0x0F
    n = b1 & 0x7F
    if n == 126:
        (n,) = struct.unpack("!H", recv_exact(2))
    elif n == 127:
        (n,) = struct.unpack("!Q", recv_exact(8))
    if b1 & 0x80:
        key = recv_exact(4)
        raw = recv_exact(n)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(raw))
    else:
        payload = recv_exact(n)
    return opcode, payload


class _FakeKodiServer:
    """In-process TCP JSON-RPC 2.0 server supporting out-of-order replies, pushes, and drop."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.clients = []
        self.requests = []
        self.on_request = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                self.sock.settimeout(0.2)
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.clients.append(conn)
            threading.Thread(target=self._client_loop, args=(conn,), daemon=True).start()

    def _client_loop(self, conn):
        dec = json.JSONDecoder()
        buf = ""
        while not self._stop.is_set():
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8")
                while buf.lstrip():
                    s = buf.lstrip()
                    try:
                        obj, idx = dec.raw_decode(s)
                    except json.JSONDecodeError:
                        break
                    buf = s[idx:]
                    self.requests.append(obj)
                    if self.on_request:
                        self.on_request(conn, obj)
            except OSError:
                break

    def send_json(self, conn, obj):
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def drop_all(self):
        for c in list(self.clients):
            try:
                c.close()
            except OSError:
                pass
        self.clients.clear()

    def close(self):
        self._stop.set()
        self.drop_all()
        try:
            self.sock.close()
        except OSError:
            pass


# ---- 1. kodi_bus ----

class TestKodiBus(unittest.TestCase):
    def setUp(self):
        self.srv = _FakeKodiServer()

    def tearDown(self):
        self.srv.close()

    def test_rpc_id_correlation_out_of_order(self):
        kb_mod = _require_module(self, "panel_core.kodi_bus")
        pending = []
        ready = threading.Event()

        def handler(conn, req):
            pending.append((conn, req))
            if len(pending) == 2:
                # Reply to second request BEFORE first request
                for c, r in reversed(pending):
                    self.srv.send_json(c, {"jsonrpc": "2.0", "id": r["id"], "result": {"echo": r["method"]}})
                ready.set()

        self.srv.on_request = handler
        bus = kb_mod.KodiBus(host="127.0.0.1", port=self.srv.port, timeout=3.0)
        bus.start()
        try:
            results = {}

            def worker(key, method):
                results[key] = bus.call(method)

            t1 = threading.Thread(target=worker, args=("a", "Player.GetActivePlayers"))
            t2 = threading.Thread(target=worker, args=("b", "XBMC.GetInfoBooleans"))
            t1.start()
            t2.start()
            t1.join(timeout=3)
            t2.join(timeout=3)
            self.assertTrue(ready.is_set())
            self.assertEqual(results["a"], {"echo": "Player.GetActivePlayers"})
            self.assertEqual(results["b"], {"echo": "XBMC.GetInfoBooleans"})
        finally:
            bus.close()

    def test_rpc_error_raises(self):
        kb_mod = _require_module(self, "panel_core.kodi_bus")
        self.srv.on_request = lambda conn, req: self.srv.send_json(
            conn, {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32602, "message": "Invalid params"}}
        )
        bus = kb_mod.KodiBus(host="127.0.0.1", port=self.srv.port, timeout=2.0)
        bus.start()
        try:
            with self.assertRaises(Exception):
                bus.call("Input.ExecuteAction", {"action": "bad"})
        finally:
            bus.close()

    def test_push_notification_dispatch_and_isolation(self):
        kb_mod = _require_module(self, "panel_core.kodi_bus")
        methods = [
            "Player.OnPlay", "Player.OnPause", "Player.OnResume", "Player.OnStop",
            "Player.OnSeek", "Player.OnAVChange", "Application.OnVolumeChanged",
            "Input.OnInputRequested", "Input.OnInputFinished",
        ]

        def handler(conn, req):
            for idx, m in enumerate(methods):
                self.srv.send_json(conn, {"jsonrpc": "2.0", "method": m, "params": {"seq": idx}})
            self.srv.send_json(conn, {"jsonrpc": "2.0", "id": req["id"], "result": "pong"})

        self.srv.on_request = handler
        bus = kb_mod.KodiBus(host="127.0.0.1", port=self.srv.port, timeout=3.0)
        seen = []
        done = threading.Event()

        def bad_sub(method, params):
            raise RuntimeError("subscriber failure")

        def good_sub(method, params):
            seen.append((method, params))
            if len(seen) == len(methods):
                done.set()

        bus.subscribe(bad_sub)
        bus.subscribe(good_sub)
        bus.start()
        try:
            res = bus.call("JSONRPC.Ping")
            self.assertEqual(res, "pong")
            self.assertTrue(done.wait(timeout=2.0), f"only received {len(seen)} notifications")
            self.assertEqual([m for m, _ in seen], methods)
        finally:
            bus.close()

    def test_auto_reconnect_after_server_drop(self):
        kb_mod = _require_module(self, "panel_core.kodi_bus")
        self.srv.on_request = lambda conn, req: self.srv.send_json(
            conn, {"jsonrpc": "2.0", "id": req["id"], "result": "pong"}
        )
        bus = kb_mod.KodiBus(host="127.0.0.1", port=self.srv.port, timeout=2.0, reconnect_delay=0.02)
        bus.start()
        try:
            self.assertEqual(bus.call("JSONRPC.Ping"), "pong")
            self.srv.drop_all()
            time.sleep(0.05)
            self.assertEqual(bus.call("JSONRPC.Ping"), "pong")
        finally:
            bus.close()


# ---- 2. state_hub ----

class TestStateHub(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.meminfo = os.path.join(self.dir.name, "meminfo")
        self.uptime = os.path.join(self.dir.name, "uptime")
        self.temp = os.path.join(self.dir.name, "temp")
        self.screen_dir = os.path.join(self.dir.name, "screen")
        os.makedirs(self.screen_dir, exist_ok=True)
        with open(self.meminfo, "w", encoding="utf-8") as f:
            f.write("MemTotal:        1024000 kB\nMemAvailable:     512000 kB\n")
        with open(self.uptime, "w", encoding="utf-8") as f:
            f.write("3665.40 1000.00\n")
        with open(self.temp, "w", encoding="utf-8") as f:
            f.write("48500\n")

    def tearDown(self):
        self.dir.cleanup()

    def test_zero_fork_telemetry_and_ttl_caches(self):
        sh_mod = _require_module(self, "panel_core.state_hub")
        now = [1000.0]
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(tuple(cmd))
            if cmd[:2] == ["vcgencmd", "get_throttled"]:
                return 0, "throttled=0x0"
            if cmd and cmd[0] == "nmcli":
                return 0, ""
            if "git" in cmd:
                return 0, "abc1234 feat: test"
            return 0, ""

        hub = sh_mod.StateHub(
            proc_meminfo=self.meminfo,
            proc_uptime=self.uptime,
            thermal_temp=self.temp,
            screen_dir=self.screen_dir,
            run_cmd=fake_run,
            kodi_call=lambda m, p=None: [] if m == "Player.GetActivePlayers" else {},
            now_fn=lambda: now[0],
        )

        s1 = hub.collect()
        self.assertEqual(s1["mem_free_mb"], 500)
        self.assertIn("48.5", s1["temp"])
        self.assertTrue(s1["power_ok"])
        self.assertEqual(s1["throttled"], "0x0")
        for key in (
            "time", "wifi", "uptime", "temp", "throttled", "power_ok",
            "mem_free_mb", "disk_free_gb", "ip", "https_url", "page", "lang",
            "commit", "commit_date", "bad_commit", "next_update", "next_update_min",
            "last_check", "last_check_min", "playing", "kb", "kodi", "dead", "screen",
        ):
            self.assertIn(key, s1)

        # Must NOT fork uptime or vcgencmd measure_temp
        self.assertFalse(any(c[0] == "uptime" for c in calls))
        self.assertFalse(any(c[:2] == ("vcgencmd", "measure_temp") for c in calls))

        throttled_count_1 = sum(1 for c in calls if c[:2] == ("vcgencmd", "get_throttled"))
        nmcli_count_1 = sum(1 for c in calls if c and c[0] == "nmcli")
        git_count_1 = sum(1 for c in calls if "git" in c)
        self.assertEqual(throttled_count_1, 1)

        # Within 5s: vcgencmd (60s) and nmcli (15s) and git (startup) are cached
        now[0] += 5.0
        hub.collect()
        self.assertEqual(sum(1 for c in calls if c[:2] == ("vcgencmd", "get_throttled")), throttled_count_1)
        self.assertEqual(sum(1 for c in calls if c and c[0] == "nmcli"), nmcli_count_1)
        self.assertEqual(sum(1 for c in calls if "git" in c), git_count_1)

        # After +16s (total +21s): nmcli refreshes if used, vcgencmd still cached
        now[0] += 16.0
        hub.collect()
        self.assertEqual(sum(1 for c in calls if c[:2] == ("vcgencmd", "get_throttled")), throttled_count_1)

        # After +45s (total +66s): vcgencmd refreshes
        now[0] += 45.0
        hub.collect()
        self.assertEqual(sum(1 for c in calls if c[:2] == ("vcgencmd", "get_throttled")), throttled_count_1 + 1)

    def test_screen_flag_reflected_in_status(self):
        sh_mod = _require_module(self, "panel_core.state_hub")
        open(os.path.join(self.screen_dir, "airplay"), "w").close()
        hub = sh_mod.StateHub(
            proc_meminfo=self.meminfo,
            proc_uptime=self.uptime,
            thermal_temp=self.temp,
            screen_dir=self.screen_dir,
            run_cmd=lambda cmd, **_kw: (0, ""),
            kodi_call=lambda m, p=None: (_ for _ in ()).throw(OSError("down")),
        )
        s = hub.collect()
        self.assertEqual(s["screen"], "airplay")
        self.assertEqual(s["kodi"], "down")


# ---- 3. input_bus ----

class TestInputBus(unittest.TestCase):
    def test_move_by_has_zero_sleep_and_wpctl_volume(self):
        ib_mod = _require_module(self, "panel_core.input_bus")
        sleep_calls = []
        cmds = []

        def fake_run(cmd, **_kw):
            cmds.append(list(cmd))
            return 0, ""

        bus = ib_mod.InputBus(
            uinput_path="/dev/null",
            run_cmd=fake_run,
            sleep_fn=lambda d: sleep_calls.append(d),
        )
        # Inject an in-memory event sink so move_by exercises event emission without /dev/uinput
        sink = io.BytesIO()
        bus._pointer_fd = sink
        for _ in range(10):
            bus.move_by(0.05, -0.05)

        self.assertEqual(sleep_calls, [], "move_by must not call time.sleep")
        self.assertGreater(len(sink.getvalue()), 0)

        for action, expected_arg in (("volumeup", "5%+"), ("volumedown", "5%-"), ("mute", "toggle")):
            cmds.clear()
            bus.set_volume(action)
            self.assertEqual(len(cmds), 1)
            self.assertEqual(cmds[0][0], "wpctl")
            self.assertIn("@DEFAULT_AUDIO_SINK@", cmds[0])
            self.assertTrue(any(expected_arg in part for part in cmds[0]))

        with self.assertRaises(ValueError):
            bus.set_volume("invalid")

    def test_dual_device_names_and_utf8_fallback(self):
        ib_mod = _require_module(self, "panel_core.input_bus")
        self.assertEqual(ib_mod.POINTER_NAME, "media-stick-pointer")
        self.assertEqual(ib_mod.KBD_NAME, "media-stick-kbd")
        bus = ib_mod.InputBus(uinput_path="/nonexistent/uinput", run_cmd=lambda cmd, **_kw: (0, ""))
        # Empty text is a safe no-op; UTF-8 text must not crash when wtype is absent
        bus.type_text("")
        bus.type_text("привет world")

    def test_open_pointer_registers_abs_without_rel_xy(self):
        ib_mod = _require_module(self, "panel_core.input_bus")
        bus = ib_mod.InputBus(uinput_path="/dev/uinput")
        ioctl_calls = []

        def fake_ioctl(fd, req, arg=0):
            ioctl_calls.append((fd, req, arg))
            return 0

        with mock.patch.object(ib_mod.os, "open", return_value=42) as mock_open, \
                mock.patch.object(ib_mod.fcntl, "ioctl", side_effect=fake_ioctl):
            fd = bus._open_pointer()

        self.assertEqual(fd, 42)
        mock_open.assert_called_once_with("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)

        by_req = {}
        for call_fd, req, arg in ioctl_calls:
            self.assertEqual(call_fd, 42)
            by_req.setdefault(req, []).append(arg)

        ev_bits = set(by_req.get(ib_mod.UI_SET_EVBIT, []))
        self.assertEqual(ev_bits, {ib_mod.EV_KEY, ib_mod.EV_REL, ib_mod.EV_ABS})

        key_bits = set(by_req.get(ib_mod.UI_SET_KEYBIT, []))
        self.assertIn(ib_mod.BTN_LEFT, key_bits)
        self.assertIn(ib_mod.BTN_RIGHT, key_bits)

        rel_bits = set(by_req.get(ib_mod.UI_SET_RELBIT, []))
        self.assertIn(ib_mod.REL_WHEEL, rel_bits)
        self.assertNotIn(ib_mod.REL_X, rel_bits, "REL_X causes libinput to discard EV_ABS motion")
        self.assertNotIn(ib_mod.REL_Y, rel_bits, "REL_Y causes libinput to discard EV_ABS motion")

        abs_bits = set(by_req.get(ib_mod.UI_SET_ABSBIT, []))
        self.assertEqual(abs_bits, {ib_mod.ABS_X, ib_mod.ABS_Y})

        self.assertIn(ib_mod.UI_DEV_SETUP, by_req)
        self.assertIn(ib_mod.UI_DEV_CREATE, by_req)


# ---- 4. screen_cap ----

class TestScreenCap(unittest.TestCase):
    def _png_bytes(self, w=1920, h=1080):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (40, 80, 120)).save(buf, format="PNG")
        return buf.getvalue()

    def test_kodi_screenshot_resized_jpeg(self):
        sc_mod = _require_module(self, "panel_core.screen_cap")
        png = self._png_bytes(1920, 1080)
        jpg = sc_mod.capture_jpeg("kodi", kodi_shot_fn=lambda: png)
        self.assertTrue(jpg.startswith(b"\xff\xd8"))
        im = Image.open(io.BytesIO(jpg))
        self.assertEqual(im.format, "JPEG")
        self.assertLessEqual(im.width, 960)
        self.assertLessEqual(im.height, 540)

    def test_webapp_invokes_grim(self):
        sc_mod = _require_module(self, "panel_core.screen_cap")
        buf = io.BytesIO()
        Image.new("RGB", (640, 360), (10, 20, 30)).save(buf, format="JPEG")
        fake_jpg = buf.getvalue()
        seen_cmds = []

        def fake_run(cmd, **_kw):
            seen_cmds.append(list(cmd))
            return 0, fake_jpg

        out = sc_mod.capture_jpeg("web-app", run_cmd=fake_run)
        self.assertTrue(out.startswith(b"\xff\xd8"))
        self.assertEqual(len(seen_cmds), 1)
        self.assertEqual(seen_cmds[0][0], "grim")
        self.assertIn("jpeg", seen_cmds[0])

    def test_cast_owners_raise_409_immediately(self):
        sc_mod = _require_module(self, "panel_core.screen_cap")
        for owner in ("airplay", "miracast"):
            with self.assertRaises(sc_mod.ScreenUnavailable) as ctx:
                sc_mod.capture_jpeg(
                    owner,
                    kodi_shot_fn=lambda: self.fail("must not call kodi_shot_fn for cast"),
                    run_cmd=lambda *a, **k: self.fail("must not fork grim for cast"),
                )
            self.assertEqual(ctx.exception.owner, owner)
            self.assertEqual(ctx.exception.status, 409)


# ---- 5. ws_hub ----

class TestWsHub(unittest.TestCase):
    def test_rfc6455_accept_key(self):
        ws_mod = _require_module(self, "panel_core.ws_hub")
        self.assertEqual(
            ws_mod.handshake_accept("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )

    def test_origin_and_host_validation(self):
        ws_mod = _require_module(self, "panel_core.ws_hub")
        base = {
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Host": "mediastick.local",
        }
        # Same-origin and absent-origin allowed
        self.assertTrue(ws_mod.validate_ws_headers({**base, "Origin": "http://mediastick.local"}))
        self.assertTrue(ws_mod.validate_ws_headers(dict(base)))
        # Cross-origin rejected
        self.assertFalse(ws_mod.validate_ws_headers({**base, "Origin": "https://evil.example"}))
        self.assertFalse(ws_mod.validate_ws_headers({**base, "Origin": "http://192.168.1.99"}))
        # Missing upgrade headers rejected
        bad = dict(base)
        del bad["Sec-WebSocket-Key"]
        self.assertFalse(ws_mod.validate_ws_headers(bad))

    def test_binary_pointer_frame_codec(self):
        ws_mod = _require_module(self, "panel_core.ws_hub")
        for op in (1, 2, 3, 4):
            pkt = struct.pack("<Bff", op, 0.25, -0.5)
            got_op, dx, dy = ws_mod.decode_pointer_frame(pkt)
            self.assertEqual(got_op, op)
            self.assertAlmostEqual(dx, 0.25, places=5)
            self.assertAlmostEqual(dy, -0.5, places=5)

        for bad in (
            b"\x01\x00\x00",
            struct.pack("<Bff", 0, 0.0, 0.0),
            struct.pack("<Bff", 5, 0.0, 0.0),
            struct.pack("<Bff", 1, math.nan, 0.0),
            struct.pack("<Bff", 1, math.inf, 0.0),
        ):
            with self.assertRaises(ValueError):
                ws_mod.decode_pointer_frame(bad)

    def test_hub_broadcast_and_dead_client_pruning(self):
        ws_mod = _require_module(self, "panel_core.ws_hub")
        hub = ws_mod.WsHub()
        a_srv, a_cli = socket.socketpair()
        b_srv, b_cli = socket.socketpair()
        try:
            hub.add(a_srv)
            hub.add(b_srv)
            b_cli.close()
            b_srv.close()
            hub.broadcast({"type": "state", "kodi": "up"})
            op, payload = _read_ws_frame(a_cli)
            self.assertEqual(op, 0x1)
            self.assertEqual(json.loads(payload.decode("utf-8")), {"type": "state", "kodi": "up"})
        finally:
            for s in (a_srv, a_cli):
                try:
                    s.close()
                except OSError:
                    pass


# ---- 6. auth_pin ----

class TestAuthPin(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_disabled_by_default_and_pin_lifecycle(self):
        ap_mod = _require_module(self, "panel_core.auth_pin")
        auth = ap_mod.PinAuth(state_dir=self.dir.name)
        self.assertFalse(auth.is_enabled())
        self.assertTrue(auth.check_request({}))

        for bad_pin in ("", "123", "12345", "12a4"):
            with self.assertRaises(ValueError):
                auth.set_pin(bad_pin)

        auth.set_pin("0451")
        self.assertTrue(auth.is_enabled())
        self.assertTrue(auth.verify_pin("0451"))
        self.assertFalse(auth.verify_pin("0000"))

        # Plaintext PIN must never be stored on disk
        for fn in os.listdir(self.dir.name):
            raw = open(os.path.join(self.dir.name, fn), "rb").read()
            self.assertNotIn(b"0451", raw)

        cookie_hdr = auth.issue_cookie(secure=False)
        self.assertIn("HttpOnly", cookie_hdr)
        self.assertIn("SameSite=Strict", cookie_hdr)
        cookie_kv = cookie_hdr.split(";", 1)[0]

        self.assertFalse(auth.check_request({}))
        self.assertFalse(auth.check_request({"Cookie": cookie_kv + "tampered"}))
        self.assertTrue(auth.check_request({"Cookie": cookie_kv}))

        auth.disable()
        self.assertFalse(auth.is_enabled())
        self.assertTrue(auth.check_request({}))


# ---- 7. tls_reload ----

class TestTlsReload(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def _gen_cert(self, cn):
        crt = os.path.join(self.dir.name, f"{cn}.crt")
        key = os.path.join(self.dir.name, f"{cn}.key")
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", key, "-out", crt, "-days", "1", "-subj", f"/CN={cn}",
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return crt, key

    def test_hot_swap_on_mtime_change(self):
        tr_mod = _require_module(self, "panel_core.tls_reload")
        crt_path = os.path.join(self.dir.name, "fullchain.pem")
        key_path = os.path.join(self.dir.name, "key.pem")
        c1, k1 = self._gen_cert("one.local")
        c2, k2 = self._gen_cert("two.local")
        with open(c1, "rb") as src, open(crt_path, "wb") as dst:
            dst.write(src.read())
        with open(k1, "rb") as src, open(key_path, "wb") as dst:
            dst.write(src.read())

        reloader = tr_mod.TlsReloader(crt_path, key_path)
        ctx1 = reloader.context
        self.assertIsInstance(ctx1, ssl.SSLContext)
        self.assertFalse(reloader.maybe_reload())
        self.assertIs(reloader.context, ctx1)

        # Replace with cert 2 and bump mtime
        with open(c2, "rb") as src, open(crt_path, "wb") as dst:
            dst.write(src.read())
        with open(k2, "rb") as src, open(key_path, "wb") as dst:
            dst.write(src.read())
        now = time.time() + 5
        os.utime(crt_path, (now, now))
        os.utime(key_path, (now, now))

        self.assertTrue(reloader.maybe_reload())
        self.assertIsNot(reloader.context, ctx1)


# ---- 8. media-stick-cert ----

class TestMediaStickCert(unittest.TestCase):
    def test_does_not_unconditionally_restart_panel(self):
        with open(CERT_SCRIPT, encoding="utf-8") as f:
            src = f.read()
        # Extract non-comment lines from section 3 (publish & restart)
        code_lines = [l for l in src.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        code = "\n".join(code_lines)
        self.assertIn("systemctl restart panel.service", code)
        # Must check whether HTTPS/panel is already active before calling systemctl restart panel.service
        restart_idx = code.index("systemctl restart panel.service")
        window = code[max(0, restart_idx - 400):restart_idx]
        self.assertRegex(
            window,
            r"\b(ss|curl|openssl|systemctl\s+is-active|443|PANEL_HTTPS_PORT)\b",
            "media-stick-cert must check if HTTPS is already active before restarting panel.service",
        )


# ---- 9. panel.H integration & bug fixes ----

class TestPanelV2Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kodi_calls = []
        cls.flags = {k: False for k in panel.PLAYER_BOOLS}
        panel.kodi = cls._fake_kodi
        panel.web_app_on = lambda: False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    @classmethod
    def _fake_kodi(cls, method, params=None, timeout=3):
        cls.kodi_calls.append((method, params))
        if method == "XBMC.GetInfoBooleans":
            return cls.flags
        if method == "Player.GetActivePlayers":
            return []
        if method in ("GUI.GetProperties", "XBMC.GetInfoLabels"):
            return {}
        return "OK"

    def setUp(self):
        self.kodi_calls.clear()

    def _req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"Host": f"localhost:{self.port}", "X-Panel": "1"}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
            if isinstance(body, (dict, list)):
                body = json.dumps(body)
        if headers:
            hdrs.update(headers)
        c.request(method, path, body, hdrs)
        r = c.getresponse()
        raw = r.read()
        resp_hdrs = dict(r.getheaders())
        c.close()
        return r.status, resp_hdrs, raw

    def test_json_body_handles_negative_and_non_int_content_length(self):
        class FakeHandler:
            def __init__(self, cl, data=b""):
                self.headers = {"Content-Length": cl}
                self.rfile = io.BytesIO(data)
                self.close_connection = False

        for bad_cl in ("-1", "-999", "abc", "", "999999999"):
            h = FakeHandler(bad_cl, b'{"action":"up"}')
            res = panel.json_body(h)
            self.assertEqual(res, {}, f"bad Content-Length={bad_cl!r} should yield {{}}")

    def test_bad_host_does_not_fork_nmcli(self):
        nmcli_calls = []
        orig_run = panel.run

        def spy_run(cmd, *a, **kw):
            if cmd and cmd[0] == "nmcli":
                nmcli_calls.append(cmd)
            return orig_run(cmd, *a, **kw)

        with mock.patch.object(panel, "run", side_effect=spy_run):
            for _ in range(5):
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                c.request("GET", "/", headers={"Host": "evil.example"})
                r = c.getresponse()
                r.read()
                c.close()
                self.assertIn(r.status, (403, 421))
        self.assertEqual(nmcli_calls, [], "bad Host must not trigger nmcli DoS")

    def test_api_key_has_no_synchronous_sleep(self):
        sleeps = []
        with mock.patch.object(time, "sleep", side_effect=lambda d: sleeps.append(d)):
            code, _, _ = self._req("POST", "/api/key", {"action": "down"})
        self.assertEqual(code, 200)
        self.assertEqual(sleeps, [], "/api/key must not block on FOCUS.after() sleep")

    def test_shot_jpg_and_shot_png_and_409_cast(self):
        buf = io.BytesIO()
        Image.new("RGB", (1920, 1080), (1, 2, 3)).save(buf, format="PNG")
        png_bytes = buf.getvalue()

        with mock.patch.object(panel, "screenshot", return_value=png_bytes):
            code, hdrs, raw = self._req("GET", "/shot.png")
            self.assertEqual(code, 200)
            self.assertEqual(hdrs.get("Content-Type"), "image/png")

            code, hdrs, raw = self._req("GET", "/shot.jpg")
            self.assertEqual(code, 200)
            self.assertEqual(hdrs.get("Content-Type"), "image/jpeg")
            self.assertTrue(raw.startswith(b"\xff\xd8"))
            im = Image.open(io.BytesIO(raw))
            self.assertLessEqual(im.width, 960)
            self.assertLessEqual(im.height, 540)

        with mock.patch.object(panel, "screen_owner", return_value="airplay"):
            code, _, _ = self._req("GET", "/shot.jpg")
            self.assertEqual(code, 409)

    def test_api_power_routes(self):
        class FakeClient:
            def __init__(self):
                self.actions = []
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def standby(self):
                self.actions.append("standby")
                return {"ok": True}
            def wake(self):
                self.actions.append("wake")
                return {"ok": True}
            def release(self, force=False):
                self.actions.append(("release", force))
                return {"ok": True}

        fc = FakeClient()
        with mock.patch.object(panel, "DisplayClient", create=True, return_value=fc):
            for act in ("standby", "wake", "return_kodi"):
                code, _, _ = self._req("POST", "/api/power", {"action": act})
                self.assertEqual(code, 200, act)
            code, _, _ = self._req("POST", "/api/power", {"action": "explode"})
            self.assertEqual(code, 400)

    def test_api_logs_scrubs_secrets_and_rejects_bad_unit(self):
        code, _, _ = self._req("GET", "/api/logs?unit=sshd")
        self.assertEqual(code, 400)

        secret = "deadbeef-1234-5678-90ab-cdef12345678"
        fake_log = f"DUCKDNS_TOKEN={secret}\npsk=\"mysecretwifi\"\nok line\n"
        with mock.patch.object(panel, "read_unit_logs", create=True, return_value=fake_log):
            code, _, raw = self._req("GET", "/api/logs?unit=panel")
            self.assertEqual(code, 200)
            text = raw.decode("utf-8")
            self.assertNotIn(secret, text)
            self.assertNotIn("mysecretwifi", text)

    def test_api_pin_and_ws_upgrade(self):
        # Initially disabled
        code, hdrs, raw = self._req("GET", "/api/pin")
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get("Content-Type"), "application/json")
        self.assertEqual(json.loads(raw.decode()), {"enabled": False})

        # Enable PIN
        code, hdrs, _ = self._req("POST", "/api/pin", {"pin": "1234"})
        self.assertEqual(code, 200)
        set_cookie = hdrs.get("Set-Cookie", "")
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        cookie_kv = set_cookie.split(";", 1)[0]

        try:
            # Unauthenticated POST must be 401
            code, _, _ = self._req("POST", "/api/key", {"action": "up"})
            self.assertEqual(code, 401)

            # Authenticated POST succeeds
            code, _, _ = self._req("POST", "/api/key", {"action": "up"}, headers={"Cookie": cookie_kv})
            self.assertEqual(code, 200)

            # Unauthenticated WS upgrade must be 401
            s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
            try:
                key = base64.b64encode(os.urandom(16)).decode()
                s.sendall(
                    (
                        f"GET /ws HTTP/1.1\r\nHost: localhost:{self.port}\r\n"
                        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
                    ).encode()
                )
                resp = s.recv(4096).decode("utf-8", errors="replace")
                self.assertIn("401", resp.splitlines()[0])
            finally:
                s.close()

            # Cross-origin WS upgrade with cookie must be 403
            s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
            try:
                key = base64.b64encode(os.urandom(16)).decode()
                s.sendall(
                    (
                        f"GET /ws HTTP/1.1\r\nHost: localhost:{self.port}\r\n"
                        f"Origin: https://evil.example\r\nCookie: {cookie_kv}\r\n"
                        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
                    ).encode()
                )
                resp = s.recv(4096).decode("utf-8", errors="replace")
                self.assertIn("403", resp.splitlines()[0])
            finally:
                s.close()

            # Valid authenticated WS upgrade
            s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
            try:
                key = base64.b64encode(os.urandom(16)).decode()
                s.sendall(
                    (
                        f"GET /ws HTTP/1.1\r\nHost: localhost:{self.port}\r\n"
                        f"Origin: http://localhost:{self.port}\r\nCookie: {cookie_kv}\r\n"
                        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
                    ).encode()
                )
                resp = s.recv(4096).decode("utf-8", errors="replace")
                self.assertIn("101", resp.splitlines()[0])
                expected_accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                self.assertIn(expected_accept, resp)
                # Send 9-byte binary pointer frame (move_by) + close frame
                s.sendall(_ws_frame(0x2, struct.pack("<Bff", 1, 0.1, -0.2)))
                s.sendall(_ws_frame(0x8, b""))
            finally:
                s.close()
        finally:
            self._req("POST", "/api/pin", {"action": "disable"}, headers={"Cookie": cookie_kv})


if __name__ == "__main__":
    unittest.main(verbosity=1)
