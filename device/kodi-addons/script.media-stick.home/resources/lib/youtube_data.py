"""YouTube app, the part that needs no Kodi: reading what the YouTube add-on lists, the sections, what the
window shows when there is nothing to show. Everything here takes ready data and returns data.

The add-on plugin.video.youtube (7.4.4) is asked with JSON-RPC Files.GetDirectory for a plugin:// path and
answers like any Kodi directory (see PROPERTIES for what is asked):

  result.files[]        file, filetype ("file" | "directory"), label, title, thumbnail, art{}, plot,
                        duration / runtime (seconds), studio[] / artist[] (the channel, when the add-on sets it)

A video is a file whose path is the add-on's /play/ route; a playlist, a channel and the "next page" entry are
directories. Anything else (the "Sign In" tile, actions) is not a card. Without a personal Google key (or signed
out) the add-on answers with an empty list or refuses the request ("Invalid params"): that is what NEEDKEY,
SIGNIN and UNAVAILABLE are about. Everything is optional here: a missing or odd field never raises, an unusable
entry is skipped.

What the add-on really sends (7.4.4, seen on a device): the label of a tile carries [B]..[/B]; a thumbnail is
"image://<url-encoded address>/"; a video has no duration (runtime 0) and artist ["Untitled"] or [] when the
channel is unknown (the add-on asks the Data API for channel names and has no key to do it with).

Read when present, never seen yet on a device (the card shows nothing for what is missing): playcount and resume
{position, total} (the red bar of a watched video), dateadded "YYYY-MM-DD[ HH:MM:SS]" (how long ago), and the
fields views, videos (the length of a playlist) and live (true for a live stream), which Kodi's own lists do not
have: the demo sends them so that the card can be seen with everything on it. What is drawn from them is in
youtube_cards.

The routes of the sections are those of the add-on's own main page: discover_routes() reads them off it by the
path tokens they contain, and they are asked for exactly as listed there (with their ?category_label= and with
or without a closing slash: a slash added or dropped is a different path, and the add-on refuses it). The table's
paths (see SECTIONS) are only the fallback, written the way the main page lists them.
"""
import calendar
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import NamedTuple, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

PLUGIN_ID = "plugin.video.youtube"
ROOT = f"plugin://{PLUGIN_ID}/"
SEARCH_ROUTE = ROOT + "kodion/search/query/?q={q}"
PATH_RE = re.compile(r"plugin://plugin\.video\.youtube/[^\s\"|\x00-\x1f\x7f]{0,1500}")
PROPERTIES = ["title", "thumbnail", "art", "plot", "duration", "runtime", "file", "studio", "artist", "playcount",
              "resume", "dateadded"]

VIDEO, FOLDER, MORE = "video", "folder", "more"                              # what a card is
DATA, SIGNIN, NEEDKEY, EMPTY, LOADING, ERROR, PROMPT, UNAVAILABLE = (
    "data", "signin", "needkey", "empty", "loading", "error", "prompt", "unavailable")    # what the window shows

SEARCH, FOLDER_KEY = "search", "folder"          # the Search section; the key of a playlist or channel opened from a card
MAX_QUERY = 80
MAX_ENTRIES = 200                                # per page: a page is a few dozen, this only bounds a runaway answer
MAX_SECONDS = 7 * 86400                          # a duration above this is a data error
CACHE_TTL, CACHE_SIZE = 300, 12                  # s a listing is shown again without asking; how many are kept
NEXT_PAGE_KEYS = {"page", "page_token"}
ART_KEYS = ("thumb", "poster", "landscape", "banner", "icon", "fanart")    # fanart last: it can be the add-on's own picture
NO_CHANNEL = {"untitled"}                        # what the add-on puts in artist/studio when it does not know the channel
NO_THUMB = "youtube-nothumb.png"                 # in the skin's media folder: the plate of a card with no picture
THUMB_URL = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"    # a video's picture, when the add-on sent none
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")      # a real video id; the demo's invented ones are not (no network there)
FIRST_YEAR, LAST_YEAR = 2005, 2100               # a date outside this is a data error
# What the skin's font has no glyph for (a square shows instead): arrows, maths, technical, shapes, symbols and
# dingbats (2190-2BFF, where the emoji of the BMP live), variation selectors, zero-width and direction marks, keycap,
# four CJK emoji, the lone halves of a surrogate pair and the specials (FFFD, FFFC). Everything past the BMP goes too
# (emoji, U+1F000-1FFFF), except the maths letters, which Unicode folds back to plain ones.
UNRENDERABLE = ((0x2190, 0x2BFF), (0xFE00, 0xFE0F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F),
                (0x20E3, 0x20E3), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
                (0xD800, 0xDFFF), (0xFFF0, 0xFFFF))
MATH_LETTERS = (0x1D400, 0x1D7FF)
INVALID_PARAMS = -32602                          # JSON-RPC: the add-on refused the path (the section is not served)
KEYS_PATH = "Accounts > YouTube > Keys"          # where the phone page keeps the key wizard
KEYS_HINT = "Phone: " + KEYS_PATH
STEP_TOTAL = 6                                   # the steps of the key wizard on the phone page
STEP_MAX_AGE = 30 * 60                           # s: the wizard's progress file older than this is a wizard left behind
KEY_SETTINGS = ("youtube.api.key", "youtube.api.id", "youtube.api.secret")    # the add-on's settings that hold the personal key


class Section(NamedTuple):
    key: str
    name: str
    route: str                   # the fallback path, used when the main page does not name the section
    tokens: Tuple[str, ...]      # path parts that mark the section's tile on the add-on's main page, best first
    needs_login: bool


# The paths are the ones the add-on's main page lists (7.4.4, seen on a device), each exactly as listed: a slash
# added or dropped makes the add-on answer "Invalid params". discover_routes() wins; these are the fallback.
# Watch later and History are the add-on's playlists WL and HL, found by that part of the path.
SECTIONS = (
    Section("rec", "Recommendations", ROOT + "special/recommendations/", ("recommendations",), True),
    Section("subs", "Subscriptions", ROOT + "special/my_subscriptions", ("my_subscriptions", "new_uploaded", "subscriptions"), True),
    Section("later", "Watch later", ROOT + "special/playlist/WL/", ("/playlist/wl", "watch_later"), True),
    Section("history", "History", ROOT + "special/playlist/HL/", ("/playlist/hl", "watch_history", "history"), True),
    Section("lists", "Playlists", ROOT + "channel/mine/playlists", ("playlists",), True),
    Section("trend", "Trending", ROOT + "special/popular_right_now", ("popular_right_now",), False),
    Section(SEARCH, "Search", "", (), False),
)
SECTION_KEYS = tuple(s.key for s in SECTIONS)
DEFAULT_SECTION = SECTIONS[0].key


class Entry(NamedTuple):
    kind: str
    path: str
    title: str
    channel: str
    seconds: int                 # 0: not known (or live)
    thumb: str
    plot: str
    views: int = 0               # 0: not known
    published: int = 0           # epoch seconds, 0: not known
    live: bool = False
    count: int = 0               # videos in a playlist, 0: not known
    progress: float = 0.0        # 0..1 of the video watched, 0: not watched or not known


class Listing(NamedTuple):
    entries: Tuple[Entry, ...]
    more: str                    # path of the next page, "" when this is the last
    error: str                   # "" when the add-on answered (an empty list is an answer)
    skipped: int = 0
    refused: bool = False        # the error is the add-on refusing this path ("Invalid params"), not a failure to answer


class View(NamedTuple):
    key: str
    title: str
    route: str                   # "" for Search before anything is typed
    needs_login: bool


class Message(NamedTuple):
    title: str
    text: str
    action: str                  # the button's label, "" for none


class RailEntry(NamedTuple):
    key: str
    name: str


NO_LISTING = Listing((), "", "")


# ---- reading values --------------------------------------------------------------------------

MARKUP = re.compile(r"\[/?(?:B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE|CR|COLOR(?:[ =][^\]]*)?)\]", re.IGNORECASE)


def _unmarked(tag) -> str:
    return " " if tag.group(0).upper() == "[CR]" else ""


def _glyph(char) -> str:
    """`char` when the skin's font draws it, else "" (see UNRENDERABLE)."""
    code = ord(char)
    if code > 0xFFFF:
        return unicodedata.normalize("NFKC", char) if MATH_LETTERS[0] <= code <= MATH_LETTERS[1] else ""
    return "" if any(low <= code <= high for low, high in UNRENDERABLE) else char


def clean_text(value, limit=200) -> str:
    """Text for a Kodi label: Kodi's own markup tags removed (the add-on puts [B] and [COLOR ...] in labels; a tag
    leaves nothing behind, [CR] a space), the symbols and emoji the font cannot draw removed (a square shows instead),
    one line with single spaces, no control characters, any other square bracket turned into a round one, cut to
    `limit`."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = "".join(map(_glyph, MARKUP.sub(_unmarked, str(value))))
    text = "".join(c if c.isprintable() else " " for c in text)
    return " ".join(text.replace("[", "(").replace("]", ")").split())[:limit]


def as_seconds(value) -> int:
    """Seconds from a number, a numeric string or "h:mm:ss"; 0 for anything else or out of range."""
    if isinstance(value, bool):
        return 0
    n = None
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        n = int(value) if math.isfinite(value) else None
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[0-9]{1,9}", text):
            n = int(text)
        elif re.fullmatch(r"[0-9]{1,3}(:[0-9]{1,2}){1,2}", text):
            n = 0
            for part in text.split(":"):
                n = n * 60 + int(part)
    return n if n is not None and 0 < n <= MAX_SECONDS else 0


def format_duration(seconds) -> str:
    """12:34, or 1:02:03 from an hour on; "" when not known."""
    seconds = as_seconds(seconds)
    if not seconds:
        return ""
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def picture(value) -> str:
    """A usable picture address: a web address, Kodi's own (special://, image://) or a local path. The add-on
    sends "image://<url-encoded address>/" for a thumbnail; Kodi loads that as it is. Kodi's stock icon names
    (image://DefaultVideo.png/) are no picture: the card shows its own plate instead of a blank tile."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("image://"):
            inner = unquote(text[len("image://"):]).strip("/")
            return "" if "://" not in inner and inner.lower().startswith("default") else text
        if text.startswith(("http://", "https://", "special://")) or text.startswith("/"):
            return text
    return ""


def thumb_url(path) -> str:
    """YouTube's own picture of the video a play route names (its video_id=...), "" when the path names none."""
    ids = parse_qs(urlsplit(path).query).get("video_id", [""])
    return THUMB_URL.format(id=ids[0]) if VIDEO_ID.fullmatch(ids[0]) else ""


def thumb_of(raw, path="") -> str:
    """The card's picture: art.thumb, then the plain thumbnail, then the other art, then the picture YouTube has of
    the video (from the play route's video_id), the add-on's own fanart last of all."""
    art = raw.get("art") if isinstance(raw.get("art"), dict) else {}
    for source in (art.get(ART_KEYS[0]), raw.get("thumbnail"), *(art.get(key) for key in ART_KEYS[1:-1]),
                   thumb_url(path), art.get(ART_KEYS[-1])):
        found = picture(source)
        if found:
            return found
    return ""


def as_count(value) -> int:
    """A count from a number or digits (with the separators people write); 0 for anything else."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, str):
        value = value.replace(",", "").replace(" ", "")
        value = int(value) if re.fullmatch(r"[0-9]{1,12}", value) else 0
    return value if isinstance(value, int) and 0 < value < 10 ** 12 else 0


def as_epoch(value) -> int:
    """Epoch seconds (UTC) from "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS" or the same with a T; 0 when it is none of those."""
    found = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?", value.strip()) if isinstance(value, str) else None
    if not found:
        return 0
    year, month, day, hour, minute, second = (int(part or 0) for part in found.groups())
    if not FIRST_YEAR <= year <= LAST_YEAR:
        return 0
    try:
        return calendar.timegm((year, month, day, hour, minute, second))
    except (ValueError, OverflowError):
        return 0


def watched_part(raw) -> float:
    """How much of the video was watched, 0..1: the resume point, else 1 for a video played to the end (playcount)."""
    resume = raw.get("resume") if isinstance(raw.get("resume"), dict) else {}
    position, total = as_seconds(resume.get("position")), as_seconds(resume.get("total"))
    if position and total:
        return min(1.0, position / total)
    return 1.0 if as_count(raw.get("playcount")) else 0.0


def name_of(*values) -> str:
    """The first real name among strings and lists of strings (studio and artist are lists). "Untitled" is what
    the add-on puts there when it does not know the channel: that is no name."""
    for value in values:
        for item in value if isinstance(value, list) else [value]:
            text = clean_text(item, 60)
            if text and text.casefold() not in NO_CHANNEL:
                return text
    return ""


def clean_query(value) -> str:
    return clean_text(value, MAX_QUERY)


# ---- a directory -----------------------------------------------------------------------------

def route_parts(path):
    """(path without the query, the query's keys) of a plugin:// address."""
    parts = urlsplit(path)
    return parts.path, set(parse_qs(parts.query))


def kind_of(raw, path) -> str:
    """VIDEO for the add-on's play route, MORE for the next-page entry, FOLDER for any other directory, "" for the rest."""
    route, keys = route_parts(path)
    if raw.get("filetype") == "directory":
        return MORE if keys & NEXT_PAGE_KEYS else FOLDER
    return VIDEO if "/play/" in route or route.endswith("/play") else ""


def parse_entry(raw) -> Optional[Entry]:
    if not isinstance(raw, dict) or not isinstance(raw.get("file"), str):
        return None
    path = raw["file"].strip()
    if not PATH_RE.fullmatch(path):
        return None
    kind = kind_of(raw, path)
    if not kind:
        return None
    video = kind == VIDEO
    seconds = as_seconds(raw.get("duration")) or as_seconds(raw.get("runtime"))
    return Entry(kind, path, clean_text(raw.get("title") or raw.get("label"), 120) or "Untitled",
                 name_of(raw.get("studio"), raw.get("artist")), seconds if video else 0,
                 thumb_of(raw, path if video else ""), clean_text(raw.get("plot"), 300),
                 as_count(raw.get("views")) if video else 0, as_epoch(raw.get("dateadded")) if video else 0,
                 video and raw.get("live") is True, 0 if video else as_count(raw.get("videos")),
                 watched_part(raw) if video else 0.0)


def is_refusal(problem, text) -> bool:
    """Whether a JSON-RPC error is "Invalid params": the add-on does not serve the path it was asked for."""
    code = problem.get("code") if isinstance(problem, dict) else None
    return code == INVALID_PARAMS or text.lower().startswith("invalid params")


def parse_reply(raw) -> Listing:
    """The JSON-RPC answer to Files.GetDirectory -> the cards and the next page. Never raises; `error` is set
    when there was no usable answer at all (an empty directory has no `files` and is not an error)."""
    if not isinstance(raw, dict):
        return Listing((), "", "No answer from YouTube.")
    if raw.get("error"):
        problem = raw["error"]
        text = clean_text(problem.get("message") if isinstance(problem, dict) else problem, 120)
        return Listing((), "", text or "YouTube reported an error.", 0, is_refusal(problem, text))
    result = raw.get("result")
    if not isinstance(result, dict):
        return Listing((), "", "No answer from YouTube.")
    files = result.get("files", [])
    if not isinstance(files, list):
        return Listing((), "", "YouTube sent a list this screen cannot read.")
    entries, more, seen, skipped = [], "", set(), 0
    for item in files[:MAX_ENTRIES]:
        try:
            entry = parse_entry(item)
        except (TypeError, ValueError, AttributeError, OverflowError):
            entry = None
        if entry is None or (entry.kind != MORE and entry.path in seen):
            skipped += 1
        elif entry.kind == MORE:
            more = more or entry.path
        else:
            seen.add(entry.path)
            entries.append(entry)
    return Listing(tuple(entries), more, "", skipped)


def merge(first, page) -> Listing:
    """`first` followed by the next `page` (cards already shown are not repeated); the page decides what comes after,
    unless it brought nothing new: then the list ends here (a page that only repeats is not asked after again)."""
    seen = {e.path for e in first.entries}
    added = tuple(e for e in page.entries if e.path not in seen)
    return Listing(first.entries + added, page.more if added else "", "")


def discover_routes(main_page) -> dict:
    """section key -> route, found on the add-on's main page (a Listing): the tile whose path holds the section's
    token. Languages do not matter, only paths. The route is the tile's address as it stands (query and slash
    included). A section not found there is left out (its fallback route is used)."""
    found = {}
    for section in SECTIONS:
        for token in section.tokens:
            tile = next((e for e in main_page.entries if e.kind == FOLDER and "/search" not in e.path
                         and token in route_parts(e.path)[0].lower()), None)
            if tile:
                found[section.key] = tile.path
                break
    return found


# ---- the sections and what the window shows --------------------------------------------------

def search_route(query) -> str:
    query = clean_query(query)
    return SEARCH_ROUTE.format(q=quote_plus(query)) if query else ""


def section_view(key, routes=None, query="") -> View:
    """The view of a section; Search without a query has no route yet (the window asks for one)."""
    section = next((s for s in SECTIONS if s.key == key), SECTIONS[0])
    if section.key == SEARCH:
        query = clean_query(query)
        return View(SEARCH, f"Results for “{query}”" if query else section.name, search_route(query), False)
    return View(section.key, section.name, (routes or {}).get(section.key) or section.route, section.needs_login)


def folder_view(entry) -> View:
    return View(FOLDER_KEY, entry.title, entry.path, False)


def crumb(stack, view) -> str:
    """The header line: the sections and folders gone through, ending in the one shown."""
    return " › ".join([v.title for v, _ in stack] + [view.title])


def rail() -> list:
    return [RailEntry(s.key, s.name) for s in SECTIONS]


def gate(signed, needs_login, keys) -> Optional[str]:
    """The mode when a section cannot even be asked for, else None. A section of the account needs the sign-in,
    which in turn needs the key: without the key that is what is said."""
    if needs_login and signed is False:
        return NEEDKEY if keys is False else SIGNIN
    return None


def mode_for(listing, keys) -> str:
    """What to show for the add-on's answer. Cards win: an empty answer is a missing key only when the key is known to be
    missing. A refused path is a section the add-on does not serve now, not a network failure."""
    if listing.error:
        return UNAVAILABLE if listing.refused else ERROR
    if listing.entries:
        return DATA
    return NEEDKEY if keys is False else EMPTY


EMPTY_TEXT = {"rec": "Nothing is recommended yet. Watch something and it shows up here.",
              "subs": "No new videos from your subscriptions.",
              "later": "Your Watch later list is empty.",
              "history": "Nothing watched yet.",
              "lists": "You have no playlists.",
              "trend": "Nothing is trending right now.",
              SEARCH: "Nothing found. Try other words.",
              FOLDER_KEY: "This list is empty."}


def message(mode, view=None, keys=None, detail="") -> Message:
    """(title, text, button) of the card for a mode that is not DATA."""
    key = view.key if view else ""
    if mode == SIGNIN:
        return Message("Sign in to see your videos", "Sign in once: a code appears here, you type it on your phone.",
                       "Sign in to YouTube")
    if mode == NEEDKEY:
        return Message("Set up your Google key", "Open the Media Stick page on your phone: " + KEYS_PATH, "Try again")
    if mode == UNAVAILABLE:
        text = "This section is not available right now."
        if keys is not True:                     # signed in without a personal key: most sections of the account are refused
            text += " It needs a personal Google key. " + KEYS_HINT
        return Message("Not available right now", text, "Try again")
    if mode == PROMPT:
        return Message("Search YouTube", "Type what you want to watch. The results show up here.", "Search")
    if mode == ERROR:
        return Message("YouTube did not answer", (detail + " " if detail else "") + "Check the network and try again.",
                       "Try again")
    if mode == EMPTY:
        text = EMPTY_TEXT.get(key, "Nothing here.")
        if keys is None:
            text += " If you expected videos, check the Google key. " + KEYS_HINT
        return Message("No results" if key == SEARCH else "Nothing here", text, "New search" if key == SEARCH else "Try again")
    return Message("Loading…", "", "")


def keys_present(raw) -> bool:
    """Whether the add-on's api_keys.json (read as JSON) holds a personal key, id and secret. That file is the
    older place; the add-on keeps the personal key in its settings (see settings_keys_present)."""
    keys = raw.get("keys") if isinstance(raw, dict) else None
    personal = keys.get("personal") if isinstance(keys, dict) else None
    return isinstance(personal, dict) and all(isinstance(personal.get(k), str) and personal[k].strip()
                                              for k in ("api_key", "client_id", "client_secret"))


def settings_keys_present(text) -> Optional[bool]:
    """Whether the add-on's settings.xml (its text) holds a personal key, id and secret: the settings
    youtube.api.key, youtube.api.id and youtube.api.secret, all three not empty. None when the text is not XML.
    Only whether a value is there is looked at; no value is returned."""
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, TypeError):
        return None
    values = {node.get("id"): (node.text or "").strip() for node in root.iter("setting")}
    return all(values.get(name) for name in KEY_SETTINGS)


def keys_state(*found) -> Optional[bool]:
    """The answer to "is there a personal key" from what each place says (True, False, or None when the place
    could not be read): any place with a key wins; else one that could not be read leaves it unknown."""
    if any(f is True for f in found):
        return True
    return None if any(f is None for f in found) else False


class Step(NamedTuple):
    number: int
    total: int
    title: str                   # "" when the phone page sent none
    hint: str


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_step(raw, now) -> Optional[Step]:
    """The key wizard's progress, as the phone page writes it ({"step", "total", "title", "hint", "updated"}), or None
    when no wizard is running: the file is not that shape, the step is not one of 1..total (0 is "not started"), or it was
    written more than STEP_MAX_AGE seconds from `now` (a wizard left behind). Title and hint are cleaned like any other
    text (Cyrillic stays) and may be empty; the total is STEP_TOTAL when the file does not say."""
    if not isinstance(raw, dict):
        return None
    number, total, updated = raw.get("step"), raw.get("total"), raw.get("updated")
    total = total if _whole(total) and 1 <= total <= 99 else STEP_TOTAL
    if not _whole(number) or not 1 <= number <= total:
        return None
    if isinstance(updated, bool) or not isinstance(updated, (int, float)) or not math.isfinite(updated) \
            or abs(now - updated) > STEP_MAX_AGE:
        return None
    return Step(number, total, clean_text(raw.get("title"), 80), clean_text(raw.get("hint"), 160))


# ---- playing and caching ---------------------------------------------------------------------

def play_path(entry) -> str:
    """What Player.Open takes: the add-on's own play route of a video; "" for anything else."""
    return entry.path if entry.kind == VIDEO and PATH_RE.fullmatch(entry.path) else ""


def fresh(stamp, now) -> bool:
    return stamp is not None and 0 <= now - stamp < CACHE_TTL
