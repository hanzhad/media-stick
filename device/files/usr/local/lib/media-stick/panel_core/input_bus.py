"""Dual persistent uinput (pointer + keyboard), PipeWire wpctl volume, and UTF-8 fallback.

Pure Core:
  - pack_input_event, pack_uinput_setup, pack_uinput_abs_setup
  - clamp_abs, build_pointer_move_events, build_key_events
  - build_volume_cmd, ascii_key_sequence

Thin I/O Shell:
  - InputBus: manages `media-stick-pointer` and `media-stick-kbd` on /dev/uinput
    without external python3-evdev, non-blocking move_by, wpctl volume, and wtype fallback.
"""
import fcntl
import glob
import os
import struct
import subprocess
import threading
import time

SCREEN_W = 1920
SCREEN_H = 1080

POINTER_NAME = "media-stick-pointer"
KBD_NAME = "media-stick-kbd"
POINTER_ACTIONS = frozenset({"click", "right", "move", "move_by", "scroll"})

# Linux input event constants (<linux/input-event-codes.h> & <linux/uinput.h>)
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT = 0

REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08

ABS_X = 0x00
ABS_Y = 0x01

BTN_LEFT = 0x110
BTN_RIGHT = 0x111

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567

KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_6 = 7
KEY_7 = 8
KEY_8 = 9
KEY_9 = 10
KEY_0 = 11
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_Q = 16
KEY_W = 17
KEY_E = 18
KEY_R = 19
KEY_T = 20
KEY_Y = 21
KEY_U = 22
KEY_I = 23
KEY_O = 24
KEY_P = 25
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_ENTER = 28
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_SEMICOLON = 39
KEY_APOSTROPHE = 40
KEY_LEFTSHIFT = 42
KEY_BACKSLASH = 43
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_COMMA = 51
KEY_DOT = 52
KEY_SLASH = 53
KEY_SPACE = 57
KEY_F11 = 87
KEY_UP = 103
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_MENU = 139
KEY_BACK = 158
KEY_NEXTSONG = 163
KEY_PLAYPAUSE = 164
KEY_PREVIOUSSONG = 165
KEY_STOPCD = 166
KEY_REWIND = 168
KEY_HOMEPAGE = 172
KEY_FASTFORWARD = 208
KEY_INFO = 358

WEB_ACTION_KEYS = {
    "up": KEY_UP,
    "down": KEY_DOWN,
    "left": KEY_LEFT,
    "right": KEY_RIGHT,
    "select": KEY_ENTER,
    "back": KEY_ESC,
    "playpause": KEY_SPACE,
    "fastforward": KEY_RIGHT,
    "rewind": KEY_LEFT,
    "fullscreen": KEY_F,
    "mute": KEY_M,
}

WEB_KEYNAME_CODES = {
    "Up": KEY_UP,
    "Down": KEY_DOWN,
    "Left": KEY_LEFT,
    "Right": KEY_RIGHT,
    "Return": KEY_ENTER,
    "Escape": KEY_ESC,
    "space": KEY_SPACE,
    "f": KEY_F,
    "m": KEY_M,
    "BackSpace": KEY_BACKSPACE,
    "Tab": KEY_TAB,
}

KBD_KEYCODES = tuple(sorted({
    KEY_ESC, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_0,
    KEY_MINUS, KEY_EQUAL, KEY_BACKSPACE, KEY_TAB, KEY_Q, KEY_W, KEY_E, KEY_R, KEY_T,
    KEY_Y, KEY_U, KEY_I, KEY_O, KEY_P, KEY_LEFTBRACE, KEY_RIGHTBRACE, KEY_ENTER,
    KEY_A, KEY_S, KEY_D, KEY_F, KEY_G, KEY_H, KEY_J, KEY_K, KEY_L, KEY_SEMICOLON,
    KEY_APOSTROPHE, KEY_LEFTSHIFT, KEY_BACKSLASH, KEY_Z, KEY_X, KEY_C, KEY_V, KEY_B,
    KEY_N, KEY_M, KEY_COMMA, KEY_DOT, KEY_SLASH, KEY_SPACE, KEY_F11,
    KEY_UP, KEY_LEFT, KEY_RIGHT, KEY_DOWN,
    KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP,
    KEY_MENU, KEY_BACK, KEY_NEXTSONG, KEY_PLAYPAUSE, KEY_PREVIOUSSONG,
    KEY_STOPCD, KEY_REWIND, KEY_HOMEPAGE, KEY_FASTFORWARD, KEY_INFO,
}))

_CHAR_MAP = {
    "a": (KEY_A, False), "b": (KEY_B, False), "c": (KEY_C, False), "d": (KEY_D, False),
    "e": (KEY_E, False), "f": (KEY_F, False), "g": (KEY_G, False), "h": (KEY_H, False),
    "i": (KEY_I, False), "j": (KEY_J, False), "k": (KEY_K, False), "l": (KEY_L, False),
    "m": (KEY_M, False), "n": (KEY_N, False), "o": (KEY_O, False), "p": (KEY_P, False),
    "q": (KEY_Q, False), "r": (KEY_R, False), "s": (KEY_S, False), "t": (KEY_T, False),
    "u": (KEY_U, False), "v": (KEY_V, False), "w": (KEY_W, False), "x": (KEY_X, False),
    "y": (KEY_Y, False), "z": (KEY_Z, False),
    "0": (KEY_0, False), "1": (KEY_1, False), "2": (KEY_2, False), "3": (KEY_3, False),
    "4": (KEY_4, False), "5": (KEY_5, False), "6": (KEY_6, False), "7": (KEY_7, False),
    "8": (KEY_8, False), "9": (KEY_9, False),
    " ": (KEY_SPACE, False), "\n": (KEY_ENTER, False), "\t": (KEY_TAB, False),
    "-": (KEY_MINUS, False), "_": (KEY_MINUS, True), "=": (KEY_EQUAL, False),
    "+": (KEY_EQUAL, True), "[": (KEY_LEFTBRACE, False), "]": (KEY_RIGHTBRACE, False),
    ";": (KEY_SEMICOLON, False), ":": (KEY_SEMICOLON, True),
    "'": (KEY_APOSTROPHE, False), '"': (KEY_APOSTROPHE, True),
    "\\": (KEY_BACKSLASH, False), ",": (KEY_COMMA, False), ".": (KEY_DOT, False),
    "/": (KEY_SLASH, False), "?": (KEY_SLASH, True),
    "!": (KEY_1, True), "@": (KEY_2, True), "#": (KEY_3, True), "$": (KEY_4, True),
    "%": (KEY_5, True), "&": (KEY_7, True), "*": (KEY_8, True),
    "(": (KEY_9, True), ")": (KEY_0, True),
}
for _ch in "abcdefghijklmnopqrstuvwxyz":
    _CHAR_MAP[_ch.upper()] = (_CHAR_MAP[_ch][0], True)


class InputUnavailable(Exception):
    """Raised when /dev/uinput cannot be opened or written."""


PointerUnavailable = InputUnavailable


# --- Pure Core ------------------------------------------------------------------------------------


def pack_input_event(ev_type: int, code: int, value: int) -> bytes:
    """Pack a Linux `struct input_event` (tv_sec=0, tv_usec=0, type, code, value)."""
    return struct.pack("llHHi", 0, 0, ev_type, code, value)


def pack_uinput_setup(
    name: str,
    bustype: int = 0x03,
    vendor: int = 0x1234,
    product: int = 0x5678,
    version: int = 1,
) -> bytes:
    """Pack `struct uinput_setup` for UI_DEV_SETUP."""
    raw_name = name.encode("utf-8")[:79]
    return struct.pack("4H80sI", bustype, vendor, product, version, raw_name, 0)


def pack_uinput_abs_setup(code: int, maximum: int, minimum: int = 0) -> bytes:
    """Pack `struct uinput_abs_setup` for UI_ABS_SETUP."""
    return struct.pack("H2x6i", code, 0, minimum, maximum, 0, 0, 0)


def clamp_abs(fx: float, fy: float, width: int = SCREEN_W, height: int = SCREEN_H) -> tuple[int, int]:
    """Convert normalized [0..1] screen fractions to integer ABS_X/ABS_Y coordinates."""
    cx = min(1.0, max(0.0, float(fx)))
    cy = min(1.0, max(0.0, float(fy)))
    return round(cx * (width - 1)), round(cy * (height - 1))


def build_pointer_move_events(fx: float, fy: float) -> bytes:
    """Encode ABS_X, ABS_Y, and SYN_REPORT input events."""
    ax, ay = clamp_abs(fx, fy)
    return (
        pack_input_event(EV_ABS, ABS_X, ax)
        + pack_input_event(EV_ABS, ABS_Y, ay)
        + pack_input_event(EV_SYN, SYN_REPORT, 0)
    )


def build_key_events(keycode: int, press: bool = True, release: bool = True) -> bytes:
    """Encode key press/release + SYN_REPORT events."""
    buf = bytearray()
    if press:
        buf.extend(pack_input_event(EV_KEY, keycode, 1))
        buf.extend(pack_input_event(EV_SYN, SYN_REPORT, 0))
    if release:
        buf.extend(pack_input_event(EV_KEY, keycode, 0))
        buf.extend(pack_input_event(EV_SYN, SYN_REPORT, 0))
    return bytes(buf)


def build_volume_cmd(action: str) -> list[str]:
    """Build PipeWire wpctl command for volumeup, volumedown, or mute."""
    if action == "volumeup":
        return ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"]
    if action == "volumedown":
        return ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]
    if action == "mute":
        return ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
    raise ValueError(f"unknown volume action: {action!r}")


def ascii_key_sequence(text: str) -> list[tuple[int, bool]] | None:
    """Convert pure ASCII text into (keycode, shift) pairs, or None if fallback needed."""
    seq: list[tuple[int, bool]] = []
    for ch in text:
        mapped = _CHAR_MAP.get(ch)
        if mapped is None:
            return None
        seq.append(mapped)
    return seq


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _default_run(cmd, env=None, timeout=10):
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""


def wayland_env() -> dict[str, str]:
    rt = f"/run/user/{os.getuid()}"
    socks = sorted(glob.glob(f"{rt}/wayland-[0-9]"))
    return dict(
        os.environ,
        XDG_RUNTIME_DIR=rt,
        WAYLAND_DISPLAY=os.path.basename(socks[-1]) if socks else "wayland-0",
    )


def _write_raw(dev, payload: bytes) -> None:
    if isinstance(dev, int):
        os.write(dev, payload)
    else:
        dev.write(payload)


def _close_raw(dev) -> None:
    if dev is None:
        return
    if isinstance(dev, int):
        try:
            fcntl.ioctl(dev, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(dev)
        except OSError:
            pass
    else:
        try:
            dev.close()
        except OSError:
            pass


class InputBus:
    """Dual persistent uinput devices (`media-stick-pointer` + `media-stick-kbd`)."""

    SETTLE_S = 2.2
    RETRY_S = 5.0

    def __init__(
        self,
        uinput_path: str = "/dev/uinput",
        run_cmd=None,
        sleep_fn=None,
        env_fn=None,
    ):
        self.uinput_path = uinput_path
        self._run_cmd = run_cmd or _default_run
        self._sleep = sleep_fn or time.sleep
        self._env_fn = env_fn or wayland_env

        self.lock = threading.RLock()
        self._pointer_fd = None
        self._kbd_fd = None
        self._ready_at = 0.0
        self._tried = 0.0
        self.err = ""
        self.x: float | None = None
        self.y: float | None = None

    def _open_pointer(self) -> int:
        fd = os.open(self.uinput_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
            fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_RIGHT)

            fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
            fcntl.ioctl(fd, UI_SET_RELBIT, REL_X)
            fcntl.ioctl(fd, UI_SET_RELBIT, REL_Y)
            fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)

            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            fcntl.ioctl(fd, UI_SET_ABSBIT, ABS_X)
            fcntl.ioctl(fd, UI_SET_ABSBIT, ABS_Y)
            fcntl.ioctl(fd, UI_ABS_SETUP, pack_uinput_abs_setup(ABS_X, SCREEN_W - 1))
            fcntl.ioctl(fd, UI_ABS_SETUP, pack_uinput_abs_setup(ABS_Y, SCREEN_H - 1))

            fcntl.ioctl(fd, UI_DEV_SETUP, pack_uinput_setup(POINTER_NAME))
            fcntl.ioctl(fd, UI_DEV_CREATE)
            return fd
        except OSError:
            os.close(fd)
            raise

    def _open_kbd(self) -> int:
        fd = os.open(self.uinput_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            for code in KBD_KEYCODES:
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)
            fcntl.ioctl(fd, UI_DEV_SETUP, pack_uinput_setup(KBD_NAME))
            fcntl.ioctl(fd, UI_DEV_CREATE)
            return fd
        except OSError:
            os.close(fd)
            raise

    def _open(self) -> None:
        now = time.time()
        if (self._pointer_fd is not None and self._kbd_fd is not None) or (now - self._tried < self.RETRY_S):
            return
        self._tried = now
        try:
            if self._pointer_fd is None:
                self._pointer_fd = self._open_pointer()
                self._ready_at = now + self.SETTLE_S
            if self._kbd_fd is None:
                self._kbd_fd = self._open_kbd()
            self.err = ""
        except OSError as exc:
            self.err = f"нет доступа к {self.uinput_path} ({exc.strerror or exc})"

    def start(self) -> None:
        """Create dual uinput devices in the background so the first tap need not wait."""
        def _go():
            with self.lock:
                self._open()
        threading.Thread(target=_go, name="input-bus-init", daemon=True).start()

    def close(self) -> None:
        with self.lock:
            _close_raw(self._pointer_fd)
            _close_raw(self._kbd_fd)
            self._pointer_fd = None
            self._kbd_fd = None
            self._tried = 0.0

    def _ensure_pointer(self):
        if self._pointer_fd is None:
            self._open()
        if self._pointer_fd is None:
            raise InputUnavailable(self.err or "устройство не создано")
        wait = self._ready_at - time.time()
        if wait > 0:
            self._sleep(wait)
        return self._pointer_fd

    def move_to(self, fx: float, fy: float, settle: float = 0.0) -> None:
        """Move pointer to normalized screen fraction `(fx, fy)` with zero default sleep."""
        with self.lock:
            dev = self._pointer_fd
            if dev is None:
                dev = self._ensure_pointer()
            cx = min(1.0, max(0.0, float(fx)))
            cy = min(1.0, max(0.0, float(fy)))
            _write_raw(dev, build_pointer_move_events(cx, cy))
            self.x, self.y = cx, cy
            if settle > 0:
                self._sleep(settle)

    def move_by(self, dfx: float, dfy: float) -> None:
        """Relative move in screen fractions without blocking or calling sleep."""
        with self.lock:
            fx = 0.5 if self.x is None else self.x
            fy = 0.5 if self.y is None else self.y
            nx = min(1.0, max(0.0, fx + float(dfx)))
            ny = min(1.0, max(0.0, fy + float(dfy)))
            dev = self._pointer_fd
            if dev is None:
                dev = self._ensure_pointer()
            _write_raw(dev, build_pointer_move_events(nx, ny))
            self.x, self.y = nx, ny

    def act(self, action: str, fx=None, fy=None, wheel: int = 0) -> None:
        """Execute pointer action (`move`, `move_by`, `click`, `right`, `scroll`)."""
        with self.lock:
            dev = self._ensure_pointer()
            try:
                if fx is None:
                    fx = 0.5 if self.x is None else self.x
                    fy = 0.5 if self.y is None else self.y
                if action == "move":
                    self.move_to(fx, fy, 0.0)
                elif action == "move_by":
                    self.move_by(fx, fy)
                elif action in ("click", "right"):
                    self.move_to(fx, fy, 0.0)
                    btn = BTN_LEFT if action == "click" else BTN_RIGHT
                    _write_raw(dev, pack_input_event(EV_KEY, btn, 1) + pack_input_event(EV_SYN, SYN_REPORT, 0))
                    self._sleep(0.02)
                    _write_raw(dev, pack_input_event(EV_KEY, btn, 0) + pack_input_event(EV_SYN, SYN_REPORT, 0))
                elif action == "scroll":
                    self.move_to(fx, fy, 0.0)
                    direction = 1 if wheel > 0 else -1
                    for _ in range(abs(int(wheel))):
                        _write_raw(
                            dev,
                            pack_input_event(EV_REL, REL_WHEEL, direction) + pack_input_event(EV_SYN, SYN_REPORT, 0),
                        )
            except OSError as exc:
                self.close()
                raise InputUnavailable(f"устройство пропало ({exc.strerror or exc})")

    def set_volume(self, action: str) -> None:
        """Adjust system volume via PipeWire `wpctl`."""
        cmd = build_volume_cmd(action)
        self._run_cmd(cmd)

    def send_key(self, key: str) -> None:
        """Send a navigation/browser key via uinput keyboard, falling back to wtype."""
        code = WEB_ACTION_KEYS.get(key) or WEB_KEYNAME_CODES.get(key)
        with self.lock:
            if code is not None:
                if self._kbd_fd is None:
                    self._open()
                if self._kbd_fd is not None:
                    try:
                        _write_raw(self._kbd_fd, build_key_events(code))
                        return
                    except OSError:
                        pass
        self._run_cmd(["wtype", "-k", key], env=self._env_fn())

    def type_text(self, text: str) -> None:
        """Type text via uinput keyboard for ASCII, or minimal `wtype` UTF-8 fallback."""
        if not text:
            return
        seq = ascii_key_sequence(text)
        with self.lock:
            if seq is not None:
                if self._kbd_fd is None:
                    self._open()
                if self._kbd_fd is not None:
                    try:
                        buf = bytearray()
                        for code, shift in seq:
                            if shift:
                                buf.extend(pack_input_event(EV_KEY, KEY_LEFTSHIFT, 1))
                                buf.extend(pack_input_event(EV_SYN, SYN_REPORT, 0))
                            buf.extend(build_key_events(code))
                            if shift:
                                buf.extend(pack_input_event(EV_KEY, KEY_LEFTSHIFT, 0))
                                buf.extend(pack_input_event(EV_SYN, SYN_REPORT, 0))
                        _write_raw(self._kbd_fd, bytes(buf))
                        return
                    except OSError:
                        pass
        self._run_cmd(["wtype", "--", text], env=self._env_fn())
