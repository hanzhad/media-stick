#!/usr/bin/env python3
"""Offline test of the TV side of the onboarding channel (no Kodi, no device): python3 tools/test-onboarding-tv.py

The pure view (onboarding_view), the window that follows a document (onboarding_app), the sign-in layout in the sign-in
window, the YouTube card's use of the keys document, the two skin files and the demo. The stubbed Kodi is the one of
tools/test-accounts-tv.py."""
import importlib.util
import os
import re
import sys
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("accounts_tv", os.path.join(HERE, "test-accounts-tv.py"))
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)          # installs the xbmc stubs and the temp directories

from resources.lib import (onboarding_app, onboarding_demo, onboarding_files, onboarding_view as view,  # noqa: E402
                           remote, signin, store, ui, youtube_files)

Fake, lib, ob = tv.Fake, tv.lib, store.onboarding
SKIN, MEDIA, ADDON = tv.SKIN, tv.MEDIA, tv.ADDON
NOW = 1_700_000_000


def doc(**over):
    """A keys document as the library would hand it to the TV."""
    d = onboarding_demo.keys_doc(NOW)
    d.update(over)
    return d


def tree(name):
    return ET.parse(os.path.join(SKIN, name)).getroot()


class Parse(unittest.TestCase):
    def test_the_demo_keys_document_becomes_the_screen_of_the_mockup(self):
        s = view.parse(doc(), "YouTube")
        self.assertEqual((s.flow, s.state, s.step, s.kicker), ("keys", "active", 2, "YouTube · one-time setup"))
        self.assertEqual([(x.text, x.state) for x in s.steps],
                         [("Project and API", "done"), ("Allow TV sign-in", "now"), ("API key", "todo"), ("TV client", "todo")])
        self.assertEqual(view.header(s), "Step 2 of 4 · on the Google page tap")
        self.assertEqual([len(r) for r in s.chips], [4, 2])
        self.assertEqual(s.chips[0][2], ("Audience: External", "now"))
        self.assertEqual(s.items[0], ("API key", False))

    def test_what_is_not_a_document_is_none(self):
        for bad in (None, [], "x", 5, {}, {"flow": "keys"}, {"state": "active"}, {"flow": 3, "state": "active"},
                    {"flow": "keys", "state": "paused"}):
            self.assertIsNone(view.parse(bad), bad)

    def test_the_tv_text_is_used_and_the_phone_text_never(self):
        s = view.parse({"flow": "keys", "state": "active", "title": {"tv": "For TV", "phone": "Для телефона"},
                        "steps": [{"tv": "", "phone": "только телефон"}, {"tv": "Second", "phone": "x"}]}, "Name")
        self.assertEqual((s.title, s.kicker, [x.text for x in s.steps]), ("For TV", "Name", ["Second"]))
        self.assertEqual(s.step, 1)

    def test_odd_values_do_not_break_it(self):
        s = view.parse({"flow": "keys", "state": "active", "step": 99, "steps": "nope",
                        "chips": [5, [1], [{"t": "a", "s": "?"}]], "items": [None, {"label": "L", "s": "ok"}],
                        "code": 5, "link": "ftp://x", "title": "plain"})
        self.assertEqual((s.step, s.steps, s.code, s.link, s.title), (0, (), "", "", ""))
        self.assertEqual(s.chips, ((("a", "todo"),),))
        self.assertEqual(s.items, (("L", True),))
        clamp = view.parse({"flow": "keys", "state": "active", "step": 99, "steps": [{"tv": "a"}, {"tv": "b"}]})
        self.assertEqual(clamp.step, 2)
        self.assertEqual(view.parse({"flow": "keys", "state": "active", "step": True, "steps": [{"tv": "a"}]}).step, 1)

    def test_a_finished_flow_has_every_step_done(self):
        s = view.parse(doc(state="done"))
        self.assertEqual({x.state for x in s.steps}, {"done"})
        self.assertFalse(s.active)

    def test_caps_hold_even_when_the_file_is_not_the_librarys(self):
        s = view.parse({"flow": "keys", "state": "active", "steps": [{"tv": f"s{n}"} for n in range(20)],
                        "chips": [[{"t": "c"}] * 9] * 9, "items": [{"label": f"i{n}"} for n in range(20)]})
        self.assertEqual((len(s.steps), len(s.items)), (8, 6))
        self.assertLessEqual(len(s.chips), 4)
        self.assertLessEqual(sum(len(r) for r in s.chips), 12)

    def test_fresh_follows_expires(self):
        self.assertTrue(view.fresh({"expires": 10}, 9))
        for bad in ({"expires": 10}, {}, {"expires": True}, {"expires": "x"}, {"expires": float("nan")}, None):
            self.assertFalse(view.fresh(bad, 10), bad)

    def test_site_is_the_address_without_scheme_query_and_www(self):
        self.assertEqual(view.site("https://www.youtube.com/activate?user_code=KQX-7MD-P4W"), "youtube.com/activate")
        self.assertEqual(view.site("https://sweet.tv/addDevice?connectCode=1#x"), "sweet.tv/addDevice")


class Pieces(unittest.TestCase):
    def test_step_rows_wrap_to_two_lines_and_carry_the_state_colours(self):
        s = view.parse(doc(steps=[{"tv": "Short"}, {"tv": "A very long step " * 6}, {"tv": "Last"}], step=2))
        rows = view.step_rows(s, view.KEYS_STEP_W)
        self.assertEqual([r.state for r in rows], ["done", "now", "todo"])
        self.assertEqual(rows[0].line2, "")
        self.assertTrue(rows[1].line2)
        colour = view.STEP_TEXT["todo"]
        self.assertEqual(rows[2].props(), {"t1": f"[COLOR {colour}]Last[/COLOR]", "t2": "", "state": "todo",
                                           "num": f"[COLOR {colour}]3[/COLOR]", "ring": view.STEP_RING["todo"]})
        self.assertTrue(rows[1].props()["t2"].startswith("[COLOR "))

    def test_badges_say_set_or_dash_and_never_carry_a_value(self):
        s = view.parse(doc(items=[{"label": "API key", "s": "ok", "value": "AIzaSECRET"}, {"label": "Client ID", "s": "wait"}]))
        rows = view.badge_rows(s)
        self.assertEqual([r["t1"] for r in rows], [f"[COLOR {view.BADGE['ok'][1]}]API key · set[/COLOR]",
                                                    f"[COLOR {view.BADGE['wait'][1]}]Client ID —[/COLOR]"])
        self.assertNotIn("AIza", repr(rows))
        self.assertEqual(rows[0]["bg"], view.BADGE["ok"][0])

    def test_keys_props_and_footers(self):
        s = view.parse(doc(), "YouTube")
        props = view.keys_props(s, view.keys_footer("192.168.1.14"))
        self.assertEqual(set(props), set(view.KEYS_PROPS))
        self.assertEqual(props["footer"], "Easier on a laptop: open 192.168.1.14 in its browser · Back — close")
        self.assertEqual(props["warn"], "Publish it, or the TV gets signed out after 7 days.")
        self.assertEqual(view.keys_footer(""), "Back — close")
        self.assertEqual(view.signin_footer(True), "Back — cancel · Menu — continue without an account")
        self.assertEqual(view.signin_footer(False), "Back — cancel")

    def test_signin_props_are_all_there_and_all_empty_when_off(self):
        s = view.parse(onboarding_demo.signin_doc(NOW), "YouTube")
        on = view.signin_props(s, "cap", "foot")
        self.assertEqual(set(on), set(view.SIGNIN_PROPS))
        self.assertEqual((on["ob"], on["ob_badge"], on["ob_title"], on["ob_code"], on["ob_site"]),
                         ("1", "Y", "Continue on your phone", "KQX-7MD-P4W", "Or on any device: youtube.com/activate"))
        off = view.signin_props(None, "cap", "foot")
        self.assertEqual(set(off), set(view.SIGNIN_PROPS))
        self.assertEqual(set(off.values()), {""})
        long_code = view.parse({"flow": "signin", "state": "active", "service": "x", "code": "A" * 30})
        self.assertEqual(view.signin_props(long_code, "", "")["ob_codelong"], "1")

    def test_card_step_is_only_for_a_running_keys_flow(self):
        step = view.card_step(view.parse(doc(), "YouTube"))
        self.assertEqual((step.number, step.total, step.title, step.hint), (2, 4, "Follow along on your phone", "Allow TV sign-in"))
        for other in (None, view.parse(doc(state="done")), view.parse(doc(flow="signin")), view.parse(doc(steps=[]))):
            self.assertIsNone(view.card_step(other))


class Chips(unittest.TestCase):
    @staticmethod
    def rows(*lengths):
        return tuple(tuple((f"chip number {n}", "todo") for n in range(k)) for k in lengths)

    def test_the_mockup_rows_are_laid_out_on_two_lines_with_separators_and_then(self):
        placed = view.layout_chips(view.parse(doc()).chips)
        kinds = [p.kind for p in placed]
        self.assertEqual((kinds.count("chip"), kinds.count("then")), (6, 1))
        then = next(p for p in placed if p.kind == "then")
        self.assertEqual(then.x, 0)
        self.assertGreater(then.y, 0)
        first = [p for p in placed if p.y == 0]
        self.assertEqual(first[0].kind, "chip")

    def test_nothing_overlaps_and_everything_is_inside_the_area(self):
        for shape in ((1,), (4, 2), (12,), (3, 3, 3, 3), (6, 6), (1, 1, 1, 1)):
            lines = {}
            for p in view.layout_chips(self.rows(*shape)):
                self.assertGreaterEqual(p.x, 0)
                self.assertLessEqual(p.x + p.w, view.CHIP_AREA_W, (shape, p))
                lines.setdefault(p.y, []).append(p)
            for same in lines.values():
                same.sort(key=lambda p: p.x)
                for a, b in zip(same, same[1:]):
                    self.assertLessEqual(a.x + a.w, b.x, (shape, a, b))

    def test_a_chip_that_does_not_fit_starts_a_new_line_without_a_separator(self):
        placed = view.layout_chips(self.rows(12))
        starts = [p for p in placed if p.kind == "chip" and p.x == 0 and p.y > 0]
        self.assertTrue(starts)
        for p in starts:
            self.assertFalse([q for q in placed if q.kind == "sep" and q.y == p.y and q.x < p.x])

    def test_lines_are_capped_and_the_slot_numbers_stay_within_the_skin(self):
        placed = view.layout_chips(tuple(tuple(("x" * 40, "todo") for _ in range(3)) for _ in range(4)))
        self.assertLessEqual(max(p.y for p in placed), (view.MAX_LINES - 1) * view.LINE_H)
        for p in view.layout_chips(self.rows(12)):
            self.assertLessEqual(p.slot, {"chip": 12, "sep": 12, "then": 3}[p.kind])

    def test_props_name_every_slot_and_clear_the_unused(self):
        props = view.chip_props(view.layout_chips(view.parse(doc()).chips))
        self.assertEqual(props["chip1"], "[COLOR FFF2F3F5]Get started[/COLOR]")
        self.assertEqual(props["chip1_bg"], view.BG["done"])
        self.assertIn("[B]", props["chip3"])
        self.assertEqual((props["chip7"], props["sep1"], props["then1"], props["then2"]), ("", "›", "Then", ""))
        self.assertEqual(len([k for k in props if k.startswith("chip") and not k.endswith("_bg")]), 12)
        self.assertEqual(view.chip_props(()).get("chip1"), "")

    def test_the_warning_goes_under_the_last_line_of_chips(self):
        self.assertEqual(view.warn_offset(()), 0)
        one = view.warn_offset(view.layout_chips(self.rows(2)))
        two = view.warn_offset(view.layout_chips(self.rows(2, 2)))
        self.assertEqual(one, view.CHIP_H + view.WARN_GAP)
        self.assertEqual(two - one, view.LINE_H)


class Source:
    """A document the window reads: set .doc to what the phone side would have written."""

    def __init__(self, doc=None):
        self.doc = doc

    def read(self, service):
        return self.doc


class Window(unittest.TestCase):
    def setUp(self):
        Fake.home.clear()
        self.clock = [100.0]
        self.patches = [mock.patch.object(onboarding_app, "clock", lambda: self.clock[0]),
                        mock.patch.object(onboarding_files, "phone_address", return_value="192.168.1.14")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def dialog(self, doc=None):
        self.source = Source(doc)
        d = onboarding_app.OnboardingDialog()
        d.setup("youtube", self.source, "YouTube")
        d.closed = False
        return d

    def test_a_look_sets_the_properties_the_lists_and_places_the_chips(self):
        d = self.dialog(doc())
        d._look()
        self.assertEqual((d.getProperty("kicker"), d.getProperty("title1"), d.getProperty("title2")),
                         ("YouTube · one-time setup", "Follow along on", "your phone"))
        self.assertEqual(d.getProperty("header"), "Step 2 of 4 · on the Google page tap")
        self.assertIn("192.168.1.14", d.getProperty("footer"))
        steps, badges = d.controls[onboarding_app.STEPS], d.controls[onboarding_app.BADGES]
        self.assertEqual((len(steps.items), steps.selected, len(badges.items)), (4, 1, 3))
        self.assertEqual(steps.items[1].props["state"], "now")
        first = d.controls[onboarding_app.CHIP_IMAGE + 1]
        self.assertEqual((first.position, first.width > 0), ((onboarding_app.AREA_X, onboarding_app.AREA_Y), True))
        warn = d.controls[onboarding_app.WARN]
        self.assertEqual(warn.position[0], onboarding_app.AREA_X)
        self.assertGreater(warn.position[1], onboarding_app.AREA_Y + view.CHIP_H)
        self.assertFalse(d.closed)

    def test_only_what_changed_is_set_again(self):
        d = self.dialog(doc())
        calls = []
        d.setProperty = lambda key, value: calls.append(key)
        d._look()
        n = len(calls)
        self.assertGreater(n, 10)
        d._look()
        self.assertEqual(len(calls), n)
        self.source.doc = doc(step=3)
        d._look()
        self.assertEqual(d.controls[onboarding_app.STEPS].selected, 2)
        self.assertEqual([k for k in calls[n:]], ["header"])

    def test_a_finished_flow_stays_up_a_while_then_closes(self):
        d = self.dialog(doc(state="done"))
        d._look()
        self.assertFalse(d.closed)
        self.clock[0] += onboarding_app.LINGER["done"] - 0.1
        d._look()
        self.assertFalse(d.closed)
        self.clock[0] += 0.2
        d._look()
        self.assertTrue(d.closed)

    def test_a_document_that_is_gone_closes_after_the_grace_and_a_return_resets_it(self):
        d = self.dialog(None)
        d._look()
        self.clock[0] += onboarding_app.GONE_GRACE - 1
        self.source.doc = doc()
        d._look()
        self.clock[0] += 10
        self.source.doc = None
        d._look()
        self.assertFalse(d.closed)
        self.clock[0] += onboarding_app.GONE_GRACE + 0.1
        d._look()
        self.assertTrue(d.closed)

    def test_a_source_that_raises_is_a_missing_document(self):
        d = self.dialog(doc())
        self.source.read = mock.Mock(side_effect=OSError("disk"))
        d._look()
        self.assertFalse(d.closed)

    def test_back_closes_and_the_worker_thread_follows_the_document(self):
        d = self.dialog(doc())
        d.onAction(types_action(ui.BACK_ACTIONS))
        self.assertTrue(d.closed)
        d = self.dialog(doc())
        with mock.patch.object(onboarding_app, "POLL", 0.01), \
                mock.patch.dict(onboarding_app.LINGER, {"failed": 0.0}):
            d.onInit()
            self.assertEqual(d.getProperty("title2"), "your phone")
            self.source.doc = doc(state="failed", title={"tv": "Did not work", "phone": ""})
            end = time.monotonic() + 3
            while not d.closed and time.monotonic() < end:
                time.sleep(0.01)
            d.stop()
        self.assertTrue(d.closed)
        self.assertEqual(d.getProperty("title1"), "Did not work")
        self.assertFalse(d._thread.is_alive())

    def test_main_does_nothing_for_nothing_and_not_twice(self):
        self.assertFalse(onboarding_app.main([]))
        self.assertFalse(onboarding_app.main(["demo", "bogus"]))
        self.assertFalse(onboarding_app.main(["show"]))
        si = onboarding_app.single_instance
        Fake.home[onboarding_app.RUNNING] = si.encode(si.Flag("t", 13001, time.time() - 3600))     # Kodi says it is active
        with mock.patch.object(onboarding_app, "show") as show:
            self.assertFalse(onboarding_app.main(["demo", "keys"]))
        show.assert_not_called()
        with mock.patch.object(si, "window_active", return_value=False), \
                mock.patch.object(si, "video_playing", return_value=False), \
                mock.patch.object(onboarding_app, "show") as show:
            self.assertTrue(onboarding_app.main(["demo", "keys"]))      # the window is gone: the flag is stale
        self.assertEqual(len(show.call_args_list), 1)
        Fake.home.clear()
        with mock.patch.object(onboarding_app, "show") as show:
            self.assertTrue(onboarding_app.main(["demo", "keys"]))
            self.assertTrue(onboarding_app.main(["show", "youtube"]))
        self.assertEqual([c.args[0] for c in show.call_args_list], ["youtube", "youtube"])
        self.assertIsInstance(show.call_args_list[0].args[1], onboarding_demo.KeysSource)
        self.assertIsInstance(show.call_args_list[1].args[1], onboarding_app.LiveSource)
        self.assertEqual(Fake.home.get(onboarding_app.RUNNING), "")


def types_action(ids):
    return mock.Mock(getId=lambda: sorted(ids)[0])


class SigninLayout(unittest.TestCase):
    """The sign-in window with an onboarding document: the new layout when it is a normal waiting sign-in, the old one otherwise."""

    def waiting(self, **over):
        return tv.waiting(code="KQX-7MD-P4W", step=1, steps=1, updated=1000, url="https://www.youtube.com/activate") | over

    def screen(self, **over):
        return view.parse(onboarding_demo.signin_doc(NOW) | over, "YouTube")

    def test_the_frame_has_the_layout_the_steps_and_the_link_while_waiting(self):
        frame = signin.Follow("YouTube", 0).feed(self.waiting(), 1001, self.screen())
        self.assertEqual((frame.props["ob"], frame.props["ob_title"], frame.props["ob_code"]),
                         ("1", "Continue on your phone", "KQX-7MD-P4W"))
        self.assertEqual([r.state for r in frame.rows], ["done", "now", "todo"])
        self.assertEqual(frame.ob_link, "https://www.youtube.com/activate?user_code=KQX-7MD-P4W")
        self.assertEqual(frame.props["code"], "K Q X  -  7 M D  -  P 4 W")      # the old layout's properties stay

    def test_the_old_layout_when_there_is_no_document_or_it_is_not_for_this(self):
        f = signin.Follow("YouTube", 0)
        for ob_screen in (None, self.screen(state="done"), self.screen(flow="keys")):
            frame = f.feed(self.waiting(), 1001, ob_screen)
            self.assertEqual(frame.props["ob"], "")
            self.assertEqual((frame.rows, frame.ob_link), ((), ""))
        partner = signin.Follow("YouTube", 0).feed(self.waiting(mode="partner"), 1001, self.screen())
        self.assertEqual((partner.props["ob"], partner.props["partner"]), ("", "1"))
        self.assertEqual(signin.Follow("YouTube", 0).feed(None, 1001, self.screen()).props["ob"], "")

    def test_a_result_goes_back_to_the_plain_layout(self):
        f = signin.Follow("YouTube", 0)
        f.feed(self.waiting(), 1001, self.screen())
        frame = f.feed(tv.ended("done", 1002), 1002, self.screen(state="done"))
        self.assertEqual((frame.props["ob"], frame.props["headline"]), ("", "Signed in"))

    def test_the_window_fills_the_step_list_and_picks_the_qr(self):
        d = signin.SigninDialog()
        d.setup("youtube", signin.Follow("YouTube", 0), True, False, source=onboarding_demo.SigninSource("/tmp/phone.png"))
        with mock.patch.object(remote, "qr_png", side_effect=lambda link: "/tmp/link.png"):
            d._apply(d.follow.feed(self.waiting(), time.time(), self.screen()))
            self.assertEqual((d.getProperty("ob_qr"), d.getProperty("ob_caption")), ("/tmp/phone.png", view.QR_REMOTE))
            self.assertEqual(d.getProperty("ob_footer"), view.signin_footer(True))
            self.assertEqual(len(d.controls[signin.CONTROL_STEPS].items), 3)
            d2 = signin.SigninDialog()
            d2.setup("youtube", signin.Follow("YouTube", 0), False, False, source=onboarding_demo.SigninSource(""))
            d2._apply(d2.follow.feed(self.waiting(), time.time(), self.screen()))
        self.assertEqual((d2.getProperty("ob_qr"), d2.getProperty("ob_caption")), ("/tmp/link.png", view.QR_LINK))
        self.assertEqual(d2.getProperty("ob_footer"), "Back — cancel")

    def test_a_layout_that_cannot_be_filled_falls_back_to_the_plain_one(self):
        d = signin.SigninDialog()
        d.setup("youtube", signin.Follow("YouTube", 0), True, False, source=onboarding_demo.SigninSource(""))
        with mock.patch.object(ui, "fill_list", side_effect=RuntimeError("no control")):
            d._apply(d.follow.feed(self.waiting(), time.time(), self.screen()))
        self.assertEqual(d.getProperty("ob"), "")
        self.assertEqual(d.getProperty("code"), "K Q X  -  7 M D  -  P 4 W")

    def test_the_demo_source_answers_like_the_library_and_ends_when_cancelled(self):
        src = onboarding_demo.SigninSource("/tmp/p.png")
        self.assertEqual(src.read("youtube")["state"], "waiting")
        self.assertEqual(view.parse(src.onboarding("youtube")).step, 2)
        src.request_cancel("youtube")
        self.assertEqual((src.read("youtube")["state"], src.onboarding("youtube")), ("cancelled", None))
        self.assertFalse(src.asked_partner("youtube"))
        self.assertEqual(src.phone_qr(), "/tmp/p.png")


def guide_doc(link):
    d = store.lib.guide.document("youtube", "active", "KQX-7MD-P4W", link)
    d.update(v=1, service="youtube", updated=NOW, expires=NOW + 120)
    return d


class SigninText(unittest.TestCase):
    def test_the_line_under_the_code_is_the_providers_page_and_the_step_words_are_in_the_rows(self):
        link = "https://www.google.com/device"
        screen = view.parse(guide_doc(link), "YouTube")
        props = view.signin_props(screen, "", "")
        self.assertEqual((props["ob_site"], props["ob_code"]), ("Or on any device: google.com/device", "KQX-7MD-P4W"))
        self.assertEqual(props["ob_kicker"], "YouTube · sign in")
        rows = [r.props() for r in view.step_rows(screen, view.SIGNIN_STEP_W)]
        self.assertEqual(len(rows), 3)
        for row, step in zip(rows, screen.steps):
            self.assertTrue(row["t1"].startswith("[COLOR "))
            self.assertIn(step.text.split()[0], row["t1"])
        self.assertIn("type the code", rows[0]["t1"])
        window = signin.SigninDialog()
        window.setup("youtube", signin.Follow("YouTube", 0), True, False, source=onboarding_demo.SigninSource(""))
        state = tv.waiting(code="KQX-7MD-P4W", step=1, steps=1, updated=1000, url=link) | {"link": link}
        with mock.patch.object(remote, "qr_png", side_effect=lambda l: l):
            frame = window.follow.feed(state, 1001, screen)
            window._apply(frame)
        self.assertEqual((frame.ob_link, window.getProperty("ob_qr")), (link, link))      # the QR holds the page itself
        items = window.controls[signin.CONTROL_STEPS].items
        self.assertEqual(len(items), 3)
        self.assertIn("Sign-in page opened", items[0].props["t1"])


class KeysCard(unittest.TestCase):
    def setUp(self):
        for name in os.listdir(ob.DIR) if os.path.isdir(ob.DIR) else []:
            os.unlink(os.path.join(ob.DIR, name))

    def test_the_card_reads_the_keys_document_and_nothing_else(self):
        self.assertIsNone(youtube_files.read_keys_guide())
        ob.write("youtube", doc(), now=int(time.time()))
        guide = youtube_files.read_keys_guide()
        self.assertEqual((guide.flow, guide.step, len(guide.steps)), ("keys", 2, 4))
        ob.write("youtube", doc(flow="signin"))
        self.assertIsNone(youtube_files.read_keys_guide())
        ob.write("youtube", doc(state="done"))
        self.assertIsNone(youtube_files.read_keys_guide())
        ob.write("youtube", doc(), now=int(time.time()) - 10_000)
        self.assertIsNone(youtube_files.read_keys_guide())

    def test_the_demo_documents_are_ones_the_writer_would_accept(self):
        for name, make in (("keys", onboarding_demo.keys_doc), ("signin", onboarding_demo.signin_doc)):
            d = make(NOW)
            self.assertTrue(ob.write("youtube", d, now=NOW), name)
            self.assertEqual(ob.read("youtube", now=NOW)["flow"], name)
        self.assertEqual(onboarding_demo.SCENARIOS, ("signin", "keys"))
        self.assertEqual(view.parse(onboarding_demo.KeysSource().read("youtube")).flow, "keys")

    def test_files_never_raise(self):
        with mock.patch.object(store, "onboarding", None):
            self.assertIsNone(onboarding_files.read("youtube"))
        with mock.patch.object(store.onboarding, "read", side_effect=RuntimeError("x")):
            self.assertIsNone(onboarding_files.read("youtube"))
        with mock.patch.object(onboarding_files.net, "address", side_effect=OSError):
            self.assertEqual(onboarding_files.phone_address(), "")
        with mock.patch.object(onboarding_files.sweettv_files, "phone_page", side_effect=OSError):
            self.assertEqual(onboarding_files.phone_qr(), "")

    def test_the_wizard_opens_the_window_once_for_each_wizard(self):
        from resources.lib import youtube_app
        app = youtube_app.YouTube.__new__(youtube_app.YouTube)
        app._guide_up = False
        Fake.builtins.clear()
        guide = view.parse(doc(), "YouTube")
        app._open_guide(guide)
        app._open_guide(guide)
        self.assertEqual(Fake.builtins, ["RunScript(script.media-stick.home,onboarding,show,youtube)"])
        app._open_guide(None)
        app._open_guide(guide)
        self.assertEqual(len(Fake.builtins), 2)


class Skin(unittest.TestCase):
    NAME = "script-media-stick-onboarding.xml"

    def ids(self, root):
        return {int(c.get("id")) for c in root.iter("control") if c.get("id", "").isdigit()}

    def test_every_control_the_window_moves_or_fills_is_there(self):
        want = {onboarding_app.STEPS, onboarding_app.BADGES, onboarding_app.WARN}
        want |= {base + n for base in (onboarding_app.CHIP_IMAGE, onboarding_app.CHIP_LABEL, onboarding_app.SEPARATOR)
                 for n in range(1, view.MAX_CHIPS + 1)}
        want |= {onboarding_app.THEN + n for n in range(1, view.THEN_SLOTS + 1)}
        self.assertLessEqual(want, self.ids(tree(self.NAME)))

    def test_every_property_the_skin_reads_is_set_by_the_python(self):
        text = "".join(ET.tostring(tree(self.NAME), encoding="unicode").split())
        read = set(re.findall(r"Window\.Property\((\w+)\)", text))
        s = view.parse(doc(), "YouTube")
        set_by_python = set(view.keys_props(s, "")) | set(view.chip_props(view.layout_chips(s.chips)))
        self.assertLessEqual(read, set_by_python)
        row_props = set(re.findall(r"ListItem\.Property\((\w+)\)", text))
        self.assertLessEqual(row_props, set(view.step_rows(s, 400)[0].props()) | set(view.badge_rows(s)[0]))

    def test_the_sign_in_skin_reads_only_what_the_python_sets(self):
        text = "".join(ET.tostring(tree("script-media-stick-signin.xml"), encoding="unicode").split())
        read = {p for p in re.findall(r"Window\.Property\((ob\w*)\)", text)}
        self.assertLessEqual(read, set(view.SIGNIN_PROPS) | {"ob_qr"})
        self.assertTrue({"ob", "ob_title", "ob_code", "ob_qr", "ob_footer"} <= read)
        rows = set(re.findall(r"ListItem\.Property\((\w+)\)", text))
        self.assertLessEqual(rows, set(view.Row("a", "", "now", "1").props()))

    def test_a_card_a_dim_backdrop_and_no_animation(self):
        root = tree(self.NAME)
        self.assertEqual(list(root.iter("animation")), [])
        text = ET.tostring(root, encoding="unicode")
        self.assertIn("D9080B10", text)
        self.assertIn("MsTitle", text)

    def test_the_texture_budget_for_the_busiest_screen_is_within_34(self):
        count = 0
        def images(node):
            """Textures one row shows: the plain ones, plus one of the pair that excludes each other (done mark / ring)."""
            found = [c for c in node.iter("control") if c.get("type") == "image"]
            return len([c for c in found if c.find("visible") is None]) + (1 if any(c.find("visible") is not None for c in found) else 0)

        root = tree(self.NAME).find("controls")
        listed = set()
        for lst, limit in (("list", view.MAX_STEPS), ("panel", view.MAX_ITEMS)):
            for node in root.iter("control"):
                if node.get("type") == lst:
                    layout = max(images(node.find("itemlayout")), images(node.find("focusedlayout")))
                    count += layout * limit
                    listed |= {id(c) for c in node.iter("control")}
        count += len([c for c in root.iter("control") if c.get("type") == "image" and id(c) not in listed])
        self.assertLessEqual(count, 34)

    def test_art_exists_and_is_small(self):
        for png in ("onboarding-done.png", "onboarding-ring.png", "onboarding-chip.png"):
            path = os.path.join(MEDIA, png)
            self.assertTrue(os.path.exists(path), png)
            self.assertLess(os.path.getsize(path), 20000, png)
            self.assertIn(png, ET.tostring(tree(self.NAME), encoding="unicode"))

    def test_the_xml_is_valid_for_xmllint(self):
        for name in (self.NAME, "script-media-stick-signin.xml"):
            self.assertEqual(tree(name).tag, "window")


class Text(unittest.TestCase):
    """The step rows and the badges were drawn without their words on a TV: a list item's <textcolor> taken from a
    ListItem property is not a colour Kodi can use there. These pin what the skins and fill_list must do instead."""
    FILES = ("script-media-stick-onboarding.xml", "script-media-stick-signin.xml")

    @staticmethod
    def label_controls(root):
        """(list control, layout, label control) for every label in a list's or panel's layouts."""
        for lst in root.iter("control"):
            if lst.get("type") in ("list", "panel", "fixedlist", "wraplist"):
                for layout in list(lst.findall("itemlayout")) + list(lst.findall("focusedlayout")):
                    for c in layout.iter("control"):
                        if c.get("type") == "label":
                            yield lst, layout, c

    def test_no_colour_in_a_list_layout_comes_from_a_property(self):
        for name in self.FILES:
            for lst, _, label in self.label_controls(tree(name)):
                for tag in ("textcolor", "selectedcolor", "focusedcolor", "shadowcolor"):
                    value = label.findtext(tag)
                    if value is not None:
                        self.assertRegex(value, r"^[0-9A-Fa-f]{8}$", f"{name} list {lst.get('id')} <{tag}>")

    def test_every_label_in_a_list_has_a_text_source_that_the_rows_set(self):
        rows = view.step_rows(view.parse(doc(), "YouTube"), view.KEYS_STEP_W)
        sources = {"onboarding": {k for r in rows for k in r.props()} | set(view.badge_rows(view.parse(doc()))[0]),
                   "signin": {k for r in rows for k in r.props()}}
        for name in self.FILES:
            known = sources["onboarding" if "onboarding" in name else "signin"]
            labels = list(self.label_controls(tree(name)))
            self.assertTrue(labels, name)
            for lst, _, label in labels:
                text = label.findtext("label") or ""
                self.assertTrue(text, f"{name} list {lst.get('id')}: a label with no text")
                props = re.findall(r"ListItem\.Property\((\w+)\)", text)
                self.assertTrue(props or "ListItem.Label" in text, f"{name}: {text}")
                self.assertLessEqual(set(props), known, f"{name}: {text}")
                self.assertGreater(int(label.findtext("width")), 0)
                self.assertGreater(int(label.findtext("height")), 0)

    def test_fill_list_hands_the_words_to_the_items_and_they_are_not_empty(self):
        s = view.parse(doc(items=[{"label": "API key", "s": "ok"}, {"label": "Client ID", "s": "wait"}]), "YouTube")
        window = tv.Window()
        ui.fill_list(window, 20, [r.props() for r in view.step_rows(s, view.KEYS_STEP_W)], select=1)
        ui.fill_list(window, 30, view.badge_rows(s))
        steps, badges = window.controls[20].items, window.controls[30].items
        self.assertIn("Project and API", steps[0].props["t1"])
        self.assertTrue(all(i.props["t1"] and i.props["num"] for i in steps))
        self.assertTrue(all(i.props["t1"] and "[COLOR " in i.props["t1"] for i in badges))
        self.assertIn("API key · set", badges[0].props["t1"])
        self.assertEqual(steps[0].label, steps[0].props["t1"])

    def test_a_nine_slice_texture_is_uniform_where_it_is_stretched(self):
        """A texture drawn with border=B is stretched between B and size-B: there it must not change along the stretch,
        or the ends of a pill come out with spiky leaf corners (pill.png, 96 px, is round only from border 47 up)."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL is not installed")
        for name in self.FILES:
            for tag in ("texture", "texturefocus", "texturenofocus"):
                for elem in tree(name).iter(tag):
                    border = elem.get("border")
                    if not border or "$" in elem.text or elem.text == "card-shadow.png":   # the shadow is a soft gradient
                        continue
                    b = int(border.split(",")[0])
                    im = Image.open(os.path.join(MEDIA, elem.text)).convert("RGBA")
                    w, h = im.size
                    self.assertLessEqual(2 * b, w, elem.text)
                    for y in range(h):
                        row = [im.getpixel((x, y)) for x in range(b, w - b)]
                        self.assertLessEqual(max((max(abs(a - c) for a, c in zip(p, row[0])) for p in row), default=0), 24,
                                             f"{name} {elem.text} border {b}: row {y} changes where it is stretched")
                    for x in range(w):
                        col = [im.getpixel((x, y)) for y in range(b, h - b)]
                        self.assertLessEqual(max((max(abs(a - c) for a, c in zip(p, col[0])) for p in col), default=0), 24,
                                             f"{name} {elem.text} border {b}: column {x} changes where it is stretched")

    def test_a_bordered_picture_is_never_smaller_than_its_two_borders(self):
        for c in tree("script-media-stick-onboarding.xml").iter("control"):
            elem = c.find("texture")
            if c.get("type") == "image" and elem is not None and elem.get("border"):
                b = int(elem.get("border"))
                self.assertGreaterEqual(int(c.findtext("width")), 2 * b, c.get("id"))
                self.assertGreaterEqual(int(c.findtext("height")), 2 * b, c.get("id"))
        self.assertGreaterEqual(view.CHIP_MIN, 48)
        self.assertGreaterEqual(view.CHIP_H, 48)


class Dispatch(unittest.TestCase):
    def run_default(self, argv):
        seen = []
        with mock.patch.object(sys, "argv", ["default.py"] + argv), \
                mock.patch.object(onboarding_app, "main", side_effect=lambda a: seen.append(a)):
            with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})
        return seen

    def test_the_onboarding_arguments_go_to_the_window(self):
        self.assertEqual(self.run_default(["onboarding", "demo", "keys"]), [["demo", "keys"]])
        self.assertEqual(self.run_default(["onboarding", "show", "youtube"]), [["show", "youtube"]])

    def test_a_failing_window_does_not_break_the_script(self):
        with mock.patch.object(onboarding_app, "main", side_effect=RuntimeError("boom")), \
                mock.patch.object(sys, "argv", ["default.py", "onboarding", "demo", "keys"]):
            with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    unittest.main()
