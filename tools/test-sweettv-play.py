#!/usr/bin/env python3
"""Offline test of what the SWEET.TV overlay hands to Kodi when a stream is played, and of the language it asks in (no Kodi,
no device, no network): python3 tools/test-sweettv-play.py

Upstream resolves a stream with a bare item: Kodi's title is empty and its label is the channel number, so the phone showed
"1226" for a channel. The overlay names the item after the channel (an archive: after the programme, the channel as its
show). Upstream also asks SWEET.TV in Hungarian unless the setting was changed: the overlay asks in Russian, unless the
person chose a language (a Hungarian chosen on purpose stays)."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in device/skin-overlay

import importlib.util  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sweettv_token_stubs", os.path.join(HERE, "test-sweettv-token.py"))
stubs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stubs
spec.loader.exec_module(stubs)

NOW = 1_800_000_000
LIST = {"status": "OK", "list": [
    {"id": 5, "name": "Первый канал", "epg": [
        {"id": 50, "time_start": NOW - 7200, "time_stop": NOW - 3600, "text": "Утро"},
        {"id": 51, "time_start": NOW - 3600, "time_stop": NOW + 3600, "text": "Холостяк"}]},
    {"id": 6, "name": "Второй", "epg": []}]}
STREAM = {"result": "OK", "http_stream": {"host": {"address": "cdn.example"}, "url": "/live.m3u8"}, "scheme": "HTTP_HLS"}


class Item:
    """xbmcgui.ListItem as far as naming goes."""
    def __init__(self):
        self.label, self.info = None, None

    def setLabel(self, label):
        self.label = label

    def setInfo(self, kind, info):
        self.info = (kind, info)


class PlayHelper(stubs.StaleHelper):
    channel_list = LIST

    def get_channel_list(self):
        if isinstance(self.channel_list, Exception):
            raise self.channel_list
        return self.channel_list

    def request_sess(self, url, method="get", headers=None, **kw):
        if url.endswith("TvService/OpenStream.json"):
            self.opened = kw.get("data")
            return STREAM
        return super().request_sess(url, method, headers, **kw)

    def playstream(self, url, lic, protocol, drm, flags=True, subs=None, vod=False):
        self.resolve(Item())

    def ffmpeg_player(self, url):
        self.resolve(Item())

    def resolve(self, item):
        self.resolved.append(item)
        self.plugin.setResolvedUrl(1, True, listitem=item)


def kodi_plugin(log):
    return types.SimpleNamespace(setResolvedUrl=lambda handle, ok, listitem=None: log.append((handle, ok, listitem)))


class Naming(unittest.TestCase):
    def play(self, videoid, channel_list=None, player="ffmpeg", now=None):
        log = []
        plugin = kodi_plugin(log)
        original = plugin.setResolvedUrl
        helper = type("H", (PlayHelper,), {"resolved": [], "channel_list": LIST if channel_list is None else channel_list, "plugin": plugin})
        sweet = stubs.load_sweettv(helper_class=helper, xbmcplugin=plugin)
        stubs.Settings.values.update(logged=True, bearer="Bearer x", playerType=player)
        if now:
            sweet.time = types.SimpleNamespace(time=lambda: now)
        sweet.playvid(videoid)
        self.assertIs(plugin.setResolvedUrl, original, "the wrapper is taken off again")
        return log, helper.resolved

    def test_live_is_named_after_the_channel_with_the_programme_as_its_plot(self):
        for player in ("ffmpeg", "inputstream"):
            log, items = self.play("5|null", player=player)
            self.assertEqual(len(log), 1)
            item = log[0][2]
            self.assertEqual(item.label, "Первый канал")
            self.assertEqual(item.info[0], "video")
            self.assertEqual(item.info[1]["title"], "Первый канал")
            self.assertEqual(item.info[1]["tvshowtitle"], "Первый канал")

    def test_the_programme_on_now_is_the_plot_of_a_live_item(self):
        log, _ = self.play("5|null", now=NOW)
        self.assertEqual(log[0][2].info[1].get("plot"), "Холостяк")

    def test_an_archived_programme_is_named_after_the_programme_with_the_channel_as_its_show(self):
        log, _ = self.play("5|50")
        item = log[0][2]
        self.assertEqual(item.label, "Утро")
        self.assertEqual(item.info[1], {"title": "Утро", "tvshowtitle": "Первый канал"})

    def test_a_programme_the_list_does_not_have_is_named_after_the_channel(self):
        log, _ = self.play("5|999")
        self.assertEqual(log[0][2].label, "Первый канал")

    def test_an_unknown_channel_or_no_list_leaves_the_item_as_upstream_made_it(self):
        for videoid, channel_list in (("77|null", LIST), ("5|null", OSError("no file")), ("5|null", {}), ("5|null", [])):
            log, _ = self.play(videoid, channel_list=channel_list)
            self.assertEqual(len(log), 1)
            self.assertIsNone(log[0][2].label)
            self.assertIsNone(log[0][2].info)


class Language(unittest.TestCase):
    """What SWEET.TV is asked in: the language the owner chose for the box (mediastick_lang, the phone's «Язык») when there
    is one, else the add-on's own setting, with upstream's untouched Hungarian read as Russian."""

    def setUp(self):
        import mediastick_lang
        self.lang = mediastick_lang
        self.prefs = tempfile.mkdtemp()
        patch = mock.patch.object(mediastick_lang, "DIR", self.prefs)       # never the real /var/lib/media-stick
        patch.start()
        self.addCleanup(patch.stop)

    def choose(self, code):
        self.assertTrue(self.lang.write(code))

    def sweet(self, text, stored="hu"):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "settings.xml")
        if text is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

        class Helper(stubs.StaleHelper):
            def __init__(self, *a):
                super().__init__(*a)
                self.countryCode = stored
                self.headers["accept-language"] = stored

        return stubs.load_sweettv(helper_class=Helper, translate=lambda p: path if p.endswith("settings.xml") else folder)

    def test_a_default_hungarian_becomes_russian(self):
        for text in (None, "<settings version='2'></settings>",
                     '<settings><setting id="countryCode" default="true">hu</setting></settings>'):
            sweet = self.sweet(text)
            self.assertEqual((sweet.helper.countryCode, sweet.helper.headers["accept-language"]), ("ru", "ru"), text)

    def test_a_hungarian_chosen_on_purpose_stays(self):
        sweet = self.sweet('<settings><setting id="countryCode">hu</setting></settings>')
        self.assertEqual((sweet.helper.countryCode, sweet.helper.headers["accept-language"]), ("hu", "hu"))

    def test_any_other_language_stays(self):
        for stored in ("pl", "uk", "ru", "en"):
            sweet = self.sweet('<settings><setting id="countryCode" default="true">%s</setting></settings>' % stored, stored)
            self.assertEqual(sweet.helper.countryCode, stored)

    def test_a_settings_file_that_cannot_be_read_changes_nothing(self):
        folder = tempfile.mkdtemp()
        sweet = stubs.load_sweettv(translate=lambda p: folder)      # a directory: not readable as a file
        self.assertEqual(sweet.helper.countryCode, "ua")

    def test_the_language_is_one_constant(self):
        sweet = self.sweet(None)
        self.assertEqual(sweet.MS_LANGUAGE, "ru")

    def asked(self, sweet):
        return (sweet.helper.countryCode, sweet.helper.headers["accept-language"])

    def test_the_language_of_the_box_is_what_sweettv_is_asked_in(self):
        for chosen, expected in (("uk", "uk"), ("pl", "pl"), ("en", "en"), ("en_US", "en"), ("be", "ru"), ("de", "en"), ("hu", "hu")):
            self.choose(chosen)
            sweet = self.sweet('<settings><setting id="countryCode" default="true">hu</setting></settings>')
            self.assertEqual(self.asked(sweet), (expected, expected), chosen)

    def test_a_chosen_language_wins_over_another_one_in_the_add_on_setting(self):
        self.choose("uk")
        sweet = self.sweet('<settings><setting id="countryCode">pl</setting></settings>', "pl")
        self.assertEqual(self.asked(sweet), ("uk", "uk"))

    def test_without_a_choice_the_setting_decides_and_nothing_is_written(self):
        sweet = self.sweet('<settings><setting id="countryCode">pl</setting></settings>', "pl")
        self.assertEqual(self.asked(sweet), ("pl", "pl"))
        self.assertEqual(os.listdir(self.prefs), [])

    def test_a_file_that_names_nothing_known_is_russian(self):
        with open(os.path.join(self.prefs, "language"), "w", encoding="utf-8") as f:
            f.write("klingon\n")
        self.assertEqual(self.asked(self.sweet(None)), ("ru", "ru"))

    def test_without_the_language_library_the_add_on_behaves_as_before(self):
        with mock.patch.dict(sys.modules, {"mediastick_lang": None}):
            self.assertEqual(self.asked(self.sweet(None)), ("ru", "ru"))
            sweet = self.sweet('<settings><setting id="countryCode">hu</setting></settings>')
            self.assertEqual(self.asked(sweet), ("hu", "hu"))

    def test_a_language_chosen_while_the_service_runs_is_asked_for_in_the_next_refresh(self):
        """The service lives from Kodi's start: the helper was built then, the language may be chosen days later."""
        self.choose("ru")
        sweet = self.sweet(None)
        stubs.Settings.values.update(bearer="Bearer " + stubs.TOKEN, logged=True)
        stubs.StaleHelper.calls.clear()
        sweet.refreshChannelList()
        self.choose("uk")
        sweet.refreshChannelList()
        self.choose("pl")
        sweet.refreshChannelList()
        self.assertEqual([h.get("accept-language") for h in stubs.channel_requests()], ["ru", "uk", "pl"])
        self.assertEqual(sweet.helper.countryCode, "pl")
        self.assertEqual(stubs.channel_requests()[0].get("authorization"), "Bearer " + stubs.TOKEN)


class CaptionsAreOnlyLabels(unittest.TestCase):
    """The TV app and the phone page key the categories by SWEET.TV's ids and show its captions as they come: a list asked
    for in Russian gives the same menu as one asked for in Hungarian, with other words."""

    def test_the_menu_is_the_same_in_any_language(self):
        path = os.path.join(HERE, "..", "device", "kodi-addons", "script.media-stick.home", "resources", "lib", "sweettv_data.py")
        spec = importlib.util.spec_from_file_location("sweettv_data_for_captions", path)
        data = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(data)

        def catalog(captions):
            return {"status": "OK", "categories": [{"id": i, "caption": c} for i, c in captions],
                    "list": [{"id": 1, "name": "A", "category": [2, 3]}, {"id": 2, "name": "B", "category": [3]}]}

        hu = data.parse_catalog(catalog([(2, "Nemzeti"), (3, "Ingyenes TV"), (1000, "Összes")]), NOW)
        ru = data.parse_catalog(catalog([(2, "Национальные"), (3, "Бесплатное ТВ"), (1000, "Все")]), NOW)
        self.assertEqual([k for k, _ in hu.categories], [k for k, _ in ru.categories])
        self.assertEqual([k for k, _ in ru.categories], ["c:2", "c:3"])
        self.assertEqual([n for _, n in ru.categories], ["Национальные", "Бесплатное ТВ"])
        self.assertEqual([(c.cid, c.cats) for c in hu.channels], [(c.cid, c.cats) for c in ru.channels])


if __name__ == "__main__":
    unittest.main()
