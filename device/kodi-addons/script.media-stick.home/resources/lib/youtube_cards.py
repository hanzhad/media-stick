"""YouTube app: what a card of the grid says. Ready data in, strings out; nothing here touches Kodi.

A card is the picture (16:9, rounded), the title in two lines, up to two grey lines (the channel; views and how long
ago: together they do not fit the 352 px of a card) and, on the picture, one strip image: the dark pill with the length (red LIVE, "24 videos" for a playlist) at the bottom
right and the red bar of what was watched along the bottom. The pill and the bar are ONE texture per card
(youtube-strip-<pill>-<bar>.png, drawn by tools/make-youtube-art.py from strip_variants()), which keeps the Pi's
texture budget; its name is the card's `strip` property, empty when there is neither.

The lines are cut here, not by Kodi: a label in a list scrolls sideways when it is focused and a textbox does not
ellipsize, so each line is made to fit its label with an ellipsis (textfit.wrap_name, whose estimate errs wide).
"""
from typing import Iterator, Optional, Tuple

from resources.lib import textfit as fit, youtube_data as data

TITLE_SIZE, TITLE_WIDTH, TITLE_LINES = 28, 336, 2    # px: Med28; the labels are 352 wide, the estimate has Reg's metrics
META_SIZE, META_WIDTH = 22, 336                      # px: Reg22
BADGE_SIZE, BADGE_PAD = 25, 28                       # px: Reg25; room around the text inside the pill
BADGE_WIDTHS = (80, 96, 112, 136, 160, 184)          # px: the pills there are pictures of; the label is right-aligned in them
BAR_STEPS = (0, 25, 50, 75, 100)                     # percent of the red bar there are pictures of; 0: no bar
DARK, RED, NONE = "d", "l", "n"                      # the pill: dark, red (LIVE), none
LIVE = "LIVE"
SEPARATOR = " · "


def plural(count, word) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def format_views(count) -> str:
    """1.2M views, 340K views, 12 views; "" when the count is not known."""
    count = data.as_count(count)
    if not count:
        return ""
    for scale, unit in ((10 ** 9, "B"), (10 ** 6, "M"), (10 ** 3, "K")):
        if count >= scale:
            value = count / scale
            number = f"{value:.1f}".rstrip("0").rstrip(".") if value < 10 else str(int(value))
            return f"{number}{unit} views"
    return plural(count, "view")


def age_text(published, now) -> str:
    """3 days ago, 2 weeks ago, 1 year ago; "" when either time is not known or the date is in the future."""
    if not published or not now or published > now:
        return ""
    seconds = int(now - published)
    for span, word in ((365 * 86400, "year"), (30 * 86400, "month"), (7 * 86400, "week"), (86400, "day"),
                       (3600, "hour"), (60, "minute")):
        if seconds >= span:
            return f"{plural(seconds // span, word)} ago"
    return "just now"


def kind_text(entry) -> str:
    """The grey line of a playlist or channel that has no channel name: what it is."""
    route = data.route_parts(entry.path)[0]
    return "Playlist" if "/playlist/" in route else "Channel" if "/channel/" in route else ""


def one_line(parts) -> str:
    """`parts` joined with a dot, the last ones dropped until it fits the line, the rest cut with an ellipsis."""
    parts = [part for part in parts if part]
    while len(parts) > 1 and fit.text_px(SEPARATOR.join(parts), META_SIZE) > META_WIDTH:
        parts.pop()
    return fit.wrap_name(SEPARATOR.join(parts), META_WIDTH, META_SIZE, 1)[0] if parts else ""


def meta_lines(entry, now=None) -> Tuple[str, str]:
    """The two grey lines under the title, filled from the top with what is known: the channel (a playlist's or
    channel's own name, else what it is), then "1.2M views · 3 days ago" (the age goes first when it does not fit).
    Both are "" when nothing is known: the card is just shorter."""
    if entry.kind == data.VIDEO:
        known = [one_line([entry.channel]), one_line([format_views(entry.views), age_text(entry.published, now)])]
    elif entry.kind == data.FOLDER:
        known = [one_line([entry.channel or kind_text(entry)])]
    else:
        known = []
    known = [line for line in known if line] + ["", ""]
    return known[0], known[1]


def title_lines(title) -> Tuple[str, ...]:
    """The title as the two lines the card has room for; the second ends in an ellipsis when it is cut."""
    return fit.wrap_name(title, TITLE_WIDTH, TITLE_SIZE, TITLE_LINES)


# ---- the strip on the picture ----------------------------------------------------------------

def badge_of(entry) -> Tuple[str, str]:
    """(text, style) of the pill: LIVE in red for a live stream, the length of a video when it is known, the
    size of a playlist when it is known; ("", NONE) otherwise: a card whose length is not known shows no pill."""
    if entry.kind == data.VIDEO:
        if entry.live:
            return LIVE, RED
        length = data.format_duration(entry.seconds)
        return (length, DARK) if length else ("", NONE)
    if entry.kind == data.FOLDER and entry.count:
        return plural(entry.count, "video"), DARK
    return "", NONE


def badge_width(text) -> int:
    """The narrowest pill picture the text fits in (the widest when it does not: the label is cut to it)."""
    need = fit.text_px(text, BADGE_SIZE) + BADGE_PAD
    return next((w for w in BADGE_WIDTHS if w >= need), BADGE_WIDTHS[-1])


def badge_text(text) -> str:
    return fit.wrap_name(text, BADGE_WIDTHS[-1] - BADGE_PAD, BADGE_SIZE, 1)[0] if text else ""


def bar_step(progress) -> int:
    """The bar picture for `progress` (0..1): none for nothing, else the nearest quarter, never less than a quarter."""
    if not isinstance(progress, (int, float)) or progress <= 0:
        return 0
    return 100 if progress >= 0.9 else min(75, max(25, round(progress * 4) * 25))


def strip_key(style, width, bar) -> str:
    """The `strip` property: the part of the picture's name after "youtube-strip-"; "" for no pill and no bar."""
    if style == NONE and not bar:
        return ""
    return f"{style}{width if style != NONE else 0:03d}-{bar:03d}"


def strip_variants() -> Iterator[Tuple[str, int, int]]:
    """(style, pill width, bar percent) of every strip picture the skin may ask for."""
    for bar in BAR_STEPS:
        for width in BADGE_WIDTHS:
            yield DARK, width, bar
        if bar:
            yield NONE, 0, bar
    yield RED, badge_width(LIVE), 0


# ---- the key wizard's block on the "Set up your Google key" card -----------------------------

STEP_SIZE, HINT_SIZE, STEP_WIDTH = 32, 25, 780        # px: Med32 and Reg25; the labels in the skin are 820 wide


def step_lines(step) -> Tuple[str, str, str]:
    """(heading, first hint line, second hint line) of the block under the card's text: "Step 2 of 6: <title>" (only
    "Step 2 of 6" when the phone page sent no title) and the hint in two lines. All "" when no wizard is running.
    Each line is cut to its label with an ellipsis here (a label that is too wide scrolls); the words are the phone
    page's own, in Russian, and are not touched beyond what youtube_data.clean_text did."""
    if step is None:
        return "", "", ""
    heading = f"Step {step.number} of {step.total}" + (f": {step.title}" if step.title else "")
    first, second = fit.wrap_name(step.hint, STEP_WIDTH, HINT_SIZE, 2)
    return fit.wrap_name(heading, STEP_WIDTH, STEP_SIZE, 1)[0], first, second


def card_props(entry, now: Optional[float] = None) -> dict:
    """The strings the skin shows for a card besides the picture; `now` (epoch seconds) is for "3 days ago"."""
    text, style = badge_of(entry)
    width = badge_width(text) if text else 0
    bar = 0 if style == RED else bar_step(entry.progress)         # a live stream has no watched part
    first, second = title_lines(entry.title)
    meta, meta2 = meta_lines(entry, now)
    return {"title1": first, "title2": second, "meta": meta, "meta2": meta2, "badge": badge_text(text),
            "strip": strip_key(style, width, bar), "kind": entry.kind}
