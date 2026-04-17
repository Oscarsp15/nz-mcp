"""Cross-database identifier validation and rendering."""

from __future__ import annotations

import re
from typing import Final

from nz_mcp.errors import InvalidInputError

_DB_IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def validate_database_identifier(name: str) -> str:
    """Validate and normalize a database identifier for ``<BD>..`` interpolation."""
    normalized = name.strip().upper()
    if not _DB_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise InvalidInputError(
            code="INVALID_DATABASE_NAME",
            detail=f"Invalid database identifier: {name!r}",
        )
    return normalized


def validate_catalog_identifier(name: str) -> str:
    """Validate schema, table, or other single-part SQL identifiers (uppercase unquoted)."""
    normalized = name.strip().upper()
    if not _DB_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise InvalidInputError(
            detail=f"Invalid catalog identifier: {name!r}",
        )
    return normalized


def render_cross_db(sql: str, database: str) -> str:
    """Replace ``<BD>..`` markers with a validated database identifier."""
    validated = validate_database_identifier(database)
    rendered = sql.replace("<BD>..", f"{validated}..")
    if "<BD>" in rendered:
        raise InvalidInputError(
            code="INVALID_DATABASE_NAME",
            detail="Unresolved <BD> marker after interpolation.",
        )
    return rendered
