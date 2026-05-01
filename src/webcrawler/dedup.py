"""URL deduplication.

At 100M URLs the only viable structures are bloom filters or sharded sets.
A bloom filter with capacity=200M, p=0.001 takes ~340 MiB of RAM, which is
the right operating point for a single node. False positives cause us to
*skip* a URL we have not actually seen, which is acceptable; false
negatives cannot occur.
"""

from __future__ import annotations

from typing import Protocol

try:
    from pybloom_live import ScalableBloomFilter  # type: ignore[import-not-found]
    _HAS_BLOOM = True
except ImportError:  # pragma: no cover - optional fallback
    _HAS_BLOOM = False


class SeenSet(Protocol):
    def add(self, key: str) -> bool: ...
    def __contains__(self, key: object) -> bool: ...
    def __len__(self) -> int: ...


class BloomSeenSet:
    """Memory-efficient probabilistic seen-set for very large crawls."""

    __slots__ = ("_bloom", "_count")

    def __init__(self, capacity: int = 200_000_000, error_rate: float = 0.001) -> None:
        if not _HAS_BLOOM:
            raise RuntimeError(
                "pybloom-live is required for BloomSeenSet. "
                "Install it or use ExactSeenSet for small crawls."
            )
        self._bloom = ScalableBloomFilter(
            initial_capacity=min(capacity, 1_000_000),
            error_rate=error_rate,
            mode=ScalableBloomFilter.LARGE_SET_GROWTH,
        )
        self._count = 0

    def add(self, key: str) -> bool:
        """Return True if key was newly added, False if already present."""
        if self._bloom.add(key):
            return False
        self._count += 1
        return True

    def __contains__(self, key: object) -> bool:
        return key in self._bloom

    def __len__(self) -> int:
        return self._count


class ExactSeenSet:
    """Exact in-memory set. Fine for crawls under a few million URLs."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def add(self, key: str) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def __contains__(self, key: object) -> bool:
        return key in self._seen

    def __len__(self) -> int:
        return len(self._seen)


def make_seen_set(capacity: int, error_rate: float) -> SeenSet:
    """Pick the right seen-set implementation for the configured capacity."""
    if capacity <= 1_000_000 or not _HAS_BLOOM:
        return ExactSeenSet()
    return BloomSeenSet(capacity=capacity, error_rate=error_rate)
