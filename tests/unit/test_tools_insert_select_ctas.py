"""Tests for nz_insert_select and nz_create_table_as (issue #85)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.catalog.ddl import execute_create_table_as
from nz_mcp.catalog.write import execute_insert_select
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidInputError
from nz_mcp.server import call_tool
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate


def _admin_profile() -> Profile:
    return Profile(
        name="a",
        host="h",
        port=5480,
        database="DEV",
        user="u",
        mode="admin",
        max_rows_default=100,
        timeout_s_default=30,
    )


def _write_profile() -> Profile:
    return Profile(
        name="w",
        host="h",
        port=5480,
        database="DEV",
        user="u",
        mode="write",
        max_rows_default=100,
        timeout_s_default=30,
    )


def test_insert_select_dry_run_returns_sql_no_execute() -> None:
    p = _write_profile()
    out = execute_insert_select(
        p,
        database="DEV",
        schema="PUBLIC",
        table="TGT",
        select_sql="SELECT 1 AS A",
        target_columns=None,
        dry_run=True,
        confirm=False,
        estimate_rows=False,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert out["would_insert"] is None
    assert "INSERT INTO PUBLIC.TGT SELECT 1 AS A" in out["sql_to_execute"].replace("\n", " ")
    assert out["duration_ms"] == 0


def test_insert_select_rejects_non_select() -> None:
    p = _write_profile()
    with pytest.raises(GuardRejectedError) as exc:
        execute_insert_select(
            p,
            database="DEV",
            schema="PUBLIC",
            table="TGT",
            select_sql="DELETE FROM PUBLIC.X WHERE 1=1",
            target_columns=None,
            dry_run=True,
            confirm=False,
        )
    assert exc.value.code == "WRONG_STATEMENT_FOR_TOOL"


def test_insert_select_rejects_stacked() -> None:
    p = _write_profile()
    with pytest.raises(GuardRejectedError):
        execute_insert_select(
            p,
            database="DEV",
            schema="PUBLIC",
            table="TGT",
            select_sql="SELECT 1; SELECT 2",
            target_columns=None,
            dry_run=True,
            confirm=False,
        )


def test_insert_select_with_union_all_happy_path() -> None:
    p = _write_profile()
    out = execute_insert_select(
        p,
        database="DEV",
        schema="PUBLIC",
        table="CFG",
        select_sql="SELECT 'a', 1 UNION ALL SELECT 'b', 2",
        target_columns=["K", "V"],
        dry_run=True,
        confirm=False,
    )
    assert "UNION ALL" in out["sql_to_execute"]
    assert "INSERT INTO PUBLIC.CFG (K, V)" in out["sql_to_execute"]


def test_insert_select_confirm_required() -> None:
    p = _write_profile()
    with pytest.raises(InvalidInputError) as exc:
        execute_insert_select(
            p,
            database="DEV",
            schema="PUBLIC",
            table="TGT",
            select_sql="SELECT 1",
            target_columns=None,
            dry_run=False,
            confirm=False,
        )
    assert exc.value.code == "CONFIRM_REQUIRED"


def test_insert_select_with_target_columns() -> None:
    p = _write_profile()
    out = execute_insert_select(
        p,
        database="DEV",
        schema="S",
        table="T",
        select_sql="SELECT col1, col2 FROM S.OTHER",
        target_columns=["A", "B"],
        dry_run=True,
        confirm=False,
    )
    assert "INSERT INTO S.T (A, B)" in out["sql_to_execute"]


def test_insert_select_star_warning() -> None:
    p = _write_profile()
    out = execute_insert_select(
        p,
        database="DEV",
        schema="PUBLIC",
        table="TGT",
        select_sql="SELECT * FROM PUBLIC.SRC",
        target_columns=None,
        dry_run=True,
        confirm=False,
    )
    assert len(out["warnings"]) == 1
    assert "target_columns" in out["warnings"][0]


def test_ctas_dry_run_returns_ddl_no_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: False)
    out = execute_create_table_as(
        p,
        database="DEV",
        schema="PUBLIC",
        table="NEW_T",
        select_sql="SELECT 1 AS X",
        distribution=None,
        organized_on=None,
        dry_run=True,
        confirm=False,
        estimate_rows=False,
    )
    assert out["dry_run"] is True
    assert out["executed"] is False
    assert "CREATE TABLE PUBLIC.NEW_T AS" in out["ddl_to_execute"]
    assert "DISTRIBUTE ON RANDOM" in out["ddl_to_execute"]
    assert out["would_create_rows"] is None


def test_ctas_hash_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: False)
    out = execute_create_table_as(
        p,
        database="DEV",
        schema="PUBLIC",
        table="H",
        select_sql="SELECT KEYREGLA FROM PUBLIC.SRC",
        distribution={"type": "HASH", "columns": ["KEYREGLA"]},
        organized_on=None,
        dry_run=True,
        confirm=False,
    )
    assert "DISTRIBUTE ON HASH (KEYREGLA)" in out["ddl_to_execute"]


def test_ctas_random_default_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: False)
    out = execute_create_table_as(
        p,
        database="DEV",
        schema="PUBLIC",
        table="R",
        select_sql="SELECT 1",
        distribution=None,
        organized_on=None,
        dry_run=True,
        confirm=False,
    )
    assert "DISTRIBUTE ON RANDOM" in out["ddl_to_execute"]


def test_ctas_union_all_select(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: False)
    out = execute_create_table_as(
        p,
        database="DEV",
        schema="PUBLIC",
        table="U",
        select_sql="SELECT 1 AS A UNION ALL SELECT 2 AS A",
        distribution=None,
        organized_on=None,
        dry_run=True,
        confirm=False,
    )
    assert "UNION ALL" in out["ddl_to_execute"]


def test_ctas_target_already_exists_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: True)
    with pytest.raises(InvalidInputError) as exc:
        execute_create_table_as(
            p,
            database="DEV",
            schema="PUBLIC",
            table="EXISTS",
            select_sql="SELECT 1",
            distribution=None,
            organized_on=None,
            dry_run=True,
            confirm=False,
        )
    assert "already exists" in str(exc.value).lower()


def test_ctas_confirm_required(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _admin_profile()
    monkeypatch.setattr("nz_mcp.catalog.ddl.table_exists", lambda *_a, **_k: False)
    with pytest.raises(InvalidInputError) as exc:
        execute_create_table_as(
            p,
            database="DEV",
            schema="PUBLIC",
            table="X",
            select_sql="SELECT 1",
            distribution=None,
            organized_on=None,
            dry_run=False,
            confirm=False,
        )
    assert exc.value.code == "CONFIRM_REQUIRED"


def test_sql_guard_accepts_create_table_as_select() -> None:
    sql = "CREATE TABLE dbo.t AS\nSELECT a, b FROM dbo.u WHERE x = 1"
    parsed = guard_validate(sql, mode="admin")
    assert parsed.kind is StatementKind.CREATE


def test_nz_insert_select_permission_read_profile(two_profiles: Path) -> None:
    out = call_tool(
        "nz_insert_select",
        {
            "database": "DEV",
            "target_schema": "PUBLIC",
            "target_table": "T",
            "select_sql": "SELECT 1",
        },
        config_path=two_profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"
