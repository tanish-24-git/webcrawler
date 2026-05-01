"""URL normalization, scope matching, and host-key extraction.

Normalization is *the* lever that makes URL deduplication actually work.
Without it, the frontier silently re-crawls the same page through dozens of
trivially-different spellings.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, unquote, urldefrag, urlencode, urljoin, urlsplit, urlunsplit

import tldextract

# tldextract caches the public-suffix list in a writable temp dir by default.
# We disable network refreshes to keep the crawler hermetic.
_TLD = tldextract.TLDExtract(suffix_list_urls=())


_DEFAULT_PORTS = {"http": 80, "https": 443}


# Tracking parameters that change URL identity without changing content.
# Stripping them is the single biggest win for dedup hit-rate on the open web.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_name", "utm_creative_format", "utm_marketing_tactic",
        "gclid", "gclsrc", "dclid", "fbclid", "yclid", "msclkid", "twclid",
        "mc_cid", "mc_eid", "_hsenc", "_hsmi", "hsCtaTracking",
        "ref", "ref_src", "ref_url", "referrer",
        "igshid", "share", "spm",
    }
)


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Resolve, canonicalize, and clean a URL. Return None if unusable."""
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None

    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)

    try:
        parts = urlsplit(url)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    host = (parts.hostname or "").lower()
    if not host:
        return None

    port = parts.port
    netloc = host
    if port and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    # Decode percent-encoded unreserved characters, then re-quote conservatively.
    path = unquote(path)
    if not path.startswith("/"):
        path = "/" + path

    if parts.query:
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        kept.sort()
        query = urlencode(kept, doseq=True)
    else:
        query = ""

    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    """Lowercase host (no port) for politeness keying."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def registered_domain(url: str) -> str:
    """Effective top-level domain plus one label, e.g. 'example.co.uk'."""
    ext = _TLD(url)
    if not ext.domain or not ext.suffix:
        return host_of(url)
    return f"{ext.domain}.{ext.suffix}".lower()


def in_scope(
    url: str,
    seed_hosts: set[str],
    seed_domains: set[str],
    *,
    same_domain_only: bool,
    same_registered_domain: bool,
    allow_subdomains: bool,
) -> bool:
    """Decide whether `url` is within the configured crawl scope."""
    if same_domain_only:
        return host_of(url) in seed_hosts
    if same_registered_domain:
        if registered_domain(url) not in seed_domains:
            return False
        if not allow_subdomains and host_of(url) not in seed_hosts:
            return False
        return True
    return True


def has_blocked_extension(url: str, blocked: tuple[str, ...]) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith(ext) for ext in blocked)


def url_fingerprint(url: str) -> bytes:
    """16-byte stable fingerprint suitable for bloom-filter keys."""
    return hashlib.blake2b(url.encode("utf-8"), digest_size=16).digest()
