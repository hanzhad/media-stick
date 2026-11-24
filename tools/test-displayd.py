#!/usr/bin/env python3
"""Offline tests for mediastick_display (Pure Core) and mediastick-displayd (Thin I/O Shell).

Run: python3 tools/test-displayd.py
"""
import asyncio
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
DAEMON_PATH = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "mediastick-displayd")
SERVICE_PATH = os.path.join(
    ROOT, "device", "files", "etc", "systemd", "system", "mediastick-displayd.service"
)

sys.dont_write_bytecode = True
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)


def _load_core():
    import mediastick_display as md  # noqa: E402
    return md


def _load_daemon():
    _load_core()
    loader = importlib.machinery.SourceFileLoader("mediastick_displayd", DAEMON_PATH)
    spec = importlib.util.spec_from_loader("mediastick_displayd", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _action_tuple(action):
    if hasattr(action, "kind"):
        return (action.kind, getattr(action, "arg", None))
    return (action[0], action[1] if len(action) > 1 else None)


class FakeSystemExecutor:
    """In-memory SystemExecutor recording ordered side effects without OS calls."""

    def __init__(self, gate_event=None):
        self.calls = []
        self.gate_event = gate_event
        self.on_first_stop = None

    async def stop_unit(self, unit):
        self.calls.append(("stop_unit", unit))
        if self.on_first_stop is not None:
            cb = self.on_first_stop
            self.on_first_stop = None
            cb()
        if self.gate_event is not None:
            await self.gate_event.wait()

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


class DisplayStateAndP2PTests(unittest.TestCase):
    """Pure Core: DisplayState enum, is_p2p_allowed truth table, and web-app allowlist."""

    def setUp(self):
        self.md = _load_core()

    def test_display_state_enum_members(self):
        S = self.md.DisplayState
        self.assertEqual(
            {s.name for s in S},
            {"KODI", "CAST_AIRPLAY", "CAST_MIRACAST", "WEB_APP", "STANDBY"},
        )

    def test_is_p2p_allowed_truth_table(self):
        S = self.md.DisplayState
        for state in S:
            for kodi_playing in (False, True):
                for hotspot_active in (False, True):
                    expected = (
                        state == S.KODI and not kodi_playing and not hotspot_active
                    )
                    with self.subTest(
                        state=state.name,
                        kodi_playing=kodi_playing,
                        hotspot_active=hotspot_active,
                    ):
                        self.assertEqual(
                            self.md.is_p2p_allowed(state, kodi_playing, hotspot_active),
                            expected,
                        )

    def test_valid_web_apps_accepted(self):
        S = self.md.DisplayState
        for app in ("netflix", "disney", "prime", "max", "youtube"):
            with self.subTest(app=app):
                sm = self.md.DisplayStateMachine()
                plan = sm.plan_transition(S.WEB_APP, owner="panel", app=app)
                self.assertEqual(plan.target, S.WEB_APP)
                self.assertEqual(plan.app, app)
                actions = [_action_tuple(a) for a in plan.actions]
                self.assertIn(("start_unit", f"web-app@{app}.service"), actions)

    def test_invalid_web_apps_rejected(self):
        S = self.md.DisplayState
        bad_apps = [
            None,
            "",
            "hulu",
            "twitch",
            "Netflix",
            "netflix ",
            "../netflix",
            "netflix;rm -rf /",
        ]
        for app in bad_apps:
            with self.subTest(app=app):
                sm = self.md.DisplayStateMachine()
                with self.assertRaises(ValueError):
                    sm.plan_transition(S.WEB_APP, owner="panel", app=app)
                self.assertEqual(sm.state, S.KODI)


class DisplayStateMachineTransitionTests(unittest.TestCase):
    """Pure Core: deterministic transition plans and lease ownership rules."""

    def setUp(self):
        self.md = _load_core()
        self.S = self.md.DisplayState

    def test_initial_state_is_kodi_with_no_lease(self):
        sm = self.md.DisplayStateMachine()
        self.assertEqual(sm.state, self.S.KODI)
        self.assertIsNone(sm.owner)
        self.assertIsNone(sm.app)
        self.assertIsNone(sm.since)

    def test_web_app_to_airplay_stops_webapp_without_starting_kodi(self):
        sm = self.md.DisplayStateMachine()
        sm.acquire(self.S.WEB_APP, owner="panel", app="netflix")
        self.assertEqual(sm.state, self.S.WEB_APP)
        self.assertEqual(sm.owner, "panel")
        self.assertEqual(sm.app, "netflix")
        self.assertIsNotNone(sm.since)

        plan = sm.plan_transition(self.S.CAST_AIRPLAY, owner="airplay")
        actions = [_action_tuple(a) for a in plan.actions]
        kinds = [k for k, _ in actions]

        self.assertIn(("stop_unit", "web-app@netflix.service"), actions)
        self.assertIn("draw_splash", kinds)
        self.assertIn("p2p_pause", kinds)
        self.assertNotIn(("start_unit", "kodi.service"), actions)
        self.assertLess(
            actions.index(("stop_unit", "web-app@netflix.service")),
            kinds.index("draw_splash"),
        )

    def test_release_requires_owner_unless_forced(self):
        sm = self.md.DisplayStateMachine()
        sm.acquire(self.S.CAST_AIRPLAY, owner="airplay-1")

        with self.assertRaises((ValueError, PermissionError)):
            sm.release(owner="other-client")
        self.assertEqual(sm.state, self.S.CAST_AIRPLAY)
        self.assertEqual(sm.owner, "airplay-1")

        plan = sm.release(owner="airplay-1")
        actions = [_action_tuple(a) for a in plan.actions]
        self.assertEqual(sm.state, self.S.KODI)
        self.assertIsNone(sm.owner)
        self.assertIsNone(sm.app)
        self.assertIsNone(sm.since)
        self.assertIn(("start_unit", "kodi.service"), actions)
        self.assertIn(("p2p_resume", None), actions)

    def test_force_release_overrides_owner_check(self):
        sm = self.md.DisplayStateMachine()
        sm.acquire(self.S.CAST_MIRACAST, owner="miracast-1")
        plan = sm.release(owner="admin", force=True)
        self.assertEqual(sm.state, self.S.KODI)
        self.assertIsNone(sm.owner)
        self.assertIn(("start_unit", "kodi.service"), [_action_tuple(a) for a in plan.actions])

    def test_standby_and_wake_exact_action_order(self):
        sm = self.md.DisplayStateMachine()
        standby_plan = sm.acquire(self.S.STANDBY, owner="power")
        standby_actions = [_action_tuple(a) for a in standby_plan.actions]
        standby_kinds = [k for k, _ in standby_actions]

        expected_standby = [
            "flush",
            "stop_unit",
            "cec_standby",
            "kms_dpms",
            "set_governor",
            "p2p_pause",
        ]
        for name in expected_standby:
            self.assertIn(name, standby_kinds)
        indices = [standby_kinds.index(name) for name in expected_standby]
        self.assertEqual(indices, sorted(indices))
        self.assertIn(("kms_dpms", False), standby_actions)
        self.assertIn(("set_governor", "powersave"), standby_actions)

        wake_plan = sm.release(owner="power", force=True)
        wake_actions = [_action_tuple(a) for a in wake_plan.actions]
        wake_kinds = [k for k, _ in wake_actions]

        expected_wake = [
            "set_governor",
            "kms_dpms",
            "cec_wake",
            "start_unit",
            "p2p_resume",
        ]
        for name in expected_wake:
            self.assertIn(name, wake_kinds)
        wake_indices = [wake_kinds.index(name) for name in expected_wake]
        self.assertEqual(wake_indices, sorted(wake_indices))
        self.assertIn(("set_governor", "ondemand"), wake_actions)
        self.assertIn(("kms_dpms", True), wake_actions)
        self.assertIn(("start_unit", "kodi.service"), wake_actions)

    def test_release_skips_p2p_resume_when_hotspot_or_kodi_playing(self):
        sm = self.md.DisplayStateMachine()
        sm.acquire(self.S.CAST_AIRPLAY, owner="airplay")
        plan = sm.plan_transition(self.S.KODI, kodi_playing=True)
        kinds = [k for k, _ in (_action_tuple(a) for a in plan.actions)]
        self.assertNotIn("p2p_resume", kinds)

        plan_hotspot = sm.plan_transition(self.S.KODI, hotspot_active=True)
        kinds_hotspot = [k for k, _ in (_action_tuple(a) for a in plan_hotspot.actions)]
        self.assertNotIn("p2p_resume", kinds_hotspot)

    def test_noop_transition_to_same_state_emits_no_unit_churn(self):
        sm = self.md.DisplayStateMachine()
        plan = sm.plan_transition(self.S.KODI)
        self.assertEqual(list(plan.actions), [])


class DisplayDaemonRPCTests(unittest.IsolatedAsyncioTestCase):
    """Thin I/O Shell: Unix socket server, RPC, lock serialization, disconnect cleanup."""

    async def asyncSetUp(self):
        self.md = _load_core()
        self.daemon = _load_daemon()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sock_path = os.path.join(self.tmpdir.name, "display.sock")
        self.old_env = os.environ.get("DISPLAYD_SOCK")
        os.environ["DISPLAYD_SOCK"] = self.sock_path
        self.executor = FakeSystemExecutor()
        self.server = self.daemon.DisplayServer(
            sock_path=self.sock_path, executor=self.executor
        )
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        if self.old_env is None:
            os.environ.pop("DISPLAYD_SOCK", None)
        else:
            os.environ["DISPLAYD_SOCK"] = self.old_env
        self.tmpdir.cleanup()

    async def _rpc(self, payload):
        reader, writer = await asyncio.open_unix_connection(self.sock_path)
        try:
            writer.write((json.dumps(payload) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            return json.loads(line.decode("utf-8"))
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_socket_permissions_are_0660(self):
        mode = stat.S_IMODE(os.stat(self.sock_path).st_mode)
        self.assertEqual(mode, 0o660)

    async def test_status_acquire_release_and_invalid_webapp(self):
        st = await self._rpc({"cmd": "status"})
        self.assertTrue(st["ok"])
        self.assertEqual(st["state"], "KODI")
        self.assertTrue(st["p2p_allowed"])

        bad = await self._rpc(
            {"cmd": "acquire", "target": "WEB_APP", "owner": "panel", "app": "unknown"}
        )
        self.assertFalse(bad["ok"])
        st_after_bad = await self._rpc({"cmd": "status"})
        self.assertEqual(st_after_bad["state"], "KODI")

        acq_web = await self._rpc(
            {"cmd": "acquire", "target": "WEB_APP", "owner": "panel", "app": "youtube"}
        )
        self.assertTrue(acq_web["ok"])
        self.assertEqual(acq_web["state"], "WEB_APP")
        self.assertFalse(acq_web["p2p_allowed"])

        self.executor.calls.clear()
        air_r, air_w = await asyncio.open_unix_connection(self.sock_path)
        try:
            air_w.write(
                (
                    json.dumps(
                        {"cmd": "acquire", "target": "CAST_AIRPLAY", "owner": "airplay"}
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await air_w.drain()
            acq_air = json.loads(
                (await asyncio.wait_for(air_r.readline(), timeout=2.0)).decode("utf-8")
            )
            self.assertTrue(acq_air["ok"])
            self.assertEqual(acq_air["state"], "CAST_AIRPLAY")
            self.assertIn(("stop_unit", "web-app@youtube.service"), self.executor.calls)
            self.assertNotIn(("start_unit", "kodi.service"), self.executor.calls)

            wrong_rel = await self._rpc({"cmd": "release", "owner": "panel"})
            self.assertFalse(wrong_rel["ok"])

            rel = await self._rpc({"cmd": "release", "owner": "airplay"})
            self.assertTrue(rel["ok"])
            self.assertEqual(rel["state"], "KODI")
            self.assertTrue(rel["p2p_allowed"])
        finally:
            air_w.close()
            await air_w.wait_closed()

    async def test_kodi_playing_and_hotspot_flip_p2p_allowed(self):
        r1 = await self._rpc({"cmd": "set_kodi_playing", "playing": True})
        self.assertTrue(r1["ok"])
        self.assertFalse(r1["p2p_allowed"])

        r2 = await self._rpc({"cmd": "set_kodi_playing", "playing": False})
        self.assertTrue(r2["ok"])
        self.assertTrue(r2["p2p_allowed"])

        r3 = await self._rpc({"cmd": "set_hotspot", "active": True})
        self.assertTrue(r3["ok"])
        self.assertFalse(r3["p2p_allowed"])

        r4 = await self._rpc({"cmd": "set_hotspot", "active": False})
        self.assertTrue(r4["ok"])
        self.assertTrue(r4["p2p_allowed"])

    async def test_standby_and_wake_rpc_drive_executor(self):
        sb = await self._rpc({"cmd": "standby"})
        self.assertTrue(sb["ok"])
        self.assertEqual(sb["state"], "STANDBY")
        self.assertFalse(sb["p2p_allowed"])
        self.assertIn(("cec_standby", None), self.executor.calls)
        self.assertIn(("kms_dpms", False), self.executor.calls)
        self.assertIn(("set_governor", "powersave"), self.executor.calls)

        self.executor.calls.clear()
        wk = await self._rpc({"cmd": "wake"})
        self.assertTrue(wk["ok"])
        self.assertEqual(wk["state"], "KODI")
        self.assertTrue(wk["p2p_allowed"])
        self.assertIn(("set_governor", "ondemand"), self.executor.calls)
        self.assertIn(("kms_dpms", True), self.executor.calls)
        self.assertIn(("cec_wake", None), self.executor.calls)
        self.assertIn(("start_unit", "kodi.service"), self.executor.calls)

    async def test_cast_client_disconnect_auto_releases_to_kodi(self):
        for target, owner in (("CAST_AIRPLAY", "airplay"), ("CAST_MIRACAST", "miracast")):
            with self.subTest(target=target):
                reader, writer = await asyncio.open_unix_connection(self.sock_path)
                writer.write(
                    (json.dumps({"cmd": "acquire", "target": target, "owner": owner}) + "\n").encode("utf-8")
                )
                await writer.drain()
                resp = json.loads((await asyncio.wait_for(reader.readline(), timeout=2.0)).decode("utf-8"))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["state"], target)

                # Unexpected disconnect without calling release
                writer.close()
                await writer.wait_closed()

                # Give server loop a turn to process EOF and run cleanup
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    st = await self._rpc({"cmd": "status"})
                    if st["state"] == "KODI":
                        break
                self.assertEqual(st["state"], "KODI")
                self.assertIsNone(st["owner"])

    async def test_webapp_client_disconnect_does_not_auto_release(self):
        reader, writer = await asyncio.open_unix_connection(self.sock_path)
        writer.write(
            (json.dumps({"cmd": "acquire", "target": "WEB_APP", "owner": "panel", "app": "netflix"}) + "\n").encode("utf-8")
        )
        await writer.drain()
        resp = json.loads((await asyncio.wait_for(reader.readline(), timeout=2.0)).decode("utf-8"))
        self.assertTrue(resp["ok"])
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.05)
        st = await self._rpc({"cmd": "status"})
        self.assertEqual(st["state"], "WEB_APP")
        self.assertEqual(st["app"], "netflix")

    async def test_subscribe_receives_state_changed_and_p2p_allowed_events(self):
        sub_r, sub_w = await asyncio.open_unix_connection(self.sock_path)
        try:
            sub_w.write((json.dumps({"cmd": "subscribe"}) + "\n").encode("utf-8"))
            await sub_w.drain()
            ack = json.loads((await asyncio.wait_for(sub_r.readline(), timeout=2.0)).decode("utf-8"))
            self.assertTrue(ack["ok"])

            await self._rpc({"cmd": "set_kodi_playing", "playing": True})
            ev1 = json.loads((await asyncio.wait_for(sub_r.readline(), timeout=2.0)).decode("utf-8"))
            self.assertIn("p2p_allowed", ev1)
            self.assertFalse(ev1["p2p_allowed"])

            await self._rpc(
                {"cmd": "acquire", "target": "CAST_AIRPLAY", "owner": "airplay"}
            )
            ev2 = json.loads((await asyncio.wait_for(sub_r.readline(), timeout=2.0)).decode("utf-8"))
            self.assertEqual(ev2.get("event"), "state_changed")
            self.assertEqual(ev2.get("state"), "CAST_AIRPLAY")
            self.assertFalse(ev2.get("p2p_allowed"))
        finally:
            sub_w.close()
            await sub_w.wait_closed()

    async def test_concurrent_transitions_serialize_behind_lock(self):
        await self.server.stop()
        gate = asyncio.Event()
        first_entered = asyncio.Event()
        self.executor = FakeSystemExecutor(gate_event=gate)
        self.executor.on_first_stop = first_entered.set
        self.server = self.daemon.DisplayServer(
            sock_path=self.sock_path, executor=self.executor
        )
        await self.server.start()

        t1 = asyncio.create_task(
            self._rpc({"cmd": "acquire", "target": "WEB_APP", "owner": "panel", "app": "netflix"})
        )
        await asyncio.wait_for(first_entered.wait(), timeout=2.0)

        t2 = asyncio.create_task(
            self._rpc({"cmd": "acquire", "target": "CAST_AIRPLAY", "owner": "airplay"})
        )
        await asyncio.sleep(0.02)
        # While t1 is paused inside stop_unit("kodi.service"), t2 must not have started its stop_unit
        self.assertEqual(self.executor.calls, [("stop_unit", "kodi.service")])

        gate.set()
        r1, r2 = await asyncio.gather(t1, t2)
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["state"], "CAST_AIRPLAY")

        # t1's start_unit("web-app@netflix.service") must finish before t2's stop_unit("web-app@netflix.service")
        start_idx = self.executor.calls.index(("start_unit", "web-app@netflix.service"))
        stop_idx = self.executor.calls.index(("stop_unit", "web-app@netflix.service"))
        self.assertLess(start_idx, stop_idx)


class DisplayClientTests(unittest.TestCase):
    """Thin sync DisplayClient against the live Unix socket server."""

    def setUp(self):
        self.md = _load_core()
        self.daemon = _load_daemon()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sock_path = os.path.join(self.tmpdir.name, "display.sock")
        self.executor = FakeSystemExecutor()
        self.loop = asyncio.new_event_loop()
        self.server = self.daemon.DisplayServer(
            sock_path=self.sock_path, executor=self.executor
        )
        self.loop.run_until_complete(self.server.start())
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        fut = asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
        fut.result(timeout=2.0)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2.0)
        self.loop.close()
        self.tmpdir.cleanup()

    def test_sync_display_client_lifecycle(self):
        client = self.md.DisplayClient(self.sock_path)
        st = client.status()
        self.assertEqual(st["state"], "KODI")

        res = client.acquire("WEB_APP", owner="panel", app="max")
        self.assertEqual(res["state"], "WEB_APP")

        rel = client.release(owner="panel")
        self.assertEqual(rel["state"], "KODI")

        client.set_kodi_playing(True)
        self.assertFalse(client.status()["p2p_allowed"])
        client.set_kodi_playing(False)
        self.assertTrue(client.status()["p2p_allowed"])


class SystemdUnitTests(unittest.TestCase):
    """Verify mediastick-displayd.service unit configuration."""

    def test_service_unit_directives(self):
        self.assertTrue(os.path.exists(SERVICE_PATH), f"missing {SERVICE_PATH}")
        text = open(SERVICE_PATH, encoding="utf-8").read()
        for directive in (
            "Type=simple",
            "Restart=always",
            "OOMScoreAdjust=-200",
            "RuntimeDirectory=media-stick",
            "RuntimeDirectoryPreserve=yes",
            "ExecStart=/usr/bin/python3 /usr/local/bin/mediastick-displayd",
        ):
            self.assertIn(directive, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
