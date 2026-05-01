"""Terminal UI: a live, monospace dashboard rendered with Rich.

Layout:

    +------------------------------------------------------------+
    |                       BANNER                                |
    +-----------------------------+------------------------------+
    | summary                     | rates / projection           |
    +-----------------------------+------------------------------+
    | top domains                 | recent activity              |
    +-----------------------------+------------------------------+
    | recent errors                                              |
    +------------------------------------------------------------+
    | footer (controls)                                          |
    +------------------------------------------------------------+
"""

from __future__ import annotations

import asyncio

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from webcrawler.config import CrawlConfig
from webcrawler.stats import Stats

BANNER = r"""
 __        __   _      ____                    _
 \ \      / /__| |__  / ___|_ __ __ ___      _| | ___ _ __
  \ \ /\ / / _ \ '_ \| |   | '__/ _` \ \ /\ / / |/ _ \ '__|
   \ V  V /  __/ |_) | |___| | | (_| |\ V  V /| |  __/ |
    \_/\_/ \___|_.__/ \____|_|  \__,_| \_/\_/ |_|\___|_|
"""


def render_banner() -> Panel:
    text = Text(BANNER, style="bold cyan")
    sub = Text(
        "high-throughput async crawler  -  press Ctrl+C to stop",
        style="dim",
    )
    return Panel(
        Align.center(Group(text, sub)),
        border_style="cyan",
        padding=(0, 2),
    )


def render_summary(stats: Stats, config: CrawlConfig) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    target = (
        f"{config.max_pages:,}" if config.max_pages else "unlimited"
    )
    progress = "-"
    if config.max_pages:
        pct = 100.0 * stats.fetched / config.max_pages
        progress = f"{pct:5.1f}%"

    table.add_row("fetched",   f"{stats.fetched:>12,}")
    table.add_row("queued",    f"{stats.enqueued - stats.fetched:>12,}")
    table.add_row("rows out",  f"{stats.rows_written:>12,}")
    table.add_row("errors",    f"{stats.fetch_errors:>12,}")
    table.add_row("bytes",     f"{_human_bytes(stats.bytes_in):>12}")
    table.add_row("target",    f"{target:>12}")
    table.add_row("progress",  f"{progress:>12}")
    table.add_row("uptime",    f"{_human_time(stats.uptime):>12}")
    return Panel(table, title="summary", border_style="green")


def render_rates(stats: Stats) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    table.add_row("rate (1m)",     f"{stats.rate_recent:>10,.1f} pages/sec")
    table.add_row("rate (life)",   f"{stats.rate_lifetime:>10,.1f} pages/sec")
    table.add_row("projected/day", f"{stats.projected_per_day:>10,.0f}")
    table.add_row("hosts",         f"{len(stats.domains):>10,}")
    table.add_row("links seen",    f"{stats.links_extracted:>10,}")
    table.add_row("dropped scope", f"{stats.dropped_scope:>10,}")
    table.add_row("dropped dedup", f"{stats.dropped_dedup:>10,}")
    table.add_row("dropped robots",f"{stats.dropped_robots:>10,}")

    s = stats.status
    status_line = (
        f"[green]2xx[/green] {s.ok:,}  "
        f"[yellow]3xx[/yellow] {s.redirect:,}  "
        f"[red]4xx[/red] {s.client:,}  "
        f"[red]5xx[/red] {s.server:,}  "
        f"[dim]other[/dim] {s.other:,}"
    )
    body = Group(table, Text.from_markup(status_line))
    return Panel(body, title="throughput", border_style="cyan")


def render_top_domains(stats: Stats) -> Panel:
    table = Table(expand=True, show_header=True, header_style="bold")
    table.add_column("domain", overflow="fold")
    table.add_column("pages", justify="right", style="cyan")
    for host, count in stats.domains.most_common(10):
        table.add_row(host, f"{count:,}")
    return Panel(table, title="top domains", border_style="magenta")


def render_recent(stats: Stats) -> Panel:
    table = Table(expand=True, show_header=True, header_style="bold")
    table.add_column("status", justify="right", width=6)
    table.add_column("url", overflow="ellipsis", no_wrap=True)
    for code, url in list(stats.recent_urls)[-10:]:
        style = "green" if 200 <= code < 300 else "yellow" if 300 <= code < 400 else "red"
        table.add_row(Text(str(code), style=style), url)
    return Panel(table, title="recent", border_style="blue")


def render_errors(stats: Stats) -> Panel:
    if not stats.recent_errors:
        body = Text("no errors yet", style="dim")
    else:
        table = Table(expand=True, show_header=True, header_style="bold")
        table.add_column("error", style="red", no_wrap=True, width=24)
        table.add_column("url", overflow="ellipsis", no_wrap=True)
        for url, err in list(stats.recent_errors)[-8:]:
            table.add_row(err[:60], url)
        body = table
    return Panel(body, title="recent errors", border_style="red")


def render_footer(config: CrawlConfig) -> Panel:
    workers = f"{config.workers} workers / {config.per_host_concurrency} per-host"
    scope = (
        "same-host"
        if config.same_domain_only
        else ("same-registered-domain" if config.same_registered_domain else "open-web")
    )
    text = Text.from_markup(
        f"  [bold]workers[/bold] {workers}   "
        f"[bold]scope[/bold] {scope}   "
        f"[bold]depth[/bold] {config.max_depth}   "
        f"[bold]robots[/bold] {'on' if config.respect_robots else 'off'}   "
        f"[bold]out[/bold] {config.output_csv}"
    )
    return Panel(text, border_style="white")


def build_layout(config: CrawlConfig, stats: Stats) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="banner", size=9),
        Layout(name="top", size=12),
        Layout(name="middle", size=14),
        Layout(name="errors", size=10),
        Layout(name="footer", size=3),
    )
    layout["banner"].update(render_banner())
    layout["top"].split_row(
        Layout(render_summary(stats, config), name="summary"),
        Layout(render_rates(stats), name="rates"),
    )
    layout["middle"].split_row(
        Layout(render_top_domains(stats), name="domains"),
        Layout(render_recent(stats), name="recent"),
    )
    layout["errors"].update(render_errors(stats))
    layout["footer"].update(render_footer(config))
    return layout


async def run_tui(config: CrawlConfig, stats: Stats, stop_event: asyncio.Event) -> None:
    """Render the dashboard until `stop_event` is set."""
    console = Console()
    refresh = max(1.0, config.refresh_per_second)
    interval = 1.0 / refresh
    with Live(
        build_layout(config, stats),
        console=console,
        refresh_per_second=refresh,
        screen=True,
        transient=False,
    ) as live:
        while not stop_event.is_set():
            stats.tick()
            live.update(build_layout(config, stats))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(n)
    for u in units:
        if f < 1024.0:
            return f"{f:.1f} {u}"
        f /= 1024.0
    return f"{f:.1f} PiB"


def _human_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
