# RunScript(script.media-stick.webapp,<name>) - hand the screen to web-app@<name>.
# The service stops Kodi (Conflicts=) and starts it again when the browser closes.
import re
import subprocess
import sys

import xbmcgui

name = sys.argv[1] if len(sys.argv) > 1 else ""
if re.fullmatch(r"[a-z0-9-]+", name):
    xbmcgui.Dialog().notification("media-stick", "Opening " + name + "…", time=4000)
    subprocess.Popen(["sudo", "-n", "/bin/systemctl", "start", "--no-block", f"web-app@{name}.service"])
