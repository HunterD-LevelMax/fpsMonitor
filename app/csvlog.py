"""CSV session logging."""

from __future__ import annotations

import csv
import time
from pathlib import Path


class CsvLogger:
    COLUMNS = [
        "fps",
        "fps_low",
        "fps_low01",
        "frametime",
        "frametime_min",
        "frametime_max",
        "frametime_display",
        "frames_window",
        "stutters",
        "cpu_load",
        "cpu_temp",
        "cpu_clock",
        "cpu_power",
        "gpu_load",
        "gpu_temp",
        "gpu_hotspot",
        "gpu_vram",
        "gpu_power",
        "gpu_clock",
        "gpu_fan",
        "ram_load",
        "proc_cpu",
    ]
    TEXT_COLUMNS = ["proc_text", "gpu_name"]

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.path: Path | None = None
        self._handle = None
        self._writer = None
        self._pending = 0

    @property
    def active(self) -> bool:
        return self._handle is not None

    def start(self) -> Path:
        self.stop()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.log_dir / f"fpsmon-{stamp}.csv"
        self._handle = open(self.path, "w", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._handle)
        self._writer.writerow(["time"] + self.COLUMNS + self.TEXT_COLUMNS)
        self._handle.flush()
        return self.path

    def write(self, values: dict, text: dict) -> None:
        if self._writer is None:
            return
        row = [time.strftime("%H:%M:%S")]
        for key in self.COLUMNS:
            value = values.get(key)
            row.append("" if value is None else f"{value:.3f}")
        for key in self.TEXT_COLUMNS:
            row.append(text.get(key, ""))
        self._writer.writerow(row)
        self._pending += 1
        if self._pending >= 5 and self._handle is not None:
            self._handle.flush()
            self._pending = 0

    def stop(self) -> None:
        if self._handle is not None:
            try:
                self._handle.flush()
                self._handle.close()
            except OSError:
                pass
        self._handle = None
        self._writer = None
