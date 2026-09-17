"""Column profiling: total rows, nulls, distinct count, min/max and top-N values."""

from __future__ import annotations

from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.execute import execute_select, inject_limit
from nz_mcp.catalog.identifier import render_cross_db, validate_catalog_identifier
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.catalog.tables import _ensure_profile_database
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import NetezzaError, ObjectNotFoundError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

TOP_N_DEFAULT: Final[int] = 10
TOP_N_CAP: Final[int] = 50
_NULL_PCT_DECIMALS: Final[int] = 2
_AGGREGATE_COLUMNS: Final[int] = 5


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[str, str]) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def profile_column(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    column: str,
    *,
    top_n: int,
    timeout_s: int,
) -> dict[str, Any]:
    """Profile one column with read-only aggregate and top-N queries.

    ``database`` must match the active profile database: the profile queries run as a
    real ``SELECT`` bound to the session database, same rule as ``nz_table_sample``.
    """
    _ensure_profile_database(profile, database)
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    column_u = validate_catalog_identifier(column)
    _ensure_column_exists(profile, database, schema_u, table_u, column_u)

    aggregates = _run_aggregates(profile, schema_u, table_u, column_u, timeout_s)
    top_values = _run_top_values(profile, schema_u, table_u, column_u, top_n, timeout_s)

    total = int(aggregates["total"])
    nulls = int(aggregates["nulls"])
    return {
        "total": total,
        "nulls": nulls,
        "null_pct": round(nulls * 100.0 / total, _NULL_PCT_DECIMALS) if total else 0.0,
        "distinct": int(aggregates["distinct"]),
        "min": _stringify(aggregates["min"]),
        "max": _stringify(aggregates["max"]),
        "top_values": top_values,
    }


def _ensure_column_exists(
    profile: Profile,
    database: str,
    schema_u: str,
    table_u: str,
    column_u: str,
) -> None:
    """Raise ``ObjectNotFoundError`` when the table or column is not visible."""
    password = get_password(profile.name)
    sql = render_cross_db(resolve_query("describe_table_columns", profile), database=database)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, (schema_u, table_u))
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="profile_column",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    if not rows:
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
    visible = {_column_name(row) for row in rows}
    if column_u not in visible:
        raise ObjectNotFoundError(
            detail=(
                f"Column {column_u!r} does not exist in {database}.{schema_u}.{table_u}. "
                f"Available: {', '.join(sorted(visible))}."
            ),
            object_type="column",
            database=database,
            schema=schema_u,
            table=table_u,
            column=column_u,
        )


def _column_name(row: Any) -> str:
    if isinstance(row, dict):
        name = row.get("COLUMN_NAME")
        if name is None:
            raise NetezzaError(
                operation="profile_column",
                detail="Column row must include COLUMN_NAME.",
            )
        return str(name).upper()
    if isinstance(row, (tuple, list)) and row:
        return str(row[0]).upper()
    raise NetezzaError(operation="profile_column", detail="Unexpected column row shape.")


def _run_aggregates(
    profile: Profile,
    schema_u: str,
    table_u: str,
    column_u: str,
    timeout_s: int,
) -> dict[str, Any]:
    sql = (
        f"SELECT COUNT(*) AS TOTAL, "  # noqa: S608 identifiers validated above
        f"SUM(CASE WHEN {column_u} IS NULL THEN 1 ELSE 0 END) AS NULL_CNT, "
        f"COUNT(DISTINCT {column_u}) AS DISTINCT_CNT, "
        f"MIN({column_u}) AS MIN_VAL, "
        f"MAX({column_u}) AS MAX_VAL "
        f"FROM {schema_u}.{table_u}"
    )
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="profile_column",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    raw = execute_select(profile, parsed.raw, max_rows=1, timeout_s=timeout_s)
    rows = raw["rows"]
    if not rows or len(rows[0]) < _AGGREGATE_COLUMNS:
        raise NetezzaError(
            operation="profile_column",
            detail="Aggregate query returned an unexpected row shape.",
        )
    cells = rows[0]
    return {
        "total": int(cells[0]),
        "nulls": 0 if cells[1] is None else int(cells[1]),
        "distinct": int(cells[2]),
        "min": cells[3],
        "max": cells[4],
    }


def _run_top_values(
    profile: Profile,
    schema_u: str,
    table_u: str,
    column_u: str,
    top_n: int,
    timeout_s: int,
) -> list[dict[str, Any]]:
    sql = (
        f"SELECT {column_u} AS VAL, COUNT(*) AS CNT "  # noqa: S608 identifiers validated above
        f"FROM {schema_u}.{table_u} "
        f"WHERE {column_u} IS NOT NULL "
        f"GROUP BY {column_u} ORDER BY CNT DESC, VAL ASC"
    )
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="profile_column",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    limited = inject_limit(parsed.raw, top_n)
    raw = execute_select(profile, limited, max_rows=top_n, timeout_s=timeout_s)
    return [{"value": _stringify(row[0]), "count": int(row[1])} for row in raw["rows"]]


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    return str(value)
