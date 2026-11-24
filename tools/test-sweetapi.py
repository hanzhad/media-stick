#!/usr/bin/env python3
"""Offline test of SWEET.TV own API as the stick uses it (no Kodi, no device, no network): python3 tools/test-sweetapi.py

mediastick_sweetapi (search, the programmes of one channel on one day, the client that posts to api.sweet.tv) on recorded
shapes of the answers (tools/fixtures/sweettv-search.json, sweettv-day.json) and a fake transport; the phone routes
/api/sweettv/search and /api/sweettv/day, and that a programme they returned plays through the existing /play."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in the add-on

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
os.environ["TZ"] = "UTC"
time.tzset()
sys.path.insert(0, LIB)

import mediastick_signin as signin  # noqa: E402
import mediastick_sweetapi as api  # noqa: E402
import mediastick_sweetlive as ml  # noqa: E402
import panel_sweettv as ps  # noqa: E402
import panel_watch as pw  # noqa: E402


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
        self.assertEqual([r["epg"] for r in programmes], ["9010", "9020", "9040", "9002", "9030"])    # newest first, a title once
        self.assertEqual([r["start"] for r in programmes], sorted((r["start"] for r in programmes), reverse=True))
        six = next(r for r in programmes if r["epg"] == "9002")
        self.assertEqual((six["repeats"], six["more"]), (2, "2 more airings"))
        self.assertEqual((six["cid"], six["channel_name"], six["start"], six["stop"]), ("15", "СТБ", 1795255200, 1795260600))
        self.assertEqual([r["repeats"] for r in programmes if r["epg"] != "9002"], [0, 0, 0, 0])

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
        six = next(r for r in self.rows(ml.text, ml.text_n) if r["epg"] == "9002")
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
        by = {r["epg"]: r for r in rows_of(self.rows(), "programme")}
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
        self.assertEqual([r["kind"] for r in rows], ["programme"] * 5 + ["channel", "channel", "movie", "person"])
        stb, other = rows_of(rows, "channel")
        self.assertEqual((stb["cid"], stb["title"], stb["channel_name"], stb["playable"], stb["subtitle"]),
                         ("15", "СТБ HD", "СТБ", True, "Новини, шоу"))
        self.assertEqual((other["cid"], other["playable"]), ("99", False))
        movie, person = rows_of(rows, "movie")[0], rows_of(rows, "person")[0]
        self.assertEqual((movie["title"], movie["subtitle"], movie["playable"], movie["cid"], movie["epg"]),
                         ("Divorce Club", "2020, Comedy", False, "", ""))
        self.assertEqual((person["title"], person["playable"]), ("Іван Холостяк", False))
        self.assertEqual(len(rows), 9)                                                               # the weird kind, bad ids, no title and no start are gone

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
        c, sender = client(reply(SEARCH))
        found = api.search("  Холостяк ", MAP, NOW, client=c, tr=ENGLISH, tr_n=ENGLISH_N)
        self.assertTrue(found["ok"])
        self.assertEqual((found["query"], found["count"]), ("Холостяк", len(found["items"])))
        self.assertEqual([(s["url"], s["body"]) for s in sender.calls],
                         [("https://api.sweet.tv/SearchService/Search.json", {"needle": "Холостяк"})])
        self.assertEqual(api.recall("15", "9002", NOW), {"start": 1795255200, "stop": 1795260600, "available": True})
        self.assertIsNone(api.recall("15", "9001", NOW))                                            # folded into 9002: not offered
        self.assertIsNone(api.recall("15", "9002", NOW + api.KNOWN_TTL + 1))
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
        api._known.clear()

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
        self.assertEqual([r["kind"] for r in body["items"]], ["programme"] * 5 + ["channel", "channel", "movie", "person"])
        self.assertEqual(body["items"][3]["more"], "ещё 2 показа")

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


if __name__ == "__main__":
    unittest.main()
