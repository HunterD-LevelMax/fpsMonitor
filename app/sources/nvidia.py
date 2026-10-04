"""GPU metrics straight from nvidia-smi - no elevation and no driver needed."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from .base import Context, Source, SourceReport, SourceStatus

CREATE_NO_WINDOW = 0x08000000

FIELDS = [
    "name",
    "temperature.gpu",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "power.draw",
    "power.limit",
    "clocks.sm",
    "fan.speed",
]

_SEARCH_PATHS = [
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]


def _to_float(raw: str) -> float | None:
    text = raw.strip()
    if not text or text.startswith("["):  # [N/A], [Not Supported], [Unknown Error]
        return None
    try:
        return float(text)
    except ValueError:
        return None


def locate_nvidia_smi() -> str | None:
    found = shutil.which("nvidia-smi")
    if found:
        return found
    for path in _SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    return None


class NvidiaSource(Source):
    name = "nvidia"
    title = "GPU (nvidia-smi)"
    interval = 1.0

    def __init__(self, ctx: Context, gpu_index: int = 0) -> None:
        super().__init__(ctx)
        self.gpu_index = gpu_index
        self.exe = locate_nvidia_smi()
        self._retry_at = 0.0

    def refresh(self) -> SourceReport | None:
        if not self.exe:
            if time.monotonic() < self._retry_at:
                return None
            self.exe = locate_nvidia_smi()
            self._retry_at = time.monotonic() + 30.0
            if not self.exe:
                self.set_status(SourceStatus.UNAVAILABLE, "nvidia-smi.exe не найден")
                return None

        cmd = [
            self.exe,
            f"--id={self.gpu_index}",
            "--query-gpu=" + ",".join(FIELDS),
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.set_status(SourceStatus.UNAVAILABLE, f"nvidia-smi: {exc}")
            return None

        if completed.returncode != 0:
            self.set_status(
                SourceStatus.UNAVAILABLE,
                f"nvidia-smi код {completed.returncode}: {completed.stderr.strip()[:80]}",
            )
            return None

        line = completed.stdout.strip().splitlines()
        if not line:
            self.set_status(SourceStatus.UNAVAILABLE, "nvidia-smi не вернул данных")
            return None
        cells = [cell.strip() for cell in line[0].split(",")]

        report = SourceReport()
        text = report.text
        values = report.values

        if cells:
            text["gpu_name"] = cells[0]

        mapping = {
            1: "gpu_temp",
            2: "gpu_load",
            3: "gpu_vram_mb",
            4: "gpu_vram_total_mb",
            5: "gpu_power",
            6: "gpu_power_limit",
            7: "gpu_clock",
            8: "gpu_fan",
        }
        for index, key in mapping.items():
            if index < len(cells):
                values[key] = _to_float(cells[index])

        used, total = values.get("gpu_vram_mb"), values.get("gpu_vram_total_mb")
        if used is not None and total:
            values["gpu_vram"] = used / total * 100.0

        self.set_status(SourceStatus.OK, text.get("gpu_name", "ok"))
        return report
