"""Tests for IEC byte formatting."""

from __future__ import annotations

import pytest

from nz_mcp.catalog.formatters import format_bytes_iec


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1048576, "1.0 MiB"),
        (1536, "1.5 KiB"),
    ],
)
def test_format_bytes_iec(n: int, expected: str) -> None:
    assert format_bytes_iec(n) == expected


def test_format_bytes_iec_negative_raises() -> None:
    with pytest.raises(ValueError):
        format_bytes_iec(-1)
