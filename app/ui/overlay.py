"""The always-on-top HUD that sits over games.

Layout in the spirit of FPS Monitor:

* the values are drawn on a colour-keyed window, so they stay fully opaque while
  everything around them is transparent;
* a separate window behind them paints the translucent container, so the
  container can be switched off or made more/less see-through without ever
  touching the readability of the numbers;
* the big FPS reads the average / 1% / 0.1% lows right beside it;
* optional per-core CPU bars, a frame-time sparkline, and per-row controls.
"""

from __future__ import annotations

import time
import tkinter as tk

from .. import winutil
from ..config import Config
from ..metrics import color_of, format_value, label_of, value_color
from . import theme, widgets
from .framegraph import FrameTimeGraph

EMPHASIS = {"fps", "frametime"}
# metrics rendered inline, right next to the big FPS counter
INLINE_FPS = ("fps_avg", "fps_low", "fps_low01")
INLINE_LABELS = {"fps_avg": "avg", "fps_low": "1%", "fps_low01": "0.1%"}

PADDING = {"sm": 4, "md": 8, "lg": 14}
RADIUS = {"sm": theme.RADIUS_SM, "md": theme.RADIUS, "lg": theme.RADIUS_LG}


class CoreBars(tk.Canvas):
    """Per-core load as a compact grid of tiny bars, like the original tool."""

    def __init__(self, master: tk.Misc, mode: str = "physical", *, scale: float = 1.0,
                 bg: str = theme.BG) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._mode = mode
        self._scale = scale
        self._last: list[float] = []

    def redraw(self, cores: list[float], mode: str | None = None) -> None:
        if mode is not None:
            self._mode = mode
        if not cores:
            if self._last:
                self._last = []
                self.delete("all")
            self.configure(width=170, height=16)
            self.create_text(0, 1, text="CPU: no data", anchor="nw",
                             fill=theme.MUTED, font=theme.ui(theme.FS_CAPTION))
            return
        if self._mode == "physical" and len(cores) >= 2:
            grouped = [max(cores[i], cores[i + 1]) for i in range(0, len(cores) - 1, 2)]
        else:
            grouped = list(cores)
        if grouped == self._last and self.winfo_ismapped():
            return
        self._last = grouped
        self.delete("all")

        font = theme.ui(theme.scaled(theme.FS_CAPTION, self._scale))
        columns = 2
        cell_w, row_h, bar_w = 86, 15, 40
        for index, load in enumerate(grouped):
            r, c = divmod(index, columns)
            x0, y0 = c * cell_w, r * row_h
            self.create_text(x0, y0 + row_h / 2, text=f"C{index}", anchor="w",
                             fill=theme.MUTED, font=font)
            bx = x0 + 24
            self.create_rectangle(bx, y0 + 4, bx + bar_w, y0 + 11,
                                  fill=theme.SURFACE_3, outline="")
            frac = max(0.0, min(1.0, load / 100.0))
            if frac > 0.02:
                color = theme.OK if load < 60 else (theme.WARN if load < 85 else theme.ERR)
                self.create_rectangle(bx, y0 + 4, bx + bar_w * frac, y0 + 11,
                                      fill=color, outline="")
            self.create_text(bx + bar_w + 4, y0 + row_h / 2, text=f"{load:.0f}",
                             anchor="w", fill=theme.FG_2, font=font)
        self.configure(width=columns * cell_w,
                       height=((len(grouped) + columns - 1) // columns) * row_h)


class Overlay:
    """Two stacked topmost windows: the container panel and the opaque values."""

    def __init__(self, master: tk.Misc, config: Config, state, on_change=None,
                 series_provider=None) -> None:
        self.master = master
        self.cfg = config
        self.state = state
        self.on_change = on_change
        self.series_provider = series_provider

        self._key = "#010203"
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._topmost_checked = 0.0
        self._graph: FrameTimeGraph | None = None
        self._graph_tick = 0
        self._proc: tk.Label | None = None
        self._hero: tk.Label | None = None
        self._inline: tk.Label | None = None
        self._rows: dict[str, tuple[tk.Label, tk.Label]] = {}
        self._last: dict[str, str] = {}
        self._cores: CoreBars | None = None
        self._hwnds: list[int] = []
        self._last_size: tuple[int, int] | None = None

        self.panel = tk.Toplevel(master)
        self.hud = tk.Toplevel(master)
        for window in (self.panel, self.hud):
            window.withdraw()
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            try:
                window.attributes("-transparentcolor", self._key)
            except tk.TclError:
                pass
            window.configure(bg=self._key)

        self._panel_canvas = tk.Canvas(self.panel, bg=self._key, highlightthickness=0, bd=0)
        self._panel_canvas.pack(fill="both", expand=True)

        self._body = tk.Frame(self.hud, bg=self._key)
        self._body.pack(fill="both", expand=True)

        self.rebuild()
        self.apply_settings()
        if config.overlay_enabled:
            self.show()

    # ------------------------------------------------------------------ #
    def _paint_panel(self, width: int, height: int) -> None:
        canvas = self._panel_canvas
        canvas.delete("all")
        if not self.cfg.overlay_container:
            self.panel.withdraw()
            return
        radius = RADIUS.get(self.cfg.overlay_radius, theme.RADIUS_LG)
        outline = theme.BORDER_STRONG if self.cfg.overlay_border else ""
        widgets.round_rect(canvas, 0, 0, width - 1, height - 1, radius,
                           fill=self.cfg.overlay_container_color, outline=outline, width=1)
        canvas.configure(width=width, height=height)
        self.panel.attributes("-alpha", max(0.05, min(1.0, self.cfg.overlay_container_alpha)))
        # visibility is owned by show()/hide(), not by a repaint

    # ------------------------------------------------------------------ #
    def rebuild(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        self._rows.clear()
        self._last.clear()
        self._proc = None
        self._graph = None
        self._cores = None
        self._hero = None
        self._inline = None

        scale = self.cfg.overlay_scale
        key = self._key
        inner = theme.scaled(PADDING.get(self.cfg.overlay_padding, 8), scale)
        self._body.configure(bg=key, padx=inner, pady=inner)

        rows = list(self.cfg.overlay_rows)
        inline = [k for k in INLINE_FPS if k in rows and self.cfg.overlay_fps_inline]
        body_rows = [k for k in rows if k != "fps" and k not in INLINE_FPS]

        row = 0
        if self.cfg.overlay_show_header:
            header = tk.Frame(self._body, bg=key)
            header.grid(row=row, column=0, columnspan=2, sticky="ew")
            tk.Label(header, text="FPS MONITOR", bg=key,
                     fg=self.cfg.overlay_header_color or theme.ACCENT,
                     font=theme.ui(theme.scaled(theme.FS_CAPTION, scale), "bold"),
                     ).pack(side="left")
            self._proc = tk.Label(header, text="", bg=key, fg=theme.MUTED,
                                  font=theme.ui(theme.scaled(theme.FS_CAPTION, scale)))
            self._proc.pack(side="right")
            row += 1
            tk.Frame(self._body, bg=theme.BORDER, height=1).grid(
                row=row, column=0, columnspan=2, sticky="ew",
                pady=(theme.scaled(3, scale), theme.scaled(4, scale)))
            row += 1

        if "fps" in rows:
            hero = tk.Frame(self._body, bg=key)
            hero.grid(row=row, column=0, columnspan=2, sticky="w")
            self._hero = tk.Label(hero, text="--", bg=key,
                                  fg=self.cfg.overlay_fps_color or color_of("fps"),
                                  font=theme.mono(theme.scaled(22, scale), "bold"))
            self._hero.pack(side="left")
            tk.Label(hero, text="FPS", bg=key, fg=theme.MUTED,
                     font=theme.ui(theme.scaled(theme.FS_BODY, scale))).pack(
                side="left", padx=(3, 0), pady=(6, 0))
            if inline:
                self._inline = tk.Label(hero, text="", bg=key, fg=theme.FG_2,
                                        font=theme.mono(theme.scaled(theme.FS_SMALL, scale)))
                self._inline.pack(side="left", padx=(theme.scaled(10, scale), 0))
            row += 1

        def separator() -> None:
            nonlocal row
            tk.Frame(self._body, bg=theme.BORDER, height=1).grid(
                row=row, column=0, columnspan=2, sticky="ew",
                pady=(theme.scaled(2, scale), theme.scaled(2, scale)))
            row += 1

        first_body = True
        for key_name in body_rows:
            if self.cfg.overlay_separators and not first_body:
                separator()
            first_body = False

            if key_name == "frame_graph":
                self._graph = FrameTimeGraph(
                    self._body, window_s=self.cfg.overlay_graph_window_s, scale="60",
                    compact=True, bg=key,
                    width=theme.scaled(150, scale), height=theme.scaled(30, scale),
                )
                self._graph.grid(row=row, column=0, columnspan=2, sticky="ew",
                                 pady=(theme.scaled(2, scale), theme.scaled(2, scale)))
                row += 1
                continue
            if key_name == "cores":
                self._cores = CoreBars(self._body, mode=self.cfg.overlay_cores_mode,
                                       scale=scale, bg=key)
                self._cores.grid(row=row, column=0, columnspan=2, sticky="w",
                                 pady=(theme.scaled(3, scale), theme.scaled(3, scale)))
                row += 1
                continue

            value_size = 13 if key_name in EMPHASIS else 10
            name = tk.Label(
                self._body,
                text=label_of(key_name) if self.cfg.overlay_labels else "",
                bg=key, fg=self.cfg.overlay_label_color or theme.MUTED,
                font=theme.ui(theme.scaled(value_size, scale)), anchor="w",
            )
            value = tk.Label(
                self._body, text="--", bg=key,
                fg=self.cfg.overlay_value_color or color_of(key_name),
                font=theme.mono(theme.scaled(value_size, scale), "bold"), anchor="e",
            )
            padx = theme.scaled(12, scale) if self.cfg.overlay_labels else 0
            pady = theme.scaled(1, scale)
            name.grid(row=row, column=0, sticky="w", padx=(0, padx), pady=pady)
            value.grid(row=row, column=1, sticky="e", pady=pady)
            self._rows[key_name] = (name, value)
            row += 1

        self._body.grid_columnconfigure(1, weight=1)
        self._bind_drag(self._body)
        self.place()

    # ------------------------------------------------------------------ #
    def apply_settings(self) -> None:
        self.rebuild()
        self.apply_click_through()
        if self.cfg.overlay_enabled:
            self.show()
        else:
            self.hide()

    def apply_container(self) -> None:
        """Re-paint the backdrop without rebuilding the values."""
        self.place()
        if self.cfg.overlay_enabled:
            self.show()

    def show(self) -> None:
        self.place()
        self.panel.attributes("-topmost", True)
        self.hud.attributes("-topmost", True)
        self.hud.deiconify()
        if self.cfg.overlay_container:
            self.panel.deiconify()
        self.hud.lift()
        self._hwnds = []
        self.master.after(60, self.apply_click_through)
        self._assert_topmost()

    def _assert_topmost(self) -> None:
        """Bump both windows back above any game that pushed itself on top."""
        for hwnd in self._hwnds or self._collect_hwnds():
            try:
                winutil.raise_topmost(hwnd)
            except Exception:
                pass

    def hide(self) -> None:
        self.hud.withdraw()
        self.panel.withdraw()

    def toggle(self) -> None:
        self.cfg.overlay_enabled = not self.cfg.overlay_enabled
        self.apply_settings()
        self._persist()

    def toggle_click_through(self) -> None:
        self.cfg.overlay_click_through = not self.cfg.overlay_click_through
        self.apply_click_through()
        self._persist()

    # ------------------------------------------------------------------ #
    def apply_click_through(self) -> None:
        for hwnd in self._hwnds or self._collect_hwnds():
            try:
                winutil.set_click_through(hwnd, self.cfg.overlay_click_through)
            except Exception:
                pass

    def _collect_hwnds(self) -> list[int]:
        result = []
        for window in (self.panel, self.hud):
            try:
                window.update_idletasks()
                inner = window.winfo_id()
                parent = winutil.user32.GetParent(inner)
                result.append(parent or inner)
            except Exception:
                pass
        self._hwnds = result
        return result

    # ------------------------------------------------------------------ #
    def place(self) -> None:
        self.hud.update_idletasks()
        width = self._body.winfo_reqwidth()
        height = self._body.winfo_reqheight()
        self._last_size = (width, height)
        screen_w, screen_h = winutil.virtual_screen_size()
        x, y = self.cfg.overlay_x, self.cfg.overlay_y
        corner = self.cfg.overlay_corner
        if corner == "top-right":
            x = screen_w - width - x
        elif corner == "bottom-left":
            y = screen_h - height - y
        elif corner == "bottom-right":
            x = screen_w - width - x
            y = screen_h - height - y
        x, y = max(0, x), max(0, y)
        # the body already carries its own padding (overlay_padding), so the
        # container hugs the values exactly instead of adding a second margin
        self.hud.geometry(f"{width}x{height}+{x}+{y}")
        self.panel.geometry(f"{width}x{height}+{x}+{y}")
        self._paint_panel(width, height)

    def _fit_if_needed(self) -> None:
        """The values change length as data arrives; keep the container fitted."""
        if not self.cfg.overlay_enabled:
            return
        self.hud.update_idletasks()
        size = (self._body.winfo_reqwidth(), self._body.winfo_reqheight())
        if size != getattr(self, "_last_size", None):
            self.place()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        values, text, _ = self.state.snapshot()

        # Games that run in borderless fullscreen still push themselves to the
        # top of the Z-order when they take focus, so the topmost flag is
        # re-asserted every half second (Win32 SetWindowPos, no focus steal).
        if time.monotonic() - self._topmost_checked > 0.5:
            self._topmost_checked = time.monotonic()
            if self.cfg.overlay_enabled and self.hud.winfo_viewable():
                self._assert_topmost()

        if self._proc is not None:
            name = text.get("proc_text") or "no active app"
            if self._last.get("__proc") != name:
                self._proc.configure(text=name)
                self._last["__proc"] = name

        if self._hero is not None:
            fps = values.get("fps")
            rendered = f"{fps:.0f}" if fps is not None else "--"
            if self._last.get("fps") != rendered:
                self._hero.configure(
                    text=rendered,
                    fg=self.cfg.overlay_fps_color or value_color("fps", fps),
                )
                self._last["fps"] = rendered

        if self._inline is not None:
            parts = []
            for key_name in INLINE_FPS:
                if key_name not in self.cfg.overlay_rows:
                    continue
                value = values.get(key_name)
                parts.append(f"{INLINE_LABELS[key_name]} {value:.0f}"
                             if value is not None else f"{INLINE_LABELS[key_name]} --")
            line = "   ".join(parts)
            if self._last.get("__inline") != line:
                self._inline.configure(text=line)
                self._last["__inline"] = line

        for key_name, (_, value_label) in self._rows.items():
            rendered = format_value(key_name, values, text) or "--"
            fg = self.cfg.overlay_value_color or value_color(key_name, values.get(key_name))
            if self._last.get(key_name) != rendered or self._last.get(key_name + "!fg") != fg:
                value_label.configure(text=rendered, fg=fg)
                self._last[key_name] = rendered
                self._last[key_name + "!fg"] = fg

        if self._cores is not None:
            self._cores.redraw(self.state.cores(), self.cfg.overlay_cores_mode)

        if self._graph is not None and self.series_provider is not None:
            self._graph_tick += 1
            if self._graph_tick % 2 == 0:
                try:
                    self._graph.redraw(
                        self.series_provider(self.cfg.overlay_graph_window_s), None
                    )
                except Exception:
                    pass

        # never re-fit mid-drag, but otherwise keep the container snug
        if self._drag_origin is None:
            self._fit_if_needed()

    # ------------------------------------------------------------------ #
    def _persist(self) -> None:
        self.cfg.save()
        if self.on_change:
            self.on_change()

    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_end)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _drag_start(self, event) -> None:
        if self.cfg.overlay_click_through:
            return
        self._drag_origin = (event.x_root, event.y_root,
                             self.hud.winfo_x(), self.hud.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_origin is None or self.cfg.overlay_click_through:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        new_x = win_x + event.x_root - start_x
        new_y = win_y + event.y_root - start_y
        self.hud.geometry(f"+{new_x}+{new_y}")
        self.panel.geometry(f"+{new_x}+{new_y}")

    def _drag_end(self, event) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        self.cfg.overlay_corner = "custom"
        self.cfg.overlay_x = max(0, self.hud.winfo_x())
        self.cfg.overlay_y = max(0, self.hud.winfo_y())
        self._persist()
