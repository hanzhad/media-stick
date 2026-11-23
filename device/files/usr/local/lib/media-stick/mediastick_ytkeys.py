"""YouTube's personal Google keys: the rules for the values and the hand-over between the phone page and Kodi.

The YouTube add-on keeps a personal key, OAuth client id and client secret in its own settings, and a settings
change is Kodi's business (an add-on's settings.xml is not edited while Kodi runs). So the panel (user media)
puts the values into one small file in tmpfs, mode 0600, and asks Kodi to run
RunScript(script.media-stick.home,ytkeys); the script reads the file, deletes it at once, writes the settings
through xbmcaddon and answers in a second file that holds no value but the last four characters of the key.
Values are never logged and never sent back to the page.

Besides that there is one file that holds no secret: ytkeys.step.json (mode 0644), which tells the TV on which step of
the phone's wizard the owner is. The panel writes it (write_step), the TV's code reads it (read_step).

Standard library only: it imports the same in Kodi's Python, in the panel and in a test.
"""
import json
import os
import secrets
import tempfile
import time
import xml.etree.ElementTree as ET

import mediastick_signin as signin

DIR = os.environ.get("MEDIASTICK_YTKEYS_DIR", "/run/media-stick")
ADDON = "plugin.video.youtube"
# our name for each value -> the add-on's setting
SETTINGS = {"api_key": "youtube.api.key", "client_id": "youtube.api.id", "client_secret": "youtube.api.secret"}
LABELS = {"api_key": "Ключ API", "client_id": "Client ID", "client_secret": "Client secret"}
LIMITS = {"api_key": 128, "client_id": 256, "client_secret": 128}
KEY_MIN = 20
ID_SUFFIX = ".apps.googleusercontent.com"

REQUEST, RESULT = "ytkeys.json", "ytkeys.result"
OPS = ("save", "clear")
MAX_AGE = 60                 # s: a request older than this is left over from something that went wrong
MAX_BYTES = 4096
# the step file (no secret in it): where the owner is in the wizard, for the TV to show
STEP = "ytkeys.step.json"
STEP_MAX_AGE = 30 * 60       # s: an older file is what a phone left behind when it went away
STEP_TOTAL_MAX = 9
STEP_TITLE_MAX, STEP_HINT_MAX = 80, 120
# what the script may answer; the panel turns each into a sentence
ERRORS = ("no_request", "insecure", "stale", "bad_request", "addon_missing", "write_failed")


class Invalid(ValueError):
    """A value the page sent is not acceptable; the message (Russian) never repeats the value."""


class BadRequest(Exception):
    """The request file cannot be used. `id` is the caller's id when it could be read, else ""."""
    def __init__(self, code, rid=""):
        super().__init__(code)
        self.code, self.id = code, rid


# ---- the values: pure ------------------------------------------------------------------------

def _plain(value, name):
    """One value, trimmed: printable ASCII with no space inside, not empty, not longer than its limit."""
    label = LABELS[name]
    if not isinstance(value, str) or not value.strip():
        raise Invalid("Заполните поле «%s»." % label)
    value = value.strip()
    if len(value) > LIMITS[name]:
        raise Invalid("Поле «%s» слишком длинное." % label)
    if any(not 33 <= ord(c) <= 126 for c in value):
        raise Invalid("В поле «%s» не должно быть пробелов, переводов строк и русских букв." % label)
    return value


def clean_values(body):
    """{api_key, client_id, client_secret} from what the page sent, or Invalid."""
    values = {name: _plain(body.get(name), name) for name in SETTINGS}
    if len(values["api_key"]) < KEY_MIN:
        raise Invalid("Ключ API слишком короткий: скопируйте его целиком.")
    if not values["client_id"].endswith(ID_SUFFIX) or len(values["client_id"]) <= len(ID_SUFFIX):
        raise Invalid("Client ID должен оканчиваться на %s." % ID_SUFFIX)
    return values


def tail4(value):
    """The last four characters, all the page may see of a key."""
    return value[-4:] if isinstance(value, str) else ""


def describe(values):
    """What is stored, as the page may see it: {set, partial, last4}. `values` is read_settings() or None."""
    filled = [bool(values and values.get(name)) for name in SETTINGS]
    full = all(filled)
    return {"set": full, "partial": any(filled) and not full, "last4": tail4(values["api_key"]) if full else ""}


# ---- the add-on's settings: read only ----------------------------------------------------------

def read_settings(userdata=None):
    """The three values as the add-on's settings.xml holds them (empty when unset); None when it cannot be read."""
    path = os.path.join(userdata or signin.USERDATA, ADDON, "settings.xml")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    found = {node.get("id"): (node.text or "").strip() for node in root.iter("setting")}
    return {name: found.get(setting, "") for name, setting in SETTINGS.items()}


# ---- the hand-over files -----------------------------------------------------------------------

def _path(name):
    return os.path.join(DIR, name)


def _unlink(name):
    try:
        os.unlink(_path(name))
    except OSError:
        pass


def _write_private(name, data, mode=0o600):
    """Write the file whole, mode 0600 (or `mode`) before the first byte, and rename it into place."""
    tmp = None
    try:
        os.makedirs(DIR, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
        os.chmod(tmp, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _path(name))
    except (OSError, ValueError, TypeError):
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise OSError("cannot write %s" % name)


def send_request(op, values=None):
    """Panel side: leave a request for Kodi's script (after forgetting an old answer); its id. Raises OSError."""
    rid = secrets.token_hex(8)
    _unlink(RESULT)
    _write_private(REQUEST, {"id": rid, "op": op, "values": values or {}})
    return rid


def withdraw_request():
    """Panel side: nobody took the request, so it must not lie around."""
    _unlink(REQUEST)


def take_request(now=None):
    """Script side: the request as {id, op, values}, and the file is gone either way. Raises BadRequest.
    The file must be this user's, readable by nobody else, and fresh."""
    try:
        with open(_path(REQUEST), "rb") as f:
            st = os.fstat(f.fileno())
            raw = f.read(MAX_BYTES + 1)
    except OSError:
        raise BadRequest("no_request")
    finally:
        _unlink(REQUEST)
    try:
        data = json.loads(raw) if len(raw) <= MAX_BYTES else None
    except ValueError:
        data = None
    rid = data.get("id") if isinstance(data, dict) else ""
    rid = rid if isinstance(rid, str) and len(rid) <= 32 else ""
    if st.st_mode & 0o077 or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
        raise BadRequest("insecure", rid)
    if abs((time.time() if now is None else now) - st.st_mtime) > MAX_AGE:
        raise BadRequest("stale", rid)
    if not isinstance(data, dict) or data.get("op") not in OPS or not rid:
        raise BadRequest("bad_request", rid)
    values = {}
    if data["op"] == "save":
        try:
            values = clean_values(data["values"] if isinstance(data.get("values"), dict) else {})
        except Invalid:
            raise BadRequest("bad_request", rid)
    return {"id": rid, "op": data["op"], "values": values}


def send_result(rid, ok, error="", last4=""):
    """Script side: the answer; no value in it but the last four characters of the key. False if it cannot be written."""
    try:
        _write_private(RESULT, {"id": rid, "ok": bool(ok), "error": error if error in ERRORS else "",
                                "last4": tail4(last4)})
        return True
    except OSError:
        return False


def read_result(rid):
    """Panel side: {ok, error, last4} when the script has answered this request, else None. The answer is used up."""
    try:
        with open(_path(RESULT), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") != rid:
        return None
    _unlink(RESULT)
    error = data.get("error") if data.get("error") in ERRORS else ""
    return {"ok": data.get("ok") is True, "error": error, "last4": tail4(data.get("last4"))}


# ---- the step file: where the owner is in the wizard, for the TV (no secret in it) ----------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def write_step(step, total, title, hint, now=None):
    """Panel side: tell the TV the owner is on step `step` of `total`, with that step's title and hint (text from the
    wizard's own description, never a value from the page). Mode 0644, renamed into place. Raises OSError, ValueError."""
    if not (_is_int(step) and _is_int(total)) or not 1 <= step <= total <= STEP_TOTAL_MAX:
        raise ValueError("step out of range")
    if not isinstance(title, str) or not isinstance(hint, str):
        raise ValueError("step text")
    _write_private(STEP, {"step": step, "total": total, "title": title[:STEP_TITLE_MAX], "hint": hint[:STEP_HINT_MAX],
                          "updated": int(time.time() if now is None else now)}, 0o644)


def clear_step():
    """Panel side: the wizard is closed or finished, the TV has nothing to say about it."""
    _unlink(STEP)


def read_step(path=None, now=None):
    """TV side: {step, total, title, hint, updated} while the step file is good, else None: no file, not JSON, not
    the right shape, a step outside 1..total, or a file older than STEP_MAX_AGE (the phone went away). `path` is the
    file (the usual one when None), `now` the time (unix seconds)."""
    try:
        with open(path or _path(STEP), "rb") as f:
            raw = f.read(MAX_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_BYTES else None
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    step, total, updated = data.get("step"), data.get("total"), data.get("updated")
    title, hint = data.get("title"), data.get("hint")
    if not (_is_int(step) and _is_int(total) and isinstance(updated, (int, float)) and not isinstance(updated, bool)
            and isinstance(title, str) and isinstance(hint, str)):
        return None
    if not 1 <= step <= total <= STEP_TOTAL_MAX or not -2 ** 40 < updated < 2 ** 40:     # also NaN
        return None
    if abs((time.time() if now is None else now) - updated) > STEP_MAX_AGE:
        return None
    return {"step": step, "total": total, "title": title[:STEP_TITLE_MAX], "hint": hint[:STEP_HINT_MAX],
            "updated": int(updated)}
