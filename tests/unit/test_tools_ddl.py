"""Tests for DDL MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.server import call_tool
from nz_mcp.tools.ddl import (
    ColumnDef,
    CreateTableInput,
    DropTableInput,
    TruncateInput,
    nz_create_table,
    nz_drop_table,
    nz_truncate,
)


def test_nz_create_table_permission_denied_read_profile(two_profiles: Path) -> None:
    out = call_tool(
        "nz_create_table",
        {
            "database": "DEV",
            "schema": "PUBLIC",
            "table": "T",
            "columns": [{"name": "ID", "type": "INTEGER"}],
        },
        config_path=two_profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_nz_create_table_permission_denied_write_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    out = call_tool(
        "nz_create_table",
        {
            "database": "DEV",
            "schema": "PUBLIC",
            "table": "T",
            "columns": [{"name": "ID", "type": "INTEGER"}],
        },
        config_path=profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_nz_truncate_permission_denied_write_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    out = call_tool(
        "nz_truncate",
        {"database": "DEV", "schema": "PUBLIC", "table": "T", "confirm": True},
        config_path=profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_nz_truncate_confirm_false_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)

    from nz_mcp.errors import InvalidInputError

    with pytest.raises(InvalidInputError) as ei:
        nz_truncate(
            TruncateInput(
                database="DEV",
                table_schema="PUBLIC",
                table="T",
                confirm=False,
            ),
            config_path=profiles,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_nz_create_table_happy_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.ddl.execute_create_table",
        lambda *_a, **_k: {
            "dry_run": False,
            "ddl_to_execute": "CREATE TABLE PUBLIC.X (ID INTEGER)\nDISTRIBUTE ON RANDOM",
            "executed": True,
            "duration_ms": 5,
        },
    )
    out = nz_create_table(
        CreateTableInput(
            database="DEV",
            table_schema="PUBLIC",
            table="X",
            columns=[ColumnDef(name="ID", type="INTEGER")],
            dry_run=False,
            confirm=True,
        ),
        config_path=profiles,
    )
    assert out.executed is True
    assert out.dry_run is False
    assert out.duration_ms == 5
    assert "DISTRIBUTE ON RANDOM" in out.ddl_to_execute


def test_nz_create_table_dry_run_skips_execute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    calls: list[bool] = []

    def _stub(*_a: object, **kw: object) -> dict[str, object]:
        dr = kw.get("dry_run", True)
        calls.append(bool(dr))
        return {
            "dry_run": True,
            "ddl_to_execute": "CREATE ...",
            "executed": False,
            "duration_ms": 0,
        }

    monkeypatch.setattr("nz_mcp.tools.ddl.execute_create_table", _stub)
    out = nz_create_table(
        CreateTableInput(
            database="DEV",
            table_schema="PUBLIC",
            table="Y",
            columns=[ColumnDef(name="ID", type="INTEGER")],
        ),
        config_path=profiles,
    )
    assert out.dry_run is True
    assert out.executed is False
    assert calls == [True]


def test_nz_create_table_confirm_required_when_dry_run_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)

    from nz_mcp.errors import InvalidInputError

    with pytest.raises(InvalidInputError) as ei:
        nz_create_table(
            CreateTableInput(
                database="DEV",
                table_schema="PUBLIC",
                table="Z",
                columns=[ColumnDef(name="ID", type="INTEGER")],
                dry_run=False,
                confirm=False,
            ),
            config_path=profiles,
        )
    assert ei.value.code == "CONFIRM_REQUIRED"


def test_nz_truncate_happy_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.ddl.execute_truncate",
        lambda *_a, **_k: {"truncated": True, "duration_ms": 3},
    )
    out = nz_truncate(
        TruncateInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            confirm=True,
        ),
        config_path=profiles,
    )
    assert out.truncated is True
    assert out.duration_ms == 3


def test_nz_drop_table_happy_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)
    monkeypatch.setattr(
        "nz_mcp.tools.ddl.execute_drop_table",
        lambda *_a, **_k: {"dropped": True},
    )
    out = nz_drop_table(
        DropTableInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            confirm=True,
            if_exists=False,
        ),
        config_path=profiles,
    )
    assert out.dropped is True


def test_nz_drop_table_confirm_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "nz-mcp"
    home.mkdir()
    profiles = home / "profiles.toml"
    profiles.write_text(
        'active = "a"\n[profiles.a]\nhost="h"\nport=5480\ndatabase="DEV"\nuser="u"\nmode="admin"\n',
        encoding="utf-8",
    )
    import nz_mcp.config as cfg

    monkeypatch.setenv("NZ_MCP_HOME", str(home))
    monkeypatch.setattr(cfg, "config_dir", lambda: home)

    from nz_mcp.errors import InvalidInputError

    with pytest.raises(InvalidInputError):
        nz_drop_table(
            DropTableInput(
                database="DEV",
                table_schema="PUBLIC",
                table="T",
                confirm=False,
                if_exists=True,
            ),
            config_path=profiles,
        )
