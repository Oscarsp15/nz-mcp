"""Compile caller-supplied procedure/view DDL (admin) with ``sql_guard`` + env guard.

Unlike ``clone_procedure`` (which reconstructs DDL from catalog source), this path
takes a full ``CREATE [OR REPLACE] PROCEDURE`` (NZPLSQL) or ``CREATE [OR REPLACE]
VIEW`` written by the caller — inline or read from a file — and compiles it against
the active profile database. The NZPLSQL body is opaque to ``sql_guard`` (validated
via the header path); the environment guard rejects ``PROD_`` references from a
non-production session.
"""

from __future__ import annotations

import re
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError
from nz_mcp.io import read_input_ddl
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

_NZPLSQL_MARKER: Final[re.Pattern[str]] = re.compile(r"\bLANGUAGE\s+NZPLSQL\s+AS\b", re.IGNORECASE)
_CREATE_VIEW_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b",
    re.IGNORECASE,
)


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _resolve_ddl(sql: str | None, input_path: str | None) -> str:
    """Return the DDL text from exactly one of ``sql`` / ``input_path``."""
    if (sql is None) == (input_path is None):
        raise InvalidInputError(
            detail="Provide exactly one of 'sql' or 'input_path' for nz_execute_ddl.",
        )
    if input_path is not None:
        try:
            text = read_input_ddl(input_path)
        except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
            raise InvalidInputError(detail=str(exc)) from exc
    else:
        text = sql if sql is not None else ""
    stripped = text.strip()
    if not stripped:
        raise InvalidInputError(detail="The DDL to execute is empty.")
    return stripped


def _assert_type_matches(ddl: str, statement_type: str) -> None:
    """Ensure the DDL shape matches the declared ``statement_type``."""
    has_marker = _NZPLSQL_MARKER.search(ddl) is not None
    if statement_type == "procedure":
        if not has_marker:
            raise InvalidInputError(
                detail=(
                    "statement_type='procedure' requires a CREATE PROCEDURE ... "
                    "LANGUAGE NZPLSQL AS statement."
                ),
            )
    elif statement_type == "view":
        if has_marker or _CREATE_VIEW_HEAD.match(ddl) is None:
            raise InvalidInputError(
                detail="statement_type='view' requires a CREATE [OR REPLACE] VIEW statement.",
            )
    else:
        raise InvalidInputError(detail="statement_type must be 'procedure' or 'view'.")


def execute_ddl(
    profile: Profile,
    *,
    sql: str | None,
    input_path: str | None,
    statement_type: str,
    dry_run: bool,
    confirm: bool,
) -> dict[str, Any]:
    """Validate and (optionally) compile a procedure/view DDL against the active DB."""
    ddl = _resolve_ddl(sql, input_path)
    _assert_type_matches(ddl, statement_type)

    parsed = guard_validate(ddl, mode="admin")
    if parsed.kind is not StatementKind.CREATE:
        raise GuardRejectedError(
            code="WRONG_STATEMENT_FOR_TOOL",
            tool="nz_execute_ddl",
            kind=str(parsed.kind),
        )

    assert_env_safe(parsed.raw, active_database=profile.database)

    if dry_run:
        return {
            "dry_run": True,
            "sql_to_execute": parsed.raw,
            "executed": False,
            "duration_ms": 0,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_execute_ddl.",
        )

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except NetezzaError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_ddl",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "dry_run": False,
        "sql_to_execute": parsed.raw,
        "executed": True,
        "duration_ms": duration_ms,
    }
