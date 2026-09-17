"""Tests for the view-lineage reference extractor (sqlglot, read-only)."""

from __future__ import annotations

from nz_mcp.catalog.views import extract_object_references


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
