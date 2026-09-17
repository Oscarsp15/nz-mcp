"""Catalog logic for row-key comparison between two tables (nz_compare_rows).

Uses COUNT(*) aggregates and EXCEPT to count keys only-in-A, only-in-B, in-both,
and null keys.  All SQL is built from validated identifiers; no user-supplied raw
SQL reaches this module.
"""

from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import (
    render_cross_db,
    validate_catalog_identifier,
    validate_database_identifier,
)
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

_SAMPLE_CAP: Final[int] = 100  # hard cap on sample rows returned to caller


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[str, str] | None = None) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def fetchmany(self, size: int) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _scalar(rows: list[Any]) -> int:
    """Extract an integer COUNT(*) from a single-cell result."""
    if not rows:
        return 0
    row = rows[0]
    cell = row[0] if isinstance(row, (list, tuple)) else row
    if cell is None:
        return 0
    return int(cell)


def _values(rows: list[Any]) -> list[str]:
    """Extract the first column of each row as a list of strings."""
    out: list[str] = []
    for row in rows:
        cell = row[0] if isinstance(row, (list, tuple)) else row
        out.append("" if cell is None else str(cell))
    return out


def _assert_read_only(sql: str) -> None:
    """Defense in depth: every statement is validated as a read-only SELECT."""
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="compare_rows",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )


def _ensure_relations_exist(
    cursor: _CursorLike,
    profile: Profile,
    database: str,
    schema_a: str,
    table_a: str,
    schema_b: str,
    table_b: str,
) -> None:
    """Raise ``ObjectNotFoundError`` before comparing when a table is missing.

    Checks both relations against ``_V_RELATION_COLUMN`` so a missing table surfaces
    as a typed ``OBJECT_NOT_FOUND`` instead of the driver's raw error text.
    """
    sql = render_cross_db(resolve_query("describe_table_columns", profile), database=database)
    for schema_u, table_u in ((schema_a, table_a), (schema_b, table_b)):
        cursor.execute(sql, (schema_u, table_u))
        if not cursor.fetchall():
            raise ObjectNotFoundError(
                detail=(
                    f"Table {table_u!r} does not exist in {database}.{schema_u} "
                    "or is not visible to this profile."
                ),
                object_type="table",
                database=database,
                schema=schema_u,
                table=table_u,
            )


def compare_rows(
    profile: Profile,
    *,
    database: str,
    schema_a: str,
    table_a: str,
    key_a: str,
    schema_b: str,
    table_b: str,
    key_b: str,
    limit: int,
) -> dict[str, Any]:
    """Compare key sets between two tables using COUNT + EXCEPT queries.

    Returns counts and bounded samples for keys only in A, only in B, keys
    appearing in both, and null keys in each side.

    Both tables must be accessible from the active profile's database connection.
    """
    # Validate all identifiers before building SQL.
    db = validate_database_identifier(database)
    sa = validate_catalog_identifier(schema_a)
    ta = validate_catalog_identifier(table_a)
    ka = validate_catalog_identifier(key_a)
    sb = validate_catalog_identifier(schema_b)
    tb = validate_catalog_identifier(table_b)
    kb = validate_catalog_identifier(key_b)

    cap = min(limit, _SAMPLE_CAP)

    # Build all SQL strings from validated identifiers only.

    ref_a = f"{db}.{sa}.{ta}"
    ref_b = f"{db}.{sb}.{tb}"

    sql_only_in_a_count = (
        f"SELECT COUNT(*) FROM ("  # noqa: S608
        f"SELECT {ka} FROM {ref_a} WHERE {ka} IS NOT NULL"
        f" EXCEPT "
        f"SELECT {kb} FROM {ref_b} WHERE {kb} IS NOT NULL"
        f") _nzmcp_only_a"
    )
    sql_only_in_b_count = (
        f"SELECT COUNT(*) FROM ("  # noqa: S608
        f"SELECT {kb} FROM {ref_b} WHERE {kb} IS NOT NULL"
        f" EXCEPT "
        f"SELECT {ka} FROM {ref_a} WHERE {ka} IS NOT NULL"
        f") _nzmcp_only_b"
    )
    sql_in_both_count = (
        f"SELECT COUNT(*) FROM ("  # noqa: S608
        f"SELECT {ka} FROM {ref_a} WHERE {ka} IS NOT NULL"
        f" INTERSECT "
        f"SELECT {kb} FROM {ref_b} WHERE {kb} IS NOT NULL"
        f") _nzmcp_both"
    )
    sql_null_a = f"SELECT COUNT(*) FROM {ref_a} WHERE {ka} IS NULL"  # noqa: S608
    sql_null_b = f"SELECT COUNT(*) FROM {ref_b} WHERE {kb} IS NULL"  # noqa: S608
    sql_sample_only_a = (
        f"SELECT * FROM ("  # noqa: S608
        f"SELECT {ka} FROM {ref_a} WHERE {ka} IS NOT NULL"
        f" EXCEPT "
        f"SELECT {kb} FROM {ref_b} WHERE {kb} IS NOT NULL"
        f") _nzmcp_sample_a LIMIT {cap}"
    )
    sql_sample_only_b = (
        f"SELECT * FROM ("  # noqa: S608
        f"SELECT {kb} FROM {ref_b} WHERE {kb} IS NOT NULL"
        f" EXCEPT "
        f"SELECT {ka} FROM {ref_a} WHERE {ka} IS NOT NULL"
        f") _nzmcp_sample_b LIMIT {cap}"
    )

    for statement in (
        sql_only_in_a_count,
        sql_only_in_b_count,
        sql_in_both_count,
        sql_null_a,
        sql_null_b,
        sql_sample_only_a,
        sql_sample_only_b,
    ):
        _assert_read_only(statement)

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()

    try:
        with closing(connection.cursor()) as cursor:
            _ensure_relations_exist(cursor, profile, db, sa, ta, sb, tb)
            cursor.execute(sql_only_in_a_count)
            only_in_a = _scalar(cursor.fetchall())

            cursor.execute(sql_only_in_b_count)
            only_in_b = _scalar(cursor.fetchall())

            cursor.execute(sql_in_both_count)
            in_both = _scalar(cursor.fetchall())

            cursor.execute(sql_null_a)
            null_keys_a = _scalar(cursor.fetchall())

            cursor.execute(sql_null_b)
            null_keys_b = _scalar(cursor.fetchall())

            cursor.execute(sql_sample_only_a)
            sample_only_in_a = _values(cursor.fetchall())

            cursor.execute(sql_sample_only_b)
            sample_only_in_b = _values(cursor.fetchall())

    except ObjectNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="compare_rows",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "in_both": in_both,
        "null_keys_a": null_keys_a,
        "null_keys_b": null_keys_b,
        "sample_only_in_a": sample_only_in_a,
        "sample_only_in_b": sample_only_in_b,
        "duration_ms": duration_ms,
    }
