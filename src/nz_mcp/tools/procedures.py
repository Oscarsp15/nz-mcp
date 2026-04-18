"""Stored procedure catalog tools."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.procedures import (
    describe_procedure,
    get_procedure_ddl,
    get_procedure_section,
    list_procedures,
)
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool
from nz_mcp.tools.timing import monotonic_duration_ms, monotonic_start

# UX: warn when procedure DDL may overwhelm LLM context (do not truncate DDL).
PROC_DDL_WARN_BYTES: int = 100 * 1024
PROC_DDL_LARGE_WARNING: str = (
    "DDL is very large (>100 KB); consider fetching sections with nz_get_procedure_section."
)


class ListProceduresInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(
        alias="schema",
        min_length=1,
        max_length=128,
    )
    pattern: str | None = Field(default=None, min_length=1, max_length=128)


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


class GetProcedureDdlOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ddl: str
    size_bytes: int = Field(ge=0, description="Byte length of ``ddl`` encoded as UTF-8.")
    warning: str | None = Field(
        default=None,
        description="Set when DDL exceeds ~100 KB; prefer nz_get_procedure_section.",
    )
    duration_ms: int = Field(ge=0, description="Wall time to build DDL (milliseconds).")


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


@tool(
    name="nz_list_procedures",
    description=(
        "List stored procedures in a Netezza schema via _V_PROCEDURE. "
        "Use to discover procedure names before describing or fetching DDL."
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
    rows = list_procedures(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        pattern=params.pattern,
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
            for r in rows
        ],
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


@tool(
    name="nz_get_procedure_ddl",
    description=(
        "Return reconstructed CREATE OR REPLACE PROCEDURE DDL from catalog source "
        "and signature metadata. For very large procedures prefer "
        "nz_get_procedure_section(section='body')."
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
    ddl = get_procedure_ddl(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
    )
    size_b = len(ddl.encode("utf-8"))
    warn = PROC_DDL_LARGE_WARNING if size_b > PROC_DDL_WARN_BYTES else None
    return GetProcedureDdlOutput(
        ddl=ddl,
        size_bytes=size_b,
        warning=warn,
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
