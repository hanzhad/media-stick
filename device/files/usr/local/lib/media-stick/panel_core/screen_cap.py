"""Unified TV screen capture for `/shot.jpg` (960x540 JPEG q75) and `/shot.png` (full-res PNG).

Pure Core:
  - resize_png_to_jpeg(png_bytes, max_width=960, max_height=540, quality=75)

Thin I/O Shell:
  - capture_jpeg(owner, kodi_shot_fn=None, run_cmd=None, ...)
  - capture_png(owner, kodi_shot_fn=None, run_cmd=None, ...)
    Routes:
      - airplay / miracast -> fast ScreenUnavailable(owner=..., status=409)
      - web-app            -> `grim` (`-t jpeg -q 70 -s 0.5 -` or `-t png -`)
      - kodi / ""          -> Kodi screenshot (+ Pillow resize/JPEG for capture_jpeg)
"""
import glob
import io
import os
import subprocess

from PIL import Image

CAST_OWNERS = frozenset({"airplay", "miracast"})
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 540
DEFAULT_QUALITY = 75


class ScreenUnavailable(Exception):
    """Raised when the screen cannot be captured (e.g. active AirPlay/Miracast cast)."""

    def __init__(self, owner: str, status: int = 409, message: str = ""):
        self.owner = owner
        self.status = status
        super().__init__(message or f"screen unavailable ({owner})")


# --- Pure Core ------------------------------------------------------------------------------------


def resize_png_to_jpeg(
    png_bytes: bytes,
    max_width: int = DEFAULT_WIDTH,
    max_height: int = DEFAULT_HEIGHT,
    quality: int = DEFAULT_QUALITY,
) -> bytes:
    """Decode PNG bytes and resize proportionally to fit `max_width x max_height` JPEG."""
    with Image.open(io.BytesIO(png_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.width > max_width or img.height > max_height:
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        return out.getvalue()


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _wayland_env() -> dict[str, str]:
    rt = f"/run/user/{os.getuid()}"
    socks = sorted(glob.glob(f"{rt}/wayland-[0-9]"))
    return dict(
        os.environ,
        XDG_RUNTIME_DIR=rt,
        WAYLAND_DISPLAY=os.path.basename(socks[-1]) if socks else "wayland-0",
    )


def _default_run_bytes(cmd, env=None, timeout=10) -> tuple[int, bytes]:
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 124, b""


def _capture_grim(cmd: list[str], magic: bytes, run_cmd=None, env=None) -> bytes:
    runner = run_cmd or _default_run_bytes
    rc, data = runner(cmd, env=env if env is not None else _wayland_env())
    if rc != 0 or not isinstance(data, (bytes, bytearray)) or not bytes(data).startswith(magic):
        raise ScreenUnavailable(owner="web-app", status=503, message="grim capture failed")
    return bytes(data)


def _capture_raw_png(
    owner: str,
    grim_cmd: list[str],
    grim_magic: bytes,
    kodi_shot_fn=None,
    run_cmd=None,
    env=None,
) -> tuple[bool, bytes]:
    if owner in CAST_OWNERS:
        raise ScreenUnavailable(owner=owner, status=409, message=f"TV busy with {owner}")

    if owner == "web-app":
        return True, _capture_grim(grim_cmd, grim_magic, run_cmd=run_cmd, env=env)

    if kodi_shot_fn is None:
        raise ScreenUnavailable(owner=owner or "kodi", status=503, message="no screenshot source")

    return False, bytes(kodi_shot_fn())


def capture_jpeg(
    owner: str,
    kodi_shot_fn=None,
    run_cmd=None,
    env=None,
    max_width: int = DEFAULT_WIDTH,
    max_height: int = DEFAULT_HEIGHT,
    quality: int = DEFAULT_QUALITY,
) -> bytes:
    """Capture current TV picture as JPEG bytes according to active screen owner."""
    from_grim, data = _capture_raw_png(
        owner,
        ["grim", "-t", "jpeg", "-q", "70", "-s", "0.5", "-"],
        b"\xff\xd8",
        kodi_shot_fn=kodi_shot_fn,
        run_cmd=run_cmd,
        env=env,
    )
    if from_grim:
        return data
    return resize_png_to_jpeg(data, max_width=max_width, max_height=max_height, quality=quality)


def capture_png(
    owner: str,
    kodi_shot_fn=None,
    run_cmd=None,
    env=None,
) -> bytes:
    """Capture current TV picture as full-resolution PNG bytes according to active screen owner."""
    _, data = _capture_raw_png(
        owner,
        ["grim", "-t", "png", "-"],
        b"\x89PNG\r\n\x1a\n",
        kodi_shot_fn=kodi_shot_fn,
        run_cmd=run_cmd,
        env=env,
    )
    return data
