"""Tests for nz_clone_procedure MCP tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.server import call_tool
from nz_mcp.tools.clone_procedure import CloneProcedureInput, nz_clone_procedure


def test_nz_clone_procedure_permission_denied_write_profile(
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
        "nz_clone_procedure",
        {
            "source_database": "DEV",
            "source_schema": "PUBLIC",
            "source_procedure": "A",
            "target_database": "DEV",
            "target_schema": "PUBLIC",
            "target_procedure": "B",
            "dry_run": True,
        },
        config_path=profiles,
    )
    assert "error" in out
    assert out["error"]["code"] == "PERMISSION_DENIED"


def test_nz_clone_procedure_dry_run_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        "nz_mcp.tools.clone_procedure.clone_procedure",
        lambda *_a, **_k: {
            "dry_run": True,
            "ddl_to_execute": "CREATE PROCEDURE PUBLIC.X()",
            "executed": False,
            "warnings": [],
            "duration_ms": None,
        },
    )
    out = nz_clone_procedure(
        CloneProcedureInput(
            source_database="DEV",
            source_schema="PUBLIC",
            source_procedure="S",
            target_database="DEV",
            target_schema="PUBLIC",
            target_procedure="X",
            dry_run=True,
        ),
        config_path=profiles,
    )
    assert out.dry_run is True
    assert out.executed is False
