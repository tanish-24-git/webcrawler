"""Crawl engine.

Composes frontier + fetcher + parser + dedup + robots + storage into a
worker pool. Workers run forever pulling from the frontier and pushing
discovered links back. The engine shuts down cleanly when:

  1. SIGINT / SIGTERM is received, or
  2. `max_pages` is reached, or
  3. The frontier is closed and drained.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp

from webcrawler.config import CrawlConfig
from webcrawler.dedup import make_seen_set
from webcrawler.fetcher import FetchResult, build_session, fetch
from webcrawler.frontier import CrawlTask, Frontier
from webcrawler.parser import parse_html
from webcrawler.politeness import HostLimiter
from webcrawler.robots import RobotsCache
from webcrawler.stats import Stats
from webcrawler.storage import CsvWriter
from webcrawler.url_utils import (
    has_blocked_extension,
    host_of,
    in_scope,
    normalize_url,
    registered_domain,
)

logger = logging.getLogger("webcrawler.engine")


class CrawlEngine:
    """The main crawl orchestrator. One instance per crawl."""

    def __init__(self, config: CrawlConfig, stats: Stats | None = None) -> None:
        self.config = config
        self.stats = stats or Stats()

        self.frontier = Frontier()
        self.seen = make_seen_set(config.bloom_capacity, config.bloom_error_rate)
        self.host_limiter = HostLimiter(config.per_host_concurrency)
        self.robots = RobotsCache(user_agent=config.user_agent, timeout=config.connect_timeout)
        self.csv = CsvWriter(config.output_csv, rotate_every=config.rotate_every)

        self._session: aiohttp.ClientSession | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()

        self._seed_hosts: set[str] = set()
        self._seed_domains: set[str] = set()

    async def run(self) -> None:
        await self._enqueue_seeds()
        if self.frontier.size == 0:
            logger.error("no valid seeds; nothing to crawl")
            return

        await self.csv.start()
        self._session = build_session(self.config)
        try:
            self._workers = [
                asyncio.create_task(self._worker(i), name=f"worker-{i}")
                for i in range(self.config.workers)
            ]
            await self._stop.wait()
        finally:
            await self._shutdown()

    def request_stop(self) -> None:
        if not self._stop.is_set():
            logger.info("stop requested; draining workers")
            self._stop.set()

    async def _shutdown(self) -> None:
        await self.frontier.close()
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._workers.clear()
        if self._session is not None:
            await self._session.close()
            self._session = None
        await self.csv.stop()

    async def _enqueue_seeds(self) -> None:
        tasks: list[CrawlTask] = []
        for raw in self.config.seeds:
            url = normalize_url(raw)
            if not url:
                logger.warning("invalid seed: %s", raw)
                continue
            host = host_of(url)
            if host:
                self._seed_hosts.add(host)
            self._seed_domains.add(registered_domain(url))
            if self.seen.add(url):
                tasks.append(CrawlTask(url=url, depth=0, parent=""))
                self.stats.enqueued += 1
        await self.frontier.push_many(tasks)

    async def _worker(self, worker_id: int) -> None:
        assert self._session is not None
        while not self._stop.is_set():
            task = await self.frontier.pop()
            if task is None:
                # Frontier drained while crawl was already stopping.
                if self.frontier.size == 0 and self.frontier.is_closed:
                    return
                continue

            host = host_of(task.url)
            try:
                await self._process(task, host)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the worker loop alive
                logger.exception("worker %d failed on %s", worker_id, task.url)
            finally:
                # Release the host so its next task becomes eligible.
                delay = max(
                    self.config.per_host_min_interval,
                    self.config.default_crawl_delay,
                )
                await self.frontier.release(host, delay)

            if self.config.max_pages and self.stats.fetched >= self.config.max_pages:
                self.request_stop()
                return

    async def _process(self, task: CrawlTask, host: str) -> None:
        assert self._session is not None
        config = self.config

        if config.respect_robots:
            allowed, crawl_delay = await self.robots.allowed(self._session, task.url)
            if not allowed:
                self.stats.dropped_robots += 1
                return
        else:
            crawl_delay = 0.0

        async with self.host_limiter.slot(host):
            result = await fetch(self._session, task.url, config)

        await self._record(task, result)

        if result.error or not result.body:
            if crawl_delay:
                await self.frontier.release(host, crawl_delay)
            return

        if not _is_html(result.content_type):
            return

        if task.depth >= config.max_depth:
            return

        await self._enqueue_links(task, result)

        if crawl_delay:
            await self.frontier.release(host, crawl_delay)

    async def _record(self, task: CrawlTask, result: FetchResult) -> None:
        self.stats.fetched += 1
        self.stats.bytes_in += len(result.body)
        if result.error:
            self.stats.record_error(task.url, result.error)
        else:
            self.stats.record_status(result.status)
            self.stats.record_url(result.status, task.url)
            self.stats.domains[host_of(task.url)] += 1

        title = ""
        if not result.error and _is_html(result.content_type) and result.body:
            try:
                title = parse_html(result.body, result.content_type).title
            except Exception:
                title = ""

        row = (
            task.url,
            result.url or task.url,
            result.status,
            result.content_type,
            len(result.body),
            task.depth,
            task.parent,
            title,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            int(result.elapsed * 1000),
            result.error,
        )
        await self.csv.write_row(row)
        self.stats.rows_written += 1

    async def _enqueue_links(self, task: CrawlTask, result: FetchResult) -> None:
        config = self.config
        try:
            page = parse_html(result.body, result.content_type)
        except Exception:
            return

        next_depth = task.depth + 1
        new_tasks: list[CrawlTask] = []
        for href in page.links:
            self.stats.links_extracted += 1
            url = normalize_url(href, base=result.url or task.url)
            if not url:
                continue
            if has_blocked_extension(url, config.blocked_extensions):
                self.stats.dropped_extension += 1
                continue
            if not in_scope(
                url,
                self._seed_hosts,
                self._seed_domains,
                same_domain_only=config.same_domain_only,
                same_registered_domain=config.same_registered_domain,
                allow_subdomains=config.allow_subdomains,
            ):
                self.stats.dropped_scope += 1
                continue
            if not self.seen.add(url):
                self.stats.dropped_dedup += 1
                continue
            new_tasks.append(CrawlTask(url=url, depth=next_depth, parent=task.url))
            self.stats.enqueued += 1

        if new_tasks:
            await self.frontier.push_many(new_tasks)


def _is_html(content_type: str) -> bool:
    if not content_type:
        return False
    return content_type.startswith(("text/html", "application/xhtml"))
