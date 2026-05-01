# Configuration

Every knob that the crawler exposes lives on `webcrawler.config.CrawlConfig`.
The CLI is a thin layer over this dataclass, but you can also import
and configure the engine directly from Python:

```python
import asyncio
from pathlib import Path
from webcrawler.config import CrawlConfig
from webcrawler.crawler import CrawlEngine

async def main():
    config = CrawlConfig(
        seeds=["https://example.com"],
        output_csv=Path("out/example.csv"),
        workers=512,
        per_host_concurrency=2,
        max_depth=4,
        max_pages=100_000,
        no_tui=True,
    )
    await CrawlEngine(config).run()

asyncio.run(main())
```

## Field reference

### Seeds and scope

| Field                       | Default | Effect                                                          |
| :-------------------------- | :------ | :-------------------------------------------------------------- |
| `seeds`                     | `[]`    | List of starting URLs. Required.                                |
| `same_domain_only`          | `False` | Only crawl URLs whose hostname exactly matches a seed hostname. |
| `same_registered_domain`    | `True`  | Only crawl URLs sharing a seed's registered domain.             |
| `allow_subdomains`          | `True`  | When same-domain, allow subdomains.                             |
| `max_depth`                 | `6`     | Stop following links beyond this depth from a seed.             |
| `max_pages`                 | `0`     | Hard page-count cap. `0` means unlimited.                       |

The two scope booleans interact: `same_domain_only=True` overrides
`same_registered_domain`. The CLI's `--same-host` sets the former,
`--open-web` clears both.

### Concurrency

| Field                  | Default | Effect                                                  |
| :--------------------- | :------ | :------------------------------------------------------ |
| `workers`              | `1024`  | Total async workers in the pool.                        |
| `per_host_concurrency` | `4`     | Max in-flight requests per host.                        |
| `connect_timeout`      | `10.0`  | DNS + TCP connect timeout (seconds).                    |
| `read_timeout`         | `20.0`  | Per-socket read timeout (seconds).                      |
| `total_timeout`        | `30.0`  | Whole-request timeout (seconds).                        |

Sane combinations:

- *Polite single-site*: `workers=64`, `per_host_concurrency=2`,
  `total_timeout=20`.
- *Broad open-web*: `workers=2048`, `per_host_concurrency=4`,
  `total_timeout=30`.
- *Slow / flaky targets*: bump `total_timeout` to `60` and accept the
  drop in throughput.

### Politeness

| Field                    | Default     | Effect                                                  |
| :----------------------- | :---------- | :------------------------------------------------------ |
| `user_agent`             | identifies the crawler | Sent on every request.                       |
| `respect_robots`         | `True`      | Honor `robots.txt`. Always leave `True` in production.  |
| `default_crawl_delay`    | `0.0`       | Per-host floor when `robots.txt` is silent.             |
| `per_host_min_interval`  | `0.0`       | Additional fixed floor on per-host interval.            |
| `max_redirects`          | `5`         | Max redirect chain length before failing.               |

Note: when `robots.txt` provides a `Crawl-delay`, that value is used
**even if** `default_crawl_delay` is lower. The crawl-delay is treated
as a binding contract.

### Network

| Field                  | Default       | Effect                                              |
| :--------------------- | :------------ | :-------------------------------------------------- |
| `max_response_bytes`   | `5_242_880`   | Cap on bytes read per response.                     |
| `accept_languages`     | `en;q=0.9, *;q=0.5` | `Accept-Language` header.                     |
| `follow_redirects`     | `True`        | Follow `3xx` automatically.                         |
| `verify_tls`           | `True`        | Validate server certs.                              |
| `proxy`                | `None`        | HTTP proxy URL.                                     |

### Filters

| Field                   | Default | Effect                                                 |
| :---------------------- | :------ | :----------------------------------------------------- |
| `allowed_schemes`       | `("http","https")` | Hard scheme allowlist.                      |
| `allowed_content_types` | `("text/html","application/xhtml+xml")` | Bodies of other content types are not parsed for links.|
| `blocked_extensions`    | image / video / archive / binary doc extensions | Skipped before fetch.|

If you want to crawl PDFs (extract metadata, etc.), remove `.pdf` from
`blocked_extensions` and add `application/pdf` to
`allowed_content_types`. The parser will not extract links from a PDF
- you would need to plug in a different parser for that.

### Deduplication

| Field              | Default       | Effect                                                  |
| :----------------- | :------------ | :------------------------------------------------------ |
| `bloom_capacity`   | `200_000_000` | Expected URL universe size.                             |
| `bloom_error_rate` | `0.001`       | Target bloom false-positive rate.                       |

Pick `bloom_capacity` close to your real universe size:

- 100k - 1M URLs: irrelevant, an exact set is used.
- 1M - 100M URLs: aim for capacity ~= expected unique URLs.
- 100M+ URLs: expect ~340 MiB resident memory at the default error rate.

### Output

| Field           | Default               | Effect                                       |
| :-------------- | :-------------------- | :------------------------------------------- |
| `output_csv`    | `Path("out/crawl.csv")` | CSV file path.                            |
| `rotate_every`  | `1_000_000`           | Rows per shard. `0` disables rotation.       |
| `state_dir`     | `Path("state")`       | Reserved for resume support.                 |
| `log_file`      | `Path("logs/crawler.log")` | File log path. Set to `None` to disable.|

### UI

| Field                  | Default | Effect                                |
| :--------------------- | :------ | :------------------------------------ |
| `no_tui`               | `False` | Disable the live dashboard.           |
| `refresh_per_second`   | `4.0`   | TUI refresh rate.                     |

## Validation

`CrawlConfig.__post_init__` validates that:

- `workers >= 1`
- `per_host_concurrency >= 1`
- `max_depth >= 0`

These raise `ValueError` immediately if violated. Other fields are
not validated at construction time - typos in extension lists, etc.,
will silently misbehave.
