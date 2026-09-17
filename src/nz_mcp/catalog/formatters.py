"""Human-readable formatting helpers for catalog metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_UNITS: tuple[str, ...] = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
_IEC_BASE: int = 1024


def format_timestamp_iso(value: Any) -> str | None:
    """Return an ISO-8601 string for a catalog timestamp value, or ``None``.

    Handles four driver representations:
    - ``None`` → ``None``
    - A ``datetime`` (or any object with ``.isoformat()``) → ``isoformat()``
    - An integer (nzpy JOIN epoch, already offset by client TZ) → UTC ISO-8601
      via ``fromtimestamp(epoch).replace(UTC)`` to cancel the client offset
    - A naive ``'YYYY-MM-DD HH:MM:SS'`` string (nzpy TIMESTAMP columns or ABSTIME
      in simple SELECT) → UTC ISO-8601; Netezza SaaS runs in UTC (verified 2026-09-17)
    """
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    try:
        epoch = int(value)
        # nzpy delivers _V_TABLE.CREATEDATE as a TZ-offset-adjusted integer in JOIN
        # queries (epoch = true_epoch - local_utc_offset). Using fromtimestamp()
        # without an explicit tz interprets it as local time, which numerically
        # equals the server's UTC wall clock. replace(tzinfo=UTC) then stamps it.
        return datetime.fromtimestamp(epoch).replace(tzinfo=UTC).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    except ValueError:
        return str(value)


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
