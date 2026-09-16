"""Unit tests for cancel_job / nz_job_cancel."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nz_mcp.catalog.call_async import cancel_job
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError
from nz_mcp.jobs import (
    _reset_for_tests,
    create_job,
    get_job,
    mark_cancelling,
    mark_done,
    mark_failed,
    set_session_id,
)


def _profile() -> Profile:
    return Profile(name="p", host="h", port=5480, database="DESA_MODELOS", user="u", mode="admin")


@pytest.fixture(autouse=True)
def clean_jobs() -> None:
    _reset_for_tests()


# ---------------------------------------------------------------------------
# cancel_job — error paths
# ---------------------------------------------------------------------------


def test_cancel_unknown_job_raises() -> None:
    with pytest.raises(InvalidInputError, match="JOB_NOT_FOUND"):
        cancel_job("does-not-exist", profile=_profile(), password="pw")


def test_cancel_job_without_session_id_raises() -> None:
    job_id = create_job()
    # session_id is None by default
    with pytest.raises(InvalidInputError, match="CANCEL_UNAVAILABLE"):
        cancel_job(job_id, profile=_profile(), password="pw")


def test_cancel_already_done_job_returns_already_done() -> None:
    job_id = create_job()
    set_session_id(job_id, 42)
    mark_done(job_id, {"return_value": None, "messages": [], "duration_ms": 10})
    result = cancel_job(job_id, profile=_profile(), password="pw")
    assert result["status"] == "already_done"
    assert result["previous_status"] == "done"


def test_cancel_already_failed_job_returns_already_done() -> None:
    job_id = create_job()
    set_session_id(job_id, 42)
    mark_failed(job_id, code="NETEZZA_ERROR", detail="boom", partial_notices=[])
    result = cancel_job(job_id, profile=_profile(), password="pw")
    assert result["status"] == "already_done"
    assert result["previous_status"] == "failed"


def test_cancel_already_cancelling_returns_already_done() -> None:
    job_id = create_job()
    set_session_id(job_id, 42)
    mark_cancelling(job_id)
    result = cancel_job(job_id, profile=_profile(), password="pw")
    assert result["status"] == "already_done"
    assert result["previous_status"] == "cancelling"


# ---------------------------------------------------------------------------
# cancel_job — happy path (ABORT SESSION succeeds)
# ---------------------------------------------------------------------------


def test_cancel_running_job_sends_abort_session() -> None:
    job_id = create_job()
    set_session_id(job_id, 99)

    executed: list[str] = []

    def _fake_open(profile: Any, password: str, **_kw: Any) -> Any:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute = executed.append
        conn.cursor.return_value = cursor
        return conn

    with patch("nz_mcp.catalog.call_async.open_connection", side_effect=_fake_open):
        result = cancel_job(job_id, profile=_profile(), password="pw")

    assert result["status"] == "cancelling"
    assert result["session_id"] == 99
    assert result["abort_error"] is None
    assert any("ABORT SESSION 99" in s for s in executed)
    assert get_job(job_id).status == "cancelling"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# cancel_job — ABORT SESSION fails (permission denied)
# ---------------------------------------------------------------------------


def test_cancel_abort_failure_returns_cancelling_with_abort_error() -> None:
    job_id = create_job()
    set_session_id(job_id, 77)

    def _error_open(profile: Any, password: str, **_kw: Any) -> Any:
        raise OSError("permission denied on ABORT SESSION")

    with patch("nz_mcp.catalog.call_async.open_connection", side_effect=_error_open):
        result = cancel_job(job_id, profile=_profile(), password="pw")

    assert result["status"] == "cancelling"
    assert result["abort_error"] is not None
    assert "permission denied" in result["abort_error"]
    assert result["session_id"] == 77


# ---------------------------------------------------------------------------
# nz_job_cancel tool — confirm guard
# ---------------------------------------------------------------------------


def test_tool_cancel_requires_confirm() -> None:
    from nz_mcp.tools.call_async import JobCancelInput, nz_job_cancel

    params = JobCancelInput(job_id="any", confirm=False)
    with pytest.raises(InvalidInputError, match="CONFIRM_REQUIRED"):
        nz_job_cancel(params)


def test_tool_cancel_confirm_true_calls_cancel_job() -> None:
    from nz_mcp.tools.call_async import JobCancelInput, nz_job_cancel

    job_id = create_job()
    set_session_id(job_id, 55)

    def _fake_open(profile: Any, password: str, **_kw: Any) -> Any:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute = MagicMock()
        conn.cursor.return_value = cursor
        return conn

    with (
        patch("nz_mcp.catalog.call_async.open_connection", side_effect=_fake_open),
        patch("nz_mcp.tools.call_async.get_password", return_value="pw"),
        patch(
            "nz_mcp.tools.call_async.get_active_profile",
            return_value=_profile(),
        ),
    ):
        params = JobCancelInput(job_id=job_id, confirm=True)
        output = nz_job_cancel(params)

    assert output.status == "cancelling"
    assert output.session_id == 55
