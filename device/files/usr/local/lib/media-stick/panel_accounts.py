"""The Accounts part of the panel: who is signed in, and signing in from the phone.

The state is read from mediastick_signin (file reads only: no sudo, no subprocess). Actions
that need Kodi go to the launcher add-on through the `rpc` callable the panel hands in (its
kodi() JSON-RPC helper); cancelling is a file, so it needs no Kodi. The page's markup, style
and script live in panel_accounts_ui.py; inject() puts them into the panel's page.

Standard library only, nothing happens on import.
"""
import re
import unicodedata
from urllib.parse import urlsplit

import mediastick_signin as signin
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

KODI_DOWN = "Kodi не отвечает. Подождите минуту и попробуйте снова."


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
    """The sign-in mode the page asks for: normal when it says nothing; partner only where there is one."""
    if value in (None, "", signin.NORMAL):
        return signin.NORMAL
    if value != signin.PARTNER:
        raise Refused("Неизвестный способ входа.")
    if service != "sweettv":
        raise Refused("Вход через партнёра есть только у SWEET.TV.")
    return signin.PARTNER


def public_signin(state):
    """A sign-in state as the page may see it: known fields only, the link checked. A partner's
    specialist types the code in by hand, so the page gets no link to open (the QR's address) there."""
    if not isinstance(state, dict):
        return None
    code = state.get("code") if CODE_RE.match(str(state.get("code", ""))) else ""
    partner = state.get("mode") == signin.PARTNER
    return {"service": state.get("service"), "name": state.get("name"), "state": state.get("state"),
            "mode": signin.PARTNER if partner else signin.NORMAL,
            "code": code, "url": "" if partner else safe_link(state.get("url", "")),
            "link": safe_link(state.get("link", "")) if code and not partner else "",
            "step": _int(state.get("step"), 1, 1, 9), "steps": _int(state.get("steps"), 1, 1, 9),
            "left": _int(state.get("left"), 0, 0, 86400), "updated": _int(state.get("updated"), 0, 0, 2 ** 40)}


def _public_account(a):
    profiles = [{"id": str(p["id"]), "name": str(p["name"]), "current": bool(p["current"]),
                 "tokens": _int(p.get("tokens"), 0, 0, 4), "signed_in": bool(p["signed_in"])}
                for p in a["profiles"]]
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
        raise Refused(KODI_DOWN, 503)


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


def _signout(body, rpc):
    _launch(rpc, ["accounts", "signout", clean_service(body.get("service"))])
    return {"ok": True}


def _ytkeys(body, rpc):
    """The YouTube keys wizard (panel_ytkeys): its reply as it is, its refusals with what it says besides the error."""
    reply, code = panel_ytkeys.handle(body, rpc)
    if code != 200:
        raise Refused(reply.get("error", ""), code, {k: v for k, v in reply.items() if k not in ("ok", "error")})
    return reply


ACTIONS = {"signin": _signin, "cancel": _cancel, "switch": _switch, "add": _add, "signout": _signout,
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
    """The panel's page with the Accounts tab, section and sheets (sign-in code, YouTube keys) put at its three markers."""
    return (page.replace("@@ACC_NAV@@", ui.NAV).replace("@@ACC_SECTION@@", ui.SECTION)
            .replace("@@ACC_TAIL@@", ui.tail(LINK_HOSTS) + panel_ytkeys_ui.tail(panel_ytkeys.WIZARD)))
