"""The «Язык» part of the panel: one language for the whole stick, chosen on the phone.

POST /api/lang {"code": ...} checks the code against the table (mediastick_lang), writes the language file and asks
the launcher add-on in Kodi to apply it (RunScript(script.media-stick.home,lang), through Addons.ExecuteAddon like
the accounts do). A Kodi that is down is no error: the file is the choice and the add-on's service applies it at its
start. The language travels to the page in the status (`lang`); the table and the page's markup, style and script
(panel_lang_ui.py) are put into the page at its three @@LANG_...@@ markers.

Standard library only, nothing happens on import.
"""
import json

import mediastick_lang as lang
import panel_lang_ui as ui

PATH = "/api/lang"
LAUNCHER = "script.media-stick.home"
MARKERS = {"@@LANG_ROW@@": ui.ROW, "@@LANG_SECTION@@": ui.SECTION}
TAIL_MARKER = "@@LANG_TAIL@@"


def current():
    """The code of the device's language, for the status."""
    return lang.read()


def post(path, body, rpc):
    """POST /api/lang: (JSON-able reply, HTTP code). The panel has already checked the X-Panel header and the Host."""
    if path != PATH:
        return {"ok": False, "error": "Неизвестное действие."}, 404
    chosen = lang.find(body.get("code")) if isinstance(body, dict) else None
    if chosen is None:
        return {"ok": False, "error": "Такого языка нет."}, 400
    if not lang.write(chosen.code):
        return {"ok": False, "error": "приставка не дала записать выбор."}, 500
    applied = True
    try:
        rpc("Addons.ExecuteAddon", {"addonid": LAUNCHER, "params": ["lang"]})
    except (OSError, ValueError):
        applied = False        # Kodi is down: the file is enough, the add-on's service applies it when Kodi starts
    return {"ok": True, "code": chosen.code, "name": chosen.name, "applied": applied}, 200


def inject(page):
    """The page with the language row, its page and its script put at their markers; a marker the page lacks raises
    ValueError (a page that lost the language setting without a word is worse than one that does not start)."""
    for marker in list(MARKERS) + [TAIL_MARKER]:
        if marker not in page:
            raise ValueError("the page has no %s: the language setting cannot be put in" % marker)
    for marker, text in MARKERS.items():
        page = page.replace(marker, text, 1)
    return page.replace(TAIL_MARKER, ui.TAIL.replace("@@LANGS@@", json.dumps(lang.public(), ensure_ascii=False)), 1)
