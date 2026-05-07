"""Tests for table reference helpers in ``nzplsql_parser`` (issue #107)."""

from __future__ import annotations

from nz_mcp.catalog.nzplsql_parser import (
    count_table_references,
    iter_table_references_in_statement,
)

# ── single-statement classification ──────────────────────────────────────────


def test_read_from_basic() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM foo;", "foo"))
    assert kinds == ["read"]


def test_read_join_basic() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM bar JOIN foo ON 1;", "foo"))
    assert kinds == ["read"]


def test_read_left_join() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM bar LEFT JOIN foo ON 1;", "foo"))
    assert kinds == ["read"]


def test_read_right_outer_join() -> None:
    kinds = list(
        iter_table_references_in_statement("SELECT 1 FROM bar RIGHT OUTER JOIN foo ON 1;", "foo")
    )
    assert kinds == ["read"]


def test_read_cross_join() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM bar CROSS JOIN foo;", "foo"))
    assert kinds == ["read"]


def test_read_inner_join() -> None:
    kinds = list(
        iter_table_references_in_statement("SELECT 1 FROM bar INNER JOIN foo ON 1;", "foo")
    )
    assert kinds == ["read"]


def test_read_full_outer_join() -> None:
    kinds = list(
        iter_table_references_in_statement("SELECT 1 FROM bar FULL OUTER JOIN foo ON 1;", "foo")
    )
    assert kinds == ["read"]


def test_read_using_clause() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 USING ( foo );", "foo"))
    assert kinds == ["read"]


def test_write_insert_into() -> None:
    kinds = list(iter_table_references_in_statement("INSERT INTO foo SELECT 1;", "foo"))
    assert kinds == ["write"]


def test_write_update() -> None:
    kinds = list(iter_table_references_in_statement("UPDATE foo SET x = 1 WHERE y;", "foo"))
    assert kinds == ["write"]


def test_write_delete_from() -> None:
    kinds = list(iter_table_references_in_statement("DELETE FROM foo WHERE x = 1;", "foo"))
    assert kinds == ["write"]


def test_write_merge_into() -> None:
    kinds = list(
        iter_table_references_in_statement("MERGE INTO foo USING bar ON foo.id = bar.id;", "foo")
    )
    # MERGE INTO foo → write; USING ( bar ) — note USING here lacks parenthesis
    # because MERGE syntax uses ``USING <source>`` not ``USING (<source>)``,
    # so ``bar`` is not detected as a read in this statement.
    assert kinds == ["write"]


def test_write_truncate_table() -> None:
    kinds = list(iter_table_references_in_statement("TRUNCATE TABLE foo;", "foo"))
    assert kinds == ["write"]


def test_write_drop_table() -> None:
    kinds = list(iter_table_references_in_statement("DROP TABLE foo;", "foo"))
    assert kinds == ["write"]


def test_write_drop_table_if_exists() -> None:
    kinds = list(iter_table_references_in_statement("DROP TABLE IF EXISTS foo;", "foo"))
    assert kinds == ["write"]


def test_write_select_into_ctas_form() -> None:
    """``SELECT … INTO <table>`` (and the CTAS variant) classify as write."""
    kinds = list(iter_table_references_in_statement("SELECT 1 INTO foo;", "foo"))
    assert kinds == ["write"]


# ── CTAS standard form (CREATE [TEMP] TABLE … AS SELECT) ────────────────────


def test_write_create_temp_table_as_select() -> None:
    kinds = list(iter_table_references_in_statement("CREATE TEMP TABLE foo AS SELECT 1;", "foo"))
    assert kinds == ["write"]


def test_write_create_table_as_select_with_read() -> None:
    """CTAS writes the target and reads the source table."""
    kinds = list(
        iter_table_references_in_statement("CREATE TABLE foo AS SELECT 1 FROM bar;", "foo")
    )
    assert kinds == ["write"]
    kinds = list(
        iter_table_references_in_statement("CREATE TABLE foo AS SELECT 1 FROM bar;", "bar")
    )
    assert kinds == ["read"]


def test_write_create_table_if_not_exists() -> None:
    kinds = list(
        iter_table_references_in_statement("CREATE TABLE IF NOT EXISTS foo AS SELECT 1;", "foo")
    )
    assert kinds == ["write"]


def test_write_create_temporary_table() -> None:
    """``TEMPORARY`` is the long form of ``TEMP``."""
    kinds = list(
        iter_table_references_in_statement("CREATE TEMPORARY TABLE foo AS SELECT 1;", "foo")
    )
    assert kinds == ["write"]


def test_write_create_temp_table_qualified() -> None:
    kinds = list(
        iter_table_references_in_statement("CREATE TEMP TABLE schema1.foo AS SELECT 1;", "foo")
    )
    assert kinds == ["write"]


def test_write_create_temp_table_if_not_exists() -> None:
    """Both optional groups (TEMP + IF NOT EXISTS) active simultaneously."""
    kinds = list(
        iter_table_references_in_statement(
            "CREATE TEMP TABLE IF NOT EXISTS foo AS SELECT 1;", "foo"
        )
    )
    assert kinds == ["write"]


def test_write_create_table_ddl() -> None:
    """Plain CREATE TABLE (not CTAS) is also classified as write."""
    kinds = list(iter_table_references_in_statement("CREATE TABLE foo (id INT);", "foo"))
    assert kinds == ["write"]


def test_ctas_token_boundary_no_match() -> None:
    """``CREATE TABLE FooBar`` must not match when searching for ``foo``."""
    kinds = list(iter_table_references_in_statement("CREATE TABLE FooBar AS SELECT 1;", "foo"))
    assert kinds == []


def test_ctas_case_insensitive() -> None:
    kinds = list(iter_table_references_in_statement("create temp table FOO as select 1;", "foo"))
    assert kinds == ["write"]


# ── token boundaries ─────────────────────────────────────────────────────────


def test_token_boundary_prefix_no_match() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM FooBar;", "foo"))
    assert kinds == []


def test_token_boundary_suffix_no_match() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM BarFoo;", "foo"))
    assert kinds == []


def test_case_insensitive_match() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM FOO;", "foo"))
    assert kinds == ["read"]
    kinds = list(iter_table_references_in_statement("INSERT INTO Foo VALUES (1);", "FOO"))
    assert kinds == ["write"]


# ── string literal and qualifier filtering ───────────────────────────────────


def test_string_literal_does_not_count() -> None:
    """``'DELETE FROM foo'`` inside a literal must not produce a write."""
    kinds = list(
        iter_table_references_in_statement("INSERT INTO bar VALUES ('DELETE FROM foo');", "foo")
    )
    assert kinds == []


def test_qualified_schema_table_match() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM s1.foo;", "foo"))
    assert kinds == ["read"]


def test_qualified_db_schema_table_match() -> None:
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM db1.s1.foo;", "foo"))
    assert kinds == ["read"]


def test_qualified_db_double_dot_table_match() -> None:
    """Netezza ``bd..table`` form (empty middle qualifier)."""
    kinds = list(iter_table_references_in_statement("SELECT 1 FROM db1..foo;", "foo"))
    assert kinds == ["read"]


def test_table_database_filter_excludes_other_db() -> None:
    kinds = list(
        iter_table_references_in_statement(
            "SELECT 1 FROM otherdb.s.foo;", "foo", table_database="db1"
        )
    )
    assert kinds == []


def test_table_database_filter_accepts_unqualified() -> None:
    """Unqualified references are treated as 'current database/schema' and accepted."""
    kinds = list(
        iter_table_references_in_statement(
            "SELECT 1 FROM foo;", "foo", table_database="db1", table_schema="s1"
        )
    )
    assert kinds == ["read"]


def test_table_schema_filter_excludes_other_schema() -> None:
    kinds = list(
        iter_table_references_in_statement("SELECT 1 FROM s2.foo;", "foo", table_schema="s1")
    )
    assert kinds == []


def test_quoted_identifier_match() -> None:
    kinds = list(iter_table_references_in_statement('SELECT 1 FROM "foo";', "foo"))
    assert kinds == ["read"]


# ── multi-statement counts via count_table_references ────────────────────────


def test_count_table_references_read_and_write() -> None:
    src = (
        "CREATE TEMP TABLE foo AS SELECT 1;\n"
        "SELECT * FROM foo;\n"
        "INSERT INTO foo SELECT 2;\n"
        "SELECT 1 FROM bar JOIN foo ON 1;\n"
    )
    reads, writes = count_table_references(src, "foo")
    assert reads == 2
    # Two writes: CREATE TEMP TABLE foo AS… (CTAS standard form) and the
    # explicit INSERT INTO.
    assert writes == 2


def test_count_table_references_comments_ignored() -> None:
    src = "-- DELETE FROM foo;\n/* INSERT INTO foo VALUES (1); */\nSELECT 1;\n"
    reads, writes = count_table_references(src, "foo")
    assert reads == 0
    assert writes == 0


def test_count_table_references_string_literal_ignored() -> None:
    src = "INSERT INTO bar VALUES ('DELETE FROM foo; INSERT INTO foo VALUES (1)');\n"
    reads, writes = count_table_references(src, "foo")
    assert reads == 0
    assert writes == 0


def test_count_table_references_returns_zero_for_empty_table() -> None:
    reads, writes = count_table_references("INSERT INTO foo SELECT 1;", "")
    assert (reads, writes) == (0, 0)


def test_count_table_references_qualifier_filter() -> None:
    src = "SELECT 1 FROM s1.foo;\nSELECT 1 FROM s2.foo;\nSELECT 1 FROM foo;\n"
    # With table_schema="s1": only s1.foo and unqualified foo count.
    reads, writes = count_table_references(src, "foo", table_schema="s1")
    assert reads == 2
    assert writes == 0
