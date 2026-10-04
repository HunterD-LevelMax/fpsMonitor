"""Common plumbing shared by all metric sources.

Every source owns a background thread that refreshes a cached report, so a slow
provider (spawning nvidia-smi, round-tripping through PowerShell) can never
stall the UI or the sampling loop.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class SourceStatus(str, Enum):
    OK = "ok"
    STARTING = "starting"
    UNAVAILABLE = "unavailable"


@dataclass
class SourceReport:
    """What a source contributes to one sample."""

    values: dict[str, float] = field(default_factory=dict)
    text: dict[str, str] = field(default_factory=dict)
    # non-scalar payloads (lists, dicts) that must not enter the float registry
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class Context:
    """Shared, mutable view of what the user is currently looking at."""

    fg_pid: int = 0
    fg_name: str = ""
    fg_title: str = ""


class Source:
    name = "source"
    title = "Source"
    interval = 1.0

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._last = SourceReport()
        self._last_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = SourceStatus.STARTING
        self._message = "запуск"
        self._lock = threading.Lock()

    @property
    def stale_after(self) -> float:
        """How long a cached report stays valid without a fresh refresh."""
        return max(3.0, self.interval * 5.0)

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                report = self.refresh()
                if report is not None:
                    self._last = report
                    self._last_at = time.monotonic()
            except Exception as exc:  # keep the app alive, report the reason
                self.set_status(SourceStatus.UNAVAILABLE, f"{type(exc).__name__}: {exc}")
            self._stop.wait(max(0.05, self.interval - (time.monotonic() - started)))

    def stop(self) -> None:
        self._stop.set()
        try:
            self.close()
        except Exception:
            pass

    # -- overridable ----------------------------------------------------
    def refresh(self) -> SourceReport | None:
        return None

    def close(self) -> None:
        pass

    # -- accessors ------------------------------------------------------
    def poll(self) -> SourceReport:
        """Latest report, or an empty one when the source went quiet.

        Without this a stalled provider (PresentMon losing its session, a
        driver that stopped answering) would keep replaying its last numbers
        forever as if they were live.
        """
        if self._last_at and time.monotonic() - self._last_at > self.stale_after:
            return SourceReport()
        return self._last

    def set_status(self, status: SourceStatus, message: str) -> None:
        with self._lock:
            self._status = status
            self._message = message

    def status(self) -> tuple[SourceStatus, str]:
        with self._lock:
            return self._status, self._message
