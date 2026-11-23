"""Onboarding: the phone does the action, the TV shows the hints. One small JSON file per service.

A flow that needs the phone (the device-code sign-in of YouTube and SWEET.TV, the Google key wizard) says
what it is doing in /run/media-stick/onboarding/<service>.json (RAM). The TV screen draws it big (the `tv`
texts), the phone page draws it as its sheet (the `phone` texts). Neither side asks the other anything:
both read this file, and whoever runs the flow writes it. The sign-in files in /run/media-stick/signin
(mediastick_signin) stay as they are; this one is the shared picture on top of them.

Schema v1 (all texts are single lines; the limits are cut by build, longer lists lose their tail):
  {"v": 1, "service": "youtube", "flow": "signin" | "keys" | <other>,
   "state": "active" | "done" | "failed" | "cancelled",
   "kicker": {"tv": "YouTube · sign in", "phone": "..."},             optional, <= 60: the small line above the title
   "title": {"tv": "Continue on your phone", "phone": "..."},         <= 80
   "step": 2, "steps": [{"id": "open", "tv": "...", "phone": "..."}], 1-based current step; <= 8 steps, text <= 120
   "code": "KQX-7MD-P4W", "link": "https://...",                      sign-in: the code and the link with it typed in
   "action": {"kind": "link" | "paste" | "wait", "label": "...", "url": "https://..."},
   "hint": {"tv": "...", "phone": "..."},                             <= 160
   "chips": [[{"t": "Get started", "s": "done" | "now" | "todo"}]],   TV only: rows of chips, <= 12 chips in <= 4 rows
   "items": [{"id": "api_key", "label": "API key", "s": "ok" | "wait"}],   TV only: status badges, <= 6, never a value
   "warn": {"tv": "...", "phone": "..."},                             <= 160
   "updated": <unix>, "expires": <unix>}                              expires is mandatory: after it the file is nothing

Never a secret: build() refuses a document with anything that looks like a Google API key (AIza...), client
secret (GOCSPX-...), client id (....apps.googleusercontent.com), an OAuth token, or a long token-like word.
read() tolerates unknown fields and gives None for a file that is missing, not JSON, of another version, expired
or leaking. State is written whole and renamed into place; standard library only, like mediastick_signin.
"""
import json
import math
import os
import re
import tempfile
import time

DIR = os.environ.get("MEDIASTICK_ONBOARDING_DIR", "/run/media-stick/onboarding")
VERSION = 1

ACTIVE, DONE, FAILED, CANCELLED = "active", "done", "failed", "cancelled"
STATES = (ACTIVE, DONE, FAILED, CANCELLED)
KINDS = ("link", "paste", "wait")
CHIP_STATES = ("done", "now", "todo")
ITEM_STATES = ("ok", "wait")

SERVICE_RE = re.compile(r"[a-z0-9_-]{1,32}")
ID_RE = re.compile(r"[a-z0-9_-]{1,32}")
URL_RE = re.compile(r"https?://[^\s\x00-\x1f]+")
CODE_BAD = re.compile(r"[^A-Za-z0-9 _-]")

TTL = 10 * 60               # how long an active document lives when the writer does not say
RESULT_TTL = 30             # a finished one stays readable this long, so a screen that polls still sees how it ended
MAX_TTL = 24 * 60 * 60

LIMITS = {"title": 80, "kicker": 60, "hint": 160, "warn": 160, "step": 120, "label": 60, "chip": 48, "item": 32,
          "code": 40, "url": 300}
MAX_STEPS, MAX_CHIPS, MAX_ROWS, MAX_ITEMS = 8, 12, 4, 6

# What must never be written: Google API keys, client secrets, client ids, OAuth tokens (access, refresh),
# and any long run of token characters (checked on texts, not on the code or a URL).
SECRET_RE = re.compile(r"AIza[0-9A-Za-z_-]{12,}|GOCSPX-[0-9A-Za-z_-]{6,}|[0-9A-Za-z_-]*\.apps\.googleusercontent\.com"
                       r"|ya29\.[0-9A-Za-z_-]{8,}|1//[0-9A-Za-z_-]{16,}", re.I)
TOKENISH_RE = re.compile(r"[A-Za-z0-9_-]{28,}")


class Refused(ValueError):
    """A document that must not be written. The message names the field, never the value."""


def looks_secret(text, texty=True) -> bool:
    """True for a string that looks like a key, a secret or a token. `texty`: it is a sentence or a label, so a long
    run of token characters counts too (not for a code or a URL)."""
    if not isinstance(text, str):
        return False
    if SECRET_RE.search(text):
        return True
    if texty:
        for word in TOKENISH_RE.findall(text):
            if any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
                return True
    return False


def _path(service):
    return os.path.join(DIR, f"{service}.json")


def _text(value, limit, field) -> str:
    """One line, no control characters, cut to `limit` with an ellipsis. Refused when the whole of it (before the
    cut: a key cut in half no longer looks like one) looks like a secret."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())
    _guard(text, field)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _guard(text, field, texty=True) -> str:
    if looks_secret(text, texty):
        raise Refused(f"{field} looks like a secret")
    return text


def _pair(value, limit, field) -> dict:
    """{"tv", "phone"} from a dict (or one string for both); keys that are not texts are empty."""
    if isinstance(value, str):
        value = {"tv": value, "phone": value}
    if not isinstance(value, dict):
        return {"tv": "", "phone": ""}
    return {side: _text(value.get(side), limit, f"{field}.{side}") for side in ("tv", "phone")}


def _url(value, field) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if len(text) > LIMITS["url"] or not URL_RE.fullmatch(text):
        return ""
    return _guard(text, field, texty=False)


def _steps(value):
    out = []
    for n, raw in enumerate(value[:MAX_STEPS] if isinstance(value, list) else [], 1):
        raw = raw if isinstance(raw, dict) else {}
        ident = raw.get("id")
        pair = _pair(raw, LIMITS["step"], f"steps[{n - 1}]")
        out.append({"id": ident if isinstance(ident, str) and ID_RE.fullmatch(ident) else f"s{n}", **pair})
    return out


def _chips(value):
    rows = []
    for r, raw_row in enumerate(value[:MAX_ROWS] if isinstance(value, list) else []):
        room = MAX_CHIPS - sum(len(row) for row in rows)
        row = []
        for raw in (raw_row if isinstance(raw_row, list) else [])[:max(room, 0)]:
            raw = raw if isinstance(raw, dict) else {}
            text = _text(raw.get("t"), LIMITS["chip"], f"chips[{r}]")
            if text:
                row.append({"t": text, "s": raw.get("s") if raw.get("s") in CHIP_STATES else "todo"})
        if row:
            rows.append(row)
    return rows


def _items(value):
    out = []
    for n, raw in enumerate(value[:MAX_ITEMS] if isinstance(value, list) else []):
        raw = raw if isinstance(raw, dict) else {}
        label = _text(raw.get("label"), LIMITS["item"], f"items[{n}]")
        ident = raw.get("id")
        if label:
            out.append({"id": ident if isinstance(ident, str) and ID_RE.fullmatch(ident) else f"i{n + 1}",
                        "label": label, "s": raw.get("s") if raw.get("s") in ITEM_STATES else "wait"})
    return out


def build(service, doc, now=None, ttl=None) -> dict:
    """The file's content for `service` from what a flow says (`doc`: flow, state and the fields above; others are
    dropped), with the limits applied. Raises Refused for a service name that is not a name, a flow or state that
    is not one, or anything that looks like a secret. `ttl`: seconds the document lives (a finished one: 30 s)."""
    if not isinstance(service, str) or not SERVICE_RE.fullmatch(service):
        raise Refused("service is not a name")
    if not isinstance(doc, dict):
        raise Refused("document is not an object")
    flow, state = doc.get("flow"), doc.get("state", ACTIVE)
    if not isinstance(flow, str) or not SERVICE_RE.fullmatch(flow):
        raise Refused("flow is not a name")
    if state not in STATES:
        raise Refused("state is not one of the four")
    now = int(time.time() if now is None else now)
    if ttl is None:
        ttl = TTL if state == ACTIVE else RESULT_TTL
    ttl = max(1, min(int(ttl), MAX_TTL))
    steps = _steps(doc.get("steps"))
    step = doc.get("step")
    step = step if isinstance(step, int) and not isinstance(step, bool) else 1
    out = {"v": VERSION, "service": service, "flow": flow, "state": state,
           "title": _pair(doc.get("title"), LIMITS["title"], "title"),
           "step": max(1, min(step, len(steps))) if steps else 0, "steps": steps}
    if doc.get("kicker"):
        out["kicker"] = _pair(doc["kicker"], LIMITS["kicker"], "kicker")
    code = CODE_BAD.sub("", doc.get("code") if isinstance(doc.get("code"), str) else "")[:LIMITS["code"]].strip()
    if code:
        out["code"] = _guard(code, "code", texty=False)
    link = _url(doc.get("link"), "link")
    if link:
        out["link"] = link
    action = doc.get("action")
    if isinstance(action, dict) and action.get("kind") in KINDS:
        out["action"] = {"kind": action["kind"], "label": _text(action.get("label"), LIMITS["label"], "action.label")}
        url = _url(action.get("url"), "action.url")
        if url:
            out["action"]["url"] = url
    for field in ("hint", "warn"):
        pair = _pair(doc.get(field), LIMITS[field], field)
        if pair["tv"] or pair["phone"]:
            out[field] = pair
    chips = _chips(doc.get("chips"))
    if chips:
        out["chips"] = chips
    items = _items(doc.get("items"))
    if items:
        out["items"] = items
    out["updated"], out["expires"] = now, now + ttl
    return out


def _store(service, data) -> bool:
    """Write whole, rename into place, mode 0644; False when it cannot be written (a flow must not break on this)."""
    tmp = None
    try:
        os.makedirs(DIR, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, _path(service))
        return True
    except (OSError, ValueError, TypeError):
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def write(service, doc, now=None, ttl=None) -> bool:
    """Publish `doc` as the picture of `service` (see build). False when it was refused or cannot be written."""
    try:
        data = build(service, doc, now, ttl)
    except Refused:
        return False
    return _store(service, data)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pairs_leak(value) -> bool:
    return isinstance(value, dict) and any(looks_secret(value.get(side)) for side in ("tv", "phone"))


def _leaks(data) -> bool:
    """A file somebody else wrote: does any text the screens show look like a secret?"""
    if any(_pairs_leak(data.get(field)) for field in ("kicker", "title", "hint", "warn")):
        return True
    if any(_pairs_leak(step) for step in _listed(data.get("steps"))):
        return True
    for row in _listed(data.get("chips")):
        if any(isinstance(c, dict) and looks_secret(c.get("t")) for c in _listed(row)):
            return True
    if any(isinstance(i, dict) and looks_secret(i.get("label")) for i in _listed(data.get("items"))):
        return True
    return any(looks_secret(data.get(k), texty=False) for k in ("code", "link"))


def _listed(value) -> list:
    return value if isinstance(value, list) else []


def read(service, now=None):
    """The document of `service`, or None: no such file, not JSON, not an object, another version, another service,
    no state, no `expires` or one that has passed, or a text that looks like a secret. Unknown fields stay."""
    if not isinstance(service, str) or not SERVICE_RE.fullmatch(service):
        return None
    try:
        with open(_path(service), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, MemoryError):
        return None
    if not isinstance(data, dict) or data.get("v") != VERSION or isinstance(data.get("v"), bool):
        return None
    if data.get("service") != service or data.get("state") not in STATES:
        return None
    now = time.time() if now is None else now
    if not _number(data.get("expires")) or now >= data["expires"] or _leaks(data):
        return None
    return data


def list_active(now=None) -> list:
    """The documents that are active right now, by service name."""
    try:
        names = sorted(n[:-5] for n in os.listdir(DIR) if n.endswith(".json"))
    except OSError:
        return []
    found = (read(name, now) for name in names if SERVICE_RE.fullmatch(name))
    return [d for d in found if d and d["state"] == ACTIVE]


def clear(service) -> bool:
    """Take the document away (the flow is over or was never there). True when there was one."""
    if not isinstance(service, str) or not SERVICE_RE.fullmatch(service):
        return False
    try:
        os.unlink(_path(service))
        return True
    except OSError:
        return False


def advance(service, step, now=None) -> bool:
    """The flow moved to `step` (1-based): rewrite the active document with it, same lifetime left. For the phone
    page, which learns that the person opened the link before the TV can know it."""
    now = int(time.time() if now is None else now)
    data = read(service, now)
    if data is None or data["state"] != ACTIVE:
        return False
    data["step"] = step
    return write(service, data, now, ttl=max(1, int(data["expires"] - now)))


def extend(service, ttl, until=None, now=None) -> bool:
    """Heartbeat of a flow that has a writer: `updated` is now and `expires` is `ttl` ahead, but never past `until`.
    A document that is not active, or already expired, is left alone (a heartbeat does not bring it back)."""
    now = int(time.time() if now is None else now)
    data = read(service, now)
    if data is None or data["state"] != ACTIVE:
        return False
    data["updated"] = now
    data["expires"] = min(now + int(ttl), until if _number(until) else now + int(ttl))
    return _store(service, data)
