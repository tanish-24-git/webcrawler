"""robots.txt fetching, parsing, and caching.

A well-behaved crawler hits /robots.txt once per host and caches the result.
We use Python's stdlib `urllib.robotparser`, which implements the original
spec, plus an extension for the (de-facto-standard) `Crawl-delay` directive.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp


@dataclass(slots=True)
class RobotsRecord:
    parser: RobotFileParser
    crawl_delay: float = 0.0
    fetched: bool = False


@dataclass(slots=True)
class RobotsCache:
    """Async-safe per-host robots.txt cache."""

    user_agent: str
    timeout: float = 10.0
    _records: dict[str, RobotsRecord] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def allowed(self, session: aiohttp.ClientSession, url: str) -> tuple[bool, float]:
        """Return (is_allowed, crawl_delay_seconds) for `url`."""
        parts = urlsplit(url)
        host = parts.netloc
        if not host:
            return True, 0.0

        record = self._records.get(host)
        if record is None or not record.fetched:
            async with self._lock_for(host):
                record = self._records.get(host)
                if record is None or not record.fetched:
                    record = await self._fetch(session, parts.scheme, host)
                    self._records[host] = record

        try:
            allowed = record.parser.can_fetch(self.user_agent, url)
        except Exception:
            allowed = True
        return allowed, record.crawl_delay

    async def _fetch(
        self, session: aiohttp.ClientSession, scheme: str, host: str
    ) -> RobotsRecord:
        rp = RobotFileParser()
        record = RobotsRecord(parser=rp, fetched=True)
        url = f"{scheme}://{host}/robots.txt"
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                allow_redirects=True,
            ) as resp:
                if resp.status >= 400:
                    rp.parse([])
                    return record
                body = await resp.text(errors="replace")
        except Exception:
            rp.parse([])
            return record

        rp.parse(body.splitlines())
        delay = rp.crawl_delay(self.user_agent)
        if delay is None:
            delay = rp.crawl_delay("*")
        if delay is not None:
            try:
                record.crawl_delay = float(delay)
            except (TypeError, ValueError):
                record.crawl_delay = 0.0
        return record
