"""Design tokens and fonts.

Three layers, following current dashboard practice:

  base palette  ->  semantic roles  ->  component values

Surfaces are layered neutrals rather than pure black, borders are a subtle
white overlay instead of coloured lines, text has three levels of emphasis and
exactly one accent colour is used for interactive elements. Semantic colours
(green / amber / red) are reserved for meaning - status and hardware alerts.

The short names (PANEL, GRID, MUTED, ...) are kept because the graph widgets
consume them.
"""

from __future__ import annotations

import tkinter.font as tkfont

# ---------------------------------------------------------------- base ----
# cool neutral ramp, near-black at the dark end
GRAY_990 = "#08090D"
GRAY_950 = "#0B0D12"
GRAY_900 = "#11141B"
GRAY_850 = "#161A22"
GRAY_800 = "#1C212B"
GRAY_700 = "#242B38"
GRAY_600 = "#333C4C"
GRAY_500 = "#4A5468"
GRAY_400 = "#6B7688"
GRAY_300 = "#98A2B3"
GRAY_200 = "#C3CAD6"
GRAY_100 = "#E8ECF3"
GRAY_50 = "#F5F7FA"

# ----------------------------------------------------------- semantic ----
BG = GRAY_950            # page
SURFACE = GRAY_900       # cards
PANEL = GRAY_900         # alias used by the graph widgets
SURFACE_2 = GRAY_850     # nested panels
PANEL_ALT = GRAY_850     # alias
SURFACE_3 = GRAY_800     # hover / popover

BORDER = "#20242E"       # ~8% white over the page
BORDER_STRONG = "#2C333F"
GRID = "#191D25"         # graph grid lines

FG = GRAY_50             # primary text
FG_2 = GRAY_200          # secondary text
MUTED = GRAY_400         # tertiary text, labels
DISABLED = GRAY_500

ACCENT = "#6E8BFF"       # the single interactive accent
ACCENT_HOVER = "#8AA1FF"
ACCENT_SOFT = "#1A2138"  # accent at ~12% over a surface
ACCENT_TEXT = "#A8B9FF"

OK = "#3FD68C"
WARN = "#FFB84D"
ERR = "#FF6B6B"
INFO = "#5AC8FA"

STATUS_COLORS = {
    "ok": OK,
    "starting": WARN,
    "unavailable": ERR,
}

# chart palette (indigo, emerald, sky, amber, violet)
CHART = ["#6E8BFF", "#3FD68C", "#5AC8FA", "#FFB84D", "#B98CFF"]

# ------------------------------------------------------------- geometry --
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24
SPACE_8 = 32

RADIUS_SM = 6
RADIUS = 10
RADIUS_LG = 14

# type scale
FS_CAPTION = 8
FS_SMALL = 9
FS_BODY = 10
FS_LABEL = 11
FS_TITLE = 13
FS_H2 = 16
FS_H1 = 19
FS_HERO = 34

# --------------------------------------------------------------- fonts ---
UI_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"
_UI_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI", "Tahoma")
_MONO_CANDIDATES = ("Cascadia Mono", "Consolas", "Courier New")


def resolve_fonts() -> None:
    """Pick the best installed families; Tk must already exist."""
    global UI_FAMILY, MONO_FAMILY
    try:
        available = {name.lower() for name in tkfont.families()}
    except Exception:
        return
    for name in _UI_CANDIDATES:
        if name.lower() in available:
            UI_FAMILY = name
            break
    for name in _MONO_CANDIDATES:
        if name.lower() in available:
            MONO_FAMILY = name
            break


def ui(size: int = FS_BODY, weight: str = "normal") -> tuple[str, int, str]:
    return (UI_FAMILY, size, weight)


def mono(size: int = FS_BODY, weight: str = "normal") -> tuple[str, int, str]:
    return (MONO_FAMILY, size, weight)


def scaled(size: int, scale: float) -> int:
    return max(6, int(round(size * scale)))


def mix(front: str, back: str, amount: float) -> str:
    """Blend two hex colours - used for hover states and soft fills."""
    fr, fg_, fb = _rgb(front)
    br, bg_, bb = _rgb(back)
    return "#%02x%02x%02x" % (
        int(fr * amount + br * (1 - amount)),
        int(fg_ * amount + bg_ * (1 - amount)),
        int(fb * amount + bb * (1 - amount)),
    )


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
