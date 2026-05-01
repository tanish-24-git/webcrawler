# Architecture

This document is a module-by-module walkthrough of the crawler. It
assumes you have read the README and want to understand how the pieces
fit together before changing anything.

## High-level shape

```
                     +-----------------------+
                     |  cli.py (typer)       |
                     |  - parse flags        |
                     |  - build CrawlConfig  |
                     +-----------+-----------+
                                 |
                                 v
                     +-----------------------+
                     |  crawler.CrawlEngine  |
                     |  (orchestrator)       |
                     +-----+-----+-----+-----+
                           |     |     |
        +------------------+     |     +-------------------+
        |                        |                         |
        v                        v                         v
  +-----------+           +-------------+            +-----------+
  | Frontier  |<--------->| WorkerPool  |<-------->  | CsvWriter |
  | per-host  |  pop/push | N coroutines|  rows      | streaming |
  | + heap    |           | each calls: |            | + rotation|
  +-----------+           |  robots     |            +-----------+
                          |  fetcher    |
                          |  parser     |
                          |  scope/dedup|
                          +-------------+
                              ^     ^
                              |     |
                       +------+     +-------+
                       |                    |
                +-------------+      +--------------+
                | RobotsCache |      | aiohttp      |
                | per-host    |      | ClientSession|
                | robots.txt  |      | (single)     |
                +-------------+      +--------------+
```

A single asyncio event loop runs:

- `N` worker coroutines (default 1024) sharing one `aiohttp.ClientSession`.
- One CSV writer coroutine draining a bounded queue.
- One TUI coroutine sampling shared state at ~4 Hz.

There are no threads. There is no multiprocessing in the default
build. Everything is cooperative on top of asyncio.

## Module reference

### `config.py`

`CrawlConfig` is a frozen-ish dataclass that holds every knob the
crawler exposes. The CLI builds one of these and hands it to the
engine. Defaults are tuned for "broad open-web crawl on a beefy VM"
rather than "polite single-site scrape" - tighten them for the latter.

### `url_utils.py`

URL normalization is the single most important correctness primitive
in the crawler. Without it, `https://example.com`, `https://example.com/`,
`https://example.com/?utm_source=x`, and `HTTPS://Example.com:443/` all
generate distinct frontier entries and the dedup table balloons.

What `normalize_url` does:

1. Resolve relative URLs against a base.
2. Strip fragments (`#section`).
3. Lowercase the scheme and host.
4. Drop default ports (80/443).
5. Ensure a path of at least `/`.
6. Sort query parameters and drop a curated list of tracking
   parameters (`utm_*`, `gclid`, `fbclid`, etc.).
7. Reject non-http/https schemes.

`registered_domain` uses `tldextract` against a bundled public-suffix
list (no network) so we can correctly tell `bbc.co.uk` from
`example.co.uk` (different sites) but recognize `news.example.com` and
`shop.example.com` as the same registered domain.

### `dedup.py`

Two implementations behind one protocol:

- `ExactSeenSet`: a Python `set[str]`. Used automatically when
  `bloom_capacity <= 1_000_000`.
- `BloomSeenSet`: `pybloom_live.ScalableBloomFilter`. Used for very
  large crawls. False positives cause us to *skip* a URL we have not
  actually seen, which is acceptable - we accept some lost coverage in
  exchange for staying inside RAM at 100M+ URLs. False negatives are
  impossible.

Capacity vs RAM (rule of thumb): 1.44 \* capacity \* log2(1/p) bits.
At p=0.001 and capacity=200M, that is ~340 MiB.

### `frontier.py`

Mercator-style per-host queue. Implementation:

- `_hosts: dict[str, deque]` - one FIFO per host.
- `_ready_heap: list[_HostSlot]` - a min-heap keyed by
  `next_eligible_time`.
- A condition variable so `pop()` blocks efficiently when no host is
  eligible yet.

The crucial invariant: while a host has a task in flight, it is *not*
on the ready heap. The worker calls `release(host, delay)` after each
fetch, which puts the host back on the heap with `ready_at = now + delay`.
This is what makes high concurrency and politeness coexist - we never
have two workers fighting over the same host's next request.

### `fetcher.py`

Thin wrapper over `aiohttp.ClientSession.get`. The interesting bits:

- One shared session for the lifetime of the crawl, with a
  `TCPConnector` configured for high concurrency and DNS caching.
- Configurable total/connect/read timeouts; defaults to 30s total.
- A capped read (`_read_capped`) so a misbehaving server cannot exhaust
  RAM by streaming us a 10 GB body.
- Content-type filtering before reading the body, so we do not
  download a 200 MB video to discover it was not HTML.
- Structured `FetchResult` with `error` field. The fetcher never
  raises; it converts every failure to a tagged `FetchResult` so the
  worker loop stays simple.

### `parser.py`

`selectolax` over `BeautifulSoup`. Roughly 10x faster on the workload
(many small HTML pages). The parser only extracts:

- The `<title>` text.
- All `href` attributes from `<a>` elements.
- A `<base href>` if present, applied to relative hrefs.

Decoding strategy: trust `Content-Type: charset=` first, then `utf-8`,
then `latin-1` with `errors="replace"`. This is sufficient to extract
links from real-world pages without trying to be a full encoding
detector.

### `robots.py`

Per-host `robots.txt` with a write-through cache. Uses the stdlib
`urllib.robotparser`. We additionally read `Crawl-delay` (an
unofficial but widely-supported directive) and surface it to the
frontier - if a site asks for 5 seconds between requests, we honor
it.

A failure to fetch `robots.txt` (404, network error, malformed
content) is treated as "no rules" - i.e. we proceed with default
politeness. This matches what most well-behaved crawlers do.

### `politeness.py`

A small utility: `HostLimiter` lazily creates an `asyncio.Semaphore`
per host with the configured max-concurrent in-flight limit. The
frontier handles *temporal* spacing; this handles *concurrent*
spacing. They are different controls and you want both.

### `storage.py`

A single async task drains a bounded queue and writes rows. The
writer:

- Opens the CSV in append mode and writes the header only if the file
  is new.
- Rotates to `crawl.part00001.csv`, `crawl.part00002.csv`, etc. once
  `rotate_every` rows have been written. Set `rotate_every=0` to
  disable.
- Flushes once per second so a `kill -9` of the process loses no more
  than one second of data.

Funneling all writes through one task means we never pay the cost of
file locking and we never produce interleaved rows.

### `stats.py`

A plain dataclass, not a metrics library. Updates are direct field
mutations from the worker loop. This is safe because there are no
threads - all writes happen on the same event loop, and the TUI reads
snapshots between awaits. No locks, no atomics, no cost on the hot
path.

`rate_recent` is computed from a 60-tick sliding window populated by
the TUI task; that gives a smooth pages-per-second figure that
responds quickly to changes in the crawl shape.

### `tui.py`

`rich.live.Live` rendering a `rich.layout.Layout` once per refresh
tick (default 4 Hz). All panels read from the shared `Stats`
instance. The dashboard is purely a viewer - it never modifies state.

If you don't want a TUI (CI, `nohup`), pass `--no-tui` and the engine
runs without it. The CSV is the source of truth either way.

### `crawler.py`

The orchestrator. `CrawlEngine.run()`:

1. Normalize seeds, push them onto the frontier, register them as the
   in-scope domain set.
2. Open the CSV writer.
3. Build the shared `aiohttp.ClientSession`.
4. Spawn `config.workers` worker coroutines.
5. Wait for `_stop`. The stop event is set by signal handler,
   `max_pages` reached, or frontier-drained-and-closed.
6. Cancel workers, drain the CSV queue, close the session.

Each worker loop:

```
loop:
    task = await frontier.pop()
    if task is None: return
    host = host_of(task.url)
    try:
        await process(task, host)
    finally:
        await frontier.release(host, delay)
    if max_pages reached: stop and return
```

`process()` is the per-URL pipeline: robots check -> per-host slot ->
fetch -> record (CSV row + stats) -> if HTML: parse, normalize,
scope-filter, dedup, enqueue children.

## Failure modes and what happens

| Failure                                  | Behavior                              |
| :--------------------------------------- | :------------------------------------ |
| DNS error                                | `error=connect:...`, no retry         |
| TCP connect refused                      | `error=connect:...`, no retry         |
| TLS handshake fail                       | `error=connect:...`, no retry         |
| Read timeout                             | `error=timeout`                       |
| 4xx/5xx response                         | Recorded with the status code         |
| Body exceeds `max_response_bytes`        | Body truncated, page still processed  |
| Malformed HTML                           | `parse_html` returns empty links      |
| `robots.txt` unreachable                 | Treated as no rules                   |
| `robots.txt` disallows the URL           | Counted as `dropped_robots`, not fetched |
| Worker raises                            | Logged with traceback, worker continues|
| Ctrl+C                                   | Stop event set, in-flight drained, CSV flushed |

## Concurrency model: why no threads

- Python's GIL kills any benefit of threads for this workload.
- The work is dominated by I/O wait, which is what asyncio is for.
- HTML parsing is the only CPU-heavy step and it is short enough
  (microseconds for typical pages with selectolax) that pre-emption
  is not necessary.
- Avoiding threads avoids a class of subtle bugs in shared-state
  updates that would otherwise need locks.

If parsing ever becomes the bottleneck (it will not on commodity
hardware below ~50 MB/s of HTML throughput), a `ProcessPoolExecutor`
fan-out from the worker is a clean addition.
