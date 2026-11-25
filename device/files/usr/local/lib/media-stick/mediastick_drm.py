"""Shared libdrm & boot-splash helpers (Pure Core + Thin DRM I/O Shell).

Lights the connected HDMI display at 1920x1080 (or its preferred mode) with the boot
picture (black if unavailable) and drops DRM master so the GStreamer kmssink drawer
or Kodi can take over cleanly without a mode-set flash.
"""
import ctypes
import fcntl
import mmap
import os
import subprocess
import threading
import time

CARD = "/dev/dri/card0"
SPLASH = "/home/media/.kodi/media/splash.png"
SPLASH_CACHE = "/var/cache/media-stick"

c_u16, c_u32, c_u64, c_int = ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_int


class ModeInfo(ctypes.Structure):
    _fields_ = [("clock", c_u32), ("hdisplay", c_u16), ("hsync_start", c_u16),
                ("hsync_end", c_u16), ("htotal", c_u16), ("hskew", c_u16),
                ("vdisplay", c_u16), ("vsync_start", c_u16), ("vsync_end", c_u16),
                ("vtotal", c_u16), ("vscan", c_u16), ("vrefresh", c_u32),
                ("flags", c_u32), ("type", c_u32), ("name", ctypes.c_char * 32)]


class Resources(ctypes.Structure):
    _fields_ = [("count_fbs", c_int), ("fbs", ctypes.POINTER(c_u32)),
                ("count_crtcs", c_int), ("crtcs", ctypes.POINTER(c_u32)),
                ("count_connectors", c_int), ("connectors", ctypes.POINTER(c_u32)),
                ("count_encoders", c_int), ("encoders", ctypes.POINTER(c_u32)),
                ("min_width", c_u32), ("max_width", c_u32),
                ("min_height", c_u32), ("max_height", c_u32)]


class Connector(ctypes.Structure):
    _fields_ = [("connector_id", c_u32), ("encoder_id", c_u32), ("connector_type", c_u32),
                ("connector_type_id", c_u32), ("connection", c_int), ("mmWidth", c_u32),
                ("mmHeight", c_u32), ("subpixel", c_int), ("count_modes", c_int),
                ("modes", ctypes.POINTER(ModeInfo)), ("count_props", c_int),
                ("props", ctypes.POINTER(c_u32)), ("prop_values", ctypes.POINTER(c_u64)),
                ("count_encoders", c_int), ("encoders", ctypes.POINTER(c_u32))]


class Encoder(ctypes.Structure):
    _fields_ = [("encoder_id", c_u32), ("encoder_type", c_u32), ("crtc_id", c_u32),
                ("possible_crtcs", c_u32), ("possible_clones", c_u32)]


class CreateDumb(ctypes.Structure):
    _fields_ = [("height", c_u32), ("width", c_u32), ("bpp", c_u32), ("flags", c_u32),
                ("handle", c_u32), ("pitch", c_u32), ("size", c_u64)]


class MapDumb(ctypes.Structure):
    _fields_ = [("handle", c_u32), ("pad", c_u32), ("offset", c_u64)]


DRM_IOCTL_MODE_CREATE_DUMB = 0xC02064B2   # _IOWR('d', 0xB2, struct drm_mode_create_dumb)
DRM_IOCTL_MODE_MAP_DUMB = 0xC01064B3      # _IOWR('d', 0xB3, struct drm_mode_map_dumb)
DRM_MODE_CONNECTED = 1
DRM_MODE_FLAG_INTERLACE = 1 << 4
DRM_MODE_TYPE_PREFERRED = 1 << 3


def _default_log(*args):
    print("[drm]", *args, flush=True)


# --- Pure Core ------------------------------------------------------------------------------------


def put_rows(mem, data, w, h, pitch):
    """Copy w x h XRGB pixels into a buffer whose rows are pitch bytes apart."""
    row = w * 4
    if pitch == row:
        mem[:row * h] = data
        return
    for y in range(h):
        mem[y * pitch:y * pitch + row] = data[y * row:(y + 1) * row]


def _mode_rank(mode):
    return (
        mode.hdisplay == 1920 and mode.vdisplay == 1080,
        not (mode.flags & DRM_MODE_FLAG_INTERLACE),
        mode.vrefresh == 60,
        bool(mode.type & DRM_MODE_TYPE_PREFERRED),
    )


# --- Thin I/O Shell -------------------------------------------------------------------------------


def splash_pixels(w, h, splash=SPLASH, cache=SPLASH_CACHE, log=None):
    """The boot picture at w x h in XRGB8888 (bytes b, g, r, x), or None without it. ffmpeg
    makes it once (about a second on the Pi 3) and the result is kept for the next time."""
    raw = os.path.join(cache, "splash-%dx%d.xrgb" % (w, h))
    try:
        if os.path.getmtime(raw) >= os.path.getmtime(splash):
            with open(raw, "rb") as f:
                data = f.read()
            if len(data) == w * h * 4:
                return data
    except OSError:
        pass
    try:
        data = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", splash,
             "-vf", "scale=%d:%d" % (w, h), "-f", "rawvideo", "-pix_fmt", "bgr0", "-"],
            capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        (log or _default_log)("no boot picture for the switch:", e)
        return None
    if len(data) != w * h * 4:
        return None
    try:
        os.makedirs(cache, exist_ok=True)
        tmp = "%s.%d.tmp" % (raw, threading.get_ident())   # made at start and on a take
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, raw)
    except OSError:
        pass
    return data


def paint_splash(fd, dumb, w, h):
    """Put the boot picture into the dumb buffer (zero filled, black, otherwise)."""
    data = splash_pixels(w, h)
    if data is None:
        return
    m = MapDumb(handle=dumb.handle)
    fcntl.ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, m)
    with mmap.mmap(fd, dumb.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                   offset=m.offset) as mem:
        put_rows(mem, data, w, h, dumb.pitch)


def paint_or_black(fd, dumb, w, h, paint=paint_splash, log=None):
    """The boot picture into the buffer; any failure leaves it as it is, black."""
    try:
        paint(fd, dumb, w, h)
    except Exception as e:   # a picture is nice to have: the take goes on without it
        (log or _default_log)("boot picture not drawn, black instead:", e)


def light_screen(card=CARD):
    """Set the connected TV to 1920x1080 (or its preferred mode) showing the boot picture
    (black without it), then give up DRM master so the drawer, opening the screen next, gets
    it. Returns the open card (the picture lasts while it is open) and the mode's size."""
    drm = ctypes.CDLL("libdrm.so.2", use_errno=True)
    drm.drmModeGetResources.restype = ctypes.POINTER(Resources)
    drm.drmModeGetConnector.restype = ctypes.POINTER(Connector)
    drm.drmModeGetEncoder.restype = ctypes.POINTER(Encoder)
    fd = os.open(card, os.O_RDWR | os.O_CLOEXEC)
    try:
        # right after Kodi stops the screen can still be held for a moment (logind lets go
        # of Kodi's session after it exits): become master once nobody is
        for _ in range(25):
            if drm.drmSetMaster(fd) == 0:
                break
            time.sleep(0.2)
        else:
            raise OSError(ctypes.get_errno(), "the screen stays held by another program")
        res = drm.drmModeGetResources(fd)
        if not res:
            raise OSError(ctypes.get_errno(), "no DRM resources")
        r = res.contents
        for i in range(r.count_connectors):
            conn = drm.drmModeGetConnector(fd, r.connectors[i])
            if conn and conn.contents.connection == DRM_MODE_CONNECTED and conn.contents.count_modes:
                break
            if conn:
                drm.drmModeFreeConnector(conn)
        else:
            raise OSError("no screen connected")
        c = conn.contents
        modes = [c.modes[i] for i in range(c.count_modes)]
        best = max(modes, key=_mode_rank)
        mode = ModeInfo.from_buffer_copy(best)
        crtc = 0
        if c.encoder_id:
            enc = drm.drmModeGetEncoder(fd, c.encoder_id)
            if enc:
                crtc = enc.contents.crtc_id
                drm.drmModeFreeEncoder(enc)
        crtc = crtc or r.crtcs[0]
        dumb = CreateDumb(height=mode.vdisplay, width=mode.hdisplay, bpp=32)
        fcntl.ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, dumb)   # zero filled: black
        paint_or_black(fd, dumb, mode.hdisplay, mode.vdisplay)
        fb = c_u32()
        if drm.drmModeAddFB(fd, mode.hdisplay, mode.vdisplay, 24, 32, dumb.pitch, dumb.handle,
                            ctypes.byref(fb)):
            raise OSError(ctypes.get_errno(), "drmModeAddFB")
        conn_id = c_u32(c.connector_id)
        if drm.drmModeSetCrtc(fd, crtc, fb.value, 0, 0, ctypes.byref(conn_id), 1, ctypes.byref(mode)):
            raise OSError(ctypes.get_errno(), "drmModeSetCrtc")
        drm.drmDropMaster(fd)
        drm.drmModeFreeConnector(conn)
        drm.drmModeFreeResources(res)
        return fd, mode.hdisplay, mode.vdisplay
    except BaseException:
        os.close(fd)
        raise
