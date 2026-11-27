"""Resident SWEET.TV playback & timeline controller (thin Kodi I/O shell).

Delegates all stream resolution, demuxer rules, initial-seek, slot rollover,
overrun resume classification, stall/EOF failover, 0.6s seek coalescing,
wall-clock timeline math, and sprite parsing to mediastick_sweetplay.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import xbmc
import xbmcgui

_LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import mediastick_resume as ms_resume  # noqa: E402
import mediastick_store as ms_store  # noqa: E402
import mediastick_sweetplay as sp  # noqa: E402
import mediastick_sweetstore as sweetstore  # noqa: E402

LOG = "[script.media-stick.home]"
RESUME_CHECKPOINT_EVERY = 30.0
INITIAL_SEEK_RETRY = 3.0
INITIAL_SEEK_MAX_TRIES = 5
STARTUP_GRACE = 30.0
SEEK_GRACE = 15.0
INITIAL_SEEK_SETTLE = 2.0

_PlayerBase = getattr(xbmc, "Player", object)


class SweetPlayerController(_PlayerBase):
    """Single resident Kodi player controller for SWEET.TV live, DVR, and VOD."""

    def __init__(
        self,
        store=None,
        state_store=None,
        send=None,
        clock=None,
        mono=None,
        session_path: str | None = None,
    ):
        super().__init__()
        self._store = store
        self._state_store = state_store
        self._send = send
        self._clock = clock or time.time
        self._mono = mono or time.monotonic
        self._session_path = session_path
        self._lock = threading.RLock()

        self._session: dict | None = None
        self._prev_meta: dict | None = None
        self._excluded_hosts: list[str] = []
        self._watchdog_state: dict = {}
        self._coalescer = sp.SeekCoalescer()
        self._initial_seek_done = True
        self._initial_seek_tries = 0
        self._last_initial_seek_mono: float | None = None
        self._paused = False
        self._reopening = False
        self._playback_seen = False
        self._av_started = False
        self._av_started_mono: float | None = None
        self._session_start_mono: float = float(self._mono())
        self._seek_grace_until: float = 0.0
        self._watchdog_exhausted = False
        self._last_pos = 0.0
        self._last_total = 0.0
        self._last_checkpoint_mono = 0.0
        self._play_gen = 0
        self._cancelled_preview_gen = 0

    # ---- dependencies & OSD helpers -------------------------------------------

    def _get_store(self):
        if self._store is not None:
            return self._store
        try:
            return sweetstore.default_store()
        except Exception:
            return None

    def _get_state_store(self):
        if self._state_store is not None:
            return self._state_store
        try:
            st = ms_resume._get_store(create=True)
            if st is not None:
                return st
        except Exception:
            pass
        try:
            return ms_store.StateStore()
        except Exception:
            return None

    @staticmethod
    def _home_window():
        try:
            return xbmcgui.Window(10000)
        except Exception:
            return None

    def _set_preview_prop(self, active: bool) -> None:
        win = self._home_window()
        if win is None:
            return
        try:
            win.setProperty("ms.tv_preview", "1" if active else "")
        except Exception:
            pass

    def _clear_osd(self) -> None:
        win = self._home_window()
        if win is None:
            return
        for key in ("ms.tv_osd", "ms.tv_time_label", "ms.tv_sublabel", "ms.tv_progress"):
            try:
                win.setProperty(key, "")
            except Exception:
                pass

    def _update_osd(self, pos: float | None = None) -> None:
        sess = self._session
        if not sess or sess.get("preview") or sess.get("kind") not in ("live", "epg"):
            self._clear_osd()
            return
        win = self._home_window()
        if win is None:
            return
        cur_pos = self._last_pos if pos is None else float(pos)
        tl = sp.wall_timeline(sess, pos=cur_pos, now=int(self._clock()))
        try:
            win.setProperty("ms.tv_osd", "1")
            win.setProperty("ms.tv_time_label", tl["time_label"])
            win.setProperty("ms.tv_sublabel", tl["sublabel"])
            win.setProperty("ms.tv_progress", str(tl["progress_pct"]))
        except Exception:
            pass

    def poll_hint(self) -> float | None:
        """Return desired service loop sleep interval when active, or None when idle."""
        with self._lock:
            if self._session is None or self._session.get("preview"):
                return None
            if self._coalescer.has_pending() or not self._initial_seek_done:
                return 0.2
            return 1.0

    # ---- player queries & resume persistence ----------------------------------

    def _read_player_times(self) -> tuple[bool, float, float]:
        try:
            if not self.isPlaying():
                return False, self._last_pos, self._last_total
            pos = float(self.getTime())
            total = float(self.getTotalTime())
            self._last_pos = max(0.0, pos)
            if total > 0:
                self._last_total = float(total)
            self._playback_seen = True
            return True, self._last_pos, self._last_total
        except Exception:
            return False, self._last_pos, self._last_total

    def _expected_duration(self) -> int:
        sess = self._session
        if not sess:
            return 0
        kind = sess.get("kind")
        if kind == "epg":
            start = int(sess.get("slot_start") or 0)
            stop = int(sess.get("slot_stop") or 0)
            now_i = int(self._clock())
            if start > 0 and stop > start:
                if stop <= now_i:
                    return stop - start
                return max(0, now_i - start)
        if kind == "vod":
            dur = int(sess.get("duration") or 0)
            return dur if dur > 0 else int(self._last_total or 0)
        return 0

    def _mark_epg_done(self, meta_info: dict, now: float) -> None:
        st = self._get_state_store()
        if st is None or not isinstance(meta_info, dict):
            return
        cid = str(meta_info.get("cid") or "")
        epg_id = str(meta_info.get("epg_id") or "")
        if not cid or not epg_id:
            return
        start = int(meta_info.get("slot_start") or 0)
        stop = int(meta_info.get("slot_stop") or 0)
        total = max(1, stop - start) if stop > start else max(1, int(meta_info.get("total") or 3600))
        meta = {
            "cid": cid,
            "epg": epg_id,
            "title": str(meta_info.get("title") or "")[:120],
            "start": start,
            "stop": stop,
        }
        try:
            st.upsert_resume(
                media_key=f"sw:{cid}|{epg_id}",
                app="sweettv",
                pos=0,
                total=total,
                done=True,
                updated_at=float(now),
                meta=meta,
            )
        except Exception as exc:
            xbmc.log(f"{LOG} mark done failed: {exc!r}", xbmc.LOGWARNING)

    def _persist_resume(self, force_done: bool = False, allow_done: bool = True) -> None:
        sess = self._session
        st = self._get_state_store()
        if sess is None or sess.get("preview") or st is None:
            return
        now = float(self._clock())
        kind = sess.get("kind")
        if kind == "live":
            cid = str(sess.get("cid") or "")
            if cid:
                try:
                    st.set_pref("sweettv:live", json.dumps({"cid": cid, "at": int(now)}, separators=(",", ":")))
                except Exception:
                    pass
            if sess.get("auto_rollover_from") and self._prev_meta:
                self._mark_epg_done(self._prev_meta, now)
            return

        pos = max(0, int(self._last_pos))
        slot_start = int(sess.get("slot_start") or 0)
        slot_stop = int(sess.get("slot_stop") or 0)
        total = int(self._last_total or 0)
        if kind == "epg" and slot_stop > slot_start:
            total = max(total, slot_stop - slot_start)
        elif kind == "vod" and int(sess.get("duration") or 0) > 0:
            total = max(total, int(sess["duration"]))

        verdict = sp.classify_overrun_resume(sess, pos=pos, total=total)
        if verdict["mark_prev_done"]:
            prev_info = self._prev_meta or {
                "cid": sess.get("cid", ""),
                "epg_id": verdict["prev_epg_id"],
                "title": "",
                "slot_start": 0,
                "slot_stop": 0,
                "total": 3600,
            }
            self._mark_epg_done(prev_info, now)

        if not verdict["record_current"] or not self._playback_seen:
            return
        if total <= 0:
            return

        done = bool(force_done or (allow_done and (total - pos <= ms_resume.END_MARGIN or pos >= 0.97 * total)))
        if not done and pos < ms_resume.MIN_POS:
            return

        if kind == "epg":
            cid = str(sess.get("cid") or "")
            epg_id = str(sess.get("epg_id") or "")
            if not cid or not epg_id:
                return
            key = f"sw:{cid}|{epg_id}"
            meta = {
                "cid": cid,
                "epg": epg_id,
                "title": str(sess.get("title") or "")[:120],
                "start": slot_start,
                "stop": slot_stop,
            }
        elif kind == "vod":
            mid = str(sess.get("movie_id") or "")
            epid = str(sess.get("episode_id") or "")
            if not mid:
                return
            key = f"sw:vod:{mid}|{epid}" if epid else f"sw:vod:{mid}"
            meta = {
                "movie_id": mid,
                "episode_id": epid,
                "title": str(sess.get("title") or "")[:120],
            }
        else:
            return

        try:
            st.upsert_resume(
                media_key=key,
                app="sweettv",
                pos=0 if done else pos,
                total=total,
                done=done,
                updated_at=now,
                meta=meta,
            )
        except Exception as exc:
            xbmc.log(f"{LOG} resume upsert failed: {exc!r}", xbmc.LOGWARNING)

    def _cleanup_session(self) -> None:
        self._session = None
        self._prev_meta = None
        self._excluded_hosts = []
        self._watchdog_state = {}
        self._coalescer.reset()
        self._initial_seek_done = True
        self._paused = False
        self._playback_seen = False
        self._av_started = False
        self._av_started_mono = None
        self._session_start_mono = float(self._mono())
        self._seek_grace_until = 0.0
        self._watchdog_exhausted = False
        sp.clear_active_session(self._session_path)
        self._clear_osd()
        self._set_preview_prop(False)

    # ---- opening, seeking, rollover, and failover -----------------------------

    def _start_session(
        self,
        spec: dict,
        *,
        exclude_hosts: tuple[str, ...] = (),
        preserve_watchdog: dict | None = None,
        prev_meta: dict | None = None,
    ) -> bool:
        now_i = int(self._clock())
        mono = float(self._mono())
        st = self._get_store()
        is_preview = bool(spec.get("preview", False))
        self._play_gen += 1
        my_gen = self._play_gen
        quality = "720p" if is_preview else ms_resume.read_quality()
        if not is_preview:
            self._set_preview_prop(False)

        kind = spec["kind"]
        cid = spec.get("cid", "")
        epg_id = spec.get("epg_id", "")
        movie_id = spec.get("movie_id", "")
        episode_id = spec.get("episode_id", "")
        owner_id = int(spec.get("owner_id", 0))
        start_offset = int(spec.get("start_offset", 0))
        from_start = bool(spec.get("from_start", False))
        episode_mode = bool(spec.get("episode_mode", False))
        auto_rollover_from = str(spec.get("auto_rollover_from") or "")

        prog = None
        slot_start = int(spec.get("slot_start") or 0)
        slot_stop = int(spec.get("slot_stop") or 0)
        channel_name = str(spec.get("channel_name") or "")
        title = str(spec.get("title") or "")
        duration = 0

        if kind == "epg":
            if st is not None:
                try:
                    prog = st.recall_programme(epg_id, cid=cid, now=now_i)
                except Exception:
                    prog = None
            if isinstance(prog, dict):
                slot_start = slot_start or int(prog.get("start") or prog.get("time_start") or 0)
                slot_stop = slot_stop or int(prog.get("stop") or prog.get("time_stop") or 0)
                channel_name = channel_name or str(prog.get("channel_name") or "")
                title = title or str(prog.get("title") or "")
            res = sp.open_stream(cid, epg_id=epg_id, exclude_hosts=exclude_hosts, send=self._send)
        elif kind == "live":
            if st is not None:
                try:
                    prog = st.programme_at(cid, now_i)
                except Exception:
                    prog = None
            if isinstance(prog, dict):
                slot_start = slot_start or int(prog.get("start") or prog.get("time_start") or 0)
                slot_stop = slot_stop or int(prog.get("stop") or prog.get("time_stop") or 0)
                channel_name = channel_name or str(prog.get("channel_name") or "")
            title = title or channel_name or (str(prog.get("title") or "") if isinstance(prog, dict) else "")
            res = sp.open_stream(cid, epg_id=None, exclude_hosts=exclude_hosts, send=self._send)
        else:
            res = sp.open_vod(
                movie_id,
                episode_id=episode_id or None,
                owner_id=owner_id,
                quality=quality,
                exclude_hosts=exclude_hosts,
                send=self._send,
            )
            title = title or str(res.get("title") or "")
            duration = int(res.get("duration") or 0)

        if not res.get("ok"):
            xbmc.log(f"{LOG} sweetplay open failed ({kind}): {res.get('error')}", xbmc.LOGWARNING)
            return False

        thumbs = None
        if not is_preview and res.get("thumbnails_playlist_url"):
            thumbs = sp.fetch_thumbnails_spec(res["thumbnails_playlist_url"], send=self._send)

        if sp.is_finished_hls_archive(res, kind=kind, slot_stop=slot_stop, now=now_i):
            resolved_url = sp.resolve_hls_variant(res["stream_url"], quality=quality, send=self._send)
            res = {**res, "stream_url": resolved_url, "url": resolved_url}

        sel = sp.select_demuxer(res, kind=kind, slot_stop=slot_stop, now=now_i, quality=quality)
        anchor_start = int(spec.get("anchor_start") or slot_start or now_i)
        anchor_stop = int(spec.get("anchor_stop") or slot_stop or now_i)

        li_label = title or channel_name
        li = xbmcgui.ListItem(label=li_label, path=sel["play_url"])
        li.setPath(sel["play_url"])
        if li_label:
            li.setLabel(li_label)
            info: dict[str, str] = {"title": li_label}
            if channel_name and kind in ("live", "epg"):
                info["tvshowtitle"] = channel_name
                if kind == "live" and isinstance(prog, dict) and prog.get("title"):
                    info["plot"] = str(prog["title"])
            li.setInfo("video", info)

        for prop_k, prop_v in sel["properties"].items():
            li.setProperty(prop_k, prop_v)
        total_sec = 0
        if kind == "epg" and slot_stop > slot_start and slot_stop <= now_i:
            total_sec = slot_stop - slot_start
        elif kind == "vod" and duration > 0:
            total_sec = duration
        if total_sec > 0:
            li.setProperty("TotalTime", str(total_sec))
        if kind in ("epg", "vod") and start_offset > 0:
            li.setProperty("ResumeTime", str(start_offset))
            li.setProperty("StartOffset", str(start_offset))
            if hasattr(li, "getVideoInfoTag"):
                try:
                    li.getVideoInfoTag().setResumePoint(float(start_offset), float(total_sec))
                except Exception:
                    pass

        session_doc = {
            "kind": kind,
            "cid": cid,
            "epg_id": epg_id,
            "movie_id": movie_id,
            "episode_id": episode_id,
            "owner_id": owner_id,
            "title": title,
            "channel_name": channel_name,
            "slot_start": slot_start,
            "slot_stop": slot_stop,
            "anchor_start": anchor_start,
            "anchor_stop": anchor_stop,
            "start_offset": start_offset,
            "from_start": from_start,
            "episode_mode": episode_mode,
            "auto_rollover_from": auto_rollover_from,
            "thumbnails": thumbs,
            "duration": duration,
            "host": str(res.get("host") or ""),
            "preview": is_preview,
            "updated_at": now_i,
        }

        if is_preview and (self._play_gen != my_gen or not (self._play_gen > self._cancelled_preview_gen)):
            self._set_preview_prop(False)
            return False

        self._session = session_doc
        self._prev_meta = prev_meta
        if preserve_watchdog is not None:
            self._watchdog_state = preserve_watchdog
        else:
            self._watchdog_state = {}
            self._excluded_hosts = []
        if res.get("host") and res["host"] not in self._excluded_hosts:
            self._excluded_hosts.append(res["host"])

        self._coalescer.reset()
        self._initial_seek_done = not (kind in ("epg", "vod") and (start_offset > 0 or from_start))
        self._initial_seek_tries = 0
        self._last_initial_seek_mono = None
        self._paused = False
        self._playback_seen = False
        self._av_started = False
        self._av_started_mono = None
        self._session_start_mono = mono
        self._seek_grace_until = 0.0
        self._watchdog_exhausted = False
        self._last_pos = float(start_offset) if kind in ("epg", "vod") else 0.0
        self._last_total = float(duration) if duration > 0 else 0.0
        self._last_checkpoint_mono = mono

        if is_preview:
            self._clear_osd()
            self._set_preview_prop(True)
        else:
            sp.write_active_session(session_doc, path=self._session_path)
            self._update_osd(pos=self._last_pos)
            self._set_preview_prop(False)

        self._reopening = True
        try:
            if is_preview:
                if self._play_gen > self._cancelled_preview_gen:
                    self.play(sel["play_url"], li, windowed=True)
            else:
                self.play(sel["play_url"], li)
        finally:
            self._reopening = False
        return True

    def handle_play(self, payload: dict) -> bool:
        """Handle sweettv.play notification payload."""
        with self._lock:
            try:
                spec = sp.validate_play_data(payload)
            except (TypeError, ValueError) as exc:
                xbmc.log(f"{LOG} invalid sweettv.play payload: {exc!r}", xbmc.LOGWARNING)
                return False
            if self._session is not None and not self._session.get("preview"):
                self._persist_resume(force_done=False, allow_done=True)
            return self._start_session(spec)

    def _step_initial_seek(self, pos: float, total: float, mono: float) -> None:
        sess = self._session
        if sess is None or self._initial_seek_done:
            return
        offset = int(sess.get("start_offset") or 0)
        from_start = bool(sess.get("from_start", False))
        slot_start = int(sess.get("slot_start") or 0)
        slot_stop = int(sess.get("slot_stop") or 0)
        now_i = int(self._clock())
        in_progress = bool(sess.get("kind") == "epg" and slot_start and slot_stop and slot_start <= now_i < slot_stop)
        if not in_progress and not from_start and offset > 0 and pos >= offset - sp.SEEK_TOLERANCE:
            self._initial_seek_done = True
            return
        if (
            not from_start
            and offset > 0
            and pos < sp.SEEK_TOLERANCE
            and self._av_started_mono is not None
            and mono - self._av_started_mono < INITIAL_SEEK_SETTLE
        ):
            return
        action, target = sp.compute_initial_seek(
            offset,
            pos,
            total,
            from_start=from_start,
        )
        if action == "done":
            self._initial_seek_done = True
            return
        if action == "wait":
            return
        if self._initial_seek_tries >= INITIAL_SEEK_MAX_TRIES:
            self._initial_seek_done = True
            return
        if self._last_initial_seek_mono is not None and mono - self._last_initial_seek_mono < INITIAL_SEEK_RETRY:
            return
        try:
            self.seekTime(float(target))
            self._last_pos = float(target)
            self._initial_seek_tries += 1
            self._last_initial_seek_mono = mono
            # Re-verify immediately if seekTime took effect synchronously
            after_action, _ = sp.compute_initial_seek(
                sess.get("start_offset", 0),
                self._last_pos,
                total,
                from_start=bool(sess.get("from_start", False)),
            )
            if after_action == "done":
                self._initial_seek_done = True
        except Exception as exc:
            xbmc.log(f"{LOG} initial seek failed: {exc!r}", xbmc.LOGWARNING)

    def _execute_seek_plan(self, plan: dict) -> None:
        action = plan.get("action")
        if action == "seek":
            target = float(plan.get("target", 0.0))
            try:
                self.seekTime(target)
                self._last_pos = target
                mono = float(self._mono())
                self._seek_grace_until = mono + SEEK_GRACE
                if self._watchdog_state:
                    self._watchdog_state = {
                        **self._watchdog_state,
                        "last_pos": target,
                        "last_advance_mono": self._seek_grace_until,
                        "last_good_pos": max(0, int(target)),
                    }
            except Exception as exc:
                xbmc.log(f"{LOG} seekTime({target}) failed: {exc!r}", xbmc.LOGWARNING)
            self._update_osd(pos=self._last_pos)
        elif action == "reopen" and isinstance(plan.get("play"), dict):
            self._persist_resume(force_done=False, allow_done=True)
            spec = sp.validate_play_data(plan["play"])
            self._start_session(spec)

    def handle_ctl(self, payload: dict) -> bool:
        """Handle sweettv.ctl notification payload."""
        with self._lock:
            try:
                ctl = sp.validate_ctl_data(payload)
            except (TypeError, ValueError) as exc:
                xbmc.log(f"{LOG} invalid sweettv.ctl payload: {exc!r}", xbmc.LOGWARNING)
                return False

            op = ctl["op"]
            if op == "stop_preview":
                self._cancelled_preview_gen = self._play_gen
                if self._session is not None and self._session.get("preview"):
                    self._reopening = True
                    try:
                        self.stop()
                    except Exception:
                        pass
                    finally:
                        self._reopening = False
                    self._cleanup_session()
                return True

            if self._session is None or self._session.get("preview"):
                return False

            mono = float(self._mono())
            if op == "seek_by":
                self._coalescer.push_seconds(ctl["seconds"], mono)
                return True

            self._coalescer.reset()
            _playing, pos, total = self._read_player_times()
            plan = sp.plan_seek(
                self._session,
                op=op,
                seconds=ctl["seconds"],
                wall_ts=ctl["wall_ts"],
                pos=pos,
                total=total,
                now=int(self._clock()),
                store=self._get_store(),
            )
            self._execute_seek_plan(plan)
            return True

    def _failover_reopen(self, resume_pos: int) -> None:
        sess = self._session
        if sess is None:
            return
        self._persist_resume(force_done=False, allow_done=False)
        reopen_spec = {
            "kind": sess["kind"],
            "cid": sess.get("cid", ""),
            "epg_id": sess.get("epg_id", ""),
            "movie_id": sess.get("movie_id", ""),
            "episode_id": sess.get("episode_id", ""),
            "owner_id": sess.get("owner_id", 0),
            "title": sess.get("title", ""),
            "channel_name": sess.get("channel_name", ""),
            "slot_start": sess.get("slot_start", 0),
            "slot_stop": sess.get("slot_stop", 0),
            "anchor_start": sess.get("anchor_start", 0),
            "anchor_stop": sess.get("anchor_stop", 0),
            "start_offset": max(0, int(resume_pos)) if sess["kind"] in ("epg", "vod") else 0,
            "from_start": bool(sess["kind"] == "epg" and int(resume_pos) == 0 and sess.get("from_start")),
            "episode_mode": bool(sess.get("episode_mode", False)),
            "auto_rollover_from": sess.get("auto_rollover_from", ""),
        }
        self._start_session(
            reopen_spec,
            exclude_hosts=tuple(self._excluded_hosts),
            preserve_watchdog=dict(self._watchdog_state),
            prev_meta=self._prev_meta,
        )

    def tick(self) -> None:
        """Advance initial seek, 0.6s seek coalescer, 8s stall watchdog, OSD, and resume."""
        with self._lock:
            if self._session is None or self._session.get("preview"):
                return
            mono = float(self._mono())
            now_i = int(self._clock())
            playing, pos, total = self._read_player_times()

            if playing and not self._initial_seek_done:
                self._step_initial_seek(pos, total, mono)
                pos = self._last_pos

            delta = self._coalescer.flush(mono)
            if delta is not None and self._session is not None:
                plan = sp.plan_seek(
                    self._session,
                    op="seek_by",
                    seconds=delta,
                    pos=self._last_pos,
                    total=self._last_total,
                    now=now_i,
                    store=self._get_store(),
                )
                self._execute_seek_plan(plan)
                if self._session is None:
                    return
                pos = self._last_pos

            if (
                not self._av_started
                and playing
                and total >= sp.MIN_TOTAL
                and (pos >= 0.5 or (self._initial_seek_done and pos > 0))
            ):
                self._av_started = True
                if self._av_started_mono is None:
                    self._av_started_mono = mono

            if (
                playing
                and self._session is not None
                and not self._watchdog_exhausted
                and (
                    (self._av_started and self._initial_seek_done)
                    or (mono - self._session_start_mono >= STARTUP_GRACE)
                )
                and mono >= self._seek_grace_until
            ):
                wd = sp.evaluate_watchdog(
                    self._watchdog_state,
                    pos=pos,
                    now_mono=mono,
                    paused=self._paused,
                    ended=False,
                    expected_duration=self._expected_duration(),
                )
                self._watchdog_state = wd["state"]
                if wd["action"] == "failover":
                    self._failover_reopen(wd["resume_pos"])
                    return
                if wd["action"] == "give_up":
                    self._watchdog_exhausted = True
                    self._persist_resume(force_done=False, allow_done=False)

            self._update_osd(pos=self._last_pos)

            if mono - self._last_checkpoint_mono >= RESUME_CHECKPOINT_EVERY:
                self._last_checkpoint_mono = mono
                self._persist_resume(force_done=False, allow_done=False)

    # ---- Kodi Player callbacks ------------------------------------------------

    def onAVStarted(self) -> None:
        with self._lock:
            if self._session is None or self._session.get("preview"):
                return
            mono = float(self._mono())
            self._av_started = True
            if self._av_started_mono is None:
                self._av_started_mono = mono
            if self._watchdog_state:
                self._watchdog_state = {
                    **self._watchdog_state,
                    "last_advance_mono": mono,
                }
            playing, pos, total = self._read_player_times()
            if playing and not self._initial_seek_done:
                self._step_initial_seek(pos, total, mono)
            self._update_osd(pos=self._last_pos)

    def onPlayBackPaused(self) -> None:
        with self._lock:
            self._paused = True

    def onPlayBackResumed(self) -> None:
        with self._lock:
            self._paused = False

    def onPlayBackSeek(self, seek_time, seek_offset) -> None:
        with self._lock:
            if self._reopening or self._session is None or self._coalescer.has_pending():
                return
            if self._session.get("kind") == "live" and seek_offset < -sp.RAW_LIVE_REWIND_THRESHOLD * 1000:
                sec = int(seek_offset / 1000.0)
                plan = sp.plan_seek(
                    self._session,
                    op="seek_by",
                    seconds=sec,
                    pos=self._last_pos,
                    total=self._last_total,
                    now=int(self._clock()),
                    store=self._get_store(),
                )
                self._execute_seek_plan(plan)

    def onPlayBackEnded(self) -> None:
        # Never call getPlayingFile() here: Kodi has already torn down player state on EOF.
        with self._lock:
            if self._reopening or self._session is None:
                return
            if self._session.get("preview"):
                self._cleanup_session()
                return
            sess = self._session
            pos = self._last_pos
            mono = float(self._mono())
            now_i = int(self._clock())

            wd = sp.evaluate_watchdog(
                self._watchdog_state,
                pos=pos,
                now_mono=mono,
                paused=self._paused,
                ended=True,
                expected_duration=self._expected_duration(),
            )
            self._watchdog_state = wd["state"]
            if wd["action"] == "failover":
                self._failover_reopen(wd["resume_pos"])
                return
            if wd["action"] == "cooldown":
                return
            if wd["action"] == "give_up":
                self._persist_resume(force_done=False, allow_done=False)
                self._cleanup_session()
                return

            cur_meta = {
                "cid": sess.get("cid", ""),
                "epg_id": sess.get("epg_id", ""),
                "title": sess.get("title", ""),
                "slot_start": sess.get("slot_start", 0),
                "slot_stop": sess.get("slot_stop", 0),
                "total": max(1, int(sess.get("slot_stop", 0)) - int(sess.get("slot_start", 0))),
            }
            if sess.get("kind") == "epg":
                self._mark_epg_done(cur_meta, float(now_i))
                roll = sp.plan_slot_end(sess, pos=pos, now=now_i, store=self._get_store())
                if roll is not None:
                    if self._start_session(roll, prev_meta=cur_meta):
                        return
            else:
                self._persist_resume(force_done=True, allow_done=True)
            self._cleanup_session()

    def onPlayBackStopped(self) -> None:
        with self._lock:
            if self._reopening or self._session is None:
                return
            if self._session.get("preview"):
                self._cleanup_session()
                return
            self._persist_resume(force_done=False, allow_done=True)
            self._cleanup_session()

    def onPlayBackError(self) -> None:
        with self._lock:
            if self._reopening or self._session is None:
                return
            if self._session.get("preview"):
                self._cleanup_session()
                return
            wd = sp.evaluate_watchdog(
                self._watchdog_state,
                pos=self._last_pos,
                now_mono=float(self._mono()),
                paused=self._paused,
                ended=True,
                expected_duration=self._expected_duration(),
            )
            self._watchdog_state = wd["state"]
            if wd["action"] == "failover":
                self._failover_reopen(wd["resume_pos"])
                return
            self._persist_resume(force_done=False, allow_done=False)
            self._cleanup_session()
