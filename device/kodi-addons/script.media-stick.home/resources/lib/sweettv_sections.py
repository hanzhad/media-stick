"""SWEET.TV app: the three sections of the TV screen, Channels, Shows and series, and Films. Ready data in, rows out; nothing
here touches Kodi.

SWEET.TV's own categories are the genres of the channels (18 of them), so the screen opens on a choice of three sections:
the channels (the existing screen, the genres are its menu), the shows and series, and the films. The shows and the films are
not in the channel list as such, only the programme guide of each channel is; the phone page already makes them from it with
mediastick_sweetsections, and this module asks that same code (and mediastick_sweetlive's `slim` and `archive_ok`, the guide's
rule for what can be played from the archive), so the two screens cannot disagree about what a show or a film is.

A Library holds the index of the list for as long as the person is in the shows or the films, and is let go of soon after
(the list is 5 MB of JSON for 200 channels; the index keeps the slimmed rows of it). The rows are made lazily, on the first
look, and capped: a Pi 3B+ keeps a few hundred of them, not thousands.

  home_entries(channels, counts)             the three cards of the first screen
  Library.load(key, read)                    build the index from `read()` (the whole list) unless `key` is the one it has
  Library.shows(now), .episodes(sid, now, logos), .films(now, logos)     (rows, how many there are before the cap)
  Row                                        what one line of the list says, and what OK on it plays
"""
import threading
from typing import NamedTuple, Optional, Tuple

from resources.lib import sweettv_data as data, sweettv_text as words, sweettv_view as view, textfit

CHANNELS, SHOWS, FILMS, EPISODES = "channels", "shows", "films", "episodes"   # the three sections, and the episodes of one show
ORDER = (CHANNELS, SHOWS, FILMS)
NAMES = {CHANNELS: "Channels", SHOWS: "Shows and series", FILMS: "Films"}          # msgids
BLURBS = {CHANNELS: "Live TV and the archive", SHOWS: "Shows and series you can watch from the archive",
          FILMS: "Films you can watch from the archive"}
COUNTS = {CHANNELS: "Channels: {n}", SHOWS: "Shows: {n}", FILMS: "Films: {n}"}
TINTS = {CHANNELS: "FF3F7FBF", SHOWS: "FF8E5CC4", FILMS: "FFC4623B"}              # blue, violet, orange: apart from each other
MAX_SHOWS, MAX_FILMS, MAX_EPISODES = 300, 300, 200
TITLE_PX, SUB_PX, HEADING_PX = 740, 740, 1060     # room in the skin: a line's title (28 px high), its second line (22), the list's title (60)


class Entry(NamedTuple):
    """A card of the first screen."""
    key: str
    title: str
    desc: str
    count: str                  # "" until it is known (the shows and films are counted when their index is built)
    plate: str
    plate_hi: str


class Row(NamedTuple):
    """A line of the list of shows, of the episodes of a show, or of films. OK on a show opens it, on a programme plays it
    (when `playable`) from its beginning in the archive."""
    key: str                    # a show's id ("" for a programme)
    title: str
    sub: str                    # the second line: how many episodes / season, time and channel
    side: str                   # the right-hand note: how many airings, "Soon", "Not in the archive"
    icon: str                   # the channel's picture ("" when there is none)
    mark: str                   # what the picture's badge is made from when there is no picture
    playable: bool = True
    future: bool = False        # not on air yet (a row that is not playable and is not this is just not in the archive)
    cid: str = ""
    epg: str = ""
    start: int = 0
    stop: int = 0
    name: str = ""              # what the archived programme is called when it is played


def home_entries(channels, counts) -> list:
    """The three cards: name, what is behind it, how many. `counts` is (shows, films), or None while they are not counted."""
    shows, films = counts if counts else (None, None)
    numbers = {CHANNELS: channels, SHOWS: shows, FILMS: films}
    out = []
    for key in ORDER:
        n = numbers[key]
        colours = view.shades(TINTS[key])
        out.append(Entry(key, words.tr(NAMES[key]), words.tr(BLURBS[key]), words.tr(COUNTS[key]).format(n=n) if n is not None else "",
                         colours["plate"], colours["plate_hi"]))
    return out


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


def _title(text) -> str:
    return fit(text, TITLE_PX, 28)


def _sub(text) -> str:
    return fit(text, SUB_PX, 22)


def _when(ts, now) -> str:
    return f"{view.day_prefix(ts, now)}{data.hhmm(ts)}"


def _line(*parts) -> str:
    return "  ·  ".join(p for p in parts if p)


def episode_title(episode) -> str:
    """"Episode 7  ·  Name"; the number or the name alone; "Episode" when it says neither."""
    number = words.tr("Episode {n}").format(n=episode["episode"]) if episode["episode"] else ""
    return _line(number, _text(episode["title"])) or words.tr("Episode")


def show_row(show) -> Row:
    title = _text(show["title"]) or str(show["id"])
    return Row(str(show["id"]), _title(title), words.tr("Episodes: {n}").format(n=show["episodes"]), "", data.logo_of(show["icon"]), title)


def episode_row(episode, show_title, icon, now) -> Row:
    playable = bool(episode["available"])
    future = not playable and episode["start"] > now
    season = words.tr("Season {n}").format(n=episode["season"]) if episode["season"] else ""
    title = episode_title(episode)
    channel = _text(episode["channel"], 80)
    side = "" if playable else words.tr("Soon" if future else "Not in the archive")
    return Row("", _title(title), _sub(_line(season, _when(episode["start"], now), channel)), side, icon, channel or show_title,
               playable, future, str(episode["cid"]), str(episode["epg"]), episode["start"], episode["stop"], _line(show_title, title))


def film_row(film, icon, now) -> Row:
    channel = _text(film["channel"], 80)
    title = _text(film["title"]) or str(film["epg"])
    airings = film["airings"]
    return Row("", _title(title), _sub(_line(channel, words.tr("{n} min").format(n=film["minutes"]), _when(film["start"], now))),
               words.tr("Airings: {n}").format(n=airings) if airings > 1 else "", icon, channel or title, True, False,
               str(film["cid"]), str(film["epg"]), film["start"], film["stop"], title)


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
        (the first screen asks on the UI thread). None otherwise."""
        with self._lock:
            shows, films = self._memo.get(SHOWS), self._memo.get(FILMS)
            if self.index is None or self._minute != int(now) // 60 or shows is None or films is None:
                return None
            return len(shows), len(films)

    def shows(self, now):
        """(rows, how many there are) of the shows with an episode to watch, by title; None without an index."""
        found = self._found(SHOWS, now, lambda s, i, ok: s.shows(i, ok))
        return None if found is None else ([show_row(s) for s in found[:MAX_SHOWS]], len(found))

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
