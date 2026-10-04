"""CPU temperature / power / clock via LibreHardwareMonitorLib.dll.

LibreHardwareMonitor no longer ships a WMI provider, and its web server needs a
manual click in the GUI, so the assembly is driven directly by Windows
PowerShell 5.1 (which runs on .NET Framework 4.x - exactly the target framework
of LibreHardwareMonitorLib.dll, v4.7.2).

The DLLs are staged into %LOCALAPPDATA% before loading. Two reasons:
  * .NET refuses to load assemblies from some redirected/workspace paths with
    "attempted to load an assembly from a network location" (HRESULT 0x80131515);
  * it keeps the app working no matter where the user unpacks it.

Reading CPU MSRs needs a kernel driver, so this source only produces real
numbers when the app runs elevated.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .base import Context, Source, SourceReport, SourceStatus

CREATE_NO_WINDOW = 0x08000000
SCRIPT = Path(__file__).resolve().parent / "lhm_bridge.ps1"


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def default_stage_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "FpsMonitor" / "lib" / "LibreHardwareMonitor"


def _clear_zone_marker(path: Path) -> None:
    """Drop the Mark-of-the-Web so .NET agrees to load the assembly.

    Files unpacked from a downloaded ZIP carry a :Zone.Identifier stream, and
    copying them keeps it. .NET then refuses the assembly with
    "attempted to load an assembly from a network location" (0x80131515), which
    is exactly what happens when someone runs the portable build straight from
    a freshly extracted archive.
    """
    try:
        os.remove(f"{path}:Zone.Identifier")
    except OSError:
        pass


def stage_library(vendor_dir: Path, stage_dir: Path) -> tuple[bool, str]:
    dll = vendor_dir / "LibreHardwareMonitorLib.dll"
    if not dll.is_file():
        return False, f"не найден {dll}"
    try:
        stage_dir.mkdir(parents=True, exist_ok=True)
        staged = stage_dir / "LibreHardwareMonitorLib.dll"
        stale = (
            not staged.is_file()
            or staged.stat().st_size != dll.stat().st_size
            or staged.stat().st_mtime < dll.stat().st_mtime
        )
        if stale:
            for item in vendor_dir.iterdir():
                if item.is_file():
                    target = stage_dir / item.name
                    shutil.copy2(item, target)
                    _clear_zone_marker(target)
        return True, str(stage_dir)
    except OSError as exc:
        return False, f"не удалось скопировать библиотеку: {exc}"


# --------------------------------------------------------------------- #
# sensor selection
# --------------------------------------------------------------------- #
def _usable(sensor_type: str, value: float | None) -> float | None:
    if value is None:
        return None
    # A missing kernel driver reports zeros instead of omitting the sensor.
    if sensor_type in ("Temperature", "Power", "Clock", "Fan") and value <= 0:
        return None
    return value


def _select(
    sensors: list[dict],
    hardware_types: tuple[str, ...],
    sensor_type: str,
    exact: tuple[str, ...] = (),
    contains: tuple[str, ...] = (),
    aggregate: str | None = None,
) -> float | None:
    pool = [
        (s["Name"], _usable(sensor_type, s.get("Value")))
        for s in sensors
        if s.get("HardwareType") in hardware_types and s.get("SensorType") == sensor_type
    ]
    pool = [(name, value) for name, value in pool if value is not None]
    if not pool:
        return None
    lowered = [(name.lower(), value) for name, value in pool]
    for wanted in exact:
        for name, value in lowered:
            if name == wanted.lower():
                return value
    for wanted in contains:
        for name, value in lowered:
            if wanted.lower() in name:
                return value
    values = [value for _, value in pool]
    if aggregate == "max":
        return max(values)
    if aggregate == "avg":
        return sum(values) / len(values)
    return values[0]


class LhmSource(Source):
    name = "lhm"
    title = "CPU (LibreHardwareMonitor)"
    interval = 1.0
    poll_timeout = 12.0

    def __init__(self, ctx: Context, vendor_dir: Path, stage_dir: Path | None = None,
                 enabled: bool = True) -> None:
        super().__init__(ctx)
        self.vendor_dir = Path(vendor_dir)
        self.stage_dir = Path(stage_dir) if stage_dir else default_stage_dir()
        self.enabled = enabled
        self.elevated = is_elevated()
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self._restart_at = 0.0
        self._failures = 0
        self._libdir: Path | None = None
        self._pawnio_installed: bool | None = None
        self._pawnio_checked = 0.0

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            self.set_status(SourceStatus.UNAVAILABLE, "источник отключён в настройках")
            return
        ok, detail = stage_library(self.vendor_dir, self.stage_dir)
        if not ok:
            self.set_status(SourceStatus.UNAVAILABLE, detail)
            return
        self._libdir = Path(detail)
        self._spawn()
        super().start()

    def close(self) -> None:
        self._kill()

    # -- process plumbing -----------------------------------------------
    def _spawn(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPT),
                    "-LibDir",
                    str(self._libdir),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self.set_status(SourceStatus.UNAVAILABLE, f"powershell не запустился: {exc}")
            self._proc = None
            return False

        self._lines = queue.Queue()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return True

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self._lines.put(line)
        self._lines.put("")  # signals EOF

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-20]

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write("q\n")
                proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    # -- sampling -------------------------------------------------------
    def refresh(self) -> SourceReport | None:
        now = time.monotonic()
        if self._proc is None or self._proc.poll() is not None:
            if now < self._restart_at:
                return None
            self._kill()
            if not self._spawn():
                self._restart_at = now + 30.0
                return None

        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write("\n")
            self._proc.stdin.flush()
        except OSError as exc:
            self._failures += 1
            self._restart_at = now + min(30.0, 2.0 ** self._failures)
            self._kill()
            self.set_status(SourceStatus.UNAVAILABLE, f"мост оборвался: {exc}")
            return None

        try:
            line = self._lines.get(timeout=self.poll_timeout)
        except queue.Empty:
            self._failures += 1
            self._restart_at = now + min(30.0, 2.0 ** self._failures)
            self._kill()
            self.set_status(SourceStatus.UNAVAILABLE, "таймаут ответа PowerShell")
            return None

        if not line:
            self._failures += 1
            self._restart_at = now + min(30.0, 2.0 ** self._failures)
            self._kill()
            detail = self._stderr[-1] if self._stderr else "процесс завершился"
            self.set_status(SourceStatus.UNAVAILABLE, f"мост закрыт: {detail[:120]}")
            return None

        try:
            payload = json.loads(line)
        except ValueError:
            self.set_status(SourceStatus.UNAVAILABLE, f"нечитаемый ответ: {line[:80]}")
            return None

        if not payload.get("Ok"):
            self._failures += 1
            self._restart_at = now + 30.0
            self._kill()
            self.set_status(SourceStatus.UNAVAILABLE, str(payload.get("Error"))[:140])
            return None

        self._failures = 0
        return self._map(payload.get("Sensors") or [])

    # ------------------------------------------------------------------ #
    def _map(self, sensors: list[dict]) -> SourceReport:
        report = SourceReport()
        values, text = report.values, report.text

        cpu_temp = _select(
            sensors, ("Cpu",), "Temperature",
            exact=("CPU Package", "Core (Tctl/Tdie)"),
            contains=("Tctl", "Tdie", "CPU Package", "Package"),
            aggregate="max",
        )
        cpu_load = _select(
            sensors, ("Cpu",), "Load", exact=("CPU Total",), contains=("CPU Total",)
        )
        if cpu_load is None:
            cpu_load = _select(sensors, ("Cpu",), "Load", contains=("CPU Core",), aggregate="avg")
        cpu_clock = _select(
            sensors, ("Cpu",), "Clock",
            exact=("Cores (Average)", "Core #1"),
            contains=("Cores (Average)", "Core Average"),
        )
        cpu_power = _select(
            sensors, ("Cpu",), "Power", exact=("Package",), contains=("Package",)
        )

        values["cpu_temp"] = cpu_temp
        values["cpu_clock"] = cpu_clock
        values["cpu_power"] = cpu_power
        if cpu_load is not None:
            values["cpu_load_lhm"] = cpu_load

        # GPU values only matter when nvidia-smi is missing; first-wins merge
        # in the sampler keeps nvidia-smi authoritative.
        values["gpu_temp_lhm"] = _select(
            sensors, ("GpuNvidia",), "Temperature", exact=("GPU Core",)
        )
        values["gpu_hotspot"] = _select(
            sensors, ("GpuNvidia",), "Temperature", contains=("Hot Spot",)
        )
        values["gpu_vram_temp"] = _select(
            sensors, ("GpuNvidia",), "Temperature", contains=("Memory Junction",)
        )
        values["gpu_clock_lhm"] = _select(
            sensors, ("GpuNvidia",), "Clock", exact=("GPU Core",)
        )

        hardware = {
            s.get("Hardware") for s in sensors if s.get("HardwareType") == "Cpu"
        }
        if hardware:
            text["cpu_name"] = sorted(hardware)[0]

        if cpu_temp is None:
            self.set_status(SourceStatus.UNAVAILABLE, self._missing_temp_hint())
        else:
            self.set_status(SourceStatus.OK, f"{len(sensors)} датчиков, админ: {'да' if self.elevated else 'нет'}")
        return report

    def _missing_temp_hint(self) -> str:
        if not self.elevated:
            return "нет данных: запустите от администратора"
        from . import pawnio

        if self._pawnio_installed is None or time.monotonic() > self._pawnio_checked + 15.0:
            self._pawnio_installed = pawnio.is_installed()
            self._pawnio_checked = time.monotonic()
        if not self._pawnio_installed:
            return (
                pawnio.blocked_driver_reason()
                + " Нажмите «Установить драйвер датчиков (PawnIO)» на вкладке «Диагностика»."
            )
        return "PawnIO установлен, но датчики CPU не отвечают"

    def restart(self) -> None:
        """Drop the bridge so the next poll launches a fresh one.

        Used after installing the sensor driver, which the running bridge
        process cannot pick up by itself.
        """
        self._kill()
        self._restart_at = 0.0
        self._failures = 0
        self._pawnio_installed = None
