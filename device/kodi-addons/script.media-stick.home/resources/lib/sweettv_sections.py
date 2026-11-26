"""SWEET.TV app: pure data builders for the 7-section Netflix-style UI, filter chips, hero, and modals.

Ready data in -> pure dicts/tuples out. Nothing here imports xbmc or touches disk/network.
"""
from datetime import date, timedelta
from typing import NamedTuple, Optional, Tuple

from resources.lib import sweettv_data as data, sweettv_text as words, sweettv_view as view

RAIL = (
    ("search", "Search"),
    ("continue", "Continue"),
    ("favourites", "Favourites"),
    ("shows", "Shows"),
    ("series", "Series"),
    ("movies", "Movies"),
    ("channels", "TV Channels"),
)
SECTION_KEYS = tuple(k for k, _ in RAIL)
FILTERED_SECTIONS = frozenset(("search", "shows", "series", "movies", "channels"))
SORT_MODES_DEFAULT = (
    {"id": 1, "name": "Popular"},
    {"id": 3, "name": "IMDb Rating"},
    {"id": 2, "name": "Newest"},
    {"id": 5, "name": "A-Z"},
)


class Card(NamedTuple):
    kind: str           # channel | movie | series | show_vod | show_epg | show_tv | programme
    key: str            # unique id
    fav_key: str        # ch:<cid> | vod:<mid> | show:vod:<mid> | show:epg:<col> | show:tv:<sid>
    title: str
    art: str            # poster / logo URL or path
    banner: str         # 16:9 hero backdrop URL
    meta: str           # metadata line in hero
    desc: str           # 2-line description in hero
    play_url: str       # plugin:// URL for primary play (empty if modal-only or unplayable)
    alt_url: str        # plugin:// URL for "From start" (catchup programme or vod start)
    cid: str            # channel id if channel/programme
    epg: str            # epg id if programme
    start: int
    stop: int
    resume_pos: int     # seconds to seek on primary play
    bar: str            # sweettv-bar-XX.png or ""
    pbar: str           # sweettv-pbar-XX.png or ""
    fav: bool
    catchup: bool
    playable: bool
    dim: bool
    num: str
    initials: str
    plate: str
    plate_hi: str
    bg: str
    tint: str
    now: str
    nowline: str
    next: str
    nextline: str
    resume_label: str
    small: bool
    art_mode: str = ""
    wide_art: str = ""


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def fmt_mmss(seconds) -> str:
    s = max(0, int(seconds or 0))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _bar_from_fraction(fraction, wide=False) -> str:
    if fraction <= 0:
        return ""
    step = max(1, min(data.BAR_STEPS, round(fraction * data.BAR_STEPS)))
    return data.bar_name(step, wide=wide)


def _vod_progress(resume_doc, movie_id, episode_id="") -> Tuple[int, float]:
    items = (resume_doc or {}).get("items") or {}
    key = f"sw:vod:{movie_id}|{episode_id}" if episode_id else f"sw:vod:{movie_id}"
    entry = items.get(key)
    if not isinstance(entry, dict):
        return 0, 0.0
    total = int(entry.get("total") or 0)
    pos = int(entry.get("pos") or 0)
    if entry.get("done"):
        return 0, 1.0
    if pos >= 5 and total > 0:
        return pos, min(1.0, pos / total)
    return 0, 0.0


def _epg_progress(resume_doc, cid, epg) -> Tuple[int, float]:
    items = (resume_doc or {}).get("items") or {}
    entry = items.get(f"sw:{cid}|{epg}")
    if not isinstance(entry, dict):
        return 0, 0.0
    total = int(entry.get("total") or 0)
    pos = int(entry.get("pos") or 0)
    if entry.get("done"):
        return 0, 1.0
    if pos >= 5 and total > 0:
        return pos, min(1.0, pos / total)
    return 0, 0.0


def _palette(seed_text):
    c = view.colours(seed_text)
    return view.initials(seed_text), c["plate"], c["plate_hi"], c["bg"], c["tint"]


def channel_card(ch, cat_names, now, resume_doc=None, favs=()) -> Card:
    current, following = data.now_next(ch, now)
    step = data.progress_step(current, now) if current else 0
    bar = data.bar_name(step) if current else ""
    pbar = data.bar_name(step, wide=True) if current else ""
    cats = [cat_names[f"c:{k}"] for k in ch.cats if f"c:{k}" in cat_names][:2]
    meta_parts = ([words.tr("Channel {n}").format(n=ch.number)] if ch.number else []) + cats
    if ch.fast:
        meta_parts.append(words.tr("24/7"))
    meta = "  ·  ".join(meta_parts)
    now_text = current.title if current else (words.tr("No programme information") if not ch.epg else "")
    nowline = words.now_line(data.time_range(current)) if current else ""
    next_text = following.title if following else ""
    nextline = words.next_line(data.time_range(following), following.title) if following else ""
    desc = current.desc if current and current.desc else (now_text if now_text else nextline)
    alt_url = ""
    if current and current.epg_id and ch.catchup:
        alt_url = data.play_url(ch.cid, current.epg_id)
    initials, plate, plate_hi, bg, tint = _palette(ch.name)
    fav_key = f"ch:{ch.cid}"
    return Card(
        kind="channel", key=ch.cid, fav_key=fav_key, title=ch.name,
        art=ch.logo, banner=ch.banner or ch.logo, meta=meta, desc=desc,
        play_url=data.play_url(ch.cid), alt_url=alt_url,
        cid=ch.cid, epg=current.epg_id if current else "",
        start=current.start if current else 0, stop=current.stop if current else 0,
        resume_pos=0, bar=bar, pbar=pbar, fav=fav_key in favs,
        catchup=ch.catchup, playable=True, dim=False,
        num=str(ch.number) if ch.number else "",
        initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now=now_text, nowline=nowline, next=next_text, nextline=nextline,
        resume_label="", small=len(ch.name) > 22, art_mode="logo", wide_art=ch.banner,
    )


def vod_card(item, kind="movie", resume_doc=None, favs=()) -> Card:
    mid = str(item.get("id") or "")
    title = str(item.get("title") or "")
    year = int(item.get("year") or 0)
    imdb = float(item.get("imdb") or 0.0)
    duration = int(item.get("duration") or 0)
    meta_parts = []
    if year:
        meta_parts.append(str(year))
    if imdb > 0:
        meta_parts.append(f"IMDb {imdb:.1f}")
    if duration >= 60:
        meta_parts.append(words.tr("{n} min").format(n=duration // 60))
    pos, frac = _vod_progress(resume_doc, mid) if kind == "movie" else (0, 0.0)
    resume_label = words.tr("Continue from {time}").format(time=fmt_mmss(pos)) if pos else ""
    url = str(item.get("vod_url") or "")
    initials, plate, plate_hi, bg, tint = _palette(title)
    fav_key = f"vod:{mid}"
    return Card(
        kind=kind, key=mid, fav_key=fav_key, title=title,
        art=str(item.get("poster") or ""), banner=str(item.get("banner") or item.get("poster") or ""),
        meta="  ·  ".join(meta_parts), desc=str(item.get("description") or ""),
        play_url=url if kind == "movie" else "", alt_url=url if (kind == "movie" and pos) else "",
        cid="", epg="", start=0, stop=0, resume_pos=pos,
        bar=_bar_from_fraction(frac), pbar=_bar_from_fraction(frac, wide=True),
        fav=fav_key in favs, catchup=False, playable=bool(url), dim=False,
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now="", nowline="", next="", nextline="", resume_label=resume_label, small=len(title) > 22,
    )


def show_card(item, favs=()) -> Card:
    show_id = str(item.get("id") or "")
    kind = str(item.get("kind") or "show_vod")
    title = str(item.get("title") or "")
    year = int(item.get("year") or 0)
    imdb = float(item.get("imdb") or 0.0)
    meta_parts = [words.tr("Shows")]
    if year:
        meta_parts.append(str(year))
    if imdb > 0:
        meta_parts.append(f"IMDb {imdb:.1f}")
    fav_key = f"show:{show_id}"
    initials, plate, plate_hi, bg, tint = _palette(title)
    poster = str(item.get("poster") or "")
    art_mode = str(item.get("art_mode") or "")
    wide_art = str(item.get("wide_art") or "")
    banner = str(item.get("banner") or wide_art or poster or "")
    return Card(
        kind=kind, key=show_id, fav_key=fav_key, title=title,
        art=poster, banner=banner,
        meta="  ·  ".join(meta_parts), desc="",
        play_url="", alt_url="", cid="", epg="", start=0, stop=0,
        resume_pos=0, bar="", pbar="", fav=fav_key in favs,
        catchup=False, playable=True, dim=False,
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now="", nowline="", next="", nextline="", resume_label="", small=len(title) > 22,
        art_mode=art_mode, wide_art=wide_art,
    )


def search_card(row, resume_doc=None, favs=()) -> Card:
    kind = str(row.get("kind") or "")
    title = str(row.get("title") or "")
    subtitle = str(row.get("subtitle") or "")
    cid = str(row.get("cid") or "")
    epg = str(row.get("epg") or "")
    start = int(row.get("start") or 0)
    stop = int(row.get("stop") or 0)
    playable = bool(row.get("playable", True)) and row.get("available") is not False
    vod_url = str(row.get("vod_url") or "")
    art = str(row.get("image_url") or row.get("preview") or "")
    is_modal = kind in ("show_tv", "show_vod", "show_epg", "series")
    if is_modal:
        rid = str(row.get("id") or "")
        fav_key = f"vod:{rid}" if (kind == "series" and rid.isdigit()) else f"show:{rid}"
        url, pos, frac = "", 0, 0.0
        playable = True
    elif kind == "channel" and cid:
        url = data.play_url(cid)
        fav_key = f"ch:{cid}"
        pos, frac = 0, 0.0
    elif vod_url:
        url = vod_url
        rid = str(row.get("id") or "")
        fav_key = f"vod:{rid}" if rid.isdigit() else ""
        pos, frac = _vod_progress(resume_doc, rid) if rid.isdigit() else (0, 0.0)
    elif cid and epg:
        url = data.play_url(cid, epg)
        fav_key = f"ch:{cid}"
        pos, frac = _epg_progress(resume_doc, cid, epg)
    else:
        url, fav_key, pos, frac = "", "", 0, 0.0
    if kind == "programme":
        time_or_live = words.tr("Live") if row.get("live") else str(row.get("when") or "")
        meta_parts = [p for p in (time_or_live, str(row.get("channel_name") or ""), subtitle) if p]
    else:
        meta_parts = [p for p in (str(row.get("channel_name") or ""), str(row.get("when") or ""), subtitle) if p]
    art_mode = "logo" if kind in ("channel", "programme") else ""
    initials, plate, plate_hi, bg, tint = _palette(title)
    return Card(
        kind=kind or "movie", key=str(row.get("id") or cid or title), fav_key=fav_key, title=title,
        art=art, banner=art, meta="  ·  ".join(meta_parts), desc="",
        play_url=url if playable else "", alt_url=url if (playable and pos) else "",
        cid=cid, epg=epg, start=start, stop=stop, resume_pos=pos,
        bar=_bar_from_fraction(frac), pbar=_bar_from_fraction(frac, wide=True),
        fav=bool(fav_key and fav_key in favs), catchup=bool(row.get("can_archive")),
        playable=playable and bool(url), dim=not (playable and bool(url)),
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now="", nowline="", next="", nextline="",
        resume_label=words.tr("Continue from {time}").format(time=fmt_mmss(pos)) if pos else "",
        small=len(title) > 22, art_mode=art_mode,
    )


def _find_vod_episode(tdetail: dict, eid: str) -> Optional[dict]:
    for s in (tdetail.get("seasons") or ()):
        if not isinstance(s, dict):
            continue
        for ep in (s.get("episodes") or ()):
            if isinstance(ep, dict) and str(ep.get("episode_id") or ep.get("id") or "") == eid:
                return ep
    for ep in (tdetail.get("episodes") or ()):
        if isinstance(ep, dict) and str(ep.get("episode_id") or ep.get("id") or "") == eid:
            return ep
    return None


def _continue_vod_card(e: dict, pos: int, bar: str, pbar: str, resume_label: str, favs, recall_title) -> Card:
    mid = str(e.get("movie_id") or "")
    eid = str(e.get("episode_id") or "")
    saved_title = str(e.get("title") or "").strip()
    saved_thumb = str(e.get("thumb") or "").strip()
    tdetail = None
    if callable(recall_title) and mid:
        try:
            tdetail = recall_title(f"vod:{mid}")
        except Exception:
            tdetail = None
        if not isinstance(tdetail, dict):
            tdetail = None
    ep_match = _find_vod_episode(tdetail, eid) if (tdetail and eid) else None
    hydrated_title = ""
    if tdetail:
        show_t = str(tdetail.get("title") or "").strip()
        ep_t = str(ep_match.get("title") or "").strip() if ep_match else ""
        if show_t and ep_t and show_t.lower() not in ep_t.lower():
            hydrated_title = f"{show_t} · {ep_t}"
        else:
            hydrated_title = ep_t or show_t
    placeholder = f"VOD {mid}"
    title = (saved_title if saved_title and saved_title != placeholder else "") or hydrated_title or saved_title or placeholder
    poster = data.logo_of(tdetail.get("poster")) if tdetail else ""
    t_banner = data.logo_of(tdetail.get("banner")) if tdetail else ""
    ep_preview = data.logo_of(ep_match.get("preview")) if ep_match else ""
    art = saved_thumb or poster or ep_preview
    wide_art = ep_preview or t_banner
    banner = wide_art or art
    base_url = f"plugin://plugin.video.sweettv/playvod/{mid}|{eid or 'null'}|0"
    url = f"{base_url}?start={pos}" if pos > 0 else base_url
    fav_key = f"vod:{mid}"
    initials, plate, plate_hi, bg, tint = _palette(title)
    return Card(
        kind="movie" if not eid else "episode", key=f"{mid}|{eid}", fav_key=fav_key,
        title=title, art=art, banner=banner, meta=resume_label, desc="",
        play_url=url, alt_url=base_url, cid="", epg="", start=0, stop=0, resume_pos=pos,
        bar=bar, pbar=pbar, fav=fav_key in favs, catchup=False, playable=True, dim=False,
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now=resume_label, nowline="", next="", nextline="", resume_label=resume_label,
        small=len(title) > 22, wide_art=wide_art,
    )


def _continue_epg_card(e: dict, ch, now, pos: int, bar: str, pbar: str, resume_label: str,
                       favs, recall_prog, seen_generic: set) -> Optional[Card]:
    cid = str(e.get("cid") or "")
    epg = str(e.get("epg") or "")
    raw_title = str(e.get("title") or "").strip()
    start = int(e.get("start") or 0)
    stop = int(e.get("stop") or 0)
    epg_prog = next((p for p in ch.epg if p.epg_id == epg), None) if (ch and epg) else None
    rec = None
    if callable(recall_prog) and cid and epg:
        try:
            rec = recall_prog(cid, epg)
        except Exception:
            rec = None
        if not isinstance(rec, dict):
            rec = None
    if start <= 0:
        start = int((epg_prog.start if epg_prog else 0) or ((rec.get("start") or rec.get("time_start")) if rec else 0) or 0)
    if stop <= 0:
        stop = int((epg_prog.stop if epg_prog else 0) or ((rec.get("stop") or rec.get("time_stop")) if rec else 0) or 0)
    prog_preview = data.logo_of(rec.get("preview") or rec.get("image_url")) if rec else ""
    ch_name = ch.name if ch else ""
    if not raw_title or (ch_name and raw_title == ch_name) or raw_title == f"Channel {cid}":
        prog_title = (epg_prog.title if epg_prog and epg_prog.title != "Programme" else "") or (
            str(rec.get("title") or "").strip() if rec else ""
        )
        title = prog_title or raw_title or (ch_name or f"Channel {cid}")
    else:
        title = raw_title
    if ch is not None and start > 0 and (not ch.catchup or start < now - max(1, ch.days) * 86400):
        return None
    if ch is not None and title == ch.name:
        if cid in seen_generic:
            return None
        seen_generic.add(cid)
        meta = resume_label
    else:
        meta = f"{ch.name}  ·  {resume_label}" if ch else resume_label
    base_url = data.play_url(cid, epg)
    url = data.play_url(cid, epg, start=pos) if pos > 0 else base_url
    fav_key = f"ch:{cid}"
    art = ch.logo if ch else str(e.get("thumb") or "")
    wide_art = prog_preview or (ch.banner if ch else "")
    banner = wide_art or art
    initials, plate, plate_hi, bg, tint = _palette(title)
    return Card(
        kind="programme", key=f"{cid}|{epg}", fav_key=fav_key,
        title=title, art=art, banner=banner, meta=meta, desc="",
        play_url=url, alt_url=base_url, cid=cid, epg=epg,
        start=start, stop=stop, resume_pos=pos,
        bar=bar, pbar=pbar, fav=fav_key in favs, catchup=True, playable=bool(url), dim=not bool(url),
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now=meta, nowline="", next="", nextline="", resume_label=resume_label, small=len(title) > 22,
        art_mode="logo", wide_art=wide_art,
    )


def continue_cards(resume_doc, catalog, now, favs=(), recall_prog=None, recall_title=None) -> list:
    """Build item-level Continue cards with SweetStore hydration, catchup expiry, and generic-channel dedup."""
    items = (resume_doc or {}).get("items") or {}
    ch_by_id = {ch.cid: ch for ch in catalog.channels} if catalog else {}
    entries = []
    for key, e in items.items():
        if not isinstance(e, dict) or not str(key).startswith("sw:"):
            continue
        if e.get("done"):
            continue
        pos = int(e.get("pos") or 0)
        total = int(e.get("total") or 0)
        if pos < 5 or total <= 0:
            continue
        at = int(e.get("at") or 0)
        entries.append((at, str(key), e))
    entries.sort(key=lambda x: -x[0])
    out = []
    seen_generic = set()
    for _, key, e in entries:
        pos = int(e.get("pos") or 0)
        total = int(e.get("total") or 1)
        frac = min(1.0, pos / total)
        bar = _bar_from_fraction(frac)
        pbar = _bar_from_fraction(frac, wide=True)
        resume_label = words.tr("Continue from {time}").format(time=fmt_mmss(pos))
        if key.startswith("sw:vod:"):
            out.append(_continue_vod_card(e, pos, bar, pbar, resume_label, favs, recall_title))
        else:
            ch = ch_by_id.get(str(e.get("cid") or ""))
            card = _continue_epg_card(e, ch, now, pos, bar, pbar, resume_label, favs, recall_prog, seen_generic)
            if card is not None:
                out.append(card)
    return out


def favourites_cards(favs_doc, catalog, cat_names, now, resume_doc=None) -> list:
    items = (favs_doc or {}).get("items") or {}
    fav_set = set(items.keys())
    ch_by_id = {ch.cid: ch for ch in catalog.channels} if catalog else {}
    entries = sorted(((int(e.get("at") or 0), k, e) for k, e in items.items() if isinstance(e, dict)),
                     key=lambda x: -x[0])
    out = []
    for _, key, e in entries:
        if key.startswith("ch:"):
            cid = key[3:]
            ch = ch_by_id.get(cid)
            if ch:
                out.append(channel_card(ch, cat_names, now, resume_doc, fav_set))
                continue
            title = str(e.get("title") or f"Channel {cid}")
            art = str(e.get("thumb") or "")
            initials, plate, plate_hi, bg, tint = _palette(title)
            out.append(Card(
                kind="channel", key=cid, fav_key=key, title=title, art=art, banner=art,
                meta=words.tr("TV Channels"), desc="", play_url=data.play_url(cid), alt_url="",
                cid=cid, epg="", start=0, stop=0, resume_pos=0, bar="", pbar="", fav=True,
                catchup=False, playable=True, dim=False, num="",
                initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
                now="", nowline="", next="", nextline="", resume_label="", small=len(title) > 22,
                art_mode="logo",
            ))
        elif key.startswith("show:"):
            show_id = key[5:]
            title = str(e.get("title") or show_id)
            art = str(e.get("thumb") or "")
            initials, plate, plate_hi, bg, tint = _palette(title)
            kind = "show_vod" if show_id.startswith("vod:") else ("show_epg" if show_id.startswith("epg:") else "show_tv")
            out.append(Card(
                kind=kind, key=show_id, fav_key=key, title=title, art=art, banner=art,
                meta=words.tr("Shows"), desc="", play_url="", alt_url="",
                cid="", epg="", start=0, stop=0, resume_pos=0, bar="", pbar="", fav=True,
                catchup=False, playable=True, dim=False, num="",
                initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
                now="", nowline="", next="", nextline="", resume_label="", small=len(title) > 22,
            ))
        elif key.startswith("vod:"):
            mid = key[4:]
            title = str(e.get("title") or f"VOD {mid}")
            art = str(e.get("thumb") or "")
            pos, frac = _vod_progress(resume_doc, mid)
            url = f"plugin://plugin.video.sweettv/playvod/{mid}|null|0"
            initials, plate, plate_hi, bg, tint = _palette(title)
            out.append(Card(
                kind="movie", key=mid, fav_key=key, title=title, art=art, banner=art,
                meta=words.tr("Movies"), desc="", play_url=url, alt_url=url if pos else "",
                cid="", epg="", start=0, stop=0, resume_pos=pos,
                bar=_bar_from_fraction(frac), pbar=_bar_from_fraction(frac, wide=True),
                fav=True, catchup=False, playable=True, dim=False, num="",
                initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
                now="", nowline="", next="", nextline="",
                resume_label=words.tr("Continue from {time}").format(time=fmt_mmss(pos)) if pos else "",
                small=len(title) > 22,
            ))
    return out


def filter_channels(channels, filter_key) -> list:
    if filter_key == "live":
        return [ch for ch in channels if not ch.fast]
    if filter_key == "fast":
        return [ch for ch in channels if ch.fast]
    if isinstance(filter_key, str) and filter_key.startswith("c:"):
        cid = filter_key[2:]
        return [ch for ch in channels if cid in ch.cats]
    return list(channels)


def search_chips() -> list:
    return [
        ("new", words.tr("New search")),
        ("all", words.tr("All items")),
        ("shows", words.tr("Shows and series")),
        ("movies", words.tr("Movies")),
        ("channels", words.tr("TV Channels")),
    ]


def filter_search(cards, filter_key) -> list:
    if filter_key == "shows":
        return [c for c in cards if c.kind in ("show_tv", "show_vod", "show_epg", "series")]
    if filter_key == "movies":
        return [c for c in cards if c.kind == "movie"]
    if filter_key == "channels":
        return [c for c in cards if c.kind == "channel"]
    return list(cards)


def show_chips() -> list:
    return [("all", words.tr("All items")), ("special", "SWEET.TV Special"), ("tv", words.tr("Shows"))]


def filter_shows(rows, filter_key) -> list:
    if filter_key == "special":
        return [r for r in rows if r.get("special") is True]
    if filter_key == "tv":
        return [r for r in rows if not r.get("special")]
    return list(rows)


def channel_chips(categories) -> list:
    chips = [("all", words.tr("All items")), ("live", words.tr("Live TV")), ("fast", words.tr("24/7"))]
    for key, name in (categories or ())[:5]:
        chips.append((key, name))
    return chips[:8]


UMBRELLA_GENRE_IDS = frozenset((1, 3, 57, 61))


def valid_sort_modes(sort_modes) -> list:
    modes = [
        {"id": m.get("id"), "name": str(m.get("name") or "").strip()}
        for m in (sort_modes or ())
        if isinstance(m, dict) and str(m.get("name") or "").strip()
    ]
    return modes or list(SORT_MODES_DEFAULT)


def catalog_chips(genres, sort_modes, sort_idx) -> list:
    modes = valid_sort_modes(sort_modes)
    mode = modes[sort_idx % len(modes)]
    chips = [("all", words.tr("All items")), ("sort", words.tr(mode["name"]))]
    for g in (genres or ()):
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        try:
            gid_num = int(gid) if not isinstance(gid, bool) and gid is not None else None
        except (TypeError, ValueError):
            gid_num = None
        name = str(g.get("name") or "").strip()
        if gid_num and gid_num not in UMBRELLA_GENRE_IDS and name:
            chips.append((f"g:{gid_num}", name))
            if len(chips) >= 8:
                break
    return chips[:8]


def day_tabs(archive_days, future_days, now) -> list:
    today = date.fromtimestamp(int(now))
    tabs = []
    for offset in range(-max(0, int(archive_days or 0)), max(0, int(future_days or 0)) + 1):
        d = today + timedelta(days=offset)
        noon_ts = int(now) + offset * 86400
        if offset == -1:
            label = words.tr("Yesterday")
        elif offset == 0:
            label = words.tr("Today")
        elif offset == 1:
            label = words.tr("Tomorrow")
        else:
            label = f"{words.tr(_WEEKDAYS[d.weekday()])} {d.strftime('%d.%m')}"
        tabs.append((noon_ts, label))
    return tabs or [(int(now), words.tr("Today"))]


def detail_meta_and_desc(detail: dict, fallback_card: Optional[Card] = None) -> Tuple[str, str]:
    """Build rich hero_meta and non-blank hero_desc from a vod_detail/show_detail answer."""
    parts = []
    year = int(detail.get("year") or 0)
    if year:
        parts.append(str(year))
    imdb = float(detail.get("imdb") or 0.0)
    if imdb > 0:
        parts.append(f"IMDb {imdb:.1f}")
    dur = int(detail.get("duration") or 0)
    if dur >= 60:
        parts.append(words.tr("{n} min").format(n=dur // 60))
    age = str(detail.get("age_rating") or "").strip()
    if age:
        parts.append(age)
    genres = [str(g).strip() for g in (detail.get("genre_names") or ()) if str(g).strip()]
    if genres:
        parts.append(", ".join(genres[:3]))
    countries = [str(c).strip() for c in (detail.get("countries") or ()) if str(c).strip()]
    if countries:
        parts.append(", ".join(countries[:2]))
    meta = "  ·  ".join(parts) if parts else (fallback_card.meta if fallback_card else "")
    desc = str(detail.get("description") or "").strip()
    if not desc:
        desc = (fallback_card.desc if fallback_card else "") or meta
    return meta, desc


def hero_info(card: Optional[Card]) -> dict:
    if card is None:
        return {
            "hero_title": "", "hero_meta": "", "hero_desc": "",
            "hero_play": words.tr("Watch"), "hero_alt": "", "hero_guide": "",
            "hero_fav": words.tr("Add to favourites"),
            "has_play": "", "has_alt": "", "has_guide": "", "has_fav": "",
            "hero_pbar": "", "hero_sub": "", "hero_initials": "", "hero_is_logo": "",
        }
    is_show = card.kind in ("show_vod", "show_epg", "show_tv", "series")
    if is_show:
        play_label = words.tr("Seasons and episodes")
        alt_label = ""
        guide_label = ""
    else:
        play_label = card.resume_label if card.resume_label else words.tr("Watch")
        alt_label = words.tr("From start (0:00)") if card.alt_url else ""
        guide_label = words.tr("Programme guide") if card.kind == "channel" else ""
    return {
        "hero_title": card.title,
        "hero_meta": card.meta,
        "hero_desc": card.desc,
        "hero_play": play_label,
        "hero_alt": alt_label,
        "hero_guide": guide_label,
        "hero_fav": words.tr("In favourites") if card.fav else words.tr("Add to favourites"),
        "has_play": "1" if (card.playable or is_show) else "",
        "has_alt": "1" if alt_label else "",
        "has_guide": "1" if guide_label else "",
        "has_fav": "1" if card.fav_key else "",
        "hero_pbar": card.pbar or "",
        "hero_sub": card.nextline or card.resume_label or "",
        "hero_initials": card.initials or "",
        "hero_is_logo": "1" if (card.art_mode == "logo" and not card.wide_art) else "",
    }


def skeleton_cards(count=5) -> list:
    return [
        Card(
            kind="skeleton", key=f"skel:{i}", fav_key="", title="",
            art="", banner="", meta="", desc="", play_url="", alt_url="",
            cid="", epg="", start=0, stop=0, resume_pos=0, bar="", pbar="",
            fav=False, catchup=False, playable=False, dim=False, num="",
            initials="", plate="", plate_hi="", bg="", tint="", now="",
            nowline="", next="", nextline="", resume_label="", small=False,
        )
        for i in range(count)
    ]


def filter_section_search(cards, section) -> list:
    if section == "movies":
        return [c for c in cards if c.kind == "movie"]
    if section == "series":
        return [c for c in cards if c.kind == "series"]
    if section == "shows":
        return [c for c in cards if c.kind in ("show_tv", "show_epg", "show_vod", "programme")]
    if section == "channels":
        return [c for c in cards if c.kind in ("channel", "programme")]
    return list(cards)


def filter_local_cards(cards, query) -> list:
    q = (query or "").strip().lower()
    if not q:
        return list(cards)
    out = []
    for c in cards:
        hay = " ".join((c.title, c.meta, c.desc, c.now, c.next)).lower()
        if q in hay:
            out.append(c)
    return out
