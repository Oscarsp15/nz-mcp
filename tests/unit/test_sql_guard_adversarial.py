"""Adversarial tests against the sql_guard.

Each entry must remain blocked. Adding a new bypass goes here BEFORE the fix.
"""

from __future__ import annotations

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import StatementKind, validate


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


@pytest.mark.adversarial
def test_nzplsql_procedure_header_stacked_blocked() -> None:
    sql = "CREATE PROCEDURE A.B(); DROP TABLE t; LANGUAGE NZPLSQL AS\nBEGIN NULL; END;\n"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code == "STACKED_NOT_ALLOWED"


@pytest.mark.adversarial
def test_nzplsql_procedure_invalid_identifier_blocked() -> None:
    sql = "CREATE PROCEDURE 1A.B()\nLANGUAGE NZPLSQL AS\nBEGIN NULL; END;\n"
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode="admin")
    assert exc.value.code == "UNKNOWN_STATEMENT"


@pytest.mark.adversarial
def test_union_all_followed_by_stacked_select_blocked() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("SELECT 1 UNION ALL SELECT 2; SELECT 3", mode="read")
    assert exc.value.code == "STACKED_NOT_ALLOWED"


@pytest.mark.adversarial
def test_intersect_blocked_as_unknown_statement() -> None:
    """INTERSECT is not classified as SELECT (only UNION / UNION ALL trees are)."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("SELECT 1 INTERSECT SELECT 1", mode="read")
    assert exc.value.code == "UNKNOWN_STATEMENT"


@pytest.mark.adversarial
def test_except_blocked_as_unknown_statement() -> None:
    """EXCEPT is not classified as SELECT."""
    with pytest.raises(GuardRejectedError) as exc:
        validate("SELECT 1 EXCEPT SELECT 1", mode="read")
    assert exc.value.code == "UNKNOWN_STATEMENT"


# --- Tautological WHERE (issue #140) ------------------------------------------
# ``WHERE 1=1`` satisfies "there is a WHERE clause" while matching every row, so the
# UPDATE/DELETE guard is worthless without static predicate analysis. Only the forms
# listed in docs/adr/0020-sql-guard-tautological-where.md are detected.


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        # Numeric tautologies.
        "UPDATE t SET a = 1 WHERE 1 = 1",
        "DELETE FROM t WHERE 1=1",
        "UPDATE t SET a = 1 WHERE 2 > 1",
        "DELETE FROM t WHERE 9 < 10",
        "DELETE FROM t WHERE 1 <> 2",
        "UPDATE t SET a = 1 WHERE -1 < 1",
        "DELETE FROM t WHERE (1) = 1",
        # Bare literal used as a predicate.
        "DELETE FROM t WHERE 1",
        # Boolean literals.
        "DELETE FROM t WHERE TRUE",
        "UPDATE t SET a = 1 WHERE TRUE = TRUE",
        "DELETE FROM t WHERE NOT FALSE",
        "DELETE FROM t WHERE NOT (1 = 2)",
        # Text literal tautologies.
        "DELETE FROM t WHERE 'a' = 'a'",
        "UPDATE t SET a = 1 WHERE 'x' <> 'y'",
        # OR neutralising a real predicate.
        "UPDATE t SET a = 1 WHERE id = 5 OR 1 = 1",
        "DELETE FROM t WHERE id = 5 OR TRUE",
        # AND of two tautologies, and parenthesised forms.
        "DELETE FROM t WHERE 1 = 1 AND 2 > 1",
        "DELETE FROM t WHERE (1 = 1)",
        # Self comparison: never restricts rows beyond NULLs.
        "DELETE FROM t WHERE id = id",
    ],
)
@pytest.mark.parametrize("mode", ["write", "admin"])
def test_tautological_where_blocked(sql: str, mode: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate(sql, mode=mode)  # type: ignore[arg-type]
    assert exc.value.code == "WHERE_ALWAYS_TRUE"


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        # Selective predicates: the normal case must keep working.
        "UPDATE t SET a = 1 WHERE id = 5",
        "DELETE FROM t WHERE id IS NOT NULL",
        "DELETE FROM t WHERE a = b",
        "DELETE FROM t WHERE a.id = b.id",
        "DELETE FROM t WHERE -id = 1",
        "DELETE FROM t WHERE id > 1",
        "DELETE FROM t WHERE id = 5 OR id = 6",
        "DELETE FROM t WHERE a = 1 AND b = 2",
        "UPDATE t SET a = 1 WHERE 1 = 1 AND id = 5",
        "DELETE FROM t WHERE NOT (id = 1)",
        # Statically false predicates affect no row: nothing to protect against.
        "DELETE FROM t WHERE 1 = 2",
        "DELETE FROM t WHERE 0",
        "DELETE FROM t WHERE 'a' = 'b'",
        "DELETE FROM t WHERE 1 = 2 AND id = 5",
        "DELETE FROM t WHERE 1 = 2 OR 'a' = 'b'",
        # Non-boolean bare literal: undecided, not blocked.
        "DELETE FROM t WHERE 'x'",
    ],
)
def test_selective_where_not_blocked(sql: str) -> None:
    """No false positives: real predicates keep passing the guard."""
    assert validate(sql, mode="write").has_where is True


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t WHERE ABS(1) = 1",
        "DELETE FROM t WHERE id > -2147483648",
        "DELETE FROM t WHERE '1' = 1",
    ],
)
def test_known_gaps_of_the_tautology_check(sql: str) -> None:
    """Documented limits (ADR 0020): folding stops at literal-only predicates.

    Deciding tautology in general is undecidable; these forms are NOT detected and
    the guard says so explicitly instead of pretending otherwise.
    """
    assert validate(sql, mode="write").has_where is True


@pytest.mark.adversarial
def test_confirm_full_table_allows_the_tautology_explicitly() -> None:
    """The caller may proceed only by declaring full-table intent in the call."""
    parsed = validate("DELETE FROM t WHERE 1 = 1", mode="write", confirm_full_table=True)
    assert parsed.kind is StatementKind.DELETE


@pytest.mark.adversarial
def test_confirm_full_table_does_not_waive_the_where_requirement() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("DELETE FROM t", mode="write", confirm_full_table=True)
    assert exc.value.code == "DELETE_REQUIRES_WHERE"


@pytest.mark.adversarial
def test_confirm_full_table_does_not_grant_mode_privileges() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("DELETE FROM t WHERE 1 = 1", mode="read", confirm_full_table=True)
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


@pytest.mark.adversarial
def test_tautological_where_in_select_is_allowed() -> None:
    """The check targets mutations only; a SELECT scanning everything is not destructive."""
    assert validate("SELECT * FROM t WHERE 1 = 1", mode="read").kind is StatementKind.SELECT
