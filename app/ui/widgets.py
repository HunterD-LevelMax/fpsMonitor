"""Flat, modern widget set drawn on Canvas.

Tk has no rounded corners, no hover states and no segmented controls, so the
building blocks of the new interface are drawn by hand:

    Surface / Card      rounded panel with a subtle border
    KpiTile             big number + label + caption (dashboard metric)
    Pill                status chip: coloured dot + text
    Segmented           segmented control (window / mode / scale pickers)
    Switch / SwitchRow  toggle in the style of current settings screens
    FlatButton          rounded button with hover and pressed states
    Slider              custom track + knob slider
    SidebarNav          vertical navigation with an active indicator
    StatRow             label ... value row used by sensor lists
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from . import theme


# ---------------------------------------------------------------- helpers --
def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               radius: float, **kwargs):
    """Rounded rectangle: a smoothed polygon is the cheapest way in Tk."""
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def set_bg_recursive(widget: tk.Misc, colour: str) -> None:
    """Repaint a small widget tree - used for hover highlights."""
    try:
        current = widget.cget("bg")
    except tk.TclError:
        current = None
    if current is not None:
        try:
            widget.configure(bg=colour)
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        set_bg_recursive(child, colour)


def draw_icon(canvas: tk.Canvas, kind: str, colour: str, size: int = 16) -> None:
    """Tiny vector icons so the navigation does not depend on emoji fonts."""
    canvas.delete("all")
    mid = size / 2
    width = 1.6
    if kind == "monitor":
        for index, height in enumerate((0.35, 0.55, 0.8)):
            x = 3 + index * 4.4
            canvas.create_line(x, size - 3, x, size - 3 - height * (size - 6),
                               fill=colour, width=2, capstyle="round")
    elif kind == "frames":
        canvas.create_line(2, mid + 3, 5, mid + 3, 7, 4, 9, size - 4, 11, mid,
                           14, mid, fill=colour, width=width, joinstyle="round")
    elif kind == "overlay":
        round_rect(canvas, 2.5, 3.5, size - 2.5, size - 4.5, 3,
                   outline=colour, fill="", width=width)
        canvas.create_line(5, 7, 11, 7, fill=colour, width=width)
    elif kind == "settings":
        for y, knob in ((5.5, 10.5), (10.5, 5.5)):
            canvas.create_line(2.5, y, size - 2.5, y, fill=colour, width=width,
                               capstyle="round")
            canvas.create_oval(knob - 2, y - 2, knob + 2, y + 2, fill=colour, outline="")
    elif kind == "diagnostics":
        canvas.create_oval(2.5, 2.5, size - 2.5, size - 2.5, outline=colour, width=width)
        canvas.create_line(mid, 7.5, mid, 11.5, fill=colour, width=width, capstyle="round")
        canvas.create_oval(mid - 1, mid - 4.5, mid + 1, mid - 2.5, fill=colour, outline="")


# ----------------------------------------------------------------- panels --
class Surface(tk.Canvas):
    """Rounded panel that hosts a normal frame inside.

    A Canvas does not grow with its contents, so the panel watches the inner
    frame and raises its own height when the content needs more room (unless the
    caller asked for a fixed height).
    """

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG, fill: str = theme.SURFACE,
                 border: str | None = theme.BORDER, radius: int = theme.RADIUS,
                 padding: int = theme.SPACE_4, height: int | None = None, **kwargs) -> None:
        self._auto_height = height is None
        options = dict(kwargs)
        options["height"] = 12 if height is None else height
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **options)
        self._bg = bg
        self._fill = fill
        self._border = border
        self._radius = radius
        self._padding = padding
        self.body = tk.Frame(self, bg=fill)
        self._window = self.create_window(0, 0, window=self.body, anchor="nw")
        self.bind("<Configure>", self._reshape)
        if self._auto_height:
            self.body.bind("<Configure>", self._grow)

    def _grow(self, _event=None) -> None:
        needed = self.body.winfo_reqheight() + 2 * self._padding
        if needed > self.winfo_height() + 1:
            self.configure(height=needed)

    @property
    def fill(self) -> str:
        return self._fill

    def set_fill(self, colour: str, border: str | None = None) -> None:
        self._fill = colour
        if border is not None:
            self._border = border
        self.body.configure(bg=colour)
        for child in self.body.winfo_children():
            set_bg_recursive(child, colour)
        self._reshape()

    def _reshape(self, _event=None) -> None:
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        self.delete("shape")
        if self._border:
            round_rect(self, 0, 0, width - 1, height - 1, self._radius,
                       fill=self._border, outline="", tags="shape")
            round_rect(self, 1, 1, width - 2, height - 2, max(1, self._radius - 1),
                       fill=self._fill, outline="", tags="shape")
        else:
            round_rect(self, 0, 0, width - 1, height - 1, self._radius,
                       fill=self._fill, outline="", tags="shape")
        self.tag_lower("shape")
        pad = self._padding
        self.coords(self._window, pad, pad)
        self.itemconfigure(self._window, width=max(1, width - 2 * pad),
                           height=max(1, height - 2 * pad))


class Card(Surface):
    """Panel with an optional uppercase title and a right-hand control slot."""

    def __init__(self, master: tk.Misc, title: str | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        if title:
            header = tk.Frame(self.body, bg=self.fill)
            header.pack(fill="x", pady=(0, theme.SPACE_3))
            tk.Label(header, text=title.upper(), bg=self.fill, fg=theme.MUTED,
                     font=theme.ui(theme.FS_LABEL, "bold")).pack(side="left")
            self.header = header
        self.content = tk.Frame(self.body, bg=self.fill)
        self.content.pack(fill="both", expand=True)


class Divider(tk.Frame):
    def __init__(self, master: tk.Misc, colour: str = theme.BORDER, **kwargs) -> None:
        super().__init__(master, bg=colour, height=1, **kwargs)


# ------------------------------------------------------------------ tiles --
class KpiTile(Surface):
    """Big number, label above, caption below - the classic KPI card."""

    def __init__(self, master: tk.Misc, label: str, unit: str = "", *,
                 min_width: int = 150, height: int = 96, **kwargs) -> None:
        super().__init__(master, fill=theme.SURFACE, padding=theme.SPACE_4,
                         width=min_width, height=height, **kwargs)
        fill = self.fill
        self.label = tk.Label(self.body, text=label.upper(), bg=fill, fg=theme.MUTED,
                              font=theme.ui(theme.FS_SMALL, "bold"), anchor="w")
        self.label.pack(fill="x")

        row = tk.Frame(self.body, bg=fill)
        row.pack(fill="x")
        self.value = tk.Label(row, text="--", bg=fill, fg=theme.FG,
                              font=theme.mono(20, "bold"), anchor="w")
        self.value.pack(side="left")
        self.unit = tk.Label(row, text=unit, bg=fill, fg=theme.MUTED,
                             font=theme.ui(theme.FS_BODY), anchor="w")
        self.unit.pack(side="left", padx=(3, 0), pady=(6, 0))

        self.caption = tk.Label(self.body, text="", bg=fill, fg=theme.MUTED,
                                font=theme.ui(theme.FS_CAPTION), anchor="w")
        self.caption.pack(fill="x")

    def update_value(self, text: str, colour: str | None = None) -> None:
        self.value.configure(text=text, fg=colour or theme.FG)

    def update_caption(self, text: str, colour: str | None = None) -> None:
        self.caption.configure(text=text, fg=colour or theme.MUTED)


class StatRow(tk.Frame):
    """label ......... value, used by the sensor list."""

    def __init__(self, master: tk.Misc, label: str, *, fill: str = theme.SURFACE) -> None:
        super().__init__(master, bg=fill)
        self._fill = fill
        dot = tk.Label(self, text="●", bg=fill, fg=theme.MUTED, font=theme.ui(6))
        dot.pack(side="left", padx=(0, theme.SPACE_2))
        self.label = tk.Label(self, text=label, bg=fill, fg=theme.FG_2,
                              font=theme.ui(theme.FS_BODY), anchor="w")
        self.label.pack(side="left")
        self.value = tk.Label(self, text="--", bg=fill, fg=theme.FG,
                              font=theme.mono(theme.FS_BODY, "bold"), anchor="e")
        self.value.pack(side="right")
        self.dot = dot

    def update_value(self, text: str, colour: str | None = None) -> None:
        self.value.configure(text=text, fg=colour or theme.FG)

    def update_dot(self, colour: str) -> None:
        self.dot.configure(fg=colour)


class Pill(tk.Canvas):
    """Status chip: coloured dot + text, never colour alone."""

    def __init__(self, master: tk.Misc, text: str = "", tone: str = theme.OK, *,
                 bg: str = theme.SURFACE, height: int = 22) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=height)
        self._bg = bg
        self._tone = tone
        self._text = text
        self._font = theme.ui(theme.FS_SMALL, "bold")
        self._measure = tkfont.Font(font=self._font)
        self.bind("<Configure>", lambda _e: self._draw())
        self._autosize()

    def configure_pill(self, text: str, tone: str) -> None:
        self._text = text
        self._tone = tone
        self._autosize()
        self._draw()

    def _autosize(self) -> None:
        """A chip must hug its text - a Canvas would otherwise stretch."""
        width = 12 + 7 + self._measure.measure(self._text) + 13
        self.configure(width=max(34, width))

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return
        fill = theme.mix(self._tone, self._bg, 0.16)
        edge = theme.mix(self._tone, self._bg, 0.30)
        round_rect(self, 0, 0, width - 1, height - 1, height / 2,
                   fill=fill, outline=edge, width=1)
        dot_x = theme.SPACE_3
        self.create_oval(dot_x - 2.5, height / 2 - 2.5, dot_x + 2.5, height / 2 + 2.5,
                         fill=self._tone, outline="")
        self.create_text(dot_x + 7, height / 2 + 1, text=self._text, anchor="w",
                         fill=self._tone, font=self._font)


# -------------------------------------------------------------- controls --
class FlatButton(tk.Canvas):
    """Rounded button with hover / pressed / disabled states."""

    def __init__(self, master: tk.Misc, text: str, command: Callable[[], None] | None = None,
                 *, variant: str = "secondary", bg: str = theme.SURFACE,
                 width: int | None = None, height: int = 28) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=height)
        self._text = text
        self._command = command
        self._variant = variant
        self._bg = bg
        self._hover = False
        self._pressed = False
        self._enabled = True
        self._font = theme.ui(theme.FS_BODY, "bold")
        if width:
            self.configure(width=width)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="" if not enabled else "hand2")
        self._draw()

    # colours per variant
    def _palette(self) -> tuple[str, str, str]:
        if not self._enabled:
            return theme.SURFACE_2, theme.BORDER, theme.DISABLED
        if self._variant == "primary":
            base = theme.ACCENT_HOVER if self._hover else theme.ACCENT
            if self._pressed:
                base = theme.mix(theme.ACCENT, "#000000", 0.85)
            return base, base, "#0B0D12"
        if self._variant == "ghost":
            fill = theme.SURFACE_3 if self._hover else theme.SURFACE_2
            return fill, theme.BORDER, theme.ACCENT_TEXT
        fill = theme.SURFACE_3 if self._hover or self._pressed else theme.SURFACE_2
        return fill, theme.BORDER_STRONG, theme.FG

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4:
            return
        fill, edge, text_colour = self._palette()
        round_rect(self, 0, 0, width - 1, height - 1, theme.RADIUS_SM,
                   fill=fill, outline=edge, width=1)
        self.create_text(width / 2, height / 2 + 1, text=self._text, fill=text_colour,
                         font=self._font)

    def _on_enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event) -> None:
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, _event) -> None:
        if self._enabled:
            self._pressed = True
            self._draw()

    def _on_release(self, _event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._enabled and self._command:
            self._command()


class Segmented(tk.Frame):
    """Segmented control: one rounded track, flat segments inside."""

    def __init__(self, master: tk.Misc, options: list[tuple[str, str]], variable: tk.StringVar,
                 command: Callable[[], None] | None = None, *, bg: str = theme.SURFACE_2,
                 fill: str = theme.SURFACE) -> None:
        super().__init__(master, bg=fill)
        self._variable = variable
        self._command = command
        self._buttons: dict[str, tk.Label] = {}
        track = tk.Frame(self, bg=bg, padx=2, pady=2)
        track.pack()
        for value, label in options:
            item = tk.Label(track, text=label, bg=bg, fg=theme.MUTED,
                            font=theme.ui(theme.FS_BODY), padx=theme.SPACE_3, pady=3,
                            cursor="hand2")
            item.pack(side="left")
            item.bind("<Button-1>", lambda _e, v=value: self._select(v))
            item.bind("<Enter>", lambda _e, v=value: self._hover(v, True))
            item.bind("<Leave>", lambda _e, v=value: self._hover(v, False))
            self._buttons[value] = item
        self._paint()

    def _select(self, value: str) -> None:
        self._variable.set(value)
        self._paint()
        if self._command:
            self._command()

    def _hover(self, value: str, entering: bool) -> None:
        if self._variable.get() == value:
            return
        self._buttons[value].configure(fg=theme.FG_2 if entering else theme.MUTED)

    def _paint(self) -> None:
        current = self._variable.get()
        for value, item in self._buttons.items():
            if value == current:
                item.configure(bg=theme.ACCENT_SOFT, fg=theme.ACCENT_TEXT)
            else:
                item.configure(bg=theme.SURFACE_2, fg=theme.MUTED)


class Switch(tk.Canvas):
    """Small toggle switch, 38x20."""

    def __init__(self, master: tk.Misc, variable: tk.BooleanVar,
                 command: Callable[[], None] | None = None, *, bg: str = theme.SURFACE) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=38, height=20,
                         cursor="hand2")
        self._variable = variable
        self._command = command
        self.bind("<Button-1>", self._toggle)
        self._variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _event=None) -> None:
        self._variable.set(not self._variable.get())
        if self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        on = bool(self._variable.get())
        round_rect(self, 1, 2, 37, 18, 8,
                   fill=theme.ACCENT if on else theme.SURFACE_3,
                   outline=theme.ACCENT if on else theme.BORDER_STRONG, width=1)
        knob_x = 28 if on else 10
        self.create_oval(knob_x - 6, 4, knob_x + 6, 16,
                         fill="#FFFFFF" if on else theme.GRAY_300, outline="")


class SwitchRow(tk.Frame):
    """Label (+ optional hint) on the left, switch on the right."""

    def __init__(self, master: tk.Misc, label: str, variable: tk.BooleanVar,
                 command: Callable[[], None] | None = None, *, hint: str = "",
                 fill: str = theme.SURFACE) -> None:
        super().__init__(master, bg=fill)
        self.columnconfigure(0, weight=1)
        text = tk.Frame(self, bg=fill)
        text.grid(row=0, column=0, sticky="w")
        tk.Label(text, text=label, bg=fill, fg=theme.FG, font=theme.ui(theme.FS_BODY),
                 anchor="w").pack(anchor="w")
        if hint:
            tk.Label(text, text=hint, bg=fill, fg=theme.MUTED,
                     font=theme.ui(theme.FS_CAPTION), anchor="w",
                     justify="left").pack(anchor="w")
        self.switch = Switch(self, variable, command, bg=fill)
        self.switch.grid(row=0, column=1, sticky="e", padx=(theme.SPACE_4, 0))


class Slider(tk.Canvas):
    """Custom track + knob slider (tk.Scale looks dated)."""

    def __init__(self, master: tk.Misc, variable: tk.DoubleVar, low: float, high: float,
                 command: Callable[[], None] | None = None, *, bg: str = theme.SURFACE,
                 width: int = 220, height: int = 24, fmt: str = "{:.2f}") -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0,
                         width=width, height=height, cursor="hand2")
        self._variable = variable
        self._low, self._high = low, high
        self._command = command
        self._fmt = fmt
        self._dragging = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._jump)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self._variable.trace_add("write", lambda *_: self._draw())

    def _fraction(self) -> float:
        span = self._high - self._low
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (float(self._variable.get()) - self._low) / span))

    def _set_from_x(self, x: float) -> None:
        pad = 10
        usable = max(1, self.winfo_width() - 2 * pad)
        fraction = min(1.0, max(0.0, (x - pad) / usable))
        value = self._low + fraction * (self._high - self._low)
        self._variable.set(round(value, 2))

    def _jump(self, event) -> None:
        self._dragging = True
        self._set_from_x(event.x)

    def _drag(self, event) -> None:
        if self._dragging:
            self._set_from_x(event.x)

    def _release(self, _event) -> None:
        self._dragging = False
        if self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 20:
            return
        pad = 10
        y = height / 2
        usable = max(1, width - 2 * pad)
        fraction = self._fraction()
        knob_x = pad + usable * fraction
        round_rect(self, pad, y - 2, pad + usable, y + 2, 2,
                   fill=theme.SURFACE_3, outline="")
        round_rect(self, pad, y - 2, max(pad + 4, knob_x), y + 2, 2,
                   fill=theme.ACCENT, outline="")
        self.create_oval(knob_x - 7, y - 7, knob_x + 7, y + 7,
                         fill=theme.GRAY_100, outline=theme.BORDER_STRONG, width=1)
        value = theme.ui(theme.FS_SMALL)
        self.create_text(pad, y - 11, text=self._fmt.format(float(self._variable.get())),
                         anchor="w", fill=theme.MUTED, font=value)


class SidebarNav(tk.Frame):
    """Vertical navigation: icon + label, active item gets an accent marker."""

    def __init__(self, master: tk.Misc, items: list[tuple[str, str, str]],
                 on_select: Callable[[str], None], *, bg: str = theme.SURFACE) -> None:
        super().__init__(master, bg=bg)
        self._on_select = on_select
        self._rows: dict[str, tk.Frame] = {}
        self._icons: dict[str, tk.Canvas] = {}
        self._labels: dict[str, tk.Label] = {}
        self._markers: dict[str, tk.Frame] = {}
        self._icon_kinds: dict[str, str] = {}
        self._active = ""
        self._bg = bg

        for key, label, icon in items:
            row = tk.Frame(self, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=1)
            marker = tk.Frame(row, bg=bg, width=3)
            marker.pack(side="left", fill="y")
            canvas = tk.Canvas(row, bg=bg, width=18, height=18, highlightthickness=0, bd=0)
            canvas.pack(side="left", padx=(theme.SPACE_3, theme.SPACE_2), pady=theme.SPACE_2)
            draw_icon(canvas, icon, theme.MUTED, 16)
            text = tk.Label(row, text=label, bg=bg, fg=theme.MUTED,
                            font=theme.ui(theme.FS_BODY), anchor="w")
            text.pack(side="left", fill="x", expand=True, pady=theme.SPACE_2)

            for widget in (row, canvas, text):
                widget.bind("<Button-1>", lambda _e, k=key: self.select(k))
                widget.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
                widget.bind("<Leave>", lambda _e, k=key: self._hover(k, False))

            self._rows[key] = row
            self._icons[key] = canvas
            self._labels[key] = text
            self._markers[key] = marker
            self._icon_kinds[key] = icon

    def select(self, key: str) -> None:
        self._active = key
        self._paint()
        self._on_select(key)

    def _hover(self, key: str, entering: bool) -> None:
        if key == self._active:
            return
        colour = theme.SURFACE_3 if entering else self._bg
        set_bg_recursive(self._rows[key], colour)
        draw_icon(self._icons[key], self._icon_kinds[key],
                  theme.FG_2 if entering else theme.MUTED, 16)

    def _paint(self) -> None:
        for key, row in self._rows.items():
            active = key == self._active
            set_bg_recursive(row, theme.ACCENT_SOFT if active else self._bg)
            self._markers[key].configure(bg=theme.ACCENT if active else self._bg)
            self._labels[key].configure(fg=theme.ACCENT_TEXT if active else theme.MUTED)
            draw_icon(self._icons[key], self._icon_kinds[key],
                      theme.ACCENT_TEXT if active else theme.MUTED, 16)


class ScrollPage(tk.Frame):
    """Page container that scrolls when its content is taller than the window."""

    def __init__(self, master: tk.Misc, *, bg: str = theme.BG) -> None:
        super().__init__(master, bg=bg)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scrollbar)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.content.bind("<Configure>", self._on_content)

    def _on_scrollbar(self, first: str, last: str) -> None:
        self.bar.set(first, last)

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_content(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._toggle_bar()

    def _toggle_bar(self) -> None:
        needed = self.content.winfo_reqheight() > self.canvas.winfo_height() + 2
        if needed and not self.bar.winfo_manager():
            self.bar.pack(side="right", fill="y")
        elif not needed and self.bar.winfo_manager():
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def scroll_by(self, steps: int) -> None:
        if not self.bar.winfo_manager():
            return
        self.canvas.yview_scroll(steps * 3, "units")


class SectionTitle(tk.Label):
    def __init__(self, master: tk.Misc, text: str, *, fill: str = theme.SURFACE,
                 top: int = theme.SPACE_4) -> None:
        super().__init__(master, text=text.upper(), bg=fill, fg=theme.MUTED,
                         font=theme.ui(theme.FS_SMALL, "bold"), anchor="w")
        self.pack(fill="x", pady=(top, theme.SPACE_2))
