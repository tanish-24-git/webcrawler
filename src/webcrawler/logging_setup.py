"""Logging configuration shared by CLI and engine."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_file: Path | None, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Quiet noisy third-party loggers in our terminal output.
    for name in ("aiohttp.access", "aiohttp.client", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
