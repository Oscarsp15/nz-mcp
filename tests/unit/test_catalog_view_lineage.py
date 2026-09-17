"""Tests for the view-lineage reference extractor and cross-database resolution."""

from __future__ import annotations

from typing import Any

import pytest

from nz_mcp.catalog.views import (
    _reference_coordinates,
    extract_object_references,
    resolve_object_kinds,
)
from nz_mcp.config import Profile


def test_extract_references_lists_relations_in_order() -> None:
    definition = "(SELECT X.A FROM DBO.V_ONE X) UNION ALL (SELECT Y.A FROM DBO.V_TWO Y);"
    assert extract_object_references(definition) == [
        {"database": None, "schema": "DBO", "name": "V_ONE"},
        {"database": None, "schema": "DBO", "name": "V_TWO"},
    ]


def test_extract_references_keeps_three_part_names() -> None:
    refs = extract_object_references("SELECT * FROM DESA_MODELOS.DBO.T_A")
    assert refs == [{"database": "DESA_MODELOS", "schema": "DBO", "name": "T_A"}]


def test_extract_references_collapses_duplicates() -> None:
    definition = "SELECT * FROM DBO.T_A UNION ALL SELECT * FROM DBO.T_A"
    assert extract_object_references(definition) == [
        {"database": None, "schema": "DBO", "name": "T_A"},
    ]


def test_extract_references_ignores_string_literals() -> None:
    definition = "SELECT 'FROM DBO.FAKE' AS NOTE FROM DBO.T_A"
    assert extract_object_references(definition) == [
        {"database": None, "schema": "DBO", "name": "T_A"},
    ]


def test_extract_references_empty_or_unparseable_is_empty() -> None:
    assert extract_object_references("") == []
    assert extract_object_references("   ") == []
    assert extract_object_references("NOT SQL (") == []


def test_reference_coordinates_keeps_cross_database() -> None:
    reference: dict[str, str | None] = {
        "database": "PROD_MODELOS",
        "schema": "DBO",
        "name": "T_REMOTE",
    }
    assert _reference_coordinates(reference, "DESA_MODELOS", "DBO") == (
        "PROD_MODELOS",
        "DBO",
        "T_REMOTE",
    )


def test_reference_coordinates_defaults_to_context() -> None:
    reference = {"database": None, "schema": None, "name": "T_LOCAL"}
    assert _reference_coordinates(reference, "DESA_MODELOS", "DBO") == (
        "DESA_MODELOS",
        "DBO",
        "T_LOCAL",
    )


def _profile(*, database: str = "DESA_MODELOS") -> Profile:
    return Profile(
        name="p",
        host="h",
        port=5480,
        database=database,
        user="u",
        mode="admin",
    )


class _RecordingCursor:
    """Fake cursor: records executed SQL and returns a fixed kind per call."""

    def __init__(self, kind: str = "TABLE") -> None:
        self._kind = kind
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[str]]:
        return [(self._kind,)]

    def close(self) -> None:
        pass


class _RecordingConn:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _RecordingCursor:
        return self._cursor

    def close(self) -> None:
        pass


def test_resolve_object_kinds_uses_the_reference_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cross-database reference must be resolved against its own database (issue #304)."""
    cursor = _RecordingCursor(kind="TABLE")
    monkeypatch.setattr(
        "nz_mcp.catalog.views.open_connection", lambda *_a, **_k: _RecordingConn(cursor)
    )
    monkeypatch.setattr("nz_mcp.catalog.views.get_password", lambda _n: "pw")

    references: list[dict[str, str | None]] = [
        {"database": "PROD_MODELOS", "schema": "DBO", "name": "T_REMOTE"},
        {"database": None, "schema": None, "name": "T_LOCAL"},
    ]
    out = resolve_object_kinds(_profile(), "DESA_MODELOS", "DBO", references)

    assert out == [
        {"database": "PROD_MODELOS", "schema": "DBO", "name": "T_REMOTE", "kind": "TABLE"},
        {"database": "DESA_MODELOS", "schema": "DBO", "name": "T_LOCAL", "kind": "TABLE"},
    ]
    executed_sql = [sql for sql, _ in cursor.executed]
    assert any("PROD_MODELOS.._V_TABLE" in sql for sql in executed_sql)
    assert any("DESA_MODELOS.._V_TABLE" in sql for sql in executed_sql)


def test_resolve_object_kinds_empty_references_skips_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("open_connection must not be called for an empty reference list")

    monkeypatch.setattr("nz_mcp.catalog.views.open_connection", _boom)
    assert resolve_object_kinds(_profile(), "DESA_MODELOS", "DBO", []) == []
