"""Catalog queries for views."""

from __future__ import annotations

from contextlib import closing
from typing import Any, Final, Protocol, cast

import sqlglot
from sqlglot import expressions as exp

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import (
    render_cross_db,
    validate_catalog_identifier,
    validate_database_identifier,
)
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.catalog.row_shape import is_sequence_row
from nz_mcp.catalog.tables import describe_table
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError, ObjectNotFoundError
from nz_mcp.logging_utils import sanitize

_VIEW_LIST_MIN_ITEMS: Final[int] = 2
_MAX_LINEAGE_DEPTH: Final[int] = 5
_MAX_LINEAGE_NODES: Final[int] = 200
_KIND_VIEW: Final[str] = "VIEW"
_KIND_UNKNOWN: Final[str] = "UNKNOWN"


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
        params: tuple[str, str] | None = ...,
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
    """Return a re-executable ``CREATE OR REPLACE VIEW`` statement for a view.

    ``_V_VIEW.DEFINITION`` stores only the SELECT body of the view, not the
    ``CREATE VIEW … AS`` header. This function wraps the raw body into a
    complete, re-executable DDL statement.

    Issue #125: ``_V_VIEW.DEFINITION`` is computed lazily from ``_T_RULE`` of the
    session's *current* catalog. When the target view lives in a database
    different from the session's default (cross-database query
    ``<BD>.._V_VIEW``), the lazy join silently fails and Netezza projects the
    sentinel string ``'Not a view'`` instead of the real DDL. To work around
    this, we emit ``SET CATALOG <database>`` on the same connection right
    before the SELECT. Each call opens a fresh nzpy connection (no pool), so
    the catalog change does not leak into subsequent queries.
    """
    schema_ident = validate_catalog_identifier(schema)
    view_ident = validate_catalog_identifier(view)
    params: tuple[str, str] = (schema_ident, view_ident)
    password = get_password(profile.name)
    base_sql = resolve_query("get_view_ddl", profile)
    sql = render_cross_db(base_sql, database=database)
    # ``database`` was validated by ``render_cross_db``; re-normalize to the same
    # uppercase identifier shape we will issue via SET CATALOG (no quoting,
    # because Netezza does not accept quoted identifiers in SET CATALOG and the
    # validator restricts the alphabet to ``[A-Z][A-Z0-9_]*``).
    target_catalog = validate_database_identifier(database)

    connection = cast(_ConnectionForDdl, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            # Bind the session catalog to the target database BEFORE reading
            # ``_V_VIEW.DEFINITION``; otherwise the column projects the
            # sentinel ``'Not a view'`` for any cross-database lookup.
            cursor.execute(f"SET CATALOG {target_catalog}")
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
    definition = _row_to_definition(row)
    return f"CREATE OR REPLACE VIEW {schema_ident}.{view_ident} AS\n{definition}"


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
    if is_sequence_row(row, _VIEW_LIST_MIN_ITEMS):
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
    if is_sequence_row(row, 1):
        cell = row[0]
        return "" if cell is None else str(cell)
    raise NetezzaError(operation="get_view_ddl", detail="Unexpected row shape from _v_view")


def extract_object_references(definition: str) -> list[dict[str, str | None]]:
    """Return the relations a view ``DEFINITION`` reads, parsed with sqlglot.

    The tree is only read, never re-serialized (postgres re-printing rewrites Netezza
    SQL — see :func:`nz_mcp.catalog.execute.inject_limit`). Duplicate references are
    collapsed; ``database``/``schema`` stay ``None`` when the definition left them
    unqualified. A definition sqlglot cannot parse yields ``[]`` rather than an error:
    lineage is best-effort metadata, not a gate.
    """
    if not definition or not definition.strip():
        return []
    try:
        tree = sqlglot.parse_one(definition, read="postgres")
    except sqlglot.errors.SqlglotError:
        return []
    seen: dict[tuple[str | None, str | None, str], None] = {}
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        seen.setdefault((table.catalog or None, table.db or None, name), None)
    return [
        {"database": database, "schema": schema, "name": name} for database, schema, name in seen
    ]


def resolve_object_kinds(
    profile: Profile,
    database: str,
    default_schema: str,
    references: list[dict[str, str | None]],
) -> list[dict[str, str]]:
    """Resolve each referenced relation's real kind, honouring its own database.

    A reference qualified with another database (``OTHER_DB.SCHEMA.TABLE``) is resolved
    against that database and reported with it, so a local homonym never masks the real
    cross-database dependency.
    """
    if not references:
        return []
    password = get_password(profile.name)
    connection = cast(Any, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            return _resolve_references_on(cursor, profile, database, default_schema, references)
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="describe_view",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()


def describe_view(
    profile: Profile,
    database: str,
    schema: str,
    view: str,
) -> dict[str, Any]:
    """Return a view's columns and its direct object dependencies (what it reads).

    Columns and the ``VIEW`` kind come from :func:`describe_table` (which already handles
    views, issue #295); ``depends_on`` is derived by parsing the view ``DEFINITION`` with
    sqlglot and resolving each reference's real kind against the catalog.
    """
    try:
        payload = describe_table(profile, database, schema, view)
    except ObjectNotFoundError as exc:
        raise ObjectNotFoundError(
            detail=(
                f"View {view!r} does not exist in {database}.{schema} "
                "or is not visible to this profile."
            ),
            object_type="view",
            database=database,
            schema=schema,
            view=view,
        ) from exc
    if payload["kind"] != _KIND_VIEW:
        raise ObjectNotFoundError(
            detail=f"{database}.{schema}.{view} is a {payload['kind']}, not a view.",
            object_type=str(payload["kind"]),
            database=database,
            schema=schema,
            view=view,
        )
    definition = get_view_ddl(profile, database, schema, view)
    depends_on = resolve_object_kinds(
        profile,
        database,
        schema,
        extract_object_references(definition),
    )
    return {
        "name": payload["name"],
        "kind": _KIND_VIEW,
        "columns": payload["columns"],
        "depends_on": depends_on,
    }


def object_dependencies(
    profile: Profile,
    database: str,
    schema: str,
    obj: str,
    *,
    direction: str,
    depth: int,
) -> dict[str, Any]:
    """Walk object dependencies: ``up`` (what ``obj`` reads) or ``down`` (what reads it).

    ``up`` follows each view's parsed ``DEFINITION``; ``down`` scans the views of
    ``schema`` and keeps those whose definition references the current node (reverse
    edges are not in the catalog, so they are derived from the definitions). The walk is
    breadth-first, de-duplicated by ``(database, schema, name)`` so a cross-database
    dependency is not collapsed onto a local homonym, capped at ``_MAX_LINEAGE_DEPTH``
    levels and ``_MAX_LINEAGE_NODES`` nodes.
    """
    db_ident = validate_database_identifier(database)
    schema_ident = validate_catalog_identifier(schema)
    obj_ident = validate_catalog_identifier(obj)
    max_depth = min(max(depth, 1), _MAX_LINEAGE_DEPTH)
    password = get_password(profile.name)
    nodes: list[dict[str, Any]] = []
    truncated = False
    connection = cast(Any, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            root_kind = _relation_kind_on(cursor, profile, db_ident, schema_ident, obj_ident)
            if root_kind is None:
                raise ObjectNotFoundError(
                    detail=(
                        f"Object {obj!r} does not exist in {database}.{schema} "
                        "or is not visible to this profile."
                    ),
                    object_type="object",
                    database=database,
                    schema=schema,
                    object=obj,
                )
            visited = {(db_ident, schema_ident, obj_ident)}
            frontier = [(db_ident, schema_ident, obj_ident, 0)]
            while frontier and not truncated:
                next_frontier: list[tuple[str, str, str, int]] = []
                for node_db, node_schema, node_name, level in frontier:
                    if level >= max_depth:
                        continue
                    children = _lineage_children_on(
                        cursor,
                        profile,
                        node_db,
                        node_schema,
                        node_name,
                        direction,
                        schema_ident,
                    )
                    for child in children:
                        key = (child["database"], child["schema"], child["name"])
                        if key in visited:
                            continue
                        visited.add(key)
                        if len(nodes) >= _MAX_LINEAGE_NODES:
                            truncated = True
                            break
                        nodes.append({**child, "level": level + 1})
                        next_frontier.append(
                            (child["database"], child["schema"], child["name"], level + 1)
                        )
                    if truncated:
                        break
                frontier = next_frontier
    except ObjectNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="object_dependencies",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()
    return {
        "name": obj_ident,
        "kind": root_kind,
        "direction": direction,
        "depth": max_depth,
        "nodes": nodes,
        "truncated": truncated,
    }


def _kind_from_rows(rows: list[Any]) -> str:
    if not rows:
        return _KIND_UNKNOWN
    row = rows[0]
    if isinstance(row, dict):
        value = row.get("KIND")
        return _KIND_UNKNOWN if value is None else str(value)
    if is_sequence_row(row, 1):
        return str(row[0])
    return _KIND_UNKNOWN


def _relation_kind_on(
    cursor: Any,
    profile: Profile,
    database: str,
    schema: str,
    name: str,
) -> str | None:
    sql = render_cross_db(resolve_query("relation_kind", profile), database=database)
    cursor.execute(sql, (schema, name, schema, name))
    rows = cursor.fetchall()
    if not rows:
        return None
    return _kind_from_rows(rows)


def _set_catalog(cursor: Any, database: str) -> None:
    """Point the session catalog at ``database``.

    ``_V_VIEW.DEFINITION`` is computed lazily from the session's *current* catalog
    (issue #125): a cross-database lookup projects the ``'Not a view'`` sentinel unless the
    session catalog is switched first. Each lineage step binds the catalog to the database
    of the node it is about to read.
    """
    cursor.execute(f"SET CATALOG {validate_database_identifier(database)}")


def _reference_coordinates(
    reference: dict[str, str | None],
    context_database: str,
    context_schema: str,
) -> tuple[str, str, str]:
    """Effective ``(database, schema, name)`` for a parsed reference.

    A reference qualified with another database keeps it — cross-database lineage must not
    be collapsed onto a local homonym; an unqualified one is assumed to live in the context
    database/schema of the object that references it.
    """
    database = reference["database"] or context_database
    schema = reference["schema"] or context_schema
    return database, schema, reference["name"] or ""


def _lineage_children_on(
    cursor: Any,
    profile: Profile,
    node_database: str,
    node_schema: str,
    node_name: str,
    direction: str,
    scan_schema: str,
) -> list[dict[str, str]]:
    if direction == "down":
        return _referencing_views_on(
            cursor, profile, node_database, scan_schema, node_database, node_schema, node_name
        )
    definition = _view_definition_on(cursor, profile, node_database, node_schema, node_name)
    if definition is None:
        return []
    references = extract_object_references(definition)
    return _resolve_references_on(cursor, profile, node_database, node_schema, references)


def _view_definition_on(
    cursor: Any,
    profile: Profile,
    database: str,
    schema: str,
    name: str,
) -> str | None:
    _set_catalog(cursor, database)
    sql = render_cross_db(resolve_query("get_view_ddl", profile), database=database)
    cursor.execute(sql, (schema, name))
    row = cursor.fetchone()
    return None if row is None else _row_to_definition(row)


def _relation_kind_in(
    cursor: Any,
    profile: Profile,
    database: str,
    schema: str,
    name: str,
) -> str:
    """Resolve a relation's kind in ``database`` (which may be a different database)."""
    try:
        sql = render_cross_db(resolve_query("relation_kind", profile), database=database)
    except InvalidInputError:
        return _KIND_UNKNOWN
    cursor.execute(sql, (schema, name, schema, name))
    return _kind_from_rows(cursor.fetchall())


def _resolve_references_on(
    cursor: Any,
    profile: Profile,
    context_database: str,
    context_schema: str,
    references: list[dict[str, str | None]],
) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    for reference in references:
        database, schema, name = _reference_coordinates(reference, context_database, context_schema)
        resolved.append(
            {
                "database": database,
                "schema": schema,
                "name": name,
                "kind": _relation_kind_in(cursor, profile, database, schema, name),
            }
        )
    return resolved


def _referencing_views_on(
    cursor: Any,
    profile: Profile,
    node_database: str,
    scan_schema: str,
    target_database: str,
    target_schema: str,
    target_name: str,
) -> list[dict[str, str]]:
    _set_catalog(cursor, node_database)
    sql = render_cross_db(resolve_query("list_view_definitions", profile), database=node_database)
    cursor.execute(sql, (scan_schema,))
    rows = cursor.fetchall()
    target = (target_database.upper(), target_schema.upper(), target_name.upper())
    referencing: list[dict[str, str]] = []
    for row in rows:
        view_name, definition = _view_name_and_definition(row)
        for reference in extract_object_references(definition):
            database, schema, name = _reference_coordinates(reference, node_database, scan_schema)
            if (database.upper(), schema.upper(), name.upper()) == target:
                referencing.append(
                    {
                        "database": node_database,
                        "schema": scan_schema,
                        "name": view_name,
                        "kind": _KIND_VIEW,
                    }
                )
                break
    return referencing


def _view_name_and_definition(row: Any) -> tuple[str, str]:
    if isinstance(row, dict):
        name = row.get("VIEWNAME")
        if name is None:
            raise NetezzaError(
                operation="object_dependencies",
                detail="Catalog query must return VIEWNAME and DEFINITION columns.",
            )
        definition = row.get("DEFINITION")
        return str(name), "" if definition is None else str(definition)
    if is_sequence_row(row, 2):
        return str(row[0]), "" if row[1] is None else str(row[1])
    raise NetezzaError(operation="object_dependencies", detail="Unexpected row shape from _v_view")
