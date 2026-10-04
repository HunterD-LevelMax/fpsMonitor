"""Persistent settings, stored as JSON next to the application."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"
VENDOR_DIR = APP_DIR / "vendor"

DEFAULT_ROWS = [
    "fps",
    "frametime",
    "cpu_load",
    "cpu_temp",
    "gpu_load",
    "gpu_temp",
    "gpu_power",
]


@dataclass
class Config:
    # --- window ---
    window_geometry: str = ""      # размер и позиция, запоминаются при выходе
    window_zoomed: bool = False

    # --- overlay ---
    overlay_enabled: bool = True
    overlay_corner: str = "top-left"  # top-left | top-right | bottom-left | bottom-right | custom
    overlay_x: int = 16
    overlay_y: int = 16
    overlay_alpha: float = 0.80
    overlay_scale: float = 1.0
    overlay_click_through: bool = True
    overlay_rows: list[str] = field(default_factory=lambda: list(DEFAULT_ROWS))
    overlay_show_header: bool = True
    hide_hint_shown: bool = False

    # --- hotkeys (modifiers+key, e.g. "ctrl+alt+o") ---
    hotkey_toggle_overlay: str = "ctrl+alt+o"
    hotkey_toggle_click_through: str = "ctrl+alt+l"
    hotkey_toggle_window: str = "ctrl+alt+m"

    # --- sampling ---
    poll_interval_ms: int = 1000
    gpu_index: int = 0
    graph_window_s: int = 120
    fps_window_s: float = 1.0
    low_fps_window_s: float = 10.0

    # --- frame time graph ---
    frame_graph_window_s: int = 10
    frame_graph_mode: str = "frametime"  # frametime | fps
    frame_graph_scale: str = "auto"      # auto | 60 | 30
    overlay_graph_window_s: int = 10

    # --- logging ---
    log_enabled: bool = False

    # --- external tools ---
    lhm_autostart: bool = True
    lhm_path: str = ""
    presentmon_path: str = ""
    presentmon_capture_all: bool = True

    # ---------------------------------------------------------------- io ---
    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            try:
                # utf-8-sig: Notepad and PowerShell love to add a BOM, which
                # would otherwise make json parsing fail and silently discard
                # every setting the user made.
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return cfg
            known = {f.name for f in fields(cls)}
            for key, value in raw.items():
                if key in known and value is not None:
                    setattr(cfg, key, value)
            cfg.overlay_rows = [r for r in cfg.overlay_rows if isinstance(r, str)]
        return cfg

    def save(self) -> None:
        try:
            CONFIG_PATH.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
