"""Tests for catalog query resolver overrides."""

from __future__ import annotations

import logging

import pytest

from nz_mcp.catalog.queries import ALL_QUERIES, LIST_DATABASES, CatalogQuery
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, InvalidProfileError
from nz_mcp.sql_guard import StatementKind, validate_catalog_override


def _profile(*, overrides: dict[str, str] | None = None) -> Profile:
    return Profile(
        name="dev",
        host="nz-dev.example.com",
        port=5480,
        database="DEV",
        user="svc_dev",
        mode="read",
        catalog_overrides=overrides or {},
    )


def test_resolve_query_returns_default_sql_without_override() -> None:
    sql = resolve_query("list_databases", _profile())
    assert sql == LIST_DATABASES.sql


def test_resolve_query_returns_profile_override() -> None:
    sql = resolve_query(
        "list_databases",
        _profile(overrides={"list_databases": "SELECT DATABASE, OWNER FROM MY_VIEW"}),
    )
    assert sql == "SELECT DATABASE, OWNER FROM MY_VIEW"


def test_resolve_query_rejects_unknown_query_id() -> None:
    with pytest.raises(InvalidProfileError) as exc:
        resolve_query("unknown_query", _profile())
    assert "Unknown catalog query id" in str(exc.value)


def test_resolve_query_rejects_unknown_override_key() -> None:
    with pytest.raises(InvalidProfileError) as exc:
        resolve_query(
            "list_databases",
            _profile(overrides={"list_databases": "SELECT 1", "not_existing": "SELECT 2"}),
        )
    assert "Unknown catalog_overrides query ids" in str(exc.value)


def test_resolve_query_warns_for_cross_db_marker_on_non_cross_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        sql = resolve_query(
            "list_databases",
            _profile(overrides={"list_databases": "SELECT * FROM <BD>.._V_DATABASE"}),
        )

    assert sql == "SELECT * FROM <BD>.._V_DATABASE"
    assert "Catalog override uses <BD>.. on non cross-database query" in caplog.text


# --- override SQL validation (issue #139, ADR 0022) ----------------------------


def test_resolve_query_rejects_override_that_is_not_a_select() -> None:
    """A profile override is user SQL: it goes through the guard before it can run."""
    with pytest.raises(GuardRejectedError) as exc:
        resolve_query(
            "list_databases",
            _profile(overrides={"list_databases": "DELETE FROM _V_DATABASE WHERE 1 = 1"}),
        )
    assert exc.value.code == "CATALOG_OVERRIDE_REJECTED"
    assert exc.value.context["query_id"] == "list_databases"
    assert exc.value.context["profile"] == "dev"


def test_resolve_query_rejects_stacked_statement_in_override() -> None:
    with pytest.raises(GuardRejectedError) as exc:
        resolve_query(
            "list_databases",
            _profile(
                overrides={"list_databases": "SELECT DATABASE FROM _V_DATABASE; DROP TABLE ADMIN.T"}
            ),
        )
    assert exc.value.context["reason"] == "STACKED_NOT_ALLOWED"


def test_resolve_query_rejects_a_bad_override_of_another_query_id() -> None:
    """One broken entry breaks the profile, like an unknown ``query_id`` already did.

    Otherwise the user would meet the problem one tool at a time, and a malicious entry
    would sit dormant until the matching tool is called.
    """
    with pytest.raises(GuardRejectedError) as exc:
        resolve_query(
            "list_databases",
            _profile(overrides={"list_tables": "DROP TABLE ADMIN.CUSTOMERS"}),
        )
    assert exc.value.context["query_id"] == "list_tables"


def test_resolve_query_still_returns_a_legitimate_override_verbatim() -> None:
    sql = "SELECT DATABASE, OWNER FROM CUSTOM_DB_VIEW ORDER BY DATABASE"
    assert resolve_query("list_databases", _profile(overrides={"list_databases": sql})) == sql


@pytest.mark.parametrize("query", ALL_QUERIES, ids=[q.id for q in ALL_QUERIES])
def test_registered_catalog_queries_pass_the_override_validation(query: CatalogQuery) -> None:
    """The rule applied to overrides must not be stricter than the built-in queries.

    Guards against a future catalog query that the validator would reject if a user
    copied it into ``catalog_overrides`` to tweak it.
    """
    parsed = validate_catalog_override(query.sql, query_id=query.id, profile="dev")
    assert parsed.kind is StatementKind.SELECT
