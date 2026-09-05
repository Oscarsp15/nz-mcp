"""Adversarial tests against the sql_guard.

Each entry must remain blocked. Adding a new bypass goes here BEFORE the fix.
"""

from __future__ import annotations

import pytest
import sqlglot

from nz_mcp.errors import GuardRejectedError
from nz_mcp.sql_guard import (
    StatementKind,
    _assert_selective_where,
    validate,
    validate_catalog_override,
)


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
def test_selective_where_helper_tolerates_a_missing_where() -> None:
    """The WHERE-less guard inside the helper is defensive and must stay.

    Through ``validate`` it is unreachable: ``_enforce`` rejects a WHERE-less UPDATE or
    DELETE first. It is kept so the helper cannot crash on ``where.this`` if that order
    ever changes, and it is exercised directly rather than left uncovered.
    """
    expr = sqlglot.parse_one("UPDATE t SET a = 1", read="postgres")
    _assert_selective_where(expr, kind=StatementKind.UPDATE, confirm_full_table=False)


def test_mode_rejection_wins_over_tautology_hint() -> None:
    """A caller who may not DELETE is told that, not invited to retry with the flag.

    ``confirm_full_table`` cannot rescue a statement the mode forbids, so suggesting it
    would send the model down a path that fails again (audit of PR #173).
    """
    with pytest.raises(GuardRejectedError) as excinfo:
        validate("DELETE FROM t WHERE 1 = 1", mode="read")
    assert excinfo.value.code == "STATEMENT_NOT_ALLOWED"


def test_confirm_full_table_does_not_grant_mode_privileges() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate("DELETE FROM t WHERE 1 = 1", mode="read", confirm_full_table=True)
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


@pytest.mark.adversarial
def test_tautological_where_in_select_is_allowed() -> None:
    """The check targets mutations only; a SELECT scanning everything is not destructive."""
    assert validate("SELECT * FROM t WHERE 1 = 1", mode="read").kind is StatementKind.SELECT


# --- catalog_overrides (profiles.toml) ----------------------------------------
# The SQL of a catalog override used to reach the driver verbatim, bypassing barriers 1
# and 2 (issue #139, ADR 0022). Everything below must stay rejected.


@pytest.mark.adversarial
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM _V_TABLE WHERE 1 = 1",
        "DROP TABLE ADMIN.CUSTOMERS",
        "TRUNCATE TABLE ADMIN.CUSTOMERS",
        "INSERT INTO ADMIN.AUDIT VALUES (1)",
        "UPDATE ADMIN.CUSTOMERS SET NAME = 'x' WHERE ID = 1",
        "SELECT DATABASE FROM _V_DATABASE; DROP TABLE ADMIN.CUSTOMERS",
        "SELECT DATABASE FROM _V_DATABASE; DELETE FROM ADMIN.CUSTOMERS WHERE ID = 1",
        "GRANT ALL ON ADMIN.CUSTOMERS TO PUBLIC",
        "CALL ADMIN.SOME_PROC(?)",
        "CREATE TABLE ADMIN.EXFIL AS SELECT * FROM ADMIN.CUSTOMERS",
        "WITH x AS (DELETE FROM ADMIN.T WHERE ID = 1 RETURNING *) SELECT * FROM x",
        "SELECT * INTO ADMIN.EXFIL FROM ADMIN.CUSTOMERS",
        "SHOW TABLES",
        "EXPLAIN SELECT 1",
        "   ",
        "NOT SQL AT ALL",
    ],
)
def test_catalog_override_rejects_non_read_statements(sql: str) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        validate_catalog_override(sql, query_id="list_databases", profile="dev")
    assert exc.value.code == "CATALOG_OVERRIDE_REJECTED"


@pytest.mark.adversarial
def test_catalog_override_rejects_nzplsql_procedure_body() -> None:
    """A profile override cannot smuggle a procedure definition into a read path.

    ``validate`` answers this one with ``PermissionDeniedError`` (admin required), not
    ``GuardRejectedError``; the override validator must catch both, otherwise it escapes
    as a permission problem of the caller instead of a broken profile.
    """
    sql = (
        "CREATE OR REPLACE PROCEDURE ADMIN.P() RETURNS INT LANGUAGE NZPLSQL AS BEGIN_PROC END_PROC"
    )
    with pytest.raises(GuardRejectedError) as exc:
        validate_catalog_override(sql, query_id="list_databases", profile="dev")
    assert exc.value.code == "CATALOG_OVERRIDE_REJECTED"
    assert exc.value.context["reason"] == "PERMISSION_DENIED"


@pytest.mark.adversarial
def test_catalog_override_rejects_select_into_materializing_a_table() -> None:
    """``SELECT ... INTO t`` classifies as a SELECT but writes a table: a read's clothes."""
    with pytest.raises(GuardRejectedError) as exc:
        validate_catalog_override(
            "SELECT DATABASE INTO ADMIN.EXFIL FROM _V_DATABASE",
            query_id="list_databases",
            profile="dev",
        )
    assert exc.value.context["reason"] == "SELECT_INTO"


@pytest.mark.adversarial
def test_catalog_override_rejects_unresolvable_cross_db_marker() -> None:
    """A ``<BD>`` that is not the ``<BD>..`` sentinel would reach the driver unrendered."""
    with pytest.raises(GuardRejectedError) as exc:
        validate_catalog_override(
            "SELECT SCHEMA FROM <BD>_V_SCHEMA",
            query_id="list_schemas",
            profile="dev",
        )
    assert exc.value.context["reason"] == "UNRESOLVED_BD_MARKER"


@pytest.mark.adversarial
def test_catalog_override_rejection_names_the_entry_without_echoing_the_sql() -> None:
    """The user must learn which override broke; the SQL itself is their config, not ours."""
    with pytest.raises(GuardRejectedError) as exc:
        validate_catalog_override(
            "DROP TABLE ADMIN.SECRET_TABLE",
            query_id="list_tables",
            profile="prod",
        )
    assert exc.value.context["query_id"] == "list_tables"
    assert exc.value.context["profile"] == "prod"
    assert exc.value.context["reason"] == "STATEMENT_NOT_ALLOWED"
    assert "SECRET_TABLE" not in str(exc.value)


@pytest.mark.adversarial
def test_catalog_override_accepts_a_legitimate_read() -> None:
    """A real override keeps working: cross-db marker, placeholders, CTE and UNION."""
    sql = (
        "WITH s AS (SELECT SCHEMA, OWNER FROM <BD>.._V_SCHEMA WHERE (? IS NULL OR SCHEMA = ?)) "
        "SELECT SCHEMA, OWNER FROM s UNION ALL SELECT 'X', 'Y'"
    )
    parsed = validate_catalog_override(sql, query_id="list_schemas", profile="dev")
    assert parsed.kind is StatementKind.SELECT
    # The stored text is returned untouched: rendering the marker is a parsing artifact.
    assert parsed.raw == sql
