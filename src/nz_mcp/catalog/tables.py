"""Catalog queries for tables."""

from __future__ import annotations

from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import render_cross_db
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import NetezzaError
from nz_mcp.logging_utils import sanitize

_TABLE_ROW_MIN_ITEMS: Final[int] = 2
_TABLE_KIND: Final[str] = "TABLE"


class _CursorLike(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def list_tables(
    profile: Profile,
    database: str,
    schema: str,
    pattern: str | None = None,
) -> list[dict[str, str]]:
    """Return tables from ``_v_table`` for ``database`` and ``schema`` (cross-database notation)."""
    like_pattern = pattern if pattern else None
    params: tuple[str, str | None, str | None] = (schema, like_pattern, like_pattern)
    password = get_password(profile.name)
    base_sql = resolve_query("list_tables", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        # Catalog/driver failures are not guaranteed to use a stable exception type.
        raise NetezzaError(
            operation="list_tables",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return [_row_to_table(row) for row in rows]


def _row_to_table(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        name_key = "NAME" if "NAME" in row else None
        if name_key is None and "TABLENAME" in row:
            name_key = "TABLENAME"
        if name_key is None:
            raise NetezzaError(
                operation="list_tables",
                detail="Catalog query must return NAME (or TABLENAME) column.",
            )
        return {"name": str(row[name_key]), "kind": _TABLE_KIND}
    if isinstance(row, tuple) and len(row) >= _TABLE_ROW_MIN_ITEMS:
        return {"name": str(row[0]), "kind": _TABLE_KIND}
    raise NetezzaError(operation="list_tables", detail="Unexpected row shape from _v_table")
