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

try:        # where the person stopped; a device without it keeps what the places read before
    import mediastick_resume as resume  # noqa: E402
except ImportError:
    resume = None

try:        # what the address of a SWEET.TV stream is (the add-on wrote it down); without it only the plugin path tells
    import mediastick_sweetlive as sweetlive  # noqa: E402
except ImportError:
    sweetlive = None

try:        # SWEET.TV's own search and the guide of any day (api.sweet.tv); a device without it has no search
    import mediastick_sweetapi as sweetapi  # noqa: E402
except ImportError:
    sweetapi = None

SERVICES = lib.SERVICES


def local_resume():
    """YouTube uses its own profile/account history; local resume override is disabled for YouTube."""
    return None


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


def channel_title(profile) -> str:
    """The YouTube channel's title of a signed-in profile, the phone page's rules (panel_accounts._channel): only when the
    profile is signed in and the answer is "yes", whitespace collapsed, printable characters, at most 64. Never waits;
    "" when there is none, the library is missing or the look fails."""
    if ytchannel is None or not profile.get("signed_in"):
        return ""
    try:
        got = ytchannel.peek(str(profile["id"]))
    except Exception:
        return ""
    if not isinstance(got, dict) or got.get("state") != "yes":
        return ""
    title = " ".join(str(got.get("title", "")).split())
    return "".join(ch for ch in title if ch.isprintable())[:64]

