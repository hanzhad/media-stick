"""The Accounts part of the panel: who is signed in, and signing in from the phone.

The state is read from mediastick_signin (file reads only: no sudo, no subprocess). Actions
that need Kodi go to the launcher add-on through the `rpc` callable the panel hands in (its
kodi() JSON-RPC helper); cancelling is a file, so it needs no Kodi. The page's markup, style
and script live in panel_accounts_ui.py; inject() puts them into the panel's page.

Standard library only, nothing happens on import.
"""
import re
import time
import unicodedata
from urllib.parse import urlsplit

import mediastick_signin as signin
import mediastick_screen as screen   # a cast or a web app has the TV: say so, not "Kodi не отвечает"
try:
    import mediastick_ytchannel as ytchannel   # does the signed-in Google account have a YouTube channel
except ImportError:
    ytchannel = None
import panel_accounts_ui as ui
import panel_ytkeys
import panel_ytkeys_ui

LAUNCHER = "script.media-stick.home"
PREFIX = "/api/accounts/"
NAME_MAX = 32
# the only places a link may lead to (sign-in pages, and the pages of the YouTube keys wizard); the page checks its own copy of this list.
# www.google.com: Google sends a TV client made with the owner's own keys to www.google.com/device to type the code.
LINK_HOSTS = ("www.youtube.com", "youtube.com", "accounts.google.com", "www.google.com", "sweet.tv", "www.sweet.tv",
              "console.cloud.google.com", "developers.google.com")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
ID_RE = re.compile(r"^[0-9]{1,6}$")
BAD_CHARS = ("Cc", "Cs", "Co", "Cn", "Zl", "Zp")

KODI_DOWN = "ТВ не отвечает. Подождите минуту и попробуйте снова."


class Refused(Exception):
    def __init__(self, message, code=400, extra=None):
        super().__init__(message)
        self.message, self.code, self.extra = message, code, extra or {}


# ---- validation: pure ------------------------------------------------------------------------

def safe_link(url):
    """The link if it is https to one of the sign-in pages, else ''."""
    if not isinstance(url, str) or len(url) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in url):
        return ""
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return ""
    ok = u.scheme == "https" and u.hostname in LINK_HOSTS and port in (None, 443) and not u.username and not u.password
    return url if ok else ""


def clean_service(value):
    if not isinstance(value, str) or value not in signin.SERVICES:
        raise Refused("Неизвестный сервис.")
    return value


def clean_profile_id(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not ID_RE.match(value):
        raise Refused("Неверный номер профиля.")
    return value


def clean_name(value):
    if not isinstance(value, str):
        raise Refused("Нужно имя профиля.")
    name = value.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise Refused("Имя профиля — от 1 до %d символов." % NAME_MAX)
    if any(unicodedata.category(c) in BAD_CHARS for c in name):
        raise Refused("В имени профиля не должно быть управляющих символов.")
    return name


def _int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def clean_mode(value, service):
    """The sign-in mode the page asks for: normal, which is also what it says when it says nothing. There is no other:
    SWEET.TV has one sign-in (it waits six hours by itself), so the old partner button's mode is refused."""
    if value in (None, "", signin.NORMAL):
        return signin.NORMAL
    raise Refused("Неизвестный способ входа.")


def public_signin(state):
    """A sign-in state as the page may see it: known fields only, the link checked. The code
    is typed into the Friendly Share page by hand, so the page gets no link to open (the QR's address) there."""
    if not isinstance(state, dict):
        return None
    code = state.get("code") if CODE_RE.match(str(state.get("code", ""))) else ""
    partner = state.get("mode") == signin.PARTNER
    return {"service": state.get("service"), "name": state.get("name"), "state": state.get("state"),
            "mode": signin.PARTNER if partner else signin.NORMAL,
            "code": code, "url": "" if partner else safe_link(state.get("url", "")),
            "link": safe_link(state.get("link", "")) if code and not partner else "",
            "step": _int(state.get("step"), 1, 1, 9), "steps": _int(state.get("steps"), 1, 1, 9),
            "left": _int(state.get("left"), 0, 0, 86400), "updated": _int(state.get("updated"), 0, 0, 2 ** 40),
            "reason": state.get("reason") if state.get("reason") in signin.REASONS else ""}


def _channel(service, p):
    """("yes" | "no" | "unknown", the channel's title): without a channel Google gives the add-on no
    subscriptions, Watch Later or playlists, so the page says so. Never waits (see mediastick_ytchannel)."""
    if service != "youtube" or not p.get("signed_in") or ytchannel is None:
        return "unknown", ""
    try:
        got = ytchannel.peek(str(p["id"]))
    except Exception:   # a check that breaks must not take the Accounts tab with it
        return "unknown", ""
    state = got.get("state") if isinstance(got, dict) and got.get("state") in ("yes", "no") else "unknown"
    title = " ".join(str(got.get("title", "")).split()) if state == "yes" else ""
    return state, "".join(ch for ch in title if ch.isprintable())[:64]


def _public_account(a):
    profiles = []
    for p in a["profiles"]:
        channel, title = _channel(a["service"], p)
        profiles.append({"id": str(p["id"]), "name": str(p["name"]), "current": bool(p["current"]),
                         "tokens": _int(p.get("tokens"), 0, 0, 4), "signed_in": bool(p["signed_in"]),
                         "channel": channel, "channel_title": title})
    return {"service": a["service"], "name": a["name"], "profiles": profiles,
            "signed_in": bool(a["signed_in"]), "signin": public_signin(a["signin"])}


# ---- what the page reads ---------------------------------------------------------------------

def view():
    """GET /api/accounts"""
    return {"accounts": [_public_account(a) for a in signin.accounts()],
            "waiting": [public_signin(s) for s in signin.active()]}


def with_signin(status):
    """The panel's status plus the names of the services waiting for a code, so the sheet can
    open on any tab; a copy, because the status is cached and shared."""
    return dict(status, signin=[s["service"] for s in signin.active()])


# ---- what the page does ----------------------------------------------------------------------

def _launch(rpc, params):
    """Ask the launcher add-on to do it. A Kodi that is down is a calm 503, not a crash."""
    try:
        rpc("Addons.ExecuteAddon", {"addonid": LAUNCHER, "params": params})
    except (OSError, ValueError):
        raise Refused(screen.kodi_down(), 503)


def _signin(body, rpc):
    service = clean_service(body.get("service"))
    mode = clean_mode(body.get("mode"), service)
    if any(s["service"] == service for s in signin.active()):
        return {"ok": True, "already": True}
    # The add-on takes the mode from this file when it starts (the launcher's argv has no room for it); a
    # plain sign-in withdraws an earlier request nobody took.
    if not signin.request_mode(service, mode):
        raise Refused("Не получилось передать способ входа.", 500)
    try:
        _launch(rpc, ["accounts", "signin", service])
    except Refused:
        signin.clear_mode(service)
        raise
    return {"ok": True}


def _cancel(body, rpc):
    if not signin.request_cancel(clean_service(body.get("service"))):
        raise Refused("Не получилось передать отмену.", 500)
    return {"ok": True}


RENEW_WAIT = 8.0   # s the add-on gets to stop the old sign-in before the new one starts


def _renew(body, rpc):
    """«Обновить код» (SWEET.TV): the sign-in that is waiting is stopped and a new one starts, which asks SWEET.TV
    for a new code. Nothing replaces a code by itself: the person may have typed it into another page, so only this
    does, when they ask. With no sign-in waiting (it ran out, or failed) it simply starts one."""
    service = clean_service(body.get("service"))
    if service != "sweettv":
        raise Refused("Обновить код можно только у SWEET.TV.")
    if any(s["service"] == service for s in signin.active()):
        if not signin.request_cancel(service):
            raise Refused("Не получилось передать отмену.", 500)
        deadline = time.monotonic() + RENEW_WAIT
        while any(s["service"] == service for s in signin.active()):
            if time.monotonic() >= deadline:
                raise Refused("Телевизор не остановил прошлый вход. Посмотрите на ТВ.", 504)
            time.sleep(0.25)
    return _signin({"service": service}, rpc)


def _youtube(body):
    if clean_service(body.get("service")) != "youtube":
        raise Refused("У этого сервиса нет профилей.")
    return "youtube"


def _switch(body, rpc):
    service, pid = _youtube(body), clean_profile_id(body.get("id"))
    if pid not in [p["id"] for p in signin.youtube_accounts()]:
        raise Refused("Такого профиля нет.", 404)
    _launch(rpc, ["accounts", "switch", service, pid])
    return {"ok": True}


def _add(body, rpc):
    service, name = _youtube(body), clean_name(body.get("name"))
    _launch(rpc, ["accounts", "add", service, name])
    return {"ok": True}


ANOTHER_WAIT = 8.0   # s for the TV to add / switch the profile before its sign-in starts


def _another(body, rpc):
    """«Войти другим аккаунтом», one tap: a profile with nobody in it becomes current (the current one if
    it is empty, else one left over from a sign-in that was given up, else a new "Аккаунт N"), then its
    sign-in starts. No name to type anywhere. `previous` is the profile to go back to if the sign-in is
    cancelled, so giving up does not leave the TV on an empty profile."""
    service = _youtube(body)
    if any(s["service"] == service for s in signin.active()):
        return {"ok": True, "already": True}
    profiles = signin.youtube_accounts()
    cur = next((p for p in profiles if p["current"]), None)
    spare = next((p for p in profiles if not p["signed_in"] and not p["current"]), None)
    known = {p["id"] for p in profiles}
    previous = cur["id"] if cur and cur["signed_in"] else None
    if cur and not cur["signed_in"]:
        target = cur["id"]
    elif spare:
        target = spare["id"]
        _launch(rpc, ["accounts", "switch", service, target])
    else:
        names = {p["name"] for p in profiles}
        n = len(profiles) + 1
        while "Аккаунт %d" % n in names:
            n += 1
        target = None
        _launch(rpc, ["accounts", "add", service, "Аккаунт %d" % n])
    deadline = time.monotonic() + ANOTHER_WAIT
    while True:
        now = next((p for p in signin.youtube_accounts() if p["current"]), None)
        if now and (now["id"] == target if target else now["id"] not in known):
            break
        if time.monotonic() >= deadline:
            raise Refused("Телевизор не переключил профиль. Посмотрите на ТВ.", 504)
        time.sleep(0.25)
    if previous is not None:
        signin.note_return(service, previous, now["id"])   # the device itself switches back if this sign-in is given up
    return dict(_signin({"service": service}, rpc), previous=previous)


def settle(rpc):
    """Every few seconds (the panel's own thread): put the TV back on the profile it had before a sign-in with
    another account that was given up. A TV that does not answer is tried again next time."""
    try:
        return signin.settle_return("youtube", lambda pid: _launch(rpc, ["accounts", "switch", "youtube", pid]))
    except Refused:
        return None


def _signout(body, rpc):
    _launch(rpc, ["accounts", "signout", clean_service(body.get("service"))])
    return {"ok": True}


def _ytkeys(body, rpc):
    """The YouTube keys wizard (panel_ytkeys): its reply as it is, its refusals with what it says besides the error."""
    reply, code = panel_ytkeys.handle(body, rpc)
    if code != 200:
        raise Refused(reply.get("error", ""), code, {k: v for k, v in reply.items() if k not in ("ok", "error")})
    return reply


ACTIONS = {"signin": _signin, "cancel": _cancel, "renew": _renew, "switch": _switch, "add": _add, "another": _another, "signout": _signout,
           "ytkeys": _ytkeys}


def post(path, body, rpc):
    """POST /api/accounts/<action>: (JSON-able reply, HTTP code). The panel has already checked
    the X-Panel header and the Host."""
    try:
        action = ACTIONS.get(path[len(PREFIX):]) if path.startswith(PREFIX) else None
        if action is None:
            raise Refused("Неизвестное действие.", 404)
        if not isinstance(body, dict):
            raise Refused("Нужен JSON-объект.")
        return action(body, rpc), 200
    except Refused as e:
        return dict(e.extra, ok=False, error=e.message), e.code


# ---- the page --------------------------------------------------------------------------------

def inject(page):
    """The panel's page with the Accounts card (in the settings) and the sheets (sign-in code, YouTube keys) put at its two markers."""
    return (page.replace("@@ACC_SECTION@@", ui.SECTION)
            .replace("@@ACC_TAIL@@", ui.tail(LINK_HOSTS) + panel_ytkeys_ui.tail(panel_ytkeys.WIZARD)))
