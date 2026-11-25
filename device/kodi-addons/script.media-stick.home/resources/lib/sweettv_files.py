"""SWEET.TV app: where its data lives and how it is read: the plugin's channel list (special://temp), the
add-on's own state file (see sweettv_state), the plugin's `logged` setting and the network the stick is on.
Thin: each function is one look at a file; what to make of it is sweettv_data's business."""
import json
import os
from typing import NamedTuple, Optional

import xbmcgui
import xbmcvfs

from resources.lib import apps, net, sweettv_data as data, ui

CHANNEL_FILE = "special://temp/channelList.json"
QR_FAILED = set()
_LAST_RAW = (None, None, None)


def channel_path():
    return xbmcvfs.translatePath(CHANNEL_FILE)


def state_path():
    return os.path.join(xbmcvfs.translatePath(apps.RECENT_DIR), "sweettv.json")


def file_stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def read_catalog(path, now):
    """The catalog in the plugin's file, or None when it cannot be read now (missing, half written, not JSON)."""
    global _LAST_RAW
    try:
        with open(path, "rb") as f:
            raw = json.load(f)
    except (OSError, ValueError, MemoryError) as e:
        ui.log(f"channel list not readable: {e!r}")
        return None
    if isinstance(raw, dict):
        _LAST_RAW = (path, file_stamp(path), raw)
    return data.parse_catalog(raw, now)


def read_raw(path):
    """The plugin's channel list as it is (a dict), or None when it cannot be read now."""
    global _LAST_RAW
    stamp = file_stamp(path)
    if _LAST_RAW[0] == path and _LAST_RAW[1] == stamp and _LAST_RAW[2] is not None:
        return _LAST_RAW[2]
    try:
        with open(path, "rb") as f:
            raw = json.load(f)
    except (OSError, ValueError, MemoryError) as e:
        ui.log(f"channel list not readable for the sections: {e!r}")
        return None
    if isinstance(raw, dict):
        _LAST_RAW = (path, stamp, raw)
        return raw
    return None


def language() -> str:
    """The device's language as SWEET.TV's own list names it ("ru", "uk", "en", ...), the one the strings of the screen follow:
    the Home property the launcher keeps (lang.reconcile), else the file the phone's "Language" writes, else Russian."""
    try:
        from resources.lib import lang as launcher      # also puts the device's library on the path
        import mediastick_lang
        return mediastick_lang.resolve(xbmcgui.Window(ui.HOME).getProperty(launcher.PROPERTY) or mediastick_lang.read()).sweet
    except Exception as e:
        ui.log(f"cannot tell the device's language: {e!r}")
        return "ru"


def signed_in():
    """True/False as the plugin's `logged` setting says; None when the sign-in library is not on this device."""
    try:
        from resources.lib import store
        return bool(store.lib.sweettv_signed_in())
    except Exception as e:
        ui.log(f"cannot tell whether SWEET.TV is signed in: {e!r}")
        return None


def network():
    """(address, "wifi" | "ethernet" | "") of the stick's network for the pill at the top; ("", "") when offline."""
    try:
        ip = net.address()
        return ip, (net.kind() if ip else "")
    except Exception as e:
        ui.log(f"network state unknown: {e!r}")
        return "", ""


class Snapshot(NamedTuple):
    signed: bool
    catalog: Optional[data.Catalog]
    stamp: Optional[tuple]       # (mtime_ns, size) of the file the catalog came from
    mtime: Optional[float]
    has_file: bool
    unreadable: bool             # the file is there but could not be read this time


def snapshot(now, catalog, stamp, mtime) -> Snapshot:
    """What there is to show now. `catalog`, `stamp` and `mtime` are what the last good look found: they are
    reused while the file is unchanged (parsing once per change), and kept when it cannot be read this time."""
    signed, path = signed_in(), channel_path()
    found = file_stamp(path)
    if signed is None:
        signed = found is not None
    if not signed:
        return Snapshot(False, None, None, None, found is not None, False)
    if found is None:
        return Snapshot(True, None, None, None, False, False)
    if found == stamp and catalog is not None:
        return Snapshot(True, catalog, found, mtime, True, False)
    fresh = read_catalog(path, now)
    if fresh is None or (fresh.error and catalog is not None and catalog.channels):
        # half written, perhaps, or the service had a bad moment: what is shown stays, the next look tries again
        return Snapshot(True, catalog, stamp, mtime, True, True)
    return Snapshot(True, fresh, found, found[0] / 1e9, True, False)


def phone_page():
    """(address of the phone page, QR picture of it); ("", "") when the stick has no network. The QR is
    cached by address, so a look costs a state-file read; any failure leaves the picture out."""
    try:
        from resources.lib import remote
        ip = net.address()
        url = remote.page_url(ip) if ip else ""
    except Exception as e:
        ui.log(f"phone page address unknown: {e!r}")
        return "", ""
    if not url or url in QR_FAILED:
        return url, ""
    try:
        return url, remote.qr_png(url)
    except Exception as e:
        QR_FAILED.add(url)                       # one try per address: the next look is three seconds away
        ui.log(f"phone page QR failed: {e!r}")
        return url, ""


def local_positions():
    """SWEET.TV always reads the stick's local positions; None only when mediastick_resume is unavailable."""
    try:
        from resources.lib import store
        return store.resume.load() if store.resume is not None else None
    except Exception:
        return None
