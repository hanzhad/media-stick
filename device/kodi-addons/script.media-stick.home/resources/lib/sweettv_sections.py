"""SWEET.TV app: the shows and the films of the TV screen, and the episodes of a show. Ready data in, rows out; nothing
here touches Kodi.

SWEET.TV's own categories are the genres of the channels (18 of them), so the left menu has them as its first group, and
as its second the two things the channel list has no category for: the shows and series, and the films. They are not in the
channel list as such, only the programme guide of each channel is; the phone page already makes them from it with
mediastick_sweetsections, and this module asks that same code (and mediastick_sweetlive's `slim` and `archive_ok`, the guide's
rule for what can be played from the archive), so the two screens cannot disagree about what a show or a film is. The row
of cards along the bottom then shows a card per show, per film or, after OK on a show, per episode.

A Library holds the index of the list for as long as the person is in the shows or the films, and is let go of soon after
(the list is 5 MB of JSON for 200 channels; the index keeps the slimmed rows of it). The rows are made lazily, on the first
look, and capped: a Pi 3B+ keeps a few hundred of them, not thousands.

  Library.load(key, read)                    build the index from `read()` (the whole list) unless `key` is the one it has
  Library.shows(now), .episodes(sid, now, logos), .films(now, logos)     (rows, how many there are before the cap)
  Row                                        what one card says, and what OK on it plays
  card_texts(row)                            the Row's texts, each cut to the room the skin has for it
"""
import threading
from typing import NamedTuple, Optional, Tuple

from resources.lib import sweettv_data as data, sweettv_text as words, sweettv_view as view, textfit

CHANNELS, SHOWS, FILMS, EPISODES = "channels", data.SHOWS, data.FILMS, "episodes"   # what the row of cards holds
SECTIONS = (SHOWS, FILMS, EPISODES)              # all of it that is not channels
MAX_SHOWS, MAX_FILMS, MAX_EPISODES = 300, 300, 200
CAPTION_PX, TITLE_PX, META_PX, LINE_PX = 236, 740, 740, 740    # room in the skin: the caption of a card (25 px high), the title over the
                                                               # row (60, or 40 when it is long), its meta and amber lines (25), the big
                                                               # line under them (40)
TITLE_PX_FONT, SMALL_PX_FONT = 60, 40


class Row(NamedTuple):
    """A card of the shows, of the episodes of a show, or of the films. OK on a show opens it, on a programme plays it
    (when `playable`) from its beginning in the archive. The texts are whole: card_texts cuts them to the skin."""
    key: str                    # a show's id ("" for a programme)
    title: str                  # the show, the film or "S2 E7  ·  Name"; the card's caption and the title over the row
    sub: str                    # the line under the title: how many episodes and the channel, the length and the channel, ...
    side: str                   # the amber line: when the newest episode / the film is on, what keeps an episode from being watched
    icon: str                   # the channel's picture ("" when there is none)
    mark: str                   # what the picture's badge and the card's colours are made from when there is no picture
    playable: bool = True
    future: bool = False        # not on air yet (a row that is not playable and is not this is just not in the archive)
    cid: str = ""
    epg: str = ""
    start: int = 0
    stop: int = 0
    name: str = ""              # what the archived programme is called when it is played
    line: str = ""              # the big line: the newest episode of a show, how many times a film is on


# ---- rows ------------------------------------------------------------------------------------

def _text(value, limit=120) -> str:
    return data.clean_text(value, limit)


def fit(text, width, size) -> str:
    """`text` on one line of `width` px in a font `size` px high: cut with an ellipsis when it would not fit (the skin's
    labels would cut it anyway, not always where it looks right). What fits is returned as it is (the spaces round a middle dot
    stay: the wrapping would squeeze them)."""
    if textfit.text_px(text, size) <= width:
        return text
    return textfit.wrap_name(text, width, size, 1)[0]


def card_texts(row) -> dict:
    """What a card and the preview over the row say of `row`: the caption under the picture, the title, the line under it,
    the amber line and the big line, each cut to its room. A title that is too long for the big letters is set smaller
    (`small`, which the skin reads) before it is cut."""
    big = textfit.text_px(row.title, TITLE_PX_FONT) <= TITLE_PX
    return {"caption": fit(row.title, CAPTION_PX, 25), "title": row.title if big else fit(row.title, TITLE_PX, SMALL_PX_FONT),
            "small": "" if big else "1", "meta": fit(row.sub, META_PX, 25), "cap": fit(row.side, META_PX, 25),
            "line": fit(row.line, LINE_PX, 40)}


def _when(ts, now) -> str:
    return f"{view.day_prefix(ts, now)}{data.hhmm(ts)}"


def _span(start, stop, now) -> str:
    return f"{view.day_prefix(start, now)}{data.span(start, stop)}"


def _line(*parts) -> str:
    return "  ·  ".join(p for p in parts if p)


def episode_title(episode) -> str:
    """"S2 E7  ·  Name" ("С2 Э7" in Russian, "С2 Е7" in Ukrainian); the numbers or the name alone; "Episode" when it says neither."""
    number = " ".join(p for p in (words.tr("S{n}").format(n=episode["season"]) if episode["season"] else "",
                                  words.tr("E{n}").format(n=episode["episode"]) if episode["episode"] else "") if p)
    return _line(number, _text(episode["title"])) or words.tr("Episode")


def show_row(show, now) -> Row:
    """`show` is mediastick_sweetsections.shows' item: id, title, how many episodes, the picture, and the newest one."""
    title = _text(show["title"]) or str(show["id"])
    latest = show.get("latest")
    channel = _text(latest["channel"], 80) if latest else ""
    return Row(str(show["id"]), title, _line(words.tr("Episodes: {n}").format(n=show["episodes"]), channel),
               _line(words.tr("Latest episode"), _when(latest["start"], now)) if latest else "", data.logo_of(show["icon"]), title,
               line=episode_title(latest) if latest else "")


def episode_row(episode, show_title, icon, now) -> Row:
    playable = bool(episode["available"])
    future = not playable and episode["start"] > now
    season = words.tr("Season {n}").format(n=episode["season"]) if episode["season"] else ""
    title = episode_title(episode)
    channel = _text(episode["channel"], 80)
    note = "" if playable else words.tr("Soon" if future else "Not in the archive")
    return Row("", title, _line(show_title, season, channel), _line(_span(episode["start"], episode["stop"], now), note), icon,
               channel or show_title, playable, future, str(episode["cid"]), str(episode["epg"]), episode["start"], episode["stop"],
               _line(show_title, title))


def film_row(film, icon, now) -> Row:
    channel = _text(film["channel"], 80)
    title = _text(film["title"]) or str(film["epg"])
    airings = film["airings"]
    return Row("", title, _line(words.tr("{n} min").format(n=film["minutes"]), channel), _span(film["start"], film["stop"], now), icon,
               channel or title, True, False, str(film["cid"]), str(film["epg"]), film["start"], film["stop"], title,
               words.tr("Airings: {n}").format(n=airings) if airings > 1 else "")


def first_playable(rows) -> int:
    """Where the cursor starts in a list of episodes: the first one that can be watched."""
    return next((i for i, row in enumerate(rows) if row.playable), 0)


def capped(rows, limit) -> list:
    """`rows` cut to `limit`, in their order. What goes first is what cannot be played (the episodes still to come, the last
    of them first), so nothing that can be watched is lost to the cap."""
    if len(rows) <= limit:
        return list(rows)
    chosen = {i for i, row in enumerate(rows) if row.playable}
    chosen = set(sorted(chosen)[:limit])
    for i in range(len(rows)):
        if len(chosen) >= limit:
            break
        chosen.add(i)
    return [rows[i] for i in sorted(chosen)]


# ---- the index -------------------------------------------------------------------------------

def _libs() -> Tuple[Optional[object], Optional[object]]:
    """(mediastick_sweetsections, mediastick_sweetlive) of the device's library; None for one that is not there."""
    try:
        from resources.lib import store
        return store.sweetsections, store.sweetlive
    except Exception:
        return None, None


class Library:
    """The index of the channel list for the shows and the films: built once per version of the file, dropped by release()."""

    def __init__(self, libs=None):
        self._given = libs
        self._lock = threading.RLock()
        self.key = None
        self.index = None
        self._memo = {}
        self._minute = None

    def libs(self):
        return self._given if self._given is not None else _libs()

    def available(self) -> bool:
        return all(self.libs())

    @property
    def loaded(self) -> bool:
        return self.index is not None

    def release(self):
        with self._lock:
            self.key = self.index = self._minute = None
            self._memo = {}

    def load(self, key, read) -> bool:
        """The index of `read()` (the list as the plugin saved it; None when it cannot be read now), kept for `key`, the
        file's version. True when there is an index to ask (an older one is better than none)."""
        sections, live = self.libs()
        if sections is None or live is None:
            return False
        with self._lock:
            if self.index is not None and self.key == key:
                return True
            raw = read()
            if raw is None:
                return self.index is not None
            self.index, self.key, self._memo = sections.build(live.slim(raw)), key, {}
            return True

    def _asked(self, name, now, make):
        """`make()` once per version of the file and minute: the archive rule depends on the clock, so what it found is reused
        for a minute (going back from a show to the list must not work it out again). None without an index."""
        with self._lock:
            if self.index is None:
                return None
            if self._minute != int(now) // 60:
                self._memo, self._minute = {}, int(now) // 60
            if name not in self._memo:
                self._memo[name] = make()
            return self._memo[name]

    def _ok(self, now):
        live = self.libs()[1]
        return lambda record: live.archive_ok(record["channel_ref"], record["programme_ref"], now)

    def _found(self, name, now, ask):
        return self._asked(name, now, lambda: ask(self.libs()[0], self.index, self._ok(now)))

    def warm(self, now):
        """Work out the shows and the films (the slow part of the rows), so that counts() knows how many there are."""
        self._found(SHOWS, now, lambda s, i, ok: s.shows(i, ok))
        self._found(FILMS, now, lambda s, i, ok: s.films(i, ok))

    def counts(self, now) -> Optional[Tuple[int, int]]:
        """(shows, films) that can be watched now, when warm() has worked them out this minute; never works them out itself
        (the menu asks on the UI thread). None otherwise."""
        with self._lock:
            shows, films = self._memo.get(SHOWS), self._memo.get(FILMS)
            if self.index is None or self._minute != int(now) // 60 or shows is None or films is None:
                return None
            return len(shows), len(films)

    def shows(self, now):
        """(rows, how many there are) of the shows with an episode to watch, by title; None without an index."""
        found = self._found(SHOWS, now, lambda s, i, ok: s.shows(i, ok))
        return None if found is None else ([show_row(s, now) for s in found[:MAX_SHOWS]], len(found))

    def episodes(self, sid, now, logos):
        """(the show's title, rows, how many there are) of one show: every episode of the list by season and number, the ones
        that cannot be watched yet dimmed, each with the picture of its channel (`logos`: channel id -> picture). None without
        an index or without such a show."""
        found = self._found((EPISODES, sid), now, lambda s, i, ok: s.show(i, sid, ok))
        if found is None:
            return None
        title, fallback = _text(found["title"]) or str(sid), found["icon"]
        rows = [episode_row(e, title, data.logo_of(logos.get(str(e["cid"]), ""), fallback), now) for e in found["episodes"]]
        return title, capped(rows, MAX_EPISODES), len(rows)

    def films(self, now, logos):
        """(rows, how many there are) of the films that can be watched now, by title; `logos` maps a channel id to its picture."""
        found = self._found(FILMS, now, lambda s, i, ok: s.films(i, ok))
        if found is None:
            return None
        return [film_row(f, data.logo_of(logos.get(str(f["cid"]), "")), now) for f in found[:MAX_FILMS]], len(found)
