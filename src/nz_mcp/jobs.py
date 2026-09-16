"""In-memory job store for async stored-procedure execution.

Each job runs in a daemon thread. The store is a module-level dict protected
by a threading.Lock. Completed jobs expire after JOB_TTL_S seconds; expiry
is lazy — pruned on every get / create call, no background thread needed.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Final, Literal

JOB_TTL_S: Final[float] = 3600.0
MAX_CONCURRENT_JOBS: Final[int] = 5

JobStatus = Literal["running", "done", "failed", "cancelling", "cancelled"]


@dataclass
class JobState:
    job_id: str
    status: JobStatus
    created_at: float
    completed_at: float | None = None
    session_id: int | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    partial_notices: list[str] = field(default_factory=list)


_store: dict[str, JobState] = {}
_lock: threading.Lock = threading.Lock()


def _purge_expired_locked() -> None:
    """Remove completed jobs past TTL. Caller must hold _lock."""
    now = time.monotonic()
    expired = [
        jid
        for jid, s in _store.items()
        if s.completed_at is not None and now - s.completed_at > JOB_TTL_S
    ]
    for jid in expired:
        del _store[jid]


class JobLimitError(Exception):
    """Raised by create_job when MAX_CONCURRENT_JOBS running jobs already exist."""


def create_job() -> str:
    """Register a new running job and return its job_id.

    Raises JobLimitError when the running-job count reaches MAX_CONCURRENT_JOBS.
    """
    job_id = str(uuid.uuid4())
    with _lock:
        _purge_expired_locked()
        running = sum(1 for s in _store.values() if s.status == "running")
        if running >= MAX_CONCURRENT_JOBS:
            raise JobLimitError()
        _store[job_id] = JobState(job_id=job_id, status="running", created_at=time.monotonic())
    return job_id


def set_session_id(job_id: str, session_id: int) -> None:
    """Record the Netezza session ID once the background thread captures it."""
    with _lock:
        if job_id in _store:
            _store[job_id].session_id = session_id


def update_partial_notices(job_id: str, notices: list[str]) -> None:
    """Replace the partial_notices list with the latest snapshot from the cursor."""
    with _lock:
        if job_id in _store:
            _store[job_id].partial_notices = list(notices)


def mark_done(job_id: str, result: dict[str, Any]) -> None:
    with _lock:
        if job_id in _store:
            s = _store[job_id]
            s.status = "done"
            s.result = result
            s.completed_at = time.monotonic()


def mark_failed(job_id: str, *, code: str, detail: str, partial_notices: list[str]) -> None:
    with _lock:
        if job_id in _store:
            s = _store[job_id]
            s.status = "failed"
            s.error = {"code": code, "detail": detail, "partial_notices": partial_notices}
            s.completed_at = time.monotonic()


def mark_cancelling(job_id: str) -> bool:
    """Transition a running job to 'cancelling'. Returns True if the transition happened.

    Reserved for #291 (nz_job_cancel). Not called from production code yet.
    """
    with _lock:
        s = _store.get(job_id)
        if s is None or s.status != "running":
            return False
        s.status = "cancelling"
        return True


def mark_cancelled(job_id: str) -> None:
    with _lock:
        if job_id in _store:
            s = _store[job_id]
            s.status = "cancelled"
            s.completed_at = time.monotonic()


def get_job(job_id: str) -> JobState | None:
    """Return a snapshot of the job state, or None if not found / expired."""
    with _lock:
        _purge_expired_locked()
        s = _store.get(job_id)
        if s is None:
            return None
        return JobState(
            job_id=s.job_id,
            status=s.status,
            created_at=s.created_at,
            completed_at=s.completed_at,
            session_id=s.session_id,
            result=s.result,
            error=s.error,
            partial_notices=list(s.partial_notices),
        )


def _reset_for_tests() -> None:
    """Clear all jobs. Tests only — never call from production code."""
    with _lock:
        _store.clear()
