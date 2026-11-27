"""HDMI / 3.5mm audio output preference & PipeWire wpctl switcher.

Pure Core (stdlib-only, zero xbmc imports):
  - normalize_output, parse_wpctl_sinks, pick_sink_id
  - build_set_default_cmd, build_set_volume_cmd

Thin I/O Shell:
  - read_output, write_output: atomic persistence under MEDIASTICK_PREFS_DIR/audio-output
  - wpctl_env, apply_output: apply saved or explicit output via `wpctl`
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

VALID_OUTPUTS = ("hdmi", "headphones")
DEFAULT_OUTPUT = "hdmi"

PREFS_DIR = os.environ.get("MEDIASTICK_PREFS_DIR", "/var/lib/media-stick/prefs")
PREFS_FILE = "audio-output"

_STOP_PREFIXES = ("Sources:", "Filters:", "Streams:", "Devices:", "Video", "Settings")
_SINK_LINE_RE = re.compile(r"^(\*)?\s*(\d+)\.\s+(.+?)\s*$")
_VOL_SUFFIX_RE = re.compile(r"\s*\[vol:[^\]]*\]\s*$")


# --- Pure Core ------------------------------------------------------------------------------------


def normalize_output(value) -> str:
    """Normalize audio output preference; returns 'headphones' only when matched, else 'hdmi'."""
    if isinstance(value, str) and value.strip().lower() == "headphones":
        return "headphones"
    return DEFAULT_OUTPUT


def _strip_tree_prefix(line: str) -> str:
    return line.lstrip(" \t│├└─")


def _classify_sink(name: str) -> str:
    lower = name.lower()
    if "hdmi" in lower or "vc4" in lower:
        return "hdmi"
    if "digital" not in lower and (
        "headphones" in lower
        or "bcm2835" in lower
        or "analog" in lower
        or "mailbox" in lower
        or "built-in audio stereo" in lower
    ):
        return "headphones"
    return "other"


def parse_wpctl_sinks(status_text: str) -> list[dict]:
    """Parse the Audio -> Sinks: section of `wpctl status` output."""
    if not isinstance(status_text, str) or not status_text:
        return []

    sinks: list[dict] = []
    in_audio = False
    in_sinks = False

    for raw_line in status_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Top-level sections have no leading whitespace or tree glyphs
        if raw_line[0] not in (" ", "\t", "│", "├", "└", "─"):
            if stripped == "Audio":
                in_audio = True
                in_sinks = False
            else:
                in_audio = False
                in_sinks = False
            continue

        if not in_audio:
            continue

        clean = _strip_tree_prefix(raw_line)
        if clean.startswith("Sinks:"):
            in_sinks = True
            continue
        if in_sinks and any(clean.startswith(prefix) for prefix in _STOP_PREFIXES):
            in_sinks = False
            continue
        if not in_sinks:
            continue

        match = _SINK_LINE_RE.match(clean)
        if not match:
            continue
        star, id_str, raw_name = match.groups()
        name = _VOL_SUFFIX_RE.sub("", raw_name).strip()
        sinks.append(
            {
                "id": int(id_str),
                "name": name,
                "default": bool(star),
                "kind": _classify_sink(name),
            }
        )

    return sinks


def pick_sink_id(sinks: list[dict], output: str) -> int | None:
    """Pick the sink id matching normalized output ('hdmi' or 'headphones'), or None."""
    target = normalize_output(output)
    for sink in sinks or ():
        if isinstance(sink, dict) and sink.get("kind") == target:
            sink_id = sink.get("id")
            if sink_id is not None:
                return int(sink_id)
    return None


def build_set_default_cmd(sink_id: int) -> list[str]:
    """Build `wpctl set-default <id>` command."""
    return ["wpctl", "set-default", str(int(sink_id))]


def build_set_volume_cmd(sink_id: int, volume: str = "1.0") -> list[str]:
    """Build `wpctl set-volume <id> <volume>` command."""
    return ["wpctl", "set-volume", str(int(sink_id)), str(volume)]


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _prefs_path() -> str:
    return os.path.join(PREFS_DIR, PREFS_FILE)


def read_output() -> str:
    """Read saved audio output preference; defaults to 'hdmi' if missing or invalid."""
    try:
        with open(_prefs_path(), encoding="utf-8") as f:
            raw = f.readline()
    except (OSError, ValueError):
        return DEFAULT_OUTPUT
    return normalize_output(raw)


def write_output(value: str) -> str:
    """Validate strictly against VALID_OUTPUTS and persist atomically with mode 0644."""
    if not isinstance(value, str) or value not in VALID_OUTPUTS:
        raise ValueError(f"invalid audio output: {value!r}")

    target = _prefs_path()
    os.makedirs(PREFS_DIR, mode=0o755, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".audio-output-", suffix=".tmp", dir=PREFS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value + "\n")
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return value


def wpctl_env(uid: int | None = None) -> dict[str, str]:
    """Copy environment and ensure XDG_RUNTIME_DIR is populated for user PipeWire socket."""
    env = dict(os.environ)
    if uid is not None:
        env["XDG_RUNTIME_DIR"] = f"/run/user/{int(uid)}"
    elif not env.get("XDG_RUNTIME_DIR"):
        env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    return env


def _default_run(cmd: list[str], env: dict[str, str] | None = None, timeout: float = 3):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _unpack_result(res) -> tuple[int, str]:
    if hasattr(res, "returncode"):
        return int(res.returncode), str(getattr(res, "stdout", "") or "")
    return int(res[0]), str(res[1] or "")


def apply_output(
    output: str | None = None,
    *,
    ensure_full_volume: bool = False,
    run_cmd=None,
    env: dict[str, str] | None = None,
) -> dict:
    """Apply saved or explicit audio output via `wpctl`. Never raises if PipeWire is unavailable."""
    target = normalize_output(output if output is not None else read_output())
    runner = run_cmd or _default_run
    run_env = dict(env) if env is not None else wpctl_env()

    try:
        rc, stdout = _unpack_result(runner(["wpctl", "status"], env=run_env, timeout=3))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"ok": True, "output": target, "applied": False, "sink_id": None}

    if rc != 0:
        return {"ok": True, "output": target, "applied": False, "sink_id": None}

    sink_id = pick_sink_id(parse_wpctl_sinks(stdout), target)
    if sink_id is None:
        return {"ok": True, "output": target, "applied": False, "sink_id": None}

    try:
        rc_def, _ = _unpack_result(runner(build_set_default_cmd(sink_id), env=run_env, timeout=3))
        if rc_def != 0:
            return {"ok": True, "output": target, "applied": False, "sink_id": None}
        if ensure_full_volume:
            rc_vol, _ = _unpack_result(runner(build_set_volume_cmd(sink_id, "1.0"), env=run_env, timeout=3))
            if rc_vol != 0:
                return {"ok": True, "output": target, "applied": False, "sink_id": None}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"ok": True, "output": target, "applied": False, "sink_id": None}

    return {"ok": True, "output": target, "applied": True, "sink_id": sink_id}
