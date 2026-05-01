"""Streaming CSV writer.

Writes are funneled through a single asyncio task so we don't pay the cost
of file-locking from many workers and don't risk row interleaving. Output
files rotate after `rotate_every` rows so very long crawls don't end up
with a single multi-GB CSV.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import IO

CSV_HEADER = (
    "url",
    "final_url",
    "status_code",
    "content_type",
    "content_length",
    "depth",
    "parent_url",
    "title",
    "fetched_at",
    "elapsed_ms",
    "error",
)


class CsvWriter:
    """Async-safe rotating CSV writer."""

    def __init__(self, path: Path, rotate_every: int = 0) -> None:
        self._base = Path(path)
        self._rotate = max(0, int(rotate_every))
        self._queue: asyncio.Queue[tuple | None] = asyncio.Queue(maxsize=10_000)
        self._task: asyncio.Task[None] | None = None
        self._fh: IO[str] | None = None
        self._writer: "csv.writer | None" = None
        self._rows_in_shard = 0
        self._shard = 0
        self._total_rows = 0

    async def start(self) -> None:
        self._base.parent.mkdir(parents=True, exist_ok=True)
        self._open_shard()
        self._task = asyncio.create_task(self._run(), name="csv-writer")

    async def write_row(self, row: tuple) -> None:
        await self._queue.put(row)

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.put(None)
        await self._task
        self._task = None
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    @property
    def total_rows(self) -> int:
        return self._total_rows

    def _shard_path(self) -> Path:
        if self._rotate == 0:
            return self._base
        stem = self._base.stem
        suffix = self._base.suffix or ".csv"
        return self._base.with_name(f"{stem}.part{self._shard:05d}{suffix}")

    def _open_shard(self) -> None:
        path = self._shard_path()
        existed = path.exists() and path.stat().st_size > 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh, quoting=csv.QUOTE_MINIMAL)
        if not existed:
            self._writer.writerow(CSV_HEADER)
            self._fh.flush()

    def _rotate_shard(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
        self._shard += 1
        self._rows_in_shard = 0
        self._open_shard()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last_flush = loop.time()
        while True:
            row = await self._queue.get()
            if row is None:
                if self._fh is not None:
                    self._fh.flush()
                return
            assert self._writer is not None and self._fh is not None
            self._writer.writerow(row)
            self._rows_in_shard += 1
            self._total_rows += 1
            if self._rotate and self._rows_in_shard >= self._rotate:
                self._rotate_shard()
            now = loop.time()
            if now - last_flush > 1.0:
                self._fh.flush()
                last_flush = now
