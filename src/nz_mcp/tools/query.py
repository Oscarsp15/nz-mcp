"""Ad-hoc SELECT execution and EXPLAIN plans (validated by sql_guard)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.execute import execute_select, fetch_explain_text, inject_limit
from nz_mcp.config import MAX_ROWS_CAP, TIMEOUT_S_CAP, get_active_profile
from nz_mcp.errors import GuardRejectedError
from nz_mcp.i18n import t
from nz_mcp.sql_guard import StatementKind, validate
from nz_mcp.tools.registry import tool


class QuerySelectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1)
    max_rows: int | None = Field(default=None, ge=1, le=MAX_ROWS_CAP)
    timeout_s: int | None = Field(default=None, ge=1, le=TIMEOUT_S_CAP)


class ColumnMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name: str
    sql_type: str = Field(alias="type")


class QuerySelectOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[ColumnMeta]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    duration_ms: int
    hint: str | None


class ExplainInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1)
    verbose: bool = False


class ExplainOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str


def _resolved_max_rows(profile_max: int, arg: int | None) -> int:
    base = arg if arg is not None else profile_max
    return min(base, MAX_ROWS_CAP)


def _resolved_timeout(profile_timeout: int, arg: int | None) -> int:
    base = arg if arg is not None else profile_timeout
    return min(base, TIMEOUT_S_CAP)


def _hint_from_execute(payload: dict[str, object]) -> str | None:
    key = payload.get("hint_key")
    if not isinstance(key, str):
        return None
    fmt = payload.get("hint_fmt")
    if isinstance(fmt, dict):
        safe: dict[str, object] = {str(k): v for k, v in fmt.items()}
        return t(key, None, **safe)
    return t(key)


@tool(
    name="nz_query_select",
    description=(
        "Run a validated SELECT against the active Netezza profile. "
        "Use for read-only queries; LIMIT is applied automatically. "
        "Do not use for INSERT, UPDATE, DELETE, or DDL."
    ),
    mode="read",
    input_model=QuerySelectInput,
    output_model=QuerySelectOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_query_select(
    params: QuerySelectInput,
    *,
    config_path: Path | None = None,
) -> QuerySelectOutput:
    profile = get_active_profile(path=config_path)
    parsed = validate(params.sql, mode="read")
    if parsed.kind is not StatementKind.SELECT:
        raise GuardRejectedError(
            code="WRONG_STATEMENT_FOR_TOOL",
            tool="nz_query_select",
            kind=str(parsed.kind),
        )

    max_rows = _resolved_max_rows(profile.max_rows_default, params.max_rows)
    timeout_s = _resolved_timeout(profile.timeout_s_default, params.timeout_s)
    limited_sql = inject_limit(parsed.raw, max_rows)
    raw = execute_select(
        profile,
        limited_sql,
        max_rows=max_rows,
        timeout_s=timeout_s,
    )
    hint = _hint_from_execute(raw)
    columns = [
        ColumnMeta.model_validate({"name": c["name"], "type": c["type"]}) for c in raw["columns"]
    ]
    return QuerySelectOutput(
        columns=columns,
        rows=raw["rows"],
        row_count=int(raw["row_count"]),
        truncated=bool(raw["truncated"]),
        duration_ms=int(raw["duration_ms"]),
        hint=hint,
    )


@tool(
    name="nz_explain",
    description=(
        "Return the Netezza EXPLAIN plan text for a SELECT (no execution). "
        "Use after drafting a SELECT. "
        "Do not use for mutations or DDL."
    ),
    mode="read",
    input_model=ExplainInput,
    output_model=ExplainOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_explain(
    params: ExplainInput,
    *,
    config_path: Path | None = None,
) -> ExplainOutput:
    profile = get_active_profile(path=config_path)
    parsed = validate(params.sql, mode="read")
    if parsed.kind not in (StatementKind.SELECT, StatementKind.SHOW):
        raise GuardRejectedError(
            code="WRONG_STATEMENT_FOR_TOOL",
            tool="nz_explain",
            kind=str(parsed.kind),
        )

    stmt = parsed.raw.strip().rstrip(";")
    prefix = "EXPLAIN VERBOSE " if params.verbose else "EXPLAIN "
    explain_sql = prefix + stmt
    plan = fetch_explain_text(profile, explain_sql)
    return ExplainOutput(plan=plan)
