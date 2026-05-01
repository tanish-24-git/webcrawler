"""Async HTTP fetcher.

Wraps aiohttp with sane defaults for crawling: bounded body reads, total
timeouts, configurable redirects. The fetcher only does I/O - all HTML
parsing happens in `parser.py` so the worker can yield the event loop
between network and CPU work.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientTimeout, TCPConnector

from webcrawler.config import CrawlConfig


@dataclass(slots=True)
class FetchResult:
    url: str            # final URL after redirects
    status: int
    content_type: str
    body: bytes
    elapsed: float
    error: str = ""


def build_session(config: CrawlConfig) -> aiohttp.ClientSession:
    """Construct a single shared aiohttp session for the crawl."""
    connector = TCPConnector(
        limit=config.workers,
        limit_per_host=config.per_host_concurrency,
        ttl_dns_cache=300,
        use_dns_cache=True,
        ssl=config.verify_tls,
        force_close=False,
        enable_cleanup_closed=True,
    )
    timeout = ClientTimeout(
        total=config.total_timeout,
        connect=config.connect_timeout,
        sock_read=config.read_timeout,
    )
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": config.accept_languages,
        "Accept-Encoding": "gzip, deflate",
    }
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
        trust_env=True,
        auto_decompress=True,
    )


async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    config: CrawlConfig,
) -> FetchResult:
    """Fetch one URL. Never raises - errors are reported as FetchResult.error."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        async with session.get(
            url,
            allow_redirects=config.follow_redirects,
            max_redirects=config.max_redirects,
            proxy=config.proxy,
        ) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()

            if ctype and not _content_type_allowed(ctype, config.allowed_content_types):
                return FetchResult(
                    url=str(resp.url),
                    status=resp.status,
                    content_type=ctype,
                    body=b"",
                    elapsed=loop.time() - start,
                    error=f"skipped content-type: {ctype}",
                )

            body = await _read_capped(resp, config.max_response_bytes)
            return FetchResult(
                url=str(resp.url),
                status=resp.status,
                content_type=ctype,
                body=body,
                elapsed=loop.time() - start,
            )
    except asyncio.TimeoutError:
        return FetchResult(url, 0, "", b"", loop.time() - start, error="timeout")
    except aiohttp.TooManyRedirects:
        return FetchResult(url, 0, "", b"", loop.time() - start, error="too_many_redirects")
    except aiohttp.ClientResponseError as exc:
        return FetchResult(
            url, getattr(exc, "status", 0) or 0, "", b"", loop.time() - start,
            error=f"http:{exc.message}",
        )
    except aiohttp.ClientConnectorError as exc:
        return FetchResult(url, 0, "", b"", loop.time() - start, error=f"connect:{exc}")
    except aiohttp.ClientPayloadError as exc:
        return FetchResult(url, 0, "", b"", loop.time() - start, error=f"payload:{exc}")
    except aiohttp.ClientError as exc:
        return FetchResult(url, 0, "", b"", loop.time() - start, error=f"client:{exc}")
    except UnicodeError as exc:
        return FetchResult(url, 0, "", b"", loop.time() - start, error=f"unicode:{exc}")
    except Exception as exc:  # noqa: BLE001 - last-ditch guard for the worker loop
        return FetchResult(url, 0, "", b"", loop.time() - start, error=f"unexpected:{exc!r}")


def _content_type_allowed(ctype: str, allowed: tuple[str, ...]) -> bool:
    return any(ctype == a or ctype.startswith(a) for a in allowed)


async def _read_capped(resp: aiohttp.ClientResponse, cap: int) -> bytes:
    """Read up to `cap` bytes from the response body, then stop reading."""
    if cap <= 0:
        return await resp.read()
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.content.iter_chunked(64 * 1024):
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= cap:
            break
    return b"".join(chunks)
