"""Command-line interface.

    webcrawler crawl <url> [options]
    webcrawler version

The CLI is intentionally thin - it just parses flags, builds a CrawlConfig,
and hands off to the engine.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console

from webcrawler import __version__
from webcrawler.config import CrawlConfig
from webcrawler.crawler import CrawlEngine
from webcrawler.logging_setup import configure_logging
from webcrawler.stats import Stats
from webcrawler.tui import run_tui

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="High-throughput asynchronous web crawler. Output: streaming CSV.",
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)
console = Console()


@app.command()
def crawl(
    seed: list[str] = typer.Argument(..., help="One or more starting URLs."),
    output: Path = typer.Option(
        Path("out/crawl.csv"), "--output", "-o", help="CSV output path."
    ),
    workers: int = typer.Option(1024, "--workers", "-w", help="Total async workers."),
    per_host: int = typer.Option(
        4, "--per-host", help="Max concurrent in-flight requests per host."
    ),
    max_depth: int = typer.Option(6, "--depth", "-d", help="Max link depth from seed."),
    max_pages: int = typer.Option(
        0, "--max-pages", "-n", help="Stop after N pages (0 = unlimited)."
    ),
    same_host: bool = typer.Option(
        False, "--same-host", help="Restrict to seed hostnames only."
    ),
    same_domain: bool = typer.Option(
        True,
        "--same-domain/--open-web",
        help="Restrict to seed registered domains, or roam the open web.",
    ),
    no_subdomains: bool = typer.Option(
        False, "--no-subdomains", help="Disallow subdomains of seed domain."
    ),
    user_agent: str = typer.Option(
        f"webcrawler/{__version__} (+https://github.com/tanish-24-git/webcrawler)",
        "--user-agent",
        "-A",
    ),
    no_robots: bool = typer.Option(
        False, "--no-robots", help="Ignore robots.txt (use only when authorized)."
    ),
    delay: float = typer.Option(
        0.0, "--delay", help="Default per-host delay (seconds) when robots.txt is silent."
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="Per-request total timeout."),
    max_bytes: int = typer.Option(
        5 * 1024 * 1024, "--max-bytes", help="Max bytes per response body."
    ),
    rotate_every: int = typer.Option(
        1_000_000, "--rotate-every", help="CSV rows per shard (0 = no rotation)."
    ),
    proxy: str | None = typer.Option(None, "--proxy", help="HTTP proxy URL."),
    insecure: bool = typer.Option(
        False, "--insecure", help="Disable TLS certificate verification."
    ),
    no_tui: bool = typer.Option(
        False, "--no-tui", help="Disable the live dashboard (useful for nohup/CI)."
    ),
    log_file: Path = typer.Option(
        Path("logs/crawler.log"), "--log-file", help="Path to crawler log."
    ),
    bloom_capacity: int = typer.Option(
        200_000_000, "--bloom-capacity", help="Bloom filter URL capacity."
    ),
) -> None:
    """Crawl starting from one or more seed URLs."""
    config = CrawlConfig(
        seeds=list(seed),
        output_csv=output,
        workers=workers,
        per_host_concurrency=per_host,
        max_depth=max_depth,
        max_pages=max_pages,
        same_domain_only=same_host,
        same_registered_domain=same_domain and not same_host,
        allow_subdomains=not no_subdomains,
        user_agent=user_agent,
        respect_robots=not no_robots,
        default_crawl_delay=delay,
        total_timeout=timeout,
        max_response_bytes=max_bytes,
        rotate_every=rotate_every,
        proxy=proxy,
        verify_tls=not insecure,
        no_tui=no_tui,
        log_file=log_file,
        bloom_capacity=bloom_capacity,
    )
    configure_logging(config.log_file)
    _install_uvloop_if_available()

    try:
        asyncio.run(_run_crawl(config))
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted by user[/yellow]")
        sys.exit(130)


@app.command()
def version() -> None:
    """Print the crawler version."""
    console.print(f"webcrawler {__version__}")


async def _run_crawl(config: CrawlConfig) -> None:
    stats = Stats()
    engine = CrawlEngine(config, stats)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in _signals():
        try:
            loop.add_signal_handler(sig, _handle_signal, engine, stop_event)
        except (NotImplementedError, RuntimeError):
            # Windows asyncio cannot install signal handlers via the loop.
            signal.signal(sig, lambda *_: _handle_signal(engine, stop_event))

    tasks = [asyncio.create_task(engine.run(), name="engine")]
    if not config.no_tui:
        tasks.append(asyncio.create_task(run_tui(config, stats, stop_event), name="tui"))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    stop_event.set()
    engine.request_stop()
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    _print_summary(stats, config)


def _print_summary(stats: Stats, config: CrawlConfig) -> None:
    console.rule("[bold cyan]crawl complete")
    console.print(f"  pages fetched : [bold]{stats.fetched:,}[/bold]")
    console.print(f"  rows written  : [bold]{stats.rows_written:,}[/bold]")
    console.print(f"  errors        : [bold]{stats.fetch_errors:,}[/bold]")
    console.print(f"  hosts touched : [bold]{len(stats.domains):,}[/bold]")
    console.print(f"  uptime        : [bold]{stats.uptime:.1f}s[/bold]")
    console.print(f"  avg rate      : [bold]{stats.rate_lifetime:.1f} pages/sec[/bold]")
    console.print(f"  output        : [bold]{config.output_csv}[/bold]")


def _signals() -> list[int]:
    sigs = [signal.SIGINT]
    if hasattr(signal, "SIGTERM"):
        sigs.append(signal.SIGTERM)
    return sigs


def _handle_signal(engine: CrawlEngine, stop_event: asyncio.Event) -> None:
    engine.request_stop()
    stop_event.set()


def _install_uvloop_if_available() -> None:
    try:
        import uvloop  # type: ignore[import-not-found]
        uvloop.install()
    except ImportError:
        pass
