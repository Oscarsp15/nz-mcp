"""Unit tests for catalog probe (faked driver)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nz_mcp.catalog.probe import (
    dummy_params_for_query_id,
    prepare_sql,
    probe_has_hard_failure,
    probe_one_row,
    probe_run_to_json_dict,
    run_probe_catalog,
)
from nz_mcp.catalog.queries import ALL_QUERIES
from nz_mcp.config import Profile


def _profile(**overrides: Any) -> Profile:
    data: dict[str, Any] = {
        "name": "t",
        "host": "localhost",
        "port": 5480,
        "database": "MYDB",
        "user": "u",
        "mode": "read",
    }
    data.update(overrides)
    return Profile.model_validate(data)


def test_dummy_params_cover_defaults_and_match_placeholder_count() -> None:
    for cq in ALL_QUERIES:
        params = dummy_params_for_query_id(cq.id)
        assert cq.sql.count("?") == len(params), cq.id


def test_prepare_sql_with_override() -> None:
    prof = _profile(catalog_overrides={"list_databases": "SELECT 1 WHERE ? = ?"})
    sql = prepare_sql(prof, ALL_QUERIES[0])
    assert sql == "SELECT 1 WHERE ? = ?"


def test_placeholder_mismatch_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _profile(catalog_overrides={"list_databases": "SELECT 1"})
    monkeypatch.setattr("nz_mcp.catalog.probe.get_password", lambda _n: "pw")

    class Cursor:
        def execute(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("should not execute")

        def fetchall(self) -> list[Any]:
            return []

        def close(self) -> None:
            pass

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.probe.open_connection", lambda _p, _pw: Conn())
    run = run_probe_catalog(prof)
    assert run.config_error is None
    first = run.results[0]
    assert first.query_id == "list_databases"
    assert first.status == "failure"
    assert first.detail is not None
    assert "Placeholder count mismatch" in first.detail


def test_run_probe_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _profile()
    monkeypatch.setattr("nz_mcp.catalog.probe.get_password", lambda _n: "pw")

    class Cursor:
        def execute(self, *_a: Any, **_k: Any) -> None:
            return None

        def fetchall(self) -> list[tuple[str, str]]:
            return [("a", "b")]

        def close(self) -> None:
            pass

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.probe.open_connection", lambda _p, _pw: Conn())
    run = run_probe_catalog(prof)
    assert run.config_error is None
    assert len(run.results) == len(ALL_QUERIES)
    assert all(r.status == "ok" for r in run.results)
    assert not probe_has_hard_failure(run)


def test_driver_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _profile()
    monkeypatch.setattr("nz_mcp.catalog.probe.get_password", lambda _n: "pw")
    calls: list[int] = []

    class Cursor:
        def execute(self, *_a: Any, **_k: Any) -> None:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("forced driver error")

        def fetchall(self) -> list[Any]:
            return []

        def close(self) -> None:
            pass

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.probe.open_connection", lambda _p, _pw: Conn())
    run = run_probe_catalog(prof)
    assert run.results[1].status == "failure"
    assert "forced driver error" in (run.results[1].error_detail or "")
    assert probe_has_hard_failure(run)


def test_structural_warning_not_hard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    prof = _profile()
    monkeypatch.setattr("nz_mcp.catalog.probe.get_password", lambda _n: "pw")
    n = 0

    class Cursor:
        def execute(self, *_a: Any, **_k: Any) -> None:
            nonlocal n
            n += 1
            if n == 5:
                raise RuntimeError("ERROR: Table __NZ_MCP_PROBE_DUMMY__ does not exist")

        def fetchall(self) -> list[Any]:
            return []

        def close(self) -> None:
            pass

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    monkeypatch.setattr("nz_mcp.catalog.probe.open_connection", lambda _p, _pw: Conn())
    run = run_probe_catalog(prof)
    gv = next(r for r in run.results if r.query_id == "get_view_ddl")
    assert gv.status == "structural_warning"
    assert not probe_has_hard_failure(run)


def test_invalid_catalog_overrides_rejected() -> None:
    prof = _profile(catalog_overrides={"not_a_real_id": "SELECT 1"})
    run = run_probe_catalog(prof)
    assert run.config_error is not None
    assert "Unknown catalog_overrides query ids" in run.config_error
    assert run.results == ()
    assert probe_has_hard_failure(run)


def test_json_shape() -> None:
    from nz_mcp.catalog.probe import ProbeResult, ProbeRun

    run = ProbeRun(
        profile_name="x",
        config_error=None,
        results=(
            ProbeResult(
                query_id="list_databases",
                status="ok",
                duration_ms=1.0,
                row_count=2,
                error_detail=None,
                detail=None,
            ),
        ),
    )
    raw = json.dumps(probe_run_to_json_dict(run))
    data = json.loads(raw)
    assert data["profile"] == "x"
    assert data["config_error"] is None
    assert data["results"][0]["query_id"] == "list_databases"
    assert data["results"][0]["status"] == "ok"


def test_probe_one_row_direct() -> None:
    prof = _profile()

    class Cursor:
        def execute(self, *_a: Any, **_k: Any) -> None:
            return None

        def fetchall(self) -> list[tuple[int]]:
            return [(1,)]

    cq = ALL_QUERIES[0]
    row = probe_one_row(Cursor(), prof, cq, password="unit-test-password")  # noqa: S106
    assert row.status == "ok"
    assert row.row_count == 1
