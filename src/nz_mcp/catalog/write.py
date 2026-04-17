"""Parameterized DML helpers (INSERT / UPDATE / DELETE) with ``sql_guard`` validation."""

from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import validate_catalog_identifier, validate_database_identifier
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

_MAX_INSERT_ROWS: Final[int] = 500


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def fetchone(self) -> Any: ...
    @property
    def rowcount(self) -> int: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _ensure_session_database(profile: Profile, database: str) -> None:
    db_arg = validate_database_identifier(database)
    db_sess = validate_database_identifier(profile.database)
    if db_arg != db_sess:
        raise InvalidInputError(
            detail=(
                "The database argument must match the active profile database "
                f"({db_sess}) for write operations."
            ),
        )


def _qualified_table(schema: str, table: str) -> str:
    return f"{validate_catalog_identifier(schema)}.{validate_catalog_identifier(table)}"


def _validate_column_name(name: str) -> str:
    return validate_catalog_identifier(name)


def _is_duplicate_row_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "duplicate" in msg or "unique" in msg or "23505" in msg


def execute_insert(  # noqa: PLR0912, PLR0915
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    rows: list[dict[str, Any]],
    *,
    on_conflict: str,
) -> dict[str, Any]:
    """Run ``INSERT`` with ``?`` placeholders; ``on_conflict`` is ``error`` or ``skip``."""
    _ensure_session_database(profile, database)
    if not rows:
        raise InvalidInputError(detail="rows must contain at least one object for nz_insert.")
    if len(rows) > _MAX_INSERT_ROWS:
        raise InvalidInputError(
            detail=f"Too many rows in one call (max {_MAX_INSERT_ROWS}).",
        )
    if on_conflict not in ("error", "skip"):
        raise InvalidInputError(detail="on_conflict must be 'error' or 'skip'.")

    first_keys = sorted(rows[0].keys())
    for i, row in enumerate(rows):
        keys = sorted(row.keys())
        if keys != first_keys:
            raise InvalidInputError(
                detail=f"Row {i} keys do not match the first row column set.",
            )

    cols = [_validate_column_name(k) for k in first_keys]
    qual = _qualified_table(schema, table)
    placeholders = "(" + ", ".join(["?"] * len(cols)) + ")"
    values_clause = ", ".join([placeholders] * len(rows))
    sql = f"INSERT INTO {qual} ({', '.join(cols)}) VALUES {values_clause}"  # noqa: S608

    flat_params: list[Any] = []
    for row in rows:
        for c in first_keys:
            flat_params.append(row[c])
    params_tuple = tuple(flat_params)

    parsed = guard_validate(sql, mode="write")
    if parsed.kind is not StatementKind.INSERT:
        raise NetezzaError(
            operation="execute_insert",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            if on_conflict == "error":
                cursor.execute(parsed.raw, params_tuple)
                inserted = len(rows)
            else:
                inserted = 0
                single_sql = f"INSERT INTO {qual} ({', '.join(cols)}) VALUES {placeholders}"  # noqa: S608
                single_parsed = guard_validate(single_sql, mode="write")
                for row in rows:
                    p = tuple(row[k] for k in first_keys)
                    try:
                        cursor.execute(single_parsed.raw, p)
                        inserted += 1
                    except Exception as exc:  # noqa: BLE001, RUF100
                        if _is_duplicate_row_error(exc):
                            continue
                        raise NetezzaError(
                            operation="execute_insert",
                            database=database,
                            detail=sanitize(str(exc), known_secrets={password}),
                        ) from exc
    except NetezzaError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_insert",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {"inserted": inserted, "duration_ms": duration_ms}


def execute_update(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    set_cols: dict[str, Any],
    where: str,
    *,
    dry_run: bool,
    confirm: bool,
) -> dict[str, Any]:
    """Run ``UPDATE`` with validation, optional dry-run ``COUNT`` first."""
    _ensure_session_database(profile, database)
    if not set_cols:
        raise InvalidInputError(detail="set must contain at least one column.")
    where_clause = where.strip()
    if not where_clause:
        raise InvalidInputError(detail="where must be a non-empty predicate.")

    qual = _qualified_table(schema, table)
    set_parts = [f"{_validate_column_name(k)} = ?" for k in sorted(set_cols.keys())]
    set_sql = ", ".join(set_parts)
    set_params = tuple(set_cols[k] for k in sorted(set_cols.keys()))

    update_sql = f"UPDATE {qual} SET {set_sql} WHERE {where_clause}"  # noqa: S608
    password = get_password(profile.name)

    if dry_run:
        count_sql = f"SELECT COUNT(*) AS C FROM {qual} WHERE {where_clause}"  # noqa: S608
        count_parsed = guard_validate(count_sql, mode="read")
        if count_parsed.kind is not StatementKind.SELECT:
            raise NetezzaError(
                operation="execute_update",
                detail=f"Unexpected statement kind for dry-run count: {count_parsed.kind}",
            )
        start = time.monotonic()
        n = _run_scalar_count(profile, password, count_parsed.raw, ())
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "updated": 0,
            "would_update": n,
            "dry_run": True,
            "confirm_required": True,
            "duration_ms": duration_ms,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_update.",
        )

    parsed = guard_validate(update_sql, mode="write")
    if parsed.kind is not StatementKind.UPDATE:
        raise NetezzaError(
            operation="execute_update",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )

    start = time.monotonic()
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, set_params)
            affected = cursor.rowcount if cursor.rowcount is not None else 0
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_update",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "updated": int(affected),
        "dry_run": False,
        "duration_ms": duration_ms,
    }


def execute_delete(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    where: str,
    *,
    dry_run: bool,
    confirm: bool,
) -> dict[str, Any]:
    """Run ``DELETE`` with validation, optional dry-run ``COUNT`` first."""
    _ensure_session_database(profile, database)
    where_clause = where.strip()
    if not where_clause:
        raise InvalidInputError(detail="where must be a non-empty predicate.")

    qual = _qualified_table(schema, table)
    delete_sql = f"DELETE FROM {qual} WHERE {where_clause}"  # noqa: S608
    password = get_password(profile.name)

    if dry_run:
        count_sql = f"SELECT COUNT(*) AS C FROM {qual} WHERE {where_clause}"  # noqa: S608
        count_parsed = guard_validate(count_sql, mode="read")
        if count_parsed.kind is not StatementKind.SELECT:
            raise NetezzaError(
                operation="execute_delete",
                detail=f"Unexpected statement kind for dry-run count: {count_parsed.kind}",
            )
        start = time.monotonic()
        n = _run_scalar_count(profile, password, count_parsed.raw, ())
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "deleted": 0,
            "would_delete": n,
            "dry_run": True,
            "confirm_required": True,
            "duration_ms": duration_ms,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_delete.",
        )

    parsed = guard_validate(delete_sql, mode="write")
    if parsed.kind is not StatementKind.DELETE:
        raise NetezzaError(
            operation="execute_delete",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )

    start = time.monotonic()
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
            affected = cursor.rowcount if cursor.rowcount is not None else 0
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_delete",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "deleted": int(affected),
        "dry_run": False,
        "duration_ms": duration_ms,
    }


def _run_scalar_count(
    profile: Profile,
    password: str,
    sql: str,
    params: tuple[Any, ...],
) -> int:
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_update",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    if row is None:
        return 0
    if isinstance(row, dict):
        v = next(iter(row.values()))
        return int(v)
    if isinstance(row, (tuple, list)) and len(row) >= 1:
        return int(row[0])
    return int(row)
