"""Thread-safe holder of the newest values plus a rolling history."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class State:
    def __init__(self, history_seconds: float = 600.0) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, float | None] = {}
        self._text: dict[str, str] = {}
        self._status: dict[str, tuple[str, str]] = {}
        self._history: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._history_seconds = history_seconds
        self._cores: list[float] = []
        self.last_update = 0.0
        self.sample_count = 0

    # ------------------------------------------------------------------ #
    def publish(
        self,
        values: dict[str, float | None],
        text: dict[str, str],
        status: dict[str, tuple[str, str]],
        cores: list[float] | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            self._values.update(values)
            self._text.update(text)
            self._status = dict(status)
            if cores is not None:
                self._cores = list(cores)
            self.last_update = now
            self.sample_count += 1
            cutoff = now - self._history_seconds
            for key, value in values.items():
                if value is None:
                    continue
                track = self._history[key]
                track.append((now, float(value)))
                while track and track[0][0] < cutoff:
                    track.popleft()

    # ------------------------------------------------------------------ #
    def snapshot(self) -> tuple[dict, dict, dict]:
        with self._lock:
            return dict(self._values), dict(self._text), dict(self._status)

    def value(self, key: str) -> float | None:
        with self._lock:
            return self._values.get(key)

    def cores(self) -> list[float]:
        """Per-logical-core load, newest sample."""
        with self._lock:
            return list(self._cores)

    def history(self, key: str, seconds: float | None = None) -> list[tuple[float, float]]:
        with self._lock:
            track = list(self._history.get(key, ()))
        if seconds is None or not track:
            return track
        cutoff = track[-1][0] - seconds
        return [item for item in track if item[0] >= cutoff]
