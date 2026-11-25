"""SWEET.TV app: unified modal overlay (400 list + 410 season/day tabs) for Show/Series episodes and 7-day Channel Guide."""
import threading

import mediastick_sweetapi as sweetapi
from resources.lib import sweettv_data as data, sweettv_demo, sweettv_items as items, sweettv_play as play, \
    sweettv_sections as sections, sweettv_text as words, ui

GUIDE = 400
MODAL_TABS = 410
GUIDE_BUTTON = 212


class Guide:
    def _guide_setup(self):
        self.modal_kind = ""        # "" | "show" | "guide"
        self.modal_gen = 0
        self.modal_tabs = []        # [(value, label), ...]
        self.modal_tab_idx = 0
        self.modal_seasons = []     # for show/series: [{"title": ..., "episodes": [...]}, ...]
        self.modal_rows = []        # current rows in 400
        self.modal_channel = None   # Channel for guide mode
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
            self._prop("modal", "")
            self._prop("guide", "")
            self._prop("guide_title", "")
            self.getControl(GUIDE).reset()
            self.getControl(MODAL_TABS).reset()
        self._select_grid(pos)
        self._focus_on(self.GRID_ID)

    def _open_show_modal(self, card: sections.Card):
        with self._lock:
            self.modal_gen += 1
            gen = self.modal_gen
            self.modal_kind = "show"
            self.modal_return_pos = max(0, self.getControl(self.GRID_ID).getSelectedPosition())
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
            if "seasons" in detail and detail["seasons"]:
                seasons = [
                    {"title": s.get("title") or words.tr("Season {n}").format(n=i + 1),
                     "episodes": s.get("episodes") or []}
                    for i, s in enumerate(detail["seasons"])
                ]
            else:
                eps = detail.get("episodes") or []
                seasons = [{"title": words.tr("Episodes"), "episodes": eps}] if eps else []
            self.modal_seasons = seasons
            self.modal_tabs = [(i, s["title"]) for i, s in enumerate(seasons)]
            self.modal_tab_idx = 0
            self._render_show_tab(0)
        self._focus_on(GUIDE)

    def _render_show_tab(self, idx):
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
            list_ctl.selectItem(0)

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
            self.modal_return_pos = max(0, self.getControl(self.GRID_ID).getSelectedPosition())
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

    def _modal_click(self):
        with self._lock:
            pos = self.getControl(GUIDE).getSelectedPosition()
            if pos < 0 or pos >= len(self.modal_rows):
                return
            row = self.modal_rows[pos]
            kind = self.modal_kind
            ch = self.modal_channel
            title = self.modal_show_title
        if kind == "show":
            url = row.get("vod_url") or row.get("url") or ""
            if not url:
                return
            resume = int(row.get("resume") or 0)
            if resume > 0 and "start=" not in url:
                url = f"{url}{'&' if '?' in url else '?'}start={resume}"
            if row.get("epg") and row.get("cid"):
                session = play.Session(str(row["cid"]), str(row["epg"]), str(row.get("title") or title),
                                       int(row.get("start") or 0), int(row.get("stop") or 0), url=url)
            else:
                session = play.Session("", "", str(row.get("title") or title), 0, 0, url=url)
            self._start_playback(url, session=session, seek_to=resume)
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
