"""DDL helpers (CREATE / TRUNCATE / DROP) with ``sql_guard`` on controlled SQL."""

from __future__ import annotations

import re
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import validate_catalog_identifier, validate_database_identifier
from nz_mcp.catalog.tables import table_exists
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

# Netezza ``DISTRIBUTE ON`` / ``ORGANIZE ON`` are not parsed by sqlglot; we validate the
# ``CREATE TABLE (...)`` core with ``guard_validate``, then append fixed templates using
# only validated identifiers (see docs/architecture/security-model.md).
_TYPE_SAFE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\(\s*\d+(?:\s*,\s*\d+)?\s*\))?$",
)
_MAX_TYPE_LEN: Final[int] = 200
_MAX_CTAS_SELECT_SQL: Final[int] = 65536


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
                f"({db_sess}) for DDL operations."
            ),
        )


def _qualified_table(schema: str, table: str) -> str:
    return f"{validate_catalog_identifier(schema)}.{validate_catalog_identifier(table)}"


def _validate_column_type_fragment(raw: str) -> str:
    s = raw.strip().upper()
    if not s or len(s) > _MAX_TYPE_LEN:
        raise InvalidInputError(detail="Invalid or too long column type.")
    if not _TYPE_SAFE.fullmatch(s):
        raise InvalidInputError(detail=f"Invalid column type fragment: {raw!r}.")
    return s


def _format_default(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        if ";" in value:
            raise InvalidInputError(detail="Column default string cannot contain semicolons.")
        return "'" + value.replace("'", "''") + "'"
    raise InvalidInputError(detail="Column default must be a string, number, or boolean.")


def _build_distribution_clause(distribution: dict[str, Any] | None) -> str:
    if distribution is None:
        return "DISTRIBUTE ON RANDOM"
    dtype = str(distribution.get("type", "RANDOM")).upper()
    if dtype == "RANDOM":
        return "DISTRIBUTE ON RANDOM"
    if dtype != "HASH":
        raise InvalidInputError(detail="distribution.type must be HASH or RANDOM.")
    cols_raw = distribution.get("columns") or []
    if not isinstance(cols_raw, list) or not cols_raw:
        raise InvalidInputError(detail="distribution HASH requires a non-empty columns list.")
    cols = [validate_catalog_identifier(str(c)) for c in cols_raw]
    return f"DISTRIBUTE ON HASH ({', '.join(cols)})"


def _build_organize_clause(organized_on: list[str] | None) -> str:
    if not organized_on:
        return ""
    cols = [validate_catalog_identifier(str(c)) for c in organized_on]
    if len(cols) == 1:
        return f"ORGANIZE ON ({cols[0]})"
    return f"ORGANIZE ON ({', '.join(cols)})"


def _build_create_table_base_sql(
    *,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    if_not_exists: bool,
) -> str:
    if not columns:
        raise InvalidInputError(detail="columns must contain at least one column definition.")
    qual = _qualified_table(schema, table)
    lines: list[str] = []
    for col in columns:
        if not isinstance(col, dict):
            raise InvalidInputError(detail="Each column must be an object.")
        name_raw = col.get("name")
        type_raw = col.get("type")
        if name_raw is None or type_raw is None:
            raise InvalidInputError(detail="Each column requires name and type.")
        cname = validate_catalog_identifier(str(name_raw))
        ctype = _validate_column_type_fragment(str(type_raw))
        segment = f"{cname} {ctype}"
        if not bool(col.get("nullable", True)):
            segment += " NOT NULL"
        if col.get("default") is not None:
            segment += f" DEFAULT {_format_default(col.get('default'))}"
        lines.append(segment)
    inner = ",\n  ".join(lines)
    if_prefix = "IF NOT EXISTS " if if_not_exists else ""
    return f"CREATE TABLE {if_prefix}{qual} (\n  {inner}\n)"


def execute_create_table(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    *,
    distribution: dict[str, Any] | None,
    organized_on: list[str] | None,
    if_not_exists: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build Netezza ``CREATE TABLE`` DDL, validate the parseable core, optionally execute."""
    _ensure_session_database(profile, database)
    base_sql = _build_create_table_base_sql(
        schema=schema,
        table=table,
        columns=columns,
        if_not_exists=if_not_exists,
    )
    parsed = guard_validate(base_sql, mode="admin")
    if parsed.kind is not StatementKind.CREATE:
        raise NetezzaError(
            operation="execute_create_table",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    org_clause = _build_organize_clause(organized_on)
    dist_clause = _build_distribution_clause(distribution)
    pieces = [parsed.raw.rstrip()]
    if org_clause:
        pieces.append(org_clause)
    pieces.append(dist_clause)
    full_sql = "\n".join(pieces)

    if dry_run:
        return {
            "dry_run": True,
            "ddl_to_execute": full_sql,
            "executed": False,
            "duration_ms": 0,
        }

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(full_sql, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_create_table",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "dry_run": False,
        "ddl_to_execute": full_sql,
        "executed": True,
        "duration_ms": duration_ms,
    }


def _run_scalar_count(
    profile: Profile,
    password: str,
    sql: str,
    params: tuple[Any, ...],
    *,
    operation: str,
    database: str,
) -> int:
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation=operation,
            database=database,
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


def execute_create_table_as(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    select_sql: str,
    *,
    distribution: dict[str, Any] | None,
    organized_on: list[str] | None,
    dry_run: bool,
    confirm: bool,
    estimate_rows: bool = False,
) -> dict[str, Any]:
    """Build Netezza ``CREATE TABLE ... AS SELECT ...`` with validated identifiers-only tail."""
    _ensure_session_database(profile, database)
    if table_exists(profile, database, schema, table):
        raise InvalidInputError(
            detail=(
                f"Target table {schema}.{table} already exists; "
                "nz_create_table_as requires a name that is not in use."
            ),
        )

    sel = select_sql.strip()
    if not sel:
        raise InvalidInputError(detail="select_sql must be non-empty.")
    if len(sel) > _MAX_CTAS_SELECT_SQL:
        raise InvalidInputError(detail="select_sql exceeds maximum length.")

    parsed_sel = guard_validate(sel, mode="admin")
    if parsed_sel.kind is not StatementKind.SELECT:
        raise GuardRejectedError(
            code="WRONG_STATEMENT_FOR_TOOL",
            tool="nz_create_table_as",
            kind=str(parsed_sel.kind),
        )

    qual = _qualified_table(schema, table)
    core_sql = f"CREATE TABLE {qual} AS\n{sel}"
    parsed_core = guard_validate(core_sql, mode="admin")
    if parsed_core.kind is not StatementKind.CREATE:
        raise NetezzaError(
            operation="execute_create_table_as",
            detail=f"Unexpected statement kind after validation: {parsed_core.kind}",
        )

    org_clause = _build_organize_clause(organized_on)
    dist_clause = _build_distribution_clause(distribution)
    pieces: list[str] = [parsed_core.raw.rstrip()]
    if org_clause:
        pieces.append(org_clause)
    pieces.append(dist_clause)
    full_sql = "\n".join(pieces)

    if dry_run:
        duration_ms = 0
        would_rows: int | None = None
        if estimate_rows:
            count_sql = f"SELECT COUNT(*) AS C FROM ({sel}) AS nz_mcp_ctas_t"  # noqa: S608
            count_parsed = guard_validate(count_sql, mode="read")
            if count_parsed.kind is not StatementKind.SELECT:
                raise NetezzaError(
                    operation="execute_create_table_as",
                    detail=f"Unexpected statement kind for row estimate: {count_parsed.kind}",
                )
            password = get_password(profile.name)
            start = time.monotonic()
            would_rows = _run_scalar_count(
                profile,
                password,
                count_parsed.raw,
                (),
                operation="execute_create_table_as",
                database=database,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "dry_run": True,
            "ddl_to_execute": full_sql,
            "would_create_rows": would_rows,
            "executed": False,
            "duration_ms": duration_ms,
        }

    if confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_create_table_as.",
        )

    password = get_password(profile.name)
    start = time.monotonic()
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(full_sql, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_create_table_as",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "dry_run": False,
        "ddl_to_execute": full_sql,
        "would_create_rows": None,
        "executed": True,
        "duration_ms": duration_ms,
    }


def execute_truncate(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
) -> dict[str, Any]:
    """Execute ``TRUNCATE TABLE`` with ``sql_guard`` (admin)."""
    _ensure_session_database(profile, database)
    qual = _qualified_table(schema, table)
    sql = f"TRUNCATE TABLE {qual}"
    parsed = guard_validate(sql, mode="admin")
    if parsed.kind is not StatementKind.TRUNCATE:
        raise NetezzaError(
            operation="execute_truncate",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_truncate",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {"truncated": True, "duration_ms": duration_ms}


def execute_drop_table(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    *,
    if_exists: bool,
) -> dict[str, Any]:
    """Execute ``DROP TABLE`` with ``sql_guard`` (admin)."""
    _ensure_session_database(profile, database)
    qual = _qualified_table(schema, table)
    # Netezza NPS expects ``DROP TABLE name IF EXISTS``, not ``DROP TABLE IF EXISTS name``.
    sql = f"DROP TABLE {qual} IF EXISTS" if if_exists else f"DROP TABLE {qual}"
    parsed = guard_validate(sql, mode="admin")
    if parsed.kind is not StatementKind.DROP:
        raise NetezzaError(
            operation="execute_drop_table",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_drop_table",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return {"dropped": True}
