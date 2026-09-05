"""Tests for the three-level profile validation ladder."""

from __future__ import annotations

from typing import Any

import pytest

from nz_mcp.config import Profile
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.profile_check import run_checks

_BASE_PROFILE: dict[str, Any] = {
    "name": "dev",
    "host": "nz.example.com",
    "port": 5480,
    "database": "DB",
    "user": "svc",
    "mode": "read",
}

_DEFAULT_ROWS: dict[str, list[tuple[str, str]]] = {
    "databases": [("DB", "ADMIN"), ("OTHER", "ADMIN")],
    "schemas": [("DBO", "ADMIN")],
}


def _profile(**overrides: Any) -> Profile:
    fields = dict(_BASE_PROFILE)
    fields.update(overrides)
    return Profile(**fields)


def _kind(sql: str) -> str:
    upper = sql.upper()
    if "VERSION()" in upper:
        return "version"
    if "_V_DATABASE" in upper:
        return "databases"
    return "schemas"


class _FakeCursor:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self._kind = "version"

    def execute(self, sql: str, params: tuple[str | None, str | None] | None = None) -> None:
        self._kind = _kind(sql)
        boom = self._conn.errors.get(self._kind)
        if boom is not None:
            raise RuntimeError(boom)

    def fetchone(self) -> tuple[str]:
        return (self._conn.version,)

    def fetchall(self) -> list[tuple[str, str]]:
        return self._conn.rows.get(self._kind, [])

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(
        self,
        *,
        version: str = "NPS 11.2.1.11",
        rows: dict[str, list[tuple[str, str]]] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self.version = version
        self.rows = _DEFAULT_ROWS if rows is None else rows
        self.errors = {} if errors is None else errors
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _patch_open(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn) -> None:
    monkeypatch.setattr("nz_mcp.profile_check.open_connection", lambda _p, _w: conn)


def test_all_three_levels_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    _patch_open(monkeypatch, conn)
    report = run_checks(_profile(), "pw")
    assert report.ok is True
    assert [o.status for o in report.outcomes] == ["ok", "ok", "ok"]
    assert report.outcomes[0].detail == "NPS 11.2.1.11"
    assert report.outcomes[1].count == 2
    assert report.outcomes[2].count == 1
    assert conn.closed is True


def test_connect_failure_skips_the_other_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_p: object, _w: str) -> None:
        raise NzConnectionError(host="h", port=1, database="d", user="u", detail="timeout")

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _boom)
    report = run_checks(_profile(), "pw")
    assert report.ok is False
    assert [o.status for o in report.outcomes] == ["failed", "skipped", "skipped"]
    failure = report.failure
    assert failure is not None
    assert failure.level == "connect"
    assert failure.detail == "timeout"


def test_version_query_failure_is_a_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn(errors={"version": "driver said no"}))
    report = run_checks(_profile(), "pw")
    assert report.outcomes[0].status == "failed"
    assert "driver said no" in report.outcomes[0].detail


def test_failure_detail_never_leaks_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn(errors={"databases": "auth failed pw=UltraSecret999"}))
    report = run_checks(_profile(), "UltraSecret999")
    assert "UltraSecret999" not in report.outcomes[1].detail


def test_catalog_error_skips_the_default_database_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn(errors={"databases": "no permission on _v_database"}))
    report = run_checks(_profile(), "pw")
    assert [o.status for o in report.outcomes] == ["ok", "failed", "skipped"]
    failure = report.failure
    assert failure is not None
    assert failure.level == "catalog_read"


def test_catalog_read_without_rows_is_reported_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn(rows={"databases": [], "schemas": []}))
    report = run_checks(_profile(), "pw")
    assert [o.status for o in report.outcomes] == ["ok", "empty", "skipped"]
    assert report.ok is False


def test_default_database_without_schemas_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn(rows={"databases": [("DB", "ADMIN")], "schemas": []}))
    report = run_checks(_profile(), "pw")
    assert [o.status for o in report.outcomes] == ["ok", "ok", "empty"]
    failure = report.failure
    assert failure is not None
    assert failure.level == "default_database"


def test_levels_one_runs_only_the_connection_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open(monkeypatch, _FakeConn())
    report = run_checks(_profile(), "pw", levels=1)
    assert len(report.outcomes) == 1
    assert report.outcomes[0].level == "connect"
    assert report.ok is True


def test_unusable_database_name_fails_at_the_catalog_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_open(monkeypatch, _FakeConn())
    report = run_checks(_profile(database="not a name"), "pw")
    assert [o.status for o in report.outcomes] == ["ok", "failed", "skipped"]
    assert "INVALID_DATABASE_NAME" in report.outcomes[1].detail
