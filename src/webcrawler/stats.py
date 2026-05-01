"""Live crawl metrics.

A single `Stats` instance is shared by the engine and the TUI. All updates
are hot-path so we avoid any locking - assignment and integer increment
are atomic enough under CPython's GIL for this use case (we only read
snapshots from the UI task, which runs in the same event loop).
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class StatusCounts:
    ok: int = 0       # 2xx
    redirect: int = 0 # 3xx (rare with follow_redirects=True)
    client: int = 0   # 4xx
    server: int = 0   # 5xx
    other: int = 0    # 0 / unknown


@dataclass(slots=True)
class Stats:
    started_at: float = field(default_factory=time.monotonic)

    enqueued: int = 0
    dropped_scope: int = 0
    dropped_dedup: int = 0
    dropped_robots: int = 0
    dropped_extension: int = 0

    fetched: int = 0
    fetch_errors: int = 0
    bytes_in: int = 0
    links_extracted: int = 0
    rows_written: int = 0

    status: StatusCounts = field(default_factory=StatusCounts)

    domains: Counter[str] = field(default_factory=Counter)
    recent_errors: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=20))
    recent_urls: deque[tuple[int, str]] = field(default_factory=lambda: deque(maxlen=10))

    # Sliding-window throughput.
    _ticks: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(maxlen=60), repr=False
    )

    def record_status(self, code: int) -> None:
        if 200 <= code < 300:
            self.status.ok += 1
        elif 300 <= code < 400:
            self.status.redirect += 1
        elif 400 <= code < 500:
            self.status.client += 1
        elif 500 <= code < 600:
            self.status.server += 1
        else:
            self.status.other += 1

    def record_error(self, url: str, err: str) -> None:
        self.fetch_errors += 1
        self.recent_errors.append((url, err))

    def record_url(self, code: int, url: str) -> None:
        self.recent_urls.append((code, url))

    def tick(self) -> None:
        now = time.monotonic()
        self._ticks.append((now, self.fetched))

    @property
    def uptime(self) -> float:
        return max(1e-9, time.monotonic() - self.started_at)

    @property
    def rate_lifetime(self) -> float:
        return self.fetched / self.uptime

    @property
    def rate_recent(self) -> float:
        if len(self._ticks) < 2:
            return 0.0
        first_t, first_n = self._ticks[0]
        last_t, last_n = self._ticks[-1]
        dt = last_t - first_t
        if dt <= 0:
            return 0.0
        return (last_n - first_n) / dt

    @property
    def projected_per_day(self) -> float:
        return self.rate_recent * 86400.0
