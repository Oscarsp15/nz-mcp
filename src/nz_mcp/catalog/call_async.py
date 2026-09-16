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
    mark_cancelling,
    mark_done,
    mark_failed,
    set_session_id,
    update_partial_notices,
)
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

_MAX_ARGS = 100


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

        # Capture Netezza session ID so nz_job_cancel can identify the session to abort.
        # SELECT CURRENT_SID is a Netezza scalar that returns this connection's own session ID.
        # It is safe under concurrent use: each session always returns its own ID, never another's.
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

    return {
        "job_id": job_id,
        "status": "running",
        "session_id": None,
        "hint_es": (
            f"Sondea con nz_job_poll(job_id='{job_id}') cada 30 s. "
            "Cancela con nz_job_cancel(job_id=...) si es necesario."
        ),
        "hint_en": (
            f"Poll with nz_job_poll(job_id='{job_id}') every 30 s. "
            "Cancel with nz_job_cancel(job_id=...) if needed."
        ),
    }


def cancel_job(job_id: str, *, profile: Profile, password: str) -> dict[str, Any]:
    """Send ABORT SESSION for a running async job via a second admin connection."""
    state = get_job(job_id)
    if state is None:
        raise InvalidInputError(
            code="JOB_NOT_FOUND",
            detail=f"No job with id={job_id!r} (may have expired or never existed).",
        )

    if state.status in ("done", "failed", "cancelled", "cancelling"):
        return {
            "job_id": job_id,
            "status": "already_done",
            "previous_status": state.status,
            "session_id": state.session_id,
            "abort_error": None,
            "message_es": (
                f"El job ya terminó con estado '{state.status}'; no hay nada que cancelar."
            ),
            "message_en": (
                f"Job already finished with status '{state.status}'; nothing to cancel."
            ),
        }

    if state.session_id is None:
        raise InvalidInputError(
            code="CANCEL_UNAVAILABLE",
            detail=(
                f"Job {job_id!r} has no captured session_id. "
                "The background thread may not have opened a connection yet; "
                "wait a moment and retry, or poll until it reaches a terminal state."
            ),
        )

    session_id = state.session_id

    # Transition to cancelling so _run_job treats the next exception as a cancel.
    transitioned = mark_cancelling(job_id)
    if not transitioned:
        # Job reached a terminal state between our check and now.
        current_state = get_job(job_id)
        current_status = current_state.status if current_state else "unknown"
        return {
            "job_id": job_id,
            "status": "already_done",
            "previous_status": current_status,
            "session_id": session_id,
            "abort_error": None,
            "message_es": (f"El job terminó justo antes de cancelar (estado: '{current_status}')."),
            "message_en": (f"Job finished just before cancel (status: '{current_status}')."),
        }

    abort_error: str | None = None
    connection: Any = None
    try:
        connection = cast(Any, open_connection(profile, password, timeout=30))
        with closing(connection.cursor()) as cursor:
            cursor.execute(f"ABORT SESSION {session_id}")
    except Exception as exc:
        abort_error = sanitize(str(exc), known_secrets={password})
    finally:
        if connection is not None:
            with suppress(Exception):
                connection.close()

    if abort_error is not None:
        return {
            "job_id": job_id,
            "status": "cancelling",
            "session_id": session_id,
            "abort_error": abort_error,
            "message_es": (
                f"ABORT SESSION {session_id} falló: {abort_error}. "
                "El job sigue en estado 'cancelling'. "
                f"Pide a un DBA que ejecute: ABORT SESSION {session_id}"
            ),
            "message_en": (
                f"ABORT SESSION {session_id} failed: {abort_error}. "
                "Job remains 'cancelling'. "
                f"Ask a DBA to run: ABORT SESSION {session_id}"
            ),
        }

    return {
        "job_id": job_id,
        "status": "cancelling",
        "session_id": session_id,
        "abort_error": None,
        "message_es": (
            f"ABORT SESSION enviado a la sesión {session_id}. "
            "El job pasará a 'cancelled' cuando el hilo confirme la interrupción."
        ),
        "message_en": (
            f"ABORT SESSION sent to session {session_id}. "
            "The job will transition to 'cancelled' once the thread confirms the interruption."
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
    out: dict[str, Any] = {
        "job_id": state.job_id,
        "status": state.status,
        "session_id": state.session_id,
        "elapsed_ms": elapsed_ms,
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
