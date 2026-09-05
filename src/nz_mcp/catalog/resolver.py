"""Catalog query resolver with profile-level overrides."""

from __future__ import annotations

import logging

from nz_mcp.catalog.queries import CATALOG_QUERY_MAP
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidProfileError
from nz_mcp.sql_guard import validate_catalog_override

_LOGGER = logging.getLogger(__name__)


def resolve_query(query_id: str, profile: Profile) -> str:
    """Resolve catalog SQL, preferring profile override when present."""
    _validate_query_id(query_id)
    _validate_overrides(profile)

    override = profile.catalog_overrides.get(query_id)
    if override is None:
        return CATALOG_QUERY_MAP[query_id].sql

    if "<BD>.." in override and not CATALOG_QUERY_MAP[query_id].cross_database:
        _LOGGER.warning(
            "Catalog override uses <BD>.. on non cross-database query",
            extra={"query_id": query_id, "profile": profile.name},
        )
    return override


def _validate_query_id(query_id: str) -> None:
    if query_id not in CATALOG_QUERY_MAP:
        raise InvalidProfileError(detail=f"Unknown catalog query id: {query_id}")


def _validate_overrides(profile: Profile) -> None:
    """Reject unknown override ids and any override SQL that is not a read-only SELECT.

    Overrides are the only SQL in the catalog paths that the user writes, so this is where
    ``sql_guard`` gets its say before ``connection.execute`` (issue #139, ADR 0022). Every
    override of the profile is checked, not only the one being resolved: one broken entry
    makes the profile broken, exactly as an unknown ``query_id`` already did, and the user
    gets the whole diagnosis on the first catalog call instead of one failure per tool.
    """
    unknown = sorted(set(profile.catalog_overrides) - set(CATALOG_QUERY_MAP))
    if unknown:
        unknown_ids = ", ".join(unknown)
        raise InvalidProfileError(
            profile=profile.name,
            detail=f"Unknown catalog_overrides query ids: {unknown_ids}",
        )
    for override_id, sql in sorted(profile.catalog_overrides.items()):
        validate_catalog_override(sql, query_id=override_id, profile=profile.name)
