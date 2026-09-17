"""Tool: nz_compare_rows — key-set comparison between two tables."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.compare_rows import compare_rows
from nz_mcp.config import get_active_profile
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool

_DEFAULT_LIMIT: int = 10
_COMPARE_ROWS_SAMPLE_CAP: int = 100


class CompareRowsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    database: str = Field(min_length=1, max_length=128)
    schema_a: str = Field(min_length=1, max_length=128, description="Schema of table A.")
    table_a: str = Field(min_length=1, max_length=128, description="Table A.")
    key_a: str = Field(
        min_length=1,
        max_length=128,
        description="Key column on table A used for comparison.",
    )
    schema_b: str = Field(min_length=1, max_length=128, description="Schema of table B.")
    table_b: str = Field(min_length=1, max_length=128, description="Table B.")
    key_b: str = Field(
        min_length=1,
        max_length=128,
        description="Key column on table B used for comparison.",
    )
    limit: int = Field(
        default=_DEFAULT_LIMIT,
        ge=1,
        le=_COMPARE_ROWS_SAMPLE_CAP,
        description=(
            "Maximum sample rows to return for only_in_a / only_in_b. "
            "Counts are always exact; this caps the sample lists only."
        ),
    )


class CompareRowsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    only_in_a: int = Field(ge=0, description="Keys present in A but not in B (nulls excluded).")
    only_in_b: int = Field(ge=0, description="Keys present in B but not in A (nulls excluded).")
    in_both: int = Field(ge=0, description="Keys present in both A and B (nulls excluded).")
    null_keys_a: int = Field(ge=0, description="Rows in A with a null key column.")
    null_keys_b: int = Field(ge=0, description="Rows in B with a null key column.")
    sample_only_in_a: list[str] = Field(
        description="Up to `limit` key values present in A but not in B."
    )
    sample_only_in_b: list[str] = Field(
        description="Up to `limit` key values present in B but not in A."
    )
    truncated: bool = Field(
        default=False,
        description="True when a difference has more keys than the returned sample.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to see the keys left out of the samples.",
    )
    duration_ms: int = Field(ge=0, description="Wall time for all comparison queries (ms).")


@tool(
    name="nz_compare_rows",
    description=(
        "Compare key sets between two tables: rows only in A, only in B, in both, "
        "plus null keys. Use to reconcile layers after an ETL join. "
        "Do not use for full column-by-column diff."
    ),
    mode="read",
    input_model=CompareRowsInput,
    output_model=CompareRowsOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_compare_rows(
    params: CompareRowsInput,
    *,
    config_path: Path | None = None,
) -> CompareRowsOutput:
    profile = get_active_profile(path=config_path)
    payload = compare_rows(
        profile,
        database=params.database,
        schema_a=params.schema_a,
        table_a=params.table_a,
        key_a=params.key_a,
        schema_b=params.schema_b,
        table_b=params.table_b,
        key_b=params.key_b,
        limit=params.limit,
    )
    only_in_a = int(payload["only_in_a"])
    only_in_b = int(payload["only_in_b"])
    sample_only_in_a = list(payload["sample_only_in_a"])
    sample_only_in_b = list(payload["sample_only_in_b"])
    missing_a = max(0, only_in_a - len(sample_only_in_a))
    missing_b = max(0, only_in_b - len(sample_only_in_b))
    truncated = missing_a > 0 or missing_b > 0
    hint = (
        t(
            "COMPARE_ROWS.HINT.SAMPLE_CAPPED",
            None,
            limit=params.limit,
            missing_a=missing_a,
            missing_b=missing_b,
            cap=_COMPARE_ROWS_SAMPLE_CAP,
        )
        if truncated
        else None
    )
    return CompareRowsOutput(
        only_in_a=only_in_a,
        only_in_b=only_in_b,
        in_both=int(payload["in_both"]),
        null_keys_a=int(payload["null_keys_a"]),
        null_keys_b=int(payload["null_keys_b"]),
        sample_only_in_a=sample_only_in_a,
        sample_only_in_b=sample_only_in_b,
        truncated=truncated,
        hint=hint,
        duration_ms=int(payload["duration_ms"]),
    )
