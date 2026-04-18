"""Tests for ``catalog.row_shape`` helpers."""

from __future__ import annotations

from nz_mcp.catalog.row_shape import is_sequence_row


def test_is_sequence_row_tuple_and_list() -> None:
    assert is_sequence_row(("a", "b"), 2) is True
    assert is_sequence_row(["a", "b"], 2) is True


def test_is_sequence_row_rejects_short_or_non_sequence() -> None:
    assert is_sequence_row(("a",), 2) is False
    assert is_sequence_row(None, 2) is False
    assert is_sequence_row("ab", 2) is False
