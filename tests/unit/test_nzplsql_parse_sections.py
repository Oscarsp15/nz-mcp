"""Regression tests for parse_sections with multi-line string literals (#113).

``mask_single_quoted_strings`` replaces newlines inside ``'…'`` with spaces,
so ``masked.splitlines()`` can be shorter than ``source.splitlines()``.
Before the fix, ``_first_plain_begin`` and ``_find_plain_outer_end`` used
the *source* line count as their loop bound, causing ``IndexError`` when
the loop advanced past the end of the (shorter) masked-lines list.
"""

from __future__ import annotations

from nz_mcp.catalog.nzplsql_parser import parse_sections

# ── _find_plain_outer_end crash path ─────────────────────────────────────────


def test_multiline_string_no_outer_end_returns_empty() -> None:
    """SP body with a multi-line string but no closing ``END;``.

    Before the fix this raised ``IndexError`` because the loop bound
    (source line count = 7) exceeded ``len(masked_lines)`` (= 4).
    """
    src = "DECLARE x INT;\nBEGIN\n  v := 'line1\nline2\nline3\nline4';\n  NULL;"
    assert parse_sections(src) == {}


def test_multiline_string_with_valid_outer_end() -> None:
    """Multi-line string inside the body, outer ``END;`` present."""
    src = "DECLARE x INT;\nBEGIN\n  v := 'a\nb\nc';\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec


def test_multiline_string_nested_begin_end() -> None:
    """Nested ``BEGIN`` / ``END;`` with a multi-line string inside."""
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  BEGIN\n"
        "    v := 'a\nb\nc\nd\ne';\n"
        "    NULL;\n"
        "  END;\n"
        "  NULL;\n"
        "END;"
    )
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec
    # Section ranges refer to masked-line numbers, so we only check that
    # the body starts after BEGIN and ends before the outer END;.
    assert sec["body"][0] > sec["declare"][1]


# ── _first_plain_begin crash path ────────────────────────────────────────────


def test_multiline_string_in_declare_no_begin_returns_empty() -> None:
    """Multi-line string in DECLARE, no ``BEGIN`` at all.

    Before the fix this raised ``IndexError`` in ``_first_plain_begin``
    because the loop bound (source line count = 6) exceeded
    ``len(masked_lines)`` (= 2).
    """
    src = "DECLARE\n  v VARCHAR := 'line1\nline2\nline3\nline4\nline5';"
    assert parse_sections(src) == {}


def test_multiline_string_in_declare_with_begin() -> None:
    """Multi-line string in DECLARE, followed by a valid ``BEGIN`` / ``END;``."""
    src = "DECLARE\n  v VARCHAR := 'a\nb\nc';\nBEGIN\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec


# ── large SP simulation ──────────────────────────────────────────────────────


def test_large_sp_many_multiline_strings() -> None:
    """Simulate a large SP with several multi-line string literals.

    Ensures the parser handles the cumulative line-count difference
    between source and masked output without crashing.
    """
    assignments = []
    for i in range(10):
        # Each string literal spans 6 source lines but collapses to 1 masked line.
        assignments.append(f"  v{i} := 'line1\nline2\nline3\nline4\nline5\nline6';")
    body = "\n".join(assignments)
    src = f"DECLARE x INT;\nBEGIN\n{body}\n  NULL;\nEND;"

    sec = parse_sections(src)
    assert "body" in sec


def test_large_sp_nested_blocks_with_multiline_strings() -> None:
    """Nested blocks interleaved with multi-line strings."""
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  v1 := 'a\nb\nc';\n"
        "  BEGIN\n"
        "    v2 := 'd\ne\nf';\n"
        "    NULL;\n"
        "  END;\n"
        "  v3 := 'g\nh\ni';\n"
        "  BEGIN\n"
        "    NULL;\n"
        "  END;\n"
        "  NULL;\n"
        "END;"
    )
    sec = parse_sections(src)
    assert "body" in sec


# ── edge cases ───────────────────────────────────────────────────────────────


def test_multiline_string_with_exception_block() -> None:
    """Multi-line string in body, followed by EXCEPTION block."""
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  v := 'a\nb\nc';\n"
        "  SELECT 1;\n"
        "EXCEPTION\n"
        "  WHEN OTHERS THEN\n"
        "    NULL;\n"
        "END;"
    )
    sec = parse_sections(src)
    assert "body" in sec
    assert "exception" in sec


def test_multiline_string_spanning_many_lines() -> None:
    """Single string literal spanning many lines (extreme case)."""
    inner = "\n".join(f"line{i}" for i in range(50))
    src = f"DECLARE x INT;\nBEGIN\n  v := '{inner}';\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "body" in sec


def test_empty_multiline_string() -> None:
    """String literal containing only newlines."""
    src = "DECLARE x INT;\nBEGIN\n  v := '\n\n\n';\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "body" in sec


# ── line-alignment with CR inside literals (issue #119) ──────────────────────


def test_carriage_return_inside_literal_preserves_section_detection() -> None:
    """A bare CR inside a literal must not shift the masked-line index.

    Before issue #119's fix, ``mask_single_quoted_strings`` blanked the CR
    along with every other in-literal byte; ``str.splitlines`` then yielded
    fewer lines for the masked source than for the raw source. The downstream
    bound checks acted on the shorter universe and ``parse_sections`` could
    miss the outer ``END;``, returning ``{}`` for procedures whose body was
    perfectly well formed.
    """
    src = "DECLARE x INT;\nBEGIN\n  v := 'abc\rxyz';\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec
    # The outer END; sits on the last raw line; ``body`` must close just
    # before it.
    assert sec["body"][1] == len(src.splitlines()) - 1


def test_apostrophe_inside_line_comment_does_not_open_phantom_literal() -> None:
    """An apostrophe inside a ``--`` comment must not poison subsequent lines.

    Without comment-aware masking, the ``'`` inside ``-- (10.Feb'`` would open
    a fake literal that stayed open until the next real ``'`` many lines
    below, blanking the outer ``END;`` and causing ``sections_detected`` to
    come back empty for real procedures (issue #119 second half).
    """
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  -- WCA$5 nueva regla parche de modelo (10.Feb'\n"
        "  v := 'plain literal';\n"
        "  NULL;\n"
        "END;"
    )
    sec = parse_sections(src)
    assert "body" in sec


def test_apostrophe_inside_block_comment_does_not_open_phantom_literal() -> None:
    """Same as above for ``/* … */`` block comments."""
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  /* it's a comment\n"
        "     spanning\n"
        "     multiple lines */\n"
        "  NULL;\n"
        "END;"
    )
    sec = parse_sections(src)
    assert "body" in sec
    # Body must run from BEGIN+1 to END-1 inclusive.
    assert sec["body"][0] == 3
    assert sec["body"][1] == 6


def test_many_crs_inside_literal_keep_outer_end_visible() -> None:
    """Stress test: a literal with many bare CRs across the body.

    ``mask_literals_preserving_lines`` must keep every CR untouched so the
    masked source splits into the same number of lines as the raw source.
    """
    crs = "x\r" * 20
    src = f"DECLARE x INT;\nBEGIN\n  v := '{crs}';\n  NULL;\nEND;"
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec
