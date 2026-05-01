"""HTML parsing: extract links and the page title.

We use selectolax (Modest-engine bindings) which is roughly an order of
magnitude faster than BeautifulSoup for this workload. The parser is the
hot CPU path - everything here is biased toward throughput, not
ergonomics.
"""

from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser


@dataclass(slots=True)
class ParsedPage:
    title: str
    links: list[str]


def parse_html(body: bytes, content_type: str = "") -> ParsedPage:
    """Parse a page body and return its title plus discovered links."""
    if not body:
        return ParsedPage(title="", links=[])

    html = _decode(body, content_type)
    if not html:
        return ParsedPage(title="", links=[])

    try:
        tree = HTMLParser(html)
    except Exception:
        return ParsedPage(title="", links=[])

    if tree.body is None:
        return ParsedPage(title="", links=[])

    base_url = ""
    base = tree.css_first("base[href]")
    if base is not None:
        base_url = (base.attributes.get("href") or "").strip()

    title = ""
    title_node = tree.css_first("title")
    if title_node is not None:
        title = (title_node.text() or "").strip()
        if len(title) > 512:
            title = title[:512]

    links: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        if base_url and not href.startswith(("http://", "https://", "//")):
            href = _join(base_url, href)
        links.append(href)

    return ParsedPage(title=title, links=links)


def _decode(body: bytes, content_type: str) -> str:
    """Decode response bytes to text, taking a charset hint from headers."""
    encoding = ""
    if content_type and "charset=" in content_type:
        encoding = content_type.split("charset=", 1)[1].strip().strip('"').strip("'")

    for enc in (encoding, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            return body.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _join(base: str, ref: str) -> str:
    from urllib.parse import urljoin

    try:
        return urljoin(base, ref)
    except Exception:
        return ref
