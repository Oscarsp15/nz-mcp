"""Adversarial tests against the sql_guard.

Each entry must remain blocked. Adding a new bypass goes here BEFORE the fix.
"""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import validate


@pytest.mark.adversarial
@pytest.mark.parametrize(
    ("sql", "expected_code"),
    [
        ("SELECT 1; DROP TABLE t;", "STACKED_NOT_ALLOWED"),
        ("SELECT * FROM t; SELECT * FROM s;", "STACKED_NOT_ALLOWED"),
        ("BEGIN; DELETE FROM t WHERE id=1; COMMIT;", "STACKED_NOT_ALLOWED"),
        ("UPDATE t SET a = 1", "UPDATE_REQUIRES_WHERE"),
        ("DELETE FROM t", "DELETE_REQUIRES_WHERE"),
        ("DROP DATABASE mydb", "STATEMENT_NOT_ALLOWED"),
    ],
)
def test_blocked_in_read(sql: str, expected_code: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="read")
    assert exc.value.code == expected_code


@pytest.mark.adversarial
def test_cte_with_delete_blocked() -> None:
    sql = "WITH x AS (DELETE FROM t WHERE id=1 RETURNING *) SELECT * FROM x"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="read")
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


@pytest.mark.adversarial
def test_update_without_where_blocked_in_admin() -> None:
    """Even admin mode does not allow UPDATE without WHERE."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("UPDATE t SET a = 1", mode="admin")
    assert exc.value.code == "UPDATE_REQUIRES_WHERE"


@pytest.mark.adversarial
def test_delete_without_where_blocked_in_admin() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("DELETE FROM t", mode="admin")
    assert exc.value.code == "DELETE_REQUIRES_WHERE"


@pytest.mark.adversarial
@pytest.mark.parametrize("mode", ["read", "write", "admin"])
def test_grant_blocked_in_all_modes(mode: str) -> None:
    with pytest.raises(GuardRejectedError):
        validate("GRANT SELECT ON t TO u", mode=mode)  # type: ignore[arg-type]


@pytest.mark.adversarial
def test_vacuum_command_blocked_as_unknown_statement() -> None:
    """Command nodes that are not SHOW/EXPLAIN stay UNKNOWN (no unintended allowlist)."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("VACUUM FULL my_table", mode="read")
    assert exc.value.code == "UNKNOWN_STATEMENT"


@pytest.mark.adversarial
def test_non_read_command_blocked_as_unknown_statement() -> None:
    """Other sqlglot Command statements must not bypass classification as read-only."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("REINDEX TABLE t", mode="read")
    assert exc.value.code == "UNKNOWN_STATEMENT"


@pytest.mark.adversarial
def test_show_stacked_with_select_blocked() -> None:
    """SHOW ... must not hide a second stacked statement."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("SHOW DATABASES; SELECT 1", mode="read")
    assert exc.value.code == "STACKED_NOT_ALLOWED"
