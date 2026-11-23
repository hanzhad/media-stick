"""Accounts: the actions the TV and the phone page share, and what launching an app does about them.

  RunScript(script.media-stick.home,accounts,signin,<service>)
  RunScript(script.media-stick.home,accounts,switch,youtube,<profile id>)
  RunScript(script.media-stick.home,accounts,add,youtube,<name>)       adds the profile and switches to it
  RunScript(script.media-stick.home,accounts,signout,<service>)

The phone page calls the same through JSON-RPC Addons.ExecuteAddon, whose params become argv, so
main() trusts nothing: services come from the library's SERVICES, ids are digits, names are short.
"""
import re
import time
from typing import NamedTuple
from urllib.parse import quote

import xbmc
import xbmcgui

from resources.lib import apps, profiles, signin, store, ui

YOUTUBE = "youtube"
PROFILE_SERVICES = (YOUTUBE,)                    # the services that have several profiles
ID_RE = re.compile(r"[0-9]{1,6}")
NAME_RE = re.compile(r"[\w .'\-]{1,24}")
SIGNOUT = {"youtube": "plugin://plugin.video.youtube/sign/out/?confirmed=true",
           "sweettv": "plugin://plugin.video.sweettv/logout"}   # SWEET.TV asks yes/no on the TV itself
RESULT_WAIT = 8.0                                # s for the screen of a sign-in that just ended to close before a new one starts
SWITCH_WAIT = 6.0                                # s for the YouTube add-on to switch / add a profile
LAUNCH, SIGNIN, SIGNIN_OPTIONAL, PICK = "launch", "signin", "signin-optional", "pick"


class Action(NamedTuple):
    verb: str
    service: str
    arg: str


def clean_name(text):
    """A profile name: whitespace collapsed, letters/digits/space/. ' - only, 1 to 24 characters; "" if not."""
    text = " ".join(str(text or "").split())
    return text if NAME_RE.fullmatch(text) and any(c.isalnum() for c in text) else ""


def parse(args):
    """argv after "accounts" -> Action, or ValueError."""
    args = [str(a) for a in args]
    if not args:
        raise ValueError("no action")
    verb, rest = args[0], args[1:]
    if verb in ("signin", "signout"):
        if len(rest) != 1 or rest[0] not in store.SERVICES:
            raise ValueError(f"{verb} wants one known service")
        return Action(verb, rest[0], "")
    if verb in ("switch", "add"):
        if len(rest) < 2 or rest[0] not in PROFILE_SERVICES:
            raise ValueError(f"{verb} wants a service with profiles and an argument")
        if verb == "switch":
            if len(rest) != 2 or not ID_RE.fullmatch(rest[1]):
                raise ValueError("switch wants a numeric profile id")
            return Action(verb, rest[0], rest[1])
        name = clean_name(" ".join(rest[1:]))
        if not name:
            raise ValueError("add wants a name of 1 to 24 letters, digits, spaces, . ' -")
        return Action(verb, rest[0], name)
    raise ValueError(f"unknown action {verb[:20]!r}")


# ---- what a card launch does -------------------------------------------------------------------

def service_for_app(app_id):
    return next((s for s, info in store.SERVICES.items() if info["addon"] == app_id), None)


def plan(app_id, accts):
    """(service, what to do first) for launching `app_id`, given store.lib.accounts():
    LAUNCH straight away, SIGNIN (must be signed in), PICK a YouTube profile first."""
    service = service_for_app(app_id)
    entry = next((a for a in accts if a["service"] == service), None) if service else None
    if entry is None:
        return None, LAUNCH
    if service == YOUTUBE:
        return service, PICK if len(entry["profiles"]) > 1 else LAUNCH     # one profile, even signed out: anonymous works
    return service, LAUNCH if entry["signed_in"] else SIGNIN


def after_pick(profile):
    """A picked YouTube profile: launch, or offer the sign-in with a way to go on without."""
    return LAUNCH if profile["signed_in"] else SIGNIN_OPTIONAL


# ---- doing things ------------------------------------------------------------------------------

def wait_for(check, timeout=SWITCH_WAIT, step=0.2):
    end = time.monotonic() + timeout
    while not check():
        if time.monotonic() >= end:
            return False
        xbmc.sleep(int(step * 1000))
    return True


def addon_ready(service):
    info = store.SERVICES[service]
    if xbmc.getCondVisibility(f"System.AddonIsEnabled({info['addon']})"):
        return True
    ui.notify(f"{info['name']} is not installed.")
    return False


def signin_service(service, allow_skip=False):
    """Start the add-on's sign-in unless one is already running, and show the sign-in screen unless
    one is up. Returns the screen's result (done, failed, cancelled, gone, skipped, closed), or
    "missing" (add-on absent), "busy" (another service is being signed in) or "shown" (a screen is up)."""
    if not addon_ready(service):
        return "missing"
    now = time.time()
    up = signin.showing(now)
    if up:
        if up != service:
            ui.notify("Finish the other sign-in first.")
            return "busy"
        # A screen of this service that stays up while its sign-in ended (cancelled, failed) is only showing the result for
        # a moment: a new sign-in asked for now (the phone's "new code" after the old one ran out) waits for it to close
        # instead of being turned away as "shown", which started nothing at all.
        ended = store.lib.read(service)
        if not (ended and ended["state"] in ("cancelled", "failed")) or not wait_for(lambda: not signin.showing(), RESULT_WAIT):
            return "shown"
        store.lib.begin(service)       # what the add-on does when it starts: the old result must not end the new screen at once
        now = time.time()
    attach = signin.can_attach(store.lib.read(service), now)
    if not attach:
        xbmc.executebuiltin(f"RunPlugin({store.SERVICES[service]['signin']})")
    return signin.run(service, attach, allow_skip)


def sign_out(service):
    if not addon_ready(service):
        return False
    xbmc.executebuiltin(f"RunPlugin({SIGNOUT[service]})")
    return True


def switch_profile(uid):
    """Switch YouTube to profile `uid` and wait until the add-on has done it."""
    if not ID_RE.fullmatch(str(uid)) or not addon_ready(YOUTUBE):
        return False
    xbmc.executebuiltin(f"RunScript(plugin.video.youtube,users/switch?ms_user={uid})")
    return wait_for(lambda: any(p["id"] == str(uid) and p["current"] for p in store.lib.youtube_accounts()))


def add_profile(name):
    """Add a YouTube profile called `name`, switch to it and wait until the add-on has done it."""
    name = clean_name(name)
    if not name or not addon_ready(YOUTUBE):
        return False
    known = {p["id"] for p in store.lib.youtube_accounts()}
    xbmc.executebuiltin(f"RunScript(plugin.video.youtube,users/add?ms_name={quote(name, safe='')}&ms_switch=1)")
    return wait_for(lambda: any(p["current"] and p["id"] not in known for p in store.lib.youtube_accounts()))


def ask_name():
    raw = xbmcgui.Dialog().input("Name for the new profile")
    name = clean_name(raw)
    if raw.strip() and not name:
        ui.notify("Use letters and digits, up to 24 characters.")
    return name


def current_profile():
    return next((p for p in store.lib.youtube_accounts() if p["current"]), None)


def choose_profile():
    """The "Who's watching" picker: the profile chosen and switched to, or None when backed out."""
    while True:
        known = store.lib.youtube_accounts()
        choice = profiles.pick(known)
        if choice is None:
            return None
        if choice == profiles.ADD_ID:
            name = ask_name()
            if not name:
                continue                     # no name typed: back to the cards
            if add_profile(name):
                return current_profile()
            ui.notify("The profile could not be added.")
            continue
        profile = next((p for p in known if p["id"] == choice), None)
        if profile is None:
            continue
        if not profile["current"] and not switch_profile(profile["id"]):
            ui.notify("The profile could not be switched.")
            return None
        return profile


def before_launch(app_id):
    """Whatever the app's accounts need before it starts; True when it should be launched now."""
    if service_for_app(app_id) is None:
        return True                          # not a sign-in app: no file is read, launching stays fast
    service, decision = plan(app_id, store.lib.accounts())
    if decision == LAUNCH:
        return True
    if decision == SIGNIN:
        return signin_service(service) == "done"
    profile = choose_profile()
    if profile is None:
        return False
    if after_pick(profile) == LAUNCH:
        return True
    return signin_service(service, allow_skip=True) in ("done", "skipped")


def launch_app(app_id):
    """apps.launch with the accounts step in front; any trouble in that step is a plain launch."""
    try:
        go = before_launch(app_id)
    except Exception as e:
        ui.log(f"accounts step before launching {app_id!r} failed: {e!r}", xbmc.LOGERROR)
        go = True
    if go:
        apps.launch(app_id)


def perform(action):
    if action.verb == "signin":
        return signin_service(action.service)
    if action.verb == "signout":
        return sign_out(action.service)
    if action.verb == "switch":
        return switch_profile(action.arg)
    return add_profile(action.arg)


def main(args):
    """Entry for `RunScript(script.media-stick.home,accounts,...)`: never raises."""
    try:
        action = parse(args)
    except ValueError as e:
        ui.log(f"refused accounts {[str(a)[:30] for a in args][:5]!r}: {e}")
        return False
    try:
        return perform(action)
    except Exception as e:
        ui.log(f"accounts {action.verb} {action.service} failed: {e!r}", xbmc.LOGERROR)
        return False
