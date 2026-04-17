"""Tests for ``nz_explain``."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import GuardRejectedError
from nz_mcp.tools.query import ExplainInput, nz_explain


def test_explain_rejects_insert(two_profiles: Path) -> None:
    with pytest.raises(GuardRejectedError) as exc:
        nz_explain(
            ExplainInput(sql="INSERT INTO t (a) VALUES (1)"),
            config_path=two_profiles,
        )
    assert exc.value.code == "STATEMENT_NOT_ALLOWED"


def test_explain_select_builds_plan(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    captured: dict[str, object] = {}

    def _fetch(_profile: object, sql: str) -> str:
        captured["sql"] = sql
        return "Seq Scan"

    monkeypatch.setattr("nz_mcp.tools.query.fetch_explain_text", _fetch)

    out = nz_explain(
        ExplainInput(sql="SELECT 1"),
        config_path=two_profiles,
    )
    assert out.plan == "Seq Scan"
    assert str(captured["sql"]).upper().startswith("EXPLAIN ")
    assert "SELECT" in str(captured["sql"]).upper()


def test_explain_verbose_prefix(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    captured: dict[str, object] = {}

    def _fetch(_profile: object, sql: str) -> str:
        captured["sql"] = sql
        return "plan"

    monkeypatch.setattr("nz_mcp.tools.query.fetch_explain_text", _fetch)

    nz_explain(
        ExplainInput(sql="SELECT 1", verbose=True),
        config_path=two_profiles,
    )
    assert "EXPLAIN VERBOSE" in str(captured["sql"]).upper()


def test_explain_allows_show(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fetch(_profile: object, sql: str) -> str:
        assert "SHOW" in sql.upper()
        return "show-plan"

    monkeypatch.setattr("nz_mcp.tools.query.fetch_explain_text", _fetch)

    out = nz_explain(
        ExplainInput(sql="SHOW DATABASES"),
        config_path=two_profiles,
    )
    assert out.plan == "show-plan"
