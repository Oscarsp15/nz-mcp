"""Human-readable formatting helpers for catalog metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_UNITS: tuple[str, ...] = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
_IEC_BASE: int = 1024


def format_timestamp_iso(value: Any) -> str | None:
    """Return an ISO-8601 string for a catalog timestamp value, or ``None``.

    Handles three driver representations:
    - ``None`` → ``None``
    - A ``datetime`` (or any object with ``.isoformat()``) → ``isoformat()``
    - An integer or numeric string (Unix epoch in seconds) → UTC ISO-8601
    """
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    try:
        epoch = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def format_bytes_iec(n: int) -> str:
    """Format ``n`` bytes using IEC binary units (KiB = 1024 B), one fractional digit."""
    if n < 0:
        raise ValueError("byte count must be non-negative")
    if n == 0:
        return "0 B"
    idx = 0
    size = float(n)
    while size >= _IEC_BASE and idx < len(_UNITS) - 1:
        size /= _IEC_BASE
        idx += 1
    if idx == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {_UNITS[idx]}"
