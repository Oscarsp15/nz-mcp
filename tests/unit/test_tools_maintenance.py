"""Unit tests for the ``nz_maintenance`` catalog helper and tool handler."""

from __future__ import annotations

from typing import Any

import pytest

from nz_mcp.catalog.maintenance import execute_maintenance
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.sql_guard import ParsedStatement, StatementKind


def _admin_profile(*, database: str = "DEV") -> Profile:
    return Profile(name="a", host="h", port=5480, database=database, user="u", mode="admin")


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append(sql)

    def close(self) -> None:
        pass


class _RecordingConn:
    def __init__(self) -> None:
        self.cursor_obj = _RecordingCursor()

    def cursor(self) -> _RecordingCursor:
        return self.cursor_obj

    def close(self) -> None:
        pass


class _BoomCursor:
    def execute(self, *_a: object, **_k: object) -> None:
        raise RuntimeError("nz oops")

    def close(self) -> None:
        pass


class _BoomConn:
    def cursor(self) -> _BoomCursor:
        return _BoomCursor()

    def close(self) -> None:
        pass


def _execute(
    profile: Profile,
    *,
    action: str = "generate_statistics",
    database: str | None = None,
    schema: str = "PUBLIC",
    table: str = "T",
    dry_run: bool = True,
    confirm: bool = False,
    echo_sql: bool = True,
) -> dict[str, Any]:
    return execute_maintenance(
        profile,
        database=database or profile.database,
        schema=schema,
        table=table,
        action=action,
        dry_run=dry_run,
        confirm=confirm,
        echo_sql=echo_sql,
    )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("generate_statistics", "GENERATE STATISTICS ON PUBLIC.T"),
        ("groom", "GROOM TABLE PUBLIC.T"),
        ("vacuum", "VACUUM PUBLIC.T"),
    ],
)
def test_dry_run_builds_one_statement_without_opening_a_connection(
    monkeypatch: pytest.MonkeyPatch, action: str, expected: str
) -> None:
    opened: list[object] = []

    def _open(*_a: object) -> None:
        opened.append(True)

    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", _open)
    monkeypatch.setattr("nz_mcp.catalog.maintenance.get_password", lambda _n: "pw")

    out = _execute(_admin_profile(), action=action)

    assert out["action"] == action
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert out["statements_executed"] == 0
    assert out["statements_to_execute"] == [expected]
    assert opened == []


def test_unknown_action_rejected_before_building_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", lambda *_a: _RecordingConn())

    with pytest.raises(InvalidInputError) as ei:
        _execute(_admin_profile(), action="drop_table")

    assert ei.value.code == "INVALID_MAINTENANCE_ACTION"


def test_database_must_match_active_profile() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(database="DEV"), database="OTHER")


def test_invalid_identifier_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), table="T; DROP TABLE X")


def test_real_execution_requires_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", lambda *_a: _RecordingConn())
    monkeypatch.setattr("nz_mcp.catalog.maintenance.get_password", lambda _n: "pw")

    with pytest.raises(InvalidInputError) as ei:
        _execute(_admin_profile(), dry_run=False, confirm=False)

    assert ei.value.code == "CONFIRM_REQUIRED"


def test_real_execution_runs_one_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingConn()
    opened: list[object] = []

    def _open(_p: object, _w: object) -> _RecordingConn:
        opened.append(fake)
        return fake

    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", _open)
    monkeypatch.setattr("nz_mcp.catalog.maintenance.get_password", lambda _n: "pw")

    out = _execute(_admin_profile(), action="groom", dry_run=False, confirm=True)

    assert out["executed"] is True
    assert out["dry_run"] is False
    assert out["statements_executed"] == 1
    assert out["statements_to_execute"] == ["GROOM TABLE PUBLIC.T"]
    assert fake.cursor_obj.executed == ["GROOM TABLE PUBLIC.T"]
    assert len(opened) == 1


def test_real_execution_echo_sql_false_omits_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", lambda *_a: _RecordingConn())
    monkeypatch.setattr("nz_mcp.catalog.maintenance.get_password", lambda _n: "pw")

    out = _execute(_admin_profile(), dry_run=False, confirm=True, echo_sql=False)

    assert out["executed"] is True
    assert out["statements_to_execute"] is None


def test_execution_failure_wrapped_as_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.maintenance.open_connection", lambda *_a: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.maintenance.get_password", lambda _n: "pw")

    with pytest.raises(NetezzaError):
        _execute(_admin_profile(), dry_run=False, confirm=True)


def test_guard_non_maintenance_kind_raises_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.maintenance.guard_validate",
        lambda *_a, **_k: ParsedStatement(
            kind=StatementKind.SELECT,
            has_where=False,
            raw="SELECT 1",
        ),
    )

    with pytest.raises(NetezzaError):
        _execute(_admin_profile())


def test_tool_handler_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.maintenance import MaintenanceInput, MaintenanceOutput, nz_maintenance

    monkeypatch.setattr(
        "nz_mcp.tools.maintenance.get_active_profile", lambda **_k: _admin_profile()
    )

    out = nz_maintenance(
        MaintenanceInput(
            database="DEV",
            schema="PUBLIC",
            table="T",
            action="groom",
        ),
    )

    assert isinstance(out, MaintenanceOutput)
    assert out.action == "groom"
    assert out.dry_run is True
    assert out.executed is False
    assert out.statements_to_execute == ["GROOM TABLE PUBLIC.T"]
