"""Catalog queries for views."""

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

_VIEW_LIST_MIN_ITEMS: Final[int] = 2


class _ListCursor(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _DdlCursor(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str],
    ) -> None: ...

    def fetchone(self) -> Any: ...
    def close(self) -> None: ...


class _ConnectionForList(Protocol):
    def cursor(self) -> _ListCursor: ...
    def close(self) -> None: ...


class _ConnectionForDdl(Protocol):
    def cursor(self) -> _DdlCursor: ...
    def close(self) -> None: ...


def list_views(
    profile: Profile,
    database: str,
    schema: str,
    pattern: str | None = None,
) -> list[dict[str, str]]:
    """Return views from ``_v_view`` for ``database`` and ``schema`` (cross-database)."""
    like_pattern = pattern if pattern else None
    params: tuple[str, str | None, str | None] = (schema, like_pattern, like_pattern)
    password = get_password(profile.name)
    base_sql = resolve_query("list_views", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionForList, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="list_views",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return [_row_to_view_list_item(row) for row in rows]


def get_view_ddl(
    profile: Profile,
    database: str,
    schema: str,
    view: str,
) -> str:
    """Return the ``DEFINITION`` text for a view from ``_v_view``."""
    params: tuple[str, str] = (schema, view)
    password = get_password(profile.name)
    base_sql = resolve_query("get_view_ddl", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionForDdl, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="get_view_ddl",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    if row is None:
        raise NetezzaError(
            operation="get_view_ddl",
            database=database,
            detail="No view definition returned for the given schema and view name.",
        )
    return _row_to_definition(row)


def _row_to_view_list_item(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        name_key = "NAME" if "NAME" in row else None
        if name_key is None and "VIEWNAME" in row:
            name_key = "VIEWNAME"
        if name_key is None or "OWNER" not in row:
            raise NetezzaError(
                operation="list_views",
                detail="Catalog query must return NAME (or VIEWNAME) and OWNER columns.",
            )
        return {"name": str(row[name_key]), "owner": str(row["OWNER"])}
    if isinstance(row, tuple) and len(row) >= _VIEW_LIST_MIN_ITEMS:
        return {"name": str(row[0]), "owner": str(row[1])}
    raise NetezzaError(operation="list_views", detail="Unexpected row shape from _v_view")


def _row_to_definition(row: Any) -> str:
    if isinstance(row, dict):
        if "DEFINITION" not in row:
            raise NetezzaError(
                operation="get_view_ddl",
                detail="Catalog query must return a DEFINITION column.",
            )
        text = row["DEFINITION"]
        return "" if text is None else str(text)
    if isinstance(row, tuple) and len(row) >= 1:
        cell = row[0]
        return "" if cell is None else str(cell)
    raise NetezzaError(operation="get_view_ddl", detail="Unexpected row shape from _v_view")
