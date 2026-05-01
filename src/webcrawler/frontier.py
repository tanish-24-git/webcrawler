"""Crawl frontier: the queue of URLs waiting to be fetched.

We use a per-host queue scheme (Mercator-style). Each host has its own FIFO.
A scheduler hands out the host whose next-allowed-fetch time has passed,
which is what makes politeness throttling and high concurrency coexist.

Single-process, asyncio-native. Swap in `RedisFrontier` for distributed
operation (see docs/SCALING.md).
"""

from __future__ import annotations

import asyncio
import heapq
import time
from collections import deque
from dataclasses import dataclass, field

from webcrawler.url_utils import host_of


@dataclass(slots=True, order=True)
class _HostSlot:
    """Heap entry: (next_eligible_time, host). Order by time then host."""

    ready_at: float
    host: str = field(compare=True)


@dataclass(slots=True)
class CrawlTask:
    url: str
    depth: int
    parent: str = ""


class Frontier:
    """Per-host async URL queue with politeness-aware scheduling.

    `pop()` blocks until a host is eligible (its next-allowed time has
    arrived) and returns one URL from that host. `release(host, delay)`
    marks the host as ready again after `delay` seconds.
    """

    def __init__(self) -> None:
        self._hosts: dict[str, deque[CrawlTask]] = {}
        self._ready_heap: list[_HostSlot] = []
        self._in_heap: set[str] = set()
        self._size = 0
        self._cv = asyncio.Condition()
        self._closed = False

    async def push(self, task: CrawlTask) -> None:
        host = host_of(task.url)
        if not host:
            return
        async with self._cv:
            queue = self._hosts.get(host)
            if queue is None:
                queue = deque()
                self._hosts[host] = queue
                heapq.heappush(self._ready_heap, _HostSlot(time.monotonic(), host))
                self._in_heap.add(host)
            queue.append(task)
            self._size += 1
            self._cv.notify()

    async def push_many(self, tasks: list[CrawlTask]) -> None:
        if not tasks:
            return
        async with self._cv:
            now = time.monotonic()
            for task in tasks:
                host = host_of(task.url)
                if not host:
                    continue
                queue = self._hosts.get(host)
                if queue is None:
                    queue = deque()
                    self._hosts[host] = queue
                    heapq.heappush(self._ready_heap, _HostSlot(now, host))
                    self._in_heap.add(host)
                queue.append(task)
                self._size += 1
            self._cv.notify_all()

    async def pop(self) -> CrawlTask | None:
        """Wait for an eligible task. Return None when frontier is closed and drained."""
        async with self._cv:
            while True:
                if self._closed and self._size == 0:
                    return None

                now = time.monotonic()
                if self._ready_heap and self._ready_heap[0].ready_at <= now:
                    slot = heapq.heappop(self._ready_heap)
                    self._in_heap.discard(slot.host)
                    queue = self._hosts.get(slot.host)
                    if queue:
                        task = queue.popleft()
                        self._size -= 1
                        # Host stays out of the heap until release() returns it.
                        if not queue:
                            self._hosts.pop(slot.host, None)
                        return task
                    continue

                if not self._ready_heap:
                    if self._closed:
                        return None
                    await self._cv.wait()
                    continue

                wait = max(0.0, self._ready_heap[0].ready_at - now)
                try:
                    await asyncio.wait_for(self._cv.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass

    async def release(self, host: str, delay: float) -> None:
        """Mark `host` as eligible again after `delay` seconds."""
        if not host:
            return
        async with self._cv:
            if host in self._in_heap:
                return
            queue = self._hosts.get(host)
            if not queue:
                return
            ready_at = time.monotonic() + max(0.0, delay)
            heapq.heappush(self._ready_heap, _HostSlot(ready_at, host))
            self._in_heap.add(host)
            self._cv.notify_all()

    async def close(self) -> None:
        async with self._cv:
            self._closed = True
            self._cv.notify_all()

    @property
    def size(self) -> int:
        return self._size

    @property
    def host_count(self) -> int:
        return len(self._hosts)

    @property
    def is_closed(self) -> bool:
        return self._closed
