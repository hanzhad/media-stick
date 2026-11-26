#!/usr/bin/env python3
"""Offline tests for mediastick_sweetplay.py, sweettv_player.py, and HomeMonitor wiring.

Covers:
  - Pure Core stdlib-only / zero-xbmc & zero manifest_update_parameter invariants
  - JSONRPC.NotifyAll payload builders & input validators (build_play_notify, build_ctl_notify)
  - Direct uncached stream resolution (open_stream, open_vod), Widevine license formatting,
    exclude_hosts CDN mirror rotation / fresh edge assignment, and demuxer selection
  - Guaranteed 0:00 DVR start (compute_initial_seek) on in-progress DVR broadcasts
  - Growing DVR live-edge retention (no forward_handoff kill), >45s raw-live rewind, and
    cross-slot seek_by / seek_wall resolution via SweetStore.programme_at
  - Continuous television slot rollover (plan_slot_end) vs episode_mode=True suppression
  - 20-minute (1200s) overrun grace rule (classify_overrun_resume) for Continue Watching
  - 8s stall & truncated-EOF watchdog (evaluate_watchdog) with MAX_FAILOVERS=3, 6s cooldown,
    and 30s healthy playback reset
  - 0.6s directional D-pad seek coalescer (SeekCoalescer) for TV/DVR vs VOD
  - Continuous wall-clock broadcast tape (wall_timeline) monotonic across slot rollover
  - Server-side thumbnail sprite parser (parse_thumbnails_spec, fetch_thumbnails_spec)
    enforcing HTTPS-only sweet.tv / *.sweet.tv host allowlist and atomic sweettv-session.json
  - Resident SweetPlayerController + HomeMonitor.onNotification + Window(10000) ms.tv_* OSD
"""
import sys

sys.dont_write_bytecode = True

import ast  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import runpy  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
HOME_ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
HOME_SERVICE = os.path.join(HOME_ADDON, "service.py")
SWEETPLAY_PY = os.path.join(LIB, "mediastick_sweetplay.py")
PLAYER_PY = os.path.join(HOME_ADDON, "resources", "lib", "sweettv_player.py")
OVERLAY_SERVICE = os.path.join(ROOT, "device", "skin-overlay", "plugin.video.sweettv", "service.py")

if LIB not in sys.path:
    sys.path.insert(0, LIB)

import mediastick_store as ms_store  # noqa: E402
import mediastick_sweetstore as sweetstore  # noqa: E402


def _local_ts(year, month, day, hour, minute=0, second=0) -> int:
    return int(time.mktime((year, month, day, hour, minute, second, 0, 0, -1)))


DAY1_21_00 = _local_ts(2026, 11, 25, 21, 0, 0)
DAY1_23_00 = DAY1_21_00 + 7200
DAY1_23_30 = DAY1_21_00 + 9000
DAY1_00_00 = DAY1_23_00 + 3600
DAY4_14_00 = _local_ts(2026, 11, 28, 14, 0, 0)


def _require_sweetplay(tc: unittest.TestCase):
    if not os.path.isfile(SWEETPLAY_PY):
        tc.fail(f"Missing Pure Core module: {SWEETPLAY_PY}")
    try:
        return importlib.import_module("mediastick_sweetplay")
    except Exception as exc:
        tc.fail(f"Failed to import mediastick_sweetplay: {exc!r}")


def _seed_store(now_ts: int) -> sweetstore.SweetStore:
    st = sweetstore.SweetStore(":memory:")
    st.upsert_channels(
        {
            "status": "OK",
            "categories": [{"id": 1, "caption": "Общие"}],
            "list": [
                {
                    "id": 5,
                    "name": "Первый канал",
                    "number": 1,
                    "catchup": True,
                    "catchup_duration": 7,
                    "available": True,
                    "category": [1],
                    "epg": [
                        {
                            "id": 49,
                            "text": "Новости",
                            "time_start": DAY1_21_00 - 3600,
                            "time_stop": DAY1_21_00,
                            "available": True,
                        },
                        {
                            "id": 50,
                            "text": "Холостяк",
                            "time_start": DAY1_21_00,
                            "time_stop": DAY1_23_00,
                            "available": True,
                        },
                        {
                            "id": 51,
                            "text": "Пост-шоу",
                            "time_start": DAY1_23_00,
                            "time_stop": DAY1_00_00,
                            "available": True,
                        },
                        {
                            "id": 52,
                            "text": "Ночной эфир",
                            "time_start": DAY1_00_00,
                            "time_stop": DAY1_00_00 + 3600,
                            "available": True,
                        },
                    ],
                },
                {
                    "id": 6,
                    "name": "Без архива",
                    "number": 2,
                    "catchup": False,
                    "catchup_duration": 0,
                    "available": True,
                    "category": [1],
                    "epg": [
                        {
                            "id": 60,
                            "text": "Прямой репортаж",
                            "time_start": DAY1_21_00,
                            "time_stop": DAY1_00_00,
                            "available": True,
                        }
                    ],
                },
            ],
        },
        now=now_ts,
    )
    return st


class TestSweetPlayModuleHygiene(unittest.TestCase):
    """Pure Core stdlib-only, zero-xbmc, and banned-property invariants."""

    def test_pure_core_has_zero_xbmc_imports_and_no_manifest_update_parameter(self):
        self.assertTrue(os.path.isfile(SWEETPLAY_PY), "mediastick_sweetplay.py must exist")
        with open(SWEETPLAY_PY, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("manifest_update_parameter", src)
        tree = ast.parse(src, filename=SWEETPLAY_PY)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        xbmc_mods = {m for m in imported if m.startswith("xbmc")}
        self.assertEqual(xbmc_mods, set(), f"Pure Core must not import xbmc*: {xbmc_mods}")

        saved_xbmc = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("xbmc")}
        try:
            sp = _require_sweetplay(self)
            self.assertEqual(sp.SESSION_FILE, "/run/media-stick/sweettv-session.json")
            self.assertFalse(any(k.startswith("xbmc") for k in sys.modules))
        finally:
            sys.modules.update(saved_xbmc)


class TestRpcNotifyBuilders(unittest.TestCase):
    """build_play_notify and build_ctl_notify payloads and boundary validation."""

    def test_build_play_notify_valid_kinds_and_fields(self):
        sp = _require_sweetplay(self)
        live_req = sp.build_play_notify("live", cid="5", title="Первый канал")
        self.assertEqual(live_req["jsonrpc"], "2.0")
        self.assertEqual(live_req["method"], "JSONRPC.NotifyAll")
        self.assertEqual(live_req["params"]["sender"], "script.media-stick.home")
        self.assertEqual(live_req["params"]["message"], "sweettv.play")
        live_data = live_req["params"]["data"]
        self.assertEqual((live_data["kind"], live_data["cid"], live_data["from_start"]), ("live", "5", False))

        epg_req = sp.build_play_notify(
            "epg",
            cid=5,
            epg_id=50,
            start_offset=0,
            from_start=True,
            wall_ts=DAY1_21_00,
            title="Холостяк",
            episode_mode=True,
        )
        epg_data = epg_req["params"]["data"]
        self.assertEqual(
            (epg_data["kind"], epg_data["cid"], epg_data["epg_id"], epg_data["from_start"], epg_data["episode_mode"]),
            ("epg", "5", "50", True, True),
        )
        self.assertEqual((epg_data["start_offset"], epg_data["wall_ts"]), (0, DAY1_21_00))

        vod_req = sp.build_play_notify(
            "vod",
            movie_id=9558,
            episode_id=101,
            owner_id=69,
            start_offset=120,
            title="Зрадники",
        )
        vod_data = vod_req["params"]["data"]
        self.assertEqual(
            (vod_data["kind"], vod_data["movie_id"], vod_data["episode_id"], vod_data["owner_id"], vod_data["start_offset"]),
            ("vod", "9558", "101", 69, 120),
        )

    def test_build_play_notify_rejects_invalid_inputs(self):
        sp = _require_sweetplay(self)
        invalid_cases = (
            ("youtube", {"cid": "5"}),
            ("", {"cid": "5"}),
            (None, {"cid": "5"}),
            ("live", {"cid": ""}),
            ("live", {"cid": "bad"}),
            ("live", {"cid": True}),
            ("epg", {"cid": "5", "epg_id": ""}),
            ("epg", {"cid": "5", "epg_id": "null"}),
            ("epg", {"cid": "x", "epg_id": "50"}),
            ("vod", {"movie_id": ""}),
            ("vod", {"movie_id": "abc"}),
            ("vod", {"movie_id": "9558", "episode_id": "bad"}),
        )
        for kind, kwargs in invalid_cases:
            with self.subTest(kind=kind, kwargs=kwargs):
                with self.assertRaises((ValueError, TypeError)):
                    sp.build_play_notify(kind, **kwargs)

    def test_build_ctl_notify_all_supported_ops_and_rejects_invalid(self):
        sp = _require_sweetplay(self)
        for op, kwargs in (
            ("seek_by", {"seconds": -15}),
            ("seek_by", {"seconds": 180}),
            ("seek_wall", {"wall_ts": DAY1_21_00 + 600}),
            ("from_start", {}),
            ("live", {}),
            ("prev_prog", {}),
            ("next_prog", {}),
        ):
            with self.subTest(op=op, kwargs=kwargs):
                req = sp.build_ctl_notify(op, **kwargs)
                self.assertEqual(req["jsonrpc"], "2.0")
                self.assertEqual(req["method"], "JSONRPC.NotifyAll")
                self.assertEqual(req["params"]["sender"], "script.media-stick.home")
                self.assertEqual(req["params"]["message"], "sweettv.ctl")
                self.assertEqual(req["params"]["data"]["op"], op)

        for bad_op, bad_kw in (
            ("stop", {}),
            ("pause", {}),
            ("", {}),
            (None, {}),
            (True, {}),
            ("seek_by", {"seconds": True}),
            ("seek_by", {"seconds": float("nan")}),
            ("seek_wall", {"wall_ts": True}),
            ("seek_wall", {"wall_ts": -10}),
        ):
            with self.subTest(bad_op=bad_op, bad_kw=bad_kw):
                with self.assertRaises((ValueError, TypeError)):
                    sp.build_ctl_notify(bad_op, **bad_kw)


class TestStreamResolutionAndDemuxer(unittest.TestCase):
    """Uncached open_stream / open_vod, exclude_hosts rotation, and demuxer rules."""

    def test_open_stream_is_uncached_captures_drm_and_thumbs_and_rotates_hosts(self):
        sp = _require_sweetplay(self)
        calls = []
        edge_hosts = ["edge1.sweet.tv", "edge2.sweet.tv"]

        def fake_send(url, headers, payload, timeout):
            body = json.loads(payload.decode("utf-8"))
            calls.append((url, dict(headers), body))
            idx = min(len(calls) - 1, len(edge_hosts) - 1)
            if body.get("epg_id") == 777:
                return 200, json.dumps(
                    {
                        "result": "OK",
                        "scheme": "HTTP_DASH",
                        "drm_type": "DRM_WIDEVINE",
                        "license_server": "https://lic.sweet.tv/wv",
                        "http_stream": {"host": {"address": "drm1.sweet.tv"}, "url": "/dash/5/777/manifest.mpd"},
                        "mirrors": [
                            {"host": {"address": "drm1.sweet.tv"}, "url": "/dash/5/777/manifest.mpd"},
                            {"host": {"address": "drm2.sweet.tv"}, "url": "/dash/5/777/manifest.mpd"},
                        ],
                        "thumbnails_playlist_url": "http://thumbs.sweet.tv/5/777/spec.json",
                    }
                ).encode("utf-8")
            return 200, json.dumps(
                {
                    "result": "OK",
                    "scheme": "HTTP_HLS",
                    "http_stream": {"host": {"address": edge_hosts[idx]}, "url": "/dvr/5/50/index.m3u8?tok=1"},
                    "thumbnails_playlist_url": "https://thumbs.sweet.tv/5/50/spec.json",
                }
            ).encode("utf-8")

        # Two identical calls MUST both hit transport (cache=False) so failover gets fresh CDN edges
        r1 = sp.open_stream("5", epg_id="50", bearer="Bearer tok", accept_lang="ru", send=fake_send)
        r2 = sp.open_stream("5", epg_id="50", bearer="Bearer tok", accept_lang="ru", exclude_hosts=("edge1.sweet.tv",), send=fake_send)
        self.assertEqual(len(calls), 2, "open_stream must never cache signed stream URLs")
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertEqual(r1["stream_url"], "https://edge1.sweet.tv/dvr/5/50/index.m3u8?tok=1")
        self.assertEqual(r2["stream_url"], "https://edge2.sweet.tv/dvr/5/50/index.m3u8?tok=1")
        self.assertEqual(r1["protocol"], "hls")
        self.assertFalse(r1.get("drm"))
        self.assertEqual(r1["thumbnails_playlist_url"], "https://thumbs.sweet.tv/5/50/spec.json")

        # Widevine DASH formatting + multi-host mirror rotation via exclude_hosts
        r_drm = sp.open_stream(
            "5",
            epg_id="777",
            bearer="Bearer tok",
            accept_lang="uk",
            exclude_hosts=("drm1.sweet.tv",),
            send=fake_send,
        )
        self.assertTrue(r_drm["ok"])
        self.assertEqual(r_drm["stream_url"], "https://drm2.sweet.tv/dash/5/777/manifest.mpd")
        self.assertEqual(r_drm["protocol"], "mpd")
        self.assertEqual(r_drm["drm"], "com.widevine.alpha")
        self.assertTrue(r_drm["license_url"].startswith("https://lic.sweet.tv/wv|"))
        self.assertTrue(r_drm["license_url"].endswith("|R{SSM}|"))
        self.assertIn("sweet.tv", r_drm["license_url"])
        self.assertEqual(r_drm["thumbnails_playlist_url"], "http://thumbs.sweet.tv/5/777/spec.json")

    def test_open_vod_is_uncached_and_supports_exclude_hosts(self):
        sp = _require_sweetplay(self)
        calls = []

        def fake_send(url, headers, payload, timeout):
            body = json.loads(payload.decode("utf-8"))
            calls.append((url, body))
            host = "vod2.sweet.tv" if len(calls) > 1 else "vod1.sweet.tv"
            return 200, json.dumps(
                {
                    "status": "OK",
                    "scheme": "HTTP_HLS",
                    "http_stream": {"host": {"address": host}, "url": "/vod/9558/101/index.m3u8"},
                    "thumbnails_playlist_url": "https://thumbs.sweet.tv/vod/9558/101.json",
                }
            ).encode("utf-8")

        v1 = sp.open_vod(9558, episode_id=101, owner_id=69, quality="720p", bearer="Bearer t", send=fake_send)
        v2 = sp.open_vod(
            9558,
            episode_id=101,
            owner_id=69,
            quality="720p",
            bearer="Bearer t",
            exclude_hosts=("vod1.sweet.tv",),
            send=fake_send,
        )
        self.assertEqual(len(calls), 2, "open_vod must never cache MovieService/GetLink.json")
        self.assertEqual(calls[0][1]["video_quality_id"], 1)
        self.assertEqual(v1["stream_url"], "https://vod1.sweet.tv/vod/9558/101/index.m3u8")
        self.assertEqual(v2["stream_url"], "https://vod2.sweet.tv/vod/9558/101/index.m3u8")
        self.assertEqual(v1["thumbnails_playlist_url"], "https://thumbs.sweet.tv/vod/9558/101.json")

    def test_select_demuxer_combinatoric_rules_and_quality_cap(self):
        sp = _require_sweetplay(self)
        hls_stream = {"stream_url": "https://cdn.sweet.tv/s/index.m3u8", "protocol": "hls", "drm": None, "license_url": ""}
        dash_stream = {"stream_url": "https://cdn.sweet.tv/s/manifest.mpd", "protocol": "mpd", "drm": None, "license_url": ""}
        wv_stream = {
            "stream_url": "https://cdn.sweet.tv/s/manifest.mpd",
            "protocol": "mpd",
            "drm": "com.widevine.alpha",
            "license_url": "https://lic.sweet.tv/wv|User-Agent=x|R{SSM}|",
        }

        cases = (
            # Finished non-DRM HLS archive (end < now and boundary end == now) -> native ffmpeg
            ("finished_hls", hls_stream, "epg", DAY1_23_00 - 60, DAY1_23_00, "1080p", "ffmpeg"),
            ("boundary_exact_end", hls_stream, "epg", DAY1_23_00, DAY1_23_00, "1080p", "ffmpeg"),
            # Adjacent boundary: end == now + 1 (still in-progress DVR) -> inputstream.adaptive
            ("boundary_in_progress", hls_stream, "epg", DAY1_23_00 + 1, DAY1_23_00, "1080p", "inputstream.adaptive"),
            # Live HLS, VOD HLS, finished DASH, finished Widevine -> inputstream.adaptive
            ("live_hls", hls_stream, "live", 0, DAY1_23_00, "720p", "inputstream.adaptive"),
            ("vod_hls", hls_stream, "vod", 0, DAY1_23_00, "1080p", "inputstream.adaptive"),
            ("finished_dash", dash_stream, "epg", DAY1_21_00, DAY1_23_00, "1080p", "inputstream.adaptive"),
            ("finished_wv", wv_stream, "epg", DAY1_21_00, DAY1_23_00, "unlimited", "inputstream.adaptive"),
        )
        for label, stream_info, kind, slot_stop, now_ts, quality, want_demuxer in cases:
            with self.subTest(case=label):
                sel = sp.select_demuxer(stream_info, kind=kind, slot_stop=slot_stop, now=now_ts, quality=quality)
                self.assertEqual(sel["demuxer"], want_demuxer)
                props = sel["properties"]
                self.assertNotIn("inputstream.adaptive.manifest_update_parameter", props)
                if want_demuxer == "ffmpeg":
                    self.assertIn("|", sel["play_url"])
                    self.assertIn("User-Agent=", sel["play_url"])
                    self.assertIn("Referer=", sel["play_url"])
                    self.assertIn("sweet.tv", sel["play_url"])
                    self.assertNotIn("inputstream", props)
                else:
                    self.assertEqual(props.get("inputstream"), "inputstream.adaptive")
                    if quality in ("720p", "1080p"):
                        self.assertEqual(props.get("inputstream.adaptive.max_resolution"), quality)
                    else:
                        self.assertNotIn("inputstream.adaptive.max_resolution", props)


class TestInitialSeekAndTimelineStateMachines(unittest.TestCase):
    """compute_initial_seek, plan_slot_end, and classify_overrun_resume pure state machines."""

    def test_compute_initial_seek_guarantees_zero_start_on_in_progress_dvr(self):
        sp = _require_sweetplay(self)
        min_total = sp.MIN_TOTAL
        tol = sp.SEEK_TOLERANCE

        cases = (
            # Duration not yet reported -> wait
            ((0, 1800, 0, True), ("wait", 0)),
            ((0, 1800, min_total - 1, True), ("wait", 0)),
            ((1200, 5, min_total - 1, False), ("wait", 0)),
            # from_start=True on in-progress DVR opened near live edge -> explicit ("seek", 0)
            ((0, 2400, 2405, True), ("seek", 0)),
            ((0, tol + 1, min_total, True), ("seek", 0)),
            # Boundary: already within SEEK_TOLERANCE of 0:00 -> ("done", 0)
            ((0, 0, 2405, True), ("done", 0)),
            ((0, tol, 2405, True), ("done", 0)),
            # Explicit start_offset (both from 0 and from live edge) + clamping to total - 5
            ((1500, 4, 3600, False), ("seek", 1500)),
            ((1500, 2400, 2405, False), ("seek", 1500)),
            ((1500, 1500 - tol, 3600, False), ("done", 0)),
            ((1500, 1500 - tol - 1, 3600, False), ("seek", 1500)),
            ((1500, 1400, 1420, False), ("seek", 1415)),
            # Default live / archive without from_start and start_offset=0 -> no-op
            ((0, 2400, 2405, False), ("done", 0)),
            ((0, 0, 0, False), ("done", 0)),
        )
        for (offset, pos, total, from_start), expected in cases:
            with self.subTest(offset=offset, pos=pos, total=total, from_start=from_start):
                self.assertEqual(
                    sp.compute_initial_seek(offset, pos, total, from_start=from_start),
                    expected,
                )

    def test_plan_slot_end_continuous_rollover_and_episode_mode_guard(self):
        sp = _require_sweetplay(self)
        st = _seed_store(DAY1_23_30)
        self.addCleanup(st.close)

        base_session = {
            "kind": "epg",
            "cid": "5",
            "epg_id": "50",
            "slot_start": DAY1_21_00,
            "slot_stop": DAY1_23_00,
            "anchor_start": DAY1_21_00,
            "anchor_stop": DAY1_23_00,
            "episode_mode": False,
        }

        # Premature EOF boundary (pos < expected_duration - 45 -> 7154 < 7155): NOT a slot rollover
        self.assertIsNone(sp.plan_slot_end(base_session, pos=7154, now=DAY1_23_30, store=st))

        # Genuine end boundary (pos == 7155) when next_prog (51) has started & can_archive -> roll to 0:00 of 51
        roll_next = sp.plan_slot_end(base_session, pos=7155, now=DAY1_23_30, store=st)
        self.assertIsNotNone(roll_next)
        self.assertEqual((roll_next["kind"], roll_next["cid"], roll_next["epg_id"]), ("epg", "5", "51"))
        self.assertEqual((roll_next["start_offset"], roll_next["from_start"]), (0, True))
        self.assertEqual(roll_next["auto_rollover_from"], "50")

        # episode_mode=True (Show/Series Hub episode): NEVER auto-roll into channel schedule
        ep_session = dict(base_session, episode_mode=True)
        self.assertIsNone(sp.plan_slot_end(ep_session, pos=7200, now=DAY1_23_30, store=st))

        # Next programme has NOT started yet, near real-time (abs(now - slot_stop) <= 90) -> roll to live
        slot_51 = dict(base_session, epg_id="51", slot_start=DAY1_23_00, slot_stop=DAY1_00_00)
        roll_live = sp.plan_slot_end(slot_51, pos=3560, now=DAY1_00_00 - 90, store=st)
        self.assertIsNotNone(roll_live)
        self.assertEqual((roll_live["kind"], roll_live["cid"]), ("live", "5"))

        # Adjacent boundary: abs(now - slot_stop) == 91 when next_prog unstarted -> None
        self.assertIsNone(sp.plan_slot_end(slot_51, pos=3560, now=DAY1_00_00 - 91, store=st))

    def test_classify_overrun_resume_1200s_grace_rule_and_explicit_start(self):
        sp = _require_sweetplay(self)
        rolled_session = {
            "kind": "epg",
            "cid": "5",
            "epg_id": "51",
            "slot_start": DAY1_23_00,
            "slot_stop": DAY1_00_00,
            "auto_rollover_from": "50",
        }

        # Stopping at pos < 1200 (including boundary 1199) marks P1 done=True and skips P2 in resume
        for pos in (0, 300, 1199):
            with self.subTest(rolled_pos=pos):
                verdict = sp.classify_overrun_resume(rolled_session, pos=pos, total=3600)
                self.assertTrue(verdict["mark_prev_done"])
                self.assertFalse(verdict["record_current"])

        # Boundary pos == 1200 and pos == 1500 -> marks P1 done=True AND records P2 in Continue Watching
        for pos in (1200, 1500):
            with self.subTest(rolled_pos=pos):
                verdict = sp.classify_overrun_resume(rolled_session, pos=pos, total=3600)
                self.assertTrue(verdict["mark_prev_done"])
                self.assertTrue(verdict["record_current"])

        # Adjacent negative: explicitly started P2 (auto_rollover_from="") at pos=300 DOES record P2
        explicit_session = dict(rolled_session, auto_rollover_from="")
        verdict_explicit = sp.classify_overrun_resume(explicit_session, pos=300, total=3600)
        self.assertFalse(verdict_explicit["mark_prev_done"])
        self.assertTrue(verdict_explicit["record_current"])


class TestWatchdogAndSeekCoalescer(unittest.TestCase):
    """8s stall / truncated-EOF watchdog and 0.6s directional SeekCoalescer."""

    def test_evaluate_watchdog_stall_paused_truncated_eof_cooldown_and_healthy_reset(self):
        sp = _require_sweetplay(self)
        self.assertEqual(sp.MAX_FAILOVERS, 3)

        # Unpaused playback advancing normally, then stalling
        res = sp.evaluate_watchdog({}, pos=100.0, now_mono=0.0, paused=False, expected_duration=3600)
        self.assertEqual(res["action"], "ok")
        state = res["state"]

        res = sp.evaluate_watchdog(state, pos=105.0, now_mono=5.0, paused=False, expected_duration=3600)
        self.assertEqual(res["action"], "ok")
        state = res["state"]

        # Paused for 60s at pos=105 -> must NOT trigger stall failover
        res = sp.evaluate_watchdog(state, pos=105.0, now_mono=65.0, paused=True, expected_duration=3600)
        self.assertEqual(res["action"], "ok")
        state = res["state"]

        # Unpaused again at t=70, stalled 7.9s -> boundary NOT stalled yet
        res = sp.evaluate_watchdog(state, pos=105.0, now_mono=70.0, paused=False, expected_duration=3600)
        state = res["state"]
        res = sp.evaluate_watchdog(state, pos=105.0, now_mono=77.9, paused=False, expected_duration=3600)
        self.assertEqual(res["action"], "ok")

        # Boundary 8.0s stalled unpaused -> failover #1 at last_good_pos=105
        res = sp.evaluate_watchdog(state, pos=105.0, now_mono=78.0, paused=False, expected_duration=3600)
        self.assertEqual((res["action"], res["resume_pos"], res["failover_count"]), ("failover", 105, 1))
        state = res["state"]

        # Within 6s cooldown (78 + 5.9 = 83.9) -> cooldown suppresses duplicate reopen
        res_cd = sp.evaluate_watchdog(state, pos=105.0, now_mono=83.9, paused=False, ended=True, expected_duration=3600)
        self.assertEqual(res_cd["action"], "cooldown")

        # Truncated EOF after 6.0s cooldown (pos=105 < 3600 - 45) -> failover #2
        res_eof = sp.evaluate_watchdog(state, pos=105.0, now_mono=84.0, paused=False, ended=True, expected_duration=3600)
        self.assertEqual((res_eof["action"], res_eof["resume_pos"], res_eof["failover_count"]), ("failover", 105, 2))
        state = res_eof["state"]

        # Healthy advance for 29s (< 30s) does NOT reset failover_count yet; 30s resets to 0
        for dt in range(1, 30):
            r_step = sp.evaluate_watchdog(state, pos=105.0 + dt, now_mono=84.0 + dt, paused=False, expected_duration=3600)
            state = r_step["state"]
        self.assertEqual(r_step["failover_count"], 2)
        r_reset = sp.evaluate_watchdog(state, pos=135.0, now_mono=114.0, paused=False, expected_duration=3600)
        self.assertEqual(r_reset["failover_count"], 0)
        state = r_reset["state"]

        # Exhaust MAX_FAILOVERS=3, then 4th premature EOF returns "give_up"
        t = 200.0
        for want_n in (1, 2, 3):
            r_f = sp.evaluate_watchdog(state, pos=135.0, now_mono=t, paused=False, ended=True, expected_duration=3600)
            self.assertEqual((r_f["action"], r_f["failover_count"]), ("failover", want_n))
            state = r_f["state"]
            t += 6.0
        r_giveup = sp.evaluate_watchdog(state, pos=135.0, now_mono=t, paused=False, ended=True, expected_duration=3600)
        self.assertEqual(r_giveup["action"], "give_up")
        self.assertEqual(r_giveup["resume_pos"], 135)

    def test_seek_coalescer_tv_vs_vod_escalation_and_06s_window(self):
        sp = _require_sweetplay(self)
        sc = sp.SeekCoalescer()

        # TV/DVR Right escalation: +60s -> +180s -> +300s (+300s...) within 0.6s
        self.assertEqual(sc.push("right", 10.00, is_vod=False), 60)
        self.assertIsNone(sc.flush(10.59))  # boundary < 0.6s: still coalescing
        self.assertEqual(sc.push("right", 10.30, is_vod=False), 240)
        self.assertEqual(sc.push("right", 10.50, is_vod=False), 540)
        self.assertEqual(sc.push("right", 10.70, is_vod=False), 840)
        self.assertIsNone(sc.flush(11.29))
        self.assertEqual(sc.flush(11.30), 840)  # boundary == 0.6s: emits single seek & resets
        self.assertIsNone(sc.flush(12.00))

        # After flush, next Right starts fresh at +60s
        self.assertEqual(sc.push("right", 20.0, is_vod=False), 60)
        self.assertEqual(sc.flush(20.6), 60)

        # TV/DVR Left escalation: -15s -> -60s (-60s...)
        self.assertEqual(sc.push("left", 30.0, is_vod=False), -15)
        self.assertEqual(sc.push("left", 30.2, is_vod=False), -75)
        self.assertEqual(sc.push("left", 30.4, is_vod=False), -135)
        self.assertEqual(sc.flush(31.0), -135)

        # VOD steps: Right +30s, Left -10s
        self.assertEqual(sc.push("right", 40.0, is_vod=True), 30)
        self.assertEqual(sc.push("right", 40.2, is_vod=True), 60)
        self.assertEqual(sc.flush(40.8), 60)
        self.assertEqual(sc.push("left", 50.0, is_vod=True), -10)
        self.assertEqual(sc.push("left", 50.2, is_vod=True), -20)
        self.assertEqual(sc.flush(50.8), -20)


class TestWallTimeline(unittest.TestCase):
    """Continuous wall-clock broadcast tape across today, past-day archive, and rollover."""

    def test_today_session_live_edge_catchup_lag_and_monotonic_rollover(self):
        sp = _require_sweetplay(self)
        session_p1 = {
            "kind": "epg",
            "cid": "5",
            "epg_id": "50",
            "slot_start": DAY1_21_00,
            "slot_stop": DAY1_23_00,
            "anchor_start": DAY1_21_00,
            "anchor_stop": DAY1_23_00,
        }

        # Catchup lag > 15s (boundary 16s and 755s = 12:35 behind live)
        tl_lag16 = sp.wall_timeline(session_p1, pos=9000 - 16, now=DAY1_23_30)
        self.assertEqual(tl_lag16["timeline_mode"], "wall")
        self.assertFalse(tl_lag16["at_live_edge"])
        self.assertEqual(tl_lag16["lag_seconds"], 16)
        self.assertEqual((tl_lag16["window_start"], tl_lag16["window_end"]), (DAY1_21_00, DAY1_23_30))
        self.assertEqual(tl_lag16["time_label"], "23:29 · −00:16 от эфира")

        tl_lag755 = sp.wall_timeline(session_p1, pos=9000 - 755, now=DAY1_23_30)
        self.assertEqual(tl_lag755["time_label"], "23:17 · −12:35 от эфира")

        # Boundary lag == 15s inside DVR -> at_live_edge=True, "HH:MM · В эфире"
        session_inprog = {
            "kind": "epg",
            "cid": "5",
            "epg_id": "51",
            "slot_start": DAY1_23_00,
            "slot_stop": DAY1_00_00,
            "anchor_start": DAY1_21_00,
            "anchor_stop": DAY1_23_00,
        }
        tl_edge = sp.wall_timeline(session_inprog, pos=1800 - 15, now=DAY1_23_30)
        self.assertTrue(tl_edge["at_live_edge"])
        self.assertEqual(tl_edge["time_label"], "23:29 · В эфире")

        # Monotonic rollover across anchor_stop (22:59:59 in P1 -> 23:00:01 at pos=1 in P2)
        tl_before = sp.wall_timeline(session_p1, pos=7199, now=DAY1_23_30)
        tl_after = sp.wall_timeline(session_inprog, pos=1, now=DAY1_23_30)
        self.assertEqual(tl_before["wall_ts"], DAY1_23_00 - 1)
        self.assertEqual(tl_after["wall_ts"], DAY1_23_00 + 1)
        self.assertGreaterEqual(tl_after["progress_pct"], tl_before["progress_pct"])
        self.assertGreater(tl_after["progress_pct"], 70)

    def test_past_day_archive_uses_plus_30m_overrun_window_and_monotonic_rollover(self):
        sp = _require_sweetplay(self)
        past_p1 = {
            "kind": "epg",
            "cid": "5",
            "epg_id": "50",
            "slot_start": DAY1_21_00,
            "slot_stop": DAY1_23_00,
            "anchor_start": DAY1_21_00,
            "anchor_stop": DAY1_23_00,
        }
        past_p2 = dict(past_p1, epg_id="51", slot_start=DAY1_23_00, slot_stop=DAY1_00_00)

        tl_before = sp.wall_timeline(past_p1, pos=7199, now=DAY4_14_00)
        tl_after = sp.wall_timeline(past_p2, pos=1, now=DAY4_14_00)

        self.assertEqual(tl_before["window_start"], DAY1_21_00)
        self.assertEqual(tl_before["window_end"], DAY1_23_00 + 1800)
        self.assertEqual(tl_before["slot_ticks"], [DAY1_23_00])
        self.assertEqual(tl_before["time_label"], "22:59 · в записи")
        self.assertEqual(tl_after["time_label"], "23:00 · в записи")
        self.assertGreaterEqual(tl_after["progress_pct"], tl_before["progress_pct"])
        self.assertGreater(tl_after["progress_pct"], 75)

        # VOD uses file timeline mode
        tl_vod = sp.wall_timeline({"kind": "vod", "movie_id": "9558"}, pos=300, now=DAY4_14_00)
        self.assertEqual(tl_vod["timeline_mode"], "file")


class TestThumbnailsSpriteParserAndSessionFile(unittest.TestCase):
    """parse_thumbnails_spec, fetch_thumbnails_spec, host security, and sweettv-session.json."""

    def test_parse_thumbnails_spec_upgrades_sweettv_http_and_drops_untrusted_hosts(self):
        sp = _require_sweetplay(self)

        # Standard single-sheet SWEET.TV JSON with http://*.sweet.tv
        spec = sp.parse_thumbnails_spec(
            {
                "rows": 15,
                "columns": 15,
                "interval": 32,
                "image_url": "http://thumbs-dvr1.sweet.tv/5/50/sheet0.jpg",
                "playlist_url": "http://thumbs-dvr1.sweet.tv/5/50/index.m3u8",
            }
        )
        self.assertEqual(
            spec,
            {
                "rows": 15,
                "columns": 15,
                "interval": 32,
                "sheets": ["https://thumbs-dvr1.sweet.tv/5/50/sheet0.jpg"],
            },
        )

        # Multi-sheet JSON list mixing sweet.tv, *.sweet.tv, and untrusted hosts
        multi = sp.parse_thumbnails_spec(
            json.dumps(
                {
                    "rows": 10,
                    "columns": 10,
                    "interval": 10,
                    "sheets": [
                        "http://sweet.tv/t/s0.jpg",
                        "https://cdn2.sweet.tv/t/s1.jpg",
                        "http://evilsweet.tv/t/spoof1.jpg",
                        "https://sweet.tv.evil.example/t/spoof2.jpg",
                        "https://attacker.example/sweet.tv/s3.jpg",
                        "javascript:alert(1)",
                    ],
                }
            )
        )
        self.assertEqual(
            multi,
            {
                "rows": 10,
                "columns": 10,
                "interval": 10,
                "sheets": ["https://sweet.tv/t/s0.jpg", "https://cdn2.sweet.tv/t/s1.jpg"],
            },
        )

        # Multi-sheet M3U8 playlist referencing relative & http sweet.tv sheet images
        m3u8_text = (
            "#EXTM3U\n"
            "#EXTINF:320,\n"
            "sheet_000.jpg\n"
            "#EXTINF:320,\n"
            "http://thumbs.sweet.tv/5/50/sheet_001.jpg\n"
            "#EXTINF:320,\n"
            "http://evil.org/sheet_002.jpg\n"
        )
        m3u_spec = sp.parse_thumbnails_spec(
            {"rows": 5, "columns": 5, "interval": 12, "playlist": m3u8_text},
            base_url="http://thumbs.sweet.tv/5/50/playlist.m3u8",
        )
        self.assertEqual(
            m3u_spec,
            {
                "rows": 5,
                "columns": 5,
                "interval": 12,
                "sheets": [
                    "https://thumbs.sweet.tv/5/50/sheet_000.jpg",
                    "https://thumbs.sweet.tv/5/50/sheet_001.jpg",
                ],
            },
        )

        # Negative / boundary cases: untrusted-only host, zero/negative dimensions, malformed JSON
        for bad in (
            {"rows": 15, "columns": 15, "interval": 32, "image_url": "http://evilsweet.tv/a.jpg"},
            {"rows": 15, "columns": 15, "interval": 32, "image_url": "https://sweet.tv.attacker.io/a.jpg"},
            {"rows": 15, "columns": 15, "interval": 32, "image_url": "ftp://sweet.tv/a.jpg"},
            {"rows": 0, "columns": 15, "interval": 32, "image_url": "https://sweet.tv/a.jpg"},
            {"rows": 15, "columns": -1, "interval": 32, "image_url": "https://sweet.tv/a.jpg"},
            {"rows": 15, "columns": 15, "interval": 0, "image_url": "https://sweet.tv/a.jpg"},
            "not json",
            None,
            {},
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(sp.parse_thumbnails_spec(bad))

    def test_fetch_thumbnails_spec_and_atomic_session_file_lifecycle(self):
        sp = _require_sweetplay(self)
        fetched = []

        def fake_send(url, headers, payload, timeout):
            fetched.append(url)
            return 200, json.dumps(
                {
                    "rows": 15,
                    "columns": 15,
                    "interval": 32,
                    "image_url": "http://thumbs.sweet.tv/5/50/sheet.jpg",
                }
            ).encode("utf-8")

        # Untrusted playlist URL must be rejected without making any network call
        self.assertIsNone(sp.fetch_thumbnails_spec("http://evilsweet.tv/spec.json", send=fake_send))
        self.assertEqual(fetched, [])

        thumbs = sp.fetch_thumbnails_spec("http://thumbs.sweet.tv/5/50/spec.json", send=fake_send)
        self.assertEqual(len(fetched), 1)
        self.assertTrue(fetched[0].startswith("https://thumbs.sweet.tv/"))
        self.assertEqual(thumbs["sheets"], ["https://thumbs.sweet.tv/5/50/sheet.jpg"])

        with tempfile.TemporaryDirectory() as tmp:
            sess_path = os.path.join(tmp, "sweettv-session.json")
            with mock.patch.object(sp, "SESSION_FILE", sess_path):
                self.assertIsNone(sp.read_active_session())
                self.assertIsNone(sp.read_active_thumbnails())

                ok = sp.write_active_session(
                    {
                        "kind": "epg",
                        "cid": "5",
                        "epg_id": "50",
                        "title": "Холостяк",
                        "slot_start": DAY1_21_00,
                        "slot_stop": DAY1_23_00,
                        "anchor_start": DAY1_21_00,
                        "anchor_stop": DAY1_23_00,
                        "thumbnails": thumbs,
                    }
                )
                self.assertTrue(ok)
                self.assertEqual([n for n in os.listdir(tmp) if n.endswith(".tmp")], [])
                with open(sess_path, encoding="utf-8") as f:
                    raw_disk = json.load(f)
                self.assertFalse(ms_store.contains_secret(raw_disk))
                self.assertEqual(sp.read_active_session()["epg_id"], "50")
                self.assertEqual(sp.read_active_thumbnails(), thumbs)

                sp.clear_active_session()
                self.assertFalse(os.path.exists(sess_path))
                self.assertIsNone(sp.read_active_session())
                self.assertIsNone(sp.read_active_thumbnails())


class TestResidentSweetPlayerControllerAndHomeService(unittest.TestCase):
    """Thin I/O wiring for SweetPlayerController, HomeMonitor, OSD props, and overlay cleanup."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session_path = os.path.join(self.tmp.name, "sweettv-session.json")
        self.state_dir = os.path.join(self.tmp.name, "resume")
        os.makedirs(self.state_dir, exist_ok=True)
        self.state_store = ms_store.StateStore(os.path.join(self.state_dir, "state.db"))
        self.addCleanup(self.state_store.close)
        self.sweet_store = _seed_store(DAY1_23_30)
        self.addCleanup(self.sweet_store.close)

        self.now = [float(DAY1_23_30)]
        self.mono = [100.0]
        self.win_props = {}
        self.played = []
        self.seeks = []
        self.pos = [0.0]
        self.total = [0.0]
        self.is_playing = [False]
        self.forbid_get_playing_file = [False]
        self.open_calls = []

        test = self

        class FakeVideoInfoTag:
            def __init__(self):
                self.resume_points = []

            def setResumePoint(self, resume, total=0.0):
                self.resume_points.append((float(resume), float(total)))

        class FakeListItem:
            def __init__(self, label="", path="", offscreen=False):
                self.label = label
                self.path = path
                self.info = {}
                self.props = {}
                self.video_info_tag = FakeVideoInfoTag()

            def setLabel(self, label):
                self.label = label

            def setPath(self, path):
                self.path = path

            def setInfo(self, kind, info):
                self.info[kind] = dict(info)

            def setProperty(self, key, value):
                self.props[key] = str(value)

            def getVideoInfoTag(self):
                return self.video_info_tag

        class FakeWindow:
            def __init__(self, wid=10000):
                self.wid = wid

            def setProperty(self, key, value):
                test.win_props[key] = str(value)

            def getProperty(self, key):
                return test.win_props.get(key, "")

            def clearProperty(self, key):
                test.win_props[key] = ""

        class FakePlayer:
            def __init__(self, *args, **kwargs):
                pass

            def play(self, item="", listitem=None, windowed=False, startpos=-1):
                test.played.append((item, listitem))
                test.is_playing[0] = True

            def stop(self):
                test.is_playing[0] = False

            def isPlaying(self):
                return test.is_playing[0]

            def isPlayingVideo(self):
                return test.is_playing[0]

            def getTime(self):
                if not test.is_playing[0]:
                    raise RuntimeError("not playing")
                return test.pos[0]

            def getTotalTime(self):
                return test.total[0]

            def seekTime(self, seconds):
                test.seeks.append(float(seconds))
                test.pos[0] = float(seconds)

            def getPlayingFile(self):
                if test.forbid_get_playing_file[0]:
                    raise AssertionError("getPlayingFile() must NOT be called inside onPlayBackEnded")
                if not test.is_playing[0] or not test.played:
                    raise RuntimeError("not playing")
                return test.played[-1][0]

        self.fake_xbmc = types.ModuleType("xbmc")
        self.fake_xbmc.Player = FakePlayer
        self.fake_xbmc.Monitor = object
        self.fake_xbmc.LOGINFO = 1
        self.fake_xbmc.LOGWARNING = 2
        self.fake_xbmc.LOGERROR = 3
        self.fake_xbmc.log = lambda *a, **k: None
        self.fake_xbmc.getCondVisibility = lambda cond: False
        self.fake_xbmc.executebuiltin = lambda cmd: None

        self.fake_xbmcgui = types.ModuleType("xbmcgui")
        self.fake_xbmcgui.Window = FakeWindow
        self.fake_xbmcgui.ListItem = FakeListItem
        self.fake_xbmcgui.Dialog = lambda: types.SimpleNamespace(notification=lambda *a, **k: None)
        self.fake_xbmcgui.NOTIFICATION_INFO = "info"
        self.fake_xbmcgui.getCurrentWindowId = lambda: 10000

        mod_patch = mock.patch.dict(sys.modules, {"xbmc": self.fake_xbmc, "xbmcgui": self.fake_xbmcgui})
        mod_patch.start()
        self.addCleanup(mod_patch.stop)
        path_patch = mock.patch.object(sys, "path", [HOME_ADDON, LIB, *sys.path])
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def _fake_send(self, url, headers, payload, timeout):
        if "thumbs.sweet.tv" in url:
            return 200, json.dumps(
                {"rows": 15, "columns": 15, "interval": 32, "image_url": "http://thumbs.sweet.tv/5/sheet.jpg"}
            ).encode("utf-8")
        body = json.loads(payload.decode("utf-8")) if payload else {}
        self.open_calls.append((url, body))
        if "MovieService/GetLink.json" in url:
            return 200, json.dumps(
                {
                    "status": "OK",
                    "scheme": "HTTP_HLS",
                    "http_stream": {"host": {"address": "vod.sweet.tv"}, "url": "/vod/9558/index.m3u8"},
                }
            ).encode("utf-8")
        epg_id = body.get("epg_id")
        host = f"edge{len(self.open_calls)}.sweet.tv"
        stream_path = f"/dvr/5/{epg_id}/index.m3u8" if epg_id else "/live/5/index.m3u8"
        return 200, json.dumps(
            {
                "result": "OK",
                "scheme": "HTTP_HLS",
                "http_stream": {"host": {"address": host}, "url": stream_path},
                "thumbnails_playlist_url": "http://thumbs.sweet.tv/5/spec.json" if epg_id else "",
            }
        ).encode("utf-8")

    def _make_controller(self):
        self.assertTrue(os.path.isfile(PLAYER_PY), f"Missing resident player module: {PLAYER_PY}")
        sp = _require_sweetplay(self)
        sys.modules.pop("resources.lib.sweettv_player", None)
        mod = importlib.import_module("resources.lib.sweettv_player")
        ctrl = mod.SweetPlayerController(
            store=self.sweet_store,
            state_store=self.state_store,
            send=self._fake_send,
            clock=lambda: self.now[0],
            mono=lambda: self.mono[0],
            session_path=self.session_path,
        )
        return sp, ctrl

    def test_from_start_in_progress_dvr_seeks_zero_stays_on_dvr_at_live_edge_and_updates_osd(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            # Start in-progress DVR broadcast (51: 23:00..00:00, now=23:30) with from_start=True
            req = sp.build_play_notify("epg", cid="5", epg_id="51", from_start=True, title="Пост-шоу")
            ctrl.handle_play(req["params"]["data"])
            self.assertEqual(len(self.open_calls), 1)
            self.assertEqual(self.win_props.get("ms.tv_osd"), "1")
            self.assertIsNotNone(sp.read_active_session(self.session_path))
            self.assertIsNotNone(sp.read_active_thumbnails(self.session_path))

            # inputstream.adaptive opens at live edge (pos=1795, total=1800) -> controller seeks to 0:00!
            self.pos[0], self.total[0] = 1795.0, 1800.0
            ctrl.onAVStarted()
            ctrl.tick()
            self.assertIn(0.0, self.seeks)
            self.assertEqual(self.pos[0], 0.0)

            # Catching up to live edge inside DVR (pos=1790, lag=10s <= 15s) keeps DVR stream (zero reopen!)
            self.seeks.clear()
            ctrl.handle_ctl(sp.build_ctl_notify("seek_by", seconds=1790)["params"]["data"])
            self.mono[0] += 0.7
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1, "Catching up to live edge in DVR must NOT reopen raw live")
            self.assertEqual(self.win_props.get("ms.tv_time_label"), "23:29 · В эфире")
            self.assertTrue(0 <= int(self.win_props.get("ms.tv_progress", "-1")) <= 100)

            # Rewinding -5m (-300s) right afterwards is an instant in-stream seekTime with zero reopen!
            ctrl.handle_ctl(sp.build_ctl_notify("seek_by", seconds=-300)["params"]["data"])
            self.mono[0] += 0.7
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1, "Rewinding inside DVR must be instant in-stream seekTime")
            self.assertAlmostEqual(self.pos[0], 1490.0, delta=2.0)

            # Seeking across slot boundary (before 23:00 into P1 50 at 22:50) resolves (50, 6600) via SweetStore
            ctrl.handle_ctl(sp.build_ctl_notify("seek_wall", wall_ts=DAY1_23_00 - 600)["params"]["data"])
            self.assertEqual(len(self.open_calls), 2)
            self.assertEqual(self.open_calls[-1][1].get("epg_id"), 50)

            # Stop cleans sweettv-session.json and clears ms.tv_* OSD properties
            ctrl.onPlayBackStopped()
            self.assertFalse(os.path.exists(self.session_path))
            self.assertEqual(self.win_props.get("ms.tv_osd"), "")
            self.assertEqual(self.win_props.get("ms.tv_time_label"), "")
            self.assertEqual(self.win_props.get("ms.tv_sublabel"), "")
            self.assertEqual(self.win_props.get("ms.tv_progress"), "")

    def test_raw_live_rewind_threshold_vod_clears_tv_osd_and_rollover_overrun_grace(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            # Raw live: rewind <= 45s stays in live; rewind > 45s (-60s) switches to EPG 51 via SweetStore
            ctrl.handle_play(sp.build_play_notify("live", cid="5")["params"]["data"])
            self.pos[0], self.total[0] = 50.0, 60.0
            self.assertEqual(len(self.open_calls), 1)
            ctrl.handle_ctl(sp.build_ctl_notify("seek_by", seconds=-30)["params"]["data"])
            self.mono[0] += 0.7
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1, "<=45s rewind on raw live stays in live buffer")

            ctrl.handle_ctl(sp.build_ctl_notify("seek_by", seconds=-60)["params"]["data"])
            self.mono[0] += 0.7
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 2, ">45s rewind on raw live switches to DVR archive")
            self.assertEqual(self.open_calls[-1][1].get("epg_id"), 51)

            # Slot rollover on P1 (50) -> P2 (51) WITHOUT calling getPlayingFile() in onPlayBackEnded,
            # followed by stopping at pos=300 (< 1200s): marks P1 done=True and omits P2 from resume!
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", start_offset=7100)["params"]["data"])
            self.pos[0], self.total[0] = 7180.0, 7200.0
            ctrl.tick()
            self.forbid_get_playing_file[0] = True
            try:
                ctrl.onPlayBackEnded()
            finally:
                self.forbid_get_playing_file[0] = False
            self.assertEqual(self.open_calls[-1][1].get("epg_id"), 51)

            # Stop 5 minutes (300s < 1200s) into auto-rolled P2
            self.pos[0], self.total[0] = 300.0, 3600.0
            ctrl.tick()
            ctrl.onPlayBackStopped()
            p1_res = self.state_store.get_resume("sw:5|50")
            p2_res = self.state_store.get_resume("sw:5|51")
            self.assertIsNotNone(p1_res)
            self.assertTrue(p1_res["done"], "Original programme P1 must be marked done=True")
            self.assertIsNone(p2_res, "Auto-rolled P2 stopped <1200s must NOT pollute Continue Watching")

            # VOD playback sets ms.tv_osd == ""
            ctrl.handle_play(sp.build_play_notify("vod", movie_id="9558", owner_id=69)["params"]["data"])
            self.assertEqual(self.win_props.get("ms.tv_osd"), "")

    def test_controller_watchdog_failover_reopens_fresh_edge_at_last_good_pos_without_marking_done(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", start_offset=900)["params"]["data"])
            self.assertEqual(len(self.open_calls), 1)
            self.assertIn("edge1.sweet.tv", self.played[-1][0])

            # Advance cleanly to 920s, then stall unpaused for 8.5s -> CDN failover reopen at 920s!
            self.pos[0], self.total[0] = 920.0, 7200.0
            ctrl.tick()
            self.mono[0] += 8.5
            ctrl.tick()

            self.assertEqual(len(self.open_calls), 2, "8s unpaused stall must reopen stream on fresh CDN edge")
            self.assertIn("edge2.sweet.tv", self.played[-1][0])
            res_entry = self.state_store.get_resume("sw:5|50")
            if res_entry is not None:
                self.assertFalse(res_entry["done"], "CDN stall failover must never mark item done=True")

    def test_controller_constants_and_startup_buffering_grace(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        mod = sys.modules["resources.lib.sweettv_player"]
        self.assertEqual(mod.STARTUP_GRACE, 30.0)
        self.assertEqual(mod.SEEK_GRACE, 15.0)
        self.assertEqual(mod.INITIAL_SEEK_SETTLE, 2.0)

        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", from_start=True)["params"]["data"])
            self.assertEqual(len(self.open_calls), 1)

            # Startup buffering (pos=0, total=0, onAVStarted not yet called) for 15s and up to 29.9s (< STARTUP_GRACE)
            self.pos[0], self.total[0] = 0.0, 0.0
            for dt in (5.0, 5.0, 5.0, 14.9):
                self.mono[0] += dt
                ctrl.tick()
                self.assertEqual(len(self.open_calls), 1, f"Startup buffering at +{self.mono[0] - 100.0:.1f}s must NOT failover")

            # onAVStarted() resets startup buffer time so 7s after onAVStarted (< 8s stall) does NOT failover
            ctrl.onAVStarted()
            self.mono[0] += 7.0
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1, "Time spent buffering before onAVStarted must not count toward 8s stall")

            # Boundary: if onAVStarted never fires and pos=0, total=0 persists >= STARTUP_GRACE (30s) + 8s, watchdog arms and fails over
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", from_start=True)["params"]["data"])
            base_opens = len(self.open_calls)
            self.pos[0], self.total[0] = 0.0, 0.0
            self.mono[0] += 30.0
            ctrl.tick()
            self.assertEqual(len(self.open_calls), base_opens)
            self.mono[0] += 8.5
            ctrl.tick()
            self.assertEqual(len(self.open_calls), base_opens + 1, "Watchdog must arm once STARTUP_GRACE expires")

    def test_controller_seek_grace_suppresses_post_seek_rebuffering_failover(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", start_offset=900)["params"]["data"])
            self.pos[0], self.total[0] = 920.0, 7200.0
            ctrl.onAVStarted()
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1)

            # Seek +180s and flush 0.6s coalescer, then hold constant pos (HLS rebuffering) for 10s and up to 14.9s (< SEEK_GRACE)
            ctrl.handle_ctl(sp.build_ctl_notify("seek_by", seconds=180)["params"]["data"])
            self.mono[0] += 0.7
            ctrl.tick()
            self.assertAlmostEqual(self.pos[0], 1100.0, delta=1.0)

            for dt in (5.0, 5.0, 4.9):
                self.mono[0] += dt
                ctrl.tick()
                self.assertEqual(len(self.open_calls), 1, "Post-seek rebuffering < SEEK_GRACE must NOT failover")

            # Boundary: after SEEK_GRACE (15s) expires + 8s stall at constant pos -> failover triggers
            self.mono[0] += 0.2
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1)
            self.mono[0] += 8.5
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 2, "Stall after SEEK_GRACE + 8s must trigger failover")

    def test_controller_watchdog_give_up_while_playing_keeps_session_and_osd_alive(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", start_offset=900)["params"]["data"])
            self.pos[0], self.total[0] = 920.0, 7200.0
            ctrl.onAVStarted()
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 1)

            # Exhaust MAX_FAILOVERS (3) while playback remains active
            for i in range(sp.MAX_FAILOVERS):
                self.mono[0] += 8.5
                ctrl.tick()
                self.assertEqual(len(self.open_calls), i + 2)
                self.pos[0], self.total[0] = 920.0, 7200.0
                ctrl.onAVStarted()
                ctrl.tick()

            # 4th stall -> evaluate_watchdog returns "give_up" while isPlaying() is True
            self.mono[0] += 8.5
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 4, "give_up must not trigger another failover reopen")
            self.assertTrue(ctrl._watchdog_exhausted)
            self.assertIsNotNone(ctrl._session, "give_up while playing must NOT clear self._session")
            self.assertTrue(os.path.exists(self.session_path), "give_up while playing must NOT delete sweettv-session.json")
            self.assertIsNotNone(sp.read_active_session(self.session_path))
            self.assertEqual(self.win_props.get("ms.tv_osd"), "1", "give_up while playing must keep ms.tv_osd alive")

            # Subsequent ticks while still playing keep session & OSD alive without reopening
            self.mono[0] += 10.0
            ctrl.tick()
            self.assertEqual(len(self.open_calls), 4)
            self.assertTrue(os.path.exists(self.session_path))
            self.assertEqual(self.win_props.get("ms.tv_osd"), "1")

            res_entry = self.state_store.get_resume("sw:5|50")
            if res_entry is not None:
                self.assertFalse(res_entry["done"])

            # Only when playback actually stops is the session cleaned up
            ctrl.onPlayBackStopped()
            self.assertFalse(os.path.exists(self.session_path))
            self.assertIsNone(ctrl._session)
            self.assertEqual(self.win_props.get("ms.tv_osd"), "")

    def test_controller_native_start_offset_and_initial_seek_settle(self):
        import mediastick_signin as signin

        sp, ctrl = self._make_controller()
        with mock.patch.object(signin, "sweettv_setting", return_value="Bearer test-tok"):
            # Case A: EPG archive with start_offset=900 sets StartOffset & setResumePoint, waits INITIAL_SEEK_SETTLE,
            # and skips fallback seekTime() when Kodi's native seek lands near start_offset.
            ctrl.handle_play(sp.build_play_notify("epg", cid="5", epg_id="50", start_offset=900)["params"]["data"])
            li = self.played[-1][1]
            self.assertEqual(li.props.get("StartOffset"), "900")
            self.assertEqual(li.props.get("ResumeTime"), "900")
            self.assertEqual(li.video_info_tag.resume_points, [(900.0, 7200.0)])

            self.pos[0], self.total[0] = 0.0, 7200.0
            ctrl.onAVStarted()
            self.assertEqual(self.seeks, [], "Must NOT call fallback seekTime immediately in onAVStarted")
            self.mono[0] += 1.9
            ctrl.tick()
            self.assertEqual(self.seeks, [], "Must wait INITIAL_SEEK_SETTLE (2.0s) before fallback seekTime")

            # Native StartOffset/setResumePoint lands within SEEK_TOLERANCE of 900 -> zero fallback seekTime!
            self.pos[0] = 898.0
            ctrl.tick()
            self.assertEqual(self.seeks, [], "Native seek landing near start_offset must skip fallback seekTime")
            self.assertTrue(ctrl._initial_seek_done)

            # Case B: VOD with start_offset=120 where native seek does NOT land -> fallback seekTime after INITIAL_SEEK_SETTLE
            self.seeks.clear()
            ctrl.handle_play(sp.build_play_notify("vod", movie_id="9558", owner_id=69, start_offset=120)["params"]["data"])
            li_vod = self.played[-1][1]
            self.assertEqual(li_vod.props.get("StartOffset"), "120")

            self.pos[0], self.total[0] = 0.0, 3600.0
            ctrl.onAVStarted()
            self.assertEqual(self.seeks, [])
            self.mono[0] += 1.9
            ctrl.tick()
            self.assertEqual(self.seeks, [])
            self.mono[0] += 0.1
            ctrl.tick()
            self.assertEqual(self.seeks, [120.0], "Fallback seekTime must fire once INITIAL_SEEK_SETTLE elapses at pos=0")

    def test_home_service_instantiates_single_controller_and_dispatches_notifications(self):
        created_controllers = []
        monitors = []

        class RecordingController:
            def __init__(self, *args, **kwargs):
                self.plays = []
                self.ctls = []
                self.ticks = 0
                created_controllers.append(self)

            def handle_play(self, payload):
                self.plays.append(payload)

            def handle_ctl(self, payload):
                self.ctls.append(payload)

            def tick(self):
                self.ticks += 1

        class FakeMonitor:
            def __init__(self):
                monitors.append(self)
                self._done = False

            def abortRequested(self):
                return self._done

            def waitForAbort(self, timeout):
                self._done = True
                return True

        fake_xbmc = types.ModuleType("xbmc")
        fake_xbmc.LOGINFO = fake_xbmc.LOGWARNING = fake_xbmc.LOGERROR = 1
        fake_xbmc.log = lambda *a, **k: None
        fake_xbmc.getCondVisibility = lambda cond: False
        fake_xbmc.Monitor = FakeMonitor
        fake_xbmc.Player = type("FakePlayer", (), {})

        fake_xbmcgui = types.ModuleType("xbmcgui")
        fake_xbmcgui.getCurrentWindowId = lambda: 10000
        fake_xbmcgui.Window = lambda wid=10000: types.SimpleNamespace(setProperty=lambda *a: None)

        fake_launcher_mod = types.ModuleType("resources.lib.launcher")
        fake_launcher_mod.ADDON_PATH = HOME_ADDON
        fake_launcher_mod.Launcher = type(
            "FakeLauncher",
            (),
            {
                "__init__": lambda self, *a, **k: None,
                "show": lambda self: None,
                "close": lambda self: None,
                "window_id": lambda self: 13000,
                "refresh_idle": lambda self, active: None,
                "refresh_status": lambda self: None,
            },
        )
        fake_lang = types.ModuleType("resources.lib.lang")
        fake_lang.reconcile = lambda: None
        fake_resume = types.ModuleType("resources.lib.resume_recorder")
        fake_resume.start = lambda: None
        fake_player_mod = types.ModuleType("resources.lib.sweettv_player")
        fake_player_mod.SweetPlayerController = RecordingController

        fake_lib = types.ModuleType("resources.lib")
        fake_lib.launcher = fake_launcher_mod
        fake_lib.lang = fake_lang
        fake_lib.resume_recorder = fake_resume
        fake_lib.sweettv_player = fake_player_mod
        fake_resources = types.ModuleType("resources")
        fake_resources.lib = fake_lib

        with mock.patch.dict(
            sys.modules,
            {
                "xbmc": fake_xbmc,
                "xbmcgui": fake_xbmcgui,
                "resources": fake_resources,
                "resources.lib": fake_lib,
                "resources.lib.launcher": fake_launcher_mod,
                "resources.lib.lang": fake_lang,
                "resources.lib.resume_recorder": fake_resume,
                "resources.lib.sweettv_player": fake_player_mod,
            },
        ):
            runpy.run_path(HOME_SERVICE, run_name="home_service_test")

        self.assertEqual(len(created_controllers), 1, "service.py must instantiate a single SweetPlayerController")
        self.assertEqual(len(monitors), 1)
        sp = _require_sweetplay(self)
        ctrl = created_controllers[0]
        mon = monitors[0]

        play_req = sp.build_play_notify("live", cid="5")
        ctl_req = sp.build_ctl_notify("from_start")
        mon.onNotification("script.media-stick.home", "Other.sweettv.play", json.dumps(play_req["params"]["data"]))
        mon.onNotification("script.media-stick.home", "Other.sweettv.ctl", json.dumps(ctl_req["params"]["data"]))
        self.assertEqual(len(ctrl.plays), 1)
        self.assertEqual(ctrl.plays[0]["cid"], "5")
        self.assertEqual(len(ctrl.ctls), 1)
        self.assertEqual(ctrl.ctls[0]["op"], "from_start")

    def test_sweettv_addon_service_has_zero_msplayer_and_zero_get_channel_list(self):
        with open(OVERLAY_SERVICE, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("_MsPlayer", src)
        self.assertNotIn("get_channel_list", src)


if __name__ == "__main__":
    unittest.main()
