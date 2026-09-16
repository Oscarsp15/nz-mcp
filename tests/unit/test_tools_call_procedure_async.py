"""Unit tests for nz_call_procedure_async and nz_job_poll."""

from __future__ import annotations

import threading
from contextlib import suppress
from typing import Any
from unittest.mock import patch

import pytest

from nz_mcp.catalog.call_async import launch_call_procedure, poll_job
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.jobs import (
    MAX_CONCURRENT_JOBS,
    _reset_for_tests,
    create_job,
    get_job,
    mark_done,
)


def _profile(*, database: str = "DESA_MODELOS") -> Profile:
    return Profile(name="p", host="h", port=5480, database=database, user="u", mode="admin")


@pytest.fixture(autouse=True)
def clean_jobs() -> None:
    _reset_for_tests()


# ---------------------------------------------------------------------------
# launch_call_procedure
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, *, sid: int = 99, notices: list[str] | None = None) -> None:
        self._sid = sid
        self.notices = notices or []
        self._row: Any = None
        self.description: Any = None
        self.executed: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append(sql)

    def fetchone(self) -> Any:
        if "CURRENT_SESSION" in (self.executed[-1] if self.executed else ""):
            return (self._sid,)
        return self._row

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _fake_open(profile: Any, password: str, **_kw: Any) -> _FakeConn:
    return _FakeConn(_FakeCursor())


def _fake_password(name: str) -> str:
    return "pw"


def test_launch_returns_job_id_immediately() -> None:
    barrier = threading.Barrier(2)

    def _slow_open(profile: Any, password: str, **_kw: Any) -> _FakeConn:
        barrier.wait()  # block until test proceeds
        return _FakeConn(_FakeCursor())

    with (
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_slow_open),
        patch("nz_mcp.catalog.call_async.get_password", return_value="pw"),
    ):
        result = launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="MYPROC",
            args=None,
            signature=None,
            confirm=True,
        )

    assert "job_id" in result
    assert result["status"] == "running"
    # Unblock background thread so it doesn't linger past the test
    with suppress(threading.BrokenBarrierError):
        barrier.wait(timeout=2)


def test_launch_requires_confirm() -> None:
    with pytest.raises(InvalidInputError, match="CONFIRM_REQUIRED"):
        launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="P",
            args=None,
            signature=None,
            confirm=False,
        )


def test_launch_rejects_wrong_database() -> None:
    with pytest.raises(InvalidInputError):
        launch_call_procedure(
            _profile(database="DESA_MODELOS"),
            database="OTHER_DB",
            schema="PUBLIC",
            procedure="P",
            args=None,
            signature=None,
            confirm=True,
        )


def test_launch_raises_job_limit_when_full() -> None:
    for _ in range(MAX_CONCURRENT_JOBS):
        create_job()
    with (
        pytest.raises(InvalidInputError, match="JOB_LIMIT_REACHED"),
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_fake_open),
        patch("nz_mcp.catalog.call_async.get_password", return_value="pw"),
    ):
        launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="P",
            args=None,
            signature=None,
            confirm=True,
        )


def test_background_thread_marks_job_done() -> None:
    done_event = threading.Event()
    original_mark_done = __import__("nz_mcp.jobs", fromlist=["mark_done"]).mark_done

    def _patched_mark_done(job_id: str, result: dict[str, Any]) -> None:
        original_mark_done(job_id, result)
        done_event.set()

    with (
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_fake_open),
        patch("nz_mcp.catalog.call_async.get_password", return_value="pw"),
        patch("nz_mcp.catalog.call_async.mark_done", side_effect=_patched_mark_done),
    ):
        result = launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="MYPROC",
            args=None,
            signature=None,
            confirm=True,
        )

    job_id = result["job_id"]
    assert done_event.wait(timeout=5), "background thread did not complete in time"
    state = get_job(job_id)
    assert state is not None
    assert state.status == "done"


def test_background_thread_marks_job_failed_on_error() -> None:
    def _error_open(profile: Any, password: str, **_kw: Any) -> Any:
        raise OSError("simulated connection error")

    failed_event = threading.Event()
    original_mark_failed = __import__("nz_mcp.jobs", fromlist=["mark_failed"]).mark_failed

    def _patched_mark_failed(
        job_id: str, *, code: str, detail: str, partial_notices: list[str]
    ) -> None:
        original_mark_failed(job_id, code=code, detail=detail, partial_notices=partial_notices)
        failed_event.set()

    with (
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_error_open),
        patch("nz_mcp.catalog.call_async.get_password", return_value="pw"),
        patch("nz_mcp.catalog.call_async.mark_failed", side_effect=_patched_mark_failed),
    ):
        result = launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="MYPROC",
            args=None,
            signature=None,
            confirm=True,
        )

    assert failed_event.wait(timeout=5), "background thread did not fail in time"
    state = get_job(result["job_id"])
    assert state is not None
    assert state.status == "failed"
    assert state.error is not None
    assert state.error["code"] == "NETEZZA_ERROR"


def test_background_thread_marks_cancelled_when_cancelling() -> None:
    """If the job is in 'cancelling' state when the thread raises, it marks cancelled."""
    from nz_mcp.jobs import mark_cancelling

    # Use an event to ensure mark_cancelling is called BEFORE the thread raises.
    cancel_set = threading.Event()

    def _error_open(profile: Any, password: str, **_kw: Any) -> Any:
        cancel_set.wait(timeout=3)  # block until mark_cancelling is called
        raise OSError("simulated abort after cancel")

    cancelled_event = threading.Event()
    original_mark_cancelled = __import__("nz_mcp.jobs", fromlist=["mark_cancelled"]).mark_cancelled

    def _patched_mark_cancelled(job_id: str) -> None:
        original_mark_cancelled(job_id)
        cancelled_event.set()

    with (
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_error_open),
        patch("nz_mcp.catalog.call_async.get_password", return_value="pw"),
        patch("nz_mcp.catalog.call_async.mark_cancelled", side_effect=_patched_mark_cancelled),
    ):
        result = launch_call_procedure(
            _profile(),
            database="DESA_MODELOS",
            schema="PUBLIC",
            procedure="MYPROC",
            args=None,
            signature=None,
            confirm=True,
        )
        job_id = result["job_id"]
        mark_cancelling(job_id)
        cancel_set.set()  # unblock the thread now that status is cancelling
        assert cancelled_event.wait(timeout=5), "background thread did not cancel in time"

    state = get_job(job_id)
    assert state is not None
    assert state.status == "cancelled"


# ---------------------------------------------------------------------------
# poll_job
# ---------------------------------------------------------------------------


def test_poll_running_job() -> None:
    job_id = create_job()
    out = poll_job(job_id)
    assert out["job_id"] == job_id
    assert out["status"] == "running"
    assert out["elapsed_ms"] >= 0
    assert out["return_value"] is None
    assert out["error"] is None


def test_poll_done_job_includes_result() -> None:
    job_id = create_job()
    mark_done(job_id, {"return_value": "42", "messages": ["ok"], "duration_ms": 500})
    out = poll_job(job_id)
    assert out["status"] == "done"
    assert out["return_value"] == "42"
    assert out["messages"] == ["ok"]
    assert out["duration_ms"] == 500


def test_poll_unknown_job_raises() -> None:
    with pytest.raises(InvalidInputError, match="JOB_NOT_FOUND"):
        poll_job("does-not-exist")
