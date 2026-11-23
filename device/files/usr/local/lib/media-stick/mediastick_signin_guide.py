"""The device-code sign-in as an onboarding document (mediastick_onboarding): what the TV says and what the phone
says while the person does the three steps on the phone. Ready data in, a document out; no files, no clock.

The TV texts are English, the phone page's are Russian like the rest of that page. The steps are the same for
every service; only the account step and the last one differ in words.

The small line over the title is "<service> · sign in". YouTube asks for a code for each of the add-on's token types
in a row, and to the person that is the same action four times: so when more than one approval is coming the line says
"YouTube · approval 2 of 3" (one counter, on the phone and on the TV; `round` of `rounds` is what the writer counted:
the slots that still lack a token, minus those Google gave no code for), and the phone's hint says once why Google asks
again. The three steps below are the recipe of every approval, not a progress bar, so nothing counts them. A link that
has the code in it (the page opens with the code typed in) is told as such; a link that does not (a personal Google
client's google.com/device) says the code is typed there."""

FLOW = "signin"
TITLE = {"tv": "Continue on your phone", "phone": None}      # the phone's title says which service: see title()
HINT = {"tv": "The Media Stick page on your phone already shows the next step. Nothing to type here.",
        "phone": "ТВ попросил вход"}
HINT_TYPED = "The Media Stick page on your phone shows the next step. Type the code from the screen on that page."
OPEN_TYPED = ("Sign-in page opened, type the code", "Страница входа открыта, введите код с экрана")
ACTION_LABEL = "Открыть страницу входа"        # the phone's button: it opens the link with the code typed in
STEP_IDS = ("open", "account", "allow")
WHY_AGAIN = ("Google спрашивает разрешение отдельно для каждого способа, которым приставка обращается к YouTube. "
             "Каждый раз выберите тот же аккаунт и нажмите «Разрешить».")      # the phone's one line when several approvals come

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


NO_CHANNEL_HINT = {      # after a YouTube sign-in whose Google account has no channel (mediastick_ytchannel says "no")
    "tv": "This Google account has no YouTube channel, so Subscriptions, Watch later and Playlists will be empty.",
    "phone": "У этого аккаунта Google нет канала YouTube, поэтому подписки, «Смотреть позже» и плейлисты будут пустыми. "
             "Создайте канал в приложении YouTube.",
}


def known(service) -> bool:
    return service in GUIDES


def document(service, state, code="", link="", step=1, steps=1, channel="", prefilled=None, round=1, rounds=1):
    """The onboarding document of a sign-in of `service` that is `state` ("active" or how it ended), or None for a
    service this module has no words for. `code` and `link` are the active one's; `step`/`steps` are the add-on's own
    count of its codes and are not shown: `round` of `rounds` is (see mediastick_signin.publish), and only `rounds` above
    one puts a counter in the kicker. `prefilled` says whether the link carries the code (None: work it out from the
    link). `channel` is "no" when the signed-in account is known to have no YouTube channel: the finished document then
    carries a hint that says what will be empty."""
    guide = GUIDES.get(service)
    if guide is None:
        return None
    if prefilled is None:
        from mediastick_signin import carries      # here, not at the top: mediastick_signin imports this module
        prefilled = carries(code, link)
    typed = state == "active" and bool(code) and not prefilled
    again = state == "active" and isinstance(rounds, int) and rounds > 1
    texts = ((OPEN_TYPED,) if typed else guide["steps"][:1]) + tuple(guide["steps"][1:])
    parts = [{"id": ident, "tv": tv, "phone": phone} for ident, (tv, phone) in zip(STEP_IDS, texts)]
    hint = {"tv": HINT_TYPED, "phone": HINT["phone"]} if typed else dict(HINT)
    kicker = {"tv": f"{guide['name']} · sign in", "phone": f"{guide['name']} · вход"}
    if again:
        which = max(1, min(int(round), rounds))
        kicker = {"tv": f"{guide['name']} · Approval {which} of {rounds}",
                  "phone": f"{guide['name']} · подтверждение {which} из {rounds}"}
        hint["phone"] = WHY_AGAIN
    doc = {"flow": FLOW, "state": state, "kicker": kicker,
           "title": {"tv": TITLE["tv"], "phone": f"Войти в {guide['name']}"},
           "step": 1, "steps": parts, "hint": hint}
    if state == "active":
        doc["code"], doc["link"] = code, link
        if link:
            doc["action"] = {"kind": "link", "label": ACTION_LABEL, "url": link}
    else:
        tv, phone = RESULTS.get(state, RESULTS["failed"])
        doc["title"] = {"tv": tv, "phone": phone}
        doc["step"] = len(parts) if state == "done" else 1
        del doc["hint"]
        if state == "done" and channel == "no" and service == "youtube":
            doc["hint"] = dict(NO_CHANNEL_HINT)
    return doc
