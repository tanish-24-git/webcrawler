# Usage

```
webcrawler crawl <URL> [<URL> ...] [options]
webcrawler version
```

You can also run the tool as a module:

```bash
python -m webcrawler crawl https://example.com
```

## Arguments

- `<URL>` (one or more, required) - Seed URL(s). Each must be an
  absolute `http://` or `https://` URL. Each seed becomes a node at
  depth 0.

## Options

### Output

- `--output, -o PATH` (default: `out/crawl.csv`)
  Path to the output CSV. Parent directories are created.
- `--rotate-every N` (default: `1000000`)
  Roll over to a new shard after `N` rows. Each shard becomes
  `<stem>.partNNNNN.<suffix>`. Pass `0` to disable rotation and write
  one big file.

### Concurrency

- `--workers, -w N` (default: `1024`)
  Number of async worker coroutines. More workers = more parallel
  fetches, but the practical ceiling is set by your bandwidth and
  the per-host limit, not by Python.
- `--per-host N` (default: `4`)
  Maximum concurrent in-flight requests against a single host. Keep
  this low (1-4) unless you own the target.
- `--timeout SECONDS` (default: `30`)
  Total per-request timeout (DNS + connect + response).

### Scope

- `--depth, -d N` (default: `6`)
  Maximum link depth from any seed. Depth 0 = the seed itself,
  depth 1 = pages linked from a seed, and so on.
- `--max-pages, -n N` (default: `0` = unlimited)
  Hard cap on total pages fetched. The crawl stops cleanly once this
  is reached.
- `--same-host`
  Only crawl pages on exactly the seed hostnames. The strictest
  scope.
- `--same-domain` / `--open-web` (default: `--same-domain`)
  `--same-domain` keeps the crawl inside the seed's *registered*
  domain (so seeds on `example.com` may visit `news.example.com`
  but not `other.com`). `--open-web` lifts the restriction
  entirely - use sparingly, and only with `robots.txt` enabled.
- `--no-subdomains`
  Combined with `--same-domain`, restricts the crawl to the exact
  hostnames of the seeds.

### Politeness

- `--user-agent, -A STRING` (default: identifies the crawler with a
  link to the repo)
  Sent on every request. Putting your contact in the UA is the
  community-accepted way to be reachable when something goes wrong.
- `--no-robots`
  Disable `robots.txt` enforcement. Only use this on infrastructure
  you own or are authorized to crawl.
- `--delay SECONDS` (default: `0.0`)
  Floor on the per-host fetch interval, applied even when
  `robots.txt` is silent. `--delay 1` means at most one request per
  second per host (combined with `--per-host` for in-flight cap).

### Network

- `--max-bytes N` (default: `5242880`)
  Read at most N bytes from any response body. Prevents a single
  hostile server from filling RAM.
- `--proxy URL` (default: none)
  HTTP proxy, e.g. `http://localhost:8080`.
- `--insecure`
  Disable TLS certificate verification. Off by default for a
  reason; only use it on internal networks with self-signed certs.

### UI / logging

- `--no-tui`
  Disable the live dashboard. Useful with `nohup`, `screen`, `tmux
  detach`, CI, or when piping the terminal output somewhere.
- `--log-file PATH` (default: `logs/crawler.log`)
  Where structured engine logs go. The TUI is decorative; the log
  file is durable.

### Dedup tuning

- `--bloom-capacity N` (default: `200_000_000`)
  Expected URL universe size. Sets the bloom filter capacity; below
  1 million we use an exact `set` automatically.

## Examples

Crawl one site, default scope, default depth, default everything:

```bash
webcrawler crawl https://example.com
```

Crawl two seeds, share the same scope rules:

```bash
webcrawler crawl https://example.com https://docs.example.com
```

Headless run with a hard page cap and rotation every 250k rows:

```bash
webcrawler crawl https://example.com \
  --no-tui \
  --max-pages 5000000 \
  --rotate-every 250000 \
  --output /data/crawl/example.csv
```

Open-web crawl from a hub, depth 3, polite (1s/host):

```bash
webcrawler crawl https://news.ycombinator.com \
  --open-web \
  --depth 3 \
  --delay 1 \
  --per-host 1
```

Crawl through a corporate proxy, bypass cert verification on an
internal site:

```bash
webcrawler crawl https://internal.example.local \
  --proxy http://proxy.corp:8080 \
  --insecure \
  --user-agent "internal-link-checker/1.0 (ops@example.local)"
```

## Stopping a crawl

`Ctrl+C` (SIGINT) requests a clean shutdown:

1. The stop event is set; workers stop pulling new tasks once their
   current fetch returns.
2. The frontier is closed.
3. The CSV writer drains its queue and flushes the file.
4. The aiohttp session closes its connection pool.
5. The CLI prints a summary and exits with code 130.

Hitting `Ctrl+C` a second time is uncooperative and may lose
in-flight rows. Don't.

## Resuming a crawl

There is no state checkpoint in v0.1; resume support is a planned
addition. Until then, treat every crawl as a fresh start. If you
need to resume in practice, set `--max-pages` to a reasonable batch
size, drain the run, and re-seed from a list of URLs you have not
yet covered.
