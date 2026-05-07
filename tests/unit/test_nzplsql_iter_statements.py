"""Tests for ``iter_statements`` and ``extract_create_or_insert_targeting`` (issue #109)."""

from __future__ import annotations

from nz_mcp.catalog.nzplsql_parser import (
    classify_target_statement,
    extract_create_or_insert_targeting,
    iter_statements,
)

# ── iter_statements ──────────────────────────────────────────────────────────


def test_iter_simple_two_statements() -> None:
    src = "SELECT 1;\nSELECT 2;\n"
    stmts = list(iter_statements(src))
    assert len(stmts) == 2
    assert stmts[0].sql.strip() == "SELECT 1;"
    assert stmts[1].sql.strip() == "SELECT 2;"
    assert stmts[0].line_start == 1 and stmts[0].line_end == 1
    assert stmts[1].line_start == 2 and stmts[1].line_end == 2


def test_iter_semicolon_inside_string_literal_does_not_split() -> None:
    src = "INSERT INTO foo VALUES ('a;b');\nSELECT 1;\n"
    stmts = list(iter_statements(src))
    assert len(stmts) == 2
    assert "'a;b'" in stmts[0].sql


def test_iter_semicolon_inside_block_comment_does_not_split() -> None:
    src = "SELECT 1 /* a; b */;\nSELECT 2;\n"
    stmts = list(iter_statements(src))
    assert len(stmts) == 2
    assert "/* a; b */" in stmts[0].sql


def test_iter_semicolon_inside_line_comment_does_not_split() -> None:
    src = "SELECT 1; -- trailing; comment text\nSELECT 2;\n"
    stmts = list(iter_statements(src))
    # First ``;`` (the real one) closes statement 1; the ``;`` inside the comment
    # must not produce a third empty statement.
    assert len(stmts) == 2


def test_iter_semicolon_inside_double_quoted_identifier() -> None:
    src = 'SELECT 1 AS "weird;name";\nSELECT 2;\n'
    stmts = list(iter_statements(src))
    assert len(stmts) == 2
    assert '"weird;name"' in stmts[0].sql


def test_iter_escaped_single_quote_in_literal() -> None:
    """``''`` inside a literal must not close the literal prematurely."""
    src = "SELECT 'it''s; still in literal';\nSELECT 2;\n"
    stmts = list(iter_statements(src))
    assert len(stmts) == 2


def test_iter_multiline_statement_line_range_tracks_raw_source() -> None:
    src = "CREATE TEMP TABLE foo AS\n  SELECT *\n  FROM bar;\nSELECT 1;\n"
    stmts = list(iter_statements(src))
    assert len(stmts) == 2
    assert stmts[0].line_start == 1
    assert stmts[0].line_end == 3
    assert stmts[1].line_start == 4
    assert stmts[1].line_end == 4


def test_iter_empty_source_yields_nothing() -> None:
    assert list(iter_statements("")) == []


def test_iter_trailing_text_without_semicolon_is_ignored() -> None:
    src = "SELECT 1;\nSELECT 2"
    stmts = list(iter_statements(src))
    assert len(stmts) == 1


# ── classify_target_statement ────────────────────────────────────────────────


def test_classify_create_temp_table() -> None:
    res = classify_target_statement("CREATE TEMP TABLE foo AS SELECT 1;")
    assert res == ("CREATE TEMP TABLE", "foo")


def test_classify_create_temporary_table() -> None:
    res = classify_target_statement("CREATE TEMPORARY TABLE foo AS SELECT 1;")
    assert res == ("CREATE TEMP TABLE", "foo")


def test_classify_create_table() -> None:
    res = classify_target_statement("CREATE TABLE foo AS SELECT 1;")
    assert res == ("CREATE TABLE", "foo")


def test_classify_create_table_qualified() -> None:
    res = classify_target_statement("CREATE TABLE schema.foo AS SELECT 1;")
    assert res == ("CREATE TABLE", "foo")


def test_classify_create_table_bd_dot_dot_table() -> None:
    """Netezza ``bd..table`` syntax (empty middle qualifier)."""
    res = classify_target_statement("CREATE TABLE BD..foo AS SELECT 1;")
    assert res == ("CREATE TABLE", "foo")


def test_classify_create_table_three_part_qualified() -> None:
    res = classify_target_statement("CREATE TABLE bd.s.foo AS SELECT 1;")
    assert res == ("CREATE TABLE", "foo")


def test_classify_insert_with_columns() -> None:
    res = classify_target_statement("INSERT INTO foo (a, b) SELECT 1, 2;")
    assert res == ("INSERT INTO", "foo")


def test_classify_insert_qualified() -> None:
    res = classify_target_statement("INSERT INTO schema.foo SELECT 1;")
    assert res == ("INSERT INTO", "foo")


def test_classify_unsupported_statement_returns_none() -> None:
    assert classify_target_statement("MERGE INTO foo USING bar ON x;") is None
    assert classify_target_statement("UPDATE foo SET x = 1;") is None
    assert classify_target_statement("DELETE FROM foo;") is None
    assert classify_target_statement("TRUNCATE TABLE foo;") is None
    assert classify_target_statement("SELECT * FROM foo;") is None


# ── extract_create_or_insert_targeting ───────────────────────────────────────


def test_extract_simple_create_temp_table() -> None:
    src = "CREATE TEMP TABLE foo AS SELECT 1;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1
    assert matches[0].kind == "CREATE TEMP TABLE"
    assert matches[0].line_start == 1
    assert matches[0].line_end == 1
    assert matches[0].sql.endswith(";")


def test_extract_create_then_insert_in_order() -> None:
    src = "CREATE TABLE foo AS SELECT 1;\nINSERT INTO foo SELECT 2;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert [m.kind for m in matches] == ["CREATE TABLE", "INSERT INTO"]


def test_extract_strips_comments_in_returned_sql() -> None:
    src = "-- preface\nCREATE TEMP TABLE foo AS /* important */ SELECT 1; -- trailer\nSELECT 2;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1
    assert "--" not in matches[0].sql
    assert "/*" not in matches[0].sql
    assert matches[0].sql.endswith(";")


def test_extract_comments_do_not_break_boundaries() -> None:
    """A `;` inside a comment must not split a statement before classification."""
    src = (
        "CREATE TEMP TABLE foo AS\n"
        "  SELECT 1 /* a; b */ AS x,\n"
        "         2 -- inline; comment\n"
        "  FROM dual;\n"
        "SELECT 99;\n"
    )
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1
    # Line range refers to the raw source body, comments included.
    assert matches[0].line_start == 1
    assert matches[0].line_end == 4


def test_extract_string_with_semicolon_does_not_split() -> None:
    src = "INSERT INTO foo VALUES ('a;b');\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1


def test_extract_table_only_in_from_returns_empty() -> None:
    src = "SELECT * FROM foo;\nINSERT INTO bar SELECT * FROM foo;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert matches == []


def test_extract_kinds_filter_excludes_insert() -> None:
    src = "CREATE TABLE foo AS SELECT 1;\nINSERT INTO foo SELECT 2;\n"
    matches = extract_create_or_insert_targeting(
        src, "foo", kinds=("CREATE TABLE", "CREATE TEMP TABLE")
    )
    assert len(matches) == 1
    assert matches[0].kind == "CREATE TABLE"


def test_extract_kinds_filter_excludes_create() -> None:
    src = "CREATE TABLE foo AS SELECT 1;\nINSERT INTO foo SELECT 2;\n"
    matches = extract_create_or_insert_targeting(src, "foo", kinds=("INSERT INTO",))
    assert len(matches) == 1
    assert matches[0].kind == "INSERT INTO"


def test_extract_case_insensitive_match() -> None:
    src = "CREATE TABLE Foo AS SELECT 1;\n"
    matches = extract_create_or_insert_targeting(src, "FOO")
    assert len(matches) == 1
    # Echo preserves the source casing.
    assert matches[0].target_as_written == "Foo"


def test_extract_line_numbers_refer_to_raw_source_with_comments() -> None:
    src = (
        "-- line 1 (header)\n"  # 1
        "-- line 2\n"  # 2
        "CREATE TEMP TABLE foo AS\n"  # 3
        "  SELECT 1\n"  # 4
        "  FROM bar;\n"  # 5
        "-- closing\n"  # 6
    )
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1
    # Statement spans lines 3..5 in the raw source.
    assert matches[0].line_start == 3
    assert matches[0].line_end == 5


def test_extract_qualified_target_matches_simple_input() -> None:
    """``CREATE TABLE schema.foo`` matches when caller asks for ``foo``."""
    src = "CREATE TABLE schema.foo AS SELECT 1;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1


def test_extract_bd_dot_dot_table_matches_simple_input() -> None:
    src = "INSERT INTO BD..foo SELECT 1;\n"
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1


def test_extract_ignores_unrelated_statements() -> None:
    src = (
        "DECLARE x INT;\n"
        "BEGIN\n"
        "  CREATE TEMP TABLE other AS SELECT 1;\n"
        "  CREATE TEMP TABLE foo AS SELECT 2;\n"
        "  INSERT INTO baz SELECT 3;\n"
        "END;\n"
    )
    matches = extract_create_or_insert_targeting(src, "foo")
    assert len(matches) == 1
    assert matches[0].kind == "CREATE TEMP TABLE"


def test_extract_empty_table_input_returns_empty() -> None:
    assert extract_create_or_insert_targeting("CREATE TABLE foo AS SELECT 1;", "") == []
    assert extract_create_or_insert_targeting("CREATE TABLE foo AS SELECT 1;", "   ") == []
