"""The device's shared sign-in library (device/files/usr/local/lib/media-stick), imported as `lib`.

It holds the services, the code an add-on is waiting for, the cancel request and who is signed
in. Kept in one place so a missing library is one ImportError that callers can fall back from.
"""
import sys

LIB_DIR = "/usr/local/lib/media-stick"
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import mediastick_signin as lib  # noqa: E402

try:        # what a flow tells the phone and the TV; a device without it keeps the older screens
    import mediastick_onboarding as onboarding  # noqa: E402
except ImportError:
    onboarding = None

try:        # whether a YouTube profile's Google account has a channel; a device without it claims nothing
    import mediastick_ytchannel as ytchannel  # noqa: E402
except ImportError:
    ytchannel = None

SERVICES = lib.SERVICES


def channel_state(profile_id) -> str:
    """"yes", "no" or "unknown" for the YouTube profile `profile_id`: the remembered answer, at once (the library looks
    again in the background when it is old). "unknown" when the library is missing or fails: nothing is then claimed."""
    if ytchannel is None:
        return "unknown"
    try:
        state = ytchannel.peek(profile_id).get("state")
    except Exception:
        return "unknown"
    return state if state in ("yes", "no") else "unknown"

