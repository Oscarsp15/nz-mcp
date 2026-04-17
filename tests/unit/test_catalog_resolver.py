"""Tests for catalog query resolver overrides."""

from __future__ import annotations

import logging

import pytest

from nz_mcp.catalog.queries import LIST_DATABASES
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidProfileError


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
