"""Tests for centralized catalog query registry."""

from __future__ import annotations

import pytest

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
        queries.GET_ALL_PROCEDURES_DDL,
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


def test_catalog_query_map_contains_all_ids() -> None:
    assert set(queries.CATALOG_QUERY_MAP) == {query.id for query in queries.ALL_QUERIES}


# ── issue #123: pattern matching against catalog must be case-insensitive ────


@pytest.mark.parametrize(
    "query",
    [
        queries.LIST_DATABASES,
        queries.LIST_SCHEMAS,
        queries.LIST_TABLES,
        queries.LIST_VIEWS,
        queries.LIST_PROCEDURES,
        queries.GET_ALL_PROCEDURES_DDL,
    ],
    ids=lambda q: q.id,
)
def test_pattern_filter_uses_upper_to_be_case_insensitive(query: queries.CatalogQuery) -> None:
    """Catalog names are stored upper-case in Netezza; the LIKE filter must UPPER(?)."""
    sql_no_ws = " ".join(query.sql.split())
    # The naked ``LIKE ?`` form is the bug from issue #123 (case-sensitive match
    # against an upper-case catalog column). Every list query must wrap the
    # pattern placeholder with ``UPPER(?)`` so callers can pass any case.
    assert "LIKE UPPER(?)" in sql_no_ws, (
        f"{query.id}: pattern filter must be ``LIKE UPPER(?)`` to match Netezza's "
        "uppercase catalog names; ``LIKE ?`` regresses issue #123."
    )
    assert "LIKE ?" not in sql_no_ws.replace("LIKE UPPER(?)", "")
