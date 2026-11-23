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

SERVICES = lib.SERVICES
