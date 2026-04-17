"""Validate catalog SQL for a profile by executing each registered query with dummy parameters."""

from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import render_cross_db
from nz_mcp.catalog.queries import ALL_QUERIES, CatalogQuery
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.errors import CredentialNotFoundError, InvalidInputError, InvalidProfileError

_DUMMY_SCHEMA: Final[str] = "DBO"
_DUMMY_OBJECT: Final[str] = "__NZ_MCP_PROBE_DUMMY__"

# Queries whose dummy names may not exist; driver errors suggesting a missing object are warnings.
_STRUCTURAL_IDS: Final[frozenset[str]] = frozenset(
    {
        "get_view_ddl",
        "describe_table_columns",
        "describe_table_distribution",
        "describe_table_pk",
        "describe_table_fk",
        "table_stats",
        "get_procedure_ddl",
        "get_procedure_section",
    }
)


ProbeStatus = Literal["ok", "failure", "structural_warning"]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome for a single catalog query id."""

    query_id: str
    status: ProbeStatus
    duration_ms: float | None
    row_count: int | None
    error_detail: str | None
    detail: str | None  # human hint (e.g. placeholder mismatch)


@dataclass(frozen=True, slots=True)
class ProbeRun:
    """Full probe result; ``config_error`` is set when the run could not finish normally."""

    profile_name: str
    config_error: str | None
    results: tuple[ProbeResult, ...]


def dummy_params_for_query_id(query_id: str) -> tuple[Any, ...]:
    """Return safe dummy parameters matching the default SQL for ``query_id``."""
    mapping: dict[str, tuple[Any, ...]] = {
        "list_databases": (None, None),
        "list_schemas": (None, None),
        "list_tables": (_DUMMY_SCHEMA, None, None),
        "list_views": (_DUMMY_SCHEMA, None, None),
        "get_view_ddl": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "describe_table_columns": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "describe_table_distribution": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "describe_table_pk": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "describe_table_fk": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "table_stats": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "list_procedures": (_DUMMY_SCHEMA, None, None),
        "get_procedure_ddl": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
        "get_procedure_section": (_DUMMY_SCHEMA, _DUMMY_OBJECT),
    }
    if query_id not in mapping:
        raise KeyError(f"Unknown catalog query id: {query_id}")
    return mapping[query_id]


def _placeholder_mismatch_message(sql: str, params: tuple[Any, ...]) -> str | None:
    n_q = sql.count("?")
    if n_q != len(params):
        return (
            f"Placeholder count mismatch: SQL has {n_q} '?' "
            f"but {len(params)} parameters were provided."
        )
    return None


def _looks_like_missing_object(message: str) -> bool:
    lowered = message.lower()
    needles = (
        "does not exist",
        "not exist",
        "not found",
        "no such",
        "undefined object",
        "undefined name",
        "object not found",
    )
    return any(n in lowered for n in needles)


def prepare_sql(profile: Profile, cq: CatalogQuery) -> str:
    """Resolve and render catalog SQL (``<BD>..``) for ``cq``."""
    base = resolve_query(cq.id, profile)
    return render_cross_db(base, profile.database)


def probe_one_row(
    cursor: Any,
    profile: Profile,
    cq: CatalogQuery,
) -> ProbeResult:
    """Execute one catalog probe using an open cursor."""
    try:
        sql = prepare_sql(profile, cq)
    except (InvalidProfileError, InvalidInputError) as exc:
        return ProbeResult(
            query_id=cq.id,
            status="failure",
            duration_ms=None,
            row_count=None,
            error_detail=str(exc),
            detail=None,
        )

    params = dummy_params_for_query_id(cq.id)
    mismatch = _placeholder_mismatch_message(sql, params)
    if mismatch is not None:
        return ProbeResult(
            query_id=cq.id,
            status="failure",
            duration_ms=None,
            row_count=None,
            error_detail=None,
            detail=mismatch,
        )

    start = time.perf_counter()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        detail_text = str(exc)
        if cq.id in _STRUCTURAL_IDS and _looks_like_missing_object(detail_text):
            return ProbeResult(
                query_id=cq.id,
                status="structural_warning",
                duration_ms=duration_ms,
                row_count=None,
                error_detail=detail_text,
                detail=None,
            )
        return ProbeResult(
            query_id=cq.id,
            status="failure",
            duration_ms=duration_ms,
            row_count=None,
            error_detail=detail_text,
            detail=None,
        )

    duration_ms = (time.perf_counter() - start) * 1000.0
    return ProbeResult(
        query_id=cq.id,
        status="ok",
        duration_ms=duration_ms,
        row_count=len(rows),
        error_detail=None,
        detail=None,
    )


def run_probe_catalog(profile: Profile) -> ProbeRun:
    """Run all catalog probes for ``profile`` using a real Netezza connection."""
    try:
        resolve_query(ALL_QUERIES[0].id, profile)
    except InvalidProfileError as exc:
        return ProbeRun(profile_name=profile.name, config_error=str(exc), results=())

    try:
        password = get_password(profile.name)
    except CredentialNotFoundError as exc:
        return ProbeRun(profile_name=profile.name, config_error=str(exc), results=())

    try:
        connection = cast(Any, open_connection(profile, password))
    except NzConnectionError as exc:
        return ProbeRun(profile_name=profile.name, config_error=str(exc), results=())

    results: list[ProbeResult] = []
    try:
        with closing(connection.cursor()) as cursor:
            cur = cast(Any, cursor)
            for cq in ALL_QUERIES:
                results.append(probe_one_row(cur, profile, cq))
    finally:
        connection.close()

    return ProbeRun(profile_name=profile.name, config_error=None, results=tuple(results))


def probe_has_hard_failure(run: ProbeRun) -> bool:
    """True if the run must yield a non-zero CLI exit (config error or any failure row)."""
    if run.config_error is not None:
        return True
    return any(r.status == "failure" for r in run.results)


def probe_result_to_json_dict(r: ProbeResult) -> dict[str, Any]:
    """Serialize ``ProbeResult`` for JSON output."""
    return {
        "query_id": r.query_id,
        "status": r.status,
        "duration_ms": r.duration_ms,
        "row_count": r.row_count,
        "error": r.error_detail,
        "detail": r.detail,
    }


def probe_run_to_json_dict(run: ProbeRun) -> dict[str, Any]:
    """Serialize ``ProbeRun`` for JSON output."""
    return {
        "profile": run.profile_name,
        "config_error": run.config_error,
        "results": [probe_result_to_json_dict(r) for r in run.results],
    }
