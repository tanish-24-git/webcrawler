# Scaling beyond a single node

The default build runs in a single Python process. That is enough for
millions of pages per day on a beefy VM. If you genuinely need
hundreds of millions per day, you need to shard, and that means
moving the two pieces of state that bind workers together onto a
network-accessible substrate:

1. **The frontier** (the URL queue).
2. **The seen-set** (URL deduplication).

Everything else - the fetcher, parser, robots cache, CSV writer,
stats - is per-process and scales by simply adding processes.

## The pieces that need to be shared

### Sharded frontier

The single-node `Frontier` uses an in-memory per-host queue plus a
ready-time heap. To shard it across N machines, give each machine
ownership of a **subset of hosts** by consistent hashing:

```
shard = blake2b(host).digest()[0] % N
```

URLs whose host hashes to your shard are popped/pushed locally.
URLs whose host belongs to another shard get forwarded to that
shard's queue, typically via Redis Streams or a Kafka topic.

The reason for sharding by host (rather than by URL) is politeness:
all requests to a given host land on the same machine, so the
per-host concurrency limiter and the per-host crawl-delay are
trivially correct. Sharding by URL would force every machine to
coordinate timing for every host, which is a much harder problem.

A reasonable substrate:

- **Redis** with one sorted set per host (`ZADD frontier:<host>`),
  scored by enqueue time. Hosts go in a global sorted-set keyed by
  their next-eligible-time. Workers pop the next eligible host with
  `ZRANGEBYSCORE`, then pop a URL from that host's set.

The single-node `Frontier` interface (`push`, `push_many`, `pop`,
`release`, `close`) is small enough to reimplement against Redis
without touching `crawler.py`.

### Sharded seen-set

The `SeenSet` protocol has three methods (`add`, `__contains__`,
`__len__`). Across machines, options:

- **Per-shard exact set** - acceptable if your shard key is the host
  and you accept that URL fingerprints from different shards never
  collide. Simplest.
- **Sharded bloom filter** - implement `BloomSeenSet` on top of
  Redis bitmaps (`SETBIT` / `GETBIT`). Loses a bit of throughput vs
  in-process but works at any scale.
- **Cuckoo filter** - if you need deletions (e.g. recrawl windows).

In practice, for crawls that fit one process's RAM (~340 MiB at 200M
URLs), sharing a seen-set across processes is usually overkill. Just
shard the input domain and let each process have its own bloom.

### Result aggregation

Each shard writes its own CSV. Concatenate them at the end:

```bash
{ head -n 1 out/shard0.csv; tail -q -n +2 out/shard*.csv; } > out/crawl.csv
```

The schema is the same across shards, so a header from shard 0 plus
header-skipped tails from the rest produces a valid combined file.

## Deployment shapes that work

### Shape A: one big VM, single process (default)

For up to ~10M pages/day this is the easy answer. No moving parts.

### Shape B: one VM, multiple processes, host-sharded

Run K processes on the same host, each owning a hash range. Use
local Redis (or even Unix sockets) for cross-shard URL forwarding.
Useful when the GIL or single-event-loop becomes the bottleneck
before bandwidth does (it almost never does).

### Shape C: multiple VMs, host-sharded, Redis-backed

Each VM runs the crawler with the Redis-backed frontier. Add a small
controller that:

1. Accepts the seed list,
2. Splits seeds by shard hash,
3. Forwards each to the owning shard's input queue,
4. Aggregates CSVs at the end.

This shape gets you to the 100M pages/day target on a handful of
modest VMs, assuming aggregate bandwidth is sufficient.

### Shape D: SQS / Kafka frontier

For pipelines where the crawler is one stage among many (URL
discovery -> crawl -> enrichment -> indexing), put the frontier on
SQS or Kafka. Workers `Receive` URLs from the queue and `Send`
discovered links back. The dedup table moves to a managed K/V store
(DynamoDB, Bigtable). Robust, expensive, and overkill unless you
already run on that infrastructure.

## Invariants you must preserve when sharding

These are correctness properties, not performance properties. Get
them wrong and the crawl is broken in subtle ways.

1. **Ownership of a host is stable for the duration of the crawl.**
   If shard 3 takes ownership of `example.com`, no other shard may
   fetch from `example.com`. Otherwise the per-host crawl-delay and
   in-flight cap are silently violated.

2. **Robots.txt cache is per-shard.** Hosts only ever appear on one
   shard, so each shard fetches `robots.txt` exactly once per host.
   No coordination needed.

3. **Dedup spans the entire crawl.** This is the trickiest one. If
   shard 1 discovers a URL whose host is owned by shard 3, shard 3
   needs to receive it. But shard 1 must also not re-forward the
   same URL on a later page. That means the *forwarding decision*
   itself goes through dedup at the source shard, before sending.

4. **Stop is global.** A `max_pages` cap interpreted per-shard would
   produce N times more pages than intended. Use a Redis counter or
   pass `max_pages / N` to each shard.

## What we have not built (and why)

- **The Redis frontier itself.** The interface is small enough that
  writing it would not take long, but committing a half-finished
  one is worse than committing none. v0.1 ships with the in-process
  frontier; the doc above is the contract you would implement
  against if you needed it.
- **A controller / orchestrator.** Same reasoning. Most users do
  not need this; those who do have opinions about how their
  orchestration should look.
- **Resume support.** Persisting the frontier and seen-set on shutdown
  is straightforward (pickle the bloom, JSON-dump the heap). It is
  on the roadmap but not in v0.1.

The goal of this document is to make sure that if you *do* need to
scale, the work is well-defined and the seams are in the right
places. The architecture was chosen with that in mind.
