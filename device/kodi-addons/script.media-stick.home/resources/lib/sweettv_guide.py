"""SWEET.TV app: unified modal overlay (400 list + 410 season/day tabs) for Show/Series episodes and 7-day Channel Guide."""
import threading

import mediastick_resume as mr
import mediastick_sweetapi as sweetapi
from resources.lib import sweettv_data as data, sweettv_demo, sweettv_items as items, sweettv_play as play, \
    sweettv_sections as sections, sweettv_text as words, ui

GUIDE = 400
MODAL_TABS = 410
GUIDE_BUTTON = 212
RESUME_BUTTON = 210


class Guide:
    def _guide_setup(self):
        self.modal_kind = ""        # "" | "show" | "guide" | "detail"
        self.modal_gen = 0
        self.modal_tabs = []        # [(value, label), ...]
        self.modal_tab_idx = 0
        self.modal_seasons = []     # for show/series: [{"title": ..., "episodes": [...]}, ...]
        self.modal_rows = []        # current rows in 400
        self.modal_channel = None   # Channel for guide mode
        self.modal_card = None
        self.modal_movie_id = ""
        self.modal_next_up = None
        self.modal_flat_tv = False
        self.modal_show_title = ""
        self.modal_return_pos = 0

    def _modal_open(self):
        return bool(self.modal_kind)

    def _guide_close(self):
        with self._lock:
            if not self.modal_kind:
                return
            pos = self.modal_return_pos
            self.modal_kind = ""
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self.modal_card = None
            self.modal_movie_id = ""
            self.modal_next_up = None
            self.modal_flat_tv = False
            self._prop("modal", "")
            self._prop("guide", "")
            self._prop("guide_title", "")
            self.getControl(GUIDE).reset()
            self.getControl(MODAL_TABS).reset()
        self._select_grid(pos)
        self._focus_on(self._grid_id())

    def _open_detail_modal(self, card: sections.Card):
        with self._lock:
            self.modal_gen += 1
            self.modal_kind = "detail"
            self.modal_card = card
            self.modal_return_pos = max(0, self.getControl(self._grid_id()).getSelectedPosition())
            self.modal_show_title = card.title
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self._prop("modal", "detail")
            self._prop("guide", "")
            self._prop("guide_title", card.title)
            self._sync_hero(card)
            self.getControl(GUIDE).reset()
            self.getControl(MODAL_TABS).reset()
        self._focus_on(RESUME_BUTTON)

    def _sync_show_cta(self, next_up):
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

    def _open_show_modal(self, card: sections.Card):
        with self._lock:
            if not self.demo:
                self.resume_doc = mr.load()
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "show"
            self.modal_card = card
            self.modal_movie_id = card.key if card.kind == "series" else ""
            self.modal_next_up = None
            self.modal_flat_tv = False
            self.modal_return_pos = max(0, self.getControl(self._grid_id()).getSelectedPosition())
            self.modal_show_title = card.title
            self.modal_rows = []
            self.modal_tabs = []
            self.modal_seasons = []
            self._prop("modal", "show")
            self._prop("guide", "1")
            self._prop("guide_title", card.title)
            self.getControl(GUIDE).reset()
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
            has_seasons = bool(detail.get("seasons"))
            if has_seasons:
                seasons = [
                    {"title": s.get("title") or words.tr("Season {n}").format(n=i + 1),
                     "episodes": s.get("episodes") or []}
                    for i, s in enumerate(detail["seasons"])
                ]
            else:
                eps = detail.get("episodes") or []
                seasons = [{"title": words.tr("Episodes"), "episodes": eps}] if eps else []
            self.modal_movie_id = str(detail.get("movie_id") or self.modal_movie_id or "")
            self.modal_flat_tv = not has_seasons
            self.modal_seasons = seasons
            self.modal_tabs = [(i, s["title"]) for i, s in enumerate(seasons)]
            nu = detail.get("next_up") or (
                sweetapi.resolve_next_up(episodes=seasons[0]["episodes"]) if (self.modal_flat_tv and seasons)
                else sweetapi.resolve_next_up(seasons=seasons)
            )
            self.modal_next_up = nu
            self._sync_show_cta(nu)
            s_idx = int(nu["season_index"]) if nu else 0
            e_idx = int(nu["episode_index"]) if nu else 0
            self.modal_tab_idx = s_idx
            self._render_show_tab(s_idx, select_ep=e_idx)
        self._focus_on(GUIDE)

    def _render_show_tab(self, idx, select_ep=0):
        if not self.modal_seasons:
            self.modal_rows = []
            self.getControl(GUIDE).reset()
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
        list_ctl = self.getControl(GUIDE)
        list_ctl.reset()
        list_ctl.addItems(items.episode_items(eps))
        if eps:
            list_ctl.selectItem(max(0, min(int(select_ep or 0), len(eps) - 1)))

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

    def _guide_show(self):
        card = self._focused_card()
        if card is None:
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if card.kind != "channel" or not self.catalog:
            return
        ch = next((c for c in self.catalog.channels if c.cid == card.cid), None)
        if ch is None:
            return
        with self._lock:
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "guide"
            self.modal_channel = ch
            self.modal_return_pos = max(0, self.getControl(self._grid_id()).getSelectedPosition())
            now = self._now()
            tabs = sections.day_tabs(ch.days if ch.catchup else 0, 3, now)
            today_idx = min(len(tabs) - 1, ch.days if ch.catchup else 0)
            self.modal_tabs = tabs
            self.modal_tab_idx = today_idx
            self.modal_rows = []
            self._prop("modal", "guide")
            self._prop("guide", "1")
            self._prop("guide_title", ch.name)
            tabs_ctl = self.getControl(MODAL_TABS)
            tabs_ctl.reset()
            tabs_ctl.addItems(items.modal_tab_items(tabs, today_idx))
            tabs_ctl.selectItem(today_idx)
            self.getControl(GUIDE).reset()
            demo = self.demo
            raw = self.raw_catalog
        day_unix = tabs[today_idx][0]
        threading.Thread(
            target=self._load_guide_day,
            args=(gen, ch, day_unix, demo, raw, now),
            daemon=True,
        ).start()

    def _load_guide_day(self, gen, ch, day_unix, demo, raw, now):
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
            self.modal_rows = list(rows)
            list_ctl = self.getControl(GUIDE)
            list_ctl.reset()
            list_ctl.addItems(items.guide_items(rows))
            if rows:
                live_idx = next((i for i, r in enumerate(rows) if r.get("live")), 0)
                list_ctl.selectItem(live_idx)
        self._focus_on(GUIDE)

    def _modal_select_tab(self, idx):
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
                tabs_ctl = self.getControl(MODAL_TABS)
                tabs_ctl.reset()
                tabs_ctl.addItems(items.modal_tab_items(self.modal_tabs, idx))
                tabs_ctl.selectItem(idx)
                ch = self.modal_channel
                day_unix = self.modal_tabs[idx][0]
                demo = self.demo
                raw = self.raw_catalog
                now = self._now()
                threading.Thread(target=self._load_guide_day, args=(gen, ch, day_unix, demo, raw, now), daemon=True).start()

    def _play_modal_row(self, row, season_num=0):
        url = row.get("vod_url") or row.get("url") or ""
        if not url:
            return
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
                                   url=url, season=season_num, episode=ep_num, thumb=thumb)
        else:
            session = play.Session("", "", full_title, 0, 0,
                                   url=url, season=season_num, episode=ep_num, thumb=thumb)
        self._start_playback(url, session=session, seek_to=resume)

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
            s_num = int(nu.get("season_number") or (si + 1))
        self._play_modal_row(row, season_num=s_num)

    def _modal_click(self):
        with self._lock:
            pos = self.getControl(GUIDE).getSelectedPosition()
            if pos < 0 or pos >= len(self.modal_rows):
                return
            row = self.modal_rows[pos]
            kind = self.modal_kind
            ch = self.modal_channel
            tab_idx = self.modal_tab_idx
            s_num = tab_idx + 1 if kind == "show" else 0
        if kind == "show":
            self._play_modal_row(row, season_num=s_num)
        elif kind == "guide" and ch is not None:
            if row.get("live"):
                url = data.play_url(ch.cid)
                self._start_playback(url, cid=ch.cid)
            elif row.get("playable_in_archive") and row.get("epg"):
                url = data.play_url(ch.cid, row["epg"])
                session = play.Session(ch.cid, str(row["epg"]), str(row.get("title") or ""),
                                       int(row.get("start") or 0), int(row.get("stop") or 0), url=url)
                self._start_playback(url, cid=ch.cid, session=session)
            else:
                ui.notify(words.tr("This programme has not aired yet."))
