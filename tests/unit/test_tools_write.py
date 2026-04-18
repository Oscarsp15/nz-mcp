"""Tests for write MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.server import call_tool
from nz_mcp.tools.write import (
    DeleteInput,
    InsertInput,
    UpdateInput,
    nz_delete,
    nz_insert,
    nz_update,
)


def test_nz_insert_permission_denied_read_profile(two_profiles: Path) -> None:
    out = call_tool(
        "nz_insert",
        {
            "database": "DEV",
            "schema": "PUBLIC",
            "table": "T",
            "rows": [{"A": 1}],
        },
        config_path=two_profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_nz_insert_happy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)

    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_insert",
        lambda *_a, **_k: {"inserted": 2, "duration_ms": 10, "dry_run": False},
    )
    out = nz_insert(
        InsertInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            rows=[{"A": 1}, {"A": 2}],
            dry_run=False,
            confirm=True,
        ),
        config_path=profiles,
    )
    assert out.inserted == 2
    assert out.dry_run is False


def test_nz_insert_dry_run_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_insert",
        lambda *_a, **_k: {
            "inserted": 0,
            "would_insert": 3,
            "dry_run": True,
            "confirm_required": True,
            "duration_ms": 0,
        },
    )
    out = nz_insert(
        InsertInput(database="DEV", table_schema="PUBLIC", table="T", rows=[{"A": 1}]),
        config_path=profiles,
    )
    assert out.dry_run is True
    assert out.would_insert == 3


def test_nz_update_output_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_update",
        lambda *_a, **_k: {
            "updated": 0,
            "would_update": 4,
            "dry_run": True,
            "confirm_required": True,
            "duration_ms": 5,
        },
    )
    out = nz_update(
        UpdateInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            set={"X": 1},
            where="ID > 0",
        ),
        config_path=profiles,
    )
    assert out.dry_run is True
    assert out.would_update == 4


def test_nz_delete_dry_run_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n'
        "max_rows_default = 100\ntimeout_s_default = 30\n",
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_delete",
        lambda *_a, **_k: {
            "deleted": 0,
            "would_delete": 9,
            "dry_run": True,
            "confirm_required": True,
            "duration_ms": 2,
        },
    )
    out = nz_delete(
        DeleteInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            where="ID = 1",
        ),
        config_path=profiles,
    )
    assert out.would_delete == 9
    assert out.dry_run is True


def test_nz_update_applies_when_confirmed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n'
        "max_rows_default = 100\ntimeout_s_default = 30\n",
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_update",
        lambda *_a, **_k: {"updated": 3, "dry_run": False, "duration_ms": 8},
    )
    out = nz_update(
        UpdateInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            set={"X": 1},
            where="ID = 1",
            dry_run=False,
            confirm=True,
        ),
        config_path=profiles,
    )
    assert out.updated == 3
    assert out.dry_run is False


def test_delete_input_strips_where() -> None:
    d = DeleteInput(
        database="DEV",
        table_schema="PUBLIC",
        table="T",
        where="  ID = 2  ",
    )
    assert d.where == "ID = 2"


def test_update_input_strips_where() -> None:
    u = UpdateInput(
        database="DEV",
        table_schema="PUBLIC",
        table="T",
        set={"X": 1},
        where="  ID = 1  ",
    )
    assert u.where == "ID = 1"


def test_nz_delete_applies_when_confirmed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "w"\n[profiles.w]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="write"\n'
        "max_rows_default = 100\ntimeout_s_default = 30\n",
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.write.execute_delete",
        lambda *_a, **_k: {"deleted": 4, "dry_run": False, "duration_ms": 1},
    )
    out = nz_delete(
        DeleteInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            where="ID = 1",
            dry_run=False,
            confirm=True,
        ),
        config_path=profiles,
    )
    assert out.deleted == 4
    assert out.dry_run is False
