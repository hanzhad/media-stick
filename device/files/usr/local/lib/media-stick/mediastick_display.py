"""Display & power-state arbitrator core and client helpers.

Pure Core:
  - DisplayState: KODI, CAST_AIRPLAY, CAST_MIRACAST, WEB_APP, STANDBY
  - is_p2p_allowed(state, kodi_playing, hotspot_active)
  - DisplayStateMachine: deterministic transition planner and lease tracker

Thin Client:
  - DisplayClient (sync) / AsyncDisplayClient (asyncio) for /run/media-stick/display.sock

Standard library only; nothing happens on import.
"""
import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import os
import socket
import time

DEFAULT_SOCK = "/run/media-stick/display.sock"
WEB_APPS = frozenset({"netflix", "disney", "prime", "max", "youtube"})


class DisplayState(Enum):
    KODI = "KODI"
    CAST_AIRPLAY = "CAST_AIRPLAY"
    CAST_MIRACAST = "CAST_MIRACAST"
    WEB_APP = "WEB_APP"
    STANDBY = "STANDBY"


CAST_STATES = frozenset({DisplayState.CAST_AIRPLAY, DisplayState.CAST_MIRACAST})


class DisplayError(RuntimeError):
    """Raised when displayd rejects an RPC request or closes unexpectedly."""


@dataclass(frozen=True)
class Action:
    kind: str
    arg: object = None


@dataclass(frozen=True)
class TransitionPlan:
    target: DisplayState
    owner: object = None
    app: object = None
    actions: tuple = ()


def as_display_state(value):
    """Normalize a DisplayState or state name string into DisplayState."""
    if isinstance(value, DisplayState):
        return value
    if isinstance(value, str):
        try:
            return DisplayState[value]
        except KeyError:
            pass
    raise ValueError("unknown display state: %r" % (value,))


def is_p2p_allowed(state, kodi_playing, hotspot_active):
    """Miracast P2P listen is only safe when Kodi is idle on screen and no hotspot runs."""
    return (
        as_display_state(state) == DisplayState.KODI
        and not kodi_playing
        and not hotspot_active
    )


def _display_unit(state, app=None):
    if state == DisplayState.KODI:
        return "kodi.service"
    if state == DisplayState.WEB_APP and app:
        return "web-app@%s.service" % app
    return None


def _validate_target_app(target, app):
    if target == DisplayState.WEB_APP:
        if not isinstance(app, str) or app not in WEB_APPS:
            raise ValueError("unknown web app: %r" % (app,))
        return app
    return None


class DisplayStateMachine:
    """Deterministic display & power-state transition planner with lease ownership."""

    def __init__(self):
        self.state = DisplayState.KODI
        self.owner = None
        self.app = None
        self.since = None
        self.kodi_playing = False
        self.hotspot_active = False

    def plan_transition(
        self,
        target,
        owner=None,
        app=None,
        kodi_playing=None,
        hotspot_active=None,
    ):
        """Plan ordered side effects to transition from the current state to target."""
        target = as_display_state(target)
        valid_app = _validate_target_app(target, app)
        playing = self.kodi_playing if kodi_playing is None else bool(kodi_playing)
        hotspot = self.hotspot_active if hotspot_active is None else bool(hotspot_active)

        if target == self.state and (target != DisplayState.WEB_APP or valid_app == self.app):
            return TransitionPlan(
                target=target,
                owner=None if target == DisplayState.KODI else (owner if owner is not None else self.owner),
                app=valid_app,
                actions=(),
            )

        actions = []
        current_unit = _display_unit(self.state, self.app)

        if target == DisplayState.STANDBY:
            actions.append(Action("flush"))
            if current_unit:
                actions.append(Action("stop_unit", current_unit))
            actions.extend([
                Action("cec_standby"),
                Action("kms_dpms", False),
                Action("set_governor", "powersave"),
                Action("p2p_pause"),
            ])
            return TransitionPlan(
                target=DisplayState.STANDBY,
                owner=owner,
                app=None,
                actions=tuple(actions),
            )

        if self.state == DisplayState.STANDBY:
            actions.extend([
                Action("set_governor", "ondemand"),
                Action("kms_dpms", True),
                Action("cec_wake"),
            ])
        else:
            if current_unit:
                actions.append(Action("stop_unit", current_unit))
            actions.append(Action("draw_splash"))

        if target == DisplayState.KODI:
            actions.append(Action("start_unit", "kodi.service"))
            if is_p2p_allowed(DisplayState.KODI, playing, hotspot):
                actions.append(Action("p2p_resume"))
        elif target == DisplayState.WEB_APP:
            actions.append(Action("start_unit", _display_unit(DisplayState.WEB_APP, valid_app)))
            actions.append(Action("p2p_pause"))
        else:
            actions.append(Action("p2p_pause"))

        return TransitionPlan(
            target=target,
            owner=None if target == DisplayState.KODI else owner,
            app=valid_app,
            actions=tuple(actions),
        )

    def check_release(self, owner=None, force=False):
        """Validate release ownership and return the transition plan back to KODI."""
        if self.state == DisplayState.KODI:
            return TransitionPlan(target=DisplayState.KODI, owner=None, app=None, actions=())
        if not force and owner != self.owner:
            raise PermissionError("display lease held by %r, not %r" % (self.owner, owner))
        return self.plan_transition(DisplayState.KODI)

    def apply_plan(self, plan):
        """Commit a previously planned transition to the state machine."""
        if plan.target == DisplayState.KODI:
            self.state = DisplayState.KODI
            self.owner = None
            self.app = None
            self.since = None
        else:
            changed = (
                self.state != plan.target
                or self.owner != plan.owner
                or self.app != plan.app
                or self.since is None
            )
            self.state = plan.target
            self.owner = plan.owner
            self.app = plan.app
            if changed:
                self.since = time.time()

    def acquire(self, target, owner=None, app=None):
        """Plan and commit a transition to target."""
        plan = self.plan_transition(target, owner=owner, app=app)
        self.apply_plan(plan)
        return plan

    def release(self, owner=None, force=False):
        """Validate ownership, plan transition to KODI, and commit it."""
        plan = self.check_release(owner=owner, force=force)
        self.apply_plan(plan)
        return plan

    def snapshot(self):
        """Return a JSON-serializable status dict of the current state."""
        return {
            "state": self.state.name,
            "owner": self.owner,
            "app": self.app,
            "since": self.since,
            "kodi_playing": self.kodi_playing,
            "hotspot_active": self.hotspot_active,
            "p2p_allowed": is_p2p_allowed(self.state, self.kodi_playing, self.hotspot_active),
        }


def resolve_sock_path(sock_path=None):
    return sock_path or os.environ.get("DISPLAYD_SOCK") or DEFAULT_SOCK


def _build_acquire_payload(target, owner=None, app=None):
    target_name = target.name if isinstance(target, DisplayState) else str(target)
    payload = {"cmd": "acquire", "target": target_name}
    if owner is not None:
        payload["owner"] = owner
    if app is not None:
        payload["app"] = app
    return payload


class DisplayClient:
    """Synchronous line-delimited JSON RPC client for mediastick-displayd."""

    def __init__(self, sock_path=None, timeout=10.0):
        self.sock_path = resolve_sock_path(sock_path)
        self.timeout = timeout
        self._sock = None
        self._rfile = None

    def _connect(self):
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.sock_path)
        self._sock = sock
        self._rfile = sock.makefile("r", encoding="utf-8")

    def close(self):
        if self._rfile is not None:
            try:
                self._rfile.close()
            except OSError:
                pass
            self._rfile = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def request(self, payload):
        line_bytes = (json.dumps(payload) + "\n").encode("utf-8")
        for attempt in range(2):
            self._connect()
            try:
                self._sock.sendall(line_bytes)
                raw = self._rfile.readline()
                if not raw:
                    raise EOFError("displayd closed connection")
                resp = json.loads(raw)
                break
            except (OSError, EOFError):
                self.close()
                if attempt == 1:
                    raise
        if not resp.get("ok"):
            raise DisplayError(resp.get("error", "displayd request failed"))
        return resp

    def status(self):
        return self.request({"cmd": "status"})

    def acquire(self, target, owner=None, app=None):
        return self.request(_build_acquire_payload(target, owner=owner, app=app))

    def release(self, owner=None, force=False):
        payload = {"cmd": "release"}
        if owner is not None:
            payload["owner"] = owner
        if force:
            payload["force"] = True
        return self.request(payload)

    def standby(self, owner=None):
        payload = {"cmd": "standby"}
        if owner is not None:
            payload["owner"] = owner
        return self.request(payload)

    def wake(self):
        return self.request({"cmd": "wake"})

    def set_kodi_playing(self, playing):
        return self.request({"cmd": "set_kodi_playing", "playing": bool(playing)})

    def set_hotspot(self, active):
        return self.request({"cmd": "set_hotspot", "active": bool(active)})


class AsyncDisplayClient:
    """Asyncio line-delimited JSON RPC client for mediastick-displayd."""

    def __init__(self, sock_path=None, timeout=10.0):
        self.sock_path = resolve_sock_path(sock_path)
        self.timeout = timeout
        self._reader = None
        self._writer = None

    async def _connect(self):
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.open_unix_connection(self.sock_path)

    async def close(self):
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def __aenter__(self):
        await self._connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def request(self, payload):
        line_bytes = (json.dumps(payload) + "\n").encode("utf-8")
        await self._connect()
        self._writer.write(line_bytes)
        await self._writer.drain()
        raw = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
        if not raw:
            await self.close()
            raise DisplayError("displayd closed connection")
        resp = json.loads(raw.decode("utf-8"))
        if not resp.get("ok"):
            raise DisplayError(resp.get("error", "displayd request failed"))
        return resp

    async def status(self):
        return await self.request({"cmd": "status"})

    async def acquire(self, target, owner=None, app=None):
        return await self.request(_build_acquire_payload(target, owner=owner, app=app))

    async def release(self, owner=None, force=False):
        payload = {"cmd": "release"}
        if owner is not None:
            payload["owner"] = owner
        if force:
            payload["force"] = True
        return await self.request(payload)

    async def standby(self, owner=None):
        payload = {"cmd": "standby"}
        if owner is not None:
            payload["owner"] = owner
        return await self.request(payload)

    async def wake(self):
        return await self.request({"cmd": "wake"})

    async def set_kodi_playing(self, playing):
        return await self.request({"cmd": "set_kodi_playing", "playing": bool(playing)})

    async def set_hotspot(self, active):
        return await self.request({"cmd": "set_hotspot", "active": bool(active)})
