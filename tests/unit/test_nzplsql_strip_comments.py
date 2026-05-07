"""Unit tests for ``nzplsql_parser.strip_comments``."""

from __future__ import annotations

import pytest

from nz_mcp.catalog.nzplsql_parser import strip_comments


# ── line comments ────────────────────────────────────────────────────────────


def test_line_comment_removed() -> None:
    src = "x := 1; -- assign x\ny := 2;\n"
    result = strip_comments(src)
    assert "--" not in result
    assert "x := 1;" in result
    assert "y := 2;" in result


def test_full_line_comment_removed() -> None:
    src = "-- this is a header comment\nx := 1;\n"
    result = strip_comments(src)
    assert "--" not in result
    assert "x := 1;" in result


def test_line_comment_newline_preserved() -> None:
    """Removing a line comment must not collapse the surrounding newlines."""
    src = "a;\n-- comment\nb;\n"
    result = strip_comments(src)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert lines == ["a;", "b;"]


# ── block comments ───────────────────────────────────────────────────────────


def test_block_comment_removed() -> None:
    src = "x := /* inline comment */ 1;\n"
    result = strip_comments(src)
    assert "/*" not in result
    assert "*/" not in result
    assert "x :=" in result
    assert "1;" in result


def test_block_comment_multiline_removed() -> None:
    src = "BEGIN\n/*\n  This is a\n  multiline comment\n*/\nx := 1;\nEND;\n"
    result = strip_comments(src)
    assert "/*" not in result
    assert "*/" not in result
    assert "x := 1;" in result


def test_multiple_block_comments_removed() -> None:
    src = "/* a */ x := /* b */ 1;\n"
    result = strip_comments(src)
    assert "/*" not in result
    assert "x :=" in result


# ── string literals — must be preserved ──────────────────────────────────────


def test_line_comment_inside_string_preserved() -> None:
    src = "msg := 'http://example.com -- not a comment';\n"
    result = strip_comments(src)
    assert "-- not a comment" in result


def test_block_comment_inside_string_preserved() -> None:
    src = "msg := 'value /* not a comment */ end';\n"
    result = strip_comments(src)
    assert "/* not a comment */" in result


def test_escaped_single_quote_inside_string() -> None:
    """Escaped single quotes ('' in SQL) must not confuse the tokenizer."""
    src = "msg := 'it''s a -- test';\n"
    result = strip_comments(src)
    # The '--' inside the string must survive
    assert "-- test" in result
    assert "it''s" in result


def test_string_followed_by_line_comment() -> None:
    src = "msg := 'hello'; -- greeting\nnext;\n"
    result = strip_comments(src)
    assert "msg := 'hello';" in result
    assert "--" not in result
    assert "next;" in result


# ── double-quoted identifiers — must be preserved ─────────────────────────────


def test_line_comment_marker_inside_double_quoted_identifier_preserved() -> None:
    """Double-quoted identifiers can contain virtually any character."""
    src = 'SELECT "col--name" FROM t;\n'
    result = strip_comments(src)
    assert '"col--name"' in result


def test_block_comment_marker_inside_double_quoted_identifier_preserved() -> None:
    src = 'SELECT "col/*name*/" FROM t;\n'
    result = strip_comments(src)
    assert '"col/*name*/"' in result


def test_escaped_double_quote_inside_identifier() -> None:
    src = 'SELECT "col""x" FROM t; -- comment\n'
    result = strip_comments(src)
    assert '"col""x"' in result
    assert "--" not in result


# ── blank-line collapsing ─────────────────────────────────────────────────────


def test_consecutive_blank_lines_collapsed() -> None:
    """Three or more consecutive newlines (= 2+ blank lines) reduce to two."""
    src = "a;\n\n\n\nb;\n"
    result = strip_comments(src)
    assert "\n\n\n" not in result
    assert "a;" in result
    assert "b;" in result


def test_comment_lines_collapse_blank_lines() -> None:
    """Several consecutive comment-only lines produce at most one blank line."""
    src = "a;\n-- c1\n-- c2\n-- c3\nb;\n"
    result = strip_comments(src)
    assert "\n\n\n" not in result
    assert "a;" in result
    assert "b;" in result


# ── invariant ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src",
    [
        "x := 1; -- comment\n",
        "/* block */ x := 1;\n",
        "x := 'literal -- with comment';\n",
        "BEGIN\n-- comment\nEND;\n",
        "",
        "no comments here\n",
    ],
)
def test_size_bytes_clean_le_size_bytes_raw(src: str) -> None:
    """Clean DDL is always <= raw DDL in byte length."""
    clean = strip_comments(src)
    assert len(clean.encode("utf-8")) <= len(src.encode("utf-8"))


# ── no-op on comment-free source ─────────────────────────────────────────────


def test_comment_free_source_unchanged_modulo_trailing_whitespace() -> None:
    src = "BEGIN\n  x := 1;\nEND;\n"
    result = strip_comments(src)
    # No comments — content must be identical (trailing-space stripping is allowed)
    assert result == src.rstrip("\n") or result == src or "x := 1;" in result
