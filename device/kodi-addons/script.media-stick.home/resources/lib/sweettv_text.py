"""SWEET.TV app: the words on the screen. Ready data in, strings out; nothing here touches Kodi.

The row of key hints, the status card (loading, empty, error), the steps for signing in on the phone, and the
account chip. What is said about a channel is in sweettv_view.
"""
from typing import NamedTuple

WAIT_LIMIT = 300                # s without a channel list after sign-in before it is called a failure
PHONE_TAB = "Аккаунты"          # the tab's name on the phone page (that page is in Russian)
ACCENT, RED, DIM = "FFFFC857", "FFFF6B5E", "99FFFFFF"      # the skin's amber, an error red, a muted white


def hint_line(numbered, archive=False) -> str:
    """The key hints at the top: each key in the accent colour, then what it does. The number keys are left out
    when no channel has a number (they would do nothing), the archive keys when no channel has an archive."""
    keys = [("OK", "Watch"), ("Menu", "Favourite")] + ([("0-9", "Channel number")] if numbered else [])
    keys += [("Up", "Guide and continue")] if archive else []
    return "        ".join(f"[COLOR {ACCENT}]{key}[/COLOR]  {what}" for key, what in keys)


def chip(demo, signed) -> str:
    """The account chip top left. "Demo" only when the screen runs as the demo."""
    return "Demo" if demo else "Signed in" if signed else "Sign in"


# ---- signed out: sign in on the phone --------------------------------------------------------

def short_url(url) -> str:
    """The phone page's address as people type it: no scheme, no closing slash."""
    return url.split("://", 1)[-1].rstrip("/") if url else ""


def phone_steps(url) -> dict:
    """Window properties of the sign-in card: the three steps. `url` is the phone page ("" when offline)."""
    shown = short_url(url)
    return {"phone_step1": "1    On your phone, open" if shown else "1    Connect the stick to a network first",
            "phone_url": shown,
            "phone_step2": f"2    Tab  {PHONE_TAB}  >  SWEET.TV",     # ">", not an arrow: the skin's font has no glyph for it
            "phone_step3": "3    Sign in there: the channels appear here by themselves."}


# ---- signed in, nothing to show --------------------------------------------------------------

class Status(NamedTuple):
    kind: str                   # loading | empty | error
    glyph: str                  # the badge's one character
    tint: str                   # the badge's colour
    title: str
    text: str
    note: str                   # the last line: what happens next


ERRORS = {
    "service": "SWEET.TV answered with an error. Check the internet connection and that the account is signed in.",
    "format": "The channel list is not in the shape this screen knows. SWEET.TV may have changed it.",
    "unreadable": "The channel list cannot be read. SWEET.TV writes it again every 15 minutes.",
    "missing": "SWEET.TV has not delivered the channel list for a long while. Check the internet connection.",
}
TRYING = "Trying again every few seconds. Back returns to Home."


def status(error, has_file, unreadable, waited) -> Status:
    """What a signed-in screen without channels says. `error` is the parser's verdict on the file ("" when fine),
    `waited` the seconds this screen has been waiting for a first list."""
    if error or ((not has_file or unreadable) and waited > WAIT_LIMIT):
        key = error if error else "unreadable" if has_file else "missing"
        return Status("error", "!", RED, "Cannot load the channels", ERRORS.get(key, ERRORS["format"]), TRYING)
    if not has_file or unreadable:
        return Status("loading", "…", ACCENT, "Loading channels",
                      "SWEET.TV is fetching the channel list. After signing in this takes a minute or two.",
                      "Checking again every few seconds. Back returns to Home.")
    return Status("empty", "0", DIM, "No channels yet",
                  "The channel list is empty. SWEET.TV may still be loading it, or the account has none.",
                  "Back returns to Home.")


# ---- translations ----------------------------------------------------------------------------
# Every string a person sees goes through tr(msgid): the msgid is the English text as written in the code, the
# translations are here, in one place. Until the language setting exists tr() answers in Russian where it has a
# translation and in English where it has none; mediastick_lang.text(msgid, lang) will replace it without a change
# in the callers.

LANG = "ru"
TEXT = {
    "Live": {"ru": "В эфире", "uk": "В ефірі"},
    "Back to live": {"ru": "К эфиру", "uk": "До ефіру"},
    "No archive for this channel": {"ru": "Архива у этого канала нет", "uk": "Архіву в цього каналу немає"},
    "SWEET.TV is not available on this device.": {"ru": "SWEET.TV недоступен на этом устройстве.",
                                                  "uk": "SWEET.TV недоступний на цьому пристрої."},
    "Wrong channel.": {"ru": "Неверный канал.", "uk": "Невірний канал."},
    "Wrong programme.": {"ru": "Неверная передача.", "uk": "Невірна передача."},
    "This programme is not in the channel's guide.": {"ru": "Такой передачи нет в программе канала.",
                                                      "uk": "Такої передачі немає в програмі каналу."},
    "This programme is not in the archive.": {"ru": "Этой передачи нет в архиве.",
                                              "uk": "Цієї передачі немає в архіві."},
    "Wrong start place.": {"ru": "Неверное место начала.", "uk": "Невірне місце початку."},
    "An archived programme is not playing.": {"ru": "Сейчас играет не архив.", "uk": "Зараз грає не архів."},
    "This channel is not in the list.": {"ru": "Такого канала нет в списке.", "uk": "Такого каналу немає у списку."},
}


def tr(msgid) -> str:
    """The text for a person: the translation in LANG, else the English msgid itself."""
    return TEXT.get(msgid, {}).get(LANG) or msgid
