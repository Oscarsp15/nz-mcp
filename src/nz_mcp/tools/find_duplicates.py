"""Duplicate key detection tool (read-only)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.tables import (
    DUPLICATES_LIMIT_CAP,
    DUPLICATES_LIMIT_DEFAULT,
    find_duplicates,
)
from nz_mcp.config import get_active_profile
from nz_mcp.i18n import resolve_locale, t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start


class DuplicateSampleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: list[str | None]
    count: int = Field(ge=0)


class FindDuplicatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    table_schema: str = Field(alias="schema", min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)
    key_columns: list[str] = Field(min_length=1)
    limit: int = Field(
        default=DUPLICATES_LIMIT_DEFAULT,
        ge=1,
        le=DUPLICATES_LIMIT_CAP,
        description="Maximum number of duplicate key groups to sample.",
    )


class FindDuplicatesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duplicate_groups: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    sample: list[DuplicateSampleItem]
    truncated: bool = Field(default=False)
    hint: str | None = None
    duration_ms: int = Field(ge=0, description="Wall time to scan for duplicates (milliseconds).")


@tool(
    name="nz_find_duplicates",
    description=(
        "Count duplicate key groups in a table and sample the offending keys. "
        "Use to validate loads and catch double-run or fan-out joins. "
        "Database must match the active profile database."
    ),
    mode="read",
    input_model=FindDuplicatesInput,
    output_model=FindDuplicatesOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_find_duplicates(
    params: FindDuplicatesInput,
    *,
    config_path: Path | None = None,
) -> FindDuplicatesOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    payload = find_duplicates(
        profile,
        database=params.database,
        schema=params.table_schema,
        table=params.table,
        key_columns=list(params.key_columns),
        limit=params.limit,
        timeout_s=profile.timeout_s_default,
    )
    groups = int(payload["duplicate_groups"])
    hint: str | None = None
    if payload["truncated"]:
        hint = t(
            "HINT.DUPLICATE_GROUPS_TRUNCATED",
            resolve_locale(),
            shown=params.limit,
            groups=groups,
            cap=DUPLICATES_LIMIT_CAP,
        )
    return FindDuplicatesOutput(
        duplicate_groups=groups,
        duplicate_rows=int(payload["duplicate_rows"]),
        sample=[DuplicateSampleItem.model_validate(item) for item in payload["sample"]],
        truncated=bool(payload["truncated"]),
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )
