"""Registry of every metric the app can display, plus value formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str = ""
    group: str = "misc"
    decimals: int = 0
    color: str = "#7dd3fc"
    default_row: bool = False


METRICS: tuple[Metric, ...] = (
    # ---- frames -------------------------------------------------------
    Metric("fps", "FPS", "", "frames", 0, "#4ade80", True),
    Metric("fps_low", "1% low", "", "frames", 0, "#22c55e"),
    Metric("fps_low01", "0.1% low", "", "frames", 0, "#16a34a"),
    Metric("frametime", "Frame time", "ms", "frames", 2, "#a3e635", True),
    Metric("frametime_min", "Frame time min", "ms", "frames", 2, "#86efac"),
    Metric("frametime_max", "Frame time max", "ms", "frames", 2, "#fca5a5"),
    Metric("frametime_display", "Кадр на экране", "ms", "frames", 2, "#7dd3fc"),
    Metric("stutters", "Статтеры", "", "frames", 0, "#fb7185"),
    Metric("frames_window", "Кадров в окне", "", "frames", 0, "#94a3b8"),
    Metric("frame_graph", "График времени кадра", "", "frames", 0, "#38bdf8"),
    # ---- cpu ----------------------------------------------------------
    Metric("cpu_load", "CPU", "%", "cpu", 0, "#60a5fa", True),
    Metric("cpu_temp", "CPU temp", "\u00b0C", "cpu", 0, "#f87171", True),
    Metric("cpu_clock", "CPU clock", "MHz", "cpu", 0, "#93c5fd"),
    Metric("cpu_power", "CPU power", "W", "cpu", 1, "#c084fc"),
    # ---- gpu ----------------------------------------------------------
    Metric("gpu_load", "GPU", "%", "gpu", 0, "#38bdf8", True),
    Metric("gpu_temp", "GPU temp", "\u00b0C", "gpu", 0, "#fb923c", True),
    Metric("gpu_vram", "VRAM", "%", "gpu", 0, "#fbbf24"),
    Metric("gpu_power", "GPU power", "W", "gpu", 1, "#f472b6", True),
    Metric("gpu_clock", "GPU clock", "MHz", "gpu", 0, "#7dd3fc"),
    Metric("gpu_fan", "GPU fan", "%", "gpu", 0, "#a5b4fc"),
    # ---- memory -------------------------------------------------------
    Metric("ram_load", "RAM", "%", "ram", 0, "#34d399"),
    Metric("ram_used", "RAM used", "GB", "ram", 1, "#34d399"),
    # ---- context ------------------------------------------------------
    Metric("proc_text", "Process", "", "ctx", 0, "#e2e8f0"),
    Metric("proc_cpu", "Process CPU", "%", "ctx", 0, "#fcd34d"),
)

METRIC_BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}

# Re-skin to the dashboard palette (cool surfaces, one accent, semantic alerts)
_PALETTE = {
    "fps": "#3FD68C", "fps_low": "#2FB574", "fps_low01": "#249A63",
    "frametime": "#A8E063", "frametime_min": "#C7F09A", "frametime_max": "#FF9F68",
    "frametime_display": "#5AC8FA", "stutters": "#FF7AB6", "frames_window": "#8B98AB",
    "frame_graph": "#6E8BFF",
    "cpu_load": "#6E8BFF", "cpu_temp": "#FF8A5B", "cpu_clock": "#9BB0FF",
    "cpu_power": "#B98CFF",
    "gpu_load": "#5AC8FA", "gpu_temp": "#FFB35C", "gpu_vram": "#FFD166",
    "gpu_power": "#FF7AB6", "gpu_clock": "#7FE7E0", "gpu_fan": "#A0B4D0",
    "ram_load": "#56CFE1", "ram_used": "#56CFE1",
    "proc_text": "#E8ECF3", "proc_cpu": "#F5D06B",
}
METRICS = tuple(
    Metric(m.key, m.label, m.unit, m.group, m.decimals,
           _PALETTE.get(m.key, m.color), m.default_row)
    for m in METRICS
)
# Russian labels; the internal keys stay English so configs and CSVs keep working
_LABELS = {
    "fps": "FPS", "fps_low": "1% low", "fps_low01": "0.1% low",
    "frametime": "Время кадра", "frametime_min": "Лучший кадр",
    "frametime_max": "Худший кадр", "frametime_display": "Кадр на экране",
    "stutters": "Статтеры", "frames_window": "Кадров в окне",
    "frame_graph": "График времени кадра",
    "cpu_load": "ЦПУ", "cpu_temp": "ЦПУ темп", "cpu_clock": "Частота ЦПУ",
    "cpu_power": "Мощность ЦПУ", "cpu_load_lhm": "ЦПУ (LHM)",
    "gpu_load": "ГПУ", "gpu_temp": "ГПУ темп", "gpu_hotspot": "ГПУ hot spot",
    "gpu_vram": "Видеопамять", "gpu_power": "Мощность ГПУ",
    "gpu_power_limit": "Лимит мощности", "gpu_clock": "Частота ГПУ",
    "gpu_fan": "Кулер ГПУ",
    "ram_load": "ОЗУ", "ram_used": "ОЗУ занято",
    "proc_text": "Приложение", "proc_cpu": "ЦПУ приложения",
}
METRICS = tuple(
    Metric(m.key, _LABELS.get(m.key, m.label), m.unit, m.group, m.decimals,
           m.color, m.default_row)
    for m in METRICS
)
METRIC_BY_KEY = {m.key: m for m in METRICS}
# sensors that only LibreHardwareMonitor / nvidia-smi can provide
for _extra in (
    Metric("gpu_hotspot", "ГПУ hot spot", "\u00b0C", "gpu", 0, "#FF9F68"),
    Metric("gpu_power_limit", "Лимит мощности", "W", "gpu", 0, "#8B98AB"),
    Metric("cpu_load_max", "Самое занятое ядро", "%", "cpu", 0, "#9BB0FF"),
):
    if _extra.key not in METRIC_BY_KEY:
        METRICS = METRICS + (_extra,)
        METRIC_BY_KEY[_extra.key] = _extra
# internal keys that only exist to build composite texts
DERIVED_ONLY = {"gpu_vram_mb", "gpu_vram_total_mb", "ram_total_mb", "fps_avg_short"}

# (warn, critical) limits for hardware alerts, like the original FPS Monitor
THRESHOLDS: dict[str, tuple[float, float]] = {
    "cpu_temp": (85.0, 95.0),
    "gpu_temp": (80.0, 89.0),
    "gpu_hotspot": (95.0, 105.0),
    "gpu_vram": (92.0, 98.0),
    "ram_load": (90.0, 96.0),
    "frametime": (50.0, 100.0),
}


def threshold_state(key: str, value: float | None) -> str | None:
    """"ok" / "warn" / "crit" for keys that have limits, else None."""
    if value is None:
        return None
    limits = THRESHOLDS.get(key)
    if limits is None:
        return "ok"
    warn, crit = limits
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


def value_color(key: str, value: float | None) -> str:
    """Colour for a value: alert colours win over the metric's own colour."""
    from .ui import theme  # local import keeps metrics free of UI init order

    if value is None:
        return theme.DISABLED
    state = threshold_state(key, value)
    if state == "crit":
        return theme.ERR
    if state == "warn":
        return theme.WARN
    return color_of(key)

OVERLAY_CHOICES: list[str] = [
    "frame_graph",
    "fps",
    "fps_low",
    "fps_low01",
    "frametime",
    "frametime_min",
    "frametime_max",
    "stutters",
    "proc_text",
    "proc_cpu",
    "cpu_load",
    "cpu_temp",
    "cpu_clock",
    "cpu_power",
    "gpu_load",
    "gpu_temp",
    "gpu_vram",
    "gpu_power",
    "gpu_clock",
    "gpu_fan",
    "ram_load",
    "ram_used",
]


def _num(values: dict, key: str, decimals: int = 0) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    return f"{value:.{decimals}f}"


def fmt_vram(values: dict, text: dict) -> str | None:
    used = values.get("gpu_vram_mb")
    total = values.get("gpu_vram_total_mb")
    if used is None:
        return None
    if total:
        return f"{used / 1024:.1f}/{total / 1024:.1f} GB"
    return f"{used / 1024:.1f} GB"


def fmt_ram(values: dict, text: dict) -> str | None:
    used = values.get("ram_used_mb")
    total = values.get("ram_total_mb")
    if used is None:
        return None
    if total:
        return f"{used / 1024:.1f}/{total / 1024:.1f} GB"
    return f"{used / 1024:.1f} GB"


FORMATTERS: dict[str, Callable[[dict, dict], str | None]] = {
    "gpu_vram": fmt_vram,
    "ram_used": fmt_ram,
    "proc_text": lambda values, text: text.get("proc_text"),
}


def format_value(key: str, values: dict, text: dict) -> str | None:
    """Human readable value of ``key`` or ``None`` when unavailable."""
    custom = FORMATTERS.get(key)
    if custom is not None:
        return custom(values, text)
    metric = METRIC_BY_KEY.get(key)
    if metric is None:
        return None
    raw = _num(values, key, metric.decimals)
    if raw is None:
        return None
    return f"{raw} {metric.unit}".strip()


def label_of(key: str) -> str:
    metric = METRIC_BY_KEY.get(key)
    return metric.label if metric else key


def color_of(key: str) -> str:
    metric = METRIC_BY_KEY.get(key)
    return metric.color if metric else "#e2e8f0"
