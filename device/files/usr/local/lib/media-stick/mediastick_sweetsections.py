"""SWEET.TV: the sections of the phone page, «Каналы», «Шоу и сериалы», «Фильмы», made from the channel list the add-on
already keeps (channelList.json). Pure, standard library only; nothing happens on import.

SWEET.TV has no catalogue in that list, only the programme guide of each channel (about ten past programmes, the one on now
and up to a hundred to come). A show is what the guide says is one, a film is what looks like one:

  show   a programme with a tv_show_id, grouped by it; one without, but with "Episode 7" / "Season 2 Episode 7" in its title,
         grouped by the title with that cut off ("Star Academy - Episode 2" is a programme of "Star Academy")
  film   a programme with neither, 75 minutes or longer, on a channel in category 4 (the "Film" category of the list)
  genre  the list's own categories, as a filter inside «Каналы» (the phone page already has them as c:<id>)

The sections list what can be played from the archive now; a show's own page also lists the episodes still to come
(information only). Playing is POST /api/sweettv/play {cid, epg}: the archive path of mediastick_sweetlive.

  split_title(text)                -> (show, season, episode, subtitle)
  build(raw)                       -> the index of a channel list (slimmed or whole), made once per list
  genres(raw), shows(idx, ok), show(idx, sid, ok), films(idx, ok)    what the routes answer; `ok(record)` says whether a
                                   programme can be played now (the caller's archive rule, the same as the guide's)
"""
import hashlib
import re
from collections import Counter

FILM_CATEGORY = 4          # "Film" in the list's categories
FILM_MINUTES = 75
HIDDEN_CATEGORY = 1000     # the list's "all"; the app and the page have their own
SHOW_ID_RE = re.compile(r"[0-9]{1,12}|t[0-9a-f]{10}")

_EPISODE = re.compile(r"(?<!\w)(?:(?:Season|Сезон)\s+(\d{1,4})\s+)?(?:Episode|Епізод|Эпизод|Серія|Серия)\s+(\d{1,5})(?!\d)",
                      re.IGNORECASE)
_SEASON = re.compile(r"(?<!\w)(?:Season|Сезон)\s+(\d{1,4})(?!\d)", re.IGNORECASE)
_EDGE = " -–—:,"


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _seconds(value):
    n = _int(value)
    return None if n is None else n // 1000 if n > 10 ** 11 else n


def split_title(text):
    """A programme's title -> (show, season, episode, subtitle). "Show Season 2 Episode 7 - Name" is ("Show", 2, 7, "Name");
    "Show - Episode 7" ("Show", 0, 7, ""); a title with no such marker is (title, 0, 0, ""). 0 means "not said"."""
    text = " ".join(str(text or "").split())
    season = episode = 0
    found = _EPISODE.search(text)
    if found:
        season, episode = int(found.group(1) or 0), int(found.group(2))
    else:
        found = _SEASON.search(text)
        if found:
            season = int(found.group(1))
    if not found:
        return text, 0, 0, ""
    show, subtitle = text[:found.start()].strip(_EDGE), text[found.end():].strip(_EDGE)
    return (show, season, episode, subtitle) if show else (text, season, episode, subtitle)


def _show_id(tv_show_id, show):
    tid = _int(tv_show_id)
    return str(tid) if tid and tid > 0 else "t" + hashlib.sha1(show.casefold().encode("utf-8")).hexdigest()[:10]


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def build(raw):
    """The index of a channel list: {"channels": n, "shows": {id: {"names": Counter, "records": [...]}}, "films": [...],
    "categories": [(id, name)], "used": {category id: channels}}. A record is {cid, channel, epg, text, title, season,
    episode, start, stop, minutes, icon, channel_ref, programme_ref}; the two refs are the list's own dicts, for the caller's
    archive rule. Rows that are not what they should be are skipped."""
    shows, films, used, count = {}, [], Counter(), 0
    for channel in _rows(raw.get("list") if isinstance(raw, dict) else None):
        cid = _int(channel.get("id"))
        if cid is None or cid <= 0 or channel.get("available") is False:
            continue
        count += 1
        cats = [c for c in (channel.get("category") if isinstance(channel.get("category"), list) else ()) if _int(c) is not None]
        used.update(set(cats))
        for p in _rows(channel.get("epg")):
            start, stop, epg = _seconds(p.get("time_start")), _seconds(p.get("time_stop")), _int(p.get("id"))
            if start is None or stop is None or stop <= start or not epg or epg <= 0:
                continue
            text = " ".join(str(p.get("text") or "").split())[:200]
            if not text:
                continue
            show, season, episode, subtitle = split_title(text)
            season = _int(p.get("season_number")) or season
            episode = _int(p.get("episode_number")) or episode
            tid = _int(p.get("tv_show_id"))
            record = {"cid": str(cid), "channel": str(channel.get("name") or "")[:80], "epg": str(epg), "text": text,
                      "title": subtitle or ("" if season or episode else text), "season": season, "episode": episode,
                      "start": start, "stop": stop, "minutes": (stop - start) // 60,
                      "icon": str(channel.get("icon_v2_url") or channel.get("icon_url") or ""),
                      "channel_ref": channel, "programme_ref": p}
            if (tid and tid > 0) or season or episode:
                entry = shows.setdefault(_show_id(tid, show), {"names": Counter(), "records": []})
                entry["names"][show] += 1
                entry["records"].append(record)
            elif FILM_CATEGORY in cats and record["minutes"] >= FILM_MINUTES:
                films.append(record)
    categories = []
    for item in _rows(raw.get("categories") if isinstance(raw, dict) else None):
        cat, name = _int(item.get("id")), " ".join(str(item.get("caption") or item.get("name") or "").split())[:40]
        if cat is not None and name:
            categories.append((cat, name))
    return {"channels": count, "shows": shows, "films": films, "categories": categories, "used": used}


def genres(index):
    """The categories that have channels, in the list's order, without its own "all": [{id: "c:<n>", name, channels}]. The id is
    the key the phone page already filters its channels by."""
    return [{"id": "c:%d" % cat, "name": name, "channels": index["used"][cat]}
            for cat, name in index["categories"] if cat != HIDDEN_CATEGORY and index["used"].get(cat)]


def _title_of(entry):
    return entry["names"].most_common(1)[0][0]


def _icon(records):
    return next((r["icon"] for r in sorted(records, key=lambda r: -r["start"]) if r["icon"]), "")


def _playable_first(records, ok):
    """The records that can be played now, the newest first."""
    return sorted((r for r in records if ok(r)), key=lambda r: -r["start"])


def shows(index, ok):
    """[{id, title, episodes, icon, latest}] of the shows that have something to play now, by title; `episodes` is how many
    different ones, `latest` the newest of them as show() gives an episode (the TV's card says its channel and name)."""
    out = []
    for sid, entry in index["shows"].items():
        playable = _unique(_playable_first(entry["records"], ok))
        if playable:
            out.append({"id": sid, "title": _title_of(entry), "episodes": len(playable), "icon": _icon(playable),
                        "latest": _episode(playable[0], ok)})
    return sorted(out, key=lambda e: (e["title"].casefold(), e["id"]))


def _unique(records):
    """One record per episode: the same season, episode and title is the same episode, whatever channel repeats it; the first one
    given (the newest, when they come newest first) stays. A record that says nothing of what it is stays as it is."""
    seen, out = set(), []
    for r in records:
        key = (r["season"], r["episode"], r["text"].casefold()) if r["season"] or r["episode"] else (r["cid"], r["epg"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _episode(r, ok):
    return {"cid": r["cid"], "epg": r["epg"], "title": r["title"], "season": r["season"], "episode": r["episode"],
            "start": r["start"], "stop": r["stop"], "available": bool(ok(r)), "channel": r["channel"]}


def show(index, sid, ok):
    """{title, episodes: [...]} of one show: every episode in the list, by season and episode (the ones with no number by time),
    playable now or still to come (available false); None when there is no such show."""
    entry = index["shows"].get(sid) if isinstance(sid, str) and SHOW_ID_RE.fullmatch(sid) else None
    if entry is None:
        return None
    ordered = sorted(entry["records"], key=lambda r: (not ok(r), -r["start"]))      # a playable repeat wins over one to come
    unique = sorted(_unique(ordered), key=lambda r: (r["season"], r["episode"], r["start"]))
    return {"title": _title_of(entry), "icon": _icon(entry["records"]), "episodes": [_episode(r, ok) for r in unique]}


def films(index, ok):
    """[{cid, epg, title, start, stop, minutes, available, airings}] of the films that can be played now, by title; one film on
    several channels or at several times is one item (its newest playable airing) with `airings` how many there are."""
    groups = {}
    for r in _playable_first(index["films"], ok):
        groups.setdefault(r["text"].casefold(), []).append(r)
    out = [{"cid": g[0]["cid"], "epg": g[0]["epg"], "title": g[0]["text"], "start": g[0]["start"], "stop": g[0]["stop"],
            "minutes": g[0]["minutes"], "available": True, "airings": len(g), "channel": g[0]["channel"]} for g in groups.values()]
    return sorted(out, key=lambda e: (e["title"].casefold(), e["start"]))
