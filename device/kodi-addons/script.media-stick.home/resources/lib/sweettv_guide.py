"""SWEET.TV app: unified Full-Screen Hero Hub overlay (400 list + 410 season/day tabs) for Movie, Show/Series, and Channel Hubs."""
from datetime import date
import threading

import mediastick_resume as mr
import mediastick_sweetapi as sweetapi
from resources.lib import sweettv_data as data, sweettv_demo, sweettv_files as files, sweettv_items as items, \
    sweettv_play as play, sweettv_sections as sections, sweettv_text as words, ui

GUIDE = 400
SHOW_EPISODES = 421
MODAL_TABS = 410
GUIDE_BUTTON = 212
RESUME_BUTTON = 210
ALT_BUTTON = 211
BTN_FAV = 213


class Guide:
    def _guide_setup(self):
        self.modal_kind = ""        # "" | "show" | "guide" | "detail"
        self.modal_gen = 0
        self.modal_tabs = []        # [(value, label), ...]
        self.modal_tab_idx = 0
        self.modal_seasons = []     # for show/series: [{"number": ..., "title": ..., "episodes": [...]}, ...]
        self.modal_rows = []        # current rows in 400
        self.modal_channel = None   # Channel for guide mode
        self.modal_card = None
        self.modal_movie_id = ""
        self.modal_next_up = None
        self.modal_flat_tv = False
        self.modal_show_title = ""
        self.modal_return_pos = 0
        self.modal_target_epg = ""

    def _modal_open(self):
        return bool(self.modal_kind)

    def _guide_close(self):
        with self._lock:
            if not self.modal_kind:
                return
            self._cancel_autoplay()
            pos = self.modal_return_pos
            self.modal_kind = ""
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self.modal_channel = None
            self.modal_card = None
            self.modal_movie_id = ""
            self.modal_next_up = None
            self.modal_flat_tv = False
            self.modal_target_epg = ""
            self._prop("modal", "")
            self._prop("guide", "")
            self._prop("guide_title", "")
            self.getControl(GUIDE).reset()
            self.getControl(SHOW_EPISODES).reset()
            self.getControl(MODAL_TABS).reset()
        self._select_grid(pos)
        self._focus_on(self._grid_id())

    def _open_detail_modal(self, card: sections.Card):
        with self._lock:
            self._cancel_autoplay()
            if not self.demo:
                self.resume_doc = mr.load()
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "detail"
            self.modal_card = card
            self.modal_channel = None
            self.modal_return_pos = self._active_grid_pos()
            self.modal_show_title = card.title
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self.modal_target_epg = ""
            self._prop("modal", "detail")
            self._prop("guide", "")
            self._prop("guide_title", card.title)
            self._sync_hero(card, immediate=True)
            self._prop("has_guide", "")
            self.getControl(GUIDE).reset()
            self.getControl(SHOW_EPISODES).reset()
            self.getControl(MODAL_TABS).reset()
            demo = self.demo
            resume_doc = self.resume_doc
            favs = self.fav_keys
        self._focus_on(RESUME_BUTTON)
        if not demo and card.key:
            threading.Thread(
                target=self._load_detail_modal,
                args=(gen, card, resume_doc, favs),
                daemon=True,
            ).start()

    def _load_detail_modal(self, gen, card: sections.Card, resume_doc, favs):
        try:
            detail = sweetapi.vod_detail(card.key, local=resume_doc, favs=favs, tr=words.tr)
        except Exception as e:
            ui.log(f"SWEET.TV detail modal failed: {e!r}")
            detail = {"ok": False}
        promote = False
        focus_eps = True
        with self._lock:
            if self._stop.is_set() or gen != self.modal_gen or self.modal_kind != "detail":
                return
            if not detail.get("ok"):
                return
            if detail.get("seasons"):
                focus_eps = self._apply_show_detail(card, detail)
                promote = True
            else:
                meta, desc = sections.detail_meta_and_desc(detail, card)
                banner = str(detail.get("banner") or card.banner or card.art or "")
                art = str(detail.get("poster") or card.art or "")
                vod_url = str(detail.get("vod_url") or card.play_url or "")
                pos = int(detail.get("resume") or card.resume_pos or 0)
                resume_label = words.tr("Continue from {time}").format(time=sections.fmt_mmss(pos)) if pos else ""
                updated = card._replace(
                    title=str(detail.get("title") or card.title),
                    art=art,
                    banner=banner,
                    meta=meta,
                    desc=desc,
                    play_url=vod_url,
                    alt_url=vod_url if pos else card.alt_url,
                    resume_pos=pos,
                    resume_label=resume_label,
                    fav=bool(detail.get("favourite", card.fav)),
                    playable=bool(vod_url),
                )
                self.modal_card = updated
                self._prop("guide_title", updated.title)
                self._sync_hero(updated, immediate=True)
                self._prop("has_guide", "")
        if promote:
            self._focus_on(SHOW_EPISODES if focus_eps else BTN_FAV)

    def _apply_show_detail(self, card: sections.Card, detail: dict) -> bool:
        self.modal_kind = "show"
        self._prop("modal", "show")
        self._prop("guide", "1")
        has_seasons = bool(detail.get("seasons"))
        if has_seasons:
            raw_seasons = sorted(
                detail["seasons"],
                key=lambda s: (int(s.get("number") or 0), int(s.get("id") or 0)),
            )
            seasons = []
            for i, s in enumerate(raw_seasons):
                s_num = int(s.get("number") or (i + 1))
                raw_title = str(s.get("title") or "").strip()
                s_title = raw_title if raw_title else words.tr("{n} season").format(n=s_num)
                eps = sorted(
                    list(s.get("episodes") or ()),
                    key=lambda ep: (int(ep.get("number") or 0), int(ep.get("episode_id") or ep.get("id") or 0)),
                )
                capped, seen_soon = [], False
                for ep in eps:
                    if ep.get("coming_soon") or ep.get("playable") is False:
                        if seen_soon:
                            continue
                        seen_soon = True
                    capped.append(ep)
                seasons.append({"number": s_num, "title": s_title, "episodes": capped})
            nu = sweetapi.resolve_next_up(seasons=seasons)
        else:
            eps = detail.get("episodes") or []
            seasons = [{"number": 1, "title": words.tr("Episodes"), "episodes": eps}] if eps else []
            nu = detail.get("next_up") or (sweetapi.resolve_next_up(episodes=eps) if eps else None)
        has_episodes = any(s.get("episodes") for s in seasons)
        meta, desc = sections.detail_meta_and_desc(detail, card)
        if not has_episodes:
            meta = words.tr("Coming soon – no episodes yet")
        banner = str(detail.get("banner") or card.banner or card.art or "")
        wide_art = str(detail.get("wide_art") or card.wide_art or banner or "")
        updated_card = card._replace(
            title=str(detail.get("title") or card.title),
            banner=banner,
            wide_art=wide_art,
            meta=meta,
            desc=desc,
            fav=bool(detail.get("favourite", card.fav)),
        )
        self.modal_card = updated_card
        self._prop("guide_title", updated_card.title)
        self._sync_hero(updated_card, immediate=True)
        self.modal_movie_id = str(detail.get("movie_id") or self.modal_movie_id or card.key or "")
        self.modal_flat_tv = not has_seasons
        self.modal_seasons = seasons if has_episodes else []
        self.modal_tabs = [(i, s["title"]) for i, s in enumerate(self.modal_seasons)]
        self.modal_next_up = nu if has_episodes else None
        if not has_episodes:
            self._sync_show_cta(None)
            self._prop("hero_meta", meta)
            self._render_show_tab(0)
            return False
        self._sync_show_cta(nu)
        s_idx = int(nu["season_index"]) if nu else 0
        e_idx = int(nu["episode_index"]) if nu else 0
        self.modal_tab_idx = s_idx
        self._render_show_tab(s_idx, select_ep=e_idx)
        return True

    def _sync_show_cta(self, next_up):
        if not self.modal_seasons:
            try:
                self.getControl(RESUME_BUTTON).setLabel("")
            except Exception:
                pass
            self._prop("hero_play", "")
            self._prop("has_play", "")
            self._prop("has_alt", "")
            self._prop("has_guide", "")
            self._prop("guide", "")
            return
        if not next_up:
            label = words.tr("Watch")
        elif next_up.get("mode") == "resume" and int(next_up.get("resume") or 0) > 0:
            label = words.tr("Continue S{s} E{e} from {time}").format(
                s=next_up.get("season_number") or 1,
                e=next_up.get("episode_number") or 1,
                time=sections.fmt_mmss(int(next_up["resume"])),
            )
        else:
            label = words.tr("Watch S{s} E{e}").format(
                s=next_up.get("season_number") or 1,
                e=next_up.get("episode_number") or 1,
            )
        try:
            self.getControl(RESUME_BUTTON).setLabel(label)
        except Exception:
            pass
        self._prop("hero_play", label)
        self._prop("has_play", "1")
        self._prop("has_alt", "")
        self._prop("has_guide", "")

    def _open_show_modal(self, card: sections.Card):
        with self._lock:
            self._cancel_autoplay()
            if not self.demo:
                self.resume_doc = mr.load()
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "show"
            self.modal_card = card
            self.modal_channel = None
            self.modal_movie_id = card.key if card.kind == "series" else ""
            self.modal_next_up = None
            self.modal_flat_tv = False
            self.modal_return_pos = self._active_grid_pos()
            self.modal_show_title = card.title
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self.modal_target_epg = ""
            self._prop("modal", "show")
            self._prop("guide", "1")
            self._prop("guide_title", card.title)
            self._sync_hero(card, immediate=True)
            self._prop("has_guide", "")
            self.getControl(GUIDE).reset()
            self.getControl(SHOW_EPISODES).reset()
            self.getControl(MODAL_TABS).reset()
            demo = self.demo
            raw = self.raw_catalog
            resume_doc = self.resume_doc
            favs = self.fav_keys
            now = self._now()
        threading.Thread(
            target=self._load_show_modal,
            args=(gen, card, demo, raw, resume_doc, favs, now),
            daemon=True,
        ).start()

    def _load_show_modal(self, gen, card: sections.Card, demo, raw, resume_doc, favs, now):
        try:
            if demo:
                detail = sweettv_demo.demo_show_detail(card.key if card.kind != "series" else f"vod:{card.key}", now)
            elif card.kind == "series":
                detail = sweetapi.vod_detail(card.key, local=resume_doc, favs=favs, tr=words.tr)
            else:
                detail = sweetapi.show_detail(card.key, raw or {}, now=now, local=resume_doc, favs=favs, tr=words.tr)
        except Exception as e:
            ui.log(f"SWEET.TV show modal failed: {e!r}")
            detail = {"ok": False}

        with self._lock:
            if self._stop.is_set() or gen != self.modal_gen or self.modal_kind != "show":
                return
            if not detail.get("ok"):
                self._prop("guide_title", f"{card.title}  ·  {words.tr('This show has no episodes to show.')}")
                return
            focus_eps = self._apply_show_detail(card, detail)
        self._focus_on(SHOW_EPISODES if focus_eps else BTN_FAV)

    def _render_show_tab(self, idx, select_ep=0):
        if not self.modal_seasons:
            self.modal_rows = []
            self.getControl(SHOW_EPISODES).reset()
            self.getControl(MODAL_TABS).reset()
            return
        idx = max(0, min(idx, len(self.modal_seasons) - 1))
        self.modal_tab_idx = idx
        eps = self.modal_seasons[idx]["episodes"]
        self.modal_rows = list(eps)
        tabs_ctl = self.getControl(MODAL_TABS)
        tabs_ctl.reset()
        tabs_ctl.addItems(items.modal_tab_items(self.modal_tabs, idx))
        tabs_ctl.selectItem(idx)
        fallback = (self.modal_card.wide_art or self.modal_card.banner) if self.modal_card else ""
        ep_ctl = self.getControl(SHOW_EPISODES)
        ep_ctl.reset()
        ep_ctl.addItems(items.episode_items(eps, fallback_art=fallback))
        if eps:
            ep_ctl.selectItem(max(0, min(int(select_ep or 0), len(eps) - 1)))

    def _refresh_show_modal_progress(self):
        with self._lock:
            if self.modal_kind != "show" or not self.modal_seasons:
                return
            if not self.demo:
                self.resume_doc = mr.load()
            sweetapi.apply_progress_to_seasons(self.modal_seasons, self.resume_doc, movie_id=self.modal_movie_id)
            nu = sweetapi.resolve_next_up(episodes=self.modal_seasons[0]["episodes"]) if self.modal_flat_tv else sweetapi.resolve_next_up(seasons=self.modal_seasons)
            self.modal_next_up = nu
            self._sync_show_cta(nu)
            if nu:
                self._render_show_tab(int(nu["season_index"]), select_ep=int(nu["episode_index"]))
            else:
                self._render_show_tab(self.modal_tab_idx)

    def _sync_channel_hub_ctas(self, ch, card: sections.Card):
        play_label = words.tr("Watch live")
        alt_label = words.tr("From start (0:00)") if (ch.catchup and card.alt_url) else ""
        try:
            self.getControl(RESUME_BUTTON).setLabel(play_label)
            self.getControl(ALT_BUTTON).setLabel(alt_label)
        except Exception:
            pass
        self._prop("hero_play", play_label)
        self._prop("has_play", "1")
        self._prop("hero_alt", alt_label)
        self._prop("has_alt", "1" if alt_label else "")
        self._prop("has_guide", "")

    def _apply_guide_rows(self, rows, target_epg=""):
        self.modal_rows = list(rows)
        list_ctl = self.getControl(GUIDE)
        list_ctl.reset()
        list_ctl.addItems(items.guide_items(rows))
        if rows:
            idx = None
            if target_epg:
                idx = next((i for i, r in enumerate(rows) if str(r.get("epg") or "") == str(target_epg)), None)
            if idx is None:
                idx = next((i for i, r in enumerate(rows) if r.get("live")), 0)
            list_ctl.selectItem(idx)

    def _open_channel_hub(self, cid, target_day=None, target_epg=""):
        if not self.catalog:
            return
        ch = next((c for c in self.catalog.channels if c.cid == str(cid)), None)
        if ch is None:
            return
        with self._lock:
            self._cancel_autoplay()
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "guide"
            self.modal_channel = ch
            self.modal_target_epg = str(target_epg or "")
            self.modal_return_pos = self._active_grid_pos()
            now = self._now()
            card = sections.channel_card(ch, self.cat_names, now, self.resume_doc, self.fav_keys)
            self.modal_card = card
            tabs = sections.day_tabs(ch.days if ch.catchup else 0, 3, now)
            today_idx = min(len(tabs) - 1, ch.days if ch.catchup else 0)
            tab_idx = today_idx
            if target_day is not None and int(target_day) > 0:
                wanted_date = date.fromtimestamp(int(target_day))
                found_idx = next((i for i, (ts, _) in enumerate(tabs) if date.fromtimestamp(int(ts)) == wanted_date), None)
                if found_idx is not None:
                    tab_idx = found_idx
            self.modal_tabs = tabs
            self.modal_tab_idx = tab_idx
            self.modal_rows = []
            self._prop("modal", "guide")
            self._prop("guide", "1")
            self._prop("guide_title", ch.name)
            self._sync_hero(card, immediate=True)
            self._sync_channel_hub_ctas(ch, card)
            tabs_ctl = self.getControl(MODAL_TABS)
            tabs_ctl.reset()
            tabs_ctl.addItems(items.modal_tab_items(tabs, tab_idx))
            tabs_ctl.selectItem(tab_idx)
            day_unix = tabs[tab_idx][0]
            demo = self.demo
            raw = self.raw_catalog
            if not demo:
                day_key = date.fromtimestamp(int(day_unix)).isoformat()
                cached_rows = files.channel_day(ch.cid, day_key, now=now, tr=words.tr)
                self._apply_guide_rows(cached_rows, target_epg=self.modal_target_epg)
            else:
                self.getControl(GUIDE).reset()
        threading.Thread(
            target=self._load_guide_day,
            args=(gen, ch, day_unix, demo, raw, now, self.modal_target_epg, True),
            daemon=True,
        ).start()
        self._focus_on(GUIDE)

    def _guide_show(self):
        card = self._focused_card()
        if card is None:
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if card.kind == "channel" and card.cid:
            self._open_channel_hub(card.cid)

    def _load_guide_day(self, gen, ch, day_unix, demo, raw, now, target_epg="", focus_list=True):
        try:
            res = sweettv_demo.demo_day(ch.cid, day_unix, raw or {}, now) if demo else sweetapi.day(
                ch.cid, day_unix, raw or {}, now=now, tr=words.tr)
            rows = res.get("items") or [] if res.get("ok") else []
        except Exception as e:
            ui.log(f"SWEET.TV guide day failed: {e!r}")
            rows = []
        with self._lock:
            if self._stop.is_set() or gen != self.modal_gen or self.modal_kind != "guide":
                return
            self._apply_guide_rows(rows, target_epg=target_epg)
        if focus_list:
            self._focus_on(GUIDE)

    def _modal_select_tab(self, idx, keep_focus=False):
        with self._lock:
            if not self.modal_tabs or idx < 0 or idx >= len(self.modal_tabs):
                return
            if self.modal_kind == "show":
                self._render_show_tab(idx)
                return
            if self.modal_kind == "guide" and self.modal_channel:
                self.modal_gen += 1
                gen = self.modal_gen
                self.modal_tab_idx = idx
                self.modal_target_epg = ""
                tabs_ctl = self.getControl(MODAL_TABS)
                tabs_ctl.reset()
                tabs_ctl.addItems(items.modal_tab_items(self.modal_tabs, idx))
                tabs_ctl.selectItem(idx)
                ch = self.modal_channel
                day_unix = self.modal_tabs[idx][0]
                demo = self.demo
                raw = self.raw_catalog
                now = self._now()
                if not demo:
                    day_key = date.fromtimestamp(int(day_unix)).isoformat()
                    cached_rows = files.channel_day(ch.cid, day_key, now=now, tr=words.tr)
                    self._apply_guide_rows(cached_rows)
                threading.Thread(
                    target=self._load_guide_day,
                    args=(gen, ch, day_unix, demo, raw, now, "", not keep_focus),
                    daemon=True,
                ).start()

    def _play_modal_row(self, row, season_num=0):
        url = row.get("vod_url") or row.get("url") or ""
        if row.get("coming_soon") or row.get("playable") is False or not url:
            ui.notify(words.tr("This episode has not been released yet."))
            return
        self._cancel_autoplay()
        resume = int(row.get("resume") or 0)
        if resume > 0 and "start=" not in url:
            url = f"{url}{'&' if '?' in url else '?'}start={resume}"
        ep_title = str(row.get("title") or "").strip()
        show_title = str(self.modal_show_title or "").strip()
        if show_title and ep_title and show_title.lower() not in ep_title.lower():
            full_title = f"{show_title} · {ep_title}"
        else:
            full_title = ep_title or show_title
        thumb = str(row.get("preview") or (self.modal_card.art if self.modal_card else "") or "")
        ep_num = int(row.get("number") or 0)
        if row.get("epg") and row.get("cid"):
            session = play.Session(str(row["cid"]), str(row["epg"]), full_title,
                                   int(row.get("start") or 0), int(row.get("stop") or 0),
                                   url=url, season=season_num, episode=ep_num, thumb=thumb, episode_mode=True)
            notify_spec = {
                "kind": "epg",
                "cid": str(row["cid"]),
                "epg_id": str(row["epg"]),
                "start_offset": resume,
                "from_start": resume == 0,
                "title": full_title,
                "episode_mode": True,
            }
        else:
            session = play.Session("", "", full_title, 0, 0,
                                   url=url, season=season_num, episode=ep_num, thumb=thumb, episode_mode=True)
            notify_spec = {"url": url, "start_offset": resume, "from_start": resume == 0,
                           "title": full_title, "episode_mode": True}
        self._start_playback(url, session=session, seek_to=resume, notify_spec=notify_spec)

    def _play_next_up(self):
        with self._lock:
            if self.modal_kind != "show" or not self.modal_seasons:
                return
            nu = self.modal_next_up
            if nu is None:
                return
            si = int(nu.get("season_index") or 0)
            ei = int(nu.get("episode_index") or 0)
            if not (0 <= si < len(self.modal_seasons)):
                return
            eps = self.modal_seasons[si].get("episodes") or ()
            if not (0 <= ei < len(eps)):
                return
            row = dict(eps[ei])
            if nu.get("mode") != "resume":
                row["resume"] = 0
            s_num = int(nu.get("season_number") or self.modal_seasons[si].get("number") or (si + 1))
        self._play_modal_row(row, season_num=s_num)

    def _modal_click(self):
        with self._lock:
            ctl_id = SHOW_EPISODES if self.modal_kind == "show" else GUIDE
            pos = self.getControl(ctl_id).getSelectedPosition()
            if pos < 0 or pos >= len(self.modal_rows):
                return
            row = self.modal_rows[pos]
            kind = self.modal_kind
            ch = self.modal_channel
            tab_idx = self.modal_tab_idx
            s_num = (int(self.modal_seasons[tab_idx].get("number") or (tab_idx + 1))
                     if kind == "show" and 0 <= tab_idx < len(self.modal_seasons) else 0)
        if kind == "show":
            self._play_modal_row(row, season_num=s_num)
        elif kind == "guide" and ch is not None:
            if row.get("live"):
                url = data.play_url(ch.cid)
                self._start_playback(url, cid=ch.cid, notify_spec={"kind": "live", "cid": ch.cid, "title": ch.name})
            elif row.get("can_archive") and row.get("epg"):
                url = data.play_url(ch.cid, row["epg"])
                title = str(row.get("title") or "")
                session = play.Session(ch.cid, str(row["epg"]), title,
                                       int(row.get("start") or 0), int(row.get("stop") or 0), url=url)
                self._start_playback(
                    url,
                    cid=ch.cid,
                    session=session,
                    notify_spec={
                        "kind": "epg",
                        "cid": ch.cid,
                        "epg_id": str(row["epg"]),
                        "start_offset": 0,
                        "from_start": True,
                        "title": title,
                    },
                )
            else:
                ui.notify(words.tr("This programme has not aired yet."))
