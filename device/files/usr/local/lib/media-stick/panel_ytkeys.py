"""The "Google key for YouTube" wizard of the panel, server side: checking what the owner pastes with Google, keeping
the wizard's progress, and handing the values to Kodi (see mediastick_ytkeys for the hand-over and the rules for
values; panel_ytkeys_steps for the words and for what a key, a client ID and a secret look like).

POST /api/accounts/ytkeys {"action": "status" | "check" | "verify" | "save" | "clear" | "step" | "tick" | "resume", ...}.
The panel has already checked the X-Panel header and the Host. Values are never logged and never sent back: a reply
carries the last four characters of the key and nothing else of them.
  "verify" ({"value": text}): says what the pasted text is (key, client ID, secret) and asks Google about the first two.
  "step" ({"step": 0..4}) and "tick" ({"id", "on"}) say where the owner is: the TV reads it from a file that holds no
  value (mediastick_ytkeys.write_step) and from the onboarding document (mediastick_onboarding, when it is there).
  "resume" gives the step and the ticks back to a page that was away.
The page's markup lives in panel_ytkeys_ui.py.

Standard library only, nothing happens on import.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException
from typing import Callable, NamedTuple

import mediastick_screen as screen   # a cast or a web app has the TV: say so, not "Kodi не отвечает"
import mediastick_ytkeys as keys
import panel_ytkeys_steps as st
from panel_ytkeys_steps import DOC_URL, STEP_TOTAL, STEPS, TICK_IDS, linked, step_text  # noqa: F401  (the tests read them here)
from panel_ytkeys_steps import android_intent, safari_link  # noqa: F401

try:
    from mediastick_onboarding import write as ob_write, clear as ob_clear
except ImportError:                 # the TV side's library is not there (yet): the step file alone tells the TV
    ob_write = ob_clear = None

LAUNCHER = "script.media-stick.home"
CHECK_URL = "https://www.googleapis.com/youtube/v3/videos"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"      # asked with a client ID to see what kind of client it is
DEVICE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
CHECK_TIMEOUT = 10         # s for Google to answer
WAIT = 12.0                # s for Kodi's script to answer
WAIT_STEP = 0.25
BODY_MAX = 8192            # of Google's error body, at most this much is read
KODI_DOWN = "Kodi не отвечает. Подождите минуту и попробуйте снова."


class Io(NamedTuple):
    """The three things the module does not do itself, so a test can replace them."""
    urlopen: Callable
    sleep: Callable
    clock: Callable


REAL = Io(urllib.request.urlopen, time.sleep, time.monotonic)
LOCK = threading.Lock()    # one hand-over at a time: there is one request file


class Refused(Exception):
    def __init__(self, message, code=400, extra=None):
        super().__init__(message)
        self.message, self.code, self.extra = message, code, extra or {}


# ---- what the page draws: one description for the page and the tests ----------------------------------

OPEN_HINT = "Откроется в браузере. Вернитесь в пульт и нажмите «Сделано, дальше»."
BACK_HINT = "Вернитесь в пульт и нажмите «Сделано, дальше»."
STANDALONE_HINT = "Если страница открылась внутри пульта, нажмите «Скопировать ссылку» и вставьте её в браузер."
IOS_STANDALONE_HINT = ("Ссылки открываются внутри приложения. Чтобы открывать их в Safari, откройте пульт в Safari, "
                       "а не с экрана «Домой». Вернуться сюда можно кнопкой «Закрыть» вверху.")
WIZARD = {
    "steps": tuple(linked(s) for s in STEPS),
    "ticks": [{"id": i, "label": phone} for i, _tv, phone in st.TICKS],
    "patterns": dict(st.PATTERNS),
    "paste_max": st.PASTE_MAX,
    "json_max": 16384,
    "fields": [{"name": n, "label": keys.LABELS[n], "max": keys.LIMITS[n], "secret": n == "client_secret"}
               for n in keys.SETTINGS],
    "doc": linked({"url": DOC_URL, "button": "Описание от Google"}),
    "note": "Интерфейс Google меняется. Если надписи отличаются, ищите похожие.",
    "texts": {"open": OPEN_HINT, "back": BACK_HINT, "standalone": STANDALONE_HINT, "ios_standalone": IOS_STANDALONE_HINT,
              "copy": "Скопировать ссылку", "copied": "Ссылка скопирована", "safari": "Открыть в Safari",
              "resume": "Продолжить настройку ключей (шаг %d из %d)", "unknown": st.NOT_RECOGNISED,
              "header": "Ключ Google для YouTube",
              "intro": "Нужен один раз, минут пять. С компьютера удобнее: откройте %s в браузере ноутбука — шаги те же."},
}


# ---- Google's verdict on a key: pure ------------------------------------------------------------

INVALID, DISABLED, BLOCKED, QUOTA, NET, OTHER, OK = "invalid", "disabled", "blocked", "quota", "net", "other", "ok"
CLIENT_MISSING, CLIENT_TYPE = "client_missing", "client_type"
SAVABLE = (OK, QUOTA)      # a key over its daily quota is still the right key
REASONS = (
    (INVALID, ("API_KEY_INVALID", "keyInvalid", "API_KEY_NOT_FOUND")),
    (BLOCKED, ("API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED", "API_KEY_ANDROID_APP_BLOCKED",
               "API_KEY_IOS_APP_BLOCKED", "API_KEY_SERVICE_BLOCKED", "ipRefererBlocked", "referrerNotAllowed")),
    (DISABLED, ("accessNotConfigured", "SERVICE_DISABLED")),
    (QUOTA, ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "RATE_LIMIT_EXCEEDED")),
)
HINTS = {
    OK: "Ключ работает.",
    QUOTA: "Ключ верный, но лимит запросов на сегодня исчерпан. Завтра заработает.",
    INVALID: "Google не принимает этот ключ. Скопируйте ключ API заново, целиком.",
    DISABLED: "Ключ верный, но в проекте не включён YouTube Data API v3. Включите его (шаг 1) и через минуту проверьте снова.",
    BLOCKED: "У ключа есть ограничения. В Google Cloud откройте этот ключ и уберите их "
             "или разрешите ему YouTube Data API v3. Потом проверьте снова.",
    NET: "Не удалось связаться с Google. Проверьте интернет на приставке и попробуйте ещё раз.",
}
CLIENT_HINTS = {
    OK: "Клиент для ТВ найден.",
    CLIENT_MISSING: "ID не найден",
    CLIENT_TYPE: "Это не клиент для ТВ: выберите тип TVs and Limited Input devices",
}


def reasons_of(body):
    """The reason words in Google's error body (bytes or str), as a set; empty when it is not the usual JSON."""
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError, TypeError):
        return set()
    if not isinstance(error, dict):
        return set()
    found = {error.get("status")}
    for part in (error.get("errors"), error.get("details")):
        for item in part if isinstance(part, list) else ():
            found.add(item.get("reason") if isinstance(item, dict) else None)
    return {r for r in found if isinstance(r, str)}


def classify(code, reasons):
    """The verdict on a key from the HTTP code and the reasons Google gave."""
    if code == 200:
        return OK
    if code in (400, 403):
        for verdict, words in REASONS:
            if reasons & set(words):
                return verdict
    return OTHER


def classify_client(code, body):
    """The verdict on a client ID from the answer of the device-code endpoint (HTTP code, body bytes or str): a 200
    that holds a device code is a client for TVs (the code is dropped here, never kept); `invalid_client` is an ID
    Google does not know; `unauthorized_client`, or `invalid_request` that talks about the client type, is a client
    of another type. Google's own words are not passed on."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        data = None
    data = data if isinstance(data, dict) else {}
    if code == 200:
        return OK if isinstance(data.get("device_code"), str) and data["device_code"] else OTHER
    error, text = data.get("error"), data.get("error_description")
    if error == "invalid_client":
        return CLIENT_MISSING
    if error == "unauthorized_client":
        return CLIENT_TYPE
    if error == "invalid_request" and isinstance(text, str) and "type" in text.lower():
        return CLIENT_TYPE
    return OTHER


def hint(verdict, code=0, kind="api_key"):
    first, second = (CLIENT_HINTS, HINTS) if kind == "client_id" else (HINTS, CLIENT_HINTS)
    return (first.get(verdict) or second.get(verdict)
            or "Google ответил ошибкой%s. Попробуйте позже." % (" (код %d)" % code if code else ""))


# ---- asking Google -------------------------------------------------------------------------------

def check_key(key, io=None):
    """(verdict, HTTP code or 0) for one request made from this device. The key is in the URL, so neither it
    nor any exception text (which may hold it) leaves this function."""
    io = io or REAL
    url = CHECK_URL + "?" + urllib.parse.urlencode(
        {"part": "id", "chart": "mostPopular", "maxResults": 1, "key": key})
    try:
        with io.urlopen(url, timeout=CHECK_TIMEOUT) as r:
            r.read(BODY_MAX)
            return classify(r.status, set()), r.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read(BODY_MAX)
        except (OSError, HTTPException):
            body = b""
        return classify(e.code, reasons_of(body)), e.code
    except (OSError, ValueError, HTTPException):
        return NET, 0


def check_client(client_id, io=None):
    """(verdict, HTTP code or 0) for a client ID: one POST of the ID and the YouTube scope to Google's device-code
    endpoint (the ID travels in the body, not in a URL, and is not logged). The device code it may hand back is
    dropped inside classify_client."""
    io = io or REAL
    data = urllib.parse.urlencode({"client_id": client_id, "scope": DEVICE_SCOPE}).encode("ascii")
    req = urllib.request.Request(DEVICE_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with io.urlopen(req, timeout=CHECK_TIMEOUT) as r:
            return classify_client(r.status, r.read(BODY_MAX)), r.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read(BODY_MAX)
        except (OSError, HTTPException):
            body = b""
        return classify_client(e.code, body), e.code
    except (OSError, ValueError, HTTPException):
        return NET, 0


def _verdict_reply(verdict, code):
    return {"check": verdict, "works": verdict in SAVABLE, "message": hint(verdict, code)}


# ---- where the owner is in the wizard (kept in memory; the TV is told through files) ------------------

class Progress:
    """The step, the ticks of step 2 and what the phone found good. No value."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.step, self.open, self.touched = 1, False, False
        self.ticks = set()
        self.checks = {name: None for name in keys.CHECK_NAMES}


PROGRESS = Progress()


def _ob(fn, *args):
    """The onboarding library, when there is one; a failure there never fails the wizard."""
    if fn is not None:
        try:
            fn(*args)
        except Exception:            # noqa: BLE001  (best effort: the step file still tells the TV)
            pass


def _publish(strict=False):
    """Tell the TV where the owner is: the step file, and the onboarding document when its library is there."""
    with PROGRESS.lock:
        if not PROGRESS.open:
            return
        step, ticks, checks = PROGRESS.step, set(PROGRESS.ticks), dict(PROGRESS.checks)
    try:
        keys.write_step(step, STEP_TOTAL, *step_text(step), checks=checks)
    except (OSError, ValueError):
        if strict:
            raise Refused("Не получилось записать шаг.", 500)
    _ob(ob_write, "youtube", st.onboarding_doc(step, ticks, checks, time.time()))


def _unpublish():
    keys.clear_step()
    _ob(ob_clear, "youtube")


# ---- the actions ---------------------------------------------------------------------------------

def _status(body, rpc, io):
    return dict(keys.describe(keys.read_settings()), ok=True)


def _check(body, rpc, io):
    stored = keys.read_settings()
    if not keys.describe(stored)["set"]:
        raise Refused("Ключ не задан.", 409)
    return dict(_verdict_reply(*check_key(stored["api_key"], io)), ok=True)


def _verify(body, rpc, io):
    """What the pasted text is, and Google's word on it: a key is tried with one request, a client ID with one more
    to the device-code endpoint, a secret is only checked for its shape. The reply holds no value."""
    found = st.detect(body.get("value"))
    if not found:
        raise Refused(st.NOT_RECOGNISED, 400, {"check": "unknown"})
    kind, value = found
    if kind == "api_key":
        verdict, code = check_key(value, io)
        works = verdict in SAVABLE
    elif kind == "client_id":
        verdict, code = check_client(value, io)
        works = verdict == OK
    else:
        verdict, code, works = OK, 200, True
    reply = {"ok": True, "kind": kind, "check": verdict, "works": works,
             "message": "Secret принят." if kind == "client_secret" else hint(verdict, code, kind)}
    name = {k: n for k, n, _ in st.KINDS}[kind]
    with PROGRESS.lock:
        PROGRESS.checks[name] = None if verdict == NET else works
    _publish()
    return reply


RESULT_ERRORS = {
    "addon_missing": "Дополнение YouTube не установлено.",
    "write_failed": "Kodi не смог записать настройки YouTube. Попробуйте ещё раз.",
}
RESULT_ELSE = "Kodi не принял запрос. Попробуйте ещё раз."


def _hand_over(op, values, rpc, io):
    """Ask Kodi's script to do `op` and wait for its answer: its {ok, error, last4}. Never leaves the request lying."""
    if not LOCK.acquire(blocking=False):
        raise Refused("Запись уже идёт. Подождите несколько секунд.", 409)
    try:
        try:
            rid = keys.send_request(op, values)
        except OSError:
            raise Refused("Не получилось передать ключи Kodi.", 500)
        try:
            rpc("Addons.ExecuteAddon", {"addonid": LAUNCHER, "params": ["ytkeys"]})
        except (OSError, ValueError):
            raise Refused(screen.kodi_down(), 503)
        end = io.clock() + WAIT
        while True:
            result = keys.read_result(rid)
            if result is not None:
                break
            if io.clock() >= end:
                raise Refused("Kodi не ответил. Подождите минуту и попробуйте снова.", 504)
            io.sleep(WAIT_STEP)
        if not result["ok"]:
            raise Refused(RESULT_ERRORS.get(result["error"], RESULT_ELSE), 500)
        return result
    finally:
        keys.withdraw_request()
        LOCK.release()


def _strict(values):
    """The server does not trust the page: each value must look like what it is (the page's guess is not asked)."""
    for kind, _name, _label in st.KINDS:
        if not st.matches(kind, values[kind]):
            raise Refused("«%s» не похоже на настоящее значение: скопируйте его заново, целиком." % keys.LABELS[kind])


def _save(body, rpc, io):
    try:
        values = keys.clean_values(body)
    except keys.Invalid as e:
        raise Refused(str(e))
    _strict(values)
    verdict, code = ("skipped", 0) if body.get("skip_check") is True else check_key(values["api_key"], io)
    reply = _verdict_reply(verdict, code) if verdict != "skipped" else {"check": verdict, "works": None, "message": ""}
    if verdict != "skipped" and verdict not in SAVABLE:
        raise Refused(reply["message"], 422, {"check": verdict})
    result = _hand_over("save", values, rpc, io)
    with PROGRESS.lock:
        PROGRESS.reset()       # the wizard is finished: the TV has no step to show
    _unpublish()
    return dict(reply, ok=True, saved=True, last4=result["last4"])


def _clear(body, rpc, io):
    _hand_over("clear", None, rpc, io)
    return {"ok": True, "cleared": True}


def _step(body, rpc, io):
    """Where the owner is in the wizard (1..STEP_TOTAL), or 0 when it is closed. Nothing from the body but the
    number goes anywhere: the words of the step are this module's own."""
    n = body.get("step")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= STEP_TOTAL:
        raise Refused("Неверный номер шага.")
    if n:
        with PROGRESS.lock:
            PROGRESS.step, PROGRESS.open, PROGRESS.touched = n, True, True
        _publish(strict=True)
    else:
        with PROGRESS.lock:
            PROGRESS.open = False
        _unpublish()
    return {"ok": True, "step": n}


def _tick(body, rpc, io):
    """One box of step 2's checklist ticked or cleared; the TV's chips follow."""
    tid, on = body.get("id"), body.get("on")
    if not isinstance(tid, str) or tid not in TICK_IDS or not isinstance(on, bool):
        raise Refused("Неверный пункт.")
    with PROGRESS.lock:
        (PROGRESS.ticks.add if on else PROGRESS.ticks.discard)(tid)
        ticks = [i for i in TICK_IDS if i in PROGRESS.ticks]
    _publish()
    return {"ok": True, "ticks": ticks}


def _resume(body, rpc, io):
    """The step and the ticks a page that was away needs. {"fresh": true} says the page holds none of the values
    any more, so what was found good is forgotten (the TV's marks follow)."""
    with PROGRESS.lock:
        if not PROGRESS.touched:           # the panel restarted: the step file still knows
            known = keys.read_step()
            if known and known["step"] <= STEP_TOTAL:
                PROGRESS.step, PROGRESS.open = known["step"], True
            PROGRESS.touched = True
        if body.get("fresh") is True:
            PROGRESS.checks = {name: None for name in keys.CHECK_NAMES}
        reply = {"ok": True, "step": PROGRESS.step, "open": PROGRESS.open,
                 "ticks": [i for i in TICK_IDS if i in PROGRESS.ticks], "checks": dict(PROGRESS.checks)}
    if body.get("fresh") is True:
        _publish()
    return reply


ACTIONS = {"status": _status, "check": _check, "verify": _verify, "save": _save, "clear": _clear, "step": _step,
           "tick": _tick, "resume": _resume}


def handle(body, rpc, io=None):
    """(JSON-able reply, HTTP code). `rpc` is the panel's kodi() helper; `io` replaces the network and the clock in a test."""
    action = ACTIONS.get(body.get("action")) if isinstance(body.get("action"), str) else None
    if action is None:
        return {"ok": False, "error": "Неизвестное действие."}, 404
    try:
        return action(body, rpc, io or REAL), 200
    except Refused as e:
        return dict(e.extra, ok=False, error=e.message), e.code
