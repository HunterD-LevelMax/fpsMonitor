"""A small canvas line chart - no external plotting dependency."""

from __future__ import annotations

import time
import tkinter as tk

from ..metrics import METRIC_BY_KEY, color_of, label_of
from . import theme


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    step = 10 ** (len(str(int(value))) - 1)
    for factor in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        candidate = step * factor
        if value <= candidate:
            return candidate
    return step * 10


class Graph(tk.Canvas):
    def __init__(self, master: tk.Misc, state, keys: list[str], window_s: int = 120,
                 height: int = 130, **kwargs) -> None:
        super().__init__(
            master,
            bg=theme.PANEL,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            height=height,
            **kwargs,
        )
        self.state = state
        self.keys = list(keys)
        self.window_s = window_s

    def set_keys(self, keys: list[str]) -> None:
        self.keys = list(keys)

    def set_window(self, seconds: int) -> None:
        self.window_s = max(10, int(seconds))

    # ------------------------------------------------------------------ #
    def redraw(self, values: dict, text: dict) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 60 or height < 40:
            return

        pad_l, pad_r, pad_t, pad_b = 8, 8, 20, 14
        plot_w = max(10, width - pad_l - pad_r)
        plot_h = max(10, height - pad_t - pad_b)
        now = time.time()
        start = now - self.window_s

        for step in range(5):
            y = pad_t + plot_h * step / 4
            self.create_line(pad_l, y, pad_l + plot_w, y, fill=theme.GRID)
        self.create_text(
            pad_l + plot_w, pad_t + plot_h + 4,
            text=f"-{self.window_s}s",
            anchor="e",
            fill=theme.MUTED,
            font=theme.ui(7),
        )

        legend_x = pad_l + 2
        for key in self.keys:
            points = self.state.history(key, self.window_s)
            metric = METRIC_BY_KEY.get(key)
            colour = color_of(key)

            current = values.get(key)
            legend = label_of(key)
            if current is not None:
                digits = metric.decimals if metric else 0
                legend = f"{legend} {current:.{digits}f}"
                if metric and metric.unit:
                    legend = f"{legend}{metric.unit}"
            self.create_text(
                legend_x, pad_t - 11, text=legend, anchor="w", fill=colour, font=theme.ui(8, "bold")
            )
            legend_x += 7 * len(legend) + 12

            if len(points) < 2:
                continue
            peak = max(value for _, value in points)
            ceiling = nice_max(peak)
            # numeric guides are only useful for the first series
            if key == self.keys[0]:
                self.create_text(
                    pad_l + plot_w - 2, pad_t - 11,
                    text=f"max {ceiling:.0f}",
                    anchor="e",
                    fill=theme.MUTED,
                    font=theme.ui(8),
                )
            coords: list[float] = []
            for stamp, value in points:
                x = pad_l + plot_w * min(1.0, max(0.0, (stamp - start) / self.window_s))
                y = pad_t + plot_h * (1.0 - min(1.0, max(0.0, value / ceiling)))
                coords.extend((x, y))
            self.create_line(*coords, fill=colour, width=2, smooth=True, capstyle="round")
