"""Execute a stored procedure via ``CALL`` (admin), capturing NOTICE/RAISE messages.

The ``CALL`` SQL is built here from validated identifiers with ``?`` placeholders for
the arguments (parameterized — never concatenated), passed through ``sql_guard`` (which
classifies ``CALL`` and gates it to admin), and screened by the environment guard so a
non-production session cannot invoke a ``PROD_`` procedure.
"""

from __future__ import annotations

import time
from contextlib import closing, suppress
from typing import Any, Final, Protocol, cast

from nzpy import ProgrammingError

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import validate_catalog_identifier, validate_database_identifier
from nz_mcp.config import TIMEOUT_S_CAP, Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError, QueryTimeoutError
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

_MAX_ARGS: Final[int] = 100


class _CursorLike(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def fetchone(self) -> Any: ...
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
                f"({db_sess}) for nz_call_procedure."
            ),
        )


def _count_signature_args(signature: str) -> int:
    """Count top-level, comma-separated argument types in a ``(TYPE, TYPE)`` signature."""
    inner = signature.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    inner = inner.strip()
    if not inner:
        return 0
    depth = 0
    count = 1
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            count += 1
    return count


def _read_notices(cursor: object) -> list[str]:
    """Extract and normalise the NOTICE messages accumulated on a cursor."""
    raw = getattr(cursor, "notices", None) or []
    return [s for n in raw if (s := str(n).strip())]


def _is_timeout_exc(exc: BaseException) -> bool:
    """Return True when *exc* looks like a socket read-timeout from nzpy."""
    # TimeoutError covers socket.timeout (same class in Python 3.11+).
    if isinstance(exc, TimeoutError):
        return True
    # nzpy may surface it as a generic OSError; match on message as a fallback.
    return isinstance(exc, OSError) and "timed out" in str(exc).lower()


def _fetch_return_value(cursor: _CursorLike) -> str | None:
    """Return the CALL result value when the procedure produced a result set, else None."""
    try:
        row = cursor.fetchone()
    except ProgrammingError as exc:
        if "no result set" in str(exc).lower():
            return None
        raise
    if row is None:
        return None
    if isinstance(row, (tuple, list)):
        return None if not row or row[0] is None else str(row[0])
    return str(row)


def call_procedure(
    profile: Profile,
    *,
    database: str,
    schema: str,
    procedure: str,
    args: list[Any] | None,
    signature: str | None,
    dry_run: bool,
    confirm: bool,
    timeout_s: int | None,
) -> dict[str, Any]:
    """Build and (optionally) run ``CALL schema.proc(args)``; capture return value + messages."""
    _ensure_session_database(profile, database)
    sch = validate_catalog_identifier(schema)
    proc = validate_catalog_identifier(procedure)
    call_args = list(args) if args else []
    if len(call_args) > _MAX_ARGS:
        raise InvalidInputError(detail=f"Too many arguments (max {_MAX_ARGS}).")
    if signature is not None and _count_signature_args(signature) != len(call_args):
        raise InvalidInputError(
            detail=(
                f"args count ({len(call_args)}) does not match the signature "
                f"({_count_signature_args(signature)} parameters)."
            ),
        )

    placeholders = ", ".join(["?"] * len(call_args))
    call_sql = f"CALL {sch}.{proc}({placeholders})"

    parsed = guard_validate(call_sql, mode="admin")
    if parsed.kind is not StatementKind.CALL:
        raise NetezzaError(
            operation="call_procedure",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    assert_env_safe(parsed.raw, active_database=profile.database)

    if dry_run:
        return {
            "dry_run": True,
            "call_sql": parsed.raw,
            "executed": False,
            "return_value": None,
            "messages": [],
            "duration_ms": 0,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_call_procedure.",
        )

    # None → no socket timeout; block until the SP returns (for long-running procedures).
    # Explicit timeout_s → cap at TIMEOUT_S_CAP and pass to the socket layer.
    effective_timeout: int | None = min(timeout_s, TIMEOUT_S_CAP) if timeout_s is not None else None

    password = get_password(profile.name)
    connection = cast(
        _ConnectionLike, open_connection(profile, password, timeout=effective_timeout)
    )
    start = time.monotonic()
    # Declared here so the except block can read any notices emitted before the failure.
    partial_notices: list[str] = []
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, tuple(call_args))
            # Read notices immediately after execute() so they are available even
            # if _fetch_return_value raises (e.g. "no result set" on a void proc).
            partial_notices = _read_notices(cursor)
            return_value = _fetch_return_value(cursor)
    except NetezzaError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        # Capture any notices emitted before the failure; the cursor variable is
        # still in scope because Python does not limit with-block assignments.
        with suppress(Exception):
            partial_notices = _read_notices(cursor)
        detail = sanitize(str(exc), known_secrets={password})
        if _is_timeout_exc(exc):
            raise QueryTimeoutError(
                operation="call_procedure",
                database=database,
                detail=detail,
                # The client socket timed out but the server session may still be
                # running.  nzpy exposes no cancel() and the finally close() only
                # shuts the local socket, so the session can persist in _V_SESSION
                # until the procedure finishes or a DBA runs ABORT SESSION.
                orphan_session_risk=True,
                partial_notices=partial_notices,
            ) from exc
        raise NetezzaError(
            operation="call_procedure",
            database=database,
            detail=detail,
            partial_notices=partial_notices,
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "dry_run": False,
        "call_sql": parsed.raw,
        "executed": True,
        "return_value": return_value,
        "messages": partial_notices,
        "duration_ms": duration_ms,
    }
