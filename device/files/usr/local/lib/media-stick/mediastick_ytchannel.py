"""Does the Google account a YouTube profile signed in with have a YouTube channel?

Without one, Google gives other apps (the Kodi add-on among them) no subscriptions, Watch Later
or playlists: every "mine" request answers "Channel not found" and the sections stay empty,
while recommendations, search and trending work. The YouTube app on a phone does not need it,
so people do not know they have no channel. This asks Google once and remembers the answer,
so the phone and the TV can say what is wrong and how to fix it.

    peek(profile_id)  -> {"state": "yes" | "no" | "unknown", "title": str}   never waits; looks
                         again in the background when the remembered answer is old
    check(profile_id) -> the same, asks Google now (up to a few seconds)
    python3 mediastick_ytchannel.py [profile_id]   prints check() as JSON

The add-on's own access tokens are read from its access_manager.json and sent only to
www.googleapis.com; they are never written anywhere, printed or logged. The answer is kept
in RAM (/run) under a hash of the profile's refresh tokens, so signing in again (another
account) asks again.
"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

USERDATA = os.environ.get("MEDIASTICK_ADDON_DATA", "/home/media/.kodi/userdata/addon_data")
CACHE = os.environ.get("MEDIASTICK_YTCHANNEL_CACHE", "/run/media-stick/ytchannel.json")
URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=1"
TIMEOUT = 4
# how long an answer holds: a channel does not go away; "no" is looked at again soon, because
# the owner is likely creating one right now; "unknown" (no network, token expired) soonest
TTL = {"yes": 6 * 3600, "no": 300, "unknown": 60}
TITLE_MAX = 64

_lock = threading.Lock()
_busy = set()


def _off():
    """MEDIASTICK_YTCHANNEL_OFF=1: never ask Google (offline tests)."""
    return os.environ.get("MEDIASTICK_YTCHANNEL_OFF") == "1"


def _profile(profile_id):
    """(access tokens, a hash naming this sign-in) of one profile, or None."""
    try:
        with open(os.path.join(USERDATA, "plugin.video.youtube", "access_manager.json"), encoding="utf-8") as f:
            users = json.load(f).get("access_manager", {}).get("users", {})
    except (OSError, ValueError, AttributeError):
        return None
    user = users.get(str(profile_id))
    if not isinstance(user, dict):
        return None
    refresh = str(user.get("refresh_token", ""))
    tokens = [t for t in str(user.get("access_token", "")).split("|") if t]
    if not tokens or not refresh.strip("|"):
        return None
    return tokens, hashlib.sha256(refresh.encode()).hexdigest()[:16]


def _clean_title(value):
    text = " ".join(str(value or "").split())
    return "".join(ch for ch in text if ch.isprintable())[:TITLE_MAX]


def _ask(tokens):
    """Ask Google with each token until one is accepted."""
    for token in tokens:
        req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read(200_000).decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            continue        # this token expired or is for another client: try the next one
        except (OSError, ValueError):
            return {"state": "unknown", "title": ""}
        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            return {"state": "no", "title": ""}
        snippet = items[0].get("snippet", {}) if isinstance(items[0], dict) else {}
        return {"state": "yes", "title": _clean_title(snippet.get("title"))}
    return {"state": "unknown", "title": ""}


def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(key, answer):
    with _lock:
        data = _load()
        now = time.time()
        data = {k: v for k, v in data.items() if isinstance(v, dict) and now - v.get("t", 0) < 86400}
        data[key] = dict(answer, t=now)
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            tmp = CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, CACHE)
        except OSError:
            pass


def _key(profile_id, sign_hash):
    return f"{profile_id}:{sign_hash}"


def check(profile_id):
    p = _profile(profile_id)
    if not p or _off():
        return {"state": "unknown", "title": ""}
    answer = _ask(p[0])
    _save(_key(profile_id, p[1]), answer)
    return answer


def _refresh(profile_id, key):
    try:
        check(profile_id)
    finally:
        with _lock:
            _busy.discard(key)


def peek(profile_id):
    p = _profile(profile_id)
    if not p or _off():
        return {"state": "unknown", "title": ""}
    key = _key(profile_id, p[1])
    known = _load().get(key)
    fresh = isinstance(known, dict) and time.time() - known.get("t", 0) < TTL.get(known.get("state"), 60)
    if not fresh:
        with _lock:
            start = key not in _busy
            _busy.add(key)
        if start:
            threading.Thread(target=_refresh, args=(profile_id, key), daemon=True).start()
    if isinstance(known, dict) and known.get("state") in TTL:
        return {"state": known["state"], "title": _clean_title(known.get("title"))}
    return {"state": "unknown", "title": ""}


def main(argv):
    profile_id = argv[0] if argv else None
    if profile_id is None:
        try:
            with open(os.path.join(USERDATA, "plugin.video.youtube", "access_manager.json"), encoding="utf-8") as f:
                profile_id = str(json.load(f).get("access_manager", {}).get("current_user", 0))
        except (OSError, ValueError, AttributeError):
            profile_id = "0"
    print(json.dumps(check(profile_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
