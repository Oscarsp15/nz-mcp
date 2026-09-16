"""Unit tests for the in-memory job store."""

from __future__ import annotations

import time

import pytest

from nz_mcp.jobs import (
    MAX_CONCURRENT_JOBS,
    JobLimitError,
    _reset_for_tests,
    create_job,
    get_job,
    mark_cancelled,
    mark_cancelling,
    mark_done,
    mark_failed,
    set_session_id,
    update_partial_notices,
)


@pytest.fixture(autouse=True)
def clean_store() -> None:
    _reset_for_tests()


def test_create_job_returns_unique_ids() -> None:
    a = create_job()
    b = create_job()
    assert a != b


def test_get_job_returns_running_state() -> None:
    job_id = create_job()
    state = get_job(job_id)
    assert state is not None
    assert state.job_id == job_id
    assert state.status == "running"
    assert state.session_id is None


def test_get_job_returns_none_for_unknown() -> None:
    assert get_job("nonexistent-id") is None


def test_set_session_id() -> None:
    job_id = create_job()
    set_session_id(job_id, 42)
    assert get_job(job_id).session_id == 42  # type: ignore[union-attr]


def test_update_partial_notices() -> None:
    job_id = create_job()
    update_partial_notices(job_id, ["NOTICE: step 1"])
    state = get_job(job_id)
    assert state is not None
    assert state.partial_notices == ["NOTICE: step 1"]


def test_update_partial_notices_copies_list() -> None:
    job_id = create_job()
    notices = ["a"]
    update_partial_notices(job_id, notices)
    notices.append("b")  # mutate original
    state = get_job(job_id)
    assert state is not None
    assert state.partial_notices == ["a"]  # store was not affected


def test_mark_done() -> None:
    job_id = create_job()
    mark_done(job_id, {"return_value": "42", "messages": ["ok"], "duration_ms": 100})
    state = get_job(job_id)
    assert state is not None
    assert state.status == "done"
    assert state.result is not None
    assert state.result["return_value"] == "42"
    assert state.completed_at is not None


def test_mark_failed() -> None:
    job_id = create_job()
    mark_failed(job_id, code="NETEZZA_ERROR", detail="boom", partial_notices=["n1"])
    state = get_job(job_id)
    assert state is not None
    assert state.status == "failed"
    assert state.error is not None
    assert state.error["code"] == "NETEZZA_ERROR"
    assert state.error["partial_notices"] == ["n1"]
    assert state.completed_at is not None


def test_mark_cancelling_running_job() -> None:
    job_id = create_job()
    result = mark_cancelling(job_id)
    assert result is True
    assert get_job(job_id).status == "cancelling"  # type: ignore[union-attr]


def test_mark_cancelling_non_running_job_returns_false() -> None:
    job_id = create_job()
    mark_done(job_id, {"return_value": None, "messages": [], "duration_ms": 0})
    result = mark_cancelling(job_id)
    assert result is False
    assert get_job(job_id).status == "done"  # type: ignore[union-attr]


def test_mark_cancelled() -> None:
    job_id = create_job()
    mark_cancelling(job_id)
    mark_cancelled(job_id)
    state = get_job(job_id)
    assert state is not None
    assert state.status == "cancelled"
    assert state.completed_at is not None


def test_job_limit_raises_when_full() -> None:
    for _ in range(MAX_CONCURRENT_JOBS):
        create_job()
    with pytest.raises(JobLimitError):
        create_job()


def test_completed_job_does_not_count_toward_limit() -> None:
    for _ in range(MAX_CONCURRENT_JOBS):
        create_job()
    # Mark all done
    from nz_mcp.jobs import _lock, _store

    with _lock:
        for s in _store.values():
            s.status = "done"
            s.completed_at = time.monotonic()
    # Should now be able to create new jobs
    new_id = create_job()
    assert get_job(new_id) is not None


def test_expired_job_is_pruned() -> None:
    import nz_mcp.jobs as jobs_module

    job_id = create_job()
    mark_done(job_id, {"return_value": None, "messages": [], "duration_ms": 0})

    # Back-date completed_at so the job appears expired.
    with jobs_module._lock:
        jobs_module._store[job_id].completed_at = time.monotonic() - jobs_module.JOB_TTL_S - 1

    # get_job triggers lazy purge.
    assert get_job(job_id) is None


def test_get_job_returns_snapshot_not_reference() -> None:
    job_id = create_job()
    state1 = get_job(job_id)
    assert state1 is not None
    mark_done(job_id, {"return_value": "x", "messages": [], "duration_ms": 5})
    assert state1.status == "running"  # snapshot is not mutated
