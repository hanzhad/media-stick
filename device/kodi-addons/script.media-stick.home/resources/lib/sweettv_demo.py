"""The built-in demo of the SWEET.TV app: about 50 invented channels in 6 categories with a plausible schedule around
`now` (what was on, what is on, what comes), in the same shape the plugin saves (see sweettv_data), so the demo runs
the real parser; and a state to go with it: some favourites, the channels watched last, and a place to continue
an archived programme from.

Nothing here is a real channel or programme. Logos are the placeholder pictures in resources/media/demo/
(made by tools/make-sweettv-art.py); some channels have none, to show the fallback badge.
"""
import os
import random

LOGOS = 12                      # logo-1.png .. logo-12.png
SLOT = 300                      # s: schedules start on a five-minute mark

CATEGORIES = [(1, "News"), (2, "Movies & Series"), (3, "Sport"), (4, "Kids"), (5, "Music & Lifestyle"), (6, "Documentary")]
HIDDEN = 1000                   # every real channel is in this one too; the app leaves it out

# (name, category id); the order is the channel number. Every third channel has no logo.
CHANNELS = [
    ("Aurora News 24", 1), ("Capital Report", 1), ("Новини Країни", 1), ("World Desk", 1),
    ("Business Hour", 1), ("Weather Centre", 1), ("Daybreak Live", 1), ("Перший Міський", 1),
    ("Cinema Nova", 2), ("Premiere Classics", 2), ("Серіал Плюс", 2), ("Night Shift Films", 2),
    ("Crime Files", 2), ("Laugh Track", 2), ("Frontier Westerns", 2), ("Sci-Fi Orbit and Beyond Network", 2),
    ("Arena Sport 1", 3), ("Arena Sport 2", 3), ("Harbor Football", 3), ("Мотор ТБ", 3),
    ("Court & Field", 3), ("Fight Night", 3), ("Race Control", 3), ("Snow Peaks Live", 3),
    ("Tiny Tales", 4), ("Cartoon Cove", 4), ("Малюк", 4), ("Adventure Kids", 4),
    ("Puzzle Planet", 4), ("Bedtime Stories", 4), ("Hero Squad", 4), ("Playground TV", 4),
    ("Hit Parade", 5), ("Музика Плюс", 5), ("Acoustic Hour", 5), ("Club Mix", 5),
    ("Home & Garden", 5), ("Tasty Table", 5), ("Travel Journal", 5), ("Wellness Now", 5),
    ("Deep Planet", 6), ("Ancient Worlds", 6), ("Wild Frontier", 6), ("Science Lab", 6),
    ("History Vault", 6), ("Ocean Eye", 6), ("Мандрівник", 6), ("Engineering Now", 6),
]
NO_CATEGORY = ("Open Window", None)       # in All only
NO_EPG = "Test Pattern"                   # a channel the service sent no programmes for
GAP = "Night Shift Films"                 # a channel with nothing scheduled right now
FAVOURITES = ["Aurora News 24", "Arena Sport 1", "Cartoon Cove", "Hit Parade", "Cinema Nova", "Deep Planet"]
RECENT = ["Cinema Nova", "Aurora News 24", "Arena Sport 1", "Cartoon Cove", "Deep Planet", "Hit Parade"]   # newest first
RESUME_ON = "Cinema Nova"                 # the channel whose last archived programme has a place to continue from
DAYS = 3                                  # days of archive on a catch-up channel

# (title, description) per category; a few programmes get no description, as in real data
SHOWS = {
    1: [("Morning Briefing", "The night's news, the weather for the day and the traffic on the way to work."),
        ("World Report", "Correspondents on three continents report on the stories that will move markets and borders."),
        ("Business Today", "Prices, rates and the people who set them: a half hour with the economy."),
        ("The Evening Desk", "The day in review: the main stories, the analysis and one long interview."),
        ("Weather and Travel", "A week ahead for the whole country, with the roads, the rails and the airports."),
        ("Midday Update", "A quarter of an hour that catches you up on everything that happened since breakfast."),
        ("Press Room", "Editors from four newspapers argue about what the front page should have said."),
        ("Headline Hour", "The hour's headlines, repeated every ten minutes, with the details in between.")],
    2: [("Harbour Lights", "A ferry captain returns to the town she left, and to the secret the harbour kept for twenty years."),
        ("Paper Moons", "A small-time forger is hired to fake the one letter that could save a theatre."),
        ("The Long Way Round", "Two brothers drive across the continent to deliver an urn, arguing the whole way."),
        ("Quiet Streets", "Night shift in a city that never quite sleeps: a detective, a baker and a missing key."),
        ("Second Chances", "A new episode: the plan falls apart on the way to the coast."),
        ("Glass Houses", "A family of architects discovers that the house they built has been listening."),
        ("The Last Lighthouse", "A keeper, a storm and a radio that starts picking up tomorrow's weather."),
        ("Under a Copper Sky", "A western about a surveyor, a railway and the town that would rather not be found."),
        ("Small Hours", "")],
    3: [("Live: League Round-up", "All the goals of the round with the commentators who were there."),
        ("Match of the Day", "Two teams, one trophy and a very loud crowd."),
        ("Highlights Show", "The best saves, the worst misses and the one tackle everybody is still talking about."),
        ("The Training Ground", "A coach walks through one set piece, step by step, with the players who scored it."),
        ("Live: Cup Quarter-final", "The cup draw has made a favourite of nobody. Kick-off in the studio, then the stadium."),
        ("Sport Extra", "Everything that does not fit the other shows: curling, darts, a tractor race."),
        ("Replay: Season Opener", "The first match of the season, in full, with the studio's second thoughts."),
        ("Pit Lane", "The mechanics' view of a race weekend, from the first lap to the last tyre.")],
    4: [("Bubble and Squeak", "Two friends in a pond find out what happens when it rains upwards."),
        ("Little Explorers", "A group of four-year-olds, a magnifying glass and one very large garden."),
        ("The Cloud Factory", "Where clouds come from, who paints them and why some of them cry."),
        ("Story Time", "A story, a song and a sleepy bear. Best watched with a blanket."),
        ("Counting Sheep", "Numbers from one to ten with the sheep that cannot sleep."),
        ("Robot Friends", "A robot that is afraid of the dark meets one that is afraid of the light."),
        ("Paint Along", "A new picture every day, three colours at a time. Bring paper."),
        ("Dino Detectives", "Who ate the leaves of the tallest tree? The detectives follow the footprints.")],
    5: [("Top 20 This Week", "The twenty songs the country played most, counted down with the videos."),
        ("Unplugged Sessions", "Bands in a small room, no cables, one microphone and a lot of quiet."),
        ("Sunday Brunch", "A table, four guests and a menu nobody planned. Recipes on the screen."),
        ("Garden Makeover", "A yard the size of a parking space becomes a garden in five days."),
        ("Street Food Tour", "One city, twelve stalls, and the one dish every local will tell you to try."),
        ("Night Drive Mix", "An hour of slow beats for an empty road."),
        ("Mind and Body", "Ten minutes of stretching and ten of talk with people who sleep well."),
        ("Coast to Coast", "A travel show on a bicycle, with all the hills left in.")],
    6: [("Deep Planet", "Cameras go down to where the light stops and find a city of animals no one has named."),
        ("Ancient Worlds", "How the first towns fed themselves, and the wall that was built to keep them from being fed on."),
        ("Wild Frontier", "A year in the life of a wolf pack on the edge of a growing town."),
        ("Science Lab", "Three experiments you can do at the kitchen table, and the physics behind each."),
        ("History Vault", "Letters, maps and one forgotten diary tell the story of a siege."),
        ("Ocean Eye", "A season with the people who count whales from a cliff."),
        ("Engineering Now", "The longest bridge, the deepest tunnel and the small bolt that holds them both."),
        ("Big Questions", "")],
}
DURATIONS = {1: (30, 30, 60), 2: (90, 105, 120), 3: (60, 90, 105, 120), 4: (20, 25, 30), 5: (30, 45, 60), 6: (45, 50, 60)}
PAST_MINUTES = (180, 420)       # a schedule starts this long before `now`: three to seven hours of archive


def names() -> list:
    return CHANNELS + [NO_CATEGORY, (NO_EPG, 1)]


def cid_of(name) -> int:
    return 101 + [n for n, _ in names()].index(name)


def _schedule(cid, category, now, rng, gap=False):
    """Programmes from a few hours back to eleven hours ahead, as the service sends them."""
    out, t = [], now - now % SLOT - rng.randint(*PAST_MINUTES) * 60
    index = 0
    while t < now + 11 * 3600:
        minutes = rng.choice(DURATIONS.get(category, (30, 60)))
        stop = t + minutes * 60
        if not (gap and t <= now < stop):
            title, blurb = rng.choice(SHOWS.get(category, [("Programme", "")]))
            out.append({"id": cid * 1000 + index, "time_start": t, "time_stop": stop, "text": title,
                        "description": blurb, "available": True})
        t, index = stop, index + 1
    return out


def demo_data(now, logo_dir) -> dict:
    """The demo channel list as a GetChannels.json answer; `logo_dir` holds logo-1.png .. logo-12.png."""
    channels = []
    for i, (name, category) in enumerate(names()):
        cid = 101 + i
        rng = random.Random(cid)
        logo = os.path.join(logo_dir, f"logo-{(i - i // 3) % LOGOS + 1}.png") if i % 3 != 2 else ""
        channel = {"id": cid, "name": name, "number": i + 1, "slug": f"demo-{cid}", "available": True,
                   "category": [category, HIDDEN] if category else [HIDDEN],
                   "catchup": i % 4 != 3, "catchup_duration": DAYS, "icon_v2_url": logo,
                   "live_blackout": False}
        if name != NO_EPG:
            channel["epg"] = _schedule(cid, category or 5, now, rng, gap=name == GAP)
        channels.append(channel)
    return {"status": "OK", "categories": [{"id": c, "caption": n} for c, n in CATEGORIES + [(HIDDEN, "All")]],
            "list": channels}


def demo_state(raw, now) -> dict:
    """The state of someone who has used the screen: favourites, the channels watched last (the first of them is
    `last`), and the place the last archived programme of RESUME_ON stopped at. `raw` is demo_data's answer."""
    ids = {name: str(cid_of(name)) for name, _ in names()}
    recent = [{"id": ids[name], "at": int(now) - 1200 * (n + 1) ** 2} for n, name in enumerate(RECENT)]
    state = {"favourites": [ids[name] for name in FAVOURITES], "recent": recent, "last": recent[0]["id"], "resume": {}}
    channel = next(c for c in raw["list"] if c["name"] == RESUME_ON)
    past = [p for p in channel["epg"] if p["time_stop"] <= now]
    if past:
        p = past[-1]
        state["resume"][ids[RESUME_ON]] = {"epg": str(p["id"]), "title": p["text"], "start": p["time_start"],
                                           "stop": p["time_stop"], "pos": min(25 * 60, (p["time_stop"] - p["time_start"]) // 2),
                                           "at": int(now) - 1500}
    return state
