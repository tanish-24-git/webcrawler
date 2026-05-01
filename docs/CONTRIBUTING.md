# Contributing

Thank you for considering a contribution. The crawler is small enough
that getting started should be quick.

## Development setup

```bash
git clone https://github.com/tanish-24-git/webcrawler
cd webcrawler
python -m venv .venv
. .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Then run the CLI directly:

```bash
webcrawler crawl https://example.com --max-pages 100 --no-tui
```

## Layout (recap)

```
src/webcrawler/
  cli.py            typer commands
  config.py         CrawlConfig dataclass
  crawler.py        the engine + worker loop
  dedup.py          bloom + exact seen-set
  fetcher.py        aiohttp wrapper
  frontier.py       per-host queue
  parser.py         selectolax HTML parsing
  politeness.py     per-host concurrency
  robots.py         robots.txt cache
  stats.py          metrics
  storage.py        rotating CSV writer
  tui.py            Rich dashboard
  url_utils.py      URL normalization + scope
docs/               documentation
```

## Style

- Format: ruff, line length 100. `ruff format .` before committing.
- Lint: `ruff check .`. Selected rules in `pyproject.toml`.
- Types: `mypy src` should be clean for new code. We do not require
  100% coverage; we do require that a function with a non-trivial
  contract has a return-type annotation.
- Comments: only when they add information that the names and types
  don't already convey. The existing comments are mostly *why*
  comments (why this dedup strategy, why this politeness model);
  prefer that style to *what* comments.
- No emojis in code, comments, docs, or commit messages.

## Tests

A test suite is on the roadmap. For now, run the smoke crawl against
a known-stable site (`https://example.com` or your own) before
opening a PR, and post the resulting summary line in the PR body.

Things that are particularly worth testing if you add tests:

- `url_utils.normalize_url` against the canonicalization corpus
  (RFC 3986 examples, plus the WHATWG URL spec test cases).
- `frontier.Frontier` ordering invariants under interleaved
  push/pop/release.
- `dedup.BloomSeenSet` false-positive rate at the configured
  capacity.
- `parser.parse_html` against a few real-world malformed pages.

## Pull requests

- One concept per PR. A change that touches the fetcher *and* the
  TUI for unrelated reasons should be two PRs.
- Update the relevant doc when you change behavior. The README,
  USAGE.md, and CONFIGURATION.md are the user-facing surfaces;
  ARCHITECTURE.md and PERFORMANCE.md are the developer-facing ones.
- Performance changes should include a before/after measurement
  in the PR description. "Faster" is not a number.

## Filing issues

Useful issue reports include:

- The exact CLI invocation (with secrets redacted).
- The Python and OS version.
- The crawl summary line, or a screenshot of the TUI at the time
  of failure.
- For crashes: the contents of `logs/crawler.log`.

## Roadmap

- Resume support (persist frontier + seen-set on shutdown).
- Redis-backed frontier and seen-set for cluster operation.
- Built-in test suite.
- Per-host adaptive politeness based on observed response times.
- Optional sitemap.xml ingestion as a seeding strategy.

If you want to pick one of these up, open an issue first to
coordinate.
