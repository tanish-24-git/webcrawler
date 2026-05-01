"""Crawl configuration. All knobs that control the crawl live here."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class CrawlConfig:
    """Runtime configuration for a single crawl."""

    seeds: list[str] = field(default_factory=list)

    # Scope
    same_domain_only: bool = False
    same_registered_domain: bool = True
    allow_subdomains: bool = True
    max_depth: int = 6
    max_pages: int = 0  # 0 == unlimited

    # Concurrency
    workers: int = 1024
    per_host_concurrency: int = 4
    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    total_timeout: float = 30.0

    # Politeness
    user_agent: str = (
        "webcrawler/0.1 (+https://github.com/tanish-24-git/webcrawler)"
    )
    respect_robots: bool = True
    default_crawl_delay: float = 0.0
    per_host_min_interval: float = 0.0  # additional floor in seconds
    max_redirects: int = 5

    # Network
    max_response_bytes: int = 5 * 1024 * 1024  # 5 MiB cap per page
    accept_languages: str = "en;q=0.9, *;q=0.5"
    follow_redirects: bool = True
    verify_tls: bool = True
    proxy: str | None = None

    # Filters
    allowed_schemes: tuple[str, ...] = ("http", "https")
    allowed_content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml")
    blocked_extensions: tuple[str, ...] = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
        ".mp3", ".mp4", ".avi", ".mov", ".webm", ".wav", ".flac",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".exe", ".dmg", ".iso", ".bin",
        ".css", ".js",
    )

    # Dedup
    bloom_capacity: int = 200_000_000
    bloom_error_rate: float = 0.001

    # Output
    output_csv: Path = Path("out/crawl.csv")
    rotate_every: int = 1_000_000  # rows per CSV shard, 0 = no rotation
    state_dir: Path = Path("state")
    log_file: Path | None = Path("logs/crawler.log")

    # UI
    no_tui: bool = False
    refresh_per_second: float = 4.0

    def __post_init__(self) -> None:
        self.output_csv = Path(self.output_csv)
        self.state_dir = Path(self.state_dir)
        if self.log_file is not None:
            self.log_file = Path(self.log_file)
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if self.per_host_concurrency < 1:
            raise ValueError("per_host_concurrency must be >= 1")
        if self.max_depth < 0:
            raise ValueError("max_depth must be >= 0")
