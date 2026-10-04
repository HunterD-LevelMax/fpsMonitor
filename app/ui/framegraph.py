"""Frame time graph, drawn on a Canvas - no plotting dependency.

Kept deliberately close to what RTSS / CapFrameX / MSI Afterburner show:

* one point per *frame* (not per sample), so single long frames stay visible;
* several frames sharing one pixel column collapse to the worst one - spikes are
  never averaged away;
* dashed reference lines at 60 and 30 FPS;
* segments coloured by severity (green / amber / red).
"""

from __future__ import annotations

import tkinter as tk

from . import theme

PERIOD_60 = 1000.0 / 60.0  # 16.67 ms
PERIOD_30 = 1000.0 / 30.0  # 33.33 ms

GREEN = "#4ade80"
AMBER = "#fbbf24"
RED = "#f87171"


def nice_ceiling(value: float) -> float:
    """Round up to something a human would put on an axis."""
    if value <= 0:
        return 1.0
    for candidate in (5, 10, 16.7, 20, 25, 33.3, 40, 50, 66.7, 80, 100, 150, 200, 300):
        if value <= candidate:
            return candidate
    return float(int(value / 100 + 1) * 100)


def nice_fps(value: float) -> float:
    """FPS ceilings that match how people think about frame rates."""
    for candidate in (30.0, 60.0, 75.0, 100.0, 120.0, 144.0, 165.0, 200.0, 240.0, 300.0,
                      360.0, 480.0):
        if value <= candidate:
            return candidate
    return float(int(value / 60 + 1) * 60)


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * share)))
    return ordered[index]


class FrameTimeGraph(tk.Canvas):
    def __init__(self, master: tk.Misc, window_s: int = 10, mode: str = "frametime",
                 scale: str = "auto", compact: bool = False, height: int = 220,
                 **kwargs) -> None:
        bg = kwargs.pop("bg", theme.PANEL if not compact else theme.BG)
        super().__init__(
            master,
            bg=bg,
            highlightthickness=0 if compact else 1,
            highlightbackground=theme.BORDER,
            height=height,
            **kwargs,
        )
        self.window_s = max(1, int(window_s))
        self.mode = mode          # frametime | fps
        self.scale_mode = scale   # auto | 60 | 30
        self.compact = compact

    # ------------------------------------------------------------------ #
    def configure_graph(self, window_s: int | None = None, mode: str | None = None,
                        scale: str | None = None) -> None:
        if window_s is not None:
            self.window_s = max(1, int(window_s))
        if mode is not None:
            self.mode = mode
        if scale is not None:
            self.scale_mode = scale

    # ------------------------------------------------------------------ #
    def redraw(self, series: list[tuple[float, float]], stats: dict | None = None) -> None:
        """``series`` is [(seconds_relative_to_now, frametime_ms)] oldest first."""
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 40 or height < 24:
            return

        if self.compact:
            pad_l, pad_r, pad_t, pad_b = 3, 3, 7, 5
        else:
            pad_l, pad_r, pad_t, pad_b = 44, 10, 22, 20
        plot_w = max(8, width - pad_l - pad_r)
        plot_h = max(8, height - pad_t - pad_b)

        ceiling = self._ceiling(series)
        if ceiling is None:
            if self.compact:
                # keep the frame and the 60 fps guide visible so the HUD area
                # still reads as a graph before a game starts
                self._draw_grid(pad_l, pad_t, plot_w, plot_h, PERIOD_60 * 2)
                self.create_text(pad_l + 6, pad_t + plot_h / 2, text="--", anchor="w",
                                 fill=theme.DISABLED, font=theme.ui(7))
            else:
                self.create_text(
                    pad_l, height / 2,
                    text="нет данных: нужен запуск от администратора",
                    anchor="w", fill=theme.MUTED, font=theme.ui(9),
                )
            return

        self._draw_grid(pad_l, pad_t, plot_w, plot_h, ceiling)
        self._draw_series(series, pad_l, pad_t, plot_w, plot_h, ceiling)
        if not self.compact:
            self._draw_legend(stats or {}, width, pad_l, pad_t)

    # ------------------------------------------------------------------ #
    def _ceiling(self, series: list[tuple[float, float]]) -> float | None:
        if not series:
            return None
        values = [self._convert(value) for _, value in series]
        if self.scale_mode == "60":
            return 75.0 if self.mode == "fps" else PERIOD_60 * 2
        if self.scale_mode == "30":
            return 40.0 if self.mode == "fps" else PERIOD_30 * 2

        # Auto: scale to a high percentile instead of the maximum, otherwise a
        # single 100 ms hitch squashes the whole graph into a flat line.
        typical = percentile(values, 0.95)
        middle = percentile(values, 0.5)
        if self.mode == "fps":
            return max(75.0, nice_fps(max(typical * 1.05, middle * 1.15)))
        target = max(typical * 1.35, middle * 2.5, 20.0)
        if target > 120.0:  # never let one spike decide the whole scale
            target = min(target, middle * 6.0)
        return nice_ceiling(target)

    def _convert(self, frametime_ms: float) -> float:
        if self.mode == "fps":
            return 1000.0 / frametime_ms if frametime_ms > 0 else 0.0
        return frametime_ms

    def _draw_grid(self, pad_l: int, pad_t: int, plot_w: int, plot_h: int, ceiling: float) -> None:
        for step in range(1, 5):
            x = pad_l + plot_w * step / 5
            self.create_line(x, pad_t, x, pad_t + plot_h, fill=theme.GRID)
        for step in range(5):
            y = pad_t + plot_h * step / 4
            self.create_line(pad_l, y, pad_l + plot_w, y, fill=theme.GRID)

        guides = ([(60.0, GREEN), (30.0, AMBER)] if self.mode == "fps"
                  else ([(PERIOD_60, GREEN)] if self.compact
                        else [(PERIOD_60, GREEN), (PERIOD_30, AMBER)]))
        for value, colour in guides:
            if value > ceiling:
                continue
            y = pad_t + plot_h * (1.0 - value / ceiling)
            self.create_line(pad_l, y, pad_l + plot_w, y, fill=colour, dash=(3, 5), width=1)
            if not self.compact:
                self.create_text(
                    pad_l - 4, y, text=f"{value:.0f}", anchor="e",
                    fill=colour, font=theme.ui(7),
                )

        if not self.compact:
            # a couple of axis numbers so the height of the graph is readable
            unit = "FPS" if self.mode == "fps" else "мс"
            for fraction in (0.0, 0.5, 1.0):
                y = pad_t + plot_h * (1.0 - fraction)
                self.create_text(
                    pad_l - 4, y, text=f"{ceiling * fraction:.0f}", anchor="e",
                    fill=theme.MUTED, font=theme.ui(7),
                )
            self.create_text(
                pad_l + plot_w, pad_t + plot_h + 4,
                text=f"-{self.window_s} с", anchor="e",
                fill=theme.MUTED, font=theme.ui(7),
            )
            self.create_text(
                pad_l + 2, pad_t + plot_h + 4, text=unit, anchor="w",
                fill=theme.MUTED, font=theme.ui(7),
            )

    def _bucket(self, series: list[tuple[float, float]], plot_w: int) -> list[float | None]:
        """Worst frame per pixel column - gaps stay gaps."""
        columns: list[float | None] = [None] * plot_w
        span = float(self.window_s)
        for x, frametime in series:
            position = int((x + span) / span * plot_w)
            if position < 0:
                continue
            if position >= plot_w:
                position = plot_w - 1
            value = self._convert(frametime)
            current = columns[position]
            if current is None or value > current:
                columns[position] = value
        return columns

    def _draw_series(self, series: list[tuple[float, float]], pad_l: int, pad_t: int,
                     plot_w: int, plot_h: int, ceiling: float) -> None:
        columns = self._bucket(series, plot_w)
        previous: tuple[float, float] | None = None
        previous_value = 0.0
        for index, value in enumerate(columns):
            if value is None:
                previous = None  # a gap: do not connect across missing frames
                continue
            x = pad_l + index
            y = pad_t + plot_h * (1.0 - min(1.0, max(0.0, value / ceiling)))
            if previous is not None:
                self.create_line(
                    previous[0], previous[1], x, y,
                    fill=self._colour(previous_value, value), width=1,
                )
            previous = (x, y)
            previous_value = value

    def _colour(self, first: float, second: float) -> str:
        worst = max(first, second)
        if self.mode == "fps":
            if worst >= 60:
                return GREEN
            if worst >= 30:
                return AMBER
            return RED
        if worst <= PERIOD_60 * 1.05:
            return GREEN
        if worst <= PERIOD_30:
            return AMBER
        return RED

    def _draw_legend(self, stats: dict, width: int, pad_l: int, pad_t: int) -> None:
        if self.mode == "fps":
            text = "FPS по кадрам"
        else:
            text = "Время кадра, мс"
        self.create_text(pad_l, pad_t - 8, text=text, anchor="w", fill=theme.FG,
                         font=theme.ui(8, "bold"))

        parts: list[str] = []
        if stats.get("avg"):
            parts.append(f"сред {stats['avg']:.1f}")
        if stats.get("min"):
            parts.append(f"мин {stats['min']:.1f}")
        if stats.get("max"):
            parts.append(f"макс {stats['max']:.1f}")
        if stats.get("samples"):
            parts.append(f"кадров {int(stats['samples'])}")
        if parts:
            self.create_text(width - 10, pad_t - 8, text="  ·  ".join(parts), anchor="e",
                             fill=theme.MUTED, font=theme.ui(8))
