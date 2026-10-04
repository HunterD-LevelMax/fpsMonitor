"""The always-on-top HUD that sits over games."""

from __future__ import annotations

import time
import tkinter as tk

from .. import winutil
from ..config import Config
from ..metrics import color_of, format_value, label_of
from . import theme, widgets
from .framegraph import FrameTimeGraph

EMPHASIS = {"fps", "frametime"}


class Overlay(tk.Toplevel):
    def __init__(self, master: tk.Misc, config: Config, state, on_change=None,
                 series_provider=None) -> None:
        super().__init__(master)
        self.cfg = config
        self.state = state
        self.on_change = on_change
        self.series_provider = series_provider
        self._hwnd: int | None = None
        self._rows: dict[str, tuple[tk.Label, tk.Label]] = {}
        self._last: dict[str, str] = {}
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._topmost_checked = 0.0
        self._graph: FrameTimeGraph | None = None
        self._graph_tick = 0

        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # Chroma key trick: the area outside the rounded card becomes fully
        # transparent, so the HUD looks like a floating panel instead of a
        # rectangle pasted over the game.
        self._key = "#010203"
        try:
            self.attributes("-transparentcolor", self._key)
        except tk.TclError:
            self._key = theme.BG
        self.configure(bg=self._key)
        self._shell = tk.Canvas(self, bg=self._key, highlightthickness=0, bd=0)
        self._shell.pack(fill="both", expand=True)
        self._body = tk.Frame(self._shell, bg=theme.SURFACE)
        self._window = self._shell.create_window(8, 8, window=self._body, anchor="nw")
        self._body.bind("<Configure>", lambda _e: self._paint_shell())

        self.rebuild()
        self.apply_settings()
        if config.overlay_enabled:
            self.show()

    def _paint_shell(self) -> None:
        self._shell.delete("card")
        width = max(4, self._body.winfo_reqwidth() + 16)
        height = max(4, self._body.winfo_reqheight() + 16)
        widgets.round_rect(self._shell, 0, 0, width - 1, height - 1, theme.RADIUS_LG,
                           fill=theme.SURFACE, outline=theme.BORDER, width=1, tags="card")
        self._shell.tag_lower("card")
        self._shell.configure(width=width, height=height)

    # ------------------------------------------------------------------ #
    def rebuild(self) -> None:
        """Recreate the row widgets from the current configuration."""
        for child in self._body.winfo_children():
            child.destroy()
        self._rows.clear()
        self._last.clear()
        self._proc: tk.Label | None = None
        self._graph = None

        surface = theme.SURFACE
        scale = self.cfg.overlay_scale
        pad = theme.scaled(4, scale)
        self._body.configure(bg=surface, padx=theme.scaled(10, scale),
                             pady=theme.scaled(8, scale))

        row = 0
        if self.cfg.overlay_show_header:
            header = tk.Frame(self._body, bg=surface)
            header.grid(row=row, column=0, columnspan=2, sticky="ew")
            tk.Label(
                header, text="FPS MONITOR", bg=surface, fg=theme.ACCENT,
                font=theme.ui(theme.scaled(theme.FS_CAPTION, scale), "bold"),
            ).pack(side="left")
            self._proc = tk.Label(
                header, text="", bg=surface, fg=theme.MUTED,
                font=theme.ui(theme.scaled(theme.FS_CAPTION, scale)),
            )
            self._proc.pack(side="right")
            row += 1
            divider = tk.Frame(self._body, bg=theme.BORDER, height=1)
            divider.grid(row=row, column=0, columnspan=2, sticky="ew",
                         pady=(theme.scaled(4, scale), theme.scaled(6, scale)))
            row += 1

        for key in self.cfg.overlay_rows:
            if key == "frame_graph":
                self._graph = FrameTimeGraph(
                    self._body,
                    window_s=self.cfg.overlay_graph_window_s,
                    scale="60",  # a 33 ms ceiling keeps typical 60-240 fps readable
                    compact=True,
                    width=theme.scaled(160, scale),
                    height=theme.scaled(34, scale),
                )
                self._graph.grid(row=row, column=0, columnspan=2, sticky="ew",
                                 pady=(pad, pad))
                row += 1
                continue

            if key == "fps":
                value_size, label_size = 22, theme.FS_SMALL
            elif key in EMPHASIS:
                value_size, label_size = 13, theme.FS_SMALL
            else:
                value_size, label_size = 10, theme.FS_SMALL
            name = tk.Label(
                self._body, text=label_of(key), bg=surface, fg=theme.MUTED,
                font=theme.ui(theme.scaled(label_size, scale)), anchor="w",
            )
            value = tk.Label(
                self._body, text="--", bg=surface, fg=color_of(key),
                font=theme.mono(theme.scaled(value_size, scale), "bold"), anchor="e",
            )
            name.grid(row=row, column=0, sticky="w", padx=(0, theme.scaled(14, scale)),
                      pady=1)
            value.grid(row=row, column=1, sticky="e", pady=1)
            self._rows[key] = (name, value)
            row += 1

        self._bind_drag(self._body)
        self.place()
        self._paint_shell()

    # ------------------------------------------------------------------ #
    def apply_settings(self) -> None:
        self.attributes("-alpha", max(0.15, min(1.0, self.cfg.overlay_alpha)))
        self.place()
        self.apply_click_through()
        if self.cfg.overlay_enabled:
            self.show()
        else:
            self.hide()

    def show(self) -> None:
        self.deiconify()
        self.attributes("-topmost", True)
        self.place()
        self._hwnd = None
        self.after(60, self.apply_click_through)

    def hide(self) -> None:
        self.withdraw()

    def toggle(self) -> None:
        self.cfg.overlay_enabled = not self.cfg.overlay_enabled
        self.apply_settings()
        self._persist()

    def toggle_click_through(self) -> None:
        self.cfg.overlay_click_through = not self.cfg.overlay_click_through
        self.apply_click_through()
        self._persist()

    # ------------------------------------------------------------------ #
    def hwnd(self) -> int:
        if self._hwnd:
            return self._hwnd
        self.update_idletasks()
        inner = self.winfo_id()
        parent = winutil.user32.GetParent(inner)
        self._hwnd = parent or inner
        return self._hwnd

    def apply_click_through(self) -> None:
        try:
            winutil.set_click_through(self.hwnd(), self.cfg.overlay_click_through)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def place(self) -> None:
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_w, screen_h = winutil.virtual_screen_size()
        offset_x, offset_y = self.cfg.overlay_x, self.cfg.overlay_y
        corner = self.cfg.overlay_corner
        x, y = offset_x, offset_y
        if corner == "top-right":
            x = screen_w - width - offset_x
        elif corner == "bottom-left":
            y = screen_h - height - offset_y
        elif corner == "bottom-right":
            x = screen_w - width - offset_x
            y = screen_h - height - offset_y
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        values, text, _ = self.state.snapshot()
        # Games like to push other topmost windows down when they take focus,
        # so the topmost flag is re-asserted every few seconds.
        if time.monotonic() - self._topmost_checked > 4.0:
            self._topmost_checked = time.monotonic()
            if self.cfg.overlay_enabled and self.winfo_viewable():
                try:
                    self.attributes("-topmost", True)
                except tk.TclError:
                    pass
        if self._proc is not None:
            name = text.get("proc_text") or "нет активного приложения"
            if self._last.get("__proc") != name:
                self._proc.configure(text=name)
                self._last["__proc"] = name
        for key, (_, value_label) in self._rows.items():
            rendered = format_value(key, values, text) or "--"
            if self._last.get(key) != rendered:
                value_label.configure(text=rendered)
                self._last[key] = rendered

        if self._graph is not None and self.series_provider is not None:
            # the sparkline is redrawn on every second tick: frametime graphs are
            # dense, and 2 Hz is plenty for a HUD
            self._graph_tick += 1
            if self._graph_tick % 2 == 0:
                try:
                    self._graph.redraw(
                        self.series_provider(self.cfg.overlay_graph_window_s), None
                    )
                except Exception:
                    pass

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
        self._drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_origin is None or self.cfg.overlay_click_through:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        self.geometry(f"+{win_x + event.x_root - start_x}+{win_y + event.y_root - start_y}")

    def _drag_end(self, event) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        self.cfg.overlay_corner = "custom"
        self.cfg.overlay_x = max(0, self.winfo_x())
        self.cfg.overlay_y = max(0, self.winfo_y())
        self._persist()
