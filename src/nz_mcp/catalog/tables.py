"""Catalog queries for tables."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.ddl_builder import build_create_table_ddl
from nz_mcp.catalog.execute import execute_select, inject_limit
from nz_mcp.catalog.formatters import format_bytes_iec
from nz_mcp.catalog.identifier import (
    render_cross_db,
    validate_catalog_identifier,
    validate_database_identifier,
)
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError, ObjectNotFoundError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

_TABLE_ROW_MIN_ITEMS: Final[int] = 2
_TABLE_KIND: Final[str] = "TABLE"
_DIST_ROW_MIN: Final[int] = 2
_COL_TUPLE_MIN: Final[int] = 4
_PK_TUPLE_MIN: Final[int] = 3
_FK_PK_MIN: Final[int] = 4
_FK_SCHEMA_MIN: Final[int] = 5
_FK_REL_MIN: Final[int] = 6
_FK_ATT_MIN: Final[int] = 7
_STATS_ROW_MIN: Final[int] = 5


class _DescribeCursorLike(Protocol):
    def execute(self, sql: str, params: tuple[str, str]) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _DescribeConnectionLike(Protocol):
    def cursor(self) -> _DescribeCursorLike: ...
    def close(self) -> None: ...


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


def describe_table(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
) -> dict[str, Any]:
    """Return columns, distribution, PK, and FK metadata for one base table via catalog views."""
    params: tuple[str, str] = (schema, table)
    password = get_password(profile.name)
    connection = cast(_DescribeConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            col_sql = render_cross_db(
                resolve_query("describe_table_columns", profile),
                database=database,
            )
            cursor.execute(col_sql, params)
            column_rows = cursor.fetchall()
            if not column_rows:
                raise ObjectNotFoundError(
                    detail=(
                        "No columns returned for this table — table may not exist "
                        f"or may not be visible (database={database!r}, schema={schema!r}, "
                        f"table={table!r})."
                    ),
                )

            dist_sql = render_cross_db(
                resolve_query("describe_table_distribution", profile),
                database=database,
            )
            cursor.execute(dist_sql, params)
            dist_rows = cursor.fetchall()

            pk_sql = render_cross_db(
                resolve_query("describe_table_pk", profile),
                database=database,
            )
            cursor.execute(pk_sql, params)
            pk_rows = cursor.fetchall()

            fk_sql = render_cross_db(
                resolve_query("describe_table_fk", profile),
                database=database,
            )
            cursor.execute(fk_sql, params)
            fk_rows = cursor.fetchall()
    except ObjectNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="describe_table",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    dist = _distribution_from_rows(dist_rows)
    return {
        "name": table.upper(),
        "kind": _TABLE_KIND,
        "columns": [_column_descriptor(r) for r in column_rows],
        "distribution": dist,
        "organized_on": [],
        "primary_key": _primary_key_columns(pk_rows),
        "foreign_keys": _foreign_keys_payload(fk_rows),
    }


def _distribution_from_rows(rows: list[Any]) -> dict[str, Any]:
    if not rows:
        return {"type": "RANDOM", "columns": []}
    pairs: list[tuple[int, str]] = []
    for row in rows:
        attname, seq = _distribution_pair(row)
        pairs.append((seq, attname))
    pairs.sort(key=lambda p: p[0])
    return {"type": "HASH", "columns": [p[1] for p in pairs]}


def _distribution_pair(row: Any) -> tuple[str, int]:
    if isinstance(row, dict):
        att = row.get("ATTNAME")
        seq = row.get("DISTSEQNO")
        if att is None or seq is None:
            raise NetezzaError(
                operation="describe_table",
                detail="Distribution row must include ATTNAME and DISTSEQNO.",
            )
        return str(att), int(seq)
    if isinstance(row, tuple) and len(row) >= _DIST_ROW_MIN:
        return str(row[0]), int(row[1])
    raise NetezzaError(operation="describe_table", detail="Unexpected distribution row shape.")


def _column_descriptor(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        name = row.get("COLUMN_NAME")
        dtype = row.get("DATA_TYPE")
        not_null = row.get("NOT_NULL")
        default = row.get("DEFAULT_VALUE")
        if name is None or dtype is None or not_null is None:
            raise NetezzaError(
                operation="describe_table",
                detail="Column row must include COLUMN_NAME, DATA_TYPE, NOT_NULL.",
            )
        return {
            "name": str(name),
            "type": str(dtype),
            "nullable": not _is_not_null(not_null),
            "default": None if default is None else str(default),
        }
    if isinstance(row, tuple) and len(row) >= _COL_TUPLE_MIN:
        default_val = row[3]
        return {
            "name": str(row[0]),
            "type": str(row[1]),
            "nullable": not _is_not_null(row[2]),
            "default": None if default_val is None else str(default_val),
        }
    raise NetezzaError(operation="describe_table", detail="Unexpected column row shape.")


def _is_not_null(cell: Any) -> bool:
    if isinstance(cell, bool):
        return cell
    if isinstance(cell, (int, float)):
        return cell != 0
    lowered = str(cell).lower()
    return lowered in ("t", "true", "1", "yes")


def _primary_key_columns(rows: list[Any]) -> list[str]:
    if not rows:
        return []
    grouped: defaultdict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in rows:
        cname, attname, seq = _pk_triplet(row)
        grouped[cname].append((seq, attname))
    chosen = sorted(grouped.keys())[0]
    ordered = sorted(grouped[chosen], key=lambda p: p[0])
    return [p[1] for p in ordered]


def _pk_triplet(row: Any) -> tuple[str, str, int]:
    if isinstance(row, dict):
        c = row.get("CONSTRAINTNAME")
        a = row.get("ATTNAME")
        s = row.get("CONSEQ")
        if c is None or a is None or s is None:
            raise NetezzaError(
                operation="describe_table",
                detail="Primary key row must include CONSTRAINTNAME, ATTNAME, CONSEQ.",
            )
        return str(c), str(a), int(s)
    if isinstance(row, tuple) and len(row) >= _PK_TUPLE_MIN:
        return str(row[0]), str(row[1]), int(row[2])
    raise NetezzaError(operation="describe_table", detail="Unexpected primary key row shape.")


def _foreign_keys_payload(rows: list[Any]) -> list[dict[str, Any]]:
    if not rows:
        return []
    grouped: defaultdict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[_fk_constraint_name(row)].append(row)
    out: list[dict[str, Any]] = []
    for cname in sorted(grouped.keys()):
        group_rows = sorted(grouped[cname], key=_fk_conseq)
        first = group_rows[0]
        out.append(
            {
                "name": cname,
                "columns": [_fk_local_column(r) for r in group_rows],
                "references": {
                    "database": _fk_ref_database(first),
                    "schema": _fk_ref_schema(first),
                    "table": _fk_ref_table(first),
                    "columns": [_fk_ref_column(r) for r in group_rows],
                },
            }
        )
    return out


def _fk_constraint_name(row: Any) -> str:
    if isinstance(row, dict):
        v = row.get("CONSTRAINTNAME")
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing CONSTRAINTNAME.")
        return str(v)
    if isinstance(row, tuple) and len(row) >= 1:
        return str(row[0])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_conseq(row: Any) -> int:
    if isinstance(row, dict):
        s = row.get("CONSEQ")
        if s is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing CONSEQ.")
        return int(s)
    if isinstance(row, tuple) and len(row) >= _PK_TUPLE_MIN:
        return int(row[2])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_local_column(row: Any) -> str:
    if isinstance(row, dict):
        v = row.get("ATTNAME")
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing ATTNAME.")
        return str(v)
    if isinstance(row, tuple) and len(row) >= _DIST_ROW_MIN:
        return str(row[1])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_database(row: Any) -> str | None:
    key = "PKDATABASE"
    if isinstance(row, dict):
        val = row.get(key)
        return None if val is None else str(val)
    if isinstance(row, tuple) and len(row) >= _FK_PK_MIN:
        val = row[3]
        return None if val is None else str(val)
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_schema(row: Any) -> str:
    key = "PKSCHEMA"
    if isinstance(row, dict):
        v = row.get(key)
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing PKSCHEMA.")
        return str(v)
    if isinstance(row, tuple) and len(row) >= _FK_SCHEMA_MIN:
        return str(row[4])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_table(row: Any) -> str:
    key = "PKRELATION"
    if isinstance(row, dict):
        v = row.get(key)
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing PKRELATION.")
        return str(v)
    if isinstance(row, tuple) and len(row) >= _FK_REL_MIN:
        return str(row[5])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_column(row: Any) -> str:
    key = "PKATTNAME"
    if isinstance(row, dict):
        v = row.get(key)
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing PKATTNAME.")
        return str(v)
    if isinstance(row, tuple) and len(row) >= _FK_ATT_MIN:
        return str(row[6])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _ensure_profile_database(profile: Profile, database: str) -> None:
    """Direct ``SELECT`` runs in the session database; reject cross-database mismatch."""
    db_arg = validate_database_identifier(database)
    db_sess = validate_database_identifier(profile.database)
    if db_arg != db_sess:
        raise InvalidInputError(
            detail=(
                "The database argument must match the active profile database "
                f"({db_sess}) when sampling table rows."
            ),
        )


def get_table_sample(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    *,
    rows: int,
    timeout_s: int,
) -> dict[str, Any]:
    """Run a bounded ``SELECT *`` for sampling; SQL is validated via ``sql_guard``."""
    _ensure_profile_database(profile, database)
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    sql = f"SELECT * FROM {schema_u}.{table_u}"  # noqa: S608 identifiers validated above
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="get_table_sample",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    limited = inject_limit(parsed.raw, rows)
    return execute_select(
        profile,
        limited,
        max_rows=rows,
        timeout_s=timeout_s,
    )


def get_table_stats(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
) -> dict[str, Any]:
    """Return row estimate, storage bytes, skew, and creation time from catalog views."""
    params: tuple[str, str] = (
        validate_catalog_identifier(schema),
        validate_catalog_identifier(table),
    )
    password = get_password(profile.name)
    sql = render_cross_db(resolve_query("table_stats", profile), database=database)

    connection = cast(_DescribeConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            fetched = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="get_table_stats",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    if not fetched:
        raise ObjectNotFoundError(
            detail=(
                "No statistics row returned — table may not exist or may not be visible "
                f"(database={database!r}, schema={schema!r}, table={table!r})."
            ),
        )

    payload = _parse_table_stats_row(fetched[0])
    used = int(payload["size_bytes_used"])
    allocated = int(payload["size_bytes_allocated"])
    return {
        "row_count": int(payload["row_count"]),
        "size_bytes_used": used,
        "size_used_human": format_bytes_iec(used),
        "size_bytes_allocated": allocated,
        "size_allocated_human": format_bytes_iec(allocated),
        "skew": payload["skew"],
        "table_created": payload["table_created"],
    }


def _parse_table_stats_row(row: Any) -> dict[str, Any]:
    """Normalize driver row shapes for ``table_stats`` query aliases."""
    if isinstance(row, dict):

        def pick(*candidates: str) -> Any:
            keys = {str(k).upper(): v for k, v in row.items()}
            for c in candidates:
                if c.upper() in keys:
                    return keys[c.upper()]
            return None

        rc = pick("ROW_COUNT")
        used = pick("SIZE_BYTES_USED")
        alloc = pick("SIZE_BYTES_ALLOCATED")
        skew = pick("SKEW")
        created = pick("TABLE_CREATED")
    elif isinstance(row, tuple) and len(row) >= _STATS_ROW_MIN:
        rc, used, alloc, skew, created = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )
    else:
        raise NetezzaError(
            operation="get_table_stats",
            detail="Unexpected row shape from table_stats catalog query.",
        )

    skew_out: float | None = None if skew is None else float(skew)

    created_out: str | None
    if created is None:
        created_out = None
    else:
        iso = getattr(created, "isoformat", None)
        created_out = iso() if callable(iso) else str(created)

    return {
        "row_count": 0 if rc is None else int(rc),
        "size_bytes_used": 0 if used is None else int(used),
        "size_bytes_allocated": 0 if alloc is None else int(alloc),
        "skew": skew_out,
        "table_created": created_out,
    }


def get_table_ddl(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    *,
    include_constraints: bool,
) -> dict[str, Any]:
    """Rebuild CREATE TABLE DDL from catalog metadata (no ``SHOW TABLE``)."""
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    meta = describe_table(profile, database, schema_u, table_u)
    fq = f"{schema_u}.{table_u}"
    ddl = build_create_table_ddl(
        fq_name=fq,
        columns=list(meta["columns"]),
        distribution=dict(meta["distribution"]),
        primary_key=list(meta["primary_key"]),
        foreign_keys=list(meta["foreign_keys"]),
        include_constraints=include_constraints,
    )
    return {
        "ddl": ddl,
        "reconstructed": True,
        "notes": [],
    }
