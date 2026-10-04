"""The sampling engine: polls every source, merges values, feeds the state."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from . import winutil
from .config import LOG_DIR, VENDOR_DIR, Config
from .csvlog import CsvLogger
from .sources import LhmSource, NvidiaSource, PresentMonSource, Source, SourceStatus, SystemSource
from .sources.base import Context
from .state import State

# first-wins merge order: nvidia-smi is authoritative for GPU, LHM for CPU
# temperature/power/clock, PresentMon names the app, psutil fills the rest.
SOURCE_ORDER = ("nvidia", "lhm", "presentmon", "system")


class Sampler(threading.Thread):
    def __init__(self, config: Config, state: State, vendor_dir: Path = VENDOR_DIR,
                 log_dir: Path = LOG_DIR) -> None:
        super().__init__(name="sampler", daemon=True)
        self.config = config
        self.state = state
        self.ctx = Context()
        self.logger = CsvLogger(log_dir)
        self._stop = threading.Event()
        self.last_error = ""
        self._sources: list[Source] = []
        self._by_name: dict[str, Source] = {}
        self._build(vendor_dir)

    # ------------------------------------------------------------------ #
    def _build(self, vendor_dir: Path) -> None:
        sources = [
            NvidiaSource(self.ctx, gpu_index=self.config.gpu_index),
            LhmSource(self.ctx, vendor_dir / "LibreHardwareMonitor",
                      enabled=self.config.lhm_autostart),
            PresentMonSource(
                self.ctx,
                vendor_dir / "PresentMon",
                fps_window=self.config.fps_window_s,
                low_window=self.config.low_fps_window_s,
                avg_window=self.config.avg_fps_window_s,
                track_desktop=self.config.track_desktop,
            ),
            SystemSource(self.ctx),
        ]
        self._sources = sorted(
            sources, key=lambda src: SOURCE_ORDER.index(src.name)
            if src.name in SOURCE_ORDER else 99
        )
        self._by_name = {src.name: src for src in self._sources}

    # ------------------------------------------------------------------ #
    def source(self, name: str) -> Source | None:
        return self._by_name.get(name)

    def start(self) -> None:
        for src in self._sources:
            try:
                src.start()
            except Exception as exc:  # a broken source must not kill startup
                src.set_status(SourceStatus.UNAVAILABLE, f"{type(exc).__name__}: {exc}")
        super().start()

    def stop(self) -> None:
        self._stop.set()
        for src in self._sources:
            src.stop()
        self.logger.stop()

    # ------------------------------------------------------------------ #
    def set_logging(self, enabled: bool) -> Path | None:
        if enabled:
            path = self.logger.start()
            self.config.log_enabled = True
            self.config.save()
            return path
        self.logger.stop()
        self.config.log_enabled = False
        self.config.save()
        return None

    def current_log(self) -> Path | None:
        return self.logger.path if self.logger.active else None

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        if self.config.log_enabled:
            self.logger.start()
        interval = max(0.1, self.config.poll_interval_ms / 1000.0)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._tick()
                self.last_error = ""
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(max(0.05, interval - (time.monotonic() - started)))

    def _tick(self) -> None:
        pid, name, title = winutil.foreground_process()
        self.ctx.fg_pid, self.ctx.fg_name, self.ctx.fg_title = pid, name, title

        values: dict[str, float | None] = {}
        text: dict[str, str] = {}
        status: dict[str, tuple[str, str]] = {}
        cores: list[float] = []

        for src in self._sources:
            state, message = src.status()
            status[src.name] = (state.value, message)
            report = src.poll()
            for key, value in report.values.items():
                values.setdefault(key, value)
            for key, value in report.text.items():
                text.setdefault(key, value)
            extra_cores = report.extra.get("cpu_cores")
            if extra_cores:
                cores = list(extra_cores)

        self._apply_fallbacks(values)
        self.state.publish(values, text, status, cores=cores)
        if self.logger.active:
            self.logger.write(values, text)

    @staticmethod
    def _apply_fallbacks(values: dict[str, float | None]) -> None:
        def fill(target: str, *sources: str) -> None:
            if values.get(target) is None:
                for key in sources:
                    if values.get(key) is not None:
                        values[target] = values[key]
                        return

        fill("gpu_temp", "gpu_temp_lhm")
        fill("gpu_clock", "gpu_clock_lhm")
        fill("cpu_load", "cpu_load_lhm")

    # ------------------------------------------------------------------ #
    def status_rows(self) -> list[tuple[str, str, str]]:
        rows = []
        for src in self._sources:
            status, message = src.status()
            rows.append((src.title, status.value, message))
        return rows
