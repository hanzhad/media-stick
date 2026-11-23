"""The built-in demo of the YouTube app: about 40 invented videos in the sections, answered the way the add-on
answers Files.GetDirectory (see youtube_data), so the demo runs the real parser. No network, no account.

Nothing here is a real video or channel. The pictures are the placeholders in resources/media/demo/yt-thumb-N.png
(made by tools/make-youtube-art.py, one scene per channel); some videos have none, to show the fallback. The videos
differ the way real cards do: most have a channel, views, an age and a length, a few are as bare as what the add-on
sends without a Google key (title, picture, file), one is live, one playlist has 24 videos, a few are watched.
`scenario` shows the cards the screen has when there is nothing to show: "signin", "needkey", "empty", "error",
"unavailable", "loading" ("" is the full demo).
"""
import os
import re
import time
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

from resources.lib import youtube_data as data

THUMBS = 8                      # yt-thumb-1.png .. yt-thumb-8.png: the scene of each channel
SCENARIOS = ("signin", "needkey", "empty", "error", "unavailable", "loading")
PAGE = 20                       # videos on the first page of Recommendations; the rest is the next page

# A name may carry what the font cannot draw: the screen cleans it (see youtube_data.clean_text).
CHANNELS = ["Northern Workshop", "Pixel Kitchen 🍳", "Тихий Берег", "Orbit Lab", "Daily Trails", "Stage Notes",
            "Garden Hour", "Нова Хвиля"]

# (title, channel index, seconds, views, days ago); the index in this list is the video's number. A live stream has
# seconds 0, the videos in BARE come without channel, length, views and age, every ninth video has no picture.
VIDEOS = [
    ("Build a bookshelf from one board", 0, 1334, 1240000, 3), ("Ten-minute pasta that tastes like an hour", 1, 612, 340000, 11),
    ("Ранкова прогулянка вздовж озера", 2, 2210, 87000, 2), ("How a telescope mirror is ground", 3, 1876, 412000, 40),
    ("The coast path, start to finish", 4, 3645, 2300000, 21), ("Live: evening jazz from the old hall", 5, 0, 3400, 0),
    ("Small garden, big harvest", 6, 904, 56000, 6), ("Нова хвиля: тиждень у студії", 7, 1521, 1100, 1),
    ("Sanding without the dust", 0, 478, 9800, 90), ("Dumplings, three ways", 1, 1103, 4700000, 400),
    ("Тиха ріка на світанку", 2, 5400, 0, 0),
    ("Why the night sky is dark, and why that was once a serious problem for astronomers", 3, 2790, 760000, 14),
    ("Ridge trail in the fog", 4, 1688, 38000, 5), ("Piano duet, first rehearsal", 5, 842, 640, 2),
    ("Compost in a small yard", 6, 733, 120000, 30), ("Музика для дороги", 7, 4020, 2800000, 62),
    ("A workbench you can fold away", 0, 2456, 650000, 8), ("One pot, five dinners", 1, 1290, 0, 0),
    ("Over the pass by bicycle", 4, 3012, 99000, 17), ("The sound of an empty hall", 5, 311, 1400, 9),
    ("Seed trays for beginners", 6, 556, 22000, 140), ("Орбіта: що там, за Місяцем", 3, 2204, 310000, 4),
    ("Pickles in a week", 1, 427, 78000, 33), ("Winter in New York ❄️ Snowfall", 4, 1950, 1900000, 1),
    ("Hand-cut dovetails", 0, 1812, 0, 0), ("Лісова стежка. Осінь", 2, 2705, 5200, 12),
    ("Soundcheck stories", 5, 1397, 16000, 45), ("Rooftop herbs", 6, 689, 8900, 7),
    ("Comets, explained slowly", 3, 3330, 2100000, 220), ("Нова хвиля: гості тижня", 7, 1744, 3000, 3),
    ("Bread without kneading", 1, 903, 910000, 25), ("Village road, long take", 4, 4380, 0, 0),
    ("A lamp from scrap oak", 0, 1566, 44000, 19), ("Concert hall tour at closing time", 5, 1126, 270000, 55),
    ("Orchard in March", 6, 2012, 33000, 380), ("Lens flare and other myths", 3, 778, 150000, 10),
    ("Береги Дніпра: літній огляд", 2, 3811, 61000, 26), ("Ramen from scratch", 1, 2347, 1300000, 16),
    ("Gravel ride, day two", 4, 2965, 0, 0), ("Нова хвиля: музика ночі", 7, 5112, 7600, 2),
]
BARE = {10, 17, 24, 31, 38}                       # no channel (artist ["Untitled"] or []), length, views, age
LIVE = 5
WATCHED = {2: 1.0, 8: 0.35, 13: 0.7, 16: 1.0, 26: 0.5}      # video number -> the part watched (1.0: to the end)
# (name, the videos inside, how many the playlist says it has)
PLAYLISTS = [("Weekend projects", range(0, 40, 8), 24), ("Slow travel", range(4, 40, 6), 12),
             ("Late night listening", range(5, 40, 7), 8), ("Cooking basics", range(1, 40, 5), 37),
             ("Space and stars", range(3, 40, 9), 5), ("Для відпочинку", range(2, 40, 10), 150)]
SECTION_VIDEOS = {
    "rec": list(range(0, 30)),
    "subs": [1, 4, 6, 9, 12, 14, 17, 19, 22, 25, 28, 31, 33, 36, 38, 39],
    "later": [3, 7, 11, 21, 29],
    "history": [0, 2, 5, 8, 10, 13, 16, 18, 23, 27],
    "trend": [4, 5, 9, 13, 22, 23, 28, 33, 35, 39],
}
# What the add-on's main page links to, in the form the real one lists them (with ?category_label=, with or without
# a closing slash). Watch later differs from data.SECTIONS' fallback path on purpose: the demo goes through
# discover_routes() like the real add-on.
ROUTES = {"rec": data.ROOT + "special/recommendations?category_label=Recommendations",
          "subs": data.ROOT + "special/my_subscriptions?category_label=My+Subscriptions",
          "later": data.ROOT + "special/playlist/WL/?category_label=Watch+Later",
          "history": data.ROOT + "special/playlist/HL/?category_label=History",
          "lists": data.ROOT + "channel/mine/playlists?category_label=Playlists",
          "trend": data.ROOT + "special/popular_right_now?category_label=Trending"}
NEXT_PAGE = data.ROOT + "special/recommendations?page=2"
BY_ROUTE = {urlsplit(route).path: key for key, route in ROUTES.items()}
SEARCH_PATH = urlsplit(data.SEARCH_ROUTE).path
PLAYLIST_PATH = re.compile(r"/playlist/demo([0-9]{1,3})/")
SEARCH_FILLERS = ["the full story", "start to finish", "for beginners", "what nobody tells you", "a calm walkthrough",
                  "behind the scenes", "ten things to know", "in one take", "the slow version", "questions answered"]


# The key wizard's progress as the phone page writes it (the words are Russian there); the "needkey" demo shows it.
KEY_STEP = {"step": 3, "total": 6, "title": "Создайте проект в Google Cloud",
            "hint": "Откройте console.cloud.google.com на телефоне и нажмите «Новый проект»."}


class Situation(NamedTuple):
    signed: bool
    keys: bool


def situation(scenario) -> Situation:
    """Who is signed in and whether there is a Google key, as the scenario pretends."""
    return Situation(scenario != "signin", scenario not in ("needkey", "unavailable"))


def _thumb(scene, thumb_dir):
    return os.path.join(thumb_dir, f"yt-thumb-{scene % THUMBS + 1}.png")


def _stamp(now, days):
    """Kodi's date format for `days` days before `now`."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - days * 86400 - 600))


def _file(path, title, thumb="", seconds=0, channel="", plot="", directory=False, unknown_channel=False, **extra):
    """A channel the add-on does not know comes as artist ["Untitled"] (or []): `unknown_channel` is the first.
    `extra` are the fields read when present (views, videos, live, dateadded, playcount, resume)."""
    art = {"thumb": thumb} if thumb else {}
    return {"file": path, "filetype": "directory" if directory else "file", "label": title, "title": title,
            "type": "unknown", "thumbnail": thumb, "art": art, "plot": plot, "duration": seconds, "runtime": seconds,
            "studio": [channel] if channel else [], "artist": ["Untitled"] if unknown_channel else [], **extra}


def _video(number, thumb_dir, now):
    title, channel, seconds, views, days = VIDEOS[number]
    thumb = "" if number % 9 == 8 else _thumb(channel, thumb_dir)
    path = data.ROOT + f"play/?video_id=demo{number:02d}"
    if number in BARE:
        return _file(path, title, thumb, 0, "", "An invented video for the demo.", unknown_channel=number % 2 == 1)
    extra = {"views": views} if views else {}
    if number == LIVE:
        extra["live"] = True
    else:
        extra["dateadded"] = _stamp(now, days)
    part = WATCHED.get(number, 0.0)
    if part >= 1.0:
        extra["playcount"] = 1
    elif part:
        extra["resume"] = {"position": int(seconds * part), "total": seconds}
    return _file(path, title, thumb, seconds, CHANNELS[channel], "An invented video for the demo.", **extra)


def _answer(files):
    """Like Kodi: an empty directory has no `files` at all."""
    result = {"limits": {"start": 0, "end": len(files), "total": len(files)}}
    if files:
        result["files"] = files
    return {"id": 1, "jsonrpc": "2.0", "result": result}


def _main_page():
    tiles = [_file(data.ROOT + "sign/in/?category_label=Sign+In", "[B]Sign In[/B]")]    # an action, not a list: the parser leaves it out
    names = {s.key: s.name for s in data.SECTIONS}
    tiles += [_file(route, f"[B]{names[key]}[/B]", directory=True) for key, route in ROUTES.items()]
    return _answer(tiles + [_file(data.ROOT + "kodion/search/input/", "Search", directory=True)])


def _search(query, thumb_dir, now):
    words = query.casefold().split()
    found = [n for n, (title, channel, *_) in enumerate(VIDEOS)
             if all(w in f"{title} {data.clean_text(CHANNELS[channel])}".casefold() for w in words)]
    if found:
        return _answer([_video(n, thumb_dir, now) for n in found])
    shown = query[:40]
    return _answer([_file(data.ROOT + f"play/?video_id=demo-q{i:02d}", f"{shown}: {filler}", _thumb(i, thumb_dir),
                          600 + 137 * i, data.clean_text(CHANNELS[i % len(CHANNELS)]), views=2500 * (i + 1) ** 2,
                          dateadded=_stamp(now, 2 + 9 * i)) for i, filler in enumerate(SEARCH_FILLERS)])


def reply(route, scenario="", thumb_dir="", now=None) -> dict:
    """What Files.GetDirectory answers for `route` in the demo (the same dict the JSON-RPC call returns); `now` is
    the time the videos' ages are counted from."""
    now = time.time() if now is None else now
    parts = urlsplit(route)
    if parts.path == urlsplit(data.ROOT).path:
        return _main_page()
    if scenario == "error":
        return {"id": 1, "jsonrpc": "2.0", "error": {"code": -32100, "message": "Demo: the add-on did not answer."}}
    if scenario == "unavailable":                # what the add-on says to a section it does not serve: Invalid params
        return {"id": 1, "jsonrpc": "2.0", "error": {"code": data.INVALID_PARAMS, "message": "Invalid params."}}
    if scenario in ("needkey", "empty"):
        return _answer([])
    query = parse_qs(parts.query)
    key = BY_ROUTE.get(parts.path)
    if key == "lists":
        return _answer([_file(data.ROOT + f"playlist/demo{n}/", name, _thumb(n, thumb_dir), channel=CHANNELS[n % len(CHANNELS)],
                              directory=True, videos=count) for n, (name, _, count) in enumerate(PLAYLISTS)])
    if key:
        numbers = SECTION_VIDEOS[key]
        if key == "rec":
            second = query.get("page") == ["2"]
            numbers = numbers[PAGE:] if second else numbers[:PAGE]
        files = [_video(n, thumb_dir, now) for n in numbers]
        if key == "rec" and not query.get("page"):
            files.append(_file(NEXT_PAGE, "Next Page", directory=True))
        return _answer(files)
    if parts.path == SEARCH_PATH:
        return _search(" ".join(query.get("q", [""])), thumb_dir, now)
    playlist = PLAYLIST_PATH.fullmatch(parts.path)
    if playlist and int(playlist.group(1)) < len(PLAYLISTS):
        return _answer([_video(n, thumb_dir, now) for n in PLAYLISTS[int(playlist.group(1))][1]])
    return _answer([])
