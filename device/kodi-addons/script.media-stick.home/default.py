# RunScript(script.media-stick.home,launch,<app-id>) records and launches an app.
# Without arguments: go to the (skin) Home window, where the service shows the launcher.
import sys

import xbmc

from resources.lib import apps

args = sys.argv[1:]
if len(args) >= 2 and args[0] == "launch":
    apps.launch(args[1])
else:
    xbmc.executebuiltin("ActivateWindow(Home)")
