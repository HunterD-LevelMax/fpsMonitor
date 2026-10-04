"""Main window: sidebar navigation, cards and live data.

Layout follows current dashboard practice: a sidebar instead of tabs, one
accent colour, layered neutral surfaces, uppercase micro-labels, KPI tiles for
the numbers that matter and status pills instead of plain text.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import __version__
from ..config import APP_DIR, LOG_DIR, Config
from ..metrics import (
    METRICS,
    METRIC_BY_KEY,
    OVERLAY_CHOICES,
    color_of,
    format_value,
    label_of,
    threshold_state,
    value_color,
)
from ..sources.lhm import default_stage_dir, is_elevated
from . import theme, widgets
from .framegraph import FrameTimeGraph
from .graph import Graph
from .overlay import Overlay

CORNER_GLYPHS = [("top-left", "↖"), ("top-right", "↗"),
                 ("bottom-left", "↙"), ("bottom-right", "↘")]

CORNERS = [
    ("top-left", "Слева в."),
    ("top-right", "Справа в."),
    ("bottom-left", "Слева н."),
    ("bottom-right", "Справа н."),
    ("custom", "Своё"),
]

SENSOR_COLUMNS: list[tuple[str, list[str]]] = [
    ("Кадры", ["fps", "fps_low", "fps_low01", "frametime", "frametime_min",
               "frametime_max", "frametime_display", "stutters", "frames_window"]),
    ("Процессор", ["cpu_load", "cpu_temp", "cpu_clock", "cpu_power", "ram_load", "ram_used"]),
    ("Видеокарта", ["gpu_load", "gpu_temp", "gpu_hotspot", "gpu_vram", "gpu_power",
                    "gpu_clock", "gpu_fan"]),
    ("Приложение", ["proc_text", "proc_cpu"]),
]


def style_ttk() -> None:
    """Flat, dark ttk styling for the few native widgets that remain."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "TCombobox", fieldbackground=theme.SURFACE_2, background=theme.SURFACE_2,
        foreground=theme.FG, arrowcolor=theme.MUTED, bordercolor=theme.BORDER,
        lightcolor=theme.SURFACE_2, darkcolor=theme.SURFACE_2, padding=5,
        selectbackground=theme.SURFACE_2, selectforeground=theme.FG,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", theme.SURFACE_2)],
        selectbackground=[("readonly", theme.SURFACE_2)],
        selectforeground=[("readonly", theme.FG)],
    )
    style.configure(
        "TSpinbox", fieldbackground=theme.SURFACE_2, background=theme.SURFACE_2,
        foreground=theme.FG, arrowcolor=theme.MUTED, bordercolor=theme.BORDER,
        lightcolor=theme.SURFACE_2, darkcolor=theme.SURFACE_2, padding=4,
        insertcolor=theme.FG,
    )
    style.configure("TFrame", background=theme.BG)
    style.configure("TButton", background=theme.SURFACE_2, foreground=theme.FG,
                    borderwidth=0, padding=(10, 5))
    style.map("TButton", background=[("active", theme.SURFACE_3)])


class Dashboard:
    def __init__(self, root: tk.Tk, config: Config, state, sampler, overlay: Overlay,
                 on_quit=None, tray=None) -> None:
        self.root = root
        self.cfg = config
        self.state = state
        self.sampler = sampler
        self.overlay = overlay
        self.on_quit = on_quit
        self.tray = tray

        self._value_rows: dict[str, widgets.StatRow] = {}
        self._kpis: dict[str, widgets.KpiTile] = {}
        self._status_rows: list[tuple[tk.Label, widgets.Pill, str]] = []
        self._proc_index: dict[str, int | None] = {"Авто": None}
        self._proc_at = 0.0
        self._pawnio_busy = False
        self._pawnio_result = ""
        self._pages: dict[str, tk.Frame] = {}
        self._page_titles: dict[str, tuple[str, str]] = {}

        theme.resolve_fonts()
        style_ttk()
        root.configure(bg=theme.BG)
        root.bind_all("<MouseWheel>", self._on_wheel)
        self._build()

    # ================================================================== #
    # shell
    # ================================================================== #
    def _build(self) -> None:
        shell = tk.Frame(self.root, bg=theme.BG)
        shell.pack(fill="both", expand=True, padx=theme.SPACE_4, pady=theme.SPACE_4)

        self._build_sidebar(shell)

        right = tk.Frame(shell, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_4, 0))

        header = tk.Frame(right, bg=theme.BG)
        header.pack(fill="x", pady=(0, theme.SPACE_3))
        titles = tk.Frame(header, bg=theme.BG)
        titles.pack(side="left")
        self._page_title = tk.Label(titles, text="Монитор", bg=theme.BG, fg=theme.FG,
                                    font=theme.ui(theme.FS_H2, "bold"), anchor="w")
        self._page_title.pack(anchor="w")
        self._page_subtitle = tk.Label(titles, text="", bg=theme.BG, fg=theme.MUTED,
                                       font=theme.ui(theme.FS_SMALL), anchor="w")
        self._page_subtitle.pack(anchor="w")
        chips = tk.Frame(header, bg=theme.BG)
        chips.pack(side="right")
        self._chip_admin = widgets.Pill(chips, "ПРАВА", theme.OK, bg=theme.BG)
        self._chip_admin.pack(side="left", padx=(0, theme.SPACE_2))
        self._chip_capture = widgets.Pill(chips, "ЗАХВАТ", theme.OK, bg=theme.BG)
        self._chip_capture.pack(side="left", padx=(0, theme.SPACE_2))
        self._chip_log = widgets.Pill(chips, "ЗАПИСЬ", theme.MUTED, bg=theme.BG)
        self._chip_log.pack(side="left")

        tracker = tk.Frame(header, bg=theme.BG)
        tracker.pack(side="right", padx=(0, theme.SPACE_4))
        tk.Label(tracker, text="ОТСЛЕЖИВАЕМОЕ ПРИЛОЖЕНИЕ", bg=theme.BG, fg=theme.MUTED,
                 font=theme.ui(theme.FS_CAPTION, "bold")).pack(anchor="e")
        self._proc_box = ttk.Combobox(tracker, state="readonly", values=["Авто"], width=34)
        self._proc_box.pack(anchor="e")
        self._proc_box.bind("<<ComboboxSelected>>", self._on_process_selected)

        self._content = tk.Frame(right, bg=theme.BG)
        self._content.pack(fill="both", expand=True)

        self._build_monitor()
        self._build_frames()
        self._build_sensors()
        self._build_overlay_page()
        self._build_settings()
        self._build_diagnostics()
        self.show_page("monitor")

    def _build_sidebar(self, parent: tk.Misc) -> None:
        card = widgets.Surface(parent, fill=theme.SURFACE, padding=theme.SPACE_2,
                               width=198)
        card.pack(side="left", fill="y")

        brand = tk.Frame(card.body, bg=theme.SURFACE)
        brand.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_4))
        tk.Label(brand, text="FPS MONITOR", bg=theme.SURFACE, fg=theme.FG,
                 font=theme.ui(theme.FS_LABEL, "bold")).pack(anchor="w", padx=theme.SPACE_3)
        tk.Label(brand, text=f"версия {__version__}", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.ui(theme.FS_CAPTION)).pack(anchor="w", padx=theme.SPACE_3)

        nav = widgets.SidebarNav(
            card.body,
            [("monitor", "Монитор", "monitor"), ("frames", "Кадры", "frames"),
             ("sensors", "Датчики", "settings"), ("overlay", "Оверлей", "overlay"),
             ("settings", "Настройки", "settings"),
             ("diagnostics", "Диагностика", "diagnostics")],
            on_select=self.show_page,
            bg=theme.SURFACE,
        )
        nav.pack(fill="x")
        self.nav = nav

        footer = tk.Frame(card.body, bg=theme.SURFACE)
        footer.pack(side="bottom", fill="x", pady=theme.SPACE_2)
        widgets.Divider(footer).pack(fill="x", pady=(0, theme.SPACE_3))
        widgets.FlatButton(footer, "Свернуть в оверлей", self.hide_window).pack(
            fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_2))
        widgets.FlatButton(footer, "Выход", self.quit_app, variant="ghost").pack(
            fill="x", padx=theme.SPACE_2)
        tk.Label(footer, text="Ctrl+Alt+M — вернуть окно", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.ui(theme.FS_CAPTION)).pack(pady=(theme.SPACE_2, 0))

    def show_page(self, key: str) -> None:
        for name, page in self._pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        title, subtitle = self._page_titles.get(key, ("", ""))
        self._page_title.configure(text=title)
        self._page_subtitle.configure(text=subtitle)
        if self.nav._active != key:  # noqa: SLF001 - keep the highlight in sync
            self.nav.select(key)

    def _page(self, key: str, title: str, subtitle: str) -> tk.Frame:
        """Create a scrollable page and return the frame to fill with content."""
        scroll = widgets.ScrollPage(self._content, bg=theme.BG)
        self._pages[key] = scroll
        self._page_titles[key] = (title, subtitle)
        return scroll.content

    def _on_wheel(self, event) -> None:
        """Route the mouse wheel to whichever page is under the pointer."""
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, widgets.ScrollPage):
                widget.scroll_by(-1 if event.delta > 0 else 1)
                return
            widget = getattr(widget, "master", None)

    # ================================================================== #
    # pages
    # ================================================================== #
    def _build_monitor(self) -> None:
        page = self._page("monitor", "Монитор",
                          "Текущая производительность и история за последние минуты")

        top = tk.Frame(page, bg=theme.BG)
        top.pack(fill="x")
        top.columnconfigure(0, weight=0)
        for column in range(1, 6):
            top.columnconfigure(column, weight=1)

        hero = widgets.Surface(top, fill=theme.SURFACE, padding=theme.SPACE_4, width=300)
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, theme.SPACE_3))
        tk.Label(hero.body, text="ТЕКУЩИЙ FPS", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.ui(theme.FS_SMALL, "bold"), anchor="w").pack(fill="x")

        hero_row = tk.Frame(hero.body, bg=theme.SURFACE)
        hero_row.pack(fill="x", pady=(theme.SPACE_1, 0))
        self._hero_fps = tk.Label(hero_row, text="--", bg=theme.SURFACE, fg=theme.OK,
                                  font=theme.mono(28, "bold"))
        self._hero_fps.pack(side="left")
        tk.Label(hero_row, text="кадр/с", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.ui(theme.FS_BODY)).pack(side="left", padx=(5, 0), pady=(9, 0))

        self._hero_caption = tk.Label(hero.body, text="", bg=theme.SURFACE, fg=theme.FG_2,
                                      font=theme.mono(theme.FS_SMALL), anchor="w",
                                      justify="left")
        self._hero_caption.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_2))

        self._hero_graph = FrameTimeGraph(hero.body, window_s=30, compact=True,
                                          scale="60", height=30)
        self._hero_graph.pack(fill="x", side="bottom")

        tiles = top
        specs = [
            ("cpu_load", "ЦПУ", "%"), ("cpu_temp", "ЦПУ темп", "°C"),
            ("gpu_load", "ГПУ", "%"), ("gpu_temp", "ГПУ темп", "°C"),
            ("ram_load", "ОЗУ", "%"),
        ]
        for index, (key, label, unit) in enumerate(specs):
            tile = widgets.KpiTile(tiles, label, unit, min_width=118)
            tile.grid(row=0, column=index + 1, sticky="nsew", padx=(0, theme.SPACE_2))
            self._kpis[key] = tile

        graphs = tk.Frame(page, bg=theme.BG)
        graphs.pack(fill="both", expand=True, pady=(theme.SPACE_3, 0))
        plan = [
            ("Кадры, 30 с", ["fps", "frametime"]),
            ("Процессор", ["cpu_load", "cpu_temp"]),
            ("Видеокарта", ["gpu_load", "gpu_temp"]),
        ]
        self.graphs = []
        for index, (title, keys) in enumerate(plan):
            card = widgets.Card(graphs, title, padding=theme.SPACE_3)
            card.pack(side="left", fill="both", expand=True,
                      padx=(0, theme.SPACE_3 if index < len(plan) - 1 else 0))
            graph = Graph(card.content, self.state, keys, self.cfg.graph_window_s, height=150)
            graph.pack(fill="both", expand=True)
            self.graphs.append(graph)

    def _build_frames(self) -> None:
        page = self._page("frames", "Кадры",
                          "График времени кадра: каждая просадка видна отдельно")

        tiles = tk.Frame(page, bg=theme.BG)
        tiles.pack(fill="x")
        specs = [("frametime", "Средний кадр", "мс"), ("frametime_min", "Лучший кадр", "мс"),
                 ("frametime_max", "Худший кадр", "мс"), ("fps_low", "1% low", "FPS"),
                 ("fps_low01", "0.1% low", "FPS"), ("stutters", "Статтеры", "")]
        for index, (key, label, unit) in enumerate(specs):
            tile = widgets.KpiTile(tiles, label, unit, min_width=118)
            tile.grid(row=0, column=index, sticky="nsew",
                      padx=(0, theme.SPACE_2), pady=(theme.SPACE_1, 0))
            tiles.columnconfigure(index, weight=1)
            self._kpis[f"frame_{key}"] = tile

        card = widgets.Card(page, "График времени кадра")
        card.pack(fill="x", pady=(theme.SPACE_3, 0))

        self._frame_window_var = tk.StringVar(value=str(self.cfg.frame_graph_window_s))
        widgets.Segmented(card.header, [("5", "5 с"), ("10", "10 с"), ("30", "30 с"),
                                        ("60", "60 с")],
                          self._frame_window_var, self._on_frame_window,
                          bg=theme.SURFACE_2, fill=theme.SURFACE).pack(side="right")
        self._frame_mode_var = tk.StringVar(value=self.cfg.frame_graph_mode)
        widgets.Segmented(card.header, [("frametime", "Время кадра"), ("fps", "FPS")],
                          self._frame_mode_var, self._on_frame_mode,
                          bg=theme.SURFACE_2, fill=theme.SURFACE).pack(
            side="right", padx=(0, theme.SPACE_2))
        self._frame_scale_var = tk.StringVar(value=self.cfg.frame_graph_scale)
        widgets.Segmented(card.header, [("auto", "Авто"), ("60", "60 Гц"), ("30", "30 Гц")],
                          self._frame_scale_var, self._on_frame_scale,
                          bg=theme.SURFACE_2, fill=theme.SURFACE).pack(
            side="right", padx=(0, theme.SPACE_2))

        self.frame_graph = FrameTimeGraph(card.content, window_s=self.cfg.frame_graph_window_s,
                                          mode=self.cfg.frame_graph_mode,
                                          scale=self.cfg.frame_graph_scale, height=300)
        self.frame_graph.pack(fill="both", expand=True)
        widgets.WrapLabel(
            card.content,
            "Каждый кадр рисуется отдельно; несколько кадров в одном пикселе "
            "схлопываются в худший, поэтому просадки не сглаживаются. "
            "Зелёный пунктир — 60 FPS, янтарный — 30 FPS.",
        ).pack(fill="x", pady=(theme.SPACE_2, 0))

    def _build_sensors(self) -> None:
        page = self._page("sensors", "Датчики", "Все метрики, которые собирает приложение")
        card = widgets.Card(page, "Показания", padding=theme.SPACE_4)
        card.pack(fill="x")
        card.content.columnconfigure(0, weight=1)
        card.content.columnconfigure(1, weight=1)
        card.content.columnconfigure(2, weight=1)

        columns = [
            SENSOR_COLUMNS[0],                       # кадры
            ("Процессор и память", SENSOR_COLUMNS[1][1] + SENSOR_COLUMNS[3][1]),
            SENSOR_COLUMNS[2],                       # видеокарта
        ]
        for index, (title, keys) in enumerate(columns):
            column = tk.Frame(card.content, bg=theme.SURFACE)
            column.grid(row=0, column=index, sticky="nsew",
                        padx=(0, theme.SPACE_5 if index < 2 else 0))
            widgets.SectionTitle(column, title, fill=theme.SURFACE, top=0)
            for key in keys:
                row = widgets.StatRow(column, label_of(key), fill=theme.SURFACE)
                row.pack(fill="x", pady=3)
                self._value_rows[key] = row

    # ------------------------------------------------------------------ #
    # overlay rows: visibility and order
    # ------------------------------------------------------------------ #
    def _redraw_rows_editor(self) -> None:
        holder = self._rows_holder
        for child in holder.winfo_children():
            child.destroy()

        visible = [key for key in self.cfg.overlay_rows if key in OVERLAY_CHOICES]
        if visible != self.cfg.overlay_rows:  # drop unknown keys from old configs
            self.cfg.overlay_rows = visible
            self.cfg.save()

        for index, key in enumerate(visible):
            row = tk.Frame(holder, bg=theme.SURFACE)
            row.pack(fill="x", pady=theme.SPACE_1)

            variable = tk.BooleanVar(value=True)
            widgets.Switch(row, variable, lambda k=key: self._set_row_visible(k, False),
                           bg=theme.SURFACE).pack(side="left")

            tk.Label(row, text=label_of(key), bg=theme.SURFACE, fg=theme.FG,
                     font=theme.ui(theme.FS_BODY), anchor="w").pack(
                side="left", padx=(theme.SPACE_3, 0))

            down = widgets.FlatButton(row, "▼", lambda k=key: self._move_row(k, 1),
                                      width=32, height=24)
            down.pack(side="right")
            up = widgets.FlatButton(row, "▲", lambda k=key: self._move_row(k, -1),
                                    width=32, height=24)
            up.pack(side="right", padx=(0, theme.SPACE_1))
            if index == 0:
                up.set_enabled(False)
            if index == len(visible) - 1:
                down.set_enabled(False)

        hidden = [key for key in OVERLAY_CHOICES if key not in visible]
        if not hidden:
            return
        widgets.Divider(holder).pack(fill="x", pady=(theme.SPACE_3, 0))
        widgets.SectionTitle(holder, "Скрытые", fill=theme.SURFACE)
        grid = tk.Frame(holder, bg=theme.SURFACE)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        for position, key in enumerate(hidden):
            widgets.FlatButton(grid, "+  " + label_of(key),
                               lambda k=key: self._set_row_visible(k, True)).grid(
                row=position // 2, column=position % 2, sticky="ew", padx=2, pady=3)

    def _set_row_visible(self, key: str, visible: bool) -> None:
        rows = [item for item in self.cfg.overlay_rows if item != key]
        if visible:
            rows.append(key)  # новые строки появляются внизу, дальше их можно двигать
        self.cfg.overlay_rows = rows
        self.cfg.save()
        self.overlay.rebuild()
        self._redraw_rows_editor()

    def _move_row(self, key: str, delta: int) -> None:
        rows = list(self.cfg.overlay_rows)
        if key not in rows:
            return
        index = rows.index(key)
        target = max(0, min(len(rows) - 1, index + delta))
        if target == index:
            return
        rows.pop(index)
        rows.insert(target, key)
        self.cfg.overlay_rows = rows
        self.cfg.save()
        self.overlay.rebuild()
        self._redraw_rows_editor()

    def _build_overlay_page(self) -> None:
        page = self._page("overlay", "Оверлей", "Что и как показывать поверх игры")
        left = tk.Frame(page, bg=theme.BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(page, bg=theme.BG)
        right.pack(side="left", fill="both", padx=(theme.SPACE_3, 0))

        rows_card = widgets.Card(left, "Строки оверлея", padding=theme.SPACE_4)
        rows_card.pack(fill="x")
        widgets.WrapLabel(
            rows_card.content,
            "Порядок строк — сверху вниз, как в оверлее. Стрелки перемещают строку, "
            "переключатель убирает её из оверлея.",
        ).pack(fill="x", pady=(0, theme.SPACE_3))
        self._rows_holder = tk.Frame(rows_card.content, bg=theme.SURFACE)
        self._rows_holder.pack(fill="x")
        self._redraw_rows_editor()

        place = widgets.Card(right, "Размещение", padding=theme.SPACE_5)
        place.pack(fill="x")
        self._corner_var = tk.StringVar(value=self.cfg.overlay_corner)
        widgets.WrapLabel(
            place.content,
            "Куда прижать оверлей. «Своё место» — перетащите мышью при выключенном "
            "пропуске кликов.",
        ).pack(fill="x", pady=(0, theme.SPACE_2))

        corners = tk.Frame(place.content, bg=theme.SURFACE)
        corners.pack(anchor="w")
        self._corner_buttons: dict[str, widgets.FlatButton] = {}
        for index, (value, glyph) in enumerate(CORNER_GLYPHS):
            button = widgets.FlatButton(corners, glyph,
                                        lambda v=value: self._set_corner(v),
                                        width=48, height=34)
            button.grid(row=index // 2, column=index % 2, padx=3, pady=3)
            self._corner_buttons[value] = button
        custom = widgets.FlatButton(place.content, "Своё место (перетащить)",
                                    lambda: self._set_corner("custom"))
        custom.pack(anchor="w", pady=(theme.SPACE_2, 0))
        self._corner_buttons["custom"] = custom
        self._paint_corners()

        look = widgets.Card(right, "Вид", padding=theme.SPACE_5)
        look.pack(fill="x", pady=(theme.SPACE_4, 0))
        self._alpha_var = tk.DoubleVar(value=self.cfg.overlay_alpha)
        self._scale_var = tk.DoubleVar(value=self.cfg.overlay_scale)
        widgets.SectionTitle(look.content, "Прозрачность", fill=theme.SURFACE, top=0)
        widgets.Slider(look.content, self._alpha_var, 0.2, 1.0, self._on_alpha,
                       bg=theme.SURFACE, width=250).pack(fill="x",
                                                         pady=(theme.SPACE_1, theme.SPACE_2))
        widgets.SectionTitle(look.content, "Масштаб текста", top=theme.SPACE_2)
        widgets.Slider(look.content, self._scale_var, 0.7, 2.0, self._on_scale,
                       bg=theme.SURFACE, width=250).pack(fill="x",
                                                         pady=(theme.SPACE_1, theme.SPACE_2))
        self._header_var = tk.BooleanVar(value=self.cfg.overlay_show_header)
        widgets.SwitchRow(look.content, "Заголовок и имя приложения", self._header_var,
                          self._on_header_changed,
                          fill=theme.SURFACE).pack(fill="x", pady=(theme.SPACE_2, 0))

        behaviour = widgets.Card(right, "Поведение", padding=theme.SPACE_5)
        behaviour.pack(fill="x", pady=(theme.SPACE_4, 0))
        self._overlay_var = tk.BooleanVar(value=self.cfg.overlay_enabled)
        widgets.SwitchRow(behaviour.content, "Показывать оверлей", self._overlay_var,
                          self._on_overlay_toggle, hint="Ctrl+Alt+O",
                          fill=theme.SURFACE).pack(fill="x", pady=theme.SPACE_1)
        self._click_var = tk.BooleanVar(value=self.cfg.overlay_click_through)
        widgets.SwitchRow(behaviour.content, "Пропускать клики сквозь оверлей",
                          self._click_var, self._on_click_changed, hint="Ctrl+Alt+L",
                          fill=theme.SURFACE).pack(fill="x", pady=theme.SPACE_1)
        widgets.WrapLabel(
            behaviour.content,
            "Чтобы передвинуть оверлей, выключите пропуск кликов и перетащите его.",
        ).pack(fill="x", pady=(theme.SPACE_3, 0))

    def _build_settings(self) -> None:
        page = self._page("settings", "Настройки", "Периоды опроса, источники и запись")
        left = tk.Frame(page, bg=theme.BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(page, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_3, 0))

        collect = widgets.Card(left, "Сбор данных", padding=theme.SPACE_4)
        collect.pack(fill="x")
        self._spin(collect.content, "Период опроса, мс", self.cfg.poll_interval_ms,
                   250, 5000, 50, self._on_poll)
        self._spin(collect.content, "Окно истории графиков, с", self.cfg.graph_window_s,
                   30, 900, 30, self._on_window)
        self._spin(collect.content, "Окно расчёта FPS, с", self.cfg.fps_window_s,
                   0.25, 3.0, 0.25, self._on_fps_window)
        self._spin(collect.content, "Окно 1% low, с", self.cfg.low_fps_window_s,
                   2.0, 60.0, 1.0, self._on_low_window)
        self._spin(collect.content, "Номер GPU для nvidia-smi", self.cfg.gpu_index,
                   0, 7, 1, self._on_gpu_index)
        self._spin(collect.content, "Окно мини-графика в оверлее, с",
                   self.cfg.overlay_graph_window_s, 3, 60, 1, self._on_overlay_graph_window)

        sources = widgets.Card(left, "Источники", padding=theme.SPACE_4)
        sources.pack(fill="x", pady=(theme.SPACE_3, 0))
        self._lhm_var = tk.BooleanVar(value=self.cfg.lhm_autostart)
        widgets.SwitchRow(sources.content,
                          "Температура и мощность CPU",
                          self._lhm_var, self._on_lhm_toggle,
                          hint="LibreHardwareMonitor, требует прав администратора",
                          fill=theme.SURFACE).pack(fill="x")
        widgets.WrapLabel(
            sources.content,
            "FPS читается через PresentMon (ETW), метрики NVIDIA — через nvidia-smi "
            "из драйвера, загрузка CPU и ОЗУ — через psutil.",
        ).pack(fill="x", pady=(theme.SPACE_2, 0))

        logging = widgets.Card(right, "Запись в CSV", padding=theme.SPACE_4)
        logging.pack(fill="x")
        self._log_var = tk.BooleanVar(value=self.cfg.log_enabled)
        widgets.SwitchRow(logging.content, "Писать все метрики в файл", self._log_var,
                          self._on_log_toggle, fill=theme.SURFACE).pack(fill="x")
        self._log_label = tk.Label(logging.content, text="", bg=theme.SURFACE,
                                   fg=theme.MUTED, font=theme.ui(theme.FS_CAPTION),
                                   anchor="w", justify="left", wraplength=420)
        self._log_label.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_3))
        widgets.FlatButton(logging.content, "Открыть папку логов",
                           lambda: self._open(LOG_DIR), width=180).pack(anchor="w")

        keys = widgets.Card(right, "Горячие клавиши", padding=theme.SPACE_4)
        keys.pack(fill="x", pady=(theme.SPACE_3, 0))
        for combo, what in (("Ctrl+Alt+O", "показать или скрыть оверлей"),
                            ("Ctrl+Alt+L", "разрешить перетаскивание оверлея"),
                            ("Ctrl+Alt+M", "показать или скрыть это окно")):
            row = tk.Frame(keys.content, bg=theme.SURFACE)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=combo, bg=theme.SURFACE, fg=theme.ACCENT_TEXT,
                     font=theme.mono(theme.FS_SMALL, "bold"), width=12, anchor="w").pack(side="left")
            tk.Label(row, text=what, bg=theme.SURFACE, fg=theme.FG_2,
                     font=theme.ui(theme.FS_BODY), anchor="w").pack(side="left")

    def _build_diagnostics(self) -> None:
        page = self._page("diagnostics", "Диагностика",
                          "Состояние источников данных и что делать, если чего-то нет")
        left = tk.Frame(page, bg=theme.BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(page, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_3, 0))

        banner = widgets.Surface(left, fill=theme.SURFACE, padding=theme.SPACE_3, height=58)
        banner.pack(fill="x", pady=(0, theme.SPACE_3))
        self._elevation_text = widgets.WrapLabel(
            banner.body, "", fg=theme.WARN, font=theme.ui(theme.FS_BODY), min_wrap=200)
        self._elevation_text.pack(fill="x")

        sources = widgets.Card(left, "Источники", padding=theme.SPACE_4)
        sources.pack(fill="x")
        for _ in range(4):
            row = tk.Frame(sources.content, bg=theme.SURFACE)
            row.pack(fill="x", pady=theme.SPACE_1 + 1)
            name = tk.Label(row, text="", bg=theme.SURFACE, fg=theme.FG,
                            font=theme.ui(theme.FS_BODY, "bold"), width=24, anchor="w")
            name.pack(side="left")
            message = tk.Label(row, text="", bg=theme.SURFACE, fg=theme.MUTED,
                               font=theme.ui(theme.FS_CAPTION), anchor="w")
            message.pack(side="left", fill="x", expand=True)
            pill = widgets.Pill(row, "", theme.MUTED, bg=theme.SURFACE)
            pill.pack(side="right", padx=(theme.SPACE_2, 0))
            pill.configure(width=132)
            self._status_rows.append((name, pill, message))

        cpu_card = widgets.Card(left, "Датчики процессора", padding=theme.SPACE_4)
        cpu_card.pack(fill="x", pady=(theme.SPACE_3, 0))
        self._cpu_temp_label = widgets.WrapLabel(
            cpu_card.content, "", fg=theme.FG_2, font=theme.ui(theme.FS_BODY), min_wrap=200)
        self._cpu_temp_label.pack(fill="x", pady=(0, theme.SPACE_3))
        cpu_buttons = tk.Frame(cpu_card.content, bg=theme.SURFACE)
        cpu_buttons.pack(fill="x")
        self._pawnio_button = widgets.FlatButton(
            cpu_buttons, "Установить драйвер (PawnIO)", self._install_pawnio,
            variant="primary", width=220)
        self._pawnio_button.pack(side="left")
        self._pawnio_button.set_enabled(False)
        widgets.FlatButton(cpu_buttons, "Перезапустить источник", self._restart_lhm,
                           width=190).pack(side="left", padx=theme.SPACE_2)

        paths = widgets.Card(right, "Расположение и действия", padding=theme.SPACE_4)
        paths.pack(fill="x")
        self._error_label = widgets.WrapLabel(
            paths.content, "", fg=theme.ERR, min_wrap=200)
        self._error_label.pack(fill="x")
        self._paths_label = tk.Label(paths.content, text="", bg=theme.SURFACE, fg=theme.MUTED,
                                     font=theme.mono(theme.FS_CAPTION), justify="left",
                                     anchor="w")
        self._paths_label.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_3))
        buttons = tk.Frame(paths.content, bg=theme.SURFACE)
        buttons.pack(fill="x")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        for index, (text, command) in enumerate((
            ("Папка приложения", lambda: self._open(APP_DIR)),
            ("Логи", lambda: self._open(LOG_DIR)),
            ("Самопроверка", self._run_selftest),
            ("Перезапустить FPS", self._restart_presentmon),
        )):
            widgets.FlatButton(buttons, text, command).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)

        help_card = widgets.Card(right, "Если данных нет", padding=theme.SPACE_4)
        help_card.pack(fill="both", expand=True, pady=(theme.SPACE_3, 0))
        widgets.WrapLabel(
            help_card.content,
            "• Нет FPS — приложение запущено без прав администратора. "
            "Закройте его и запустите FpsMonitor.cmd, подтвердите UAC.\n"
            "• Нет температуры CPU — либо нет прав, либо Windows блокирует "
            "драйвер WinRing0; нажмите «Установить драйвер (PawnIO)».\n"
            "• Нет метрик GPU — нужен драйвер NVIDIA (nvidia-smi).\n"
            "• Окно пропало — приложение свёрнуто: значок в трее рядом с часами, "
            "левый клик открывает окно, правый даёт меню с выходом.",
            font=theme.ui(theme.FS_SMALL), fg=theme.FG_2,
        ).pack(fill="x")

    # ------------------------------------------------------------------ #
    def _spin(self, parent: tk.Misc, title: str, value, low, high, step, command,
              floating: bool = False) -> None:
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", pady=theme.SPACE_1 + 1)
        tk.Label(row, text=title, bg=theme.SURFACE, fg=theme.FG_2,
                 font=theme.ui(theme.FS_BODY), anchor="w").pack(side="left")
        var = tk.StringVar(value=str(value))
        box = ttk.Spinbox(row, from_=low, to=high, increment=step, textvariable=var,
                          width=8, command=lambda: command(var.get()))
        box.pack(side="right")
        box.bind("<Return>", lambda _e: command(var.get()))
        box.bind("<FocusOut>", lambda _e: command(var.get()))

    # ================================================================== #
    # refresh
    # ================================================================== #
    def refresh(self) -> None:
        values, text, status = self.state.snapshot()
        self._refresh_hero(values, text)
        self._refresh_kpis(values, text)
        for graph in self.graphs:
            graph.redraw(values, text)
        self._refresh_frames(values)
        self._refresh_value_rows(values, text)
        self._refresh_status(values, text, status)
        self._refresh_process_box()
        if self._log_var.get() != self.sampler.logger.active:
            self._log_var.set(self.sampler.logger.active)

    def _refresh_hero(self, values: dict, text: dict) -> None:
        fps = values.get("fps")
        self._hero_fps.configure(text="--" if fps is None else f"{fps:.0f}",
                                 fg=value_color("fps", fps))
        parts = []
        if values.get("frametime") is not None:
            parts.append(f"{values['frametime']:.2f} мс")
        if values.get("fps_low") is not None:
            parts.append(f"1% low {values['fps_low']:.0f}")
        if values.get("fps_low01") is not None:
            parts.append(f"0.1% {values['fps_low01']:.0f}")
        self._hero_caption.configure(text="  ·  ".join(parts) if parts else "нет данных")
        if self.overlay.series_provider:
            try:
                self._hero_graph.redraw(self.overlay.series_provider(30), None)
            except Exception:
                pass

    def _refresh_kpis(self, values: dict, text: dict) -> None:
        for key, tile in self._kpis.items():
            if key.startswith("frame_"):
                continue
            value = values.get(key)
            tile.update_value("--" if value is None else f"{value:.0f}",
                              value_color(key, value))
            state = threshold_state(key, value)
            caption = {"crit": "критично", "warn": "выше порога"}.get(state or "", "в норме")
            if value is None:
                caption = "нет данных"
            tile.update_caption(caption, theme.MUTED)

        frame_specs = {
            "frametime": "{:.2f}", "frametime_min": "{:.2f}", "frametime_max": "{:.2f}",
            "fps_low": "{:.0f}", "fps_low01": "{:.0f}", "stutters": "{:.0f}",
        }
        for key, tile in self._kpis.items():
            if not key.startswith("frame_"):
                continue
            metric = key.split("frame_", 1)[1]
            value = values.get(metric)
            template = frame_specs.get(metric, "{:.1f}")
            colour = value_color(metric, value)
            tile.update_value("--" if value is None else template.format(value), colour)
            caption = {
                "frametime": "среднее",
                "frametime_min": "минимум",
                "frametime_max": "максимум",
                "fps_low": "худшие 1%",
                "fps_low01": "худшие 0.1%",
                "stutters": "> 2× среднего",
            }.get(metric, "")
            tile.update_caption(caption)

    def _refresh_frames(self, values: dict) -> None:
        source = self.sampler.source("presentmon")
        series: list[tuple[float, float]] = []
        stats: dict = {}
        if source is not None and hasattr(source, "frame_series"):
            try:
                series = source.frame_series(self.cfg.frame_graph_window_s)
                stats = source.stats(self.cfg.low_fps_window_s)
            except Exception:
                series, stats = [], {}
        self.frame_graph.redraw(series, stats)

    def _refresh_value_rows(self, values: dict, text: dict) -> None:
        for key, row in self._value_rows.items():
            rendered = format_value(key, values, text) or "--"
            row.update_value(rendered, value_color(key, values.get(key)))
            row.update_dot(color_of(key) if values.get(key) is not None else theme.DISABLED)

    def _refresh_status(self, values: dict, text: dict, status: dict) -> None:
        elevated = is_elevated()
        self._chip_admin.configure_pill(
            "АДМИН ЕСТЬ" if elevated else "БЕЗ АДМИНА", theme.OK if elevated else theme.ERR)
        capture = status.get("presentmon", ("", ""))[0]
        self._chip_capture.configure_pill(
            {"ok": "ЗАХВАТ ИДЁТ", "starting": "ЗАХВАТ: ОЖИДАНИЕ",
             "unavailable": "ЗАХВАТ НЕДОСТУПЕН"}.get(capture, "ЗАХВАТ"),
            theme.STATUS_COLORS.get(capture, theme.MUTED))
        logging_on = self.sampler.logger.active
        self._chip_log.configure_pill("ЗАПИСЬ CSV" if logging_on else "БЕЗ ЗАПИСИ",
                                      theme.INFO if logging_on else theme.DISABLED)

        if elevated:
            self._elevation_text.configure(
                text="Права администратора есть: работают захват кадров и датчики CPU.",
                fg=theme.OK)
        else:
            self._elevation_text.configure(
                text="Нет прав администратора: FPS и температура CPU недоступны. "
                     "Закройте приложение и запустите FpsMonitor.cmd.",
                fg=theme.ERR)

        rows = self.sampler.status_rows()
        for index, (name_widget, pill, message) in enumerate(self._status_rows):
            if index >= len(rows):
                name_widget.configure(text="")
                message.configure(text="")
                pill.configure_pill("", theme.MUTED)
                continue
            title, source_status, detail = rows[index]
            name_widget.configure(text=title)
            message.configure(text=detail)
            pill.configure_pill(source_status.upper(),
                                theme.STATUS_COLORS.get(source_status, theme.MUTED))

        error = getattr(self.sampler, "last_error", "")
        self._error_label.configure(text=f"ошибка цикла опроса: {error}" if error else "")
        home = str(Path.home())
        shown = str(APP_DIR).replace(home, "~")
        logs = str(LOG_DIR).replace(home, "~")
        self._paths_label.configure(
            text=f"{shown}\nлоги: {logs}\n"
                 f"python {platform.python_version()}  ·  сэмплов {self.state.sample_count}")

        cpu_temp = values.get("cpu_temp")
        if cpu_temp is not None:
            self._cpu_temp_label.configure(
                text=f"Датчики работают: {cpu_temp:.0f} °C, "
                     f"{(values.get('cpu_clock') or 0) / 1000:.2f} ГГц, "
                     f"{(values.get('cpu_power') or 0):.0f} Вт.",
                fg=theme.OK)
            self._pawnio_button.set_enabled(False)
        else:
            from ..sources import pawnio

            installed = pawnio.is_installed()
            if self._pawnio_result:
                text_line, colour = self._pawnio_result, theme.WARN
            elif not elevated:
                text_line, colour = ("Нужны права администратора — запустите через "
                                     "FpsMonitor.cmd."), theme.ERR
            elif installed:
                text_line, colour = ("PawnIO установлен, но датчики не отвечают."), theme.ERR
            else:
                text_line, colour = pawnio.blocked_driver_reason() + " Можно починить ниже.", theme.WARN
            self._cpu_temp_label.configure(text=text_line, fg=colour)
            self._pawnio_button.set_enabled(elevated and not installed and not self._pawnio_busy)

    def _refresh_process_box(self) -> None:
        now = time.time()
        if now - self._proc_at < 2.0:
            return
        self._proc_at = now
        source = self.sampler.source("presentmon")
        if source is None or not hasattr(source, "candidates"):
            return
        options = ["Авто"]
        self._proc_index = {"Авто": None}
        for pid, name, fps in source.candidates()[:14]:
            label = f"{name} · {fps:.0f} fps"
            if label in self._proc_index:
                label = f"{label} (pid {pid})"
            options.append(label)
            self._proc_index[label] = pid
        if options != list(self._proc_box["values"]):
            self._proc_box["values"] = options
        if self._proc_box.get() not in options:
            self._proc_box.set("Авто")

    # ================================================================== #
    # callbacks
    # ================================================================== #
    def _on_process_selected(self, _event=None) -> None:
        source = self.sampler.source("presentmon")
        if source is not None and hasattr(source, "set_pinned"):
            source.set_pinned(self._proc_index.get(self._proc_box.get()))

    def _set_corner(self, value: str) -> None:
        self._corner_var.set(value)
        self._on_corner_changed()

    def _paint_corners(self) -> None:
        """Highlight the chosen corner button."""
        current = self.cfg.overlay_corner
        for value, button in getattr(self, "_corner_buttons", {}).items():
            button.set_variant("primary" if value == current else "secondary")

    def _on_corner_changed(self) -> None:
        self.cfg.overlay_corner = self._corner_var.get()
        self.cfg.save()
        self.overlay.place()
        self._paint_corners()

    def _on_alpha(self) -> None:
        self.cfg.overlay_alpha = round(self._alpha_var.get(), 2)
        self.overlay.attributes("-alpha", self.cfg.overlay_alpha)
        self.cfg.save()

    def _on_scale(self) -> None:
        new_scale = round(self._scale_var.get(), 2)
        if abs(new_scale - self.cfg.overlay_scale) < 0.01:
            return
        self.cfg.overlay_scale = new_scale
        self.cfg.save()
        self.overlay.rebuild()

    def _on_header_changed(self) -> None:
        self.cfg.overlay_show_header = self._header_var.get()
        self.cfg.save()
        self.overlay.rebuild()

    def _on_overlay_toggle(self) -> None:
        self.cfg.overlay_enabled = self._overlay_var.get()
        self.cfg.save()
        self.overlay.apply_settings()

    def _on_click_changed(self) -> None:
        self.cfg.overlay_click_through = self._click_var.get()
        self.cfg.save()
        self.overlay.apply_click_through()

    def _on_poll(self, raw: str) -> None:
        try:
            self.cfg.poll_interval_ms = max(100, int(float(raw)))
        except ValueError:
            return
        self.cfg.save()

    def _on_window(self, raw: str) -> None:
        try:
            self.cfg.graph_window_s = max(10, int(float(raw)))
        except ValueError:
            return
        self.cfg.save()
        for graph in self.graphs:
            graph.set_window(self.cfg.graph_window_s)

    def _on_fps_window(self, raw: str) -> None:
        try:
            self.cfg.fps_window_s = max(0.2, float(raw))
        except ValueError:
            return
        self.cfg.save()
        source = self.sampler.source("presentmon")
        if source is not None:
            source.fps_window = self.cfg.fps_window_s

    def _on_low_window(self, raw: str) -> None:
        try:
            self.cfg.low_fps_window_s = max(1.0, float(raw))
        except ValueError:
            return
        self.cfg.save()
        source = self.sampler.source("presentmon")
        if source is not None:
            source.low_window = self.cfg.low_fps_window_s

    def _on_gpu_index(self, raw: str) -> None:
        try:
            self.cfg.gpu_index = max(0, int(float(raw)))
        except ValueError:
            return
        self.cfg.save()
        source = self.sampler.source("nvidia")
        if source is not None:
            source.gpu_index = self.cfg.gpu_index

    def _on_lhm_toggle(self) -> None:
        self.cfg.lhm_autostart = self._lhm_var.get()
        self.cfg.save()

    def _on_overlay_graph_window(self, raw: str) -> None:
        try:
            self.cfg.overlay_graph_window_s = max(3, int(float(raw)))
        except ValueError:
            return
        self.cfg.save()
        graph = getattr(self.overlay, "_graph", None)
        if graph is not None:
            graph.configure_graph(window_s=self.cfg.overlay_graph_window_s)

    def _on_log_toggle(self) -> None:
        path = self.sampler.set_logging(self._log_var.get())
        self._log_label.configure(text=str(path) if path else "запись остановлена")

    def _on_frame_window(self) -> None:
        self.cfg.frame_graph_window_s = int(self._frame_window_var.get())
        self.cfg.save()
        self.frame_graph.configure_graph(window_s=self.cfg.frame_graph_window_s)

    def _on_frame_mode(self) -> None:
        self.cfg.frame_graph_mode = self._frame_mode_var.get()
        self.cfg.save()
        self.frame_graph.configure_graph(mode=self.cfg.frame_graph_mode)

    def _on_frame_scale(self) -> None:
        self.cfg.frame_graph_scale = self._frame_scale_var.get()
        self.cfg.save()
        self.frame_graph.configure_graph(scale=self.cfg.frame_graph_scale)

    # ------------------------------------------------------------------ #
    def hide_window(self, hint: bool = True) -> None:
        self.root.withdraw()
        if hint and not self.cfg.hide_hint_shown:
            self.cfg.hide_hint_shown = True
            self.cfg.save()
            tray_ok = self.tray is not None and getattr(self.tray, "available", False)
            if tray_ok:
                self.tray.notify(
                    "FPS Monitor продолжает работать",
                    "Значок в трее рядом с часами: левый клик — открыть окно, "
                    "правый — меню с выходом.",
                )
                return
            messagebox.showinfo(
                "FPS Monitor продолжает работать",
                "Окно скрыто, приложение не закрыто.\n\n"
                "• Ctrl+Alt+M — вернуть это окно\n"
                "• Ctrl+Alt+O — показать или скрыть оверлей\n"
                "• Ctrl+Alt+L — разрешить перетаскивание оверлея\n\n"
                "Полностью закрыть приложение можно кнопкой «Выход» в боковом меню.",
            )

    def quit_app(self) -> None:
        if messagebox.askokcancel("FPS Monitor", "Закрыть FPS Monitor полностью?"):
            if self.on_quit:
                self.on_quit()

    def sync_overlay_controls(self) -> None:
        """Reflect config changes made through hotkeys or by dragging the HUD."""
        self._overlay_var.set(self.cfg.overlay_enabled)
        self._click_var.set(self.cfg.overlay_click_through)
        self._corner_var.set(self.cfg.overlay_corner)
        self._paint_corners()

    # ------------------------------------------------------------------ #
    def _open(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))  # noqa: S606 - deliberate shell open
        except Exception:
            pass

    def _run_selftest(self) -> None:
        script = APP_DIR / "tools" / "selftest.py"
        if not script.is_file():
            return
        try:
            subprocess.Popen([sys.executable, str(script), "8"], cwd=str(APP_DIR),
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError:
            pass

    def _restart_presentmon(self) -> None:
        source = self.sampler.source("presentmon")
        if source is None:
            return
        try:
            source._kill()  # noqa: SLF001 - deliberate manual restart
            source._restart_at = 0.0
        except Exception:
            pass

    def _restart_lhm(self) -> None:
        source = self.sampler.source("lhm")
        if source is not None and hasattr(source, "restart"):
            source.restart()
        self._pawnio_result = ""

    def _install_pawnio(self) -> None:
        if self._pawnio_busy:
            return
        self._pawnio_busy = True
        self._pawnio_result = ""
        self._pawnio_button.set_text("Установка драйвера…")
        self._pawnio_button.set_enabled(False)

        def worker() -> None:
            from ..sources import pawnio

            staged = default_stage_dir() / "LibreHardwareMonitor.exe"
            vendor = APP_DIR / "vendor" / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe"
            exe = staged if staged.is_file() else vendor
            try:
                ok, message = pawnio.install(exe)
            except Exception as exc:
                ok, message = False, f"{type(exc).__name__}: {exc}"
            self.root.after(0, lambda: self._pawnio_done(ok, message))

        threading.Thread(target=worker, daemon=True).start()

    def _pawnio_done(self, ok: bool, message: str) -> None:
        self._pawnio_busy = False
        self._pawnio_button.set_text("Установить драйвер (PawnIO)")
        self._pawnio_result = ("Готово: " if ok else "Не удалось: ") + message
        source = self.sampler.source("lhm")
        if source is not None and hasattr(source, "restart"):
            source.restart()
        messagebox.showinfo("FPS Monitor — драйвер датчиков", self._pawnio_result)

    # kept for compatibility with the previous layout
    @property
    def _values(self) -> dict:
        return self._value_rows
