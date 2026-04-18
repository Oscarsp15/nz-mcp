"""Monotonic timing helpers for tool responses."""

from __future__ import annotations

import time


def monotonic_start() -> float:
    """Return a start time from :func:`time.monotonic`."""
    return time.monotonic()


def monotonic_duration_ms(start: float) -> int:
    """Elapsed milliseconds since ``start`` (non-negative)."""
    return max(0, int((time.monotonic() - start) * 1000))
