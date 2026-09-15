"""Additive ``ALTER TABLE`` DDL (ADD COLUMN / SET|DROP DEFAULT / RENAME COLUMN), admin-only."""

from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.ddl import (
    _ensure_session_database,
    _format_default,
    _qualified_table,
    _validate_column_type_fragment,
)
from nz_mcp.catalog.identifier import validate_catalog_identifier
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _add_columns_statement(qual: str, add_columns: list[dict[str, Any]]) -> str | None:
    if not add_columns:
        return None
    segments: list[str] = []
    for col in add_columns:
        if not isinstance(col, dict):
            raise InvalidInputError(detail="Each column must be an object.")
        name_raw = col.get("name")
        type_raw = col.get("type")
        if name_raw is None or type_raw is None:
            raise InvalidInputError(detail="Each column requires name and type.")
        cname = validate_catalog_identifier(str(name_raw))
        ctype = _validate_column_type_fragment(str(type_raw))
        segment = f"ADD COLUMN {cname} {ctype}"
        if not bool(col.get("nullable", True)):
            segment += " NOT NULL"
        if col.get("default") is not None:
            segment += f" DEFAULT {_format_default(col.get('default'))}"
        segments.append(segment)
    return f"ALTER TABLE {qual} " + ", ".join(segments)


def _set_default_statements(qual: str, set_defaults: list[dict[str, Any]]) -> list[str]:
    statements: list[str] = []
    for entry in set_defaults:
        if not isinstance(entry, dict) or "column" not in entry or "default" not in entry:
            raise InvalidInputError(detail="Each set_defaults entry requires column and default.")
        column = validate_catalog_identifier(str(entry["column"]))
        value = _format_default(entry["default"])
        statements.append(f"ALTER TABLE {qual} ALTER COLUMN {column} SET DEFAULT {value}")
    return statements


def _drop_default_statements(qual: str, drop_defaults: list[str]) -> list[str]:
    return [
        f"ALTER TABLE {qual} ALTER COLUMN {validate_catalog_identifier(str(col))} DROP DEFAULT"
        for col in drop_defaults
    ]


def _rename_column_statements(qual: str, rename_columns: list[dict[str, Any]]) -> list[str]:
    statements: list[str] = []
    for entry in rename_columns:
        if not isinstance(entry, dict) or "from" not in entry or "to" not in entry:
            raise InvalidInputError(detail="Each rename_columns entry requires from and to.")
        old = validate_catalog_identifier(str(entry["from"]))
        new = validate_catalog_identifier(str(entry["to"]))
        statements.append(f"ALTER TABLE {qual} RENAME COLUMN {old} TO {new}")
    return statements


def _build_alter_statements(
    *,
    schema: str,
    table: str,
    add_columns: list[dict[str, Any]],
    set_defaults: list[dict[str, Any]],
    drop_defaults: list[str],
    rename_columns: list[dict[str, Any]],
) -> list[str]:
    if not (add_columns or set_defaults or drop_defaults or rename_columns):
        raise InvalidInputError(
            detail="At least one ALTER TABLE operation is required.",
        )
    qual = _qualified_table(schema, table)
    statements: list[str] = []
    add_stmt = _add_columns_statement(qual, add_columns)
    if add_stmt is not None:
        statements.append(add_stmt)
    statements.extend(_set_default_statements(qual, set_defaults))
    statements.extend(_drop_default_statements(qual, drop_defaults))
    statements.extend(_rename_column_statements(qual, rename_columns))
    return statements


def execute_alter_table(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    *,
    add_columns: list[dict[str, Any]],
    set_defaults: list[dict[str, Any]],
    drop_defaults: list[str],
    rename_columns: list[dict[str, Any]],
    dry_run: bool,
    confirm: bool,
) -> dict[str, Any]:
    """Build additive ``ALTER TABLE`` statements, validate each, optionally execute all."""
    _ensure_session_database(profile, database)
    built = _build_alter_statements(
        schema=schema,
        table=table,
        add_columns=add_columns,
        set_defaults=set_defaults,
        drop_defaults=drop_defaults,
        rename_columns=rename_columns,
    )

    statements: list[str] = []
    for stmt in built:
        parsed = guard_validate(stmt, mode="admin")
        if parsed.kind is not StatementKind.ALTER:
            raise NetezzaError(
                operation="execute_alter_table",
                detail=f"Unexpected statement kind after validation: {parsed.kind}",
            )
        assert_env_safe(parsed.raw, active_database=profile.database)
        statements.append(parsed.raw)

    if dry_run:
        return {
            "dry_run": True,
            "statements_to_execute": statements,
            "executed": False,
            "statements_executed": 0,
            "duration_ms": 0,
        }

    if confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_alter_table.",
        )

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            for stmt in statements:
                cursor.execute(stmt, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_alter_table",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "dry_run": False,
        "statements_to_execute": None,
        "executed": True,
        "statements_executed": len(statements),
        "duration_ms": duration_ms,
    }
