# webcrawler

A high-throughput, asynchronous web crawler written in Python. It takes
one or more seed URLs, walks the link graph reachable from them, and
streams the result to a CSV file. The interface is a terminal dashboard
in the spirit of `htop`, `nmap`, and the rest of the Unix tradition: no
GUI, no server, no browser. Just `webcrawler crawl <url>` and a live
view of what is happening.

```
 __        __   _      ____                    _
 \ \      / /__| |__  / ___|_ __ __ ___      _| | ___ _ __
  \ \ /\ / / _ \ '_ \| |   | '__/ _` \ \ /\ / / |/ _ \ '__|
   \ V  V /  __/ |_) | |___| | | (_| |\ V  V /| |  __/ |
    \_/\_/ \___|_.__/ \____|_|  \__,_| \_/\_/ |_|\___|_|
```

---

## What it does

- Crawls the entire link graph reachable from a seed, breadth-first, up
  to a configurable depth.
- Honors `robots.txt` per host, including `Crawl-delay`.
- Deduplicates URLs aggressively via canonicalization plus a scalable
  bloom filter, so the same page is never fetched twice across
  hundreds of millions of candidate URLs.
- Politeness: per-host concurrency cap, per-host fetch interval, and
  bounded total concurrency.
- Streams every fetch (success or failure) to a rotating CSV file with
  a fixed schema (see [Output](#output)).
- Renders a live terminal dashboard while the crawl runs: throughput,
  status-code distribution, top domains, recent URLs, recent errors.
- Shuts down cleanly on `Ctrl+C` and flushes all in-flight rows.

It does not render JavaScript, take screenshots, build a search index,
or extract page content beyond the title. By design - those are
separate problems and bolting them on would slow the crawler by 10x.

---

## Why another crawler

Most Python crawlers are either toy spiders (synchronous, single-host)
or full frameworks that you have to bend around (Scrapy, Apify). This
one is built around a single, narrow contract:

> Given seed URLs, produce a CSV of every page reachable, as fast as
> the network and the politeness budget allow, on commodity hardware.

Everything in the codebase exists to serve that contract.

---

## Throughput

The architecture is built to scale to the **100M pages/day** range, but
let's be honest about where that number actually lives:

| Setup                                           | Realistic ceiling     |
| :---------------------------------------------- | :-------------------- |
| Laptop, residential connection                  | 1M - 3M pages/day     |
| Single VM, gigabit, broad seed list             | 5M - 20M pages/day    |
| Cluster, sharded frontier (Redis), 10+ workers  | 100M+ pages/day       |

The single-process default in this repo gets you the first two rows
out of the box. The third row requires the distributed deployment
described in [docs/SCALING.md](docs/SCALING.md) - the codebase is
structured so the frontier and dedup layers can be swapped for
network-backed implementations without touching the engine.

What actually limits a single node:

1. **Per-host politeness** caps requests-per-second to any one origin.
   If you are crawling a single site, you are bounded by what that
   site will tolerate, not by your CPU.
2. **DNS** becomes the bottleneck above roughly 2,000 unique hosts/sec
   without a local resolver cache.
3. **TLS handshake CPU cost** dominates for short-lived connections,
   which is why the default uses connection pooling and
   `enable_cleanup_closed=True`.
4. **HTML parsing** - we use `selectolax`, not BeautifulSoup, because
   on a 100k-page-per-hour budget the parser cost is non-trivial.

See [docs/PERFORMANCE.md](docs/PERFORMANCE.md) for a longer treatment
of these.

---

## Install

Requires Python 3.10 or newer.

```bash
git clone https://github.com/tanish-24-git/webcrawler
cd webcrawler
pip install -e .
```

For maximum throughput on Linux, add the optional `uvloop` extra:

```bash
pip install -e ".[uvloop]"
```

---

## Usage

Crawl a site, restricted to its registered domain (the default), depth
six, with the live dashboard:

```bash
webcrawler crawl https://example.com
```

Crawl the open web (no domain restriction) with explicit limits:

```bash
webcrawler crawl https://news.ycombinator.com \
  --open-web \
  --depth 4 \
  --max-pages 1000000 \
  --workers 2048 \
  --per-host 4 \
  --output out/hn-crawl.csv
```

Run headless (no TUI), suitable for `nohup` / `screen` / CI:

```bash
webcrawler crawl https://example.com --no-tui --max-pages 500000
```

Full flag reference: [docs/USAGE.md](docs/USAGE.md).

---

## Output

The crawler writes a single streaming CSV (or rotated shards if you set
`--rotate-every`). Every fetch gets exactly one row, regardless of
whether it succeeded.

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

## How it works (one paragraph)

A pool of async workers shares a single `Frontier` (per-host FIFOs in a
ready-time min-heap), a `Seen` set (a scalable bloom filter at large
capacities), a `RobotsCache`, and a single `aiohttp.ClientSession`.
Each worker pops the next eligible URL, asks `RobotsCache` if the
fetch is allowed, fetches it under a per-host concurrency
slot, parses the body with `selectolax`, normalizes and scope-filters
each discovered link, dedupes it against the bloom filter, and pushes
the survivors back into the frontier. A separate task drains a write
queue into a rotating CSV. The TUI runs as another async task that
samples the shared `Stats` object on each frame.

For the long version, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - module-by-module walkthrough.
- [docs/USAGE.md](docs/USAGE.md) - every command-line flag, with examples.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - tuning knobs and what they do.
- [docs/PERFORMANCE.md](docs/PERFORMANCE.md) - throughput tuning and bottlenecks.
- [docs/SCALING.md](docs/SCALING.md) - how to scale beyond a single node.
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) - dev environment, style, tests.

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

## License

MIT. See [LICENSE](LICENSE).

---

## A note on responsibility

This tool can issue a very large number of HTTP requests in a short
window. That is its purpose. With that purpose comes the obligation to
use it on infrastructure you own, infrastructure you have written
permission to crawl, or public infrastructure that explicitly permits
crawling via `robots.txt`. The default configuration honors
`robots.txt` and applies per-host politeness; do not turn those off
without thinking about who is on the receiving end.
