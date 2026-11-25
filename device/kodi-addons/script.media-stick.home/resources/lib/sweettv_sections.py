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
        art=ch.logo, banner=ch.logo, meta=meta, desc=desc,
        play_url=data.play_url(ch.cid), alt_url=alt_url,
        cid=ch.cid, epg=current.epg_id if current else "",
        start=current.start if current else 0, stop=current.stop if current else 0,
        resume_pos=0, bar=bar, pbar=pbar, fav=fav_key in favs,
        catchup=ch.catchup, playable=True, dim=False,
        num=str(ch.number) if ch.number else "",
        initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now=now_text, nowline=nowline, next=next_text, nextline=nextline,
        resume_label="", small=len(ch.name) > 22,
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
    return Card(
        kind=kind, key=show_id, fav_key=fav_key, title=title,
        art=str(item.get("poster") or ""), banner=str(item.get("banner") or item.get("poster") or ""),
        meta="  ·  ".join(meta_parts), desc="",
        play_url="", alt_url="", cid="", epg="", start=0, stop=0,
        resume_pos=0, bar="", pbar="", fav=fav_key in favs,
        catchup=False, playable=True, dim=False,
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now="", nowline="", next="", nextline="", resume_label="", small=len(title) > 22,
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
    if kind == "channel" and cid:
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
    meta_parts = [p for p in (str(row.get("channel_name") or ""), str(row.get("when") or ""), subtitle) if p]
    initials, plate, plate_hi, bg, tint = _palette(title)
    return Card(
        kind=kind or "movie", key=str(row.get("id") or cid or title), fav_key=fav_key, title=title,
        art=art, banner=art, meta="  ·  ".join(meta_parts), desc="",
        play_url=url if playable else "", alt_url=url if (playable and pos) else "",
        cid=cid, epg=epg, start=start, stop=stop, resume_pos=pos,
        bar=_bar_from_fraction(frac), pbar=_bar_from_fraction(frac, wide=True),
        fav=bool(fav_key and fav_key in favs), catchup=bool(row.get("playable_in_archive")),
        playable=playable and bool(url), dim=not (playable and bool(url)),
        num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
        now="", nowline="", next="", nextline="",
        resume_label=words.tr("Continue from {time}").format(time=fmt_mmss(pos)) if pos else "",
        small=len(title) > 22,
    )


def continue_cards(resume_doc, catalog, now, favs=()) -> list:
    """Build item-level Continue cards from mediastick_resume without per-channel collapse."""
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
    for _, key, e in entries:
        pos = int(e.get("pos") or 0)
        total = int(e.get("total") or 1)
        frac = min(1.0, pos / total)
        bar = _bar_from_fraction(frac)
        pbar = _bar_from_fraction(frac, wide=True)
        resume_label = words.tr("Continue from {time}").format(time=fmt_mmss(pos))
        if key.startswith("sw:vod:"):
            mid = str(e.get("movie_id") or "")
            eid = str(e.get("episode_id") or "")
            title = str(e.get("title") or f"VOD {mid}")
            base_url = f"plugin://plugin.video.sweettv/playvod/{mid}|{eid or 'null'}|0"
            url = f"{base_url}?start={pos}" if pos > 0 else base_url
            fav_key = f"vod:{mid}"
            art = str(e.get("thumb") or "")
            initials, plate, plate_hi, bg, tint = _palette(title)
            out.append(Card(
                kind="movie" if not eid else "episode", key=f"{mid}|{eid}", fav_key=fav_key,
                title=title, art=art, banner=art, meta=resume_label, desc="",
                play_url=url, alt_url=base_url, cid="", epg="", start=0, stop=0, resume_pos=pos,
                bar=bar, pbar=pbar, fav=fav_key in favs, catchup=False, playable=True, dim=False,
                num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
                now="", nowline="", next="", nextline="", resume_label=resume_label, small=len(title) > 22,
            ))
        else:
            cid = str(e.get("cid") or "")
            epg = str(e.get("epg") or "")
            ch = ch_by_id.get(cid)
            title = str(e.get("title") or (ch.name if ch else f"Channel {cid}"))
            base_url = data.play_url(cid, epg)
            url = data.play_url(cid, epg, start=pos) if pos > 0 else base_url
            fav_key = f"ch:{cid}"
            art = ch.logo if ch else str(e.get("thumb") or "")
            initials, plate, plate_hi, bg, tint = _palette(title)
            meta = f"{ch.name}  ·  {resume_label}" if ch else resume_label
            out.append(Card(
                kind="programme", key=f"{cid}|{epg}", fav_key=fav_key,
                title=title, art=art, banner=art, meta=meta, desc="",
                play_url=url, alt_url=base_url, cid=cid, epg=epg,
                start=int(e.get("start") or 0), stop=int(e.get("stop") or 0), resume_pos=pos,
                bar=bar, pbar=pbar, fav=fav_key in favs, catchup=True, playable=bool(url), dim=not bool(url),
                num="", initials=initials, plate=plate, plate_hi=plate_hi, bg=bg, tint=tint,
                now="", nowline="", next="", nextline="", resume_label=resume_label, small=len(title) > 22,
            ))
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


def catalog_chips(genres, sort_modes, sort_idx) -> list:
    modes = sort_modes or SORT_MODES_DEFAULT
    mode = modes[sort_idx % len(modes)]
    chips = [("all", words.tr("All items")), ("sort", words.tr(mode["name"]))]
    for g in (genres or ())[:6]:
        gid = g.get("id")
        name = g.get("name")
        if gid and name:
            chips.append((f"g:{gid}", str(name)))
    return chips[:8]


def day_tabs(archive_days, future_days, now) -> list:
    today = date.fromtimestamp(int(now))
    tabs = []
    for offset in range(-max(0, int(archive_days or 0)), max(0, int(future_days or 0)) + 1):
        d = today + timedelta(days=offset)
        noon_ts = int(now) + offset * 86400
        label = d.strftime("%a %d.%m")
        tabs.append((noon_ts, label))
    return tabs or [(int(now), today.strftime("%a %d.%m"))]


def hero_info(card: Optional[Card]) -> dict:
    if card is None:
        return {
            "hero_title": "", "hero_meta": "", "hero_desc": "",
            "hero_play": words.tr("Watch"), "hero_alt": "", "hero_guide": "",
            "hero_fav": words.tr("Add to favourites"),
            "has_play": "", "has_alt": "", "has_guide": "", "has_fav": "",
        }
    is_show = card.kind in ("show_vod", "show_epg", "show_tv", "series")
    if is_show:
        play_label = words.tr("Seasons and episodes")
        alt_label = ""
        guide_label = words.tr("Episodes")
    else:
        play_label = card.resume_label if card.resume_label else words.tr("Watch")
        alt_label = words.tr("From start") if card.alt_url else ""
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
    }
