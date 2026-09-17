"""Netezza table maintenance (``GENERATE STATISTICS`` / ``GROOM`` / ``VACUUM``), admin-only.

The caller declares the operation as structured data (an action from a closed
allowlist plus validated identifiers); this module builds the single statement,
validates it through ``sql_guard`` and only then executes it. No raw SQL is accepted.
"""

from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Final, Literal, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.ddl import _ensure_session_database, _qualified_table
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

MaintenanceAction = Literal["generate_statistics", "groom", "vacuum"]

# Closed allowlist: an unknown action has no template and is rejected before any SQL is
# built (default-deny). ``{qual}`` is replaced with the validated ``schema.table``. NPS
# takes ``VACUUM`` directly on the table (no ``TABLE`` keyword, no ``FULL``).
_ACTION_TEMPLATES: Final[dict[str, str]] = {
    "generate_statistics": "GENERATE STATISTICS ON {qual}",
    "groom": "GROOM TABLE {qual}",
    "vacuum": "VACUUM {qual}",
}


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _build_maintenance_statement(schema: str, table: str, action: str) -> str:
    template = _ACTION_TEMPLATES.get(action)
    if template is None:
        raise InvalidInputError(
            code="INVALID_MAINTENANCE_ACTION",
            detail=f"Unsupported maintenance action: {action!r}.",
        )
    return template.format(qual=_qualified_table(schema, table))


def execute_maintenance(
    profile: Profile,
    database: str,
    schema: str,
    table: str,
    *,
    action: str,
    dry_run: bool,
    confirm: bool,
    echo_sql: bool = True,
) -> dict[str, Any]:
    """Build one maintenance statement, validate it, and optionally execute it."""
    _ensure_session_database(profile, database)
    statement = _build_maintenance_statement(schema, table, action)

    parsed = guard_validate(statement, mode="admin")
    if parsed.kind is not StatementKind.MAINTENANCE:
        raise NetezzaError(
            operation="execute_maintenance",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    assert_env_safe(parsed.raw, active_database=profile.database)

    if dry_run:
        return {
            "action": action,
            "dry_run": True,
            "statements_to_execute": [parsed.raw],
            "executed": False,
            "statements_executed": 0,
            "duration_ms": 0,
        }

    if confirm is not True:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_maintenance.",
        )

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_maintenance",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "action": action,
        "dry_run": False,
        "statements_to_execute": [parsed.raw] if echo_sql else None,
        "executed": True,
        "statements_executed": 1,
        "duration_ms": duration_ms,
    }
