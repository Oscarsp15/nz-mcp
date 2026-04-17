"""Catalog queries for databases."""

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

_DATABASE_ROW_MIN_ITEMS: Final[int] = 2


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[str | None, str | None]) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def list_databases(profile: Profile, pattern: str | None = None) -> list[dict[str, str]]:
    """Return visible databases from ``_v_database`` for the active profile."""
    like_pattern = pattern if pattern else None
    params: tuple[str | None, str | None] = (like_pattern, like_pattern)
    password = get_password(profile.name)
    base_sql = resolve_query("list_databases", profile)
    sql = render_cross_db(base_sql, database=profile.database)

    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        # Catalog/driver failures are not guaranteed to use a stable exception type.
        raise NetezzaError(
            operation="list_databases",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return [_row_to_database(row) for row in rows]


def _row_to_database(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        if "DATABASE" not in row or "OWNER" not in row:
            raise NetezzaError(
                operation="list_databases",
                detail="Catalog query must return DATABASE and OWNER columns.",
            )
        return {"name": str(row["DATABASE"]), "owner": str(row["OWNER"])}
    if isinstance(row, tuple) and len(row) >= _DATABASE_ROW_MIN_ITEMS:
        return {"name": str(row[0]), "owner": str(row[1])}
    raise NetezzaError(operation="list_databases", detail="Unexpected row shape from _v_database")
