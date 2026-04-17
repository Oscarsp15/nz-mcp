"""Tests for centralized catalog query registry."""

from __future__ import annotations

from nz_mcp.catalog import queries


def test_all_queries_contains_all_exported_query_constants() -> None:
    constants = [
        queries.LIST_DATABASES,
        queries.LIST_SCHEMAS,
        queries.LIST_TABLES,
        queries.LIST_VIEWS,
        queries.GET_VIEW_DDL,
        queries.DESCRIBE_TABLE_COLUMNS,
        queries.DESCRIBE_TABLE_DISTRIBUTION,
        queries.DESCRIBE_TABLE_PK,
        queries.DESCRIBE_TABLE_FK,
        queries.TABLE_STATS,
        queries.LIST_PROCEDURES,
        queries.GET_PROCEDURE_DDL,
        queries.GET_PROCEDURE_SECTION,
    ]

    assert set(queries.ALL_QUERIES) == set(constants)


def test_query_ids_are_unique() -> None:
    ids = [query.id for query in queries.ALL_QUERIES]
    assert len(ids) == len(set(ids))


def test_catalog_views_use_v_prefix() -> None:
    for query in queries.ALL_QUERIES:
        assert query.catalog_views
        for catalog_view in query.catalog_views:
            assert catalog_view.startswith("_V_")


def test_cross_database_flag_matches_sql_marker() -> None:
    for query in queries.ALL_QUERIES:
        has_marker = "<BD>.." in query.sql
        assert query.cross_database is has_marker


def test_all_queries_are_marked_with_tested_version() -> None:
    for query in queries.ALL_QUERIES:
        assert query.tested_versions == ("NPS 11.2.1.11-IF1",)
