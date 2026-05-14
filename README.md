# webcrawler

> A high-throughput, asynchronous web crawler with a live terminal dashboard.
> One command. CSV out. No browser, no server, no JavaScript engine.

[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](#roadmap)
[![Async](https://img.shields.io/badge/built%20on-aiohttp%20%2B%20selectolax-informational)](#how-it-works)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](docs/CONTRIBUTING.md)

```
 __        __   _      ____                    _
 \ \      / /__| |__  / ___|_ __ __ ___      _| | ___ _ __
  \ \ /\ / / _ \ '_ \| |   | '__/ _` \ \ /\ / / |/ _ \ '__|
   \ V  V /  __/ |_) | |___| | | (_| |\ V  V /| |  __/ |
    \_/\_/ \___|_.__/ \____|_|  \__,_| \_/\_/ |_|\___|_|
```

`webcrawler` is the crawler you reach for when you want **a CSV of every page
reachable from a seed URL, as fast as the network will allow, on commodity
hardware** - and you want to see it happening live in your terminal.

If you have ever started Scrapy and felt like you signed up for a framework
when you only wanted a tool, this is for you.

```bash
pip install -e .
webcrawler crawl https://example.com
```

That's it. No `scrapy startproject`. No spider class. No middleware pipeline.

---

## Table of contents

- [Why webcrawler](#why-webcrawler)
- [Highlights](#highlights)
- [Live dashboard](#live-dashboard)
- [Quickstart](#quickstart)
- [Compared to other tools](#compared-to-other-tools)
- [Use cases](#use-cases)
- [Throughput](#throughput)
- [Output schema](#output-schema)
- [How it works](#how-it-works)
- [Documentation](#documentation)
- [Project layout](#project-layout)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [License](#license)
- [Responsible use](#responsible-use)

---

## Why webcrawler

Most Python crawlers fall into one of two camps:

1. **Toy spiders** - a few hundred lines, synchronous, single-host, breaks at
   1,000 pages.
2. **Full frameworks** - Scrapy, Apify, etc. Powerful, but you have to bend
   your problem around the framework instead of the other way around.

`webcrawler` lives in the middle. It is built around a single, narrow contract:

> Given seed URLs, produce a CSV of every page reachable, as fast as the
> network and the politeness budget allow, on commodity hardware.

Everything in the codebase exists to serve that contract. No more, no less.

---

## Highlights

- **Async at the core.** A single `aiohttp.ClientSession` shared by 1,024+
  worker coroutines. Connection pooling, DNS caching, and `uvloop` support
  on Linux.
- **Polite by default.** Honors `robots.txt` per host (including
  `Crawl-delay`), enforces per-host concurrency caps, and a configurable
  per-host fetch interval.
- **Scalable dedup.** Canonicalizes URLs and runs them through a scalable
  bloom filter sized for hundreds of millions of candidates. Below 1M, the
  bloom filter is automatically swapped for an exact set.
- **Streaming output.** Every fetch (success or failure) becomes one row in
  a rotating CSV. No buffering surprises, no in-memory accumulation.
- **Live dashboard.** A Rich-powered TUI in the spirit of `htop` and `nmap` -
  throughput, status-code distribution, top domains, recent URLs, recent
  errors. Or run with `--no-tui` for CI and `nohup`.
- **Clean shutdown.** `Ctrl+C` drains workers, closes the connection pool,
  flushes the CSV, and prints a summary. No orphaned sockets, no half-written
  rows.
- **Typed, documented, MIT-licensed.** `py.typed`, module-by-module
  architecture docs, and a permissive license.

It does **not** render JavaScript, take screenshots, build a search index,
or extract page content beyond the title. Those are different problems, and
bolting them on would slow the crawler by 10x. See [How it works](#how-it-works).

---

## Live dashboard

A snapshot of what you see when you run `webcrawler crawl <url>`:

```
+----------------------------------------------------------------------------+
|                                                                            |
|    __        __   _      ____                    _                         |
|    \ \      / /__| |__  / ___|_ __ __ ___      _| | ___ _ __               |
|     \ \ /\ / / _ \ '_ \| |   | '__/ _` \ \ /\ / / |/ _ \ '__|              |
|      \ V  V /  __/ |_) | |___| | | (_| |\ V  V /| |  __/ |                 |
|       \_/\_/ \___|_.__/ \____|_|  \__,_| \_/\_/ |_|\___|_|                 |
|                                                                            |
|         high-throughput async crawler - press Ctrl+C to stop               |
+--------------------------------------+-------------------------------------+
| summary                              | throughput                          |
|   fetched         124,803            |   rate (1m)        892.4 pages/sec  |
|   queued           37,221            |   rate (life)      834.1 pages/sec  |
|   rows out        124,803            |   projected/day  72,065,000         |
|   errors             612             |   hosts                  3,418      |
|   bytes          5.8 GiB             |   links seen         1,948,712      |
|   target       1,000,000             |   2xx 118,902  3xx 4,910  4xx 612   |
|   progress         12.5%             |   5xx 379      dropped dedup 482k   |
|   uptime        00:02:29             |                                     |
+--------------------------------------+-------------------------------------+
| top domains                          | recent                              |
|   news.example.com         18,442    |   200 https://example.com/page/482  |
|   docs.example.com         12,901    |   301 https://example.com/old-url   |
|   blog.example.com          9,118    |   200 https://docs.example.com/...  |
|   ...                                |   404 https://example.com/missing   |
+--------------------------------------+-------------------------------------+
| recent errors                                                              |
|   timeout                  https://slow.example.com/loader                 |
|   connect:refused          https://down.example.net/                       |
+----------------------------------------------------------------------------+
|  workers 1024 / 4 per-host   scope same-registered-domain   depth 6        |
|  robots on   out out/crawl.csv                                             |
+----------------------------------------------------------------------------+
```

The dashboard refreshes at ~4 Hz with negligible overhead. For long
unattended runs, pass `--no-tui` and tail `logs/crawler.log` instead.

---

## Quickstart

Requires Python **3.10 or newer**.

```bash
git clone https://github.com/tanish-24-git/webcrawler
cd webcrawler
pip install -e .
```

On Linux, install the `uvloop` extra for a 1.5x to 2x event-loop speedup:

```bash
pip install -e ".[uvloop]"
```

**Crawl a single site** (default scope: same registered domain, depth 6,
live dashboard):

```bash
webcrawler crawl https://example.com
```

**Cap the crawl** at one million pages and write to a custom path:

```bash
webcrawler crawl https://example.com \
  --max-pages 1000000 \
  --output out/example.csv
```

**Open-web crawl**, headless, suitable for `nohup` / `screen` / CI:

```bash
webcrawler crawl https://news.ycombinator.com \
  --open-web \
  --depth 4 \
  --no-tui \
  --max-pages 5000000 \
  --workers 2048 \
  --per-host 4
```

**Multiple seeds, shared scope:**

```bash
webcrawler crawl https://example.com https://docs.example.com
```

Full flag reference: [docs/USAGE.md](docs/USAGE.md).

---

## Compared to other tools

|                              | webcrawler          | Scrapy             | Colly (Go)      | wget --mirror   |
| :--------------------------- | :------------------ | :----------------- | :-------------- | :-------------- |
| Setup before first crawl     | one `pip install`   | spider class + cfg | Go project      | none            |
| Concurrency model            | asyncio, 1024+      | twisted, ~100      | goroutines      | single-process  |
| Per-host politeness          | built-in            | built-in           | built-in        | manual          |
| `robots.txt`                 | built-in, per-host  | built-in           | built-in        | partial         |
| Live terminal dashboard      | yes (Rich)          | no                 | no              | no              |
| Output format                | streaming CSV       | items, pipelines   | callbacks       | files on disk   |
| Dedup at 100M+ URLs          | scaling bloom       | DIY                | DIY             | n/a             |
| JavaScript rendering         | no (by design)      | via plugin         | no              | no              |
| Learning curve               | minutes             | hours              | hours           | minutes         |
| Best at                      | wide CSV crawls     | structured ETL     | embedding in Go | single-site dl  |

If you need structured extraction with item pipelines, use Scrapy. If you
need a CSV of the link graph as fast as possible, stay here.

---

## Use cases

- **SEO and content audits.** Map every page on a site, capture status
  codes and titles, find broken links and redirects.
- **Link-graph research.** Build a graph for ranking, clustering, or
  recommendation work. The CSV is one row per edge.
- **Site migration QA.** Crawl staging, crawl production, diff the two
  CSVs.
- **Compliance checks.** Stream `(url, status, title)` to a data warehouse
  to verify that pages you expect to be live are actually live.
- **Dataset building.** Generate seed lists for downstream scrapers,
  classifiers, or LLM training pipelines.
- **Dead-link sweeping.** Filter the CSV to `status_code != 2xx` and you
  have a deadlink report.

If your use case needs JavaScript-rendered content, pair `webcrawler` with
a headless browser as a second pass on the resulting CSV.

---

## Throughput

The architecture is built to scale to the **100M pages/day** range, but let's
be honest about where that number actually lives:

| Setup                                          | Realistic ceiling    |
| :--------------------------------------------- | :------------------- |
| Laptop, residential connection                 | 1M - 3M pages/day    |
| Single VM, gigabit, broad seed list            | 5M - 20M pages/day   |
| Cluster, sharded frontier (Redis), 10+ workers | 100M+ pages/day      |

The single-process default in this repo gets you the first two rows out of
the box. The third row requires the distributed deployment described in
[docs/SCALING.md](docs/SCALING.md) - the codebase is structured so the
frontier and dedup layers can be swapped for network-backed implementations
without touching the engine.

What actually limits a single node:

1. **Per-host politeness** caps requests-per-second against any one origin.
   If you are crawling a single site, you are bounded by what that site will
   tolerate, not by your CPU.
2. **DNS** becomes the bottleneck above roughly 2,000 unique hosts/sec
   without a local resolver cache.
3. **TLS handshake CPU cost** dominates for short-lived connections, which
   is why the default uses connection pooling and `enable_cleanup_closed=True`.
4. **HTML parsing** - we use `selectolax`, not BeautifulSoup, because on a
   100k-page-per-hour budget the parser cost is non-trivial.

See [docs/PERFORMANCE.md](docs/PERFORMANCE.md) for a longer treatment.

---

## Output schema

The crawler writes a single streaming CSV (or rotated shards if you set
`--rotate-every`). Every fetch gets exactly one row, regardless of whether
it succeeded.

| Column           | Description                                              |
| :--------------- | :------------------------------------------------------- |
| `url`            | The URL we attempted to fetch (post-normalization).      |
| `final_url`      | The URL after following redirects.                       |
| `status_code`    | HTTP status, or `0` for transport-level failures.        |
| `content_type`   | The first part of the `Content-Type` header.             |
| `content_length` | Bytes actually read from the body (capped).              |
| `depth`          | Hops from the seed (seed = 0).                           |
| `parent_url`     | The page that linked to this one. Empty for seeds.       |
| `title`          | `<title>` text, truncated at 512 characters.             |
| `fetched_at`     | UTC ISO-8601 timestamp.                                  |
| `elapsed_ms`     | Round-trip time in milliseconds.                         |
| `error`          | Empty on success, otherwise a short failure tag.         |

Error tags currently in use: `timeout`, `too_many_redirects`,
`connect:<detail>`, `payload:<detail>`, `client:<detail>`,
`unicode:<detail>`, `unexpected:<detail>`, and
`skipped content-type: <ctype>`.

---

## How it works

One paragraph, then a pointer.

A pool of async workers shares a single `Frontier` (per-host FIFOs in a
ready-time min-heap), a `Seen` set (a scalable bloom filter at large
capacities), a `RobotsCache`, and a single `aiohttp.ClientSession`. Each
worker pops the next eligible URL, asks `RobotsCache` if the fetch is
allowed, fetches it under a per-host concurrency slot, parses the body with
`selectolax`, normalizes and scope-filters each discovered link, dedupes
against the bloom filter, and pushes the survivors back into the frontier.
A separate task drains a write queue into a rotating CSV. The TUI runs as
another async task that samples the shared `Stats` object on each frame.

For the long version, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Documentation

| Document                                              | What it covers                                     |
| :---------------------------------------------------- | :------------------------------------------------- |
| [docs/USAGE.md](docs/USAGE.md)                        | Every CLI flag, with examples.                     |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md)        | Every `CrawlConfig` field and what it does.        |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)          | Module-by-module design notes.                     |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md)            | Throughput tuning, real bottlenecks.               |
| [docs/SCALING.md](docs/SCALING.md)                    | Single-node to multi-node migration path.          |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)          | Dev environment, style, tests.                     |

---

## Project layout

```
webcrawler/
  pyproject.toml
  README.md
  LICENSE
  docs/
    ARCHITECTURE.md      module-by-module design notes
    USAGE.md             CLI reference
    CONFIGURATION.md     every CrawlConfig field, with rationale
    PERFORMANCE.md       throughput tuning
    SCALING.md           single-node -> multi-node migration path
    CONTRIBUTING.md      developer setup
  src/
    webcrawler/
      __init__.py
      __main__.py        `python -m webcrawler` entrypoint
      cli.py             typer commands
      config.py          CrawlConfig dataclass
      crawler.py         the engine + worker loop
      dedup.py           bloom + exact seen-set
      fetcher.py         aiohttp wrapper with sane defaults
      frontier.py        per-host queue + scheduler
      logging_setup.py   file logging config
      parser.py          selectolax-based HTML parsing
      politeness.py      per-host concurrency limiter
      robots.py          robots.txt cache
      stats.py           live metrics object
      storage.py         streaming rotating CSV writer
      tui.py             Rich live dashboard
      url_utils.py       URL normalization + scope checks
```

---

## FAQ

**Does it render JavaScript?**
No, and that is intentional. JavaScript rendering costs 100x more CPU and
memory per page than parsing static HTML, which is incompatible with the
"100k+ pages/hour on commodity hardware" goal. If you need rendered DOM,
run a second pass with a headless browser over the URLs the crawler
discovers.

**Can I crawl just one site, slowly and politely?**
Yes. The default scope is already the seed's registered domain. Add
`--per-host 1 --delay 1` to throttle to one request per second per host.

**How does it compare to Scrapy?**
Scrapy is a full ETL framework: spiders, items, pipelines, middlewares.
`webcrawler` is a single command that emits CSV. If you want structured
extraction with custom item types, use Scrapy. If you want the link graph
plus titles, stay here.

**Will it work on Windows?**
Yes. `uvloop` and `aiodns` are skipped automatically on Windows; everything
else works the same.

**What about resume support?**
v0.1 has none. Treat each crawl as a fresh start. Resume support is on the
[roadmap](#roadmap).

**Memory footprint on a 100M-URL crawl?**
The bloom filter at 200M capacity, 0.001 error rate is roughly 360 MB. The
frontier holds only pending tasks, which is bounded by your fetch rate; in
practice a few hundred MB total RSS at steady state.

**Can I send the rows somewhere other than CSV?**
Not yet via CLI. The `CsvWriter` is a thin module - point it at a queue or
database client and you have a sink swap. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Is it production-grade?**
It is Development Status: 4 - Beta. The engine is solid; the test suite is
not yet built. Use it where a re-run is cheap.

---

## Roadmap

- **Resume support** - persist the frontier and seen-set on shutdown, pick
  back up on restart.
- **Redis-backed frontier and seen-set** - swap-in implementations for
  cluster operation.
- **Built-in test suite** - URL normalization corpus, frontier ordering
  invariants, parser fixtures.
- **Per-host adaptive politeness** - back off automatically when a host's
  observed response time degrades.
- **Optional `sitemap.xml` ingestion** as a seeding strategy.
- **Pluggable sinks** - Parquet, JSONL, stdout, Kafka, generic queue.

If you want to pick one of these up, open an issue first to coordinate.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Responsible use

This tool can issue a very large number of HTTP requests in a short window.
That is its purpose. With that purpose comes the obligation to use it on
infrastructure you own, infrastructure you have written permission to crawl,
or public infrastructure that explicitly permits crawling via `robots.txt`.

The default configuration honors `robots.txt` and applies per-host
politeness. Do not turn those off without thinking about who is on the
receiving end.

---

If `webcrawler` saves you an afternoon, please consider starring the repo
on GitHub - it helps other people find the project.
