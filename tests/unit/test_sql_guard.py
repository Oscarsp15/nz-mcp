"""sql_guard happy-path tests by mode."""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError, PermissionDeniedError
from nz_mcp.sql_guard import StatementKind, validate


@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT * FROM t WHERE id = 1"])
def test_select_passes_in_read(sql: str) -> None:
    parsed = validate(sql, mode="read")
    assert parsed.kind is StatementKind.SELECT


def test_union_all_select_passes_in_read() -> None:
    parsed = validate("SELECT 1 AS a UNION ALL SELECT 2 AS a", mode="read")
    assert parsed.kind is StatementKind.SELECT


def test_union_three_selects_passes_in_write() -> None:
    parsed = validate(
        "SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3",
        mode="write",
    )
    assert parsed.kind is StatementKind.SELECT


def test_insert_select_with_union_inner_passes_in_write() -> None:
    parsed = validate(
        "INSERT INTO dbo.t (a, b) SELECT 'x', 1 UNION ALL SELECT 'y', 2",
        mode="write",
    )
    assert parsed.kind is StatementKind.INSERT


def test_explain_passes_in_read() -> None:
    parsed = validate("EXPLAIN SELECT 1", mode="read")
    assert parsed.kind is StatementKind.EXPLAIN


def test_show_passthrough_command_parses_as_show() -> None:
    parsed = validate("SHOW DATABASES", mode="read")
    assert parsed.kind is StatementKind.SHOW


def test_insert_blocked_in_read() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("INSERT INTO t (a) VALUES (1)", mode="read")
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


def test_insert_passes_in_write() -> None:
    parsed = validate("INSERT INTO t (a) VALUES (1)", mode="write")
    assert parsed.kind is StatementKind.INSERT


def test_update_with_where_passes_in_write() -> None:
    parsed = validate("UPDATE t SET a = 1 WHERE id = 5", mode="write")
    assert parsed.kind is StatementKind.UPDATE
    assert parsed.has_where is True


def test_delete_with_where_passes_in_write() -> None:
    parsed = validate("DELETE FROM t WHERE id = 5", mode="write")
    assert parsed.kind is StatementKind.DELETE


def test_create_blocked_in_write() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("CREATE TABLE x (id INT)", mode="write")
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


def test_create_passes_in_admin() -> None:
    parsed = validate("CREATE TABLE x (id INT)", mode="admin")
    assert parsed.kind is StatementKind.CREATE


def test_drop_passes_in_admin() -> None:
    parsed = validate("DROP TABLE x", mode="admin")
    assert parsed.kind is StatementKind.DROP


def test_truncate_passes_in_admin() -> None:
    parsed = validate("TRUNCATE TABLE x", mode="admin")
    assert parsed.kind is StatementKind.TRUNCATE


def test_empty_string_rejected() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("", mode="read")
    assert exc.value.code == "EMPTY_STATEMENT"


def test_whitespace_only_rejected() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("   \n\t  ", mode="read")
    assert exc.value.code == "EMPTY_STATEMENT"


def test_validate_trivial_nzplsql_procedure() -> None:
    sql = "CREATE OR REPLACE PROCEDURE DBO.TGT()\nLANGUAGE NZPLSQL AS\nBEGIN\n  NULL;\nEND;\n"
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE
    assert parsed.raw == sql


def test_validate_procedure_with_declarations() -> None:
    sql = """CREATE OR REPLACE PROCEDURE DBO.TGT(DATE)
RETURNS INTEGER
LANGUAGE NZPLSQL AS
DECLARE
  v_campo VARCHAR(10000);
BEGIN
  RETURN 0;
END;
"""
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE


def test_validate_procedure_with_loops() -> None:
    sql = """CREATE OR REPLACE PROCEDURE SCH.P()
RETURNS INTEGER
LANGUAGE NZPLSQL AS
BEGIN
  FOR r IN SELECT 1 AS x FROM DUAL LOOP
    EXIT;
  END LOOP;
  RETURN 0;
END;
"""
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE


def test_validate_procedure_with_exception() -> None:
    sql = """CREATE OR REPLACE PROCEDURE SCH.P()
RETURNS INTEGER
LANGUAGE NZPLSQL AS
BEGIN
  NULL;
EXCEPTION WHEN OTHERS THEN
  NULL;
END;
"""
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE


def test_validate_procedure_requires_admin_mode() -> None:
    sql = "CREATE PROCEDURE A.B()\nLANGUAGE NZPLSQL AS\nBEGIN NULL; END;\n"
    with pytest.raises(PermissionDeniedError):
        validate(sql, mode="write")


def test_validate_malformed_nzplsql_missing_body() -> None:
    sql = "CREATE PROCEDURE A.B()\nLANGUAGE NZPLSQL AS\n"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"


def test_validate_nzplsql_procedure_rejects_overlong_catalog_identifier() -> None:
    long_schema = "S" * 130
    sql = f"CREATE PROCEDURE {long_schema}.P()\nLANGUAGE NZPLSQL AS\nBEGIN NULL; END;\n"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"
    assert "identifier" in str(exc.value).lower()


def test_validate_malformed_procedure_header_unqualified() -> None:
    sql = "CREATE PROCEDURE UNQUALIFIED()\nLANGUAGE NZPLSQL AS\nBEGIN NULL; END;\n"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"


def test_validate_non_procedure_statements_still_parsed() -> None:
    assert validate("INSERT INTO t (a) VALUES (1)", mode="write").kind is StatementKind.INSERT
    assert validate("CREATE TABLE x (id INT)", mode="admin").kind is StatementKind.CREATE


def test_validate_create_table_without_language_nzplsql_not_header_only_path() -> None:
    """Statements without ``LANGUAGE NZPLSQL AS`` stay on the sqlglot path."""
    sql = "CREATE TABLE z (a INT)"
    assert "LANGUAGE" not in sql
    assert validate(sql, mode="admin").kind is StatementKind.CREATE


def test_validate_netezza_drop_table_if_exists_suffix() -> None:
    parsed = validate("DROP TABLE DBO.X IF EXISTS", mode="admin")
    assert parsed.kind is StatementKind.DROP


def test_validate_netezza_drop_if_exists_suffix_rejected_in_read() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("DROP TABLE DBO.X IF EXISTS", mode="read")
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


def test_validate_nzplsql_procedure_with_begin_proc_wrapped_body() -> None:
    sql = (
        "CREATE PROCEDURE DBO.P()\n"
        "RETURNS INTEGER\n"
        "LANGUAGE NZPLSQL AS\n"
        "BEGIN_PROC\n"
        "DECLARE x INT;\n"
        "BEGIN NULL; END;\n"
        "END_PROC;\n"
    )
    parsed = validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE
