"""Sign-in and accounts: what a Kodi add-on is waiting for, and who is signed in.

An add-on that signs in with a code (YouTube, SWEET.TV) publishes it here, through the
overlay in device/skin-overlay/. The TV screen and the phone page read it and show the code
as a link that opens on the phone with the code already typed in, instead of an address to
type. Either of them can ask the add-on to stop (request_cancel).

A sign-in has a mode. `normal` is a person at the TV with a phone, and it is the only one the phone page asks for.
How long the code is waited for belongs to the service (SERVICES[...]["ttl"], else the mode): ten minutes, but SWEET.TV six
hours, because the owner's subscription is connected by a reseller's specialist (Friendly Share) who may come hours later and
the code must not run out on our side. The SWEET.TV add-on also polls gently and retries when the network drops
(PartnerPoll), and says how it ended: `reason` of a failed state is EXPIRED when the code ran out, SWEET.TV refused it or
the checks got no answer for too long, so the phone can say "refresh the code". `partner` is the older mode of the same
patience with its own screens (no QR; the phone no longer asks for it, request_mode still understands it). The mode travels in the
published state. waiting_any() tells the update script that somebody is still entering a code.

State is plain JSON in a tmpfs directory, written whole and renamed into place, standard
library only: it imports the same in Kodi's Python, in the panel and in a test.

Next to it each normal sign-in also writes the shared onboarding picture (mediastick_onboarding,
/run/media-stick/onboarding/<service>.json; its words are in mediastick_signin_guide): the three steps the
person does on the phone, which the TV and the phone sheet both draw. This file stays what the add-ons,
the accounts list and the update script read; the onboarding one is a view of it and never breaks it.
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

try:        # the shared picture of a flow for the TV and the phone; a device without it signs in as it always did
    import mediastick_onboarding as onboarding
    import mediastick_signin_guide as guide
except ImportError:
    onboarding = guide = None
try:        # whether a Google account has a YouTube channel (the "done" document says so when it has none)
    import mediastick_ytchannel as ytchannel
except ImportError:
    ytchannel = None

DIR = os.environ.get("MEDIASTICK_SIGNIN_DIR", "/run/media-stick/signin")
USERDATA = os.environ.get("MEDIASTICK_ADDON_DATA", "/home/media/.kodi/userdata/addon_data")

WAITING, DONE, FAILED, CANCELLED = "waiting", "done", "failed", "cancelled"
STATES = (WAITING, DONE, FAILED, CANCELLED)
HEARTBEAT = 60      # a waiting state not touched for this long is dead (Kodi restarted mid sign-in)
RESULT_KEEP = 30    # a finished state stays readable this long, so a page that polls still sees it

NORMAL, PARTNER = "normal", "partner"
MODES = (NORMAL, PARTNER)
TTL = {NORMAL: 10 * 60, PARTNER: 6 * 60 * 60}    # how long the code is waited for, by mode (a service's own "ttl" wins)
EXPIRED = "expired"                              # the `reason` of a failed state: the code ran out and a new one is needed
REASONS = (EXPIRED,)
MODE_KEEP = 120     # a mode the phone asked for is forgotten after this many seconds if no sign-in took it
CHANNEL_WAIT = 6    # s the end of a YouTube sign-in waits for the answer to "has the account a channel?" (it asks Google)
ONBOARD_ALIVE = HEARTBEAT + 30    # the onboarding picture of a waiting sign-in dies this long after the last heartbeat

SERVICES = {
    "youtube": {
        "name": "YouTube",
        "addon": "plugin.video.youtube",
        "signin": "plugin://plugin.video.youtube/sign/in/",
        "link": "https://www.youtube.com/activate?user_code={code}",
        "prefill": "youtube.com/activate",
    },
    "sweettv": {
        "name": "SWEET.TV",
        "addon": "plugin.video.sweettv",
        "signin": "plugin://plugin.video.sweettv/login",
        "link": "https://sweet.tv/addDevice?connectCode={code}",
        "prefill": "sweet.tv/addDevice",
        "ttl": 6 * 60 * 60,
    },
}


def _path(service, ext="json"):
    return os.path.join(DIR, f"{service}.{ext}")


def _load(service):
    try:
        with open(_path(service), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("state") in STATES else None


def _store(service, data):
    """Write the state whole and rename it into place; never raises: the add-on must not break."""
    tmp = None
    try:
        os.makedirs(DIR, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
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


def begin(service):
    """A sign-in starts: forget an earlier stop request and an earlier result."""
    clear_cancel(service)
    clear_renew(service)
    try:
        os.unlink(_path(service))
    except OSError:
        pass
    if onboarding is not None:
        onboarding.clear(service)


def clean_mode(mode):
    return PARTNER if mode == PARTNER else NORMAL


def ttl_for(mode, service=None):
    """Seconds a code is waited for: the service's own wait if it has one, else what the mode allows."""
    return SERVICES.get(service, {}).get("ttl") or TTL[clean_mode(mode)]


def _web(url) -> str:
    return url.strip() if isinstance(url, str) and re.fullmatch(r"https://[^\s\x00-\x1f]{1,290}", url.strip()) else ""


def _place(url) -> str:
    """sweet.tv/addDevice from https://www.sweet.tv/addDevice?x=1: where a page is, without scheme, www, query."""
    text = url.split("://", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    return (text[4:] if text.startswith("www.") else text).rstrip("/").lower()


def link_for(service, code, url="", complete="") -> str:
    """The link the QR holds and the phone opens. What the provider's answer gives comes first: its own complete link
    (`complete`, the code already in it), else the page it names (`url`), with nothing added to it. Only the two pages
    this device knows to take the code in the address (SERVICES[...]["prefill"]: YouTube's own activate page, SWEET.TV's
    add-device page), and a service whose answer named no page at all, get the code put in by us. A page the answer names
    that is not one of those (a personal Google client answers google.com/device) is not given a made-up query."""
    complete, url = _web(complete), _web(url)
    if complete:
        return complete
    guide_for = SERVICES[service]
    if code and (not url or _place(url) == guide_for["prefill"].lower()):
        return guide_for["link"].format(code=quote(code, safe="-"))
    return url


def carries(code, link) -> bool:
    """Whether `link` opens the sign-in page with `code` already typed in. A bare page (a personal Google client's
    google.com/device) does not: the person types the code there."""
    return bool(code) and bool(link) and (code in link or quote(code, safe="-") in link)


def publish(service, state, code="", url="", step=1, steps=1, ttl=None, mode=NORMAL, link="", reason="", round=1, rounds=1):
    """Say what the add-on is doing: WAITING with the code to enter, or how it ended.
    `ttl` is how long the code is waited for (seconds); by default what the service or the mode allows. `url` is the
    page the code is entered on and `link` the provider's complete link with the code in it, when its answer had one
    (link_for). `reason` says why a FAILED sign-in failed, when it is known (REASONS).
    `step`/`steps` are the add-on's own count (YouTube: the token slot, of at most four). What a person is told is
    `round` of `rounds`: this approval, of the approvals Google will ask for in this sign-in (the slots that still lack
    a token and for which Google gave a code; the add-on lowers `rounds` when it skips one). A WAITING state also says
    `prefilled`: whether the link has the code in it, so the page says "opens with the code" only when that is true."""
    if service not in SERVICES or state not in STATES:
        return False
    now = int(time.time())
    mode = clean_mode(mode)
    data = {"service": service, "state": state, "mode": mode, "step": int(step), "steps": int(steps),
            "updated": now, "expires": now + int(ttl_for(mode, service) if ttl is None else ttl)}
    if state == WAITING:
        shown = link_for(service, code, url, link) if code else url
        rounds = max(1, min(int(rounds), 9))
        data.update(code=code, url=url, link=shown, prefilled=carries(code, shown),
                    round=max(1, min(int(round), rounds)), rounds=rounds)
    elif state == FAILED and reason in REASONS:
        data["reason"] = reason
    stored = _store(service, data)
    _onboard(service, data)
    if service == "youtube" and state == DONE:
        _channel_note(data)
    return stored


def _channel_note(data):
    """A YouTube sign-in has just succeeded: if the account turns out to have no channel, add that to the finished
    onboarding document (the sections of the account will be empty, which the screens would otherwise leave unexplained).
    The question goes to Google, so it runs in a thread that is waited for at most CHANNEL_WAIT seconds; the "done"
    above is already published, and this is only an addition to it. Whatever goes wrong, nothing changes."""
    if ytchannel is None or onboarding is None or guide is None:
        return
    worker = threading.Thread(target=_channel_hint, args=(data,), daemon=True)
    worker.start()
    worker.join(CHANNEL_WAIT)


def _channel_hint(data):
    try:
        current = next((p for p in youtube_accounts() if p["current"]), None)
        if current is None:
            return
        answer = ytchannel.peek(current["id"])
        if answer.get("state") == "unknown":         # nothing remembered for this sign-in yet: ask Google now
            answer = ytchannel.check(current["id"])
        if answer.get("state") != "no":
            return
        shown = onboarding.read("youtube")
        if not shown or shown.get("state") != DONE or shown.get("updated") != data["updated"]:
            return                                   # another sign-in has begun since: that document is not ours
        onboarding.write("youtube", guide.document("youtube", DONE, channel="no"))
    except Exception:
        pass


def _onboard(service, data):
    """Keep the onboarding picture in step with the sign-in state `data`. Whatever goes wrong here, the sign-in goes on."""
    if onboarding is None or not guide.known(service):
        return
    try:
        if data["state"] == WAITING and data["mode"] == PARTNER:
            onboarding.clear(service)        # the code is typed into the Friendly Share page by hand: nobody follows it on the phone
            return
        state = onboarding.ACTIVE if data["state"] == WAITING else data["state"]
        doc = guide.document(service, state, data.get("code", ""), data.get("link", ""), data["step"], data["steps"],
                             prefilled=data.get("prefilled"), round=data.get("round", 1), rounds=data.get("rounds", 1))
        ttl = min(data["expires"] - data["updated"], ONBOARD_ALIVE) if state == onboarding.ACTIVE else None
        onboarding.write(service, doc, data["updated"], ttl)
    except Exception:
        pass


def touch(service):
    """Heartbeat while waiting: a state that stops being touched is read as gone."""
    data = _load(service)
    if data is None or data["state"] != WAITING:
        return False
    data["updated"] = int(time.time())
    stored = _store(service, data)
    if stored and onboarding is not None:
        try:
            onboarding.extend(service, ONBOARD_ALIVE, until=data.get("expires"), now=data["updated"])
        except Exception:
            pass
    return stored


def read(service, now=None):
    """The current state, or None when there is none, it is stale, or it is long finished."""
    data = _load(service)
    if data is None:
        return None
    now = time.time() if now is None else now
    updated, expires = data.get("updated", 0), data.get("expires", 0)
    if data["state"] == WAITING:
        if now - updated > HEARTBEAT or now > expires:
            return None
    elif now - updated > RESULT_KEEP:
        return None
    out = dict(data)
    out["name"] = SERVICES.get(service, {}).get("name", service)
    out["mode"] = clean_mode(data.get("mode"))
    out["reason"] = data["reason"] if data["state"] == FAILED and data.get("reason") in REASONS else ""
    out["left"] = max(0, int(expires - now)) if data["state"] == WAITING else 0
    return out


def active(now=None):
    """The sign-ins waiting for a person right now."""
    return [s for s in (read(name, now) for name in SERVICES) if s and s["state"] == WAITING]


def waiting_any(now=None):
    """True while some sign-in is alive and waiting for its code: the update must not restart Kodi."""
    return bool(active(now))


def _mark(service, ext, text):
    """A small flag file next to the state, world readable; False when it cannot be written."""
    try:
        os.makedirs(DIR, mode=0o755, exist_ok=True)
        with open(_path(service, ext), "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(_path(service, ext), 0o644)
        return True
    except OSError:
        return False


def _unmark(service, ext):
    try:
        os.unlink(_path(service, ext))
    except OSError:
        pass


def request_cancel(service):
    return service in SERVICES and _mark(service, "cancel", str(int(time.time())))


def cancel_requested(service):
    return os.path.exists(_path(service, "cancel"))


def clear_cancel(service):
    _unmark(service, "cancel")


RENEW_KEEP = 120    # a request for a new code that the add-on has not taken is forgotten after this many seconds


def request_renew(service):
    """The phone asks the sign-in that is running to get a new code in the same run: relaunching it would not do,
    the TV's screen of the old one is still up for a moment and a second launch of the screen is turned away."""
    return service in SERVICES and _mark(service, "renew", str(int(time.time())))


def take_renew(service, now=None):
    """What the add-on calls between two checks: True once if a fresh request for a new code is there (and uses it up)."""
    try:
        with open(_path(service, "renew"), encoding="utf-8") as f:
            age = (time.time() if now is None else now) - int(f.read().strip())
    except (OSError, ValueError):
        return False
    clear_renew(service)
    return -RENEW_KEEP <= age <= RENEW_KEEP


def renew_requested(service):
    return os.path.exists(_path(service, "renew"))


def clear_renew(service):
    _unmark(service, "renew")


def request_mode(service, mode):
    """The phone asks that the next sign-in of `service` runs in `mode`; normal asks for no change."""
    if service not in SERVICES:
        return False
    if clean_mode(mode) == NORMAL:
        clear_mode(service)
        return True
    return _mark(service, "mode", f"{PARTNER} {int(time.time())}")


def requested_mode(service, now=None):
    """The mode asked for and not yet taken, if the request is fresh; else normal."""
    try:
        with open(_path(service, "mode"), encoding="utf-8") as f:
            mode, stamp = f.read().split()
        age = (time.time() if now is None else now) - int(stamp)
    except (OSError, ValueError):
        return NORMAL
    return clean_mode(mode) if -MODE_KEEP <= age <= MODE_KEEP else NORMAL


def take_mode(service, now=None):
    """What the add-on calls when a sign-in starts: the requested mode, which is then used up."""
    mode = requested_mode(service, now)
    clear_mode(service)
    return mode


def clear_mode(service):
    _unmark(service, "mode")


# ---- back to who was signed in, when a sign-in with another account is given up ---------------------

RETURN_GRACE = 90   # s the add-on has to publish its first state after the phone asked for the sign-in


def note_return(service, previous, target, now=None):
    """«Войти другим аккаунтом»: the TV now sits on the empty profile `target`; `previous` is who was signed in."""
    rec = {"previous": str(previous), "target": str(target), "started": int(time.time() if now is None else now)}
    return _mark(service, "return", json.dumps(rec))


def _return_rec(service):
    try:
        with open(_path(service, "return"), encoding="utf-8") as f:
            rec = json.load(f)
        return {"previous": str(rec["previous"]), "target": str(rec["target"]), "started": int(rec["started"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def return_decision(rec, state, profiles, now):
    """What to do with a note_return record: "wait" (the sign-in is going), "drop" (nothing to do: it succeeded, or the
    profile was changed by hand) or "back" (it ended without success, or never started). `state` is the raw state."""
    cur = next((p for p in profiles if p["current"]), None)
    if cur is None or cur["id"] != rec["target"] or cur["signed_in"]:
        return "drop"        # somebody else moved the TV, or the sign-in worked
    if rec["previous"] not in [p["id"] for p in profiles]:
        return "drop"
    if state is not None and state.get("updated", 0) >= rec["started"] - 2:     # a state of this sign-in, not an older one
        if state["state"] == DONE:
            return "drop"
        alive = now - state.get("updated", 0) <= HEARTBEAT and now <= state.get("expires", 0)
        return "wait" if state["state"] == WAITING and alive else "back"
    return "wait" if now - rec["started"] < RETURN_GRACE else "back"


def settle_return(service, switch, now=None):
    """Called every few seconds by the panel: when a sign-in with another account ended without success (cancelled,
    failed, code expired, the add-on went silent), switch the TV back to `previous` once, and only if the TV is
    still on the empty profile. `switch(profile_id)` raises when the TV does not answer: the note stays, to try again."""
    rec = _return_rec(service)
    if rec is None:
        return None
    now = time.time() if now is None else now
    verdict = return_decision(rec, _load(service), youtube_accounts(), now)
    if verdict == "back":
        switch(rec["previous"])
    if verdict != "wait":
        _unmark(service, "return")
    return verdict


# ---- waiting for a partner: the rules of the add-on's loop, pure ---------------------------------

POLL_FAST, POLL_SLOW, FAST_FOR = 3, 12, 10 * 60     # s between checks, and for how long the quick pace lasts
RETRY_FIRST, RETRY_MAX = 5, 60                      # s of the pause after a check with no answer: doubles up to the cap
NO_ANSWER_LIMIT = 30 * 60                           # s of checks in a row with no answer after which the code is given up
LOG_AGAIN = 10 * 60                                 # the same unknown answer is logged again after this long
NOTE_MAX = 200
# The `result` texts of SWEET.TV's check reply that only say "not yet": a device's log showed STARTED (with an
# access_token and expires_in 0, which mean nothing yet) for as long as the code waits; it is not worth a warning.
SWEETTV_WAITING = frozenset({"STARTED"})
# The `result` texts of SWEET.TV's check reply that mean the code is refused. What the server says is not known
# yet: stays empty until a first run's log (WARNING lines of PartnerPoll) shows it. Any text with EXPIRED in it
# (an expired code, whatever the exact word) is a refusal too. Anything else that is not COMPLETED is logged and waited on.
SWEETTV_REFUSED = frozenset()
SECRET_KEY = re.compile(r"token|secret|pass|auth|bearer|cookie|session|sign|key", re.I)


def describe(reply):
    """A reply as one short log line: values of anything that smells of a secret hidden, 200 characters at most."""
    if isinstance(reply, dict):
        keys = sorted(reply, key=lambda k: (str(k) != "result", str(k)))     # what the server says first: the cut comes last
        reply = {str(k): "***" if SECRET_KEY.search(str(k)) else reply[k] for k in keys}
    else:
        reply = f"<{type(reply).__name__}>"
    text = str(reply)
    return text if len(text) <= NOTE_MAX else text[:NOTE_MAX - 1] + "…"


class PartnerPoll:
    """How the add-on waits for a partner: when to ask again, what to do about no answer, what an
    answer means. Takes the time as an argument and sleeps nowhere; answers with what to log."""

    def __init__(self, started, refused=None):
        self.started, self.refused = started, refused
        self.failures = 0                # checks in a row that got no answer
        self.first_failure = None        # when the first of them was
        self.logged = {}                 # described unknown answer -> when it was last logged

    def delay(self, now):
        """Seconds to wait after an answer that says "not yet"."""
        return POLL_FAST if now - self.started < FAST_FOR else POLL_SLOW

    def no_answer(self, now):
        """(seconds to wait, what to log or "") after a check that got no answer; lost() says when to give up."""
        if not self.failures:
            self.first_failure = now
        self.failures += 1
        wait = min(RETRY_MAX, RETRY_FIRST * 2 ** min(self.failures - 1, 6))
        note = ""
        if self.failures == 1 or self.failures % 10 == 0:
            note = f"media-stick: SWEET.TV check got no answer ({self.failures} in a row); trying again in {wait} s"
        return wait, note

    def lost(self, now):
        """True once the checks have got no answer for NO_ANSWER_LIMIT: the code is given up (it may be gone, or the
        network is: either way the person is told to ask for a new one)."""
        return bool(self.failures) and self.first_failure is not None and now - self.first_failure >= NO_ANSWER_LIMIT

    def answer(self, reply, now):
        """(verdict, what to log or ""): completed | refused | unknown (keep waiting)."""
        self.failures, self.first_failure = 0, None
        result = reply.get("result") if isinstance(reply, dict) else None
        if result == "COMPLETED":
            return "completed", ""
        refused = SWEETTV_REFUSED if self.refused is None else self.refused
        text = describe(reply)
        if isinstance(result, str) and (result in refused or "EXPIRED" in result.upper()):
            return "refused", f"media-stick: SWEET.TV refused the code: {text}"
        if isinstance(result, str) and result in SWEETTV_WAITING:
            return "unknown", ""
        last = self.logged.get(text)
        if last is not None and now - last < LOG_AGAIN:
            return "unknown", ""
        self.logged[text] = now
        return "unknown", f"media-stick: SWEET.TV check answered something unexpected, still waiting: {text}"


# ---- who is signed in -----------------------------------------------------------------------

def _addon_file(addon, name):
    return os.path.join(USERDATA, addon, name)


def youtube_accounts():
    """YouTube's profiles: [{id, name, current, tokens, signed_in}]. The add-on signs each
    profile in up to four times (tokens tv|user|vr|dev), so `tokens` says how far it got."""
    try:
        with open(_addon_file("plugin.video.youtube", "access_manager.json"), encoding="utf-8") as f:
            manager = json.load(f).get("access_manager", {})
        users = manager.get("users", {})
        current = str(manager.get("current_user", 0))
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for uid in sorted(users, key=lambda k: (not str(k).isdigit(), int(k) if str(k).isdigit() else 0, str(k))):
        user = users[uid] if isinstance(users[uid], dict) else {}
        tokens = sum(1 for t in str(user.get("refresh_token", "")).split("|") if t)
        out.append({"id": str(uid), "name": user.get("name") or "Default", "current": str(uid) == current,
                    "tokens": tokens, "signed_in": tokens > 0})
    return out


def sweettv_signed_in():
    """SWEET.TV has one account; it is signed in when the add-on says `logged`."""
    try:
        root = ET.parse(_addon_file("plugin.video.sweettv", "settings.xml")).getroot()
    except (OSError, ET.ParseError):
        return False
    for node in root.iter("setting"):
        if node.get("id") == "logged":
            return (node.text or "").strip().lower() == "true"
    return False


def accounts():
    """Everything a screen needs for the Accounts list, one entry per service."""
    youtube = youtube_accounts()
    return [
        {"service": "youtube", "name": SERVICES["youtube"]["name"], "profiles": youtube,
         "signed_in": any(p["signed_in"] for p in youtube), "signin": read("youtube")},
        {"service": "sweettv", "name": SERVICES["sweettv"]["name"], "profiles": [],
         "signed_in": sweettv_signed_in(), "signin": read("sweettv")},
    ]


def main(argv):
    """`python3 mediastick_signin.py waiting`: for media-stick-update, like `media-stick-lease check`:
    exit 3 and say who, while a sign-in waits for its code; exit 0 when nothing does."""
    if argv != ["waiting"]:
        print("usage: mediastick_signin.py waiting", file=sys.stderr)
        return 2
    live = active()
    for s in live:
        print(f"{s['name']} sign-in waits for a code ({s['mode']}, {s['left'] // 60} min left)")
    return 3 if live else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
