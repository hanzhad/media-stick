# RunScript(script.media-stick.home,launch,<app-id>) records and launches an app.
# RunScript(script.media-stick.home,accounts,signin|signout|switch|add,...) sign-in and YouTube profiles
# (resources/lib/accounts.py; the phone page calls it through Addons.ExecuteAddon).
# RunScript(script.media-stick.home,ytkeys) writes the YouTube add-on's personal Google keys that the phone page left
# in /run/media-stick/ytkeys.json (resources/lib/ytkeys.py); the keys are never an argument, so never in a log.
# RunScript(script.media-stick.home,sweettv,open|demo) the SWEET.TV app screen (resources/lib/sweettv_app.py);
# `demo` is the same screen on invented channels, for looking at the design without an account.
# RunScript(script.media-stick.home,youtube,open|demo[,signin|needkey|empty|error|loading]) the YouTube app screen
# (resources/lib/youtube_app.py); `demo` is invented videos, the last word shows one of its cards instead of the list.
# RunScript(script.media-stick.home,onboarding,show,<service>) the screen of a flow the phone is working through (the Google
# key wizard; resources/lib/onboarding_app.py), following /run/media-stick/onboarding/<service>.json; `onboarding,demo,signin`
# and `onboarding,demo,keys` are the sign-in and the key wizard screens on invented documents, for looking at them.
# RunScript(script.media-stick.home,lang) applies the device's language (/var/lib/media-stick/prefs/language, written by
# the phone page) to the YouTube and SWEET.TV add-ons and the Home property media-stick.lang (resources/lib/lang.py).
# Without arguments: go to the (skin) Home window, where the service shows the launcher.
import sys

import xbmc

from resources.lib import apps

args = sys.argv[1:]
if len(args) >= 2 and args[0] == "launch":
    apps.launch(args[1])
elif args and args[0] == "accounts":
    try:
        from resources.lib import accounts
        accounts.main(args[1:])
    except Exception as e:      # e.g. the sign-in library is not on this device
        xbmc.log(f"[script.media-stick.home] accounts {args[1:2]!r} failed: {e!r}", xbmc.LOGERROR)
elif args and args[0] == "ytkeys":
    try:
        from resources.lib import ytkeys
        ytkeys.main(args[1:])
    except Exception as e:      # named by its type only: what failed may have been holding a key
        xbmc.log(f"[script.media-stick.home] ytkeys failed: {type(e).__name__}", xbmc.LOGERROR)
elif args and args[0] == "lang":
    try:
        from resources.lib import lang
        lang.main(args[1:])
    except Exception as e:      # the add-ons keep the language they had
        xbmc.log(f"[script.media-stick.home] lang failed: {type(e).__name__}", xbmc.LOGERROR)
elif args and args[0] == "sweettv":
    try:
        from resources.lib import sweettv_app
        sweettv_app.main(args[1:])
    except Exception as e:      # the screen cannot open: SWEET.TV's own list still works (not for the demo)
        xbmc.log(f"[script.media-stick.home] sweettv {args[1:2]!r} failed: {e!r}", xbmc.LOGERROR)
        if args[1:2] != ["demo"]:
            xbmc.executebuiltin("RunAddon(plugin.video.sweettv)")
elif args and args[0] == "onboarding":
    try:
        from resources.lib import onboarding_app
        onboarding_app.main(args[1:])
    except Exception as e:      # the screen cannot open: the phone still shows the steps
        xbmc.log(f"[script.media-stick.home] onboarding {args[1:3]!r} failed: {e!r}", xbmc.LOGERROR)
elif args and args[0] == "youtube":
    try:
        from resources.lib import youtube_app
        youtube_app.main(args[1:])
    except Exception as e:      # the screen cannot open: YouTube's own list still works (not for the demo)
        xbmc.log(f"[script.media-stick.home] youtube {args[1:2]!r} failed: {e!r}", xbmc.LOGERROR)
        if args[1:2] != ["demo"]:
            xbmc.executebuiltin("RunAddon(plugin.video.youtube)")
else:
    xbmc.executebuiltin("ActivateWindow(Home)")
