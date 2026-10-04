"""CPU / memory metrics via psutil, with a dependency-free ctypes fallback."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

from .base import Context, Source, SourceReport, SourceStatus

try:  # psutil ships in the bundled libs/ directory
    import psutil
except ImportError:  # pragma: no cover - fallback path
    psutil = None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _base_clock_mhz() -> float | None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            return float(winreg.QueryValueEx(key, "~MHz")[0])
    except Exception:
        return None


class SystemSource(Source):
    name = "system"
    title = "CPU / RAM (psutil)"
    interval = 1.0

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._fallback_clock = _base_clock_mhz()
        self._last_cpu_times: tuple[int, int, int] | None = None
        self._processes: dict[int, object] = {}
        self._primed = False

    # ------------------------------------------------------------------ #
    def refresh(self) -> SourceReport | None:
        report = SourceReport()
        values, text = report.values, report.text

        if psutil is not None:
            self._fill_psutil(values, text)
            self.set_status(SourceStatus.OK, f"psutil {psutil.__version__}")
        else:
            self._fill_fallback(values)
            self.set_status(SourceStatus.OK, "ctypes fallback (psutil отсутствует)")

        self._fill_process(report)
        self._primed = True
        return report

    # ------------------------------------------------------------------ #
    def _fill_psutil(self, values: dict, text: dict) -> None:
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        if per_core:
            values["cpu_load"] = sum(per_core) / len(per_core)
            values["cpu_load_max"] = max(per_core)
        values["cpu_cores"] = len(per_core) if per_core else float(psutil.cpu_count() or 0)

        try:
            freq = psutil.cpu_freq()
            if freq and freq.current:
                values["cpu_clock"] = float(freq.current)
            elif self._fallback_clock:
                values["cpu_clock"] = self._fallback_clock
        except Exception:
            if self._fallback_clock:
                values["cpu_clock"] = self._fallback_clock

        memory = psutil.virtual_memory()
        values["ram_load"] = float(memory.percent)
        values["ram_used_mb"] = memory.used / 1048576.0
        values["ram_total_mb"] = memory.total / 1048576.0

    # ------------------------------------------------------------------ #
    def _fill_fallback(self, values: dict) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            idle_ticks = (idle.dwHighDateTime << 32) | idle.dwLowDateTime
            kernel_ticks = (kernel.dwHighDateTime << 32) | kernel.dwLowDateTime
            user_ticks = (user.dwHighDateTime << 32) | user.dwLowDateTime
            total = kernel_ticks + user_ticks
            if self._last_cpu_times is not None:
                prev_idle, prev_total = self._last_cpu_times[0], self._last_cpu_times[2]
                delta_total = total - prev_total
                delta_idle = idle_ticks - prev_idle
                if delta_total > 0:
                    values["cpu_load"] = max(
                        0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0)
                    )
            self._last_cpu_times = (idle_ticks, kernel_ticks, total)

        if self._fallback_clock:
            values["cpu_clock"] = self._fallback_clock

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
            values["ram_load"] = float(status.dwMemoryLoad)
            values["ram_used_mb"] = (status.ullTotalPhys - status.ullAvailPhys) / 1048576.0
            values["ram_total_mb"] = status.ullTotalPhys / 1048576.0

    # ------------------------------------------------------------------ #
    def _fill_process(self, report: SourceReport) -> None:
        """CPU share of the foreground application."""
        pid = self.ctx.fg_pid
        if not pid or pid == os.getpid():
            return
        report.text["proc_text"] = self.ctx.fg_name
        if psutil is None or not self._primed:
            return
        try:
            process = self._processes.get(pid)
            if process is None:
                process = psutil.Process(pid)
                self._processes[pid] = process
                process.cpu_percent(interval=None)  # prime the counter
                return
            share = process.cpu_percent(interval=None)
            cores = psutil.cpu_count(logical=True) or 1
            report.values["proc_cpu"] = min(100.0, share / cores)
        except Exception:
            self._processes.pop(pid, None)

    def close(self) -> None:
        self._processes.clear()
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)  # reset internal counters
            except Exception:
                pass
        time.sleep(0)
