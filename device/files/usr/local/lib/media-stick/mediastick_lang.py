"""The device's one language: which language the owner chose for the whole stick.

The choice is one line in /var/lib/media-stick/prefs/language (a code from LANGS; missing or unknown reads as
"ru"), written whole and renamed into place. The phone panel writes it and asks Kodi's launcher add-on to apply it
(script.media-stick.home, resources/lib/lang.py); the add-on's service applies it once at start, so a file written
while Kodi was down is enough. Standard library only: it imports the same in Kodi's Python, in the panel and in a test.

What each language means for the add-ons that follow it:
  yt     YouTube's `hl` (interface and content language), as the add-on's own language list names it
  sweet  SWEET.TV's country code: ru, uk, en, pl, hu are localized by its API; be falls back to ru, the rest to en
  kodi   the Kodi language add-on of the language (used by a later phase; none of this phase touches Kodi's own language)
"""
import os
import tempfile
from collections import namedtuple

DIR = os.environ.get("MEDIASTICK_PREFS_DIR", "/var/lib/media-stick/prefs")
FILE = "language"
DEFAULT = "ru"

Lang = namedtuple("Lang", "code name yt sweet kodi")

SWEET_OWN = ("ru", "uk", "en", "pl", "hu")      # the languages SWEET.TV's API localizes; be reads as ru, the rest as en


def _sweet(code):
    base = code.split("_")[0]
    return base if base in SWEET_OWN else "ru" if base == "be" else "en"


def _lang(code, name, yt, kodi):
    return Lang(code, name, yt, _sweet(code), "resource.language." + kodi)


# ru, uk, en first (the phone shows them first), then the other languages of Europe. yt: a code YouTube knows;
# Irish, Welsh and Maltese have none, they get en-GB.
LANGS = (
    _lang("ru", "Русский", "ru", "ru_ru"),
    _lang("uk", "Українська", "uk", "uk_ua"),
    _lang("en", "English (UK)", "en-GB", "en_gb"),
    _lang("en_US", "English (US)", "en", "en_us"),
    _lang("be", "Беларуская", "be", "be_by"),
    _lang("pl", "Polski", "pl", "pl_pl"),
    _lang("hu", "Magyar", "hu", "hu_hu"),
    _lang("de", "Deutsch", "de", "de_de"),
    _lang("fr", "Français", "fr", "fr_fr"),
    _lang("it", "Italiano", "it", "it_it"),
    _lang("es", "Español", "es", "es_es"),
    _lang("pt", "Português", "pt-PT", "pt_pt"),
    _lang("nl", "Nederlands", "nl", "nl_nl"),
    _lang("cs", "Čeština", "cs", "cs_cz"),
    _lang("sk", "Slovenčina", "sk", "sk_sk"),
    _lang("sl", "Slovenščina", "sl", "sl_si"),
    _lang("hr", "Hrvatski", "hr", "hr_hr"),
    _lang("bs", "Bosanski", "bs", "bs_ba"),
    _lang("sr", "Српски", "sr", "sr_rs"),
    _lang("sr_Latn", "Srpski (latinica)", "sr-Latn", "sr_rs@latin"),
    _lang("bg", "Български", "bg", "bg_bg"),
    _lang("mk", "Македонски", "mk", "mk_mk"),
    _lang("ro", "Română", "ro", "ro_ro"),
    _lang("el", "Ελληνικά", "el", "el_gr"),
    _lang("sq", "Shqip", "sq", "sq_al"),
    _lang("lt", "Lietuvių", "lt", "lt_lt"),
    _lang("lv", "Latviešu", "lv", "lv_lv"),
    _lang("et", "Eesti", "et", "et_ee"),
    _lang("fi", "Suomi", "fi", "fi_fi"),
    _lang("sv", "Svenska", "sv", "sv_se"),
    _lang("da", "Dansk", "da", "da_dk"),
    _lang("nb", "Norsk bokmål", "no", "nb_no"),
    _lang("is", "Íslenska", "is", "is_is"),
    _lang("ga", "Gaeilge", "en-GB", "ga_ie"),
    _lang("cy", "Cymraeg", "en-GB", "cy_gb"),
    _lang("mt", "Malti", "en-GB", "mt_mt"),
    _lang("ca", "Català", "ca", "ca_es"),
    _lang("eu", "Euskara", "eu", "eu_es"),
    _lang("gl", "Galego", "gl", "gl_es"),
    _lang("tr", "Türkçe", "tr", "tr_tr"),
)
_BY_CODE = {l.code.lower(): l for l in LANGS}


def find(code):
    """The language of `code` (any letter case), or None."""
    return _BY_CODE.get(code.strip().lower()) if isinstance(code, str) else None


def resolve(code):
    """The language of `code`; Russian for a missing or unknown one."""
    return find(code) or _BY_CODE[DEFAULT]


def path():
    return os.path.join(DIR, FILE)


def read():
    """The code in the file, as the table spells it; "ru" when the file is missing, empty or names nothing known."""
    try:
        with open(path(), encoding="utf-8") as f:
            line = f.readline()
    except (OSError, ValueError):
        line = ""
    return resolve(line).code


def write(code):
    """Make `code` the device's language: False (nothing written) when the table does not know it or the disk refuses."""
    lang = find(code)
    if lang is None:
        return False
    tmp = None
    try:
        os.makedirs(DIR, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(lang.code + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path())
        return True
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def wanted(lang):
    """What the language asks of the add-ons: {(add-on id, setting id): value}. YouTube's region is not here: a
    language is not a country, and the owner's region stays as it is."""
    return {("plugin.video.youtube", "youtube.language"): lang.yt,
            ("plugin.video.sweettv", "countryCode"): lang.sweet}


def public():
    """The table as the phone page needs it: [{code, name}] in the order shown."""
    return [{"code": l.code, "name": l.name} for l in LANGS]
