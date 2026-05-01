# Performance

This document is about throughput tuning. Read it after you have run
the crawler on a real workload at least once.

## What is "fast"?

A useful upper bound: with average HTML page size of 50 KB, a sustained
1,000 pages/sec costs you 50 MB/s = 400 Mbps of inbound bandwidth, plus
the same in TCP overhead and TLS records. So before you tune anything,
look at your link.

| Pages/sec | Inbound (50 KB/page) | Reasonable on             |
| :-------- | :------------------- | :------------------------ |
| 50        | 20 Mbps              | Laptop / home connection  |
| 200       | 80 Mbps              | Cheap VM                  |
| 1,000     | 400 Mbps             | Decent VM                 |
| 5,000     | 2 Gbps               | Bare metal / multi-NIC VM |
| 12,000    | ~5 Gbps              | Distributed cluster       |

100M pages/day is sustained 1,160 pages/sec. The architecture supports
that rate; whether *you* hit it depends on your network and how broad
the seed set is (a single domain will throttle you long before
hardware does).

## Where the time goes

For a typical broad crawl on a healthy connection:

```
DNS lookup            10 ms   (cached after first hit per host)
TCP connect           20 ms   (pooled, amortized to ~0)
TLS handshake         60 ms   (pooled, amortized to ~0)
Server processing    150 ms   (the long pole, totally external)
Body download         50 ms   (depends on page size and bandwidth)
HTML parse             1 ms   (selectolax)
Link normalization     1 ms
Frontier push          0.1 ms
CSV write (queued)     0.05 ms (truly async)
```

The single biggest lever is **server response time**. You cannot make a
3-second-to-respond server fast; you can only fetch from many of them
concurrently.

The next biggest is **connection reuse**. The default connector keeps
the pool open and `enable_cleanup_closed=True`. Do not change those.

## Tuning checklist

In rough priority order:

### 1. Increase `--workers`

Default 1024. You can usually go higher. Watch CPU; once one core
saturates the event loop you have hit the ceiling. On Linux, install
`uvloop` (`pip install -e ".[uvloop]"`) for a 1.5x to 2x event-loop
speedup before adding more workers.

```bash
webcrawler crawl https://example.com --workers 4096
```

### 2. Tune `--per-host`

Default 4. Higher values fetch faster from a single host but anger
operators. Lower values are politer. For a single-site mirror, 2 is
usually correct.

### 3. Use a local DNS resolver

Above ~2,000 unique hosts/sec the OS resolver becomes a bottleneck.
Run an unbound or coredns instance on `127.0.0.1` and point
`/etc/resolv.conf` at it. The aiohttp DNS cache mitigates this within
a single crawl (TTL 300s) but cold lookups still go to the OS.

### 4. Cap response bodies aggressively

```bash
webcrawler crawl https://example.com --max-bytes 1048576
```

Most crawlable pages are well under 200 KB. Capping at 1 MiB drops
the long-tail of giant pages without losing crawl-graph completeness.

### 5. Keep `--depth` honest

A depth of 6 from a hub site can easily mean millions of pages. The
crawler explores breadth-first per host, so the time-to-first-results
is roughly constant in depth - but the total time grows
combinatorially.

### 6. Disable the TUI for long runs

```bash
webcrawler crawl https://example.com --no-tui
```

The TUI samples stats once per ~250ms. The cost is negligible at
small scale and noticeable at extreme concurrency. For 24-hour runs,
turn it off.

### 7. Set a sensible bloom capacity

Too small: scaling bloom filter grows in steps and each step costs
memory copies. Too large: you waste RAM. Aim within ~2x of your
expected universe.

```bash
webcrawler crawl https://example.com --bloom-capacity 50000000
```

## Diagnostics

The dashboard surfaces the metrics that matter most. Look for:

- **rate (1m)** drifts down over time -> growing per-host backlog or
  slowing target servers. Try `--per-host 2` or check your bandwidth.
- **errors** climbing fast -> target is rate-limiting you. Slow down.
- **dropped dedup** climbing -> your normalization is doing its job.
  Healthy sites have ~30-60% link redundancy.
- **dropped scope** dominating -> your scope rules are too tight or
  the site links a lot offsite. Both can be fine.
- **2xx ratio** below 90% -> something is wrong (rate-limited,
  blocked by a WAF, or the target was deindexed and links are stale).

## What does not help

- **Adding threads** - the GIL blocks any benefit and asyncio already
  handles I/O parallelism.
- **Spawning multiple processes on one box** - the connection pool
  cannot be shared, so you end up with multiple smaller pools and
  more DNS pressure.
- **Caching parsed HTML** - parse cost is microseconds; not worth the
  memory.
- **Switching to httpx** - aiohttp is faster for this workload. (The
  authors of httpx know this and don't claim otherwise.)

## What does help, but is not in v0.1

- **Sharded frontier with Redis** - lets multiple machines share one
  URL universe. See [SCALING.md](SCALING.md).
- **Process-pool HTML parser fan-out** - if you ever measure parsing
  as the bottleneck (you probably will not).
- **HTTP/2** - aiohttp does not support HTTP/2 client. For most
  servers HTTP/1.1 with keep-alive is competitive.
