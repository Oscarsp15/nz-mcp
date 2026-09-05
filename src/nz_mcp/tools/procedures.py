"""Stored procedure catalog tools."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.execute import RESPONSE_BYTES_CAP
from nz_mcp.catalog.nzplsql_parser import StatementKind, strip_comments
from nz_mcp.catalog.procedures import (
    PROCEDURE_SECTION_MAX_LINES,
    describe_procedure,
    find_table_references,
    get_all_procedures_ddl,
    get_procedure_ddl,
    get_procedure_section,
    get_procedure_size,
    get_procedure_table_logic,
    list_procedures,
    truncate_procedure_ddl,
)
from nz_mcp.config import MAX_ROWS_CAP, get_active_profile
from nz_mcp.errors import ResponseTooLargeError
from nz_mcp.i18n import t
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start

# UX: warn when procedure DDL may overwhelm LLM context (do not truncate DDL).
PROC_DDL_WARN_BYTES: int = 100 * 1024
PROC_DDL_LARGE_WARNING: str = (
    "DDL is very large (>100 KB); consider fetching sections with nz_get_procedure_section."
)

# Hard cap for the structured response of nz_get_procedure_table_logic (issue #109).
PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES: int = 200 * 1024

# Truncation budget for nz_get_procedure_ddl (issue #165, ADR 0018). The default
# matches the response cap every other read tool already honours; the ceiling
# matches the largest response cap already accepted in this module.
PROC_DDL_DEFAULT_MAX_BYTES: int = RESPONSE_BYTES_CAP
PROC_DDL_MAX_BYTES_CAP: int = PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES
PROC_DDL_MIN_MAX_BYTES: int = 1024


class ListProceduresInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ROWS_CAP,
        description=(
            "Maximum number of procedures to return. Defaults to the active profile's "
            "max_rows_default; always capped at MAX_ROWS_CAP."
        ),
    )


class ProcedureListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str
    language: Literal["NZPLSQL"] = "NZPLSQL"
    arguments: str
    returns: str


class ListProceduresOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedures: list[ProcedureListItem]
    truncated: bool = Field(
        default=False,
        description="True when the schema holds more procedures than max_rows.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to reach the procedures left out.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to run the catalog query (milliseconds).")


class DescribeProcedureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    procedure: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=2048)


class ProcedureArg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str


class DescribeProcedureOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str
    language: Literal["NZPLSQL"] = "NZPLSQL"
    arguments: list[ProcedureArg]
    returns: str
    created_at: str | None = None
    lines: int
    sections_detected: list[str]
    duration_ms: int = Field(
        ge=0, description="Wall time to describe the procedure (milliseconds)."
    )


class GetProcedureDdlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    procedure: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=2048)
    variant: Literal["raw", "clean"] = Field(
        default="raw",
        description=(
            "DDL variant to return. "
            "'raw' preserves original source including comments (default, back-compat). "
            "'clean' strips NZPLSQL line (--) and block (/* */) comments "
            "for token-efficient AI reasoning."
        ),
    )
    max_bytes: int = Field(
        default=PROC_DDL_DEFAULT_MAX_BYTES,
        ge=PROC_DDL_MIN_MAX_BYTES,
        le=PROC_DDL_MAX_BYTES_CAP,
        description=(
            "Hard cap in UTF-8 bytes for the returned DDL. The text is cut on line "
            "boundaries and a hint points at nz_get_procedure_section for the rest."
        ),
    )


class GetProcedureDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ddl: str
    size_bytes: int = Field(
        ge=0,
        description="Byte length of the returned ``ddl`` variant encoded as UTF-8.",
    )
    size_bytes_raw: int = Field(
        ge=0,
        description="Byte length of the raw DDL (comments included) encoded as UTF-8.",
    )
    size_bytes_clean: int = Field(
        ge=0,
        description="Byte length of the clean DDL (comments stripped) encoded as UTF-8.",
    )
    warning: str | None = Field(
        default=None,
        description="Set when the returned DDL exceeds ~100 KB; prefer nz_get_procedure_section.",
    )
    truncated: bool = Field(
        default=False,
        description="True when the DDL was cut because it exceeded max_bytes.",
    )
    hint: str | None = Field(
        default=None,
        description="Localized guidance on how to read the part left out when truncated.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to build DDL (milliseconds.)")


class GetProcedureSizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    procedure: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=2048)


class GetProcedureSizeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    signature: str
    size_bytes_raw: int = Field(ge=0)
    size_bytes_clean: int = Field(ge=0)
    lines_raw: int = Field(ge=0)
    lines_clean: int = Field(ge=0)
    sections_detected: list[str]
    duration_ms: int = Field(ge=0, description="Wall time to calculate size (milliseconds).")


class GetProcedureSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    procedure: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=2048)
    section: Literal["header", "declare", "body", "exception", "range"]
    from_line: int | None = Field(default=None, ge=1)
    to_line: int | None = Field(default=None, ge=1)


class GetProcedureSectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: str
    from_line: int
    to_line: int
    content: str
    truncated: bool
    duration_ms: int = Field(ge=0, description="Wall time to extract the section (milliseconds).")


class GetProceduresDdlBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


class ProcedureBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    owner: str
    arguments: str
    returns: str
    ddl: str
    signature: str
    last_altered: str
    size_bytes: int


class GetProceduresDdlBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedures: list[ProcedureBatchItem]
    count: int
    total_size_bytes: int
    warning: str | None = Field(
        default=None,
        description="Set when any single DDL > 100 KB or total > 1 MB.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to batch build DDLs (milliseconds).")


@tool(
    name="nz_list_procedures",
    description=(
        "List stored procedures in a Netezza schema via _V_PROCEDURE. "
        "Use to discover procedure names before describing or fetching DDL. "
        "The result is capped by max_rows (profile default); when truncated, "
        "narrow the search with pattern instead of raising max_rows blindly."
    ),
    mode="read",
    input_model=ListProceduresInput,
    output_model=ListProceduresOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_list_procedures(
    params: ListProceduresInput,
    *,
    config_path: Path | None = None,
) -> ListProceduresOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    requested = params.max_rows if params.max_rows is not None else profile.max_rows_default
    max_rows = min(requested, MAX_ROWS_CAP)
    rows = list_procedures(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        pattern=params.pattern,
    )
    total = len(rows)
    truncated = total > max_rows
    hint = (
        t("HINT.PROCEDURE_LIST_TRUNCATED", None, n=max_rows, total=total, cap=MAX_ROWS_CAP)
        if truncated
        else None
    )
    return ListProceduresOutput(
        procedures=[
            ProcedureListItem(
                name=r["name"],
                owner=r["owner"],
                language="NZPLSQL",
                arguments=r["arguments"],
                returns=r["returns"],
            )
            for r in rows[:max_rows]
        ],
        truncated=truncated,
        hint=hint,
        duration_ms=monotonic_duration_ms(start),
    )


@tool(
    name="nz_describe_procedure",
    description=(
        "Describe one stored procedure metadata (arguments, returns, line count, "
        "detected NZPLSQL sections) without returning the full body."
    ),
    mode="read",
    input_model=DescribeProcedureInput,
    output_model=DescribeProcedureOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_describe_procedure(
    params: DescribeProcedureInput,
    *,
    config_path: Path | None = None,
) -> DescribeProcedureOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    raw = describe_procedure(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
    )
    args = [ProcedureArg(name=a["name"], type=a["type"]) for a in raw["arguments"]]
    return DescribeProcedureOutput(
        name=raw["name"],
        owner=raw["owner"],
        language="NZPLSQL",
        arguments=args,
        returns=raw["returns"],
        created_at=raw.get("created_at"),
        lines=int(raw["lines"]),
        sections_detected=list(raw["sections_detected"]),
        duration_ms=monotonic_duration_ms(start),
    )


def _ddl_truncation_hint(
    returned_bytes: int,
    total_bytes: int,
    max_bytes: int,
    resume_line: int,
) -> str | None:
    """Build the localized hint that routes the caller to the section tools."""
    if resume_line <= 0:
        return None
    return t(
        "HINT.PROCEDURE_DDL_TRUNCATED",
        None,
        returned_kb=returned_bytes // 1024,
        total_kb=total_bytes // 1024,
        max_kb=max_bytes // 1024,
        from_line=resume_line,
        to_line=resume_line + PROCEDURE_SECTION_MAX_LINES - 1,
        step=PROCEDURE_SECTION_MAX_LINES,
    )


@tool(
    name="nz_get_procedure_ddl",
    description=(
        "Return CREATE OR REPLACE PROCEDURE DDL from catalog. Use variant='clean' to strip "
        "comments for token-efficient reasoning; 'raw' (default) preserves full source. "
        "Always returns size_bytes_raw and size_bytes_clean. The DDL is truncated at "
        "max_bytes (~100 KB by default); when truncated, follow the returned hint and "
        "read the rest with nz_get_procedure_section."
    ),
    mode="read",
    input_model=GetProcedureDdlInput,
    output_model=GetProcedureDdlOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_procedure_ddl(
    params: GetProcedureDdlInput,
    *,
    config_path: Path | None = None,
) -> GetProcedureDdlOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    ddl_raw = get_procedure_ddl(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
    )
    ddl_clean = strip_comments(ddl_raw)
    size_bytes_raw = len(ddl_raw.encode("utf-8"))
    size_bytes_clean = len(ddl_clean.encode("utf-8"))

    is_clean = params.variant == "clean"
    full = ddl_clean if is_clean else ddl_raw
    full_bytes = size_bytes_clean if is_clean else size_bytes_raw

    if full_bytes <= params.max_bytes:
        ddl, resume_line = full, 0
    else:
        # The budget is spent on the raw prefix even for variant='clean' so the
        # resume line stays valid against PROCEDURESOURCE numbering. Stripping
        # comments afterwards can only shrink the payload, never overflow it.
        cut, resume_line = truncate_procedure_ddl(ddl_raw, params.max_bytes)
        ddl = strip_comments(cut) if is_clean else cut

    size_b = len(ddl.encode("utf-8"))
    warn = PROC_DDL_LARGE_WARNING if size_b > PROC_DDL_WARN_BYTES else None
    return GetProcedureDdlOutput(
        ddl=ddl,
        size_bytes=size_b,
        size_bytes_raw=size_bytes_raw,
        size_bytes_clean=size_bytes_clean,
        warning=warn,
        truncated=resume_line > 0,
        hint=_ddl_truncation_hint(size_b, full_bytes, params.max_bytes, resume_line),
        duration_ms=monotonic_duration_ms(start),
    )


@tool(
    name="nz_get_procedure_size",
    description=(
        "Return the byte size, line counts (raw and clean variants), and detected sections "
        "of a procedure without fetching its full body text. Use this for token budgeting "
        "before deciding whether to fetch the full procedure or fetch it by section."
    ),
    mode="read",
    input_model=GetProcedureSizeInput,
    output_model=GetProcedureSizeOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_procedure_size(
    params: GetProcedureSizeInput,
    *,
    config_path: Path | None = None,
) -> GetProcedureSizeOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    result = get_procedure_size(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
    )
    return GetProcedureSizeOutput(
        name=result["name"],
        signature=result["signature"],
        size_bytes_raw=result["size_bytes_raw"],
        size_bytes_clean=result["size_bytes_clean"],
        lines_raw=result["lines_raw"],
        lines_clean=result["lines_clean"],
        sections_detected=result["sections_detected"],
        duration_ms=monotonic_duration_ms(start),
    )


@tool(
    name="nz_get_procedure_section",
    description=(
        "Extract a logical section (header/declare/body/exception) or a raw line range "
        "from a stored procedure body (NZPLSQL markers). Range is capped at 500 lines."
    ),
    mode="read",
    input_model=GetProcedureSectionInput,
    output_model=GetProcedureSectionOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_procedure_section(
    params: GetProcedureSectionInput,
    *,
    config_path: Path | None = None,
) -> GetProcedureSectionOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    raw = get_procedure_section(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        section=params.section,
        signature=params.signature,
        from_line=params.from_line,
        to_line=params.to_line,
    )
    return GetProcedureSectionOutput(
        section=raw["section"],
        from_line=int(raw["from_line"]),
        to_line=int(raw["to_line"]),
        content=raw["content"],
        truncated=bool(raw["truncated"]),
        duration_ms=monotonic_duration_ms(start),
    )


@tool(
    name="nz_get_procedures_ddl_batch",
    description=(
        "Batch fetch the DDL for all stored procedures in a schema. "
        "Useful for bulk indexing without hitting Netezza with hundreds of queries."
    ),
    mode="read",
    input_model=GetProceduresDdlBatchInput,
    output_model=GetProceduresDdlBatchOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_procedures_ddl_batch(
    params: GetProceduresDdlBatchInput,
    *,
    config_path: Path | None = None,
) -> GetProceduresDdlBatchOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    res = get_all_procedures_ddl(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        pattern=params.pattern,
    )

    total_size = res["total_size_bytes"]
    procs = res["procedures"]

    warning = None
    if total_size > 1024 * 1024:
        warning = "Total DDL size exceeds ~1 MB."
    elif any(p["size_bytes"] > PROC_DDL_WARN_BYTES for p in procs):
        warning = "One or more procedures exceed ~100 KB in DDL size."

    return GetProceduresDdlBatchOutput(
        procedures=[ProcedureBatchItem(**p) for p in procs],
        count=len(procs),
        total_size_bytes=total_size,
        warning=warning,
        duration_ms=monotonic_duration_ms(start),
    )


# ── nz_get_procedure_table_logic (issue #109) ────────────────────────────────


_TableLogicKind = Literal[
    "create",
    "insert",
    "drop",
    "truncate",
    "update",
    "delete",
    "merge",
]


def _default_kinds() -> list[_TableLogicKind]:
    """Default for ``GetProcedureTableLogicInput.kinds`` (typed for mypy strict)."""
    # Keeping the default at ``["create", "insert"]`` preserves back-compat
    # for existing callers; the five new verbs (drop/truncate/update/delete/
    # merge) are opt-in via an explicit ``kinds`` request (issue #120).
    return ["create", "insert"]


class GetProcedureTableLogicInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    procedure: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, max_length=2048)
    table: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Internal table name to isolate (case-insensitive). "
            "Schema-qualified names are not accepted — the logic is internal to the SP."
        ),
    )
    kinds: list[_TableLogicKind] = Field(
        default_factory=_default_kinds,
        description="Statement kinds to include. Defaults to both create and insert.",
    )


class StatementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "CREATE TABLE",
        "CREATE TEMP TABLE",
        "INSERT INTO",
        "DROP TABLE",
        "TRUNCATE TABLE",
        "UPDATE",
        "DELETE FROM",
        "MERGE INTO",
    ]
    sql: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    size_bytes: int = Field(ge=0)


class GetProcedureTableLogicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    statements: list[StatementItem]
    count: int = Field(ge=0)
    not_found: bool
    duration_ms: int = Field(
        ge=0,
        description="Wall time to extract targeting statements (milliseconds).",
    )


_KINDS_MAP: dict[_TableLogicKind, tuple[StatementKind, ...]] = {
    "create": ("CREATE TABLE", "CREATE TEMP TABLE"),
    "insert": ("INSERT INTO",),
    "drop": ("DROP TABLE",),
    "truncate": ("TRUNCATE TABLE",),
    "update": ("UPDATE",),
    "delete": ("DELETE FROM",),
    "merge": ("MERGE INTO",),
}


def _resolve_kinds(kinds: list[_TableLogicKind]) -> tuple[StatementKind, ...]:
    """Map UI ``kinds`` (``create`` / ``insert``) to internal ``StatementKind`` tuples."""
    out: list[StatementKind] = []
    seen: set[StatementKind] = set()
    for k in kinds:
        for inner in _KINDS_MAP[k]:
            if inner not in seen:
                seen.add(inner)
                out.append(inner)
    return tuple(out)


@tool(
    name="nz_get_procedure_table_logic",
    description=(
        "Return the CREATE/INSERT statements that build or populate a single internal table "
        "inside a stored procedure (comments stripped, raw line range preserved). "
        "Use to isolate the logic of one intermediate table without fetching the full DDL. "
        "Do not use to find what other procedures reference a table — use a reverse-lookup tool."
    ),
    mode="read",
    input_model=GetProcedureTableLogicInput,
    output_model=GetProcedureTableLogicOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_get_procedure_table_logic(
    params: GetProcedureTableLogicInput,
    *,
    config_path: Path | None = None,
) -> GetProcedureTableLogicOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    raw = get_procedure_table_logic(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        table=params.table,
        kinds=_resolve_kinds(params.kinds),
        signature=params.signature,
    )

    statements = [StatementItem(**s) for s in raw["statements"]]
    total_bytes = sum(s.size_bytes for s in statements)
    if total_bytes > PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES:
        raise ResponseTooLargeError(
            size_kb=total_bytes // 1024,
            cap_kb=PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES // 1024,
        )

    return GetProcedureTableLogicOutput(
        table=raw["table"],
        statements=statements,
        count=int(raw["count"]),
        not_found=bool(raw["not_found"]),
        duration_ms=monotonic_duration_ms(start),
    )


# ── nz_find_table_references (issue #107) ────────────────────────────────────


class GetFindTableReferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    table: str = Field(
        min_length=1,
        max_length=128,
        description="Table name to look up references for (case-insensitive).",
    )
    table_database: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Restrict references to those qualified by this database. When omitted, "
            "any qualifier (or none) is accepted."
        ),
    )
    table_schema: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Restrict references to those qualified by this schema. When omitted, "
            "any qualifier (or none) is accepted."
        ),
    )
    pattern: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional LIKE filter on procedure names to narrow the scan universe.",
    )


class TableReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_name: str
    signature: str
    usage: Literal["read", "write", "both"]
    occurrences_read: int = Field(ge=0)
    occurrences_write: int = Field(ge=0)
    last_altered: str


class GetFindTableReferencesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    references: list[TableReferenceItem]
    scanned_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    truncated: bool
    duration_ms: int = Field(ge=0, description="Wall time to scan procedures (milliseconds).")


@tool(
    name="nz_find_table_references",
    description=(
        "Find which stored procedures in a schema read or write a given table. "
        "Returns each procedure with read/write occurrence counts. Use for impact "
        "analysis before changing a table. Do not use for views, dynamic SQL, or "
        "column-level analysis."
    ),
    mode="read",
    input_model=GetFindTableReferencesInput,
    output_model=GetFindTableReferencesOutput,
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
def nz_find_table_references(
    params: GetFindTableReferencesInput,
    *,
    config_path: Path | None = None,
) -> GetFindTableReferencesOutput:
    start = monotonic_start()
    profile = get_active_profile(path=config_path)
    raw = find_table_references(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        table=params.table,
        table_database=params.table_database,
        table_schema=params.table_schema,
        pattern=params.pattern,
    )
    return GetFindTableReferencesOutput(
        references=[TableReferenceItem(**r) for r in raw["references"]],
        scanned_count=int(raw["scanned_count"]),
        match_count=int(raw["match_count"]),
        truncated=bool(raw["truncated"]),
        duration_ms=monotonic_duration_ms(start),
    )
