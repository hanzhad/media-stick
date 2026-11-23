"""What the "Google key for YouTube" wizard says and how it reads what the owner pastes: pure data and functions
(no I/O, nothing happens on import). panel_ytkeys.py serves it, panel_ytkeys_ui.py draws it, the tests read it.

Four steps: the project and the API, the TV sign-in permission (a checklist the owner ticks), the API key, the TV
client. The phone's words are Russian; the words for the TV (step file and onboarding document) are English.
"""
import re
import urllib.parse

CONSOLE = "https://console.cloud.google.com/"
DOC_URL = "https://developers.google.com/youtube/v3/getting-started"
TV_TITLE, PHONE_TITLE = "Follow along on your phone", "Ключ Google для YouTube"
# Google publishes an External app only with a home page and a privacy policy on an authorized domain. These two
# pages (branch gh-pages of the project's repository) serve every owner: the phone offers them to copy.
PAGES_DOMAIN = "hanzhad.github.io"
HOME_URL = "https://hanzhad.github.io/media-stick/"
PRIVACY_URL = "https://hanzhad.github.io/media-stick/privacy.html"
COPIES = (("Главная страница (Application home page)", HOME_URL),
          ("Политика (Application privacy policy link)", PRIVACY_URL),
          ("Домен (Authorized domain)", PAGES_DOMAIN))
UNVERIFIED = ("При входе Google предупредит, что приложение не проверено: это ваш собственный проект. "
              "Нажмите «Дополнительно» → «Перейти на сайт TV».")
WARN = {"tv": "Publish it, or the TV gets signed out after 7 days.",
        "phone": "Без публикации вход на ТВ слетает через 7 дней."}

# "tv"/"tv_hint": what the TV shows (step file: title <= 80, hint <= 120); "title"/"hint": the phone's (hint <= 160)
STEPS = (
    {"id": "project", "title": "Проект и YouTube API", "tv": "Project and API",
     "tv_hint": "On your phone: open the Google link and tap Enable.",
     "url": CONSOLE + "flows/enableapi?apiid=youtube.googleapis.com", "button": "Открыть страницу Google",
     "hint": "Откройте ссылку, при необходимости создайте проект сверху, затем «Next» и «Enable».",
     "lines": ["Google покажет два шага: «Confirm project» → «Enable API». Если проекта нет — создайте его в списке "
               "проектов сверху (имя любое, например TV), затем «Next» и «Enable»."]},
    {"id": "consent", "title": "Разрешить вход с ТВ", "tv": "Allow TV sign-in",
     "tv_hint": "Get started › App name: TV › External › Create › Branding: two links › Audience › Publish app.",
     "url": CONSOLE + "auth/overview", "button": "Открыть страницу Google",
     "hint": "Начать → TV → внешняя аудитория → Создать; в «Брендинге» две ссылки и домен; Аудитория → Опубликовать.",
     "lines": ["Отмечайте пункты, которые уже сделали. Ссылки и домен для «Брендинга» — ниже, их можно скопировать."],
     "ticks": True, "warn": WARN["phone"], "copies": [{"label": l, "value": v} for l, v in COPIES]},
    {"id": "api_key", "title": "Ключ API", "tv": "API key",
     "tv_hint": "Create an API key and paste it on your phone.",
     "url": CONSOLE + "apis/credentials", "button": "Открыть страницу Google",
     "hint": "«Создать учётные данные» → «Ключ API», скопируйте ключ и вставьте его здесь.",
     "lines": ["Если в списке уже есть «API key 1» — Google создал его сам: откройте его и нажмите «Show key». "
               "Иначе «Создать учётные данные» → «Ключ API». Скопируйте ключ и вставьте его ниже.",
               "Лучше сразу ограничить ключ: в его настройках «API restrictions» → YouTube Data API v3 → «Save»."],
     "paste": True},
    {"id": "client", "title": "Клиент для ТВ", "tv": "TV client",
     "tv_hint": "Create a client of type TVs and Limited Input devices, paste its ID and secret on your phone.",
     "url": CONSOLE + "auth/clients/create", "button": "Открыть страницу Google",
     "hint": "Тип «TVs and Limited Input devices». Вставьте Client ID и secret или загрузите JSON клиента.",
     "lines": ["Создайте клиент типа «TVs and Limited Input devices». Google покажет Client ID и secret один раз: "
               "скопируйте оба (или нажмите «Download JSON») до того, как закроете окно.",
               "Вставьте их ниже по одному или загрузите скачанный JSON клиента.", UNVERIFIED], "paste": True},
)
STEP_TOTAL = len(STEPS)

# step 2's checklist: (id, the TV's chip, the phone's line); two rows on the TV: the app, then publishing it
TICKS = (
    ("start", "Get started", "Нажмите «Начать»"),
    ("name", "App name: TV", "Название — TV, почта — ваша"),
    ("external", "Audience: External", "Аудитория: «Внешняя»"),
    ("create", "Create", "Нажмите «Создать»"),
    ("links", "Branding: links", "«Брендинг»: две ссылки и домен ниже → «Сохранить»"),
    ("audience", "Audience", "Откройте «Аудитория»"),
    ("publish", "Publish app", "«Опубликовать приложение» → «Подтвердить»"),
)
TICK_IDS = tuple(t[0] for t in TICKS)
TICK_ROWS = (TICK_IDS[:4], TICK_IDS[4:])

# the three values: our name, the name in a check report, the TV's label
KINDS = (("api_key", "key", "API key"), ("client_id", "client_id", "Client ID"), ("client_secret", "secret", "Secret"))
CHECK_NAMES = tuple(k[1] for k in KINDS)

# what each pasted value looks like (JS takes the same sources); matched whole, after trimming and a length cap
PATTERNS = (
    ("api_key", r"^AIza[0-9A-Za-z_-]{35}$"),
    ("client_id", r"^[0-9]+-[0-9a-z]+\.apps\.googleusercontent\.com$"),
    ("client_secret", r"^GOCSPX-[0-9A-Za-z_-]{20,40}$"),
)
_COMPILED = tuple((kind, re.compile(src)) for kind, src in PATTERNS)
PASTE_MAX = 512
NOT_RECOGNISED = "Не похоже ни на ключ, ни на ID, ни на secret"


def detect(text):
    """(kind, value) for what was pasted, `value` trimmed; None when it is not a key, a client ID or a secret. The
    length is capped before anything is matched."""
    if not isinstance(text, str) or len(text) > PASTE_MAX * 2:
        return None
    value = text.strip()
    if not value or len(value) > PASTE_MAX:
        return None
    for kind, rx in _COMPILED:
        if rx.fullmatch(value):
            return kind, value
    return None


def matches(kind, value):
    d = detect(value)
    return bool(d) and d[0] == kind and d[1] == value


# ---- the step's words for the TV ------------------------------------------------------------------

def step_text(n):
    """(title, hint) of step n (1..STEP_TOTAL), the words the TV shows for it in the step file."""
    s = STEPS[n - 1]
    return s["tv"], s["tv_hint"]


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


def linked(item):
    return dict(item, intent=android_intent(item["url"]), safari=safari_link(item["url"]))


# ---- the onboarding document for the TV: no value in it, only words and states ----------------------

DOC_LIFETIME = 1800     # s: the TV forgets a document nobody has renewed


def chip_rows(ticks):
    """Step 2's chips: each one done (ticked), now (the first not ticked) or todo."""
    ticks = set(ticks)
    first = next((i for i in TICK_IDS if i not in ticks), None)
    chip = {i: t for i, t, _ in TICKS}
    return [[{"t": chip[i], "s": "done" if i in ticks else "now" if i == first else "todo"} for i in row]
            for row in TICK_ROWS]


def onboarding_doc(step, ticks, checks, now):
    """The document of schema v1 for step `step` (1..STEP_TOTAL). `checks` is {key, client_id, secret: True/False/None}."""
    s = STEPS[step - 1]
    doc = {"v": 1, "service": "youtube", "flow": "keys", "state": "active",
           "title": {"tv": TV_TITLE, "phone": PHONE_TITLE},
           "step": step, "steps": [{"id": x["id"], "tv": x["tv"], "phone": x["title"]} for x in STEPS],
           "hint": {"tv": s["tv_hint"], "phone": s["hint"]},
           "items": [{"id": kind if kind != "client_secret" else "secret", "label": label,
                      "s": "ok" if checks.get(name) is True else "wait"} for kind, name, label in KINDS],
           "expires": int(now) + DOC_LIFETIME, "updated": int(now)}
    if s.get("ticks"):
        doc["chips"] = chip_rows(ticks)
        doc["warn"] = dict(WARN)
    return doc
