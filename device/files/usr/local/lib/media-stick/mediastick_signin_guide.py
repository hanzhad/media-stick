"""The device-code sign-in as an onboarding document (mediastick_onboarding): what the TV says and what the phone
says while the person does the three steps on the phone. Ready data in, a document out; no files, no clock.

The TV texts are English, the phone page's are Russian like the rest of that page. The steps are the same for
every service; only the account step and the last one differ in words."""

FLOW = "signin"
TITLE = {"tv": "Continue on your phone", "phone": None}      # the phone's title says which service: see title()
HINT = {"tv": "The Media Stick page on your phone already shows the next step. Nothing to type here.",
        "phone": "ТВ попросил вход"}
ACTION_LABEL = "Открыть страницу входа"        # the phone's button: it opens the link with the code typed in
STEP_IDS = ("open", "account", "allow")

GUIDES = {
    "youtube": {
        "name": "YouTube",
        "steps": (("Sign-in page opened, code filled in", "Страница входа открыта, код уже вписан"),
                  ("Choose your Google account", "Выберите аккаунт Google"),
                  ("Tap Allow", "Нажмите «Разрешить» — телевизор войдёт сам")),
    },
    "sweettv": {
        "name": "SWEET.TV",
        "steps": (("Sign-in page opened, code filled in", "Страница входа открыта, код уже вписан"),
                  ("Sign in to your SWEET.TV account", "Войдите в аккаунт SWEET.TV"),
                  ("Confirm adding this TV", "Подтвердите добавление телевизора")),
    },
}

RESULTS = {      # state -> (TV title, phone title) of a sign-in that is over
    "done": ("Signed in", "Вход выполнен"),
    "failed": ("Sign-in did not work", "Войти не удалось"),
    "cancelled": ("Sign-in cancelled", "Вход отменён"),
}


def known(service) -> bool:
    return service in GUIDES


def document(service, state, code="", link="", step=1, steps=1):
    """The onboarding document of a sign-in of `service` that is `state` ("active" or how it ended), or None for a
    service this module has no words for. `code` and `link` are the active one's; `step`/`steps` count the codes
    the add-on asks for in a row (YouTube asks up to four), which the small line above the title says."""
    guide = GUIDES.get(service)
    if guide is None:
        return None
    n, total = int(step), int(steps)
    tv_kicker, phone_kicker = f"{guide['name']} · sign in", f"{guide['name']} · вход"
    if total > 1:
        tv_kicker, phone_kicker = f"{tv_kicker} · code {n} of {total}", f"{phone_kicker} · код {n} из {total}"
    parts = [{"id": ident, "tv": tv, "phone": phone} for ident, (tv, phone) in zip(STEP_IDS, guide["steps"])]
    doc = {"flow": FLOW, "state": state, "kicker": {"tv": tv_kicker, "phone": phone_kicker},
           "title": {"tv": TITLE["tv"], "phone": f"Войти в {guide['name']}"},
           "step": 1, "steps": parts, "hint": dict(HINT)}
    if state == "active":
        doc["code"], doc["link"] = code, link
        if link:
            doc["action"] = {"kind": "link", "label": ACTION_LABEL, "url": link}
    else:
        tv, phone = RESULTS.get(state, RESULTS["failed"])
        doc["title"] = {"tv": tv, "phone": phone}
        doc["step"] = len(parts) if state == "done" else 1
        del doc["hint"]
    return doc
