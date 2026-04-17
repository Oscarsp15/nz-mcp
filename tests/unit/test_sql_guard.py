"""sql_guard happy-path tests by mode."""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import StatementKind, validate


@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT * FROM t WHERE id = 1"])
def test_select_passes_in_read(sql: str) -> None:
    parsed = validate(sql, mode="read")
    assert parsed.kind is StatementKind.SELECT


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
