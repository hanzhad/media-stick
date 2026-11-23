"""The "Google keys for YouTube" wizard of the panel, server side: what the steps say, checking a key with
Google, and handing the values to Kodi (see mediastick_ytkeys for the hand-over and the rules for values).

POST /api/accounts/ytkeys {"action": "status" | "check" | "save" | "clear" | "step", ...}. The panel has already
checked the X-Panel header and the Host. Values are never logged and never sent back: a reply carries the last four
characters of the key and nothing else of them. "step" ({"step": 0..6}) says where the owner is in the wizard: the
TV reads it from a file that holds no value (mediastick_ytkeys.write_step). The page's markup lives in
panel_ytkeys_ui.py.

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

import mediastick_ytkeys as keys

LAUNCHER = "script.media-stick.home"
CHECK_URL = "https://www.googleapis.com/youtube/v3/videos"
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


# ---- the steps the page shows -----------------------------------------------------------------

CONSOLE = "https://console.cloud.google.com/"
DOC_URL = "https://developers.google.com/youtube/v3/getting-started"
STEPS = (
    {"title": "Создайте проект", "url": CONSOLE + "projectcreate", "button": "Открыть Google Cloud",
     "hint": "Создайте проект в Google Cloud: имя любое, например «TV».",
     "lines": ["Войдите тем аккаунтом Google, каким хотите.",
               "Назовите проект как угодно, например «TV», и создайте его."]},
    {"title": "Включите YouTube Data API v3", "url": CONSOLE + "apis/library/youtube.googleapis.com",
     "button": "Открыть YouTube Data API v3",
     "hint": "Выберите свой проект и нажмите «Включить» у YouTube Data API v3.",
     "lines": ["Вверху выберите свой проект и нажмите «Включить»."]},
    {"title": "Настройте экран согласия", "url": CONSOLE + "apis/credentials/consent",
     "button": "Открыть экран согласия",
     "hint": "Тип «Внешний», свою почту в тестовые, потом «In production».",
     "lines": ["Тип — «Внешний» (External). Название любое, почта — ваша.",
               "В «Тестовые пользователи» добавьте свою почту Google.",
               "Потом опубликуйте приложение («In production»). Иначе вход слетает через 7 дней."]},
    {"title": "Создайте ключ API", "url": CONSOLE + "apis/credentials", "button": "Открыть учётные данные",
     "hint": "Создайте ключ API и вставьте его на телефоне.",
     "lines": ["Нажмите «Создать учётные данные» → «Ключ API».", "Скопируйте ключ и вставьте сюда:"],
     "fields": ["api_key"]},
    {"title": "Создайте клиент OAuth", "url": CONSOLE + "apis/credentials/oauthclient",
     "button": "Открыть создание клиента",
     "hint": "Клиент OAuth для ТВ: вставьте Client ID и Client secret на телефоне.",
     "lines": ["Тип — «Телевизоры и устройства с ограниченным вводом» (TVs and Limited Input devices).",
               "Скопируйте Client ID и Client secret и вставьте сюда:"],
     "fields": ["client_id", "client_secret"]},
)
# the last step is the form; it has no link
FORM = {"title": "Проверим и сохраним", "hint": "Проверьте три значения на телефоне и нажмите «Проверить и сохранить»."}
STEP_TOTAL = len(STEPS) + 1


def step_text(n):
    """(title, hint) of step n (1..STEP_TOTAL), the words the TV shows for it."""
    s = STEPS[n - 1] if n <= len(STEPS) else FORM
    return s["title"], s["hint"]


# ---- opening a link outside the panel: pure ---------------------------------------------------------
# The page opens a step's link in the phone's browser. Which way depends on the phone (the page finds it out):
# Android gets an intent link (the browser takes over; if nothing can, the https page opens as it is); anywhere
# else the link itself opens in a new tab; on an iPhone "Открыть в Safari" is the x-safari-https spare.

def _https_rest(url):
    """What follows "https://" in `url` when it can stand inside another link scheme; else ''."""
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 512:
        return ""
    rest = url[len("https://"):]
    return rest if rest and all(33 <= ord(c) <= 126 and c not in ";#<>\"'\\" for c in rest) else ""


def android_intent(url):
    """Chrome's intent link that views `url` in a browser, falling back to the https page; '' for a url that cannot be one."""
    rest = _https_rest(url)
    if not rest:
        return ""
    return ("intent://%s#Intent;scheme=https;action=android.intent.action.VIEW;S.browser_fallback_url=%s;end"
            % (rest, urllib.parse.quote(url, safe="")))


def safari_link(url):
    """Safari's x-safari-https link for `url`; '' for a url that cannot be one."""
    return "x-safari-" + url if _https_rest(url) else ""


def _linked(item):
    return dict(item, intent=android_intent(item["url"]), safari=safari_link(item["url"]))


OPEN_HINT = "Откроется в браузере. Вернитесь в пульт и нажмите «Готово»."
BACK_HINT = "Вернитесь в пульт и нажмите «Готово»."
STANDALONE_HINT = "Если страница открылась внутри пульта, нажмите «Скопировать ссылку» и вставьте её в браузер."
IOS_STANDALONE_HINT = ("Ссылки открываются внутри приложения. Чтобы открывать их в Safari, откройте пульт в Safari, "
                       "а не с экрана «Домой». Вернуться сюда можно кнопкой «Готово» вверху.")
# the page draws these from this one description, the last step (the form) after the steps above
WIZARD = {
    "steps": tuple(_linked(s) for s in STEPS),
    "form": FORM,
    "fields": [{"name": n, "label": keys.LABELS[n], "max": keys.LIMITS[n], "secret": n == "client_secret"}
               for n in keys.SETTINGS],
    "doc": _linked({"url": DOC_URL, "button": "Описание от Google"}),
    "note": "Интерфейс Google меняется. Если надписи отличаются, ищите похожие.",
    "texts": {"open": OPEN_HINT, "back": BACK_HINT, "standalone": STANDALONE_HINT, "ios_standalone": IOS_STANDALONE_HINT,
              "copy": "Скопировать ссылку", "copied": "Ссылка скопирована", "safari": "Открыть в Safari",
              "resume": "Продолжить настройку ключей (шаг %d из %d)"},
}


# ---- Google's verdict on a key: pure ------------------------------------------------------------

INVALID, DISABLED, BLOCKED, QUOTA, NET, OTHER, OK = "invalid", "disabled", "blocked", "quota", "net", "other", "ok"
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
    DISABLED: "Ключ верный, но в проекте не включён YouTube Data API v3. Включите его (шаг 2) и через минуту проверьте снова.",
    BLOCKED: "У ключа есть ограничения. В Google Cloud откройте этот ключ и уберите их "
             "или разрешите ему YouTube Data API v3. Потом проверьте снова.",
    NET: "Не удалось связаться с Google. Проверьте интернет на приставке и попробуйте ещё раз.",
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


def hint(verdict, code=0):
    return HINTS.get(verdict) or "Google ответил ошибкой%s. Попробуйте позже." % (" (код %d)" % code if code else "")


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


def _verdict_reply(verdict, code):
    return {"check": verdict, "works": verdict in SAVABLE, "message": hint(verdict, code)}


# ---- the actions ---------------------------------------------------------------------------------

def _status(body, rpc, io):
    return dict(keys.describe(keys.read_settings()), ok=True)


def _check(body, rpc, io):
    stored = keys.read_settings()
    if not keys.describe(stored)["set"]:
        raise Refused("Ключ не задан.", 409)
    return dict(_verdict_reply(*check_key(stored["api_key"], io)), ok=True)


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
            raise Refused(KODI_DOWN, 503)
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


def _save(body, rpc, io):
    try:
        values = keys.clean_values(body)
    except keys.Invalid as e:
        raise Refused(str(e))
    verdict, code = ("skipped", 0) if body.get("skip_check") is True else check_key(values["api_key"], io)
    reply = _verdict_reply(verdict, code) if verdict != "skipped" else {"check": verdict, "works": None, "message": ""}
    if verdict != "skipped" and verdict not in SAVABLE:
        raise Refused(reply["message"], 422, {"check": verdict})
    result = _hand_over("save", values, rpc, io)
    keys.clear_step()          # the wizard is finished: the TV has no step to show
    return dict(reply, ok=True, saved=True, last4=result["last4"])


def _clear(body, rpc, io):
    _hand_over("clear", None, rpc, io)
    return {"ok": True, "cleared": True}


def _step(body, rpc, io):
    """Where the owner is in the wizard (1..STEP_TOTAL), or 0 when it is closed or finished. Nothing from the body
    but the number goes anywhere: the words of the step are this module's own."""
    n = body.get("step")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= STEP_TOTAL:
        raise Refused("Неверный номер шага.")
    try:
        if n:
            keys.write_step(n, STEP_TOTAL, *step_text(n))
        else:
            keys.clear_step()
    except (OSError, ValueError):
        raise Refused("Не получилось записать шаг.", 500)
    return {"ok": True, "step": n}


ACTIONS = {"status": _status, "check": _check, "save": _save, "clear": _clear, "step": _step}


def handle(body, rpc, io=None):
    """(JSON-able reply, HTTP code). `rpc` is the panel's kodi() helper; `io` replaces the network and the clock in a test."""
    action = ACTIONS.get(body.get("action")) if isinstance(body.get("action"), str) else None
    if action is None:
        return {"ok": False, "error": "Неизвестное действие."}, 404
    try:
        return action(body, rpc, io or REAL), 200
    except Refused as e:
        return dict(e.extra, ok=False, error=e.message), e.code
