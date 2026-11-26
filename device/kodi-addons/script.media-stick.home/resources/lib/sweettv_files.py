"""SWEET.TV app: where its data lives and how it is read: SweetStore (SQLite catalog & EPG), the
add-on's own state file (see sweettv_state), the plugin's `logged` setting and the network the stick is on.
Thin: each function is one look at a store or file; what to make of it is sweettv_data's business.
"""
import os
import sys
from typing import NamedTuple, Optional

import xbmcgui
import xbmcvfs

LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(LIB_DIR) and LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import mediastick_sweetapi as sweetapi  # noqa: E402
import mediastick_sweetstore as sweetstore  # noqa: E402
from resources.lib import apps, net, sweettv_data as data, ui  # noqa: E402

QR_FAILED = set()
_LAST_RAW = (None, None)


def state_path():
    return os.path.join(xbmcvfs.translatePath(apps.RECENT_DIR), "sweettv.json")


def _payload_stamp(payload: dict) -> tuple:
    return (
        int(payload.get("updated_at") or 0),
        len(payload.get("list") or ()),
        str(payload.get("status") or ""),
        str(payload.get("sync_error") or ""),
    )


def read_raw(now=None):
    """The normalized SweetStore channel payload as a dict, or None when it cannot be read."""
    global _LAST_RAW
    try:
        payload = sweetstore.default_store().get_channels_payload(now=now)
    except Exception as e:
        ui.log(f"channel store not readable for the sections: {e!r}")
        return _LAST_RAW[1]
    if isinstance(payload, dict) and payload:
        _LAST_RAW = (_payload_stamp(payload), payload)
        return payload
    return None


def channel_day(cid, day_key: str, now=None, tr=None) -> list:
    """Stored programmes for `(cid, day_key)` formatted with local `when` labels."""
    try:
        rows = sweetstore.default_store().channel_day(cid, day_key, now=now)
    except Exception as e:
        ui.log(f"channel day read failed: {e!r}")
        return []
    ref_now = int(now) if now is not None else None
    out = []
    for r in rows:
        item = dict(r)
        if not item.get("when") and item.get("start"):
            item["when"] = sweetapi.when_text(int(item["start"]), ref_now, tr)
        out.append(item)
    return out


def recall_programme(cid, epg, now=None) -> Optional[dict]:
    """Stored programme metadata for `(cid, epg)` from SweetStore, or None when absent/unreadable."""
    try:
        return sweetstore.default_store().recall_programme(epg, cid=cid, now=now)
    except Exception:
        return None


def recall_title_detail(title_key) -> Optional[dict]:
    """Stored VOD/show detail for `title_key` from SweetStore, or None when absent/unreadable."""
    try:
        return sweetstore.default_store().get_title_detail(str(title_key or ""))
    except Exception:
        return None


def enrich_epg_art(epg_ids, now=None) -> dict:
    """Batch-fetch EPG artwork and real titles into SweetStore via sweetapi.enrich_epg_records."""
    try:
        return sweetapi.enrich_epg_records(epg_ids, store=sweetstore.default_store(), now=now)
    except Exception as e:
        ui.log(f"epg art enrichment failed: {e!r}")
        return {}


def clear_store() -> None:
    """Wipe cached SWEET.TV catalog data on sign-out."""
    try:
        sweetstore.default_store().clear()
    except Exception as e:
        ui.log(f"channel store clear failed: {e!r}")


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
    stamp: Optional[tuple]       # (updated_at, count, status, sync_error) of the store payload
    mtime: Optional[float]
    has_file: bool
    unreadable: bool             # the store could not be read this time


def snapshot(now, catalog, stamp, mtime) -> Snapshot:
    """What there is to show now. `catalog`, `stamp` and `mtime` are what the last good look found: they are
    reused while the store is unchanged (parsing once per change), and kept when it cannot be read this time."""
    global _LAST_RAW
    signed = signed_in()
    if signed is False:
        return Snapshot(False, None, None, None, False, False)
    try:
        payload = sweetstore.default_store().get_channels_payload(now=now)
    except Exception as e:
        ui.log(f"channel store not readable: {e!r}")
        return Snapshot(True if signed is None else True, catalog, stamp, mtime, True, True)
    has_data = isinstance(payload, dict) and bool(payload)
    if signed is None:
        signed = isinstance(payload, dict) and bool(payload.get("list"))
    if not signed:
        return Snapshot(False, None, None, None, has_data, False)
    if not has_data:
        return Snapshot(True, None, None, None, False, False)
    new_stamp = _payload_stamp(payload)
    if new_stamp == stamp and catalog is not None:
        return Snapshot(True, catalog, new_stamp, mtime, True, False)
    fresh = data.parse_catalog(payload, now)
    _LAST_RAW = (new_stamp, payload)
    if fresh is None or (fresh.error and catalog is not None and catalog.channels):
        return Snapshot(True, catalog, stamp, mtime, True, True)
    updated_at = int(payload.get("updated_at") or 0)
    new_mtime = float(updated_at) if updated_at > 0 else float(now)
    return Snapshot(True, fresh, new_stamp, new_mtime, True, False)


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
