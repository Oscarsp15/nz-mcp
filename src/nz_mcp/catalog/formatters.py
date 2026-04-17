"""Human-readable formatting helpers for catalog metadata."""

from __future__ import annotations

_UNITS: tuple[str, ...] = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
_IEC_BASE: int = 1024


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
