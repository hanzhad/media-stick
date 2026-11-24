#!/usr/bin/env python3
"""Offline test of the sections of the SWEET.TV page (no Kodi, no device, no network): python3 tools/test-sweetsections.py

«Каналы», «Шоу и сериалы» and «Фильмы» are made from the channel list the add-on keeps: mediastick_sweetsections (pure) groups
the programme guide into shows and films, panel_sweettv answers the routes. The data is tools/fixtures/sweettv-channel-list.json,
five channels of a real list (a show with tv_show_id, shows without it, a film channel, a channel without an archive), taken
at the moment NOW; the rest of the tests are small lists made here."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON_LIB = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "resources", "lib")
os.environ["MEDIASTICK_ADDON_LIB"] = ADDON_LIB
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home"))

import mediastick_sweetsections as sec  # noqa: E402
import panel_sweettv as ps  # noqa: E402
import panel_watch as pw  # noqa: E402
from resources.lib import sweettv_text as words  # noqa: E402

with open(os.path.join(HERE, "fixtures", "sweettv-channel-list.json"), encoding="utf-8") as _f:
    FIXTURE = json.load(_f)
NOW = 1795473564                      # the moment that list was taken: the programmes on now are the ones that contain it
DAY = 86400


def programme(epg, text, start, minutes=45, **fields):
    return {"id": epg, "text": text, "time_start": start, "time_stop": start + minutes * 60, "available": True, **fields}


def channel(cid, epg, name="Channel", category=(29, 1000), catchup=True, days=7, **fields):
    return {"id": cid, "name": name, "category": list(category), "catchup": catchup, "catchup_duration": days, "available": True,
            "icon_v2_url": "https://img.sweet.tv/c/%d.webp" % cid, "epg": epg, **fields}


def listing(*channels, categories=()):
    return {"status": "OK", "categories": list(categories), "list": list(channels)}


class SplitTitle(unittest.TestCase):
    def test_what_a_title_says(self):
        for text, expected in (
                ("Миша Season 1 Episode 7", ("Миша", 1, 7, "")),
                ("Star Academy - Episode 2", ("Star Academy", 0, 2, "")),
                ("Зрадники Сезон 2 Епізод 6", ("Зрадники", 2, 6, "")),
                ("Сліпа Season 5 Episode 277 - Дріб'язкові справи", ("Сліпа", 5, 277, "Дріб'язкові справи")),
                ("Сніданок з 1+1 Episode 227", ("Сніданок з 1+1", 0, 227, "")),
                ("Мастер Серия 12", ("Мастер", 0, 12, "")),
                ("Show episode 3", ("Show", 0, 3, "")),
                ("Show Season 4", ("Show", 4, 0, "")),
                ("Сусідка", ("Сусідка", 0, 0, "")),
                ("", ("", 0, 0, "")),
                ("  Many   spaces  Episode  9 ", ("Many spaces", 0, 9, "")),
                ("Episode 5", ("Episode 5", 0, 5, "")),            # nothing before the marker: the title stays whole
                ("Episodes of a day", ("Episodes of a day", 0, 0, "")),
                ("Season 3 Finale", ("Season 3 Finale", 3, 0, "Finale")),
                ("Reepisode 4", ("Reepisode 4", 0, 0, "")),         # a word that only ends in the marker is not one
        ):
            self.assertEqual(sec.split_title(text), expected, text)

    def test_nonsense_is_not_a_crash(self):
        for value in (None, 5, [], {"a": 1}, "Episode " + "9" * 40):
            self.assertEqual(len(sec.split_title(value)), 4)


class Rules(unittest.TestCase):
    """The grouping, on small lists."""

    def build(self, *channels, **kw):
        return sec.build(listing(*channels, **kw))

    def everything(self, record):
        return True

    def test_a_show_id_groups_and_a_title_groups_when_there_is_none(self):
        raw = channel(1, [programme(11, "Alpha Season 1 Episode 1", NOW - 9000, tv_show_id=77),
                          programme(12, "Alpha Season 1 Episode 2", NOW - 6000, tv_show_id=77),
                          programme(13, "Beta - Episode 4", NOW - 3000), programme(14, "Beta - Episode 5", NOW - 2000)])
        index = self.build(raw)
        self.assertEqual(sorted(index["shows"]), sorted(["77", sec._show_id(0, "Beta")]))
        self.assertEqual(sorted(e["title"] for e in sec.shows(index, self.everything)), ["Alpha", "Beta"])
        self.assertTrue(re.fullmatch(sec.SHOW_ID_RE, sec._show_id(None, "Beta")))
        self.assertEqual(sec._show_id(0, "Beta"), sec._show_id(None, "BETA"))

    def test_the_field_numbers_win_over_the_title(self):
        raw = channel(1, [programme(11, "Alpha Season 1 Episode 1", NOW - 9000, tv_show_id=77, season_number=3, episode_number=8)])
        record = self.build(raw)["shows"]["77"]["records"][0]
        self.assertEqual((record["season"], record["episode"]), (3, 8))

    def test_a_film_is_long_has_no_show_and_is_on_a_film_channel(self):
        films = channel(1, [programme(11, "Long film", NOW - 9000, 120), programme(12, "Short film", NOW - 20000, 74),
                            programme(13, "Edge film", NOW - 30000, 75), programme(14, "Show-like", NOW - 40000, 120, tv_show_id=5),
                            programme(15, "Serial Episode 3", NOW - 50000, 120)], category=(4, 1000))
        other = channel(2, [programme(21, "Long film elsewhere", NOW - 9000, 120)], category=(29, 1000))
        index = self.build(films, other)
        self.assertEqual(sorted(r["text"] for r in index["films"]), ["Edge film", "Long film"])
        self.assertEqual(sorted(e["title"] for e in sec.shows(index, self.everything)), ["Serial", "Show-like"])

    def test_the_same_film_is_one_item_with_its_airings(self):
        films = channel(1, [programme(11, "Hugo", NOW - 9000, 120), programme(12, "Hugo", NOW - 90000, 120),
                            programme(13, "HUGO", NOW + 9000, 120)], category=(4,))
        elsewhere = channel(2, [programme(21, "Hugo", NOW - 3000, 120)], category=(4,))
        items = sec.films(self.build(films, elsewhere), lambda r: r["start"] < NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["epg"], items[0]["cid"], items[0]["airings"], items[0]["title"]), ("21", "2", 3, "Hugo"))
        self.assertEqual((items[0]["minutes"], items[0]["available"]), (120, True))

    def test_only_what_can_be_played_is_in_the_lists(self):
        raw = channel(1, [programme(11, "Alpha Episode 1", NOW - 9000), programme(12, "Alpha Episode 2", NOW + 9000),
                          programme(13, "Gamma Episode 1", NOW + 9000)])
        index = self.build(raw)
        started = lambda r: r["start"] <= NOW           # noqa: E731
        self.assertEqual([(e["title"], e["episodes"]) for e in sec.shows(index, started)], [("Alpha", 1)])
        shown = sec.show(index, sec._show_id(0, "Alpha"), started)       # a show's own page lists what is still to come too
        self.assertEqual([(e["episode"], e["available"]) for e in shown["episodes"]], [(1, True), (2, False)])
        gamma = sec.show(index, sec._show_id(0, "Gamma"), started)
        self.assertEqual([e["available"] for e in gamma["episodes"]], [False])

    def test_an_episode_repeated_on_another_channel_is_one_episode(self):
        a = channel(1, [programme(11, "Alpha Season 2 Episode 5", NOW - 9000, tv_show_id=9)])
        b = channel(2, [programme(21, "Alpha Season 2 Episode 5", NOW - 3000, tv_show_id=9),
                        programme(22, "Alpha Season 2 Episode 6", NOW + 3000, tv_show_id=9)])
        shown = sec.show(self.build(a, b), "9", lambda r: r["start"] <= NOW)
        self.assertEqual([(e["episode"], e["epg"], e["available"]) for e in shown["episodes"]], [(5, "21", True), (6, "22", False)])
        self.assertEqual(sec.shows(self.build(a, b), lambda r: r["start"] <= NOW)[0]["episodes"], 1)

    def test_a_playable_repeat_wins_over_one_to_come(self):
        a = channel(1, [programme(11, "Alpha Episode 5", NOW + 9000), programme(12, "Alpha Episode 5", NOW - 9000)])
        shown = sec.show(self.build(a), sec._show_id(0, "Alpha"), lambda r: r["start"] <= NOW)
        self.assertEqual([(e["epg"], e["available"]) for e in shown["episodes"]], [("12", True)])

    def test_episodes_are_in_the_order_of_the_series(self):
        raw = channel(1, [programme(11, "A Season 2 Episode 1", NOW - 100, tv_show_id=3), programme(12, "A Season 1 Episode 9", NOW - 200, tv_show_id=3),
                          programme(13, "A Season 1 Episode 10", NOW - 300, tv_show_id=3), programme(14, "A Special", NOW - 400, tv_show_id=3)])
        shown = sec.show(self.build(raw), "3", self.everything)
        self.assertEqual([(e["season"], e["episode"]) for e in shown["episodes"]], [(0, 0), (1, 9), (1, 10), (2, 1)])
        self.assertEqual(shown["episodes"][0]["title"], "A Special")      # nothing said of what it is: the title is the text
        self.assertEqual(shown["episodes"][1]["title"], "")              # numbered: the numbers say it

    def test_the_most_common_name_is_the_title_of_a_show(self):
        raw = channel(1, [programme(11, "Alpha Episode 1", NOW - 100, tv_show_id=3), programme(12, "Alpha Episode 2", NOW - 200, tv_show_id=3),
                          programme(13, "Alfa Episode 3", NOW - 300, tv_show_id=3)])
        self.assertEqual(sec.shows(self.build(raw), self.everything)[0]["title"], "Alpha")

    def test_genres_are_the_lists_own_without_all_and_empty_ones(self):
        raw = listing(channel(1, [], category=(4, 1000)), channel(2, [], category=(4, 29, 1000)), channel(3, [], category=(1000,)),
                      categories=[{"id": 1000, "caption": "All"}, {"id": 12, "caption": "Favourite"}, {"id": 4, "caption": "Film"},
                                  {"id": 29, "caption": "Fun"}, {"id": 99, "caption": "Nobody"}, {"id": 5}, "x"])
        self.assertEqual(sec.genres(sec.build(raw)), [{"id": "c:4", "name": "Film", "channels": 2}, {"id": "c:29", "name": "Fun", "channels": 1}])

    def test_a_channel_that_is_not_available_or_a_broken_row_is_skipped(self):
        raw = listing(channel(1, [programme(11, "Alpha Episode 1", NOW - 100)], available=False),
                      channel(2, [programme(21, "Beta Episode 1", NOW - 100), {"id": 22, "text": "No times"},
                                  {"id": 0, "text": "Zero Episode 1", "time_start": NOW - 5, "time_stop": NOW},
                                  {"id": 23, "text": "Backwards Episode 1", "time_start": NOW, "time_stop": NOW - 5},
                                  {"id": True, "text": "Bool Episode 1", "time_start": NOW - 5, "time_stop": NOW},
                                  {"id": 24, "text": "", "time_start": NOW - 5, "time_stop": NOW}, "junk", None, 5]),
                      "junk", None, {"id": None}, {"id": "x"})
        index = sec.build(raw)
        self.assertEqual(index["channels"], 1)
        self.assertEqual([e["title"] for e in sec.shows(index, self.everything)], ["Beta"])

    def test_milliseconds_are_seconds(self):
        raw = channel(1, [{"id": 11, "text": "Alpha Episode 1", "time_start": (NOW - 100) * 1000, "time_stop": NOW * 1000}], category=(4,))
        self.assertEqual(sec.build(listing(raw))["shows"][sec._show_id(0, "Alpha")]["records"][0]["start"], NOW - 100)

    def test_nothing_is_not_a_crash(self):
        for raw in (None, {}, [], "x", {"list": 5}, {"list": [None]}, {"list": [{"id": 1, "epg": 5}]}):
            index = sec.build(raw)
            self.assertEqual((sec.shows(index, self.everything), sec.films(index, self.everything), sec.genres(index)), ([], [], []))

    def test_a_show_id_is_checked(self):
        index = sec.build(listing(channel(1, [programme(11, "A Episode 1", NOW - 100, tv_show_id=3)])))
        for sid in ("3", "t0123456789"):
            self.assertTrue(sec.SHOW_ID_RE.fullmatch(sid))
        self.assertIsNotNone(sec.show(index, "3", self.everything))
        for sid in (None, 3, "", "4", "3 ", "../3", "t12", "T0123456789", "3" * 13, "t0123456789ab", ["3"]):
            self.assertIsNone(sec.show(index, sid, self.everything), sid)


class Fixture(unittest.TestCase):
    """What the guide of five real channels makes of it."""
    slim = ps.slim(FIXTURE)
    index = sec.build(slim)
    ok = staticmethod(ps._playable(NOW))

    def test_what_is_in_it(self):
        self.assertEqual(self.index["channels"], 5)
        self.assertEqual((len([k for k in self.index["shows"] if not k.startswith("t")]),
                          len([k for k in self.index["shows"] if k.startswith("t")]), len(self.index["films"])), (10, 10, 60))

    def test_the_shows_with_something_to_play(self):
        self.assertEqual([(e["id"], e["title"], e["episodes"]) for e in sec.shows(self.index, self.ok)], [
            ("t63a67f2171", "Destination X", 2), ("t3662848201", "Декстер", 2), ("t5e219491d6", "Елементарно", 2),
            ("t664460eefa", "Закохані", 1), ("tb6e519d7d3", "Миша", 2), ("242551", "Одруження наосліп", 1), ("214108", "Реванш", 2),
            ("t2f5828fff7", "Розслідування з Андрієм Данілевичем", 1), ("213184", "Світ навиворіт", 2), ("241218", "Сльози Дженнет", 4),
            ("228884", "Сусідка", 1), ("235390", "Таємниці архівів", 1)])

    def test_a_show_says_its_newest_episode_that_can_be_played(self):
        for item in sec.shows(self.index, self.ok):
            shown = sec.show(self.index, item["id"], self.ok)
            playable = [e for e in shown["episodes"] if e["available"]]
            newest = max(playable, key=lambda e: e["start"])
            self.assertEqual(item["latest"], newest, item["title"])
            self.assertTrue(item["latest"]["available"] and item["latest"]["channel"])
        self.assertEqual(set(sec.shows(self.index, self.ok)[0]["latest"]),
                         {"cid", "epg", "title", "season", "episode", "start", "stop", "available", "channel"})

    def test_a_show_with_an_id_and_numbered_episodes(self):
        shown = sec.show(self.index, "241218", self.ok)
        self.assertEqual(shown["title"], "Сльози Дженнет")
        self.assertEqual(len(shown["episodes"]), 10)
        self.assertEqual(sum(e["available"] for e in shown["episodes"]), 4)
        self.assertEqual([e["episode"] for e in shown["episodes"]][:4], [89, 90, 91, 92])
        self.assertTrue(all(e["available"] == (e["start"] <= NOW) for e in shown["episodes"]))
        self.assertEqual(set(shown["episodes"][0]), {"cid", "epg", "title", "season", "episode", "start", "stop", "available", "channel"})

    def test_a_show_without_an_id_is_the_title_across_channels(self):
        shown = sec.show(self.index, "t63a67f2171", self.ok)
        self.assertEqual(shown["title"], "Destination X")
        self.assertEqual({e["cid"] for e in shown["episodes"]}, {"3711", "3832"})
        self.assertEqual([e["episode"] for e in shown["episodes"]], [1, 2, 3])
        self.assertEqual([e["available"] for e in shown["episodes"]], [True, True, False])

    def test_the_films(self):
        films = sec.films(self.index, self.ok)
        self.assertEqual(len(films), 12)
        self.assertEqual([f["title"] for f in films][:3], ["Boudica", "Hugo", "If You Were the Last"])
        hugo = next(f for f in films if f["title"] == "Hugo")
        self.assertEqual((hugo["airings"], hugo["minutes"], hugo["channel"], hugo["available"]), (2, 134, "SWEET MOVIES HD", True))
        self.assertTrue(all(f["minutes"] >= sec.FILM_MINUTES and f["start"] <= NOW for f in films))
        self.assertTrue(all(not re.search(r"(Season|Episode)\s+\d", f["title"]) for f in films))   # «Миша Season 1 Episode 7» is a show

    def test_a_channel_without_an_archive_gives_nothing_to_play(self):
        raw = json.loads(json.dumps(FIXTURE))
        for c in raw["list"]:
            c["catchup"] = False
        slim = ps.slim(raw)
        index = sec.build(slim)
        self.assertEqual((sec.shows(index, ps._playable(NOW)), sec.films(index, ps._playable(NOW))), ([], []))

    def test_what_is_older_than_the_archive_is_not_playable(self):
        later = NOW + 30 * DAY                        # no channel of the list keeps more than 14 days
        self.assertEqual((sec.shows(self.index, ps._playable(later)), sec.films(self.index, ps._playable(later))), ([], []))
        self.assertEqual(len(sec.films(self.index, ps._playable(NOW))), 12)

    def test_the_genres_are_the_channel_filter_of_the_phone_page(self):
        genres = sec.genres(self.index)
        self.assertIn({"id": "c:4", "name": "Film", "channels": 2}, genres)
        self.assertTrue(all(re.fullmatch(r"c:[0-9]+", g["id"]) and g["channels"] > 0 for g in genres))
        self.assertNotIn("c:1000", [g["id"] for g in genres])
        sw = pw.sweet()
        if sw is not None:                                           # the add-on's own parse of the same list: the same keys
            theirs = {key for key, _ in sw.parse_catalog(FIXTURE, NOW).categories}
            self.assertEqual({g["id"] for g in genres}, theirs)


class Routes(unittest.TestCase):
    slim = Fixture.slim

    def setUp(self):
        ps._index_cache.update(raw=None, value=None)
        patches = [mock.patch.object(ps, "channels", lambda: self.slim), mock.patch.object(ps, "time", types.SimpleNamespace(time=lambda: NOW))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_sections(self):
        body, code = ps.get(ps.PREFIX + "sections", None)
        self.assertEqual(code, 200)
        self.assertEqual((body["ok"], body["channels"], body["shows"], body["films"]), (True, 5, 12, 12))
        self.assertEqual(body["labels"], {"channels": "Каналы", "shows": "Шоу и сериалы", "films": "Фильмы"})
        self.assertIn({"id": "c:4", "name": "Film", "channels": 2}, body["genres"])
        self.assertEqual(body["shows"], len(ps.get(ps.PREFIX + "shows", None)[0]["items"]))
        self.assertEqual(body["films"], len(ps.get(ps.PREFIX + "films", None)[0]["items"]))

    def test_shows(self):
        body, code = ps.get(ps.PREFIX + "shows", None)
        self.assertEqual(code, 200)
        first = body["items"][0]
        self.assertEqual(set(first), {"id", "title", "episodes", "thumb"})
        self.assertEqual((first["id"], first["title"], first["episodes"]), ("t63a67f2171", "Destination X", 2))
        self.assertTrue(first["thumb"].startswith("https://img.sweet.tv/"))

    def test_a_picture_from_anywhere_else_is_not_passed_on(self):
        raw = listing(channel(1, [programme(11, "Alpha Episode 1", NOW - 100)], icon_v2_url="http://evil.example/x.png"))
        with mock.patch.object(ps, "channels", lambda: ps.slim(raw)):
            self.assertEqual(ps.get(ps.PREFIX + "shows", None)[0]["items"][0]["thumb"], "")

    def test_show(self):
        body, code = ps.get(ps.PREFIX + "show?id=241218", None)
        self.assertEqual((code, body["id"], body["title"], len(body["episodes"])), (200, "241218", "Сльози Дженнет", 10))
        self.assertTrue(body["thumb"].startswith("https://"))

    def test_a_wrong_show_is_refused_in_words(self):
        for query, code, text in (("", 400, "Неверное шоу."), ("id=abc", 400, "Неверное шоу."), ("id=1;2", 400, "Неверное шоу."),
                                  ("id=999", 404, "Такого шоу нет в списке.")):
            body, status = ps.get(ps.PREFIX + "show?" + query, None)
            self.assertEqual((status, body), (code, {"error": text}), query)
        self.assertEqual(ps.get(ps.PREFIX + "show", None)[1], 400)

    def test_films(self):
        body, code = ps.get(ps.PREFIX + "films", None)
        self.assertEqual(code, 200)
        self.assertEqual(set(body["items"][0]), {"cid", "epg", "title", "start", "stop", "minutes", "available", "airings", "channel"})
        self.assertEqual(body["items"][1]["title"], "Hugo")

    def test_what_a_section_lists_plays_through_the_archive_route(self):
        film = ps.get(ps.PREFIX + "films", None)[0]["items"][0]
        url, epg, offset = ps.play_request(self.slim, {"cid": film["cid"], "epg": film["epg"]}, NOW)
        self.assertEqual((epg, offset), (film["epg"], 0))
        self.assertTrue(url.endswith("/playvid/%s|%s" % (film["cid"], film["epg"])))
        shown = ps.get(ps.PREFIX + "show?id=241218", None)[0]
        coming = next(e for e in shown["episodes"] if not e["available"])
        with self.assertRaises(pw.Refused) as caught:
            ps.play_request(self.slim, {"cid": coming["cid"], "epg": coming["epg"]}, NOW)
        self.assertEqual(caught.exception.code, 409)
        episode = next(e for e in shown["episodes"] if e["available"])
        self.assertEqual(ps.play_request(self.slim, {"cid": episode["cid"], "epg": episode["epg"], "at": "start"}, NOW)[1], episode["epg"])

    def test_the_index_is_made_once_per_list(self):
        first = ps._index(self.slim)
        self.assertIs(ps._index(self.slim), first)
        self.assertIsNot(ps._index(ps.slim(FIXTURE)), first)

    def test_an_empty_list_has_empty_sections(self):
        with mock.patch.object(ps, "channels", lambda: {}):
            body, code = ps.get(ps.PREFIX + "sections", None)
            self.assertEqual((code, body["channels"], body["shows"], body["films"], body["genres"]), (200, 0, 0, 0, []))
            self.assertEqual(ps.get(ps.PREFIX + "films", None)[0]["items"], [])

    def test_without_the_libraries_the_routes_say_so(self):
        for name in ("sections", "ml"):
            with mock.patch.object(ps, name, None):
                for route in ("sections", "shows", "films", "show?id=1"):
                    self.assertEqual(ps.get(ps.PREFIX + route, None)[1], 503, (name, route))

    def test_slim_keeps_what_the_sections_read_and_nothing_heavy(self):
        row = self.slim["list"][0]
        self.assertTrue({"category", "icon_v2_url", "epg"} <= set(row))
        self.assertEqual(self.slim["categories"][0], {"id": 1000, "caption": "Összes"})
        heavy = json.dumps(ps.slim({"list": [{"id": 1, "banner_url": "x" * 1000, "epg": [{"id": 2, "external_ids": [1] * 500}]}]}))
        self.assertLess(len(heavy), 300)


class Texts(unittest.TestCase):
    def test_every_new_text_has_russian_and_ukrainian(self):
        for msgid in ("Channels", "Shows and series", "Films", "Wrong show.", "This show is not in the list."):
            self.assertTrue(words.TEXT[msgid].get("ru") and words.TEXT[msgid].get("uk"), msgid)
            self.assertNotEqual(words.TEXT[msgid]["ru"], msgid)
            self.assertNotEqual(words.TEXT[msgid]["uk"], words.TEXT[msgid]["ru"])


if __name__ == "__main__":
    unittest.main()
