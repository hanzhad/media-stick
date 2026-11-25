# RunScript(script.media-stick.webapp,<name>) - hand the screen to web-app@<name> via mediastick-displayd.
import os
import subprocess
import sys

import xbmcgui

_LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from mediastick_display import DisplayClient  # noqa: E402

WEB_APPS = frozenset({"netflix", "disney", "prime", "max", "youtube"})

name = sys.argv[1] if len(sys.argv) > 1 else ""
if name in WEB_APPS:
    xbmcgui.Dialog().notification("media-stick", "Opening " + name + "…", time=4000)
    client = None
    try:
        client = DisplayClient()
        client.acquire("WEB_APP", owner="kodi", app=name)
    except (OSError, EOFError):
        subprocess.Popen(["sudo", "-n", "/bin/systemctl", "start", "--no-block", f"web-app@{name}.service"])
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()
