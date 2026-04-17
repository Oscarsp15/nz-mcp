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
    )


@tool(
    name="nz_get_procedure_ddl",
    description=(
        "Return reconstructed CREATE OR REPLACE PROCEDURE DDL from catalog source "
        "and signature metadata."
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
    profile = get_active_profile(path=config_path)
    ddl = get_procedure_ddl(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        signature=params.signature,
    )
    return GetProcedureDdlOutput(ddl=ddl)


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
    )
