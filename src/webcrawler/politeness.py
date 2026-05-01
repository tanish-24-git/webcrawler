"""Per-host concurrency limiter.

The frontier already serializes a host's *next-fetch time* so we don't
hammer a single origin. This module additionally caps the number of
*in-flight* requests to a single host, which matters when crawl-delay is
zero and a host has thousands of URLs queued.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class HostLimiter:
    """Async semaphore-per-host with lazy creation."""

    __slots__ = ("_limit", "_sems")

    def __init__(self, per_host_concurrency: int) -> None:
        if per_host_concurrency < 1:
            raise ValueError("per_host_concurrency must be >= 1")
        self._limit = per_host_concurrency
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _sem(self, host: str) -> asyncio.Semaphore:
        sem = self._sems.get(host)
        if sem is None:
            sem = asyncio.Semaphore(self._limit)
            self._sems[host] = sem
        return sem

    @asynccontextmanager
    async def slot(self, host: str):
        sem = self._sem(host)
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()
