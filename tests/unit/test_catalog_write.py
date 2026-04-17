"""Unit tests for catalog write helpers (mocked DB)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nz_mcp.catalog.write import _run_scalar_count, execute_delete, execute_insert, execute_update
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError
from nz_mcp.sql_guard import validate as guard_validate

_PROFILE = Profile(
    name="dev",
    host="h",
    port=5480,
    database="DEV",
    user="u",
    mode="write",
)


def _mock_conn(cursor: MagicMock) -> MagicMock:
    """``closing(connection.cursor())`` expects the cursor object directly."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def test_execute_insert_empty_rows() -> None:
    with pytest.raises(InvalidInputError):
        execute_insert(_PROFILE, "DEV", "PUBLIC", "T", [], on_conflict="error")


def test_execute_insert_too_many_rows() -> None:
    rows = [{"A": 1} for _ in range(501)]
    with pytest.raises(InvalidInputError):
        execute_insert(_PROFILE, "DEV", "PUBLIC", "T", rows, on_conflict="error")


def test_execute_insert_on_conflict_invalid() -> None:
    with pytest.raises(InvalidInputError):
        execute_insert(_PROFILE, "DEV", "PUBLIC", "T", [{"A": 1}], on_conflict="bogus")


def test_execute_insert_row_key_mismatch() -> None:
    with pytest.raises(InvalidInputError):
        execute_insert(
            _PROFILE,
            "DEV",
            "PUBLIC",
            "T",
            [{"A": 1}, {"A": 1, "B": 2}],
            on_conflict="error",
        )


def test_execute_insert_batch_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    rows = [{"A": 1, "B": 2}]
    out = execute_insert(_PROFILE, "DEV", "PUBLIC", "TAB", rows, on_conflict="error")
    assert out["inserted"] == 1
    cursor.execute.assert_called_once()
    assert "INSERT INTO PUBLIC.TAB" in cursor.execute.call_args[0][0]


def test_execute_update_dry_run_count(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = (5,)
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    out = execute_update(
        _PROFILE,
        "DEV",
        "PUBLIC",
        "TAB",
        {"X": 1},
        "ID = 1",
        dry_run=True,
        confirm=False,
    )
    assert out["dry_run"] is True
    assert out["would_update"] == 5
    assert "COUNT" in cursor.execute.call_args[0][0]


def test_execute_update_confirm_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    with pytest.raises(InvalidInputError) as ei:
        execute_update(
            _PROFILE,
            "DEV",
            "PUBLIC",
            "TAB",
            {"X": 1},
            "ID = 1",
            dry_run=False,
            confirm=False,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_execute_delete_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = (3,)
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    out = execute_delete(
        _PROFILE,
        "DEV",
        "PUBLIC",
        "TAB",
        "ID = 1",
        dry_run=True,
        confirm=False,
    )
    assert out["would_delete"] == 3


def test_database_mismatch() -> None:
    with pytest.raises(InvalidInputError):
        execute_insert(
            _PROFILE,
            "OTHER",
            "PUBLIC",
            "T",
            [{"A": 1}],
            on_conflict="error",
        )


def test_guard_rejects_update_without_where() -> None:
    with pytest.raises(GuardRejectedError) as ge:
        guard_validate("UPDATE PUBLIC.T SET X=1", mode="write")
    assert ge.value.code == "UPDATE_REQUIRES_WHERE"


def test_guard_rejects_delete_without_where() -> None:
    with pytest.raises(GuardRejectedError) as ge:
        guard_validate("DELETE FROM PUBLIC.T", mode="write")
    assert ge.value.code == "DELETE_REQUIRES_WHERE"


def test_execute_update_real_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.rowcount = 7
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    out = execute_update(
        _PROFILE,
        "DEV",
        "PUBLIC",
        "TAB",
        {"X": 1},
        "ID = 1",
        dry_run=False,
        confirm=True,
    )
    assert out["dry_run"] is False
    assert out["updated"] == 7


def test_execute_delete_real_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.rowcount = 2
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    out = execute_delete(
        _PROFILE,
        "DEV",
        "PUBLIC",
        "TAB",
        "ID = 1",
        dry_run=False,
        confirm=True,
    )
    assert out["dry_run"] is False
    assert out["deleted"] == 2


def test_run_scalar_count_dict_row(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"C": 42}
    conn = _mock_conn(cursor)
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    n = _run_scalar_count(_PROFILE, "pw", "SELECT 1", ())
    assert n == 42


def test_execute_insert_skip_ignores_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = MagicMock()
    conn = _mock_conn(cursor)

    def _exec(sql: str, params: tuple[Any, ...] | None = None) -> None:
        if "INSERT" in sql and params and params[0] == 2:
            msg = "duplicate key value violates unique constraint"
            raise OSError(msg)

    cursor.execute.side_effect = _exec

    monkeypatch.setattr("nz_mcp.catalog.write.get_password", lambda _n: "pw")
    monkeypatch.setattr("nz_mcp.catalog.write.open_connection", lambda *_a, **_k: conn)
    rows = [{"A": 1}, {"A": 2}]
    out = execute_insert(_PROFILE, "DEV", "PUBLIC", "TAB", rows, on_conflict="skip")
    assert out["inserted"] == 1
