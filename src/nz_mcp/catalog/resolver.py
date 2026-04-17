"""Catalog query resolver with profile-level overrides."""

from __future__ import annotations

import logging

from nz_mcp.catalog.queries import CATALOG_QUERY_MAP
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidProfileError

_LOGGER = logging.getLogger(__name__)


def resolve_query(query_id: str, profile: Profile) -> str:
    """Resolve catalog SQL, preferring profile override when present."""
    _validate_query_id(query_id)
    _validate_override_keys(profile)

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


def _validate_override_keys(profile: Profile) -> None:
    unknown = sorted(set(profile.catalog_overrides) - set(CATALOG_QUERY_MAP))
    if unknown:
        unknown_ids = ", ".join(unknown)
        raise InvalidProfileError(
            profile=profile.name,
            detail=f"Unknown catalog_overrides query ids: {unknown_ids}",
        )
