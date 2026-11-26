#!/usr/bin/env python3
"""Offline test of SWEET.TV own API as the stick uses it (no Kodi, no device, no network): python3 tools/test-sweetapi.py

mediastick_sweetapi (search, the programmes of one channel on one day, the client that posts to api.sweet.tv) on recorded
shapes of the answers (tools/fixtures/sweettv-search.json, sweettv-day.json) and a fake transport; the phone routes
/api/sweettv/search and /api/sweettv/day, and that a programme they returned plays through the existing /play."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from datetime import date, timedelta  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON_LIB = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "resources", "lib")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_ADDON_LIB"] = ADDON_LIB
os.environ["MEDIASTICK_PREFS_DIR"] = os.path.join(TMP, "prefs")
os.environ["MEDIASTICK_SWEETSTORE_DB"] = os.path.join(TMP, "sweettv", "sweettv.db")
os.environ["TZ"] = "UTC"
time.tzset()
sys.path.insert(0, LIB)

import mediastick_signin as signin  # noqa: E402
import mediastick_sweetapi as api  # noqa: E402
import mediastick_sweetlive as ml  # noqa: E402
import mediastick_sweetstore as sweetstore  # noqa: E402
import panel_sweettv as ps  # noqa: E402
import panel_watch as pw  # noqa: E402


def _clear_default_sweetstore():
    st = sweetstore.default_store()
    if hasattr(st, "clear"):
        st.clear()
    if hasattr(api, "_known"):
        api._known.clear()


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)


SEARCH, DAY = fixture("sweettv-search.json"), fixture("sweettv-day.json")
NOW = 1795521600                                  # Tue 2026-11-24 12:00 UTC; the fixture Friday 20th 17:00 UTC is 1795194000
DAY_START = 1795392000                            # Mon 2026-11-23 00:00 UTC
CHANNELS = {"list": [
    {"id": 15, "name": "СТБ", "catchup": True, "catchup_duration": 7, "available": True, "epg_days_future": 3, "epg": []},
    {"id": 16, "name": "1+1", "catchup": False, "available": True, "epg": []}]}
MAP = api.channel_map(CHANNELS)
ENGLISH = lambda msgid: msgid                      # noqa: E731
ENGLISH_N = lambda n, one, other: (one if n == 1 else other).format(n=n)    # noqa: E731
TOKEN = "Bearer SECRET-TOKEN-VALUE"


def reply(body, status=200):
    return status, json.dumps(body).encode("utf-8")


class Sender:
    """The fake transport: answers in turn (a list) or by a function; keeps what was asked."""

    def __init__(self, *answers, by=None):
        self.answers, self.by, self.calls = list(answers), by, []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(payload.decode("utf-8")), "timeout": timeout})
        if self.by:
            return self.by(self.calls[-1])
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def client(*answers, by=None, token=lambda: TOKEN, clock=None):
    sender = Sender(*answers, by=by)
    return api.Client(token=token, send=sender, clock=clock or Clock()), sender


def rows_of(rows, kind):
    return [r for r in rows if r["kind"] == kind]


class Search(unittest.TestCase):
    def rows(self, tr=ENGLISH, tr_n=ENGLISH_N, now=NOW):
        return api.normalize_search(SEARCH, MAP, now, tr, tr_n)

    def test_one_title_is_one_row_with_the_other_airings_counted_and_the_programmes_newest_first(self):
        programmes = rows_of(self.rows(), "programme")
        shows = rows_of(self.rows(), "show_tv")
        self.assertEqual(len(shows), 1)
        self.assertEqual([r["epg"] for r in shows[0]["episodes"]], ["9010", "9002"])
        self.assertEqual([r["epg"] for r in programmes], ["9020", "9040", "9030"])
        self.assertEqual([r["start"] for r in programmes], sorted((r["start"] for r in programmes), reverse=True))
        six = next(r for r in shows[0]["episodes"] if r["epg"] == "9002")
        self.assertEqual((six["repeats"], six["more"]), (2, "2 more airings"))
        self.assertEqual((six["cid"], six["channel_name"], six["start"], six["stop"]), ("15", "СТБ", 1795255200, 1795260600))
        self.assertEqual([r["repeats"] for r in programmes], [0, 0, 0])

    def test_the_airing_that_stands_for_a_title_is_the_newest_that_can_be_watched_else_the_soonest_to_come_else_the_newest(self):
        def airing(epg, start, watchable, live=False):
            return {"title": "T", "epg": epg, "start": start, "live": live, "playable_in_archive": watchable}
        rows = [airing("a", NOW - 300, True), airing("b", NOW - 200, True), airing("c", NOW + 100, False), airing("d", NOW + 50, False)]
        self.assertEqual(api.collapse(rows, NOW, ENGLISH_N)[0]["epg"], "b")
        self.assertEqual(api.collapse(rows[2:], NOW, ENGLISH_N)[0]["epg"], "d")                 # nothing to watch: the soonest to come
        self.assertEqual(api.collapse([airing("e", NOW - 900, False), airing("f", NOW - 800, False)], NOW, ENGLISH_N)[0]["epg"], "f")
        self.assertEqual(api.collapse([airing("g", NOW - 900, False), airing("h", NOW - 8000, True)], NOW, ENGLISH_N)[0]["epg"], "h")
        self.assertEqual(api.collapse([airing("i", NOW - 900, False, live=True)], NOW, ENGLISH_N)[0]["more"], "")

    def test_the_words_of_the_count_follow_the_language(self):
        shows_ru = rows_of(self.rows(ml.text, ml.text_n), "show_tv")
        six = next(r for r in shows_ru[0]["episodes"] if r["epg"] == "9002")
        self.assertEqual((six["more"], six["when"]), ("ещё 2 показа", "Сб 21 ноя 10:00"))
        self.assertEqual([ml.text_n(n, api.MORE_ONE, api.MORE_MANY) for n in (1, 2, 5, 21)],
                         ["ещё 1 показ", "ещё 2 показа", "ещё 5 показов", "ещё 21 показ"])

    def test_when_is_the_day_the_date_and_the_time_in_local_time(self):
        self.assertEqual(api.when_text(1795194000, NOW, ENGLISH), "Fri 20 Nov 17:00")
        self.assertEqual(api.when_text(1795194000, NOW, ml.text), "Пт 20 ноя 17:00")
        self.assertEqual(api.when_text(1795194000 + 15 * 86400, NOW, ENGLISH), "Sat 5 Dec 17:00")
        os.environ["TZ"] = "Europe/Kyiv"
        time.tzset()
        try:
            self.assertEqual(api.when_text(1795194000, NOW, ENGLISH), "Fri 20 Nov 19:00")
        finally:
            os.environ["TZ"] = "UTC"
            time.tzset()

    def test_on_now_in_the_archive_to_come_and_out_of_the_archive(self):
        rows_all = self.rows()
        by = {r["epg"]: r for r in rows_of(rows_all, "programme") + rows_of(rows_all, "show_tv")[0]["episodes"]}
        live = by["9020"]
        self.assertEqual((live["live"], live["playable_in_archive"], live["playable"]), (True, True, True))
        future = by["9010"]
        self.assertEqual((future["live"], future["playable_in_archive"], future["playable"]), (False, False, False))
        old = by["9030"]
        self.assertEqual((old["playable_in_archive"], old["playable"]), (False, False))              # 20 days back, the archive keeps 7
        stranger = by["9040"]
        self.assertEqual((stranger["channel_name"], stranger["playable"]), ("", False))              # a channel the account does not have
        self.assertTrue(by["9002"]["playable_in_archive"] and not by["9002"]["live"])

    def test_the_archive_window_is_the_rule_of_the_guide(self):
        channel = {"id": 15, "catchup": True, "catchup_duration": 7, "available": True}
        week = 7 * 86400

        def row(start, channel=channel, stop=None):
            item = {"type": "EpgRecord", "id": 5, "sub_id": 15, "text": "X", "time_start": str(start), "time_stop": str(stop or start + 1800)}
            return api.normalize_search({"result": [item]}, api.channel_map({"list": [channel]}), NOW, ENGLISH, ENGLISH_N)[0]
        self.assertTrue(row(NOW - week)["playable_in_archive"])
        self.assertFalse(row(NOW - week - 1)["playable_in_archive"])
        self.assertTrue(row(NOW - 1800, stop=NOW + 600)["playable_in_archive"])                      # started, still on
        self.assertFalse(row(NOW + 1)["playable_in_archive"])                                        # not started
        self.assertFalse(row(NOW - 3600, {**channel, "catchup": False})["playable_in_archive"])
        self.assertFalse(row(NOW - 3600, {**channel, "available": False})["playable_in_archive"])
        self.assertTrue(row(NOW - 3 * 86400, {**channel, "catchup_duration": 3})["playable_in_archive"])
        self.assertFalse(row(NOW - 3 * 86400 - 1, {**channel, "catchup_duration": 3})["playable_in_archive"])

    def test_channels_films_and_people_follow_the_programmes_and_odd_items_are_left_out(self):
        rows = self.rows()
        self.assertEqual([r["kind"] for r in rows], ["show_tv"] + ["programme"] * 3 + ["channel", "movie", "person"])
        stb = rows_of(rows, "channel")[0]
        self.assertEqual((stb["cid"], stb["title"], stb["channel_name"], stb["playable"], stb["available"], stb["subtitle"]),
                         ("15", "СТБ HD", "СТБ", True, True, "Новини, шоу"))
        all_rows = api.normalize_search(SEARCH, MAP, NOW, tr=ENGLISH, tr_n=ENGLISH_N, include_unavailable=True)
        _, other = rows_of(all_rows, "channel")
        self.assertEqual((other["cid"], other["playable"], other["available"]), ("99", False, False))
        movie, person = rows_of(rows, "movie")[0], rows_of(rows, "person")[0]
        self.assertEqual((movie["title"], movie["subtitle"], movie["playable"], movie["cid"], movie["epg"]),
                         ("Divorce Club", "2020, Comedy", True, "", ""))
        self.assertEqual((person["title"], person["playable"]), ("Іван Холостяк", False))
        self.assertEqual(len(rows), 7)

    def test_premiera_collapse_channel_boost_and_enriched_vod(self):
        c1 = {"kind": "programme", "id": "1", "title": "Любовь на выживание", "cid": "15", "epg": "1", "start": NOW - 200, "stop": NOW - 100, "live": False, "playable_in_archive": True, "playable": True, "available": True}
        c2 = {"kind": "programme", "id": "2", "title": "Премьера. Любовь на выживание", "cid": "15", "epg": "2", "start": NOW - 500, "stop": NOW - 400, "live": False, "playable_in_archive": True, "playable": True, "available": True}
        self.assertEqual(len(api.collapse([c1, c2], NOW, ENGLISH_N)), 1)
        boosted = api.normalize_search(SEARCH, MAP, NOW, tr=ENGLISH, tr_n=ENGLISH_N, needle="СТБ")
        self.assertEqual(boosted[0]["kind"], "channel")
        self.assertEqual(boosted[0]["cid"], "15")

    def test_odd_answers_never_raise(self):
        for junk in (None, 5, "x", [], {}, {"result": None}, {"result": "x"}, {"result": [None, 1, {}, {"type": 5}]}, {"result": {"a": 1}}):
            self.assertEqual(api.normalize_search(junk, MAP, NOW, ENGLISH, ENGLISH_N), [])
        self.assertEqual(api.normalize_search(SEARCH, None, NOW, ENGLISH, ENGLISH_N)[0]["playable"], False)
        self.assertEqual(api.normalize_search(SEARCH, {}, NOW, ENGLISH, ENGLISH_N)[0]["channel_name"], "")

    def test_a_row_is_json_and_never_has_the_token(self):
        rows = self.rows()
        self.assertNotIn("SECRET", json.dumps(rows))
        self.assertTrue(set(rows[0]) >= {"kind", "title", "cid", "epg", "start", "stop", "channel_name", "when", "playable_in_archive", "live"})

    def test_too_many_rows_are_cut(self):
        items = [{"type": "EpgRecord", "id": 100 + n, "sub_id": 15, "text": "Show %d" % n, "time_start": str(NOW - 4000 - n),
                  "time_stop": str(NOW - 3000)} for n in range(200)]
        self.assertEqual(len(api.normalize_search({"result": items}, MAP, NOW, ENGLISH, ENGLISH_N)), api.MAX_ROWS)

    def test_search_asks_with_the_needle_and_remembers_what_it_showed(self):
        _clear_default_sweetstore()
        c, sender = client(reply(SEARCH))
        found = api.search("  Холостяк ", MAP, NOW, client=c, tr=ENGLISH, tr_n=ENGLISH_N)
        self.assertTrue(found["ok"])
        self.assertEqual((found["query"], found["count"]), ("Холостяк", len(found["items"])))
        self.assertEqual([(s["url"], s["body"]) for s in sender.calls],
                         [("https://api.sweet.tv/SearchService/Search.json", {"needle": "Холостяк"})])
        self.assertEqual(api.recall("15", "9002", NOW), {"start": 1795255200, "stop": 1795260600, "available": True})
        self.assertIsNone(api.recall("15", "9001", NOW))                                            # folded into 9002: not offered
        self.assertIsNone(api.recall("16", "9002", NOW))

    def test_a_needle_of_under_two_characters_asks_nothing(self):
        c, sender = client(reply(SEARCH))
        for needle in ("", " ", "a", " х ", None, 5):
            found = api.search(needle, MAP, NOW, client=c)
            self.assertEqual((found["ok"], found["items"], found.get("short")), (True, [], True))
        self.assertEqual(sender.calls, [])
        self.assertTrue(api.search("xy", MAP, NOW, client=c)["ok"])
        self.assertEqual(len(sender.calls), 1)

    def test_a_needle_is_cut_and_cleaned(self):
        c, sender = client(reply({}))
        api.search("a\n\tb" + "z" * 300, MAP, NOW, client=c)
        self.assertEqual(sender.calls[0]["body"]["needle"], ("a b" + "z" * 300)[:api.MAX_NEEDLE])

    def test_an_answer_without_results_is_an_empty_list_not_an_error(self):
        c, _ = client(reply({}))
        found = api.search("nothing", MAP, NOW, client=c)
        self.assertEqual((found["ok"], found["items"]), (True, []))

    def test_span_and_complete_filter_truncated_repeats(self):
        for row, expected in (
                ({"start": 100, "stop": 400}, 300),
                ({"start": 100.0, "stop": 250.5}, 150),
                ({"start": 100}, 0),
                ({"stop": 400}, 0),
                ({}, 0),
                ({"start": 100, "stop": 100}, 0),
                ({"start": 200, "stop": 100}, 0),
                ({"start": None, "stop": 200}, 0),
                ({"start": "100", "stop": "200"}, 0),
        ):
            self.assertEqual(api._span(row), expected, row)

        full = {"epg": "full", "start": 1000, "stop": 2000}
        exact_80 = {"epg": "80", "start": 3000, "stop": 3800}
        below_80 = {"epg": "79", "start": 4000, "stop": 4799}
        self.assertEqual([r["epg"] for r in api._complete([full, exact_80])], ["full", "80"])
        self.assertEqual([r["epg"] for r in api._complete([full, below_80])], ["full"])

        no_stop = [{"epg": "a", "start": 100}, {"epg": "b", "start": 200, "stop": 200}]
        self.assertEqual(api._complete(no_stop), no_stop)

    def test_collapse_prefers_complete_premiere_over_split_repeat_halves(self):
        rows = [
            {"title": "Холостяк", "epg": "931394511", "start": 1763658000, "stop": 1763675520, "live": False, "playable_in_archive": True},
            {"title": "Холостяк", "epg": "931410509", "start": 1763707680, "stop": 1763715600, "live": False, "playable_in_archive": True},
            {"title": "Холостяк", "epg": "931416611", "start": 1763715720, "stop": 1763724540, "live": False, "playable_in_archive": True},
        ]
        collapsed = api.collapse(rows, NOW, ENGLISH_N)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual((collapsed[0]["epg"], collapsed[0]["repeats"]), ("931394511", 2))

    def test_collapse_and_stands_for_boundaries_and_fallback(self):
        def row(epg, start, span, watchable=True):
            r = {"title": "Show", "epg": epg, "start": start, "live": False, "playable_in_archive": watchable}
            if span is not None:
                r["stop"] = start + span
            return r

        # Similar full durations (>= 80% of longest) still pick the newest watchable airing
        self.assertEqual(api.collapse([row("a", NOW - 9000, 5400), row("b", NOW - 3000, 5400)], NOW, ENGLISH_N)[0]["epg"], "b")
        self.assertEqual(api.collapse([row("a", NOW - 20000, 10800), row("b", NOW - 10000, 9600)], NOW, ENGLISH_N)[0]["epg"], "b")
        self.assertEqual(api.collapse([row("a", NOW - 9000, 1000), row("b", NOW - 3000, 800)], NOW, ENGLISH_N)[0]["epg"], "b")
        self.assertEqual(api.collapse([row("a", NOW - 9000, 1000), row("b", NOW - 3000, 799)], NOW, ENGLISH_N)[0]["epg"], "a")

        # Missing stop or stop <= start falls back to newest watchable without KeyError
        self.assertEqual(api.collapse([row("a", NOW - 500, None), row("b", NOW - 200, None)], NOW, ENGLISH_N)[0]["epg"], "b")
        self.assertEqual(api.collapse([row("a", NOW - 500, 0), row("b", NOW - 200, -10)], NOW, ENGLISH_N)[0]["epg"], "b")

        # Coming: soonest wins regardless of duration; past unwatchable: complete wins over truncated repeat
        coming = [row("c1", NOW + 100, 1800, False), row("c2", NOW + 500, 7200, False)]
        self.assertEqual(api._stands_for(coming, NOW)["epg"], "c1")
        past = [row("p1", NOW - 9000, 1000, False), row("p2", NOW - 3000, 500, False)]
        self.assertEqual(api._stands_for(past, NOW)["epg"], "p1")

    def test_search_other_row_classifies_series_by_subtext(self):
        # SearchService/Search.json returns Movie entries without is_serial/seasons_count/genres;
        # subtext keywords must classify series/shows as kind="series" while plain movies stay "movie".
        for subtext in (
            "2025, Сериалы, Детективы",
            "2024, Серіали, Драма",
            "2023, Drama Series",
            "2025, Передачи и шоу",
            "2025, Передачі та шоу",
            "2024, Телешоу",
        ):
            with self.subTest(subtext=subtext):
                row = api._other_row(
                    {"type": "Movie", "id": 33871, "text": "Зрадники", "subtext": subtext},
                    "movie",
                    MAP,
                )
                self.assertIsNotNone(row)
                self.assertEqual(row["kind"], "series")

        for subtext in ("2025, Боевики", "2024, Комедія", ""):
            with self.subTest(subtext=subtext):
                row = api._other_row(
                    {"type": "Movie", "id": 501, "text": "Начало", "subtext": subtext},
                    "movie",
                    MAP,
                )
                self.assertIsNotNone(row)
                self.assertEqual(row["kind"], "movie")


class Calls(unittest.TestCase):
    def test_the_headers_are_those_of_the_addon_and_the_token_goes_only_in_the_header(self):
        c, sender = client(reply({}))
        api.search("xy", MAP, NOW, client=c)
        call = sender.calls[0]
        headers = call["headers"]
        self.assertEqual((headers["authorization"], headers["origin"], headers["x-device"]),
                         (TOKEN, "https://sweet.tv", "1;22;0;2;" + api.ADDON_VERSION))
        self.assertTrue(headers["user-agent"] and headers["content-type"] == "application/json" and headers["accept-language"])
        self.assertEqual((call["timeout"], api.TIMEOUT), (8, 8))
        self.assertNotIn("SECRET", json.dumps(call["body"]))

    def test_an_answer_is_kept_for_a_minute_under_its_request(self):
        clock = Clock()
        c, sender = client(reply(SEARCH), clock=clock)
        api.search("holo", MAP, NOW, client=c)
        clock.now += api.CACHE_TTL - 1
        api.search("holo", MAP, NOW, client=c)
        self.assertEqual(len(sender.calls), 1)
        api.search("other", MAP, NOW, client=c)                                                     # another request
        self.assertEqual(len(sender.calls), 2)
        clock.now += 2
        api.search("holo", MAP, NOW, client=c)
        self.assertEqual(len(sender.calls), 3)

    def test_the_cache_is_small(self):
        c, sender = client(reply({}))
        for n in range(api.CACHE_MAX * 2):
            api.search("needle %d" % n, MAP, NOW, client=c)
        self.assertLessEqual(len(c._cache), api.CACHE_MAX)

    def test_what_failed_is_not_kept(self):
        c, sender = client((500, b""), reply({}))
        self.assertFalse(api.search("holo", MAP, NOW, client=c)["ok"])
        self.assertTrue(api.search("holo", MAP, NOW, client=c)["ok"])
        self.assertEqual(len(sender.calls), 2)

    def test_every_failure_is_a_small_result_in_words_never_an_exception(self):
        cases = {"network": (0, b""), "service": (500, b""), "format": (200, b"<html>"), "auth": (403, b"")}
        for code, answer in cases.items():
            c, _ = client(answer)
            found = api.search("holo", MAP, NOW, client=c, tr=ENGLISH)
            self.assertEqual((found["ok"], found["error"], found["message"]), (False, code, api.MESSAGES[code]), code)
            self.assertEqual(set(found), {"ok", "error", "message"})
        c, _ = client(reply([1, 2]))
        self.assertEqual(api.search("holo", MAP, NOW, client=c)["error"], "format")
        c, _ = client(reply({"status": "ERROR"}))
        self.assertEqual(api.search("holo", MAP, NOW, client=c)["error"], "service")
        c, _ = client(reply({"status": "OK", "result": []}))
        self.assertTrue(api.search("holo", MAP, NOW, client=c)["ok"])

    def test_the_words_of_a_failure_are_russian_by_default(self):
        c, _ = client((0, b""))
        self.assertEqual(api.search("holo", MAP, NOW, client=c)["message"], ml.text(api.MESSAGES["network"]))
        self.assertNotEqual(ml.text(api.MESSAGES["network"]), api.MESSAGES["network"])

    def test_no_bearer_is_auth_and_nothing_is_sent(self):
        c, sender = client(reply({}), token=lambda: "")
        self.assertEqual(api.search("holo", MAP, NOW, client=c)["error"], "auth")
        self.assertEqual(sender.calls, [])

    def test_a_401_reads_the_bearer_again_and_tries_once_more_with_a_new_one(self):
        reads = []

        def token():
            reads.append(1)
            return "Bearer OLD" if len(reads) == 1 else "Bearer NEW"
        c, sender = client((401, b""), reply(SEARCH), token=token)
        self.assertTrue(api.search("holo", MAP, NOW, client=c)["ok"])
        self.assertEqual([s["headers"]["authorization"] for s in sender.calls], ["Bearer OLD", "Bearer NEW"])

    def test_a_401_with_the_same_bearer_is_auth_after_one_call(self):
        c, sender = client((401, b""))
        self.assertEqual(api.search("holo", MAP, NOW, client=c)["error"], "auth")
        self.assertEqual(len(sender.calls), 1)

    def test_the_bearer_is_the_one_in_the_settings_of_the_addon(self):
        path = os.path.join(TMP, "addon_data", "plugin.video.sweettv", "settings.xml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.assertEqual(api.bearer(), "")
        with open(path, "w", encoding="utf-8") as f:
            f.write('<settings version="2"><setting id="logged">true</setting><setting id="bearer">%s</setting></settings>' % TOKEN)
        self.assertEqual(api.bearer(), TOKEN)
        self.assertEqual((signin.sweettv_setting("logged"), signin.sweettv_setting("nothing")), ("true", None))
        self.assertTrue(signin.sweettv_signed_in())
        with open(path, "w", encoding="utf-8") as f:
            f.write('<settings version="2"><setting id="logged">false</setting><setting id="bearer"></setting></settings>')
        self.assertEqual((api.bearer(), signin.sweettv_signed_in()), ("", False))

    def test_the_transport_never_raises(self):
        self.assertEqual(api.transport("http://127.0.0.1:1/", {}, b"{}", 0.2), (0, b""))
        self.assertEqual(api.transport("not a url", {}, b"{}", 0.2), (0, b""))


class Day(unittest.TestCase):
    def setUp(self):
        _clear_default_sweetstore()

    def rows(self, day=DAY_START + 43200):
        c, _ = client(reply(DAY))
        return api.day("15", day, MAP, NOW, client=c, tr=ENGLISH)

    def test_the_programmes_that_are_on_during_the_day_in_time_order_each_once(self):
        found = self.rows()
        self.assertEqual((found["ok"], found["cid"], found["name"], found["date"]), (True, "15", "СТБ", "2026-11-23"))
        self.assertEqual([r["epg"] for r in found["items"]], ["8001", "8002", "8003", "8004"])     # 8005 starts at midnight: the next day
        self.assertEqual((found["archive_days"], found["future_days"], found["now"]), (7, 3, NOW))
        first = found["items"][0]
        self.assertEqual((first["start"], first["stop"], first["title"], first["when"]),
                         (1795390200, 1795393800, "Нічний показ", "Sun 22 Nov 23:30"))

    def test_the_pictures_are_https_from_the_extended_one_else_the_plain_one(self):
        by = {r["epg"]: r for r in self.rows()["items"]}
        self.assertEqual([by[e]["preview"] for e in ("8001", "8002", "8003", "8004")],
                         ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg", "https://cdn.example/c-ext.jpg", ""])
        self.assertEqual([api.https(v) for v in (None, 5, "ftp://x/y", "", "http://a/b", "//a/b", "https://a/b")],
                         ["", "", "", "", "https://a/b", "https://a/b", "https://a/b"])

    def test_what_can_be_played_from_the_archive_and_the_episode(self):
        by = {r["epg"]: r for r in self.rows()["items"]}
        self.assertEqual([by[e]["playable_in_archive"] for e in ("8001", "8002", "8003", "8004")], [True, True, False, True])
        self.assertEqual([by[e]["live"] for e in by], [False] * 4)
        self.assertEqual((by["8004"]["season"], by["8004"]["episode"], by["8004"]["show_id"]), (2, 7, "321"))
        self.assertEqual((by["8001"]["season"], by["8001"]["episode"], by["8001"]["show_id"]), (0, 0, ""))

    def test_a_programme_on_now_is_live(self):
        c, _ = client(reply(DAY))
        found = api.day("15", DAY_START + 3600, MAP, 1795460000, client=c, tr=ENGLISH)
        self.assertEqual([r["epg"] for r in found["items"] if r["live"]], ["8004"])

    def test_the_request_is_the_channel_call_around_noon_of_the_day(self):
        c, sender = client(reply(DAY))
        api.day("15", DAY_START + 100, MAP, NOW, client=c)
        call = sender.calls[0]
        self.assertEqual(call["url"], "https://api.sweet.tv/TvService/GetChannels.json")
        self.assertEqual(call["body"], {"channels": [15], "epg_current_time": DAY_START + 43200, "epg_limit_prev": 30, "epg_limit_next": 30,
                                        "need_epg": True, "need_list": True, "need_categories": False, "need_offsets": False,
                                        "need_hash": False, "need_icons": False, "need_big_icons": False})

    def test_which_days_may_be_asked_for(self):
        today = date.fromtimestamp(NOW)
        stb, plain = MAP["15"], MAP["16"]
        for days, expect in ((0, ""), (-7, ""), (-8, "too_old"), (3, ""), (4, "too_far"), (-30, "too_old")):
            self.assertEqual(api.check_day(stb, today + timedelta(days=days), NOW), expect, days)
        self.assertEqual(api.check_day(plain, today, NOW), "")                                       # no archive: today only, back
        self.assertEqual(api.check_day(plain, today - timedelta(days=1), NOW), "too_old")
        self.assertEqual(api.check_day({**stb, "epg_days_future": 1}, today + timedelta(days=2), NOW), "too_far")
        self.assertEqual(api.check_day({**stb, "epg_days_future": 1}, today + timedelta(days=1), NOW), "")
        self.assertEqual(api.check_day({**stb, "catchup_duration": None}, today - timedelta(days=1), NOW), "")    # one day when it does not say
        self.assertEqual(api.check_day({**stb, "catchup_duration": None}, today - timedelta(days=2), NOW), "too_old")
        self.assertEqual(api.check_day({**stb, "catchup_duration": 90}, today - timedelta(days=31), NOW), "too_old")   # never more than 30
        self.assertEqual(api.check_day(None, today, NOW), "unknown")
        self.assertEqual(api.check_day({**stb, "available": False}, today - timedelta(days=1), NOW), "too_old")

    def test_a_refused_day_asks_nothing_and_says_why_in_words(self):
        c, sender = client(reply(DAY))
        for cid, unix, code in (("15", DAY_START - 8 * 86400, "too_old"), ("15", NOW + 5 * 86400, "too_far"), ("77", NOW, "unknown"),
                                ("x", NOW, "unknown"), ("15", "later", "bad_date"), ("15", True, "bad_date"), ("15", 10 ** 30, "bad_date")):
            found = api.day(cid, unix, MAP, NOW, client=c, tr=ENGLISH)
            self.assertEqual((found["ok"], found["error"], found["message"]), (False, code, api.MESSAGES[code]), code)
        self.assertEqual(sender.calls, [])

    def test_a_failed_call_is_a_small_result(self):
        for code, answer in (("network", (0, b"")), ("service", (500, b"")), ("auth", (401, b""))):
            c, _ = client(answer)
            self.assertEqual(api.day("15", NOW, MAP, NOW, client=c, tr=ENGLISH)["error"], code)

    def test_odd_programmes_never_raise(self):
        c, _ = client(reply({"status": "OK", "list": [None, 5, {"id": 99}, {"id": 15, "epg": "x"}]}))
        self.assertEqual(api.day("15", NOW, MAP, NOW, client=c)["items"], [])
        c, _ = client(reply({"status": "OK"}))
        self.assertEqual(api.day("15", NOW, MAP, NOW, client=c)["items"], [])

    def test_a_programme_of_a_day_is_remembered_for_playing(self):
        self.rows()
        self.assertEqual(api.recall("15", "8002", NOW), {"start": 1795393800, "stop": 1795402800, "available": True})

    def busy_server(self, per_day=72, step=1200):
        """A service that counts programmes: `step` s each, `per_day` a day, 30 before and 30 after the moment it was asked for."""
        starts = [DAY_START - 3 * 86400 + n * step for n in range(10 * per_day)]

        def by(call):
            body = call["body"]
            moment = body["epg_current_time"]
            before = [s for s in starts if s <= moment][-body["epg_limit_prev"]:]
            after = [s for s in starts if s > moment][:body["epg_limit_next"]]
            epg = [{"id": s // 60, "text": "P%d" % (s // step), "time_start": str(s), "time_stop": str(s + step), "available": True}
                   for s in before + after]
            return reply({"status": "OK", "list": [{"id": 15, "epg": epg}]})
        return by

    def test_a_busy_day_that_does_not_fit_in_one_call_is_asked_for_again_until_covered(self):
        c, sender = client(by=self.busy_server())
        found = api.day("15", DAY_START + 100, MAP, NOW, client=c)
        self.assertEqual(len(found["items"]), 72)
        self.assertEqual(found["items"][0]["start"], DAY_START)
        self.assertEqual(found["items"][-1]["stop"], DAY_START + 86400)
        self.assertEqual(found["items"], sorted(found["items"], key=lambda r: r["start"]))
        self.assertLessEqual(len(sender.calls), 1 + 2 * api.DAY_EXTEND)
        self.assertGreater(len(sender.calls), 1)

    def test_a_quiet_day_is_one_call_and_an_edge_of_the_archive_ends_the_asking(self):
        c, sender = client(by=self.busy_server(per_day=24, step=3600))
        self.assertEqual(len(api.day("15", DAY_START + 100, MAP, NOW, client=c)["items"]), 24)
        self.assertEqual(len(sender.calls), 1)
        late = {"id": 1, "text": "Late", "time_start": DAY_START + 50000, "time_stop": DAY_START + 60000, "available": True}
        c, sender = client(reply({"status": "OK", "list": [{"id": 15, "epg": [late]}]}))
        self.assertEqual([r["epg"] for r in api.day("15", DAY_START + 100, MAP, NOW, client=c)["items"]], ["1"])
        self.assertLessEqual(len(sender.calls), 1 + 2 * api.DAY_EXTEND)                              # it stopped: nothing new came


class Routes(unittest.TestCase):
    """The phone routes, and that what they return plays through the existing /play."""

    def setUp(self):
        self.api = api._default
        self.addCleanup(setattr, api, "_default", self.api)
        self.slim = ml.slim(CHANNELS)
        _clear_default_sweetstore()

    def serve(self, *answers, by=None):
        api._default, sender = client(*answers, by=by)
        return sender

    def get(self, path):
        orig, clock = ps.channels, ps.time
        ps.channels, ps.time = (lambda: self.slim), types.SimpleNamespace(time=lambda: NOW)
        try:
            return ps.get(path, None)
        finally:
            ps.channels, ps.time = orig, clock

    def test_search_gives_the_rows_of_the_api(self):
        sender = self.serve(reply(SEARCH))
        body, status = self.get("/api/sweettv/search?q=%D0%A5%D0%BE%D0%BB%D0%BE%D1%81%D1%82%D1%8F%D0%BA")
        self.assertEqual(status, 200)
        self.assertEqual(sender.calls[0]["body"], {"needle": "Холостяк"})
        self.assertEqual(body["ok"], True)
        self.assertEqual([r["kind"] for r in body["items"]], ["show_tv"] + ["programme"] * 3 + ["channel", "movie", "person"])
        self.assertEqual(body["items"][0]["episodes"][1]["more"], "ещё 2 показа")

    def test_a_short_needle_is_an_empty_answer_and_asks_nothing(self):
        sender = self.serve(reply(SEARCH))
        for path in ("/api/sweettv/search?q=x", "/api/sweettv/search", "/api/sweettv/search?q="):
            body, status = self.get(path)
            self.assertEqual((status, body["items"], body["short"]), (200, [], True), path)
        self.assertEqual(sender.calls, [])

    def test_a_failure_is_an_error_text_with_a_status(self):
        for answer, status in (((0, b""), 502), ((500, b""), 502), ((200, b"x"), 502), ((401, b""), 409)):
            self.serve(answer)
            body, code = self.get("/api/sweettv/search?q=holo")
            self.assertEqual((code, set(body)), (status, {"error"}), answer)
            self.assertTrue(body["error"])

    def test_day_gives_the_programmes_of_one_channel_on_one_date(self):
        sender = self.serve(reply(DAY))
        body, status = self.get("/api/sweettv/day?cid=15&date=2026-11-23")
        self.assertEqual((status, body["ok"], body["date"]), (200, True, "2026-11-23"))
        self.assertEqual([r["epg"] for r in body["items"]], ["8001", "8002", "8003", "8004"])
        self.assertEqual(sender.calls[0]["body"]["channels"], [15])

    def test_day_refuses_a_wrong_channel_or_date_or_a_day_outside_what_the_channel_keeps(self):
        sender = self.serve(reply(DAY))
        today = date.fromtimestamp(NOW)
        cases = (("cid=15&date=nope", 400), ("cid=15&date=2026-13-40", 400), ("cid=15", 400), ("cid=x&date=2026-11-23", 400),
                 ("date=2026-11-23", 400), ("cid=77&date=%s" % today, 404), ("cid=15&date=%s" % (today - timedelta(days=8)), 409),
                 ("cid=15&date=%s" % (today + timedelta(days=4)), 409), ("cid=16&date=%s" % (today - timedelta(days=1)), 409))
        for query, status in cases:
            body, code = self.get("/api/sweettv/day?" + query)
            self.assertEqual((code, set(body)), (status, {"error"}), query)
        self.assertEqual(sender.calls, [])
        self.assertEqual(self.get("/api/sweettv/day?cid=15&date=%s" % (today - timedelta(days=7)))[1], 200)      # the last day of the archive
        self.assertEqual(self.get("/api/sweettv/day?cid=15&date=%s" % (today + timedelta(days=3)))[1], 200)      # the last day of the guide

    def test_the_routes_need_the_libraries(self):
        orig = ps.api
        ps.api = None
        try:
            for path in ("/api/sweettv/search?q=holo", "/api/sweettv/day?cid=15&date=2026-11-23"):
                self.assertEqual(self.get(path)[1], 503)
        finally:
            ps.api = orig

    def test_a_programme_that_search_returned_plays_through_the_play_route_and_no_other_does(self):
        raw = CHANNELS
        self.assertRaises(pw.Refused, ps.play_request, raw, {"cid": 15, "epg": 9002}, NOW)          # not in the guide, not returned yet
        self.serve(reply(SEARCH))
        self.get("/api/sweettv/search?q=holo")
        self.assertEqual(ps.play_request(raw, {"cid": 15, "epg": 9002}, NOW), (ml.url(15, 9002, 0), "9002", 0))
        self.assertEqual(ps.play_request(raw, {"cid": "15", "epg": "9002", "at": 120}, NOW)[2], 120)
        self.assertEqual(ps.play_request(raw, {"cid": 15, "epg": 9002, "at": 10 ** 6}, NOW)[2], 5399)      # into the programme, not past it
        for body, code in (({"cid": 15, "epg": 9001}, 404),        # a repeat that was folded into the row
                           ({"cid": 15, "epg": 9010}, 409),        # still to come
                           ({"cid": 15, "epg": 9030}, 409),        # out of the archive
                           ({"cid": 16, "epg": 9002}, 404)):       # another channel
            with self.assertRaises(pw.Refused) as why:
                ps.play_request(raw, body, NOW)
            self.assertEqual(why.exception.code, code, body)

    def test_a_programme_that_day_returned_plays_the_same_way_and_one_of_the_guide_is_still_the_guides(self):
        self.serve(reply(DAY))
        self.get("/api/sweettv/day?cid=15&date=2026-11-23")
        self.assertEqual(ps.play_request(CHANNELS, {"cid": 15, "epg": 8002, "at": "start"}, NOW), (ml.url(15, 8002, 0), "8002", 0))
        with self.assertRaises(pw.Refused) as why:
            ps.play_request(CHANNELS, {"cid": 15, "epg": 8003}, NOW)                                  # available: false
        self.assertEqual(why.exception.code, 409)
        listed = {"id": 7, "text": "In the guide", "time_start": NOW - 3600, "time_stop": NOW - 600, "available": True}
        guide = {"list": [{**CHANNELS["list"][0], "epg": [listed]}]}
        self.assertEqual(ps.play_request(guide, {"cid": 15, "epg": 7}, NOW)[1], "7")


class Words(unittest.TestCase):
    def test_every_text_has_russian_and_ukrainian(self):
        words = ml._dictionary()
        for msgid in (*api.MESSAGES.values(), *api.WEEKDAYS, *api.MONTHS, api.MORE_ONE, api.MORE_MANY):
            self.assertTrue(words.TEXT.get(msgid, {}).get("ru") and words.TEXT[msgid].get("uk"), msgid)
        self.assertEqual([words.TEXT[api.MORE_MANY][lang].count("|") for lang in ("ru", "uk")], [2, 2])


CONFIG, COLLECTIONS, MOVIES, TOP = (
    fixture("sweettv-config.json"),
    fixture("sweettv-collections.json"),
    fixture("sweettv-movies.json"),
    fixture("sweettv-top.json"),
)


class VodAndCatalog(unittest.TestCase):
    def test_quality_id_mapping(self):
        for q, expected in (("720p", 1), ("1080p", 2), ("unlimited", 3), (None, 2), ("bad", 2)):
            self.assertEqual(api.quality_id(q), expected, q)

    def test_owner_of_prefers_preferred_external_id_pair_then_first_then_owners(self):
        self.assertEqual(api.owner_of({"id": 9558, "external_id_pairs": [{"owner_id": 12}, {"owner_id": 69, "preferred": True}], "owners": None}), 69)
        self.assertEqual(api.owner_of({"id": 1, "external_id_pairs": [{"owner_id": 12}, {"owner_id": 34}], "owners": [99]}), 12)
        self.assertEqual(api.owner_of({"id": 2, "external_id_pairs": [], "owners": [42]}), 42)
        self.assertEqual(api.owner_of({"id": 3}), 0)

    def test_configuration_normalizes_and_caches_for_600s(self):
        clock = Clock(NOW)
        c, sender = client(reply(CONFIG), clock=clock)
        first = api.configuration(client=c)
        self.assertTrue(first["ok"])
        self.assertIn("genres", first)
        self.assertIn("sort_modes", first)
        self.assertEqual([m["id"] for m in first["sort_modes"]], [1, 2, 3, 5, 6])
        clock.now += 599
        second = api.configuration(client=c)
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(second["sort_modes"], first["sort_modes"])
        clock.now += 2
        api.configuration(client=c)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(sender.calls[0]["url"], "https://api.sweet.tv/MovieService/GetConfiguration.json")

    def test_configuration_reads_live_title_or_name_filters_blank_sort_modes_and_parses_countries(self):
        live_cfg = {
            "status": "OK",
            "genres": [
                {"id": 61, "title": "Все фильмы"},
                {"id": 4, "title": "  Комедии  "},
                {"id": 14, "name": "Боевики"},
                {"id": 15, "title": "", "name": "Драмы"},
                {"id": 16, "title": "Триллеры", "name": "Legacy"},
                {"id": 20, "title": "   "},
                {"id": 21},
                {"title": "Без ID"},
                None,
                5,
            ],
            "sort_modes": [
                {"id": 1, "title": "По умолчанию"},
                {"id": 2, "name": "По рейтингу"},
                {"id": 3, "title": "   "},
                {"id": 5, "title": "", "name": "Недавно добавленные"},
                {"id": 6},
                {"id": 99, "title": "Неизвестный"},
            ],
            "countries": [
                {"id": 47, "title": "США"},
                {"id": "18", "name": "Великобритания"},
                {"id": 33, "title": "  Франція  "},
                {"id": 90, "title": "   "},
                {"title": "Без ID"},
                None,
            ],
        }
        c_live, _ = client(reply(live_cfg))
        res = api.configuration(client=c_live)
        self.assertTrue(res["ok"])
        self.assertEqual(res["genres"], [
            {"id": 61, "name": "Все фильмы"},
            {"id": 4, "name": "Комедии"},
            {"id": 14, "name": "Боевики"},
            {"id": 15, "name": "Драмы"},
            {"id": 16, "name": "Триллеры"},
        ])
        self.assertEqual(res["sort_modes"], [
            {"id": 1, "name": "По умолчанию"},
            {"id": 2, "name": "По рейтингу"},
            {"id": 5, "name": "Недавно добавленные"},
        ])
        self.assertEqual(res["countries"], [
            {"id": 47, "name": "США"},
            {"id": 18, "name": "Великобритания"},
            {"id": 33, "name": "Франція"},
        ])

        c_name, _ = client(reply(CONFIG))
        legacy = api.configuration(client=c_name)
        self.assertTrue(legacy["ok"])
        self.assertEqual(legacy["countries"], [])
        self.assertEqual([g["name"] for g in legacy["genres"]], ["Фильмы", "Сериалы", "Шоу", "Комедия", "Ultra HD"])

    def test_vod_detail_maps_numeric_country_ids_via_live_configuration_and_preserves_strings(self):
        live_cfg = {
            "status": "OK",
            "genres": [
                {"id": 4, "title": "Комедии"},
                {"id": 14, "title": "Боевики"},
            ],
            "sort_modes": [{"id": 1, "title": "По умолчанию"}],
            "countries": [
                {"id": 47, "title": "США"},
                {"id": 18, "title": "Великобритания"},
                {"id": 33, "name": "Франція"},
            ],
        }

        def make_by(movie_doc):
            def by(call):
                if call["url"].endswith("GetConfiguration.json"):
                    return reply(live_cfg)
                if call["url"].endswith("GetMovieInfo.json"):
                    return reply({"status": "OK", "movies": [movie_doc]})
                return reply({"status": "OK"})
            return by

        with tempfile.TemporaryDirectory() as td:
            st = sweetstore.SweetStore(os.path.join(td, "countries.db"))
            self.addCleanup(st.close)

            # 1. Live genres + mixed numeric and non-numeric countries (47 -> США, "33" -> Франція, "Україна" unchanged)
            c1, s1 = client(by=make_by({
                "id": 7101,
                "title": "Поліцейська академія",
                "genres": [4, 14],
                "countries": [47, "33", "Україна"],
                "availability_info": {"available": True},
                "seasons": [],
            }))
            det1 = api.vod_detail(7101, client=c1, tr=ENGLISH, store=st)
            self.assertTrue(det1["ok"])
            self.assertEqual(
                (det1["genre_names"], det1["countries"]),
                (["Комедии", "Боевики"], ["США", "Франція", "Україна"]),
            )

            c_off, _ = client((0, b""))
            det1_cached = api.vod_detail(7101, client=c_off, tr=ENGLISH, store=st)
            self.assertTrue(det1_cached["ok"])
            self.assertEqual(det1_cached["genre_names"], ["Комедии", "Боевики"])
            self.assertEqual(det1_cached["countries"], ["США", "Франція", "Україна"])

            # 2. Boundary: empty genres=[] with numeric countries still fetches GetConfiguration.json
            c2, s2 = client(by=make_by({
                "id": 7102,
                "title": "Іноземний фільм",
                "genres": [],
                "countries": ["47", 18],
                "availability_info": {"available": True},
                "seasons": [],
            }))
            det2 = api.vod_detail(7102, client=c2, tr=ENGLISH, store=st)
            self.assertTrue(det2["ok"])
            self.assertEqual(det2["genre_names"], [])
            self.assertEqual(det2["countries"], ["США", "Великобритания"])
            self.assertTrue(any(c["url"].endswith("GetConfiguration.json") for c in s2.calls))

            # 3. Adjacent negative: empty genres=[] and only non-numeric countries keeps strings without extra config call
            c3, s3 = client(by=make_by({
                "id": 7103,
                "title": "Локальний фільм",
                "genres": [],
                "countries": ["Україна", "Польща"],
                "availability_info": {"available": True},
                "seasons": [],
            }))
            det3 = api.vod_detail(7103, client=c3, tr=ENGLISH, store=st)
            self.assertTrue(det3["ok"])
            self.assertEqual(det3["countries"], ["Україна", "Польща"])
            self.assertFalse(any(c["url"].endswith("GetConfiguration.json") for c in s3.calls))

    def test_catalog_page_movies_filters_tvod_uhd_and_ignores_watch_info(self):
        def by(call):
            if call["url"].endswith("GetGenreMovies.json"):
                gid = call["body"]["genre_id"]
                if gid == 61:
                    return reply({"status": "OK", "movies": [9558, 9559, 9560, 1001]})
                if gid == 1:
                    return reply({"status": "OK", "movies": [1001]})
                if gid == 3:
                    return reply({"status": "OK", "movies": []})
            if call["url"].endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            return reply({"status": "OK"})

        c, sender = client(by=by)
        res = api.catalog_page("movies", genre_id=0, sort_mode_id=1, offset=0, limit=30, quality="1080p", client=c)
        self.assertTrue(res["ok"])
        ids = [m["id"] for m in res["items"]]
        self.assertEqual(ids, [9558])
        m = res["items"][0]
        self.assertEqual((m["owner_id"], m["year"], m["imdb"]), (69, 2024, 8.2))
        self.assertNotIn("watch_info", m)

        res_4k = api.catalog_page("movies", genre_id=0, quality="unlimited", client=c)
        self.assertEqual([x["id"] for x in res_4k["items"]], [9558, 9560])

    def test_catalog_page_series_unions_genre_1_and_collections_type_3(self):
        def by(call):
            if call["url"].endswith("GetGenreMovies.json"):
                return reply({"status": "OK", "movies": [9558]})
            if call["url"].endswith("GetCollections.json"):
                self.assertEqual(call["body"], {"type": 3})
                return reply({"status": "OK", "collections": [{"id": 301, "id_list": [9559, 9560]}]})
            if call["url"].endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            return reply({"status": "OK"})

        c, _ = client(by=by)
        res = api.catalog_page("series", quality="unlimited", client=c)
        self.assertTrue(res["ok"])
        self.assertEqual([x["id"] for x in res["items"]], [9558, 9560])

    def test_shows_unifies_movie_and_epg_collections_without_promo_slogans(self):
        epg_info = {
            "status": "OK",
            "collections": [
                {"id": 801, "title": "Холостяк", "poster_url": "https://img.example/801-p.jpg",
                 "secondary_id_list": [501, 502]},
                {"id": 802, "title": "Найкращі шоу тижня",
                 "secondary_id_list": [601, 602]},
            ],
        }
        epg_records = {
            "status": "OK",
            "list": [
                {"id": 501, "channel_id": 15, "text": "Холостяк. Випуск 1", "time_start": NOW - 7200, "time_stop": NOW - 3600,
                 "tv_show_id": 111, "image_url": "https://img.example/501.jpg", "available": True},
                {"id": 502, "channel_id": 15, "text": "Холостяк. Випуск 2", "time_start": NOW - 3600, "time_stop": NOW - 1800,
                 "tv_show_id": 111, "available": True},
                {"id": 601, "channel_id": 15, "text": "МастерШеф. Випуск 1", "time_start": NOW - 7200, "time_stop": NOW - 3600,
                 "tv_show_id": 222, "image_url": "https://img.example/601.jpg", "available": True},
                {"id": 602, "channel_id": 15, "text": "Супермама. Випуск 1", "time_start": NOW - 3600, "time_stop": NOW - 1800,
                 "tv_show_id": 333, "image_url": "https://img.example/602.jpg", "available": True},
            ],
        }

        def by(call):
            url = call["url"]
            if url.endswith("GetCollections.json"):
                return reply(COLLECTIONS)
            if url.endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            if url.endswith("GetCollectionInfo.json"):
                return reply(epg_info)
            if url.endswith("GetEpgRecords.json"):
                return reply(epg_records)
            return reply({"status": "OK"})

        channels = {"list": [
            {"id": 15, "name": "СТБ", "catchup": True, "catchup_duration": 7, "available": True, "epg": [
                {"id": 700, "text": "Destination X", "time_start": NOW - 3600, "time_stop": NOW - 1800, "tv_show_id": 444, "available": True},
                {"id": 501, "text": "Холостяк. Випуск 1", "time_start": NOW - 7200, "time_stop": NOW - 3600, "tv_show_id": 111, "available": True},
            ]}
        ]}
        c, _ = client(by=by)
        res = api.shows(channels, now=NOW, quality="1080p", client=c, tr=ENGLISH)
        self.assertTrue(res["ok"])
        titles = [item["title"] for item in res["items"]]
        self.assertNotIn("Промо-слоган не должен попасть в карточку", titles)
        self.assertIn("Зрадники", titles)
        self.assertIn("Холостяк", titles)
        self.assertIn("МастерШеф", titles)
        self.assertIn("Супермама", titles)
        self.assertIn("Destination X", titles)
        vod_item = next(x for x in res["items"] if x["title"] == "Зрадники")
        self.assertEqual((vod_item["kind"], vod_item["id"], vod_item["owner_id"]), ("show_vod", "vod:9558", 69))

    def test_vod_detail_and_show_detail_vod_use_local_resume_and_favs_never_watch_info(self):
        extended_movie = {
            "status": "OK",
            "movies": [{
                "id": 9558,
                "title": "Зрадники",
                "year": 2024,
                "duration": 3600,
                "rating_imdb": 8.2,
                "poster_url": "https://img.example/9558-p.jpg",
                "external_id_pairs": [{"owner_id": 69, "preferred": True}],
                "availability_info": {"available": True},
                "watch_info": {"position": 999},
                "seasons": [{
                    "id": 1,
                    "title": "Сезон 1",
                    "owner_id": 69,
                    "episodes": [
                        {"id": 101, "number": 1, "title": "Епізод 1", "duration": 2400, "preview_url": "https://img.example/e1.jpg", "available": True},
                        {"id": 102, "number": 2, "title": "Епізод 2", "duration": 2400, "preview_url": "https://img.example/e2.jpg", "available": True},
                    ],
                }],
            }],
        }
        c, _ = client(reply(extended_movie))
        local = {"v": 1, "items": {
            "sw:vod:9558|101": {"pos": 500, "total": 2400, "done": False, "at": NOW},
            "sw:vod:9558|102": {"pos": 0, "total": 2400, "done": True, "at": NOW},
        }, "live": {}}
        favs = {"show:vod:9558"}
        detail = api.vod_detail(9558, local=local, favs=favs, client=c, tr=ENGLISH)
        self.assertTrue(detail["ok"])
        self.assertTrue(detail["favourite"])
        eps = detail["seasons"][0]["episodes"]
        self.assertEqual((eps[0]["resume"], eps[0]["watched"]), (500, False))
        self.assertEqual((eps[1]["resume"], eps[1]["watched"]), (0, True))

        show_res = api.show_detail("vod:9558", CHANNELS, now=NOW, local=local, favs=favs, client=c, tr=ENGLISH)
        self.assertTrue(show_res["ok"])
        self.assertEqual(len(show_res["seasons"][0]["episodes"]), 2)

    def test_vod_link_resolves_owner_and_first_episode_and_never_logs_secret_url(self):
        extended_series = {
            "status": "OK",
            "movies": [{
                "id": 9558,
                "title": "Зрадники",
                "duration": 2400,
                "external_id_pairs": [{"owner_id": 69, "preferred": True}],
                "availability_info": {"available": True},
                "seasons": [{
                    "id": 1,
                    "title": "Сезон 1",
                    "owner_id": 77,
                    "episodes": [
                        {"id": 101, "number": 1, "title": "Епізод 1", "duration": 2400, "available": True},
                    ],
                }],
            }],
        }
        link_reply = {
            "status": "OK",
            "http_stream": {"host": {"address": "vod-cdn.example"}, "url": "/vod/9558/101/index.m3u8?token=SECRET-STREAM"},
            "scheme": "HTTP_HLS",
            "license_url": "https://drm.example/widevine",
        }
        c, sender = client(reply(extended_series), reply(link_reply))
        res = api.vod_link(9558, episode_id=None, owner_id=0, quality="720p", client=c, tr=ENGLISH)
        self.assertTrue(res["ok"])
        self.assertEqual(res["protocol"], "hls")
        self.assertIn("SECRET-STREAM", res["url"])
        self.assertEqual(res["license_url"], "https://drm.example/widevine")
        get_link_call = sender.calls[-1]
        self.assertEqual(get_link_call["url"], "https://api.sweet.tv/MovieService/GetLink.json")
        self.assertEqual(get_link_call["body"]["owner_id"], 77)
        self.assertEqual(get_link_call["body"]["episode_id"], 101)
        self.assertEqual(get_link_call["body"]["video_quality_id"], 1)

    def test_top_search_and_search_mark_playable_movies_preserve_image_and_hide_uhd(self):
        c, sender = client(reply(TOP))
        res = api.top_search(MAP, now=NOW, quality="1080p", client=c, tr=ENGLISH)
        self.assertTrue(res["ok"])
        self.assertEqual(sender.calls[0]["url"], "https://api.sweet.tv/SearchService/GetTop.json")
        titles = [r["title"] for r in res["items"]]
        self.assertIn("Зрадники", titles)
        self.assertIn("СТБ HD", titles)
        self.assertNotIn("Космос 4K", titles)
        self.assertNotIn("UHD 4K", titles)
        avail_movie = next(r for r in res["items"] if r["title"] == "Зрадники")
        tvod_movie = next(r for r in res["items"] if r["title"] == "Платний фільм TVOD")
        self.assertTrue(avail_movie["playable"])
        self.assertEqual(avail_movie["vod_url"], ml.vod_url(9558, None, 0))
        self.assertEqual(avail_movie["image_url"], "https://img.example/top-9558.jpg")
        self.assertFalse(tvod_movie["playable"])
        self.assertEqual(tvod_movie["image_url"], "https://img.example/top-9559.jpg")

        res_4k = api.top_search(MAP, now=NOW, quality="unlimited", client=c, tr=ENGLISH, include_unavailable=True)
        self.assertIn("Космос 4K", [r["title"] for r in res_4k["items"]])
        self.assertIn("UHD 4K", [r["title"] for r in res_4k["items"]])

    def test_live_singular_collection_and_epg_collections_use_col_id_and_epg_records(self):
        def by_series(call):
            url = call["url"]
            if url.endswith("GetGenreMovies.json"):
                return reply({"status": "OK", "movies": [9558]})
            if url.endswith("GetCollections.json"):
                return reply({"status": "OK", "collection": [{"id": 301, "id_list": [9559, 9560]}]})
            if url.endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            return reply({"status": "OK"})

        c, _ = client(by=by_series)
        series_res = api.catalog_page("series", quality="unlimited", client=c)
        self.assertTrue(series_res["ok"])
        self.assertEqual([x["id"] for x in series_res["items"]], [9558, 9560])

        c_empty, _ = client(by=lambda call: (
            reply({"status": "OK", "movies": [9558]}) if call["url"].endswith("GetGenreMovies.json")
            else reply(MOVIES) if call["url"].endswith("GetMovieInfo.json")
            else reply({"status": "OK"})
        ))
        self.assertEqual([x["id"] for x in api.catalog_page("series", quality="1080p", client=c_empty)["items"]], [9558])

        col_info_calls = []

        def by_shows(call):
            url = call["url"]
            if url.endswith("GetCollections.json"):
                if call["body"] == {"type": 3}:
                    return reply({"status": "OK", "collection": [{"id": 301, "id_list": [9558]}]})
                if call["body"] == {"type": 7}:
                    return reply({"status": "OK", "collection": [
                        {"id": 8838, "type": "Epg", "id_list": [15]},
                        {"id": 8839, "type": "Channel", "id_list": [16]},
                    ]})
            if url.endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            if url.endswith("GetCollectionInfo.json"):
                col_info_calls.append(call["body"])
                return reply({"status": "OK", "collections": [
                    {"id": 8838, "title": "Холостяк", "poster_url": "https://img.example/8838.jpg",
                     "secondary_id_list": [931394511]},
                ]})
            if url.endswith("GetEpgRecords.json"):
                return reply({"status": "OK", "epg_records": [
                    {"id": 931394511, "channel_id": 15, "text": "Холостяк. Випуск 6",
                     "time_start": NOW - 20000, "time_stop": NOW - 2480,
                     "tv_show_id": 111, "image_url": "https://img.example/931.jpg", "available": True},
                ]})
            return reply({"status": "OK"})

        c2, _ = client(by=by_shows)
        res = api.shows(CHANNELS, now=NOW, quality="1080p", client=c2, tr=ENGLISH)
        self.assertTrue(res["ok"])
        self.assertEqual(len(col_info_calls), 1)
        self.assertEqual(col_info_calls[0]["id_list"], [8838])
        ids = [x["id"] for x in res["items"]]
        self.assertIn("vod:9558", ids)
        self.assertIn("epg:8838", ids)

    def test_shows_reads_collection_posters_list_and_show_detail_posts_id_list(self):
        ci_calls = []

        def by(call):
            url = call["url"]
            if url.endswith("GetCollections.json"):
                return reply({"status": "OK", "collection": (
                    [{"id": 8838, "type": "Epg", "id_list": [15]}] if call["body"] == {"type": 7} else []
                )})
            if url.endswith("GetCollectionInfo.json"):
                ci_calls.append(call["body"])
                return reply({"status": "OK", "collections": [{
                    "id": 8838,
                    "title": "Холостяк",
                    "posters": [{"orientation": "Horizontal", "original_poster_url": "https://img.example/col8838.png"}],
                    "secondary_id_list": [931394511],
                }]})
            if url.endswith("GetEpgRecords.json"):
                return reply({"status": "OK", "epg_records": [
                    {"id": 931394511, "channel_id": 15, "text": "Холостяк. Випуск 6",
                     "time_start": NOW - 20000, "time_stop": NOW - 2480, "tv_show_id": 111, "available": True},
                ]})
            return reply({"status": "OK"})

        c2, _ = client(by=by)
        res = api.shows(CHANNELS, now=NOW, quality="1080p", client=c2, tr=ENGLISH)
        epg_item = next(x for x in res["items"] if x["id"] == "epg:8838")
        self.assertEqual(epg_item["poster"], "https://img.example/col8838.png")
        self.assertEqual(epg_item["banner"], "https://img.example/col8838.png")
        det = api.show_detail("epg:8838", CHANNELS, now=NOW, client=c2, tr=ENGLISH)
        self.assertTrue(det["ok"])
        self.assertEqual(det["title"], "Холостяк")
        self.assertEqual(len(det["episodes"]), 1)
        self.assertGreaterEqual(len(ci_calls), 1)
        for call_body in ci_calls:
            self.assertEqual(call_body["id_list"], [8838])

    def test_shows_and_show_detail_accept_both_raw_and_channel_map(self):
        self.assertEqual(api.channel_map(MAP), MAP)
        self.assertEqual(api.channel_map(None), {})
        self.assertEqual(api.channel_map({"list": []}), {})

        def by(call):
            url = call["url"]
            if url.endswith("GetCollections.json"):
                return reply({"status": "OK", "collection": (
                    [{"id": 8838, "type": "Epg", "id_list": [15]}] if call["body"] == {"type": 7} else []
                )})
            if url.endswith("GetCollectionInfo.json"):
                return reply({"status": "OK", "collections": [
                    {"id": 8838, "title": "Холостяк", "secondary_id_list": [931394511]},
                ]})
            if url.endswith("GetEpgRecords.json"):
                return reply({"status": "OK", "epg_records": [
                    {"id": 931394511, "channel_id": 15, "text": "Холостяк. Випуск 6",
                     "time_start": NOW - 20000, "time_stop": NOW - 2480,
                     "tv_show_id": 111, "available": True},
                ]})
            return reply({"status": "OK"})

        raw = {"list": [{**CHANNELS["list"][0], "epg": [
            {"id": 700, "text": "Destination X", "time_start": NOW - 3600, "time_stop": NOW - 1800,
             "tv_show_id": 444, "available": True},
        ]}]}
        mapped = api.channel_map(raw)
        c1, _ = client(by=by)
        c2, _ = client(by=by)
        s_raw = api.shows(raw, now=NOW, client=c1, tr=ENGLISH)
        s_map = api.shows(mapped, now=NOW, client=c2, tr=ENGLISH)
        self.assertEqual([x["id"] for x in s_raw["items"]], [x["id"] for x in s_map["items"]])
        self.assertIn("tv:444", [x["id"] for x in s_raw["items"]])
        self.assertIn("epg:8838", [x["id"] for x in s_raw["items"]])

        for show_key in ("epg:8838", "tv:444"):
            d_raw = api.show_detail(show_key, raw, now=NOW, client=client(by=by)[0], tr=ENGLISH)
            d_map = api.show_detail(show_key, mapped, now=NOW, client=client(by=by)[0], tr=ENGLISH)
            self.assertTrue(d_raw["ok"], show_key)
            self.assertEqual(len(d_raw["episodes"]), len(d_map["episodes"]), show_key)

    def test_show_detail_epg_remembers_episodes_for_recall_and_play_and_exposes_fields(self):
        _clear_default_sweetstore()

        def by(call):
            url = call["url"]
            if url.endswith("GetCollectionInfo.json"):
                return reply({"status": "OK", "collections": [
                    {"id": 8838, "title": "Холостяк", "poster_url": "https://img.example/8838.jpg",
                     "secondary_id_list": [931394511, 931394512]},
                ]})
            if url.endswith("GetEpgRecords.json"):
                return reply({"status": "OK", "epg_records": [
                    {"id": 931394511, "channel_id": 15, "text": "Холостяк. Випуск 6",
                     "time_start": NOW - 20000, "time_stop": NOW - 2480,
                     "image_url": "https://img.example/931.jpg", "available": True},
                    {"id": 931394512, "channel_id": 15, "text": "Холостяк. Випуск 7",
                     "time_start": NOW + 3600, "time_stop": NOW + 7200,
                     "available": False},
                ]})
            return reply({"status": "OK"})

        local = {"v": 1, "items": {
            "sw:15|931394511": {"pos": 420, "total": 17520, "done": False, "at": NOW},
        }, "live": {}}
        c, _ = client(by=by)
        detail = api.show_detail("epg:8838", CHANNELS, now=NOW, local=local, client=c, tr=ENGLISH)
        self.assertTrue(detail["ok"])
        self.assertEqual(len(detail["episodes"]), 2)
        ep6 = next(e for e in detail["episodes"] if e["epg"] == "931394511")
        ep7 = next(e for e in detail["episodes"] if e["epg"] == "931394512")
        self.assertEqual((ep6["preview"], ep6["duration"], ep6["channel_name"], ep6["resume"], ep6["watched"], ep6["available"]),
                         ("https://img.example/931.jpg", 17520, "СТБ", 420, False, True))
        self.assertTrue(ep6["when"])
        self.assertEqual((ep7["available"], ep7["resume"], ep7["watched"]), (False, 0, False))
        self.assertEqual(api.recall("15", "931394511", NOW),
                         {"start": NOW - 20000, "stop": NOW - 2480, "available": True})
        self.assertEqual(ps.play_request(CHANNELS, {"cid": 15, "epg": 931394511}, NOW),
                         (ml.url(15, 931394511, 0), "931394511", 0))
        with self.assertRaises(pw.Refused) as why:
            ps.play_request(CHANNELS, {"cid": 15, "epg": 931394512}, NOW)
        self.assertEqual(why.exception.code, 409)

    def test_base_show_title_strips_season_episode_markers_and_deduplicates_tv_shows(self):
        cases = (
            ("Холостяк Сезон 14 Випуск 1", "Холостяк"),
            ("Холостяк. Випуск 6", "Холостяк"),
            ("Шоу Season 2 Episode 5", "Шоу"),
            ("Шоу Сезон 1 Серія 3", "Шоу"),
            ("Шоу Сезон 1 Серия 3", "Шоу"),
            ("Шоу Епізод 4", "Шоу"),
            ("Шоу Эпизод 4", "Шоу"),
            ("Холостяк - Сезон 14 - Випуск 1", "Холостяк"),
            ("Destination X", "Destination X"),
            ("Seasoned Chef", "Seasoned Chef"),
        )
        for raw_title, expected in cases:
            self.assertEqual(api._base_show_title(raw_title), expected, raw_title)

        channels = {"list": [{**CHANNELS["list"][0], "epg": [
            {"id": 701, "text": "МастерШеф Сезон 14 Серія 1", "time_start": NOW - 7200, "time_stop": NOW - 3600,
             "tv_show_id": 222, "available": True},
            {"id": 702, "text": "МастерШеф Сезон 14 Серія 2", "time_start": NOW - 3600, "time_stop": NOW - 1800,
             "tv_show_id": 222, "available": True},
        ]}]}
        c, _ = client(by=lambda call: reply({"status": "OK"}))
        res = api.shows(channels, now=NOW, client=c, tr=ENGLISH)
        tv_shows = [x for x in res["items"] if x["id"] == "tv:222"]
        self.assertEqual(len(tv_shows), 1)
        self.assertEqual(tv_shows[0]["title"], "МастерШеф")

    def test_vod_detail_accepts_plain_and_prefixed_ids_and_rejects_invalid(self):
        extended = {
            "status": "OK",
            "movies": [{"id": 37475, "title": "Фільм", "availability_info": {"available": True}, "seasons": []}],
        }
        for mid in ("37475", "vod:37475", 37475):
            c, sender = client(reply(extended))
            res = api.vod_detail(mid, client=c, tr=ENGLISH)
            self.assertTrue(res["ok"], mid)
            self.assertEqual(sender.calls[0]["body"]["movies"], [37475], mid)
        for bad in ("", "vod:", "vod:abc", "abc", 0, -1, None):
            c, sender = client(reply(extended))
            res = api.vod_detail(bad, client=c, tr=ENGLISH)
            self.assertFalse(res["ok"], bad)
            self.assertEqual(sender.calls, [], bad)

    def test_inline_epg_show_tv_artwork_fallback_and_non_logo_preservation(self):
        channels = {"list": [
            {
                "id": 15, "name": "СТБ HD", "catchup": True, "catchup_duration": 7, "available": True,
                "icon_v2_url": "https://img.example/stb-v2.png",
                "icon_url": "https://img.example/stb-v1.png",
                "banner_url": "https://static.sweet.tv/cdn-cgi/image/width=400/https://static.sweet.tv/stb-banner.jpg",
                "epg": [
                    {
                        "id": 8101, "text": "Супермама Сезон 8 Випуск 1",
                        "time_start": NOW - 3600, "time_stop": NOW - 1800,
                        "tv_show_id": 101, "available": True,
                    },
                    {
                        "id": 8104, "text": "Зважені та щасливі Випуск 3",
                        "time_start": NOW - 7200, "time_stop": NOW - 5400,
                        "tv_show_id": 104, "available": True,
                        "image_url": "https://img.example/show104-poster.jpg",
                    },
                ],
            },
            {
                "id": 16, "name": "1+1 Марафон", "catchup": True, "catchup_duration": 3, "available": True,
                "icon_url": "http://img.example/1plus1.png",
                "banner_url": "https://img.example/1plus1-banner.jpg",
                "epg": [
                    {
                        "id": 8102, "text": "Сніданок з 1+1 Випуск 12",
                        "time_start": NOW - 1800, "time_stop": NOW + 1800,
                        "tv_show_id": 102, "available": True,
                        "preview_url_ext": "https://static.sweet.tv/cdn-cgi/image/width=400/https://static.sweet.tv/ep102-prev.jpg",
                    },
                ],
            },
            {
                "id": 17, "name": "Новий Канал", "catchup": True, "catchup_duration": 3, "available": True,
                "icon_v2_url": "https://img.example/novy.png",
                "epg": [
                    {
                        "id": 8103, "text": "Хто зверху Сезон 13 Випуск 4",
                        "time_start": NOW - 5400, "time_stop": NOW - 3600,
                        "tv_show_id": 103, "available": True,
                    },
                ],
            },
            {
                "id": 18, "name": "Bare Channel", "catchup": True, "catchup_duration": 3, "available": True,
                "epg": [
                    {
                        "id": 8105, "text": "Без картинки Випуск 1",
                        "time_start": NOW - 3600, "time_stop": NOW - 1800,
                        "tv_show_id": 105, "available": True,
                    },
                ],
            },
        ]}
        with tempfile.TemporaryDirectory() as td:
            st = sweetstore.SweetStore(os.path.join(td, "shows.db"))
            self.addCleanup(st.close)
            c, _ = client(by=lambda call: reply({"status": "OK"}))
            res = api.shows(channels, now=NOW, client=c, tr=ENGLISH, store=st)
        self.assertTrue(res["ok"])
        by_id = {x["id"]: x for x in res["items"]}

        # 1. Missing image_url falls back to channel icon_v2_url (art_mode='logo') and channel banner_url (_hq_url)
        s101 = by_id["tv:101"]
        self.assertEqual(s101["poster"], "https://img.example/stb-v2.png")
        self.assertEqual(s101.get("art_mode"), "logo")
        self.assertEqual(s101["banner"], "https://static.sweet.tv/stb-banner.jpg")

        # 2. Missing icon_v2_url falls back to icon_url (https), and preview_url_ext wins over channel banner_url
        s102 = by_id["tv:102"]
        self.assertEqual(s102["poster"], "https://img.example/1plus1.png")
        self.assertEqual(s102.get("art_mode"), "logo")
        self.assertEqual(s102["banner"], "https://static.sweet.tv/ep102-prev.jpg")

        # 3. Missing preview_url and missing channel banner_url falls back banner to poster
        s103 = by_id["tv:103"]
        self.assertEqual(s103["poster"], "https://img.example/novy.png")
        self.assertEqual(s103.get("art_mode"), "logo")
        self.assertEqual(s103["banner"], "https://img.example/novy.png")

        # 4. Adjacent negative: programme WITH image_url keeps its poster and does NOT set art_mode='logo'
        s104 = by_id["tv:104"]
        self.assertEqual(s104["poster"], "https://img.example/show104-poster.jpg")
        self.assertNotEqual(s104.get("art_mode", ""), "logo")
        self.assertEqual(s104["banner"], "https://static.sweet.tv/stb-banner.jpg")

        # 5. Adjacent boundary: neither programme image_url nor channel icon exists -> empty poster, not art_mode='logo'
        s105 = by_id["tv:105"]
        self.assertEqual(s105["poster"], "")
        self.assertNotEqual(s105.get("art_mode", ""), "logo")
        self.assertEqual(s105["banner"], "")


class FieldFixesTest(unittest.TestCase):
    def test_normalize_search_list_channels_and_hq_url(self):
        ch_list = {"list": [{"id": 15, "name": "1+1", "catchup": True, "catchup_duration": 7}]}
        now = 1750000000
        reply = {"result": [
            {"type": "EpgRecord", "id": "931394511", "sub_id": "15", "text": "Холостяк", "time_start": now - 300, "time_stop": now + 300},
            {"type": "Movie", "id": "999", "text": "Холостяк шоу"},
        ]}
        rows = api.normalize_search(reply, ch_list, now=now)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["playable"])
        self.assertTrue(rows[1]["playable"])
        self.assertEqual(
            api._hq_url("https://static.sweet.tv/cdn-cgi/image/width=400,f=auto/https://static.sweet.tv/b.jpg"),
            "https://static.sweet.tv/b.jpg",
        )


class GroupedSearchTest(unittest.TestCase):
    def test_search_groups_episodes_into_show_tv_and_detects_series(self):
        ch_list = {"list": [{"id": 15, "name": "1+1", "catchup": True, "catchup_duration": 7}]}
        now = 1750000000
        search_doc = {"status": "OK", "result": [
            {"type": "EpgRecord", "id": "901", "sub_id": "15", "tv_show_id": 111, "text": "Холостяк. Випуск 5", "time_start": now - 7200, "time_stop": now - 3600},
            {"type": "EpgRecord", "id": "902", "sub_id": "15", "tv_show_id": 111, "text": "Холостяк. Випуск 6", "time_start": now - 3600, "time_stop": now - 1800},
            {"type": "Movie", "id": "500", "text": "Футурама", "genres": [1]},
        ]}
        rows = api.normalize_search(search_doc, ch_list, now=now)
        self.assertEqual([r["kind"] for r in rows], ["series", "show_tv"])
        self.assertEqual(rows[1]["episodes_count"], 2)
        self.assertIn("store", inspect.signature(api.search).parameters, "api.search must accept store parameter")
        self.assertIn("store", inspect.signature(api.show_detail).parameters, "api.show_detail must accept store parameter")
        with tempfile.TemporaryDirectory() as td:
            st = sweetstore.SweetStore(os.path.join(td, "sweettv.db"))
            self.addCleanup(st.close)
            c, _ = client(reply(search_doc))
            found = api.search("Холостяк", ch_list, now=now, client=c, store=st)
            self.assertTrue(found["ok"])
            det = api.show_detail(rows[1]["id"], ch_list, now=now, client=client((0, b""))[0], store=st)
            self.assertTrue(det["ok"])
            self.assertEqual(len(det["episodes"]), 2)


class SweetStoreIntegrationTest(unittest.TestCase):
    """Verify SweetStore ACL wiring, zero _known/_SEARCH_SHOWS globals, can_archive, and rich metadata."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = sweetstore.SweetStore(os.path.join(self.tmp.name, "main.db"))
        self.other_st = sweetstore.SweetStore(os.path.join(self.tmp.name, "other.db"))

    def tearDown(self):
        self.other_st.close()
        self.st.close()
        self.tmp.cleanup()

    def test_no_module_level_known_or_search_shows_globals(self):
        for forbidden in ("_known", "_known_lock", "_SEARCH_SHOWS", "_SEARCH_SHOWS_LOCK"):
            self.assertFalse(hasattr(api, forbidden), f"mediastick_sweetapi must not define {forbidden}")

    def test_canonical_can_archive_matches_playable_in_archive_across_outputs(self):
        search_rows = api.normalize_search(SEARCH, MAP, NOW, ENGLISH, ENGLISH_N)
        prog_rows = [r for r in search_rows if r["kind"] == "programme"]
        show_eps = [ep for r in search_rows if r["kind"] == "show_tv" for ep in r.get("episodes", ())]
        self.assertTrue(prog_rows and show_eps)
        for r in prog_rows + show_eps:
            self.assertIn("can_archive", r)
            self.assertEqual(r["can_archive"], r["playable_in_archive"])
        self.assertTrue(any(r["can_archive"] for r in prog_rows + show_eps))
        self.assertTrue(any(not r["can_archive"] for r in prog_rows + show_eps))

        c_day, _ = client(reply(DAY))
        day_res = api.day("15", DAY_START + 43200, MAP, NOW, client=c_day, tr=ENGLISH)
        self.assertTrue(day_res["ok"])
        for item in day_res["items"]:
            self.assertIn("can_archive", item)
            self.assertEqual(item["can_archive"], item["playable_in_archive"])

    def test_injectable_store_isolation_and_offline_fallbacks(self):
        entrypoints = (
            ("recall", api.recall),
            ("day", api.day),
            ("vod_detail", api.vod_detail),
            ("show_detail", api.show_detail),
            ("search", api.search),
            ("top_search", api.top_search),
            ("shows", api.shows),
            ("catalog_page", api.catalog_page),
        )
        missing_store = [name for name, fn in entrypoints if "store" not in inspect.signature(fn).parameters]
        self.assertEqual(missing_store, [], f"Entrypoints missing injectable store parameter: {missing_store}")

        # 1. search() + top_search() + recall() isolated to self.st
        c_search, _ = client(reply(SEARCH))
        s_res = api.search("Холостяк", MAP, NOW, client=c_search, tr=ENGLISH, tr_n=ENGLISH_N, store=self.st)
        self.assertTrue(s_res["ok"])
        self.assertEqual(
            api.recall("15", "9002", NOW, store=self.st),
            {"start": 1795255200, "stop": 1795260600, "available": True},
        )
        self.assertIsNone(api.recall("15", "9002", NOW, store=self.other_st))

        c_top, _ = client(reply(TOP))
        top_res = api.top_search(MAP, now=NOW, quality="1080p", client=c_top, tr=ENGLISH, store=self.st)
        self.assertTrue(top_res["ok"])

        # 2. day() persists EPG into self.st and falls back to self.st on network failure
        c_day, _ = client(reply(DAY))
        d_ok = api.day("15", DAY_START + 43200, MAP, NOW, client=c_day, tr=ENGLISH, store=self.st)
        self.assertTrue(d_ok["ok"])
        self.assertEqual(
            api.recall("15", "8002", NOW, store=self.st),
            {"start": 1795393800, "stop": 1795402800, "available": True},
        )
        self.assertIsNone(api.recall("15", "8002", NOW, store=self.other_st))

        c_offline, _ = client((0, b""))
        d_cached = api.day("15", DAY_START + 43200, MAP, NOW, client=c_offline, tr=ENGLISH, store=self.st)
        self.assertTrue(d_cached["ok"])
        self.assertEqual([r["epg"] for r in d_cached["items"]], ["8001", "8002", "8003", "8004"])

        # Empty other_st still returns network failure cleanly
        d_miss = api.day("15", DAY_START + 43200, MAP, NOW, client=client((0, b""))[0], tr=ENGLISH, store=self.other_st)
        self.assertFalse(d_miss["ok"])
        self.assertEqual(d_miss["error"], "network")

        # 3. catalog_page() and shows() persist SWR/catalog into self.st and fall back when offline
        def by_catalog(call):
            url = call["url"]
            if url.endswith("GetGenreMovies.json"):
                return reply({"status": "OK", "movies": [9558] if call["body"]["genre_id"] == 61 else []})
            if url.endswith("GetMovieInfo.json"):
                return reply(MOVIES)
            if url.endswith("GetCollections.json"):
                return reply(COLLECTIONS)
            return reply({"status": "OK"})

        cat_ok = api.catalog_page("movies", genre_id=0, sort_mode_id=1, offset=0, limit=30,
                                  quality="1080p", client=client(by=by_catalog)[0], tr=ENGLISH, store=self.st)
        self.assertTrue(cat_ok["ok"])
        cat_offline = api.catalog_page("movies", genre_id=0, sort_mode_id=1, offset=0, limit=30,
                                       quality="1080p", client=client((0, b""))[0], tr=ENGLISH, store=self.st)
        self.assertTrue(cat_offline["ok"])
        self.assertEqual([m["id"] for m in cat_offline["items"]], [9558])

        shows_ok = api.shows(CHANNELS, now=NOW, quality="1080p", client=client(by=by_catalog)[0], tr=ENGLISH, store=self.st)
        self.assertTrue(shows_ok["ok"])
        shows_offline = api.shows(CHANNELS, now=NOW, quality="1080p", client=client((0, b""))[0], tr=ENGLISH, store=self.st)
        self.assertTrue(shows_offline["ok"])
        self.assertTrue(any(x["id"] == "vod:9558" for x in shows_offline["items"]))

    def test_vod_detail_and_show_detail_include_rich_metadata_and_sorted_seasons_episodes(self):
        self.assertIn("store", inspect.signature(api.vod_detail).parameters, "vod_detail() must accept store")
        self.assertIn("store", inspect.signature(api.show_detail).parameters, "show_detail() must accept store")
        unsorted_series = {
            "status": "OK",
            "movies": [{
                "id": 9558,
                "title": "Зрадники",
                "description": "Детективне реаліті-шоу у замку.",
                "age_limit": "16+",
                "age_rating": "16+",
                "genres": [3, 12],
                "countries": ["Україна", "Польща"],
                "year": 2024,
                "duration": 3600,
                "rating_imdb": 8.2,
                "poster_url": "https://img.example/9558-p.jpg",
                "external_id_pairs": [{"owner_id": 69, "preferred": True}],
                "availability_info": {"available": True},
                "seasons": [
                    {
                        "id": 20,
                        "number": 2,
                        "title": "Сезон 2",
                        "owner_id": 69,
                        "episodes": [
                            {"id": 202, "number": 2, "title": "S2E2", "duration": 2400, "available": True},
                            {"id": 201, "number": 1, "title": "S2E1", "duration": 2400, "available": True},
                        ],
                    },
                    {
                        "id": 10,
                        "number": 1,
                        "title": "Сезон 1",
                        "owner_id": 69,
                        "episodes": [
                            {"id": 103, "number": 3, "title": "S1E3", "duration": 2400, "available": True},
                            {"id": 101, "number": 1, "title": "S1E1", "duration": 2400, "available": True},
                            {"id": 102, "number": 2, "title": "S1E2", "duration": 2400, "available": True},
                        ],
                    },
                ],
            }],
        }

        def by(call):
            if call["url"].endswith("GetConfiguration.json"):
                return reply(CONFIG)
            if call["url"].endswith("GetMovieInfo.json"):
                return reply(unsorted_series)
            if call["url"].endswith("GetCollectionInfo.json"):
                return reply({
                    "status": "OK",
                    "collections": [{
                        "id": 8838,
                        "title": "Холостяк",
                        "description": "Романтичне шоу",
                        "secondary_id_list": [931394511],
                    }],
                })
            if call["url"].endswith("GetEpgRecords.json"):
                return reply({
                    "status": "OK",
                    "epg_records": [{
                        "id": 931394511,
                        "channel_id": 15,
                        "text": "Холостяк. Випуск 6",
                        "time_start": NOW - 20000,
                        "time_stop": NOW - 2480,
                        "available": True,
                    }],
                })
            return reply({"status": "OK"})

        c, _ = client(by=by)
        det = api.vod_detail(9558, client=c, tr=ENGLISH, store=self.st)
        self.assertTrue(det["ok"])
        for field in ("description", "age_rating", "genres", "genre_names", "countries", "seasons"):
            self.assertIn(field, det, field)
        self.assertEqual(det["description"], "Детективне реаліті-шоу у замку.")
        self.assertEqual(det["age_rating"], "16+")
        self.assertEqual(det["genres"], [3, 12])
        self.assertEqual(det["genre_names"], ["Шоу", "Комедия"])
        self.assertTrue(det["countries"])
        self.assertEqual([s["number"] for s in det["seasons"]], [1, 2])
        self.assertEqual([e["number"] for e in det["seasons"][0]["episodes"]], [1, 2, 3])
        self.assertEqual([e["number"] for e in det["seasons"][1]["episodes"]], [1, 2])

        # Offline fallback from self.st reconstructs sorted seasons & episodes and applies fresh local resume
        local = {"v": 1, "items": {"sw:vod:9558|102": {"pos": 600, "total": 2400, "done": False, "at": NOW}}, "live": {}}
        det_offline = api.show_detail("vod:9558", CHANNELS, now=NOW, local=local, favs={"show:vod:9558"},
                                      client=client((0, b""))[0], tr=ENGLISH, store=self.st)
        self.assertTrue(det_offline["ok"])
        self.assertTrue(det_offline["favourite"])
        self.assertEqual([s["number"] for s in det_offline["seasons"]], [1, 2])
        self.assertEqual([e["number"] for e in det_offline["seasons"][0]["episodes"]], [1, 2, 3])
        self.assertEqual(det_offline["seasons"][0]["episodes"][1]["resume"], 600)

        # EPG show_detail also exposes rich metadata fields and falls back via self.st
        epg_det = api.show_detail("epg:8838", CHANNELS, now=NOW, client=client(by=by)[0], tr=ENGLISH, store=self.st)
        self.assertTrue(epg_det["ok"])
        for field in ("description", "age_rating", "genres", "genre_names", "countries", "episodes"):
            self.assertIn(field, epg_det, field)
        self.assertIn("can_archive", epg_det["episodes"][0])
        self.assertEqual(epg_det["episodes"][0]["can_archive"], epg_det["episodes"][0]["playable_in_archive"])





class NextUpResolverTest(unittest.TestCase):
    def test_resolve_next_up_seasons_table(self):
        seasons = [
            {"id": 1, "title": "Сезон 1", "episodes": [
                {"id": 101, "episode_id": 101, "number": 1, "title": "S1E1", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "u1"},
                {"id": 102, "episode_id": 102, "number": 2, "title": "S1E2", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "u2"},
            ]},
            {"id": 2, "title": "Сезон 2", "episodes": [
                {"id": 201, "episode_id": 201, "number": 1, "title": "S2E1", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "u3"},
                {"id": 202, "episode_id": 202, "number": 2, "title": "S2E2", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "u4"},
            ]},
        ]
        # 1. Unwatched -> S1E1 start
        nu = api.resolve_next_up(seasons=seasons)
        self.assertEqual((nu["season_index"], nu["episode_index"], nu["mode"]), (0, 0, "start"))
        # 2. S1E2 watched -> advances to S2E1 next (season boundary!)
        seasons[0]["episodes"][1]["watched"] = True
        seasons[0]["episodes"][1]["resume_at"] = 100
        nu = api.resolve_next_up(seasons=seasons)
        self.assertEqual((nu["season_index"], nu["episode_index"], nu["mode"]), (1, 0, "next"))
        # 3. Unfinished S2E2 -> resumes S2E2
        seasons[1]["episodes"][1]["resume"] = 450
        seasons[1]["episodes"][1]["resume_at"] = 200
        nu = api.resolve_next_up(seasons=seasons)
        self.assertEqual((nu["season_index"], nu["episode_index"], nu["mode"], nu["resume"]), (1, 1, "resume", 450))
        # 4. Finale watched -> stays on S2E2 watched
        seasons[1]["episodes"][1]["resume"] = 0
        seasons[1]["episodes"][1]["watched"] = True
        seasons[1]["episodes"][1]["resume_at"] = 300
        nu = api.resolve_next_up(seasons=seasons)
        self.assertEqual((nu["season_index"], nu["episode_index"], nu["mode"]), (1, 1, "watched"))

    def test_resolve_next_up_flat_tv_newest_first(self):
        eps = [
            {"cid": "15", "epg": "3", "title": "Ep 3", "resume": 0, "watched": False, "resume_at": 0, "url": "u3"},
            {"cid": "15", "epg": "2", "title": "Ep 2", "resume": 0, "watched": True, "resume_at": 500, "url": "u2"},
            {"cid": "15", "epg": "1", "title": "Ep 1", "resume": 0, "watched": True, "resume_at": 100, "url": "u1"},
        ]
        nu = api.resolve_next_up(episodes=eps)
        self.assertEqual((nu["episode_index"], nu["mode"]), (0, "next"))

class HeroBannerAndWideArtTest(unittest.TestCase):
    def test_movie_card_banner_and_wide_art_table(self):
        cases = (
            (
                "banner_url_and_horizontal_poster",
                {
                    "id": 101,
                    "title": "Hero Movie",
                    "banner_url": "https://static.sweet.tv/cdn-cgi/image/width=1280/https://static.sweet.tv/banner-1280x720.jpg",
                    "horizontal_poster_url": "http://static.sweet.tv/horiz-478x267.jpg",
                    "poster_url": "https://static.sweet.tv/poster.jpg",
                },
                "https://static.sweet.tv/banner-1280x720.jpg",
                "https://static.sweet.tv/horiz-478x267.jpg",
            ),
            (
                "original_banner_url_fallback",
                {
                    "id": 102,
                    "title": "Original Banner",
                    "original_banner_url": "https://static.sweet.tv/orig-banner.jpg",
                    "horizontal_poster_url": "https://static.sweet.tv/horiz.jpg",
                    "poster_url": "https://static.sweet.tv/poster.jpg",
                },
                "https://static.sweet.tv/orig-banner.jpg",
                "https://static.sweet.tv/horiz.jpg",
            ),
            (
                "horizontal_poster_fallback_when_no_banner",
                {
                    "id": 103,
                    "title": "No Banner",
                    "horizontal_poster_url": "https://static.sweet.tv/horiz-478x267.jpg",
                    "poster_url": "https://static.sweet.tv/poster.jpg",
                },
                "https://static.sweet.tv/horiz-478x267.jpg",
                "https://static.sweet.tv/horiz-478x267.jpg",
            ),
            (
                "poster_fallback_when_only_poster",
                {
                    "id": 104,
                    "title": "Poster Only",
                    "poster_url": "https://static.sweet.tv/poster.jpg",
                },
                "https://static.sweet.tv/poster.jpg",
                "https://static.sweet.tv/poster.jpg",
            ),
            (
                "empty_urls",
                {"id": 105, "title": "Bare"},
                "",
                "",
            ),
        )
        for name, movie, exp_banner, exp_wide_art in cases:
            with self.subTest(name=name):
                card = api._movie_card(movie)
                self.assertEqual(card["banner"], exp_banner)
                self.assertEqual(card["wide_art"], exp_wide_art)

    def test_shows_sets_banner_and_wide_art_for_vod_and_epg(self):
        def by(call):
            url = call["url"]
            if url.endswith("GetCollections.json"):
                if call["body"] == {"type": 3}:
                    return reply({"status": "OK", "collection": [{"id": 301, "id_list": [9558]}]})
                if call["body"] == {"type": 7}:
                    return reply({"status": "OK", "collection": [
                        {"id": 8838, "type": "Epg", "id_list": [15]},
                        {"id": 8839, "type": "Epg", "id_list": [15]},
                        {"id": 8840, "type": "Epg", "id_list": [15]},
                    ]})
            if url.endswith("GetMovieInfo.json"):
                return reply({"status": "OK", "movies": [{
                    "id": 9558,
                    "title": "Зрадники",
                    "banner_url": "https://img.example/9558-banner-1280.jpg",
                    "horizontal_poster_url": "https://img.example/9558-wide-478.jpg",
                    "poster_url": "https://img.example/9558-poster.jpg",
                    "availability_info": {"available": True},
                }]})
            if url.endswith("GetCollectionInfo.json"):
                return reply({"status": "OK", "collections": [
                    {
                        "id": 8838,
                        "title": "Холостяк",
                        "banner_url": "https://img.example/8838-banner.jpg",
                        "horizontal_poster_url": "https://img.example/8838-wide.jpg",
                        "poster_url": "https://img.example/8838-poster.jpg",
                        "secondary_id_list": [501],
                    },
                    {
                        "id": 8839,
                        "title": "МастерШеф",
                        "horizontal_poster_url": "https://img.example/8839-wide.jpg",
                        "poster_url": "https://img.example/8839-poster.jpg",
                        "secondary_id_list": [501],
                    },
                    {
                        "id": 8840,
                        "title": "Супермама",
                        "banner_url": "https://img.example/8840-banner.jpg",
                        "poster_url": "https://img.example/8840-poster.jpg",
                        "secondary_id_list": [501],
                    },
                ]})
            if url.endswith("GetEpgRecords.json"):
                return reply({"status": "OK", "epg_records": [
                    {"id": 501, "channel_id": 15, "text": "Шоу 1", "time_start": NOW - 3600, "time_stop": NOW - 1800, "available": True},
                ]})
            return reply({"status": "OK"})

        c, _ = client(by=by)
        res = api.shows(CHANNELS, now=NOW, quality="1080p", client=c, tr=ENGLISH)
        self.assertTrue(res["ok"])
        by_id = {x["id"]: x for x in res["items"]}

        vod_item = by_id["vod:9558"]
        self.assertEqual(vod_item["banner"], "https://img.example/9558-banner-1280.jpg")
        self.assertEqual(vod_item["wide_art"], "https://img.example/9558-wide-478.jpg")

        epg_both = by_id["epg:8838"]
        self.assertEqual(epg_both["banner"], "https://img.example/8838-banner.jpg")
        self.assertEqual(epg_both["wide_art"], "https://img.example/8838-wide.jpg")

        epg_horiz_only = by_id["epg:8839"]
        self.assertEqual(epg_horiz_only["banner"], "https://img.example/8839-wide.jpg")
        self.assertEqual(epg_horiz_only["wide_art"], "https://img.example/8839-wide.jpg")

        epg_banner_only = by_id["epg:8840"]
        self.assertEqual(epg_banner_only["banner"], "https://img.example/8840-banner.jpg")
        self.assertEqual(epg_banner_only["wide_art"], "https://img.example/8840-banner.jpg")

    def test_vod_detail_and_cache_include_wide_art(self):
        movie_doc = {
            "id": 9558,
            "title": "Зрадники",
            "banner_url": "https://img.example/9558-banner.jpg",
            "horizontal_poster_url": "https://img.example/9558-wide.jpg",
            "poster_url": "https://img.example/9558-poster.jpg",
            "availability_info": {"available": True},
            "seasons": [],
        }
        c, _ = client(reply({"status": "OK", "movies": [movie_doc]}))
        det = api.vod_detail(9558, client=c, tr=ENGLISH)
        self.assertTrue(det["ok"])
        self.assertEqual(det["banner"], "https://img.example/9558-banner.jpg")
        self.assertEqual(det["wide_art"], "https://img.example/9558-wide.jpg")

        cached_with_wide = {"id": "vod:9558", "title": "Зрадники", "banner": "https://b.jpg", "wide_art": "https://w.jpg", "seasons": []}
        from_cache = api._vod_detail_from_cache(cached_with_wide, 9558, None, None)
        self.assertEqual(from_cache["wide_art"], "https://w.jpg")

        cached_legacy = {"id": "vod:9558", "title": "Зрадники", "banner": "https://b.jpg", "seasons": []}
        from_legacy = api._vod_detail_from_cache(cached_legacy, 9558, None, None)
        self.assertEqual(from_legacy["wide_art"], "https://b.jpg")


class UnreleasedEpisodesTest(unittest.TestCase):
    def test_extract_release_date_table(self):
        self.assertTrue(callable(getattr(api, "extract_release_date", None)), "mediastick_sweetapi must define extract_release_date(ep)")
        cases = (
            ({"release_date": "2026-12-03"}, "03.12.2026"),
            ({"premiere_date": "2026-01-09"}, "09.01.2026"),
            ({"available_from": 1796256000}, "03.12.2026"),          # 2026-12-03 00:00:00 UTC
            ({"air_date": "1796256000"}, "03.12.2026"),
            ({"date": "2027-05-15"}, "15.05.2027"),
            ({"release_date": "", "premiere_date": "2026-12-03"}, "03.12.2026"),
            # Negative / boundary cases
            ({}, ""),
            (None, ""),
            ({"release_date": ""}, ""),
            ({"release_date": "not-a-date"}, ""),
            ({"available_from": 999999999}, ""),                    # < 10**9
            ({"available_from": 10 ** 11}, ""),                     # >= 10**11
            ({"date": 0}, ""),
            ({"date": -100}, ""),
        )
        for ep, expected in cases:
            with self.subTest(ep=ep):
                self.assertEqual(api.extract_release_date(ep), expected)

    def test_filter_season_episodes_caps_unreleased_to_one_soon_stub(self):
        self.assertTrue(callable(getattr(api, "filter_season_episodes", None)), "mediastick_sweetapi must define filter_season_episodes()")

        # 1. Fact: 10 released episodes (duration > 0) with a truncated 4-item playable_ids preview
        #    returns all 10 playable episodes (0 coming_soon) — never gated by playable_ids.
        raw_10 = [{"id": n, "number": n, "title": f"Ep {n}", "duration": 3720 + n * 60} for n in range(1, 11)]
        f10 = api.filter_season_episodes(raw_10, playable_ids=[1, 2, 3, 4], mid=33871, s_owner=69)
        self.assertEqual([e["id"] for e in f10], list(range(1, 11)))
        self.assertTrue(all(e["playable"] and not e["coming_soon"] for e in f10))

        # 2. Boundary: duration > 0 not in playable_ids is still playable; duration == 0 even if in playable_ids
        #    is unreleased and collapses to at most 1 coming_soon stub.
        raw = [
            {"id": 4, "number": 4, "title": "Ep 4", "duration": 0, "release_date": "2026-12-03"},
            {"id": 2, "number": 2, "title": "Ep 2", "duration": 2400},
            {"id": 5, "number": 5, "title": "Ep 5", "duration": 0, "release_date": "2026-12-10"},
            {"id": 1, "number": 1, "title": "Ep 1", "duration": 2400},
            {"id": 3, "number": 3, "title": "Ep 3", "duration": 2400},
            *[{"id": n, "number": n, "title": f"Ep {n}", "duration": 0} for n in range(6, 11)],
        ]
        local = {
            "v": 1,
            "items": {
                "sw:vod:9558|2": {"pos": 321, "total": 2400, "done": False, "at": NOW},
                "sw:vod:9558|4": {"pos": 100, "total": 2400, "done": True, "at": NOW},
            },
            "live": {},
        }
        filtered = api.filter_season_episodes(raw, playable_ids=[1, 2, 3, 4], mid=9558, s_owner=69, local=local)
        self.assertEqual([e["id"] for e in filtered], [1, 2, 3, 4])
        for ep in filtered[:3]:
            self.assertFalse(ep["coming_soon"])
            self.assertTrue(ep["playable"])
            self.assertEqual(ep["release_date"], "")
            self.assertEqual(ep["vod_url"], ml.vod_url(9558, ep["id"], 69))
        self.assertEqual(filtered[1]["resume"], 321)

        stub = filtered[3]
        self.assertEqual((stub["coming_soon"], stub["playable"], stub["vod_url"]), (True, False, ""))
        self.assertEqual((stub["duration"], stub["resume"], stub["watched"], stub["resume_at"]), (0, 0, False, 0))
        self.assertEqual(stub["release_date"], "03.12.2026")

        non_playable_dur = [
            {"id": 11, "number": 1, "title": "R1", "duration": 1800},
            {"id": 12, "number": 2, "title": "R2 not in playable_ids", "duration": 1800},
            {"id": 13, "number": 3, "title": "U1 in playable_ids", "duration": 0, "premiere_date": "2026-12-20"},
            {"id": 14, "number": 4, "title": "U2", "duration": 0},
        ]
        f2 = api.filter_season_episodes(non_playable_dur, playable_ids=[11, 13], mid=9558, s_owner=69)
        self.assertEqual([e["id"] for e in f2], [11, 12, 13])
        self.assertTrue(f2[0]["playable"] and not f2[0]["coming_soon"])
        self.assertTrue(f2[1]["playable"] and not f2[1]["coming_soon"])
        self.assertTrue(f2[2]["coming_soon"] and not f2[2]["playable"])
        self.assertEqual(f2[2]["vod_url"], "")
        self.assertEqual(f2[2]["release_date"], "20.12.2026")

        # 3. Boundary: empty/None playable_ids relies on duration > 0
        f3 = api.filter_season_episodes(
            [
                {"id": 21, "number": 1, "title": "R1", "duration": 1800},
                {"id": 22, "number": 2, "title": "U1", "duration": 0},
                {"id": 23, "number": 3, "title": "U2", "duration": 0},
            ],
            playable_ids=None,
            mid=9558,
            s_owner=69,
        )
        self.assertEqual([e["id"] for e in f3], [21, 22])
        self.assertTrue(f3[1]["coming_soon"])
        self.assertEqual(f3[1]["release_date"], "")

        # 4. Negative: available is False or invalid/non-positive id ignored completely
        f4 = api.filter_season_episodes([
            {"id": 0, "number": 1, "title": "Zero", "duration": 1800},
            {"id": -5, "number": 2, "title": "Neg", "duration": 1800},
            {"number": 3, "title": "Missing", "duration": 1800},
            {"id": 31, "number": 4, "title": "Unavail", "duration": 1800, "available": False},
            {"id": 32, "number": 5, "title": "Valid", "duration": 1800, "available": True},
        ], mid=9558, s_owner=69)
        self.assertEqual([e["id"] for e in f4], [32])

        # 5. Boundary: 0 released episodes -> only 1 coming_soon stub
        f5 = api.filter_season_episodes([
            {"id": 41, "number": 1, "title": "Soon 1", "duration": 0, "release_date": "2026-12-01"},
            {"id": 42, "number": 2, "title": "Soon 2", "duration": 0, "release_date": "2026-12-08"},
        ], mid=9558, s_owner=69)
        self.assertEqual(len(f5), 1)
        self.assertEqual((f5[0]["id"], f5[0]["coming_soon"], f5[0]["playable"]), (41, True, False))

    def test_filter_season_episodes_preserves_api_order_when_number_missing(self):
        # When episodes omit number (None or absent), preserve API order and assign 1-based numbers
        raw_no_num = [
            {"id": 50, "number": None, "title": "First in API", "duration": 2400},
            {"id": 10, "title": "Second in API", "duration": 2400},
            {"id": 30, "number": 0, "title": "Third in API", "duration": 2400},
        ]
        res = api.filter_season_episodes(raw_no_num, mid=33871, s_owner=69)
        self.assertEqual([e["id"] for e in res], [50, 10, 30])
        self.assertEqual([e["number"] for e in res], [1, 2, 3])

        # Boundary: when at least one episode has an explicit positive number, sort by (ep_num, orig_idx)
        raw_with_num = [
            {"id": 50, "number": 2, "title": "Ep 2", "duration": 2400},
            {"id": 10, "number": 1, "title": "Ep 1", "duration": 2400},
        ]
        res_sorted = api.filter_season_episodes(raw_with_num, mid=33871, s_owner=69)
        self.assertEqual([e["id"] for e in res_sorted], [10, 50])
        self.assertEqual([e["number"] for e in res_sorted], [1, 2])

    def test_vod_detail_filters_unreleased_episodes_and_persists_to_store(self):
        movie_doc = {
            "id": 9558,
            "title": "Зрадники",
            "availability_info": {"available": True},
            "playable_episode_ids": [1, 2, 3, 4],
            "seasons": [{
                "id": 1,
                "number": 1,
                "title": "Сезон 1",
                "owner_id": 69,
                "episodes": [
                    {"id": 1, "number": 1, "title": "Ep 1", "duration": 2400},
                    {"id": 2, "number": 2, "title": "Ep 2", "duration": 2400},
                    {"id": 3, "number": 3, "title": "Ep 3", "duration": 2400},
                    {"id": 4, "number": 4, "title": "Ep 4", "duration": 0, "release_date": "2026-12-03"},
                    {"id": 5, "number": 5, "title": "Ep 5", "duration": 0, "release_date": "2026-12-10"},
                    {"id": 6, "number": 6, "title": "Ep 6", "duration": 0},
                ],
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            st = sweetstore.SweetStore(os.path.join(td, "unreleased.db"))
            self.addCleanup(st.close)
            c, _ = client(reply({"status": "OK", "movies": [movie_doc]}))
            det = api.vod_detail(9558, client=c, tr=ENGLISH, store=st)
            self.assertTrue(det["ok"])
            eps = det["seasons"][0]["episodes"]
            self.assertEqual([e["id"] for e in eps], [1, 2, 3, 4])
            self.assertFalse(eps[2]["coming_soon"])
            self.assertTrue(eps[2]["playable"])
            self.assertTrue(eps[3]["coming_soon"])
            self.assertFalse(eps[3]["playable"])
            self.assertEqual(eps[3]["vod_url"], "")
            self.assertEqual(eps[3]["release_date"], "03.12.2026")

            # Offline cache reconstruction preserves coming_soon, playable, release_date, vod_url=""
            c_off, _ = client((0, b""))
            det_off = api.vod_detail(9558, client=c_off, tr=ENGLISH, store=st)
            self.assertTrue(det_off["ok"])
            eps_off = det_off["seasons"][0]["episodes"]
            self.assertEqual([e["id"] for e in eps_off], [1, 2, 3, 4])
            self.assertTrue(eps_off[3]["coming_soon"])
            self.assertFalse(eps_off[3]["playable"])
            self.assertEqual(eps_off[3]["vod_url"], "")
            self.assertEqual(eps_off[3]["release_date"], "03.12.2026")

    def test_resolve_next_up_and_apply_progress_skip_coming_soon(self):
        # Season with 3 released episodes + 1 coming_soon stub: watching ep 3 must return ep 3 ("watched"), never ep 4
        seasons = [{
            "id": 1,
            "number": 1,
            "title": "Сезон 1",
            "episodes": [
                {"id": 1, "episode_id": 1, "number": 1, "title": "Ep 1", "resume": 0, "watched": True, "resume_at": 100, "vod_url": "u1", "coming_soon": False, "playable": True},
                {"id": 2, "episode_id": 2, "number": 2, "title": "Ep 2", "resume": 0, "watched": True, "resume_at": 200, "vod_url": "u2", "coming_soon": False, "playable": True},
                {"id": 3, "episode_id": 3, "number": 3, "title": "Ep 3", "resume": 0, "watched": True, "resume_at": 300, "vod_url": "u3", "coming_soon": False, "playable": True},
                {"id": 4, "episode_id": 4, "number": 4, "title": "Ep 4", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "", "coming_soon": True, "playable": False},
            ],
        }]
        nu = api.resolve_next_up(seasons=seasons)
        self.assertIsNotNone(nu)
        self.assertEqual((nu["episode_index"], nu["episode_id"], nu["mode"]), (2, 3, "watched"))

        # Season with 0 released episodes (only coming_soon stub) -> None
        only_soon = [{
            "id": 1,
            "number": 1,
            "title": "Сезон 1",
            "episodes": [
                {"id": 4, "episode_id": 4, "number": 1, "title": "Ep 1", "resume": 0, "watched": False, "resume_at": 0, "vod_url": "", "coming_soon": True, "playable": False},
            ],
        }]
        self.assertIsNone(api.resolve_next_up(seasons=only_soon))

        # apply_progress_to_seasons must not apply resume/watched to coming_soon or playable=False episodes
        local = {
            "v": 1,
            "items": {
                "sw:vod:9558|1": {"pos": 120, "total": 2400, "done": False, "at": NOW},
                "sw:vod:9558|4": {"pos": 500, "total": 2400, "done": True, "at": NOW},
            },
            "live": {},
        }
        prog_seasons = [{
            "id": 1,
            "number": 1,
            "title": "Сезон 1",
            "episodes": [
                {"id": 1, "number": 1, "title": "Ep 1", "coming_soon": False, "playable": True},
                {"id": 4, "number": 2, "title": "Ep 2", "coming_soon": True, "playable": False},
            ],
        }]
        applied = api.apply_progress_to_seasons(prog_seasons, local, movie_id=9558)
        self.assertEqual(applied[0]["episodes"][0]["resume"], 120)
        self.assertEqual((applied[0]["episodes"][1]["resume"], applied[0]["episodes"][1]["watched"], applied[0]["episodes"][1]["resume_at"]), (0, False, 0))


class EnrichEpgRecordsTest(unittest.TestCase):
    def test_enrich_epg_records_dedup_chunk_skip_and_persist(self):
        self.assertTrue(callable(getattr(api, "enrich_epg_records", None)), "mediastick_sweetapi must define enrich_epg_records()")
        with tempfile.TemporaryDirectory() as td:
            st = sweetstore.SweetStore(os.path.join(td, "enrich.db"))
            self.addCleanup(st.close)
            st.upsert_channels({
                "status": "OK",
                "list": [{"id": 15, "name": "СТБ", "catchup": True, "catchup_duration": 7, "available": True}],
            }, now=NOW)
            # Pre-seed EPG 9001 with image_url (already enriched -> should be skipped unless force=True)
            # and EPG 9002 without image_url/preview_url (missing art -> should be fetched)
            st.upsert_epg("15", [
                {"id": 9001, "text": "Already Has Art", "time_start": NOW - 7200, "time_stop": NOW - 3600,
                 "image_url": "https://img.example/9001-existing.jpg", "available": True},
                {"id": 9002, "text": "Placeholder", "time_start": NOW - 3600, "time_stop": NOW - 1800,
                 "available": True},
            ], now=NOW)

            def by(call):
                if call["url"].endswith("GetEpgRecords.json"):
                    self.assertEqual(call["body"]["image_type"], 0)
                    self.assertTrue(call["body"]["need_extended_info"])
                    ids = call["body"]["id_list"]
                    self.assertLessEqual(len(ids), 50)
                    return reply({
                        "status": "OK",
                        "epg_records": [
                            {
                                "id": eid,
                                "channel_id": 15,
                                "text": f"Real Title {eid}",
                                "image_url": f"http://img.example/epg_horizontal/{eid}.jpg",
                                "preview_url_ext": f"https://img.example/prev/{eid}.jpg",
                            }
                            for eid in ids
                        ],
                    })
                return reply({"status": "OK"})

            # 60 missing IDs (9002 + 9010..9068) + duplicate 9002 + already-cached 9001 + invalid IDs
            c, sender = client(by=by)
            req_ids = [9001, 9002, "9002", 0, -5, "bad", None] + list(range(9010, 9069))
            res = api.enrich_epg_records(req_ids, client=c, store=st, now=NOW)

            # 9001 skipped; 60 unique missing IDs chunked into 2 calls (50 + 10)
            self.assertEqual(len(sender.calls), 2)
            self.assertEqual(len(sender.calls[0]["body"]["id_list"]), 50)
            self.assertEqual(len(sender.calls[1]["body"]["id_list"]), 10)
            sent_ids = sender.calls[0]["body"]["id_list"] + sender.calls[1]["body"]["id_list"]
            self.assertNotIn(9001, sent_ids)
            self.assertIn(9002, sent_ids)
            self.assertEqual(len(set(sent_ids)), 60)

            self.assertIn("9002", res)
            self.assertEqual(res["9002"], {
                "epg": "9002",
                "cid": "15",
                "title": "Real Title 9002",
                "image_url": "https://img.example/epg_horizontal/9002.jpg",
                "preview": "https://img.example/prev/9002.jpg",
            })

            # Persisted into SweetStore; 9002 is no longer missing art
            self.assertEqual(st.epg_ids_missing_art([9001, 9002, 9010]), [])

            # Calling again with same IDs makes 0 network calls
            c2, sender2 = client(by=by)
            res2 = api.enrich_epg_records([9001, 9002, 9010], client=c2, store=st, now=NOW)
            self.assertEqual(sender2.calls, [])
            self.assertEqual(res2, {})

            # force=True re-fetches even when image_url is already present
            c3, sender3 = client(by=by)
            res3 = api.enrich_epg_records([9001], client=c3, store=st, now=NOW, force=True)
            self.assertEqual(len(sender3.calls), 1)
            self.assertEqual(sender3.calls[0]["body"]["id_list"], [9001])
            self.assertIn("9001", res3)

            # Cap to 100 unique IDs per call -> at most 2 chunks of 50
            c4, sender4 = client(by=by)
            api.enrich_epg_records(list(range(20000, 20125)), client=c4, store=st, now=NOW)
            self.assertEqual(len(sender4.calls), 2)
            self.assertEqual([len(call["body"]["id_list"]) for call in sender4.calls], [50, 50])


if __name__ == "__main__":
    unittest.main()
