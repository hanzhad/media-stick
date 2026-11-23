"""Onboarding on the TV: what a flow's document (mediastick_onboarding) becomes on the screen. Ready data in, strings
and numbers out; nothing here touches Kodi. The windows are in onboarding_app (the key wizard) and signin (the sign-in
code); both draw what this module hands them.

The words come from the document's `tv` fields. What is fixed here is only the furniture of the layouts: "Step 2 of 4",
"Then", the line over a QR, the key hints in a footer, a badge's "set".

A step list is a list control (one item for each step, a step is wrapped into two lines at most). Chips are different:
their widths follow their words, so the skin has a fixed set of slots (a picture and a label each) and layout_chips
says where each goes; the window moves the slots (Control.setPosition / setWidth) and sets their window properties.
"""
import math
from typing import NamedTuple, Optional, Tuple

from resources.lib import textfit, youtube_data

SIGNIN, KEYS = "signin", "keys"
ACTIVE = "active"
STATES = ("active", "done", "failed", "cancelled")
MAX_STEPS, MAX_CHIPS, MAX_ROWS, MAX_ITEMS = 8, 12, 4, 6
THEN_SLOTS = MAX_ROWS - 1
CODE_LONG = 14                      # a code longer than this is drawn in the smaller font

# What each text is drawn in and how wide its room is (px of the 1080-high skin; the font's number is the size textfit wants).
STEP_SIZE, TITLE_SIZE = 32, 56      # Med32 (a step, a chip), MsTitle
SIGNIN_STEP_W, KEYS_STEP_W = 876, 438
SIGNIN_TITLE_W, KEYS_TITLE_W = 948, 510

CHIP_H, CHIP_PAD, CHIP_MIN, GAP, SEP_W, LINE_H, MAX_LINES = 66, 27, 96, 18, 24, 84, 5
WARN_GAP = 36                       # between the last line of chips and the warning
CHIP_AREA_W = 846                   # the room of the chip rows: the right column of the keys card
BG = {"done": "FF2F6B4C", "now": "FFF2F3F5", "todo": "FF2A2D38"}                 # a chip's fill, by state
TEXT = {"done": "[COLOR FFF2F3F5]{}[/COLOR]", "now": "[COLOR FF0F1115][B]{}[/B][/COLOR]", "todo": "[COLOR FFF2F3F5]{}[/COLOR]"}
BADGE_COLOURS = {"youtube": "FF6A2A30"}     # the square behind a service's letter; any other service is grey
BADGE_GREY = "FF2A2D38"

STEP_TEXT = {"done": "FFA3A8B3", "now": "FFF2F3F5", "todo": "FF8D939F"}     # a step's words and number, by state
STEP_RING = {"done": "FFF2F3F5", "now": "FFF2F3F5", "todo": "FF454A57"}     # the ring round the number
BADGE = {"ok": ("FF2F6B4C", "FFF2F3F5"), "wait": ("FF14161D", "FFA3A8B3")}  # a badge's fill and words, by state

THEN, SEPARATOR = "Then", "›"
QR_REMOTE = "Phone not connected yet? Scan to open the remote."
QR_LINK = "Scan to open the sign-in page on your phone."
ALSO_ON = "Or on any device: "


class Step(NamedTuple):
    text: str
    state: str                      # done | now | todo


class Screen(NamedTuple):
    service: str
    flow: str
    state: str                      # active | done | failed | cancelled
    kicker: str
    title: str
    hint: str
    warn: str
    step: int                       # the current step, 1-based; 0 when there are no steps
    steps: Tuple[Step, ...]
    code: str
    link: str
    chips: Tuple[Tuple[Tuple[str, str], ...], ...]      # rows of (text, done | now | todo)
    items: Tuple[Tuple[str, bool], ...]                 # (label, has it)

    @property
    def active(self) -> bool:
        return self.state == ACTIVE


def _side(value, limit) -> str:
    """The `tv` text of a {"tv", "phone"} pair."""
    return youtube_data.clean_text(value.get("tv"), limit) if isinstance(value, dict) else ""


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _chips(raw) -> tuple:
    rows, left = [], MAX_CHIPS
    for raw_row in raw[:MAX_ROWS] if isinstance(raw, list) else []:
        row = []
        for chip in raw_row[:left] if isinstance(raw_row, list) else []:
            text = youtube_data.clean_text(chip.get("t"), 48) if isinstance(chip, dict) else ""
            if text:
                state = chip.get("s")
                row.append((text, state if state in BG else "todo"))
        left -= len(row)
        if row:
            rows.append(tuple(row))
    return tuple(rows)


def _items(raw) -> tuple:
    out = []
    for item in raw[:MAX_ITEMS] if isinstance(raw, list) else []:
        label = youtube_data.clean_text(item.get("label"), 32) if isinstance(item, dict) else ""
        if label:
            out.append((label, item.get("s") == "ok"))
    return tuple(out)


def _link(value) -> str:
    return value.strip() if isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 300 else ""


def step_state(number, step, state) -> str:
    """How step `number` is marked when the flow is at `step`: a finished flow has every step done."""
    if state == "done" or number < step:
        return "done"
    return "now" if number == step else "todo"


def parse(doc, name="") -> Optional[Screen]:
    """The screen a document asks for, or None when it is not one (not an object, no flow, a state that is not one of
    the four). `name` is the service's name: the small line over the title when the document has none. What the file
    says is cleaned like any text for a label; a step with no `tv` text is left out."""
    if not isinstance(doc, dict) or doc.get("state") not in STATES or not isinstance(doc.get("flow"), str):
        return None
    raw = doc.get("steps") if isinstance(doc.get("steps"), list) else []
    texts = [t for t in (_side(s, 120) for s in raw[:MAX_STEPS]) if t]
    step = doc.get("step") if _whole(doc.get("step")) else 1
    step = max(1, min(step, len(texts))) if texts else 0
    steps = tuple(Step(t, step_state(n, step, doc["state"])) for n, t in enumerate(texts, 1))
    code = doc.get("code")
    return Screen(
        service=str(doc.get("service", "")), flow=doc["flow"], state=doc["state"],
        kicker=_side(doc.get("kicker"), 60) or name, title=_side(doc.get("title"), 80),
        hint=_side(doc.get("hint"), 160), warn=_side(doc.get("warn"), 160), step=step, steps=steps,
        code=youtube_data.clean_text(code, 40) if isinstance(code, str) else "", link=_link(doc.get("link")),
        chips=_chips(doc.get("chips")), items=_items(doc.get("items")))


def fresh(doc, now) -> bool:
    """Whether a document's own clock lets it be shown: it has an `expires` that has not passed. The library says the
    same when it reads; a screen that is handed a document and looks again later asks this."""
    expires = doc.get("expires") if isinstance(doc, dict) else None
    return isinstance(expires, (int, float)) and not isinstance(expires, bool) and math.isfinite(expires) and now < expires


def site(link) -> str:
    """youtube.com/activate from https://www.youtube.com/activate?user_code=...: where to go without the link."""
    text = link.split("://", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    return (text[4:] if text.startswith("www.") else text).rstrip("/")


# ---- the step list -----------------------------------------------------------------------------------------

def tinted(colour, text) -> str:
    """`text` in `colour` (AARRGGBB) with a [COLOR] tag; "" stays "" (the skin tests an empty line with IsEmpty)."""
    return f"[COLOR {colour}]{text}[/COLOR]" if text else ""


class Row(NamedTuple):
    line1: str
    line2: str                      # "" for a step that fits one line
    state: str
    number: str

    def props(self) -> dict:
        """The list item's properties: the words and the number (in the colour of the state), the state (which marker
        is drawn) and the colour of the ring. The colours are in the text, as [COLOR] tags: Kodi does not take a list
        item's <textcolor> from a ListItem property (the text is not drawn at all), only fixed colours there."""
        colour = STEP_TEXT[self.state]
        return {"t1": tinted(colour, self.line1), "t2": tinted(colour, self.line2), "state": self.state,
                "num": tinted(colour, self.number), "ring": STEP_RING[self.state]}


def step_rows(screen, width) -> Tuple[Row, ...]:
    return tuple(Row(*textfit.wrap_name(s.text, width, STEP_SIZE, 2), s.state, str(n)) for n, s in enumerate(screen.steps, 1))


def title_lines(screen, width) -> Tuple[str, str]:
    """The title cut into the two lines a card has room for (an ellipsis at the end of a long one)."""
    return textfit.wrap_name(screen.title, width, TITLE_SIZE, 2)


# ---- the sign-in layout (inside the sign-in window) ------------------------------------------------------------

SIGNIN_PROPS = ("ob", "ob_badge", "ob_badge_colour", "ob_kicker", "ob_title", "ob_hint", "ob_site", "ob_code", "ob_codelong",
                "ob_caption", "ob_footer")


def signin_props(screen, caption, footer) -> dict:
    """Window properties of the sign-in layout, all of them (empty when `screen` is None: the layout is off)."""
    if screen is None:
        return dict.fromkeys(SIGNIN_PROPS, "")
    name = screen.kicker or screen.service
    return {"ob": "1", "ob_badge": name[:1].upper(), "ob_badge_colour": BADGE_COLOURS.get(screen.service, BADGE_GREY),
            "ob_kicker": screen.kicker, "ob_title": textfit.wrap_name(screen.title, SIGNIN_TITLE_W, TITLE_SIZE, 1)[0],
            "ob_hint": screen.hint, "ob_site": ALSO_ON + site(screen.link) if screen.link else "",
            "ob_code": screen.code, "ob_codelong": "1" if len(screen.code) > CODE_LONG else "",
            "ob_caption": caption, "ob_footer": footer}


def signin_footer(allow_skip) -> str:
    return "Back — cancel" + (" · Menu — continue without an account" if allow_skip else "")


# ---- the key-wizard layout (the onboarding window) -----------------------------------------------------------

KEYS_PROPS = ("kicker", "title1", "title2", "header", "warn", "footer")


def header(screen) -> str:
    """"Step 2 of 4 · on the Google page tap": where the flow is, then the document's own hint."""
    where = f"Step {screen.step} of {len(screen.steps)}" if screen.steps else ""
    return " · ".join(part for part in (where, screen.hint) if part)


def keys_props(screen, footer) -> dict:
    line1, line2 = title_lines(screen, KEYS_TITLE_W)
    return {"kicker": screen.kicker, "title1": line1, "title2": line2, "header": header(screen), "warn": screen.warn,
            "footer": footer}


def keys_footer(address) -> str:
    """The key hints at the foot of the card; `address` is the phone page's (no scheme), "" when the stick is offline."""
    return (f"Easier on a laptop: open {address} in its browser · " if address else "") + "Back — close"


def badge_rows(screen) -> Tuple[dict, ...]:
    """The status badges as list items: what the phone has handed over so far ("API key · set"), "—" for what it has
    not yet. Never a value."""
    rows = []
    for label, has in screen.items:
        fill, words = BADGE["ok" if has else "wait"]
        rows.append({"t1": tinted(words, f"{label} · set" if has else f"{label} —"), "bg": fill})
    return tuple(rows)


# ---- chips ----------------------------------------------------------------------------------------------------

class Placed(NamedTuple):
    kind: str                       # chip | sep | then
    slot: int                       # 1-based, within its kind
    x: int                          # from the left of the chip area
    y: int
    w: int
    text: str
    state: str                      # of a chip; "" for the others


def _chip_width(text, room) -> int:
    return min(room, max(CHIP_MIN, int(textfit.text_px(text, STEP_SIZE)) + 2 * CHIP_PAD))


def layout_chips(rows, width=CHIP_AREA_W) -> Tuple[Placed, ...]:
    """Where each chip, separator and "Then" goes in an area `width` wide. A row of chips goes on from the last, a
    chip that does not fit moves to a new line (without its separator), every row after the first starts a new line
    with "Then". At most MAX_LINES lines: what would not fit is left out."""
    placed, x, line, chips, seps, thens = [], 0, 0, 0, 0, 0
    for r, row in enumerate(rows):
        if r and x:
            x, line = 0, line + 1
        if r:
            thens += 1
            w = int(textfit.text_px(THEN, STEP_SIZE))
            placed.append(Placed("then", thens, x, line * LINE_H, w, THEN, ""))
            x += w + GAP
        for c, (text, state) in enumerate(row):
            w = _chip_width(text, width)
            lead = SEP_W + GAP if c else 0
            if x + lead + w > width and x:
                x, line, lead = 0, line + 1, 0
            if line >= MAX_LINES:
                return tuple(placed)
            if lead:
                seps += 1
                placed.append(Placed("sep", seps, x, line * LINE_H, SEP_W, SEPARATOR, ""))
                x += lead
            chips += 1
            placed.append(Placed("chip", chips, x, line * LINE_H, w, text, state))
            x += w + GAP
    return tuple(placed)


def warn_offset(placed) -> int:
    """How far under the chip area's top the warning goes: just under the last line of chips (none: at the top)."""
    lines = max((p.y // LINE_H for p in placed), default=-1) + 1
    return (lines - 1) * LINE_H + CHIP_H + WARN_GAP if lines else 0


def chip_props(placed) -> dict:
    """Window properties of the chip slots: chipN (label) and chipN_bg (fill), sepN, thenN; "" for a slot not used."""
    props = {}
    for n in range(1, MAX_CHIPS + 1):
        props[f"chip{n}"], props[f"chip{n}_bg"], props[f"sep{n}"] = "", BG["todo"], ""
    for n in range(1, THEN_SLOTS + 1):
        props[f"then{n}"] = ""
    for p in placed:
        if p.kind == "chip":
            props[f"chip{p.slot}"], props[f"chip{p.slot}_bg"] = TEXT[p.state].format(p.text), BG[p.state]
        else:
            props[f"{p.kind}{p.slot}"] = p.text
    return props


# ---- the YouTube "keys" card ----------------------------------------------------------------------------------

def card_step(screen) -> Optional[youtube_data.Step]:
    """The key card's progress line from a keys document: "Step 2 of 4: <title>" and the step's own words as the hint
    (the card is older than the document and shows what the old step file gave it). None when it is not a running keys flow."""
    if screen is None or screen.flow != KEYS or not screen.active or not screen.steps:
        return None
    return youtube_data.Step(screen.step, len(screen.steps), screen.title, screen.steps[screen.step - 1].text)
