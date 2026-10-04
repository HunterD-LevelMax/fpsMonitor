"""Real FPS / frame times via PresentMon (Intel, MIT) and its ETW session.

PresentMon must run elevated: capturing the Microsoft-Windows-DxgKrnl provider
needs administrative rights or membership of the "Performance Log Users" group.

Accuracy notes
--------------
* Frames are timestamped with PresentMon's own ETW clock (``TimeInMs``), not
  with the moment Python happens to parse the line, so scheduler and pipe
  buffering jitter never reach the numbers.
* Frames are kept per (process, swap chain). A process with several swap chains
  (multi-monitor, launcher + game) would otherwise report a summed, wrong rate;
  the busiest chain of the tracked process wins.
* ``fps`` is frames per second over a sliding window measured on that clock,
  ``frametime`` is the mean present-to-present time in the window, and the
  1% / 0.1% lows are the standard ``1000 / mean(worst N% of frame times)``.
* Timestamps and frame times come straight from PresentMon, so the numbers are
  directly comparable with RTSS, CapFrameX and PresentMon itself.
"""

from __future__ import annotations

import codecs
import csv
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from .base import Context, Source, SourceReport, SourceStatus
from .lhm import is_elevated

CREATE_NO_WINDOW = 0x08000000

SHELL_PROCESSES = {
    "explorer.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "lockapp.exe",
    "applicationframehost.exe",
    "taskmgr.exe",
    "textinputhost.exe",
}

SESSION_NAME = "FpsMonitorCapture"
KEEP_SECONDS = 60.0
MAX_FRAMES_PER_CHAIN = 30000
FRESH_FRAME_SECONDS = 0.75  # a newer frame than this means the app is still drawing

# v1 / v2 schemas spell the same data differently - accept every known name.
FRAME_TIME_COLUMNS = ("frametime", "msbetweenpresents", "msbetweendisplaychange")
DISPLAY_TIME_COLUMNS = ("msbetweendisplaychange",)
# (column, multiplier to milliseconds); raw QPC ticks are deliberately excluded
# because their unit is unknown and would silently break the time window.
TIMESTAMP_COLUMNS = (("timeinms", 1.0), ("cpustarttimeinms", 1.0), ("timeinseconds", 1000.0))
SWAPCHAIN_COLUMNS = ("swapchainaddress",)
GPU_TIME_COLUMNS = ("msgputime", "msgpubusy")


def decode_presentmon_line(raw: bytes) -> str:
    """PresentMon emits UTF-16; anything else is decoded as UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if raw.count(b"\x00") > len(raw) // 4:
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def read_available(stream, size: int = 65536) -> bytes:
    """Return whatever the pipe holds right now.

    ``BufferedReader.read`` would block until it collected ``size`` bytes, which
    never happens for a live capture, so ``read1`` (one raw read) is used.
    """
    reader = getattr(stream, "read1", None)
    if reader is not None:
        return reader(size)
    return os.read(stream.fileno(), size)


def sniff_encoding(sample: bytes) -> str:
    """PresentMon has shipped both UTF-16 and single-byte output over versions."""
    if sample[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if sample.count(b"\x00") > len(sample) // 4:
        return "utf-16-le"
    return "utf-8"


def iter_decoded_lines(stream, sniff_bytes: int = 64):
    """Yield text lines from a byte stream of unknown encoding.

    Splitting raw bytes on b"\\n" would be wrong for UTF-16, where the newline is
    two bytes: the leftover NUL would shift every following line by one byte and
    silently corrupt the whole capture. Decoding is therefore incremental and
    the text is split afterwards.
    """
    decoder = None
    pending = b""
    text = ""
    while True:
        chunk = read_available(stream)
        if not chunk:
            if decoder is not None:
                text += decoder.decode(b"", True)
            elif pending:
                decoder = codecs.getincrementaldecoder(sniff_encoding(pending))("replace")
                text += decoder.decode(pending, True)
            for line in text.split("\n"):
                if line.strip():
                    yield line
            return
        if decoder is None:
            pending += chunk
            if len(pending) < sniff_bytes:  # not enough bytes to sniff yet
                continue
            decoder = codecs.getincrementaldecoder(sniff_encoding(pending))("replace")
            text += decoder.decode(pending, False)
            pending = b""
        else:
            text += decoder.decode(chunk, False)
        while "\n" in text:
            line, text = text.split("\n", 1)
            yield line


def stop_etw_session(name: str = SESSION_NAME) -> bool:
    """Stop an orphaned trace session (no-op when there is nothing to stop)."""
    try:
        completed = subprocess.run(
            ["logman", "stop", name, "-ets"],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=CREATE_NO_WINDOW,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def parse_header(row: list[str], stderr_tail: list[str]) -> dict[str, float] | None:
    """Map the CSV header onto the columns we need (-1 when absent)."""
    lowered = [cell.strip().lower() for cell in row]
    if "processid" not in lowered:
        return None
    frame_column = next((n for n in FRAME_TIME_COLUMNS if n in lowered), None)
    if frame_column is None:
        stderr_tail.append("unknown PresentMon schema: " + ",".join(lowered[:8]))
        return None

    def find(names: tuple[str, ...]) -> int:
        for name in names:
            if name in lowered:
                return lowered.index(name)
        return -1

    timestamp, scale = -1, 1.0
    for name, multiplier in TIMESTAMP_COLUMNS:
        if name in lowered:
            timestamp, scale = lowered.index(name), multiplier
            break

    return {
        "pid": lowered.index("processid"),
        "frame": lowered.index(frame_column),
        "display": find(DISPLAY_TIME_COLUMNS),
        "timestamp": timestamp,
        "timestamp_scale": scale,
        "swapchain": find(SWAPCHAIN_COLUMNS),
        "gpu": find(GPU_TIME_COLUMNS),
        "app": find(("application",)),
    }


@dataclass(slots=True)
class Frame:
    """One presented frame, timestamped on PresentMon's own clock."""

    t: float          # milliseconds on the capture timeline
    present: float    # ms since the previous present of the same chain
    display: float | None = None
    gpu: float | None = None


def percentiles(frame_times: list[float]) -> dict[str, float]:
    """1% / 0.1% low FPS = 1000 / mean(worst N% of frame times)."""
    result: dict[str, float] = {}
    if len(frame_times) < 20:
        return result
    ordered = sorted(frame_times, reverse=True)
    for key, share in (("fps_low", 0.01), ("fps_low01", 0.001)):
        count = max(1, int(len(ordered) * share))
        average = fmean(ordered[:count])
        if average > 0:
            result[key] = 1000.0 / average
    return result


class PresentMonSource(Source):
    name = "presentmon"
    title = "FPS (PresentMon)"
    interval = 0.2  # five updates per second keeps the HUD feeling live

    def __init__(self, ctx: Context, vendor_dir: Path, sticky_seconds: float = 6.0,
                 fps_window: float = 1.0, low_window: float = 10.0) -> None:
        super().__init__(ctx)
        self.vendor_dir = Path(vendor_dir)
        self.sticky_seconds = sticky_seconds
        self.fps_window = fps_window
        self.low_window = low_window

        self.exe: Path | None = self._locate()
        self.session_name = SESSION_NAME
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._chains: dict[tuple[int, str], deque[Frame]] = {}
        self._names: dict[int, str] = {}
        self._active_pid: int | None = None
        self._active_seen = 0.0
        self._pinned_pid: int | None = None
        self._stderr: list[str] = []
        self._reader_error = ""
        self._restart_at = 0.0
        self._failures = 0
        self._admin_hint = not is_elevated()
        self._clock_origin: float | None = None  # local fallback timeline
        self._newest_t = 0.0
        self._newest_local = 0.0
        self._native_clock = False

    # ------------------------------------------------------------------ #
    # discovery / lifecycle
    # ------------------------------------------------------------------ #
    def _locate(self) -> Path | None:
        if not self.vendor_dir.is_dir():
            return None
        candidates = sorted(self.vendor_dir.glob("PresentMon*.exe"))
        return candidates[-1] if candidates else None

    def start(self) -> None:
        if self.exe is None:
            self.set_status(SourceStatus.UNAVAILABLE, f"PresentMon не найден в {self.vendor_dir}")
            return
        self._spawn()
        super().start()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        # PresentMon does not stop its ETW session when it is killed
        stop_etw_session(self.session_name)

    def _spawn(self) -> bool:
        # an orphaned session from a previously killed capture starves this one
        stop_etw_session(self.session_name)
        cmd = [
            str(self.exe),
            "--output_stdout",
            "--no_console_stats",
            "--stop_existing_session",
            "--session_name",
            self.session_name,
            "--set_circular_buffer_size",
            "65536",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self.set_status(SourceStatus.UNAVAILABLE, f"PresentMon не запустился: {exc}")
            self._proc = None
            return False
        self._reader_error = ""
        self._clock_origin = None
        self._native_clock = False
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return True

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # reading
    # ------------------------------------------------------------------ #
    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        columns: dict[str, float] | None = None
        try:
            for text in iter_decoded_lines(proc.stdout):
                line = text.strip("\r\ufeff")
                if not line:
                    continue
                try:
                    row = next(iter(csv.reader([line])), None)
                except (csv.Error, UnicodeError):
                    continue
                if not row:
                    continue
                if columns is None:
                    columns = parse_header(row, self._stderr)
                    continue
                self._ingest(row, columns)
        except Exception as exc:  # a dead reader must not fail silently
            self._reader_error = f"{type(exc).__name__}: {exc}"

    def _ingest(self, row: list[str], columns: dict[str, float]) -> None:
        try:
            pid = int(row[int(columns["pid"])])
            frame_ms = float(row[int(columns["frame"])])
        except (ValueError, IndexError):
            return
        if frame_ms <= 0:
            return

        def optional(index: float) -> float | None:
            position = int(index)
            if position < 0 or position >= len(row):
                return None
            try:
                value = float(row[position])
            except ValueError:
                return None
            return value if value > 0 else None

        local_now = time.monotonic()
        stamp = optional(columns["timestamp"]) if columns["timestamp"] >= 0 else None
        if stamp is None:
            # no timestamp column in this schema - fall back to arrival time
            if self._clock_origin is None:
                self._clock_origin = local_now
            t_ms = (local_now - self._clock_origin) * 1000.0
        else:
            self._native_clock = True
            t_ms = stamp * columns["timestamp_scale"]

        swapchain = row[int(columns["swapchain"])] if columns["swapchain"] >= 0 else "0"
        key = (pid, swapchain)
        frame = Frame(
            t=t_ms,
            present=frame_ms,
            display=optional(columns["display"]),
            gpu=optional(columns["gpu"]),
        )

        with self._lock:
            chain = self._chains.get(key)
            if chain is None:
                chain = self._chains[key] = deque(maxlen=MAX_FRAMES_PER_CHAIN)
            chain.append(frame)
            app_index = int(columns["app"])
            if 0 <= app_index < len(row) and row[app_index]:
                self._names[pid] = os.path.basename(row[app_index])
            if t_ms >= self._newest_t:
                self._newest_t = t_ms
                self._newest_local = local_now
            self._trim()

    def _trim(self) -> None:
        cutoff = self._newest_t - KEEP_SECONDS * 1000.0
        empty: list[tuple[int, str]] = []
        for key, chain in self._chains.items():
            while chain and chain[0].t < cutoff:
                chain.popleft()
            if not chain:
                empty.append(key)
        for key in empty:
            self._chains.pop(key, None)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for text in iter_decoded_lines(proc.stderr):
                line = text.strip("\r\ufeff")
                if line:
                    self._stderr.append(line)
                    del self._stderr[:-20]
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # sampling
    # ------------------------------------------------------------------ #
    def refresh(self) -> SourceReport | None:
        now = time.monotonic()
        if self._reader_error:
            self.set_status(SourceStatus.UNAVAILABLE, f"чтение вывода: {self._reader_error}")
            self._reader_error = ""
            self._kill()
            self._restart_at = now + 5.0
            return None
        if self._proc is None or self._proc.poll() is not None:
            if now < self._restart_at:
                return None
            self._kill()
            if not self._spawn():
                self._restart_at = now + 30.0
                return None
            self._failures += 1
            self._restart_at = now + min(30.0, 2.0 * self._failures)

        chains, names, newest_t, newest_local = self._snapshot()
        if not chains:
            detail = self._stderr[-1] if self._stderr else "ожидание кадров"
            if self._admin_hint or "denied" in detail.lower():
                self.set_status(
                    SourceStatus.UNAVAILABLE,
                    "нужны права администратора: перезапустите через FpsMonitor.cmd",
                )
            else:
                self.set_status(SourceStatus.STARTING, detail[:100])
            return None

        if now - newest_local > FRESH_FRAME_SECONDS:
            self.set_status(SourceStatus.STARTING, "нет свежих кадров (приложение не рисует)")
            return None

        pid = self._choose_pid(chains, newest_t, names)
        if pid is None:
            self.set_status(SourceStatus.STARTING, "кадры есть, активное приложение не выбрано")
            return None

        key = self._busiest_chain(chains, pid, newest_t)
        frames = [f for f in chains[key] if f.t >= newest_t - self.fps_window * 1000.0]
        if len(frames) < 2:
            self.set_status(SourceStatus.STARTING, f"мало кадров ({names.get(pid, pid)})")
            return None

        report = SourceReport()
        values = report.values
        present_times = [f.present for f in frames]
        average_frame = fmean(present_times)
        # FPS is the reciprocal of the mean frame time. Counting frames per
        # window would be the same for a steady stream, but it jumps around by
        # several frames per second whenever a hitch falls inside the window -
        # this definition stays consistent with the frame time shown next to it.
        values["fps"] = 1000.0 / average_frame if average_frame > 0 else None
        values["frametime"] = average_frame
        values["frametime_min"] = min(present_times)
        values["frametime_max"] = max(present_times)
        values["frames_window"] = float(len(frames))

        low_times = [
            f.present for f in chains[key] if f.t >= newest_t - self.low_window * 1000.0
        ]
        values.update(percentiles(low_times))
        if len(low_times) > 20:
            average = fmean(low_times)
            values["stutters"] = float(sum(1 for t in low_times if t > 2.0 * average))

        display_times = [f.display for f in frames if f.display]
        if display_times:
            values["frametime_display"] = fmean(display_times)

        chains_for_pid = sum(1 for chain_pid, _ in chains if chain_pid == pid)
        report.text["proc_text"] = names.get(pid, f"pid {pid}")
        report.text["frame_source"] = names.get(pid, f"pid {pid}") + (
            f" · свопчейнов: {chains_for_pid}" if chains_for_pid > 1 else ""
        )
        self.set_status(
            SourceStatus.OK,
            f"{len(self._names)} процессов, активный {names.get(pid, pid)}, "
            f"часы: {'ETW' if self._native_clock else 'локальные'}",
        )
        return report

    def _snapshot(self) -> tuple[dict, dict, float, float]:
        with self._lock:
            return (
                {key: list(chain) for key, chain in self._chains.items()},
                dict(self._names),
                self._newest_t,
                self._newest_local,
            )

    # ------------------------------------------------------------------ #
    # frame series for the graphs
    # ------------------------------------------------------------------ #
    def frame_series(self, seconds: float = 10.0) -> list[tuple[float, float]]:
        """[(seconds_relative_to_now, frametime_ms)] of the tracked swap chain.

        Present-to-present times are used, exactly like RTSS or CapFrameX, so the
        graph is comparable with other tools.
        """
        chains, names, newest_t, _ = self._snapshot()
        if not chains or not newest_t:
            return []
        present_pids = {pid for pid, _ in chains}
        pid = self._pinned_pid if self._pinned_pid in present_pids else self._active_pid
        if pid is None or pid not in present_pids:
            pid = self._choose_pid(chains, newest_t, names)
        if pid is None:
            return []
        key = self._busiest_chain(chains, pid, newest_t)
        cutoff = newest_t - seconds * 1000.0
        return [
            ((frame.t - newest_t) / 1000.0, frame.present)
            for frame in chains[key]
            if frame.t >= cutoff
        ]

    def stats(self, seconds: float | None = None) -> dict[str, float]:
        """Aggregate numbers for the frame-time panel."""
        series = self.frame_series(seconds if seconds is not None else self.low_window)
        if not series:
            return {}
        times = [value for _, value in series]
        result = {
            "samples": float(len(times)),
            "avg": fmean(times),
            "min": min(times),
            "max": max(times),
        }
        result.update(percentiles(times))
        return result

    # ------------------------------------------------------------------ #
    # active process selection
    # ------------------------------------------------------------------ #
    def set_pinned(self, pid: int | None) -> None:
        self._pinned_pid = pid

    def pinned(self) -> int | None:
        return self._pinned_pid

    def candidates(self) -> list[tuple[int, str, float]]:
        """[(pid, name, fps)] sorted by frame rate - used by the UI picker."""
        chains, names, newest_t, _ = self._snapshot()
        cutoff = newest_t - self.fps_window * 1000.0
        rates: dict[int, int] = {}
        for (pid, _chain), frames in chains.items():
            rates[pid] = rates.get(pid, 0) + sum(1 for f in frames if f.t >= cutoff)
        result = [
            (pid, names.get(pid, f"pid {pid}"), count / self.fps_window)
            for pid, count in rates.items()
            if count
        ]
        result.sort(key=lambda item: item[2], reverse=True)
        return result

    def _busiest_chain(self, chains: dict, pid: int, newest_t: float) -> tuple[int, str]:
        """The swap chain of ``pid`` that is actually putting frames on screen."""
        cutoff = newest_t - self.fps_window * 1000.0
        best_key: tuple[int, str] | None = None
        best_count = -1
        for key, frames in chains.items():
            if key[0] != pid:
                continue
            count = sum(1 for f in frames if f.t >= cutoff)
            if count > best_count:
                best_key, best_count = key, count
        if best_key is None:  # nothing in the window - use the longest history
            candidates = [key for key in chains if key[0] == pid]
            best_key = max(candidates, key=lambda key: len(chains[key]))
        return best_key

    def _choose_pid(self, chains: dict, newest_t: float, names: dict) -> int | None:
        if self._pinned_pid is not None:
            return self._pinned_pid

        now = time.monotonic()
        fg_pid = self.ctx.fg_pid
        fg_name = (self.ctx.fg_name or "").lower()
        looks_like_shell = fg_name in SHELL_PROCESSES or fg_pid == os.getpid()
        present_pids = {pid for pid, _ in chains}

        if fg_pid and not looks_like_shell and fg_pid in present_pids:
            self._active_pid = fg_pid
            self._active_seen = now
        elif (
            self._active_pid is not None
            and self._active_pid in present_pids
            and now - self._active_seen <= self.sticky_seconds
        ):
            pass  # keep showing the game while the user alt-tabs away
        else:
            self._active_pid = None

        if self._active_pid is not None:
            return self._active_pid

        # Nothing in front: fall back to the hardest-working presenter that is
        # not a shell window, which is usually the running game.
        cutoff = newest_t - self.fps_window * 1000.0
        best_pid, best_fps = None, 0.0
        for (pid, _chain), frames in chains.items():
            if pid == os.getpid():
                continue
            if (names.get(pid, "") or "").lower() in SHELL_PROCESSES:
                continue
            rate = sum(1 for f in frames if f.t >= cutoff) / self.fps_window
            if rate > best_fps:
                best_pid, best_fps = pid, rate
        if best_pid is not None:
            self._active_pid = best_pid
            self._active_seen = now
        return best_pid
