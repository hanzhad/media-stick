#!/usr/bin/env python3
"""Offline test of the device's one language (no Kodi, no device, no network): python3 tools/test-lang.py

The table and the file (mediastick_lang), the applier inside Kodi (script.media-stick.home, resources/lib/lang.py, with
the Kodi modules stubbed), the panel's API and page (panel_lang) and the pieces that wire them in. What the add-ons do
with the values on a real device is not tested here."""
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["MEDIASTICK_SCREEN_DIR"] = os.path.join(TMP, "screen")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"
sys.dont_write_bytecode = True

YT, SWEET = "plugin.video.youtube", "plugin.video.sweettv"


class Fake:
    """What the stubbed Kodi shows and does."""
    logs = []
    addons = {}            # add-on id -> {setting id: value}; an add-on that is not here does not exist
    refuse = False         # setSettingString says False
    props = {}             # Home window properties
    writes = []            # (add-on, setting, value) for every setSettingString


class StubAddon:
    def __init__(self, addon_id):
        self.id = addon_id

    def getSettingString(self, sid):
        return Fake.addons[self.id].get(sid, "")

    def setSettingString(self, sid, value):
        if Fake.refuse:
            return False
        Fake.addons[self.id][sid] = value
        Fake.writes.append((self.id, sid, value))
        return True


def addon_factory(addon_id=None):
    if addon_id is None:
        return types.SimpleNamespace(getAddonInfo=lambda key: ADDON)
    if addon_id not in Fake.addons:
        raise RuntimeError("unknown add-on")
    return StubAddon(addon_id)


class StubWindow:
    def __init__(self, wid):
        pass

    def getProperty(self, name):
        return Fake.props.get(name, "")

    def setProperty(self, name, value):
        Fake.props[name] = value


xbmc = types.ModuleType("xbmc")
xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 1, 2, 3
xbmc.log = lambda msg, level=2: Fake.logs.append(str(msg))
xbmc.executebuiltin = lambda cmd: None
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: TMP + "/"
xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.Dialog = lambda: types.SimpleNamespace(notification=lambda *a, **k: None)
xbmcgui.NOTIFICATION_INFO = "info"
xbmcgui.Window = StubWindow
xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = addon_factory
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui, xbmcaddon=xbmcaddon)
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

import mediastick_lang as ml  # noqa: E402
import panel_lang as pl  # noqa: E402
from resources.lib import lang as tvlang  # noqa: E402

# YouTube's own list of interface languages (snippet.hl of i18nLanguages), as the add-on's DEFAULT_LANGUAGES offline
# fallback carries it. The add-on's constants.py is not in this repository: this is the list as known, and
# tools/test-lang.py is not a proof against the device (the device check in the report is).
YT_KNOWN = {"ru", "uk", "en", "en-GB", "be", "pl", "hu", "de", "fr", "it", "es", "pt-PT", "nl", "cs", "sk", "sl", "hr",
            "bs", "sr", "sr-Latn", "bg", "mk", "ro", "el", "sq", "lt", "lv", "et", "fi", "sv", "da", "no", "is", "ca",
            "eu", "gl", "tr"}
EUROPE = {"ru", "uk", "en", "en_US", "be", "pl", "hu", "de", "fr", "it", "es", "pt", "nl", "cs", "sk", "sl", "hr", "bs",
          "sr", "bg", "mk", "ro", "el", "sq", "lt", "lv", "et", "fi", "sv", "da", "nb", "is", "ga", "cy", "mt", "ca",
          "eu", "gl", "tr"}


def clean():
    for name in (ml.FILE,):
        try:
            os.unlink(os.path.join(ml.DIR, name))
        except OSError:
            pass
    Fake.logs, Fake.props, Fake.writes, Fake.refuse = [], {}, [], False
    Fake.addons = {YT: {"youtube.language": "en", "youtube.region": "US"}, SWEET: {"countryCode": "hu"}}


class Table(unittest.TestCase):
    def test_every_european_language_and_english_us_and_russian_is_the_default(self):
        codes = [l.code for l in ml.LANGS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len({c.lower() for c in codes}), len(codes))
        self.assertTrue(EUROPE <= set(codes), EUROPE - set(codes))
        self.assertEqual(ml.DEFAULT, "ru")
        self.assertEqual(codes[:3], ["ru", "uk", "en"])                # first on the page

    def test_each_row_is_complete(self):
        for l in ml.LANGS:
            self.assertTrue(l.name.strip(), l.code)
            self.assertIn(l.yt, YT_KNOWN, l.code)
            self.assertRegex(l.yt, r"^[a-z]{2}(-[A-Za-z0-9]{2,4})?$")
            self.assertIn(l.sweet, ("ru", "uk", "en", "pl", "hu"), l.code)
            self.assertRegex(l.kodi, r"^resource\.language\.[a-z]{2}_[a-z]{2}(@latin)?$", l.code)

    def test_native_names(self):
        names = {l.code: l.name for l in ml.LANGS}
        self.assertEqual((names["ru"], names["uk"], names["en"], names["en_US"]),
                         ("Русский", "Українська", "English (UK)", "English (US)"))

    def test_the_content_languages(self):
        by = {l.code: l for l in ml.LANGS}
        self.assertEqual((by["en"].yt, by["en_US"].yt, by["ru"].yt, by["uk"].yt), ("en-GB", "en", "ru", "uk"))
        for code in ("ru", "uk", "en", "pl", "hu"):
            self.assertEqual(by[code].sweet, code)                       # localized by the SWEET.TV API
        self.assertEqual(by["en_US"].sweet, "en")
        self.assertEqual(by["be"].sweet, "ru")
        for code in ("de", "fr", "bg", "sr", "tr", "ga"):
            self.assertEqual(by[code].sweet, "en", code)

    def test_find_and_resolve(self):
        self.assertEqual(ml.find("UK").code, "uk")
        self.assertEqual(ml.find(" en_us ").code, "en_US")
        for bad in ("", "xx", "../x", None, 5, "ru\nuk"):
            self.assertIsNone(ml.find(bad), bad)
            self.assertEqual(ml.resolve(bad).code, "ru")

    def test_the_wishes_never_include_the_youtube_region(self):
        wish = ml.wanted(ml.resolve("de"))
        self.assertEqual(wish, {(YT, "youtube.language"): "de", (SWEET, "countryCode"): "en"})
        self.assertFalse([k for k in wish if "region" in k[1]])
        self.assertEqual(ml.public()[0], {"code": "ru", "name": "Русский"})


class File(unittest.TestCase):
    def setUp(self):
        clean()

    def test_missing_empty_and_unknown_read_as_russian(self):
        self.assertEqual(ml.read(), "ru")
        os.makedirs(ml.DIR, exist_ok=True)
        for text in ("", "\n", "klingon\n", "\x00\xff", "  \n"):
            with open(ml.path(), "w", encoding="utf-8", errors="ignore") as f:
                f.write(text)
            self.assertEqual(ml.read(), "ru", repr(text))

    def test_what_is_written_is_read_back_for_every_language(self):
        for l in ml.LANGS:
            self.assertTrue(ml.write(l.code), l.code)
            self.assertEqual(ml.read(), l.code)
            self.assertEqual(open(ml.path(), encoding="utf-8").read(), l.code + "\n")

    def test_the_file_is_world_readable_and_written_by_rename(self):
        ml.write("uk")
        self.assertEqual(stat.S_IMODE(os.stat(ml.path()).st_mode), 0o644)
        self.assertEqual(os.listdir(ml.DIR), ["language"])             # no temp file left
        with mock.patch.object(ml.os, "replace", side_effect=OSError("disk")):
            self.assertFalse(ml.write("de"))
        self.assertEqual(os.listdir(ml.DIR), ["language"])
        self.assertEqual(ml.read(), "uk")                              # the old choice stands

    def test_an_unknown_code_writes_nothing(self):
        ml.write("pl")
        for bad in ("xx", "", None, "ru\nuk"):
            self.assertFalse(ml.write(bad))
        self.assertEqual(ml.read(), "pl")

    def test_a_letter_case_is_spelled_the_tables_way(self):
        ml.write("EN_us")
        self.assertEqual(ml.read(), "en_US")


class Applier(unittest.TestCase):
    def setUp(self):
        clean()

    def test_it_writes_what_differs_and_only_that(self):
        ml.write("ru")
        self.assertEqual(sorted(tvlang.reconcile()), sorted([YT + ":youtube.language", SWEET + ":countryCode"]))
        self.assertEqual(Fake.addons[YT], {"youtube.language": "ru", "youtube.region": "US"})   # the region is left alone
        self.assertEqual(Fake.addons[SWEET], {"countryCode": "ru"})
        self.assertEqual(Fake.props["media-stick.lang"], "ru")
        Fake.writes.clear()
        self.assertEqual(tvlang.reconcile(), [])                       # nothing changed, nothing written
        self.assertEqual(Fake.writes, [])

    def test_a_missing_file_means_russian(self):
        tvlang.reconcile()
        self.assertEqual(Fake.addons[YT]["youtube.language"], "ru")
        self.assertEqual(Fake.props["media-stick.lang"], "ru")

    def test_another_language_follows_the_file(self):
        ml.write("be")
        tvlang.main([])
        self.assertEqual((Fake.addons[YT]["youtube.language"], Fake.addons[SWEET]["countryCode"]), ("be", "ru"))
        ml.write("de")
        tvlang.main([])
        self.assertEqual((Fake.addons[YT]["youtube.language"], Fake.addons[SWEET]["countryCode"]), ("de", "en"))
        self.assertEqual(Fake.props["media-stick.lang"], "de")

    def test_a_missing_addon_or_a_refusal_does_not_stop_the_rest(self):
        del Fake.addons[SWEET]
        self.assertEqual(tvlang.reconcile(), [YT + ":youtube.language"])
        clean()
        Fake.refuse = True
        self.assertEqual(tvlang.reconcile(), [])
        self.assertEqual(Fake.props["media-stick.lang"], "ru")
        self.assertTrue(any("refused" in line for line in Fake.logs))

    def test_a_broken_addon_is_logged_by_its_type_and_never_raised(self):
        with mock.patch.object(StubAddon, "getSettingString", side_effect=ValueError("secret")):
            self.assertEqual(tvlang.reconcile(), [])
        self.assertTrue(any("ValueError" in line for line in Fake.logs))
        self.assertFalse(any("secret" in line for line in Fake.logs))

    def run_default(self, argv):
        path = os.path.join(ADDON, "default.py")
        with mock.patch.object(sys, "argv", ["default.py"] + argv):
            exec(compile(open(path, encoding="utf-8").read(), path, "exec"), {"__name__": "__main__"})

    def test_default_py_dispatches_lang(self):
        ml.write("uk")
        self.run_default(["lang"])
        self.assertEqual(Fake.addons[YT]["youtube.language"], "uk")
        with mock.patch.object(tvlang, "main", side_effect=KeyError("x")):
            self.run_default(["lang"])                                 # an exception is logged, never raised
        self.assertTrue(any("lang failed" in line for line in Fake.logs))

    def test_the_service_reconciles_once_at_start(self):
        text = open(os.path.join(ADDON, "service.py"), encoding="utf-8").read()
        self.assertEqual(text.count("apply_language()"), 2)             # its definition and one call, before the loop
        self.assertLess(text.index("    apply_language()\n"), text.index("monitor = xbmc.Monitor()"))
        self.assertIn("lang.reconcile()", text)


class Fakekodi:
    def __init__(self, down=False):
        self.calls, self.down = [], down

    def __call__(self, method, params=None, timeout=3):
        if self.down:
            raise ConnectionRefusedError("kodi is off")
        self.calls.append((method, params))
        return "OK"


class PanelApi(unittest.TestCase):
    def setUp(self):
        clean()

    def test_a_known_code_is_written_and_kodi_is_asked_to_apply_it(self):
        k = Fakekodi()
        reply, code = pl.post("/api/lang", {"code": "uk"}, k)
        self.assertEqual((code, reply), (200, {"ok": True, "code": "uk", "name": "Українська", "applied": True}))
        self.assertEqual(ml.read(), "uk")
        self.assertEqual(k.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home", "params": ["lang"]})])

    def test_kodi_down_the_file_is_enough(self):
        reply, code = pl.post("/api/lang", {"code": "de"}, Fakekodi(down=True))
        self.assertEqual((code, reply["ok"], reply["applied"]), (200, True, False))
        self.assertEqual(ml.read(), "de")

    def test_nonsense_is_refused_and_nothing_changes(self):
        ml.write("pl")
        k = Fakekodi()
        for body in ({"code": "xx"}, {"code": ""}, {"code": None}, {"code": 7}, {}, [], "uk", {"code": "../etc"}):
            reply, code = pl.post("/api/lang", body, k)
            self.assertEqual((code, reply["ok"]), (400, False), body)
        self.assertEqual(pl.post("/api/other", {"code": "uk"}, k)[1], 404)
        self.assertEqual((ml.read(), k.calls), ("pl", []))

    def test_a_disk_that_refuses_is_a_calm_error_and_kodi_is_not_asked(self):
        k = Fakekodi()
        with mock.patch.object(ml, "write", return_value=False):
            reply, code = pl.post("/api/lang", {"code": "uk"}, k)
        self.assertEqual((code, reply["ok"]), (500, False))
        self.assertEqual(k.calls, [])

    def test_the_status_carries_the_code(self):
        ml.write("hu")
        self.assertEqual(pl.current(), "hu")


class PageAndWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("panel_lang_page", PANEL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.panel = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.panel)
        cls.page = cls.panel.PAGE
        cls.source = open(PANEL, encoding="utf-8").read()

    def test_the_settings_list_has_the_row_and_the_page_is_there(self):
        lst = self.page.split('id="t-setlist"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<button class="srow" data-sp="lang">', lst)
        self.assertIn('<span class="sname">Язык</span><span class="sval" id="sv-lang">', lst)
        self.assertIn('<section id="t-lang" data-tab="settings" data-spage="lang" class="hide">', self.page)
        self.assertIn("lang:'language'", self.page)
        self.assertIn("lang:'t-lang'", self.page)
        self.assertIn("v('sv-lang',window.langRowText?langRowText(s):'')", self.page)

    def test_the_page_lists_the_languages_by_native_name_with_ru_uk_en_first(self):
        table = json.loads(re.search(r"const LG=(\[.*?\]);\n", self.page, re.S).group(1))
        self.assertEqual(table, ml.public())
        self.assertEqual([t["name"] for t in table[:3]], ["Русский", "Українська", "English (UK)"])
        self.assertIn("aria-current", self.page)
        self.assertIn("toast('Язык: '+l.name)", self.page)
        self.assertIn("api('/api/lang',{code:l.code})", self.page)
        self.assertEqual(re.findall(r"@@\w+@@", self.page.replace("@@PAGE_VER@@", "")), [])

    def test_inject_raises_for_a_missing_marker(self):
        base = ("<x>@@LANG_ROW@@@@LANG_SECTION@@@@LANG_TAIL@@</x>")
        self.assertNotIn("@@", pl.inject(base))
        for marker in ("@@LANG_ROW@@", "@@LANG_SECTION@@", "@@LANG_TAIL@@"):
            with self.assertRaises(ValueError):
                pl.inject(base.replace(marker, ""))

    def test_the_panel_routes_and_reports_it(self):
        self.assertIn('s["lang"] = panel_lang.current()', self.source)
        self.assertIn("if p == panel_lang.PATH:\n            body, code = panel_lang.post(p, b, kodi)", self.source)
        self.assertIn("PAGE = panel_lang.inject(PAGE)", self.source)

    def test_the_state_directory_is_made_at_boot(self):
        conf = open(os.path.join(ROOT, "device", "files", "etc", "tmpfiles.d", "media-stick.conf"), encoding="utf-8").read()
        self.assertIn("d /var/lib/media-stick/prefs 0755 media media -", conf.splitlines())

    def test_the_scripts_are_balanced(self):
        spec = importlib.util.spec_from_file_location("tabs", os.path.join(ROOT, "tools", "test-panel-tabs.py"))
        tabs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tabs)
        for script in re.findall(r"<script>(.*?)</script>", self.page, re.S):
            self.assertIsNone(tabs.unbalanced(script))


if __name__ == "__main__":
    unittest.main(verbosity=2)
