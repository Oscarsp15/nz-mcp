"""Async stored-procedure execution: launch in background thread, poll state."""

from __future__ import annotations

import threading
import time
from contextlib import closing, suppress
from typing import Any, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.call import (
    _count_signature_args,
    _ensure_session_database,
    _fetch_return_value,
    _read_notices,
)
from nz_mcp.catalog.identifier import validate_catalog_identifier
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.jobs import (
    MAX_CONCURRENT_JOBS,
    JobLimitError,
    create_job,
    get_job,
    mark_cancelled,
    mark_done,
    mark_failed,
    set_session_id,
    update_partial_notices,
)
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

_MAX_ARGS = 100

# Adaptive poll_after_s: short for fresh/fast jobs so a 3-second SP isn't stuck
# behind a fixed wait, grows with elapsed time so long SPs don't get hammered.
_POLL_MIN_S = 2
_POLL_MAX_S = 30


def _suggest_poll_after_s(elapsed_ms: int) -> int:
    """Suggest a next-poll delay that scales with how long the job has been running."""
    elapsed_s = elapsed_ms / 1000
    return int(min(_POLL_MAX_S, max(_POLL_MIN_S, elapsed_s)))


def _run_job(
    *,
    job_id: str,
    profile: Profile,
    password: str,
    call_sql: str,
    call_args: list[Any],
) -> None:
    """Background thread target. Opens its own connection; shares no state with other threads."""
    partial_notices: list[str] = []
    connection: Any = None
    start = time.monotonic()
    try:
        connection = cast(Any, open_connection(profile, password, timeout=None))

        # Capture Netezza session ID; exposed by nz_job_poll so a DBA can abort the session
        # manually with nzsession if needed. SELECT CURRENT_SID is a Netezza scalar that returns
        # this connection's own session ID (safe under concurrent use; never returns another's).
        with closing(connection.cursor()) as sid_cur:
            sid_cur.execute("SELECT CURRENT_SID")
            row = sid_cur.fetchone()
        if row is not None:
            raw_sid = row[0] if isinstance(row, (tuple, list)) else row
            with suppress(Exception):
                set_session_id(job_id, int(raw_sid))

        with closing(connection.cursor()) as cursor:
            cursor.execute(call_sql, tuple(call_args))
            partial_notices = _read_notices(cursor)
            update_partial_notices(job_id, partial_notices)
            return_value = _fetch_return_value(cursor)

    except Exception as exc:
        # cursor may be in scope (if execute raised) or not (if connection failed).
        with suppress(Exception):
            partial_notices = _read_notices(cursor)
        detail = sanitize(str(exc), known_secrets={password})
        state = get_job(job_id)
        if state is not None and state.status == "cancelling":
            mark_cancelled(job_id)
        else:
            mark_failed(
                job_id,
                code="NETEZZA_ERROR",
                detail=detail,
                partial_notices=partial_notices,
            )
        return
    finally:
        if connection is not None:
            with suppress(Exception):
                connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    mark_done(
        job_id,
        {
            "return_value": return_value,
            "messages": partial_notices,
            "duration_ms": duration_ms,
        },
    )


def launch_call_procedure(
    profile: Profile,
    *,
    database: str,
    schema: str,
    procedure: str,
    args: list[Any] | None,
    signature: str | None,
    confirm: bool,
) -> dict[str, Any]:
    """Validate inputs, register a job, start the background thread, return job_id immediately."""
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
            operation="launch_call_procedure",
            detail=f"Unexpected statement kind after validation: {parsed.kind}",
        )
    assert_env_safe(parsed.raw, active_database=profile.database)

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required for nz_call_procedure_async.",
        )

    try:
        job_id = create_job()
    except JobLimitError:
        raise InvalidInputError(
            code="JOB_LIMIT_REACHED",
            detail=f"Maximum concurrent async jobs ({MAX_CONCURRENT_JOBS}) already running.",
        ) from None

    password = get_password(profile.name)
    threading.Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "profile": profile,
            "password": password,
            "call_sql": parsed.raw,
            "call_args": call_args,
        },
        daemon=True,
    ).start()

    poll_after_s = _suggest_poll_after_s(0)
    return {
        "job_id": job_id,
        "status": "running",
        "session_id": None,
        "poll_after_s": poll_after_s,
        "hint_es": (
            f"Sondea con nz_job_poll(job_id='{job_id}') en unos {poll_after_s} s; "
            "el intervalo sugerido crece mientras el job siga corriendo, no esperes 30 s fijos. "
            "session_id llega null aquí porque el hilo en segundo plano todavía no abre la "
            "conexión a Netezza; aparece en la primera respuesta de nz_job_poll y permite a un "
            "DBA abortar con nzsession si es necesario."
        ),
        "hint_en": (
            f"Poll with nz_job_poll(job_id='{job_id}') in about {poll_after_s} s; "
            "the suggested interval grows while the job keeps running, don't wait a fixed 30 s. "
            "session_id is null here because the background thread hasn't opened the Netezza "
            "connection yet; it appears in the first nz_job_poll response and lets a DBA abort "
            "with nzsession if needed."
        ),
    }


def poll_job(job_id: str) -> dict[str, Any]:
    """Return the current state snapshot of an async job."""
    state = get_job(job_id)
    if state is None:
        raise InvalidInputError(
            code="JOB_NOT_FOUND",
            detail=f"No job with id={job_id!r} (may have expired or never existed).",
        )
    elapsed_ms = int((time.monotonic() - state.created_at) * 1000)
    still_running = state.status in ("running", "cancelling")
    out: dict[str, Any] = {
        "job_id": state.job_id,
        "status": state.status,
        "session_id": state.session_id,
        "elapsed_ms": elapsed_ms,
        "poll_after_s": _suggest_poll_after_s(elapsed_ms) if still_running else None,
        "partial_notices": state.partial_notices,
        "return_value": None,
        "messages": [],
        "duration_ms": None,
        "error": None,
    }
    if state.status == "done" and state.result is not None:
        out["return_value"] = state.result.get("return_value")
        out["messages"] = state.result.get("messages", [])
        out["duration_ms"] = state.result.get("duration_ms")
    elif state.status in ("failed", "cancelled") and state.error is not None:
        out["error"] = state.error
    return out
