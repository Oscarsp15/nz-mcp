"""Catalog queries for tables."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from typing import Any, Final, Literal, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.databases import list_databases
from nz_mcp.catalog.ddl_builder import build_create_table_ddl
from nz_mcp.catalog.execute import execute_select, inject_limit
from nz_mcp.catalog.formatters import format_bytes_iec, format_timestamp_iso
from nz_mcp.catalog.identifier import (
    render_cross_db,
    validate_catalog_identifier,
    validate_database_identifier,
    validate_system_view_identifier,
)
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.catalog.row_shape import is_sequence_row
from nz_mcp.config import MAX_ROWS_CAP, Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import (
    InputTooBroadError,
    InvalidInputError,
    NetezzaError,
    ObjectNotFoundError,
)
from nz_mcp.i18n import both
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

_TABLE_ROW_MIN_ITEMS: Final[int] = 3
_TABLE_KIND: Final[str] = "TABLE"
_EXTERNAL_TABLE_KIND: Final[str] = "EXTERNAL TABLE"
_VIEW_KIND: Final[str] = "VIEW"
# Every Netezza catalog/management view (``_V_*``) lives in this schema; the caller's
# ``schema`` argument is ignored for those names (issue #315).
_SYSTEM_VIEW_SCHEMA: Final[str] = "DEFINITION_SCHEMA"
_OBJECT_TYPES_WITH_DISTRIBUTION: Final[frozenset[str]] = frozenset(
    {_TABLE_KIND, _EXTERNAL_TABLE_KIND},
)
_DIST_ROW_MIN: Final[int] = 2
_COL_TUPLE_MIN: Final[int] = 4
_COL_WITH_ATTNUM_MIN: Final[int] = 5
_PK_TUPLE_MIN: Final[int] = 3
_FK_PK_MIN: Final[int] = 4
_FK_SCHEMA_MIN: Final[int] = 5
_FK_REL_MIN: Final[int] = 6
_FK_ATT_MIN: Final[int] = 7
_STATS_ROW_MIN: Final[int] = 5
_STATS_BATCH_ROW_MIN: Final[int] = 6

# Default top-N for nz_table_stats_batch; the tool caps it at MAX_ROWS_CAP.
TABLE_STATS_BATCH_TOP_N_DEFAULT: Final[int] = 20

# Rule-of-thumb skew bands (Netezza): document-only, not policy thresholds.
_SKEW_BALANCED_LT: Final[float] = 0.1
_SKEW_MODERATE_LE: Final[float] = 0.3

# Hard cap on the distinct values fetched by ``summarize_partitions`` (issue #338).
# A real partition/period column holds a handful of values; one with this many is
# not a partition column, so the summary is refused instead of streaming groups.
# Kept at ``MAX_ROWS_CAP`` so the per-row list stays well below the response byte cap.
PARTITION_SUMMARY_MAX_GROUPS: Final[int] = MAX_ROWS_CAP


def skew_class(skew: float | None) -> Literal["balanced", "moderate", "severe"] | None:
    """Classify storage skew: `<0.1` balanced, `≤0.3` moderate, else severe."""
    if skew is None:
        return None
    if skew < _SKEW_BALANCED_LT:
        return "balanced"
    if skew <= _SKEW_MODERATE_LE:
        return "moderate"
    return "severe"


class _DescribeCursorLike(Protocol):
    def execute(self, sql: str, params: tuple[str, ...]) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _DescribeConnectionLike(Protocol):
    def cursor(self) -> _DescribeCursorLike: ...
    def close(self) -> None: ...


class _CursorLike(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str | None, ...],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


class _FindColumnCursorLike(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None, str | None, str | None],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _FindColumnConnectionLike(Protocol):
    def cursor(self) -> _FindColumnCursorLike: ...
    def close(self) -> None: ...


def table_exists(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
) -> bool:
    """Return True if a base table name exists in ``schema`` (case-insensitive match)."""
    tab_ident = validate_catalog_identifier(table)
    want = tab_ident.upper()
    for entry in list_tables(profile, database, schema, pattern=None):
        if str(entry["name"]).upper() == want:
            return True
    return False


def list_tables(
    profile: Profile,
    database: str,
    schema: str,
    pattern: str | None = None,
    object_type: Literal["TABLE", "EXTERNAL TABLE", "ALL"] = "TABLE",
) -> list[dict[str, str]]:
    """Return tables from ``_v_table`` for ``database`` and ``schema`` (cross-database notation).

    ``object_type`` filters the catalog's ``OBJTYPE`` column: ``TABLE`` (default) lists only
    base tables, ``EXTERNAL TABLE`` lists only external tables, and ``ALL`` lists both.
    """
    like_pattern = pattern if pattern else None
    type_filter = None if object_type == "ALL" else object_type
    params: tuple[str, str | None, str | None, str | None, str | None] = (
        schema,
        type_filter,
        type_filter,
        like_pattern,
        like_pattern,
    )
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
        if name_key is None or "OBJTYPE" not in row:
            raise NetezzaError(
                operation="list_tables",
                detail="Catalog query must return NAME (or TABLENAME) and OBJTYPE columns.",
            )
        return {"name": str(row[name_key]), "kind": str(row["OBJTYPE"])}
    if is_sequence_row(row, _TABLE_ROW_MIN_ITEMS):
        return {"name": str(row[0]), "kind": str(row[2])}
    raise NetezzaError(operation="list_tables", detail="Unexpected row shape from _v_table")


def _is_system_view_name(name: str) -> bool:
    """True for Netezza catalog/management view names (``_V_*``)."""
    return name.strip().startswith("_")


def describe_table(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
) -> dict[str, Any]:
    """Return columns, kind, PK, and FK metadata for one relation via catalog views.

    ``kind`` is the real object type (``TABLE``, ``EXTERNAL TABLE``, or ``VIEW``); the
    ``distribution`` key is only present for tables and external tables, since Netezza
    views have no distribution.

    A ``_V_*`` name is a Netezza catalog/management view: it is resolved in
    ``DEFINITION_SCHEMA`` and the caller's ``schema`` argument is ignored (issue #315).
    """
    db_ident = validate_database_identifier(database)
    if _is_system_view_name(table):
        sch_ident = validate_catalog_identifier(_SYSTEM_VIEW_SCHEMA)
        tab_ident = validate_system_view_identifier(table)
    else:
        sch_ident = validate_catalog_identifier(schema)
        tab_ident = validate_catalog_identifier(table)
    params: tuple[str, str] = (sch_ident, tab_ident)
    dist_params: tuple[str, str, str] = (db_ident, sch_ident, tab_ident)
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
                        f"Table {table!r} does not exist in {database}.{sch_ident} "
                        "or is not visible to this profile."
                    ),
                    object_type="table",
                    database=database,
                    schema=sch_ident,
                    table=tab_ident,
                )

            objtype_sql = render_cross_db(
                resolve_query("describe_table_objtype", profile),
                database=database,
            )
            cursor.execute(objtype_sql, params)
            kind = _resolve_kind(cursor.fetchall())

            if kind in _OBJECT_TYPES_WITH_DISTRIBUTION:
                dist_sql = render_cross_db(
                    resolve_query("describe_table_distribution", profile),
                    database=database,
                )
                cursor.execute(dist_sql, dist_params)
                dist_rows = cursor.fetchall()
            else:
                dist_rows = []

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

    result: dict[str, Any] = {
        "name": tab_ident,
        "kind": kind,
        "columns": [_column_descriptor(r) for r in column_rows],
        "organized_on": [],
        "primary_key": _primary_key_columns(pk_rows),
        "foreign_keys": _foreign_keys_payload(fk_rows),
    }
    if kind in _OBJECT_TYPES_WITH_DISTRIBUTION:
        result["distribution"] = _distribution_from_rows(dist_rows)
    return result


def _resolve_kind(objtype_rows: list[Any]) -> str:
    """Map the ``describe_table_objtype`` result to a real object kind.

    No row means the relation is not in ``_V_TABLE``, i.e. it is a view.
    """
    if not objtype_rows:
        return _VIEW_KIND
    row = objtype_rows[0]
    if isinstance(row, dict):
        value = row.get("OBJTYPE")
        if value is None:
            raise NetezzaError(operation="describe_table", detail="OBJTYPE row missing OBJTYPE.")
        return str(value)
    if is_sequence_row(row, 1):
        return str(row[0])
    raise NetezzaError(operation="describe_table", detail="Unexpected OBJTYPE row shape.")


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
    if is_sequence_row(row, _DIST_ROW_MIN):
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
    if is_sequence_row(row, _COL_TUPLE_MIN):
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
    if is_sequence_row(row, _PK_TUPLE_MIN):
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
    if is_sequence_row(row, 1):
        return str(row[0])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_conseq(row: Any) -> int:
    if isinstance(row, dict):
        s = row.get("CONSEQ")
        if s is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing CONSEQ.")
        return int(s)
    if is_sequence_row(row, _PK_TUPLE_MIN):
        return int(row[2])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_local_column(row: Any) -> str:
    if isinstance(row, dict):
        v = row.get("ATTNAME")
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing ATTNAME.")
        return str(v)
    if is_sequence_row(row, _DIST_ROW_MIN):
        return str(row[1])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_database(row: Any) -> str | None:
    key = "PKDATABASE"
    if isinstance(row, dict):
        val = row.get(key)
        return None if val is None else str(val)
    if is_sequence_row(row, _FK_PK_MIN):
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
    if is_sequence_row(row, _FK_SCHEMA_MIN):
        return str(row[4])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_table(row: Any) -> str:
    key = "PKRELATION"
    if isinstance(row, dict):
        v = row.get(key)
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing PKRELATION.")
        return str(v)
    if is_sequence_row(row, _FK_REL_MIN):
        return str(row[5])
    raise NetezzaError(operation="describe_table", detail="Unexpected FK row shape.")


def _fk_ref_column(row: Any) -> str:
    key = "PKATTNAME"
    if isinstance(row, dict):
        v = row.get(key)
        if v is None:
            raise NetezzaError(operation="describe_table", detail="FK row missing PKATTNAME.")
        return str(v)
    if is_sequence_row(row, _FK_ATT_MIN):
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
    where: str | None = None,
    order_by: str | None = None,
) -> dict[str, Any]:
    """Run a bounded ``SELECT *`` for sampling; SQL is validated via ``sql_guard``.

    ``where`` and ``order_by`` are raw SQL fragments, not identifiers: the composed
    statement is classified read-only by ``sql_guard`` before execution, which rejects
    stacked statements, non-``SELECT`` kinds and mutation CTEs. The table name stays a
    validated identifier and ``database`` must match the active profile database.
    """
    _ensure_profile_database(profile, database)
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    sql = f"SELECT * FROM {schema_u}.{table_u}"  # noqa: S608 identifiers validated above
    if where is not None:
        sql = f"{sql} WHERE {where}"
    if order_by is not None:
        sql = f"{sql} ORDER BY {order_by}"
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


def _partition_value(cell: Any) -> str | None:
    """Render a partition key as text, keeping a SQL NULL as ``None``."""
    return None if cell is None else str(cell)


def summarize_partitions(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    partition_column: str,
    *,
    timeout_s: int,
) -> dict[str, Any]:
    """Return one entry per distinct ``partition_column`` value, newest first.

    A column name cannot be bound as a parameter, so the SQL is built from
    identifiers validated by :func:`validate_catalog_identifier` and passed through
    ``sql_guard`` before it reaches the driver.

    The distinct values are fetched with a hard cap (:data:`PARTITION_SUMMARY_MAX_GROUPS`).
    Hitting it means the column has at least that many values, i.e. it is not a
    partition/period column: the call is refused with ``INPUT_TOO_BROAD`` rather
    than returning a partial summary that an analyst could mistake for the truth.

    Ordering is ``DESC`` on the column, so the first entry is the newest partition
    and the last one the oldest. ``max_rows`` is applied by the tool layer.
    """
    _ensure_profile_database(profile, database)
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    column_u = validate_catalog_identifier(partition_column)
    sql = (
        f"SELECT {column_u} AS PARTITION_VALUE, COUNT(*) AS PARTITION_ROWS "  # noqa: S608
        f"FROM {schema_u}.{table_u} "
        f"GROUP BY {column_u} ORDER BY {column_u} DESC"
    )
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="summarize_partitions",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )

    raw = execute_select(
        profile,
        parsed.raw,
        max_rows=PARTITION_SUMMARY_MAX_GROUPS,
        timeout_s=timeout_s,
    )
    if raw["truncated"]:
        hints = both(
            "HINT.PARTITION_COLUMN_TOO_MANY_VALUES",
            column=column_u,
            cap=PARTITION_SUMMARY_MAX_GROUPS,
        )
        raise InputTooBroadError(
            scanned=PARTITION_SUMMARY_MAX_GROUPS,
            cap=PARTITION_SUMMARY_MAX_GROUPS,
            column=column_u,
            hint_es=hints["es"],
            hint_en=hints["en"],
        )

    partitions = [
        {"value": _partition_value(cell[0]), "rows": int(cell[1])} for cell in raw["rows"]
    ]
    return {
        "partitions": partitions,
        "partition_count": len(partitions),
        "latest": partitions[0]["value"] if partitions else None,
        "earliest": partitions[-1]["value"] if partitions else None,
        "duration_ms": int(raw["duration_ms"]),
    }


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
                f"Table {table!r} does not exist in {database}.{schema} "
                "or is not visible to this profile."
            ),
            object_type="table",
            database=database,
            schema=schema,
            table=table,
        )

    payload = _parse_table_stats_row(fetched[0])
    used = int(payload["size_bytes_used"])
    allocated = int(payload["size_bytes_allocated"])
    sk = payload["skew"]
    return {
        "row_count": int(payload["row_count"]),
        "size_bytes_used": used,
        "size_used_human": format_bytes_iec(used),
        "size_bytes_allocated": allocated,
        "size_allocated_human": format_bytes_iec(allocated),
        "skew": sk,
        "skew_class": skew_class(sk),
        "stats_last_analyzed": payload.get("stats_last_analyzed"),
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
    elif is_sequence_row(row, _STATS_ROW_MIN):
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

    # NPS 11.x _V_STATISTIC has no LASTUPDATETIMESTAMP; do not surface a fake timestamp.
    return {**_normalize_stats_metrics(rc, used, alloc, skew, created), "stats_last_analyzed": None}


def _normalize_stats_metrics(
    rc: Any,
    used: Any,
    alloc: Any,
    skew: Any,
    created: Any,
) -> dict[str, Any]:
    """Normalize the scalar metrics shared by single-table and batch stats rows.

    ``stats_last_analyzed`` is deliberately not included: NPS 11.x has no stable
    timestamp in ``_V_STATISTIC``, so only the single-table tool surfaces that key.
    """
    skew_out: float | None = None if skew is None else float(skew)

    return {
        "row_count": 0 if rc is None else int(rc),
        "size_bytes_used": 0 if used is None else int(used),
        "size_bytes_allocated": 0 if alloc is None else int(alloc),
        "skew": skew_out,
        "table_created": format_timestamp_iso(created),
    }


def get_table_stats_batch(
    profile: Profile,
    database: str,
    schema: str,
    order_by: Literal["size", "rows"],
) -> list[dict[str, Any]]:
    """Return storage metrics for every table in ``schema``, ranked by size or rows.

    The SQL only filters by schema and orders by name; ranking and the top-N cut happen
    in the caller, so ``top_n`` never becomes dynamic SQL. A schema with no visible
    tables yields an empty list, matching the other ``nz_list_*`` tools.
    """
    schema_ident = validate_catalog_identifier(schema)
    password = get_password(profile.name)
    sql = render_cross_db(resolve_query("table_stats_batch", profile), database=database)

    connection = cast(_DescribeConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, (schema_ident,))
            fetched = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="get_table_stats_batch",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    rows = [_parse_table_stats_batch_row(row) for row in fetched]
    for row in rows:
        used = int(row["size_bytes_used"])
        allocated = int(row["size_bytes_allocated"])
        row["size_used_human"] = format_bytes_iec(used)
        row["size_allocated_human"] = format_bytes_iec(allocated)
        row["skew_class"] = skew_class(row["skew"])

    sort_key = "size_bytes_used" if order_by == "size" else "row_count"
    rows.sort(key=lambda r: (-int(r[sort_key]), str(r["name"]).upper()))
    return rows


def _parse_table_stats_batch_row(row: Any) -> dict[str, Any]:
    """Normalize driver row shapes for the ``table_stats_batch`` query aliases."""
    if isinstance(row, dict):
        keys = {str(k).upper(): v for k, v in row.items()}
        name = keys.get("TABLE_NAME")
        rc = keys.get("ROW_COUNT")
        used = keys.get("SIZE_BYTES_USED")
        alloc = keys.get("SIZE_BYTES_ALLOCATED")
        skew = keys.get("SKEW")
        created = keys.get("TABLE_CREATED")
        if name is None:
            raise NetezzaError(
                operation="get_table_stats_batch",
                detail="Column row must include TABLE_NAME.",
            )
    elif is_sequence_row(row, _STATS_BATCH_ROW_MIN):
        name, rc, used, alloc, skew, created = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
        )
    else:
        raise NetezzaError(
            operation="get_table_stats_batch",
            detail="Unexpected row shape from table_stats_batch catalog query.",
        )

    return {
        "name": str(name),
        **_normalize_stats_metrics(rc, used, alloc, skew, created),
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


_COLUMN_MATCH_MIN_ITEMS: Final[int] = 4


def find_columns(
    profile: Profile,
    database: str,
    column_pattern: str,
    schema_pattern: str | None = None,
    table_pattern: str | None = None,
) -> list[dict[str, str]]:
    """Return columns matching ``column_pattern`` across tables and views in ``database``.

    Queries ``_v_relation_column`` restricted to ``TYPE IN ('TABLE', 'VIEW')``, excluding
    system/management views and external tables/sequences that also expose columns there.
    """
    schema_like = schema_pattern if schema_pattern else None
    table_like = table_pattern if table_pattern else None
    params: tuple[str, str | None, str | None, str | None, str | None] = (
        column_pattern,
        schema_like,
        schema_like,
        table_like,
        table_like,
    )
    password = get_password(profile.name)
    base_sql = resolve_query("find_column", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_FindColumnConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        # Catalog/driver failures are not guaranteed to use a stable exception type.
        raise NetezzaError(
            operation="find_column",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return [_row_to_column_match(row) for row in rows]


def _row_to_column_match(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        keys = {str(k).upper(): v for k, v in row.items()}
        required = ("SCHEMA", "NAME", "ATTNAME", "FORMAT_TYPE")
        if not all(k in keys for k in required):
            raise NetezzaError(
                operation="find_column",
                detail="Catalog query must return SCHEMA, NAME, ATTNAME, FORMAT_TYPE columns.",
            )
        return {
            "schema": str(keys["SCHEMA"]),
            "table": str(keys["NAME"]),
            "column": str(keys["ATTNAME"]),
            "type": str(keys["FORMAT_TYPE"]),
        }
    if is_sequence_row(row, _COLUMN_MATCH_MIN_ITEMS):
        return {
            "schema": str(row[0]),
            "table": str(row[1]),
            "column": str(row[2]),
            "type": str(row[3]),
        }
    raise NetezzaError(
        operation="find_column", detail="Unexpected row shape from _v_relation_column"
    )


class _FindTableCursorLike(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None, str, str | None, str | None, str, str, str],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _FindTableConnectionLike(Protocol):
    def cursor(self) -> _FindTableCursorLike: ...
    def close(self) -> None: ...


_TABLE_MATCH_MIN_ITEMS: Final[int] = 3

#: ``LIKE`` wildcards. A pattern made only of these matches every object in every database:
#: the shape that turned a cross-database search into a full catalog sweep (issue #361).
_LIKE_WILDCARDS: Final[frozenset[str]] = frozenset({"%", "_"})


def _narrows_anything(table_pattern: str) -> bool:
    """Whether a ``LIKE`` pattern holds at least one literal character."""
    return any(char not in _LIKE_WILDCARDS for char in table_pattern)


def _ensure_pattern_narrows(database: str | None, table_pattern: str) -> None:
    """Refuse a cross-database sweep whose pattern matches everything (issue #361).

    A pattern made only of wildcards matches every object of every visible database, so the
    call is not a search: it is a sweep whose result nobody asked for. It is refused before
    anything else runs, so the caller pays nothing — not even the connection that listing
    the databases would open.

    A named ``database`` is never refused — it bounds the sweep to one — and neither is a
    pattern with a literal character, however wide the visible universe is: that is a real
    search and it keeps working exactly as it did. Capping the number of databases was
    considered and rejected: measured live, the SaaS environment has 62 visible databases,
    so any cap low enough to bound the cost would have refused the specific-pattern search
    this fix exists to preserve.
    """
    if database is not None or _narrows_anything(table_pattern):
        return
    hints = both("HINT.INPUT_TOO_BROAD.PATTERN_MATCHES_EVERYTHING", pattern=table_pattern)
    raise InputTooBroadError(
        pattern=table_pattern,
        hint_es=hints["es"],
        hint_en=hints["en"],
    )


def find_tables(
    profile: Profile,
    *,
    table_pattern: str,
    database: str | None,
    schema_pattern: str | None,
    object_type: str,
    max_rows: int,
) -> tuple[list[dict[str, str]], bool]:
    """Search base tables and views by name across the visible databases.

    Returns ``(matches, truncated)``: at most ``max_rows`` matches plus a flag that says at
    least one more exists. Databases are scanned in ``nz_list_databases`` order and the scan
    stops as soon as one extra match is found, so a rare pattern does not read the whole
    catalog of every database.

    Without a ``database`` the call is refused by :func:`_ensure_pattern_narrows` when the
    pattern narrows nothing, before anything is opened (issue #361); a pattern with a
    literal character is a real search and scans every visible database as before.
    """
    schema_like = schema_pattern if schema_pattern else None
    _ensure_pattern_narrows(database, table_pattern)
    targets = _target_databases(profile, database)
    params = (
        table_pattern,
        schema_like,
        schema_like,
        table_pattern,
        schema_like,
        schema_like,
        object_type,
        object_type,
        object_type,
    )
    base_sql = resolve_query("find_table", profile)
    password = get_password(profile.name)
    matches: list[dict[str, str]] = []
    truncated = False
    connection = cast(_FindTableConnectionLike, open_connection(profile, password))
    try:
        for db_name in targets:
            sql = render_cross_db(base_sql, database=db_name)
            with closing(connection.cursor()) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            for row in rows:
                matches.append(_row_to_table_match(db_name, row))
                if len(matches) > max_rows:
                    truncated = True
                    break
            if truncated:
                break
    except NetezzaError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="find_table",
            database=database or profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()
    return matches, truncated


def _target_databases(profile: Profile, database: str | None) -> list[str]:
    """Return the databases to scan: all visible ones, or the single requested database."""
    visible = [str(entry["name"]) for entry in list_databases(profile)]
    if database is None:
        return visible
    db_ident = validate_database_identifier(database)
    if db_ident not in {name.upper() for name in visible}:
        raise ObjectNotFoundError(
            detail=(
                f"Database {db_ident!r} is not visible to profile {profile.name!r}. "
                f"Available: {', '.join(sorted(visible))}."
            ),
            database=db_ident,
            available=sorted(visible),
        )
    return [db_ident]


def _row_to_table_match(database: str, row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        keys = {str(k).upper(): v for k, v in row.items()}
        required = ("SCHEMA", "NAME", "KIND")
        if not all(k in keys for k in required):
            raise NetezzaError(
                operation="find_table",
                detail="Catalog query must return SCHEMA, NAME, KIND columns.",
            )
        return {
            "database": database,
            "schema": str(keys["SCHEMA"]),
            "name": str(keys["NAME"]),
            "kind": str(keys["KIND"]),
        }
    if is_sequence_row(row, _TABLE_MATCH_MIN_ITEMS):
        return {
            "database": database,
            "schema": str(row[0]),
            "name": str(row[1]),
            "kind": str(row[2]),
        }
    raise NetezzaError(operation="find_table", detail="Unexpected row shape from _v_table/_v_view")


_CONSTRAINT_ROW_MIN_ITEMS: Final[int] = 5


def list_constraints(
    profile: Profile,
    database: str,
    schema: str,
    table: str | None = None,
) -> list[dict[str, Any]]:
    """Return PK/FK/unique constraints for ``schema``, or one ``table`` when given.

    Queries ``_v_relation_keydata`` restricted to ``CONTYPE IN ('p', 'f', 'u')`` and groups
    rows by ``(RELATION, CONSTRAINTNAME)``, ordering each constraint's columns by ``CONSEQ``.
    When ``table`` is given and does not resolve to a real table in ``_v_table``, raises
    ``ObjectNotFoundError`` instead of silently returning an empty list (a real table with
    zero constraints must stay distinguishable from a typo in ``table``).
    """
    sch_ident = validate_catalog_identifier(schema)
    tab_ident = validate_catalog_identifier(table) if table else None
    params: tuple[str, str | None, str | None] = (sch_ident, tab_ident, tab_ident)
    password = get_password(profile.name)
    base_sql = resolve_query("list_constraints", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            if tab_ident is not None:
                exists_sql = render_cross_db(
                    resolve_query("describe_table_objtype", profile), database=database
                )
                cursor.execute(exists_sql, (sch_ident, tab_ident))
                if not cursor.fetchall():
                    raise ObjectNotFoundError(
                        detail=(
                            f"Table {table!r} does not exist in {database}.{schema} "
                            "or is not visible to this profile."
                        ),
                        object_type="table",
                        database=database,
                        schema=schema,
                        table=table,
                    )
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except ObjectNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        # Catalog/driver failures are not guaranteed to use a stable exception type.
        raise NetezzaError(
            operation="list_constraints",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return _group_constraints(rows)


def _group_constraints(rows: list[Any]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in rows:
        relation, cname, ctype, attname, conseq = _constraint_quintuplet(row)
        grouped[(relation, cname, ctype)].append((conseq, attname))
    out: list[dict[str, Any]] = []
    for relation, cname, ctype in sorted(grouped.keys()):
        ordered = sorted(grouped[(relation, cname, ctype)], key=lambda p: p[0])
        out.append(
            {
                "table": relation,
                "name": cname,
                "type": ctype,
                "columns": [attname for _, attname in ordered],
            }
        )
    return out


def _constraint_quintuplet(row: Any) -> tuple[str, str, str, str, int]:
    if isinstance(row, dict):
        keys = {str(k).upper(): v for k, v in row.items()}
        required = ("RELATION", "CONSTRAINTNAME", "CONTYPE", "ATTNAME", "CONSEQ")
        if not all(k in keys for k in required):
            raise NetezzaError(
                operation="list_constraints",
                detail=(
                    "Catalog query must return RELATION, CONSTRAINTNAME, CONTYPE, "
                    "ATTNAME, CONSEQ columns."
                ),
            )
        return (
            str(keys["RELATION"]),
            str(keys["CONSTRAINTNAME"]),
            str(keys["CONTYPE"]),
            str(keys["ATTNAME"]),
            int(keys["CONSEQ"]),
        )
    if is_sequence_row(row, _CONSTRAINT_ROW_MIN_ITEMS):
        return (str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]))
    raise NetezzaError(
        operation="list_constraints", detail="Unexpected row shape from _v_relation_keydata"
    )


def compare_tables(
    profile: Profile,
    database_a: str,
    schema_a: str,
    table_a: str,
    database_b: str,
    schema_b: str,
    table_b: str,
) -> dict[str, Any]:
    """Compare column schemas between two tables/views in Netezza.

    Returns columns only in A, only in B, type/nullability mismatches, and ordinal
    position mismatches. Raises ObjectNotFoundError if either relation does not exist.
    """
    db_a_ident = validate_database_identifier(database_a)
    sch_a_ident = validate_catalog_identifier(schema_a)
    tab_a_ident = validate_catalog_identifier(table_a)
    db_b_ident = validate_database_identifier(database_b)
    sch_b_ident = validate_catalog_identifier(schema_b)
    tab_b_ident = validate_catalog_identifier(table_b)

    params_a: tuple[str, str] = (sch_a_ident, tab_a_ident)
    params_b: tuple[str, str] = (sch_b_ident, tab_b_ident)

    password = get_password(profile.name)
    connection = cast(_DescribeConnectionLike, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            col_sql_a = render_cross_db(
                resolve_query("describe_table_columns", profile),
                database=db_a_ident,
            )
            cursor.execute(col_sql_a, params_a)
            column_rows_a = cursor.fetchall()
            if not column_rows_a:
                raise ObjectNotFoundError(
                    detail=(
                        f"Table {table_a!r} does not exist in {database_a}.{schema_a} "
                        "or is not visible to this profile."
                    ),
                    object_type="table",
                    database=database_a,
                    schema=schema_a,
                    table=table_a,
                )

            col_sql_b = render_cross_db(
                resolve_query("describe_table_columns", profile),
                database=db_b_ident,
            )
            cursor.execute(col_sql_b, params_b)
            column_rows_b = cursor.fetchall()
            if not column_rows_b:
                raise ObjectNotFoundError(
                    detail=(
                        f"Table {table_b!r} does not exist in {database_b}.{schema_b} "
                        "or is not visible to this profile."
                    ),
                    object_type="table",
                    database=database_b,
                    schema=schema_b,
                    table=table_b,
                )
    except ObjectNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="compare_tables",
            database=database_a,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    cols_a = [_compare_column_descriptor(r, i + 1) for i, r in enumerate(column_rows_a)]
    cols_b = [_compare_column_descriptor(r, i + 1) for i, r in enumerate(column_rows_b)]

    map_a: dict[str, dict[str, Any]] = {col["name"].upper(): col for col in cols_a}
    map_b: dict[str, dict[str, Any]] = {col["name"].upper(): col for col in cols_b}

    only_in_a: list[dict[str, Any]] = [
        {
            "column": col["name"],
            "type": col["type"],
            "nullable": col["nullable"],
            "position": col["position"],
        }
        for col in cols_a
        if col["name"].upper() not in map_b
    ]

    only_in_b: list[dict[str, Any]] = [
        {
            "column": col["name"],
            "type": col["type"],
            "nullable": col["nullable"],
            "position": col["position"],
        }
        for col in cols_b
        if col["name"].upper() not in map_a
    ]

    type_mismatches: list[dict[str, Any]] = []
    position_mismatches: list[dict[str, Any]] = []

    for col_a in cols_a:
        key = col_a["name"].upper()
        if key in map_b:
            col_b = map_b[key]
            if col_a["type"] != col_b["type"] or col_a["nullable"] != col_b["nullable"]:
                type_mismatches.append(
                    {
                        "column": col_a["name"],
                        "type_a": col_a["type"],
                        "type_b": col_b["type"],
                        "nullable_a": col_a["nullable"],
                        "nullable_b": col_b["nullable"],
                    }
                )
            if col_a["position"] != col_b["position"]:
                position_mismatches.append(
                    {
                        "column": col_a["name"],
                        "position_a": col_a["position"],
                        "position_b": col_b["position"],
                    }
                )

    common_count = len(set(map_a.keys()) & set(map_b.keys()))
    identical = (
        len(only_in_a) == 0
        and len(only_in_b) == 0
        and len(type_mismatches) == 0
        and len(position_mismatches) == 0
    )

    return {
        "identical": identical,
        "columns_in_a": len(cols_a),
        "columns_in_b": len(cols_b),
        "columns_in_common": common_count,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "type_mismatches": type_mismatches,
        "position_mismatches": position_mismatches,
    }


def _compare_column_descriptor(row: Any, fallback_pos: int) -> dict[str, Any]:
    if isinstance(row, dict):
        name = row.get("COLUMN_NAME")
        dtype = row.get("DATA_TYPE")
        not_null = row.get("NOT_NULL")
        attnum = row.get("ATTNUM")
        if name is None or dtype is None or not_null is None:
            raise NetezzaError(
                operation="compare_tables",
                detail="Column row must include COLUMN_NAME, DATA_TYPE, NOT_NULL.",
            )
        pos = int(attnum) if attnum is not None else fallback_pos
        return {
            "name": str(name),
            "type": str(dtype),
            "nullable": not _is_not_null(not_null),
            "position": pos,
        }
    if is_sequence_row(row, _COL_TUPLE_MIN):
        pos = (
            int(row[4]) if len(row) >= _COL_WITH_ATTNUM_MIN and row[4] is not None else fallback_pos
        )
        return {
            "name": str(row[0]),
            "type": str(row[1]),
            "nullable": not _is_not_null(row[2]),
            "position": pos,
        }
    raise NetezzaError(operation="compare_tables", detail="Unexpected column row shape.")


_DUPLICATE_COUNT_COLUMNS: Final[int] = 2
_DUPLICATE_SAMPLE_MIN_CELLS: Final[int] = 2
DUPLICATES_LIMIT_DEFAULT: Final[int] = 10
DUPLICATES_LIMIT_CAP: Final[int] = 100


def find_duplicates(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    key_columns: list[str],
    *,
    limit: int,
    timeout_s: int,
) -> dict[str, Any]:
    """Return duplicate key groups for ``key_columns`` plus a bounded sample.

    Netezza does not enforce PK/UNIQUE (issue #134), so this is the analyst's only check
    for double-run loads or fan-out joins. ``database`` must match the active profile
    database: the queries run as real ``SELECT`` bound to the session database, same rule
    as ``nz_table_sample``.
    """
    _ensure_profile_database(profile, database)
    schema_u = validate_catalog_identifier(schema)
    table_u = validate_catalog_identifier(table)
    keys_u = _validate_key_columns(key_columns)
    _ensure_columns_exist(profile, database, schema_u, table_u, keys_u)

    key_list = ", ".join(keys_u)
    groups, rows = _run_duplicate_counts(profile, schema_u, table_u, key_list, timeout_s)
    sample = _run_duplicate_sample(profile, schema_u, table_u, keys_u, key_list, limit, timeout_s)
    return {
        "duplicate_groups": groups,
        "duplicate_rows": rows,
        "sample": sample,
        "truncated": groups > limit,
    }


def _validate_key_columns(key_columns: list[str]) -> list[str]:
    if not key_columns:
        raise InvalidInputError(detail="key_columns must contain at least one column.")
    validated: list[str] = []
    for column in key_columns:
        name = validate_catalog_identifier(column)
        if name in validated:
            raise InvalidInputError(detail=f"key_columns contains a duplicate column: {name}.")
        validated.append(name)
    return validated


def _ensure_columns_exist(
    profile: Profile,
    database: str,
    schema_u: str,
    table_u: str,
    columns_u: list[str],
) -> None:
    """Raise when the table is missing (``OBJECT_NOT_FOUND``) or a key column is not there.

    A missing column is an input mistake by the caller (they named a column that does not
    exist), so it surfaces as ``INVALID_INPUT`` with the available columns in the detail.
    """
    password = get_password(profile.name)
    sql = render_cross_db(resolve_query("describe_table_columns", profile), database=database)
    connection = cast(Any, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, (schema_u, table_u))
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="find_duplicates",
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
    visible = {_duplicate_column_name(row) for row in rows}
    missing = [column for column in columns_u if column not in visible]
    if missing:
        raise InvalidInputError(
            detail=(
                f"Column(s) {', '.join(missing)} do not exist in "
                f"{database}.{schema_u}.{table_u}. Available: {', '.join(sorted(visible))}."
            ),
        )


def _run_duplicate_counts(
    profile: Profile,
    schema_u: str,
    table_u: str,
    key_list: str,
    timeout_s: int,
) -> tuple[int, int]:
    sql = (
        f"SELECT COUNT(*) AS DUP_GROUPS, COALESCE(SUM(CNT), 0) AS DUP_ROWS "  # noqa: S608
        f"FROM (SELECT COUNT(*) AS CNT FROM {schema_u}.{table_u} "
        f"GROUP BY {key_list} HAVING COUNT(*) > 1) AS NZ_MCP_DUP"
    )
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="find_duplicates",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    raw = execute_select(profile, parsed.raw, max_rows=1, timeout_s=timeout_s)
    rows = raw["rows"]
    if not rows or len(rows[0]) < _DUPLICATE_COUNT_COLUMNS:
        raise NetezzaError(
            operation="find_duplicates",
            detail="Duplicate count query returned an unexpected row shape.",
        )
    cells = rows[0]
    rows_in_groups = 0 if cells[1] is None else int(cells[1])
    return int(cells[0]), rows_in_groups


def _run_duplicate_sample(
    profile: Profile,
    schema_u: str,
    table_u: str,
    keys_u: list[str],
    key_list: str,
    limit: int,
    timeout_s: int,
) -> list[dict[str, Any]]:
    select_keys = ", ".join(keys_u)
    sql = (
        f"SELECT {select_keys}, COUNT(*) AS CNT "  # noqa: S608
        f"FROM {schema_u}.{table_u} "
        f"GROUP BY {key_list} HAVING COUNT(*) > 1 "
        f"ORDER BY CNT DESC, {key_list}"
    )
    parsed = guard_validate(sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise NetezzaError(
            operation="find_duplicates",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    limited = inject_limit(parsed.raw, limit)
    raw = execute_select(profile, limited, max_rows=limit, timeout_s=timeout_s)
    return [_duplicate_sample_item(row) for row in raw["rows"]]


def _duplicate_sample_item(row: Any) -> dict[str, Any]:
    cells = list(row)
    if len(cells) < _DUPLICATE_SAMPLE_MIN_CELLS:
        raise NetezzaError(
            operation="find_duplicates",
            detail="Duplicate sample row must include the key columns and a count.",
        )
    return {
        "key": [_stringify_duplicate(cell) for cell in cells[:-1]],
        "count": int(cells[-1]),
    }


def _stringify_duplicate(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    return str(value)


def _duplicate_column_name(row: Any) -> str:
    if isinstance(row, dict):
        name = row.get("COLUMN_NAME")
        if name is None:
            raise NetezzaError(
                operation="find_duplicates",
                detail="Column row must include COLUMN_NAME.",
            )
        return str(name).upper()
    if is_sequence_row(row, 1):
        return str(row[0]).upper()
    raise NetezzaError(operation="find_duplicates", detail="Unexpected column row shape.")
