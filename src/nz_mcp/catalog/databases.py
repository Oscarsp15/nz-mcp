"""Catalog queries for databases."""

from __future__ import annotations

from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import NetezzaError

_LIST_DATABASES_SQL = (
    "SELECT DATABASE, OWNER FROM _v_database WHERE (? IS NULL OR DATABASE LIKE ?) ORDER BY DATABASE"
)
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

    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(_LIST_DATABASES_SQL, params)
            rows = cursor.fetchall()
    except Exception as exc:
        raise NetezzaError(
            operation="list_databases",
            database=profile.database,
            detail=str(exc),
        ) from exc
    finally:
        connection.close()

    return [_row_to_database(row) for row in rows]


def _row_to_database(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        return {
            "name": str(row["DATABASE"]),
            "owner": str(row["OWNER"]),
        }
    if isinstance(row, tuple) and len(row) >= _DATABASE_ROW_MIN_ITEMS:
        return {"name": str(row[0]), "owner": str(row[1])}
    raise NetezzaError(operation="list_databases", detail="Unexpected row shape from _v_database")
