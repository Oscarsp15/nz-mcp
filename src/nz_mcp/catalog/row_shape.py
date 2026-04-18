"""Row-shape helpers for catalog row parsing.

nzpy ``fetchall`` may return list cells (not only tuples) in the outer sequence.
"""

from __future__ import annotations


def is_sequence_row(row: object, min_len: int) -> bool:
    """True if ``row`` is list/tuple with at least ``min_len`` cells (not ``str``/``bytes``)."""
    return isinstance(row, (tuple, list)) and len(row) >= min_len
