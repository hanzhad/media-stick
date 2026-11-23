"""Onboarding: where the TV gets a flow's document and the phone page's address. Thin: each function is one look at a
file or at the network; what to make of it is onboarding_view's business."""
from resources.lib import net, remote, store, sweettv_text, sweettv_files, ui


def read(service, now=None):
    """The document of `service` as the library reads it (mediastick_onboarding.read), None when there is none, it has
    expired, or this device has no such library. A look costs one small file read."""
    lib = store.onboarding
    if lib is None:
        return None
    try:
        return lib.read(service, now)
    except Exception as e:
        ui.log(f"onboarding document not readable: {e!r}")
        return None


def phone_address():
    """The phone page's address as people type it ("192.168.1.14"), "" when the stick has no network."""
    try:
        ip = net.address()
        return sweettv_text.short_url(remote.page_url(ip)) if ip else ""
    except Exception as e:
        ui.log(f"phone page address unknown: {e!r}")
        return ""


def phone_qr():
    """The QR picture of the phone page, "" when there is no network or no QR can be made (cached by address)."""
    try:
        return sweettv_files.phone_page()[1]
    except Exception as e:
        ui.log(f"phone page QR unknown: {e!r}")
        return ""
