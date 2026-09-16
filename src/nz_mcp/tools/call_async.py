"""Async stored-procedure tools: launch and poll."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.call_async import launch_call_procedure, poll_job
from nz_mcp.config import get_active_profile
from nz_mcp.tools.registry import tool

ScalarArg = str | int | float | bool | None


# ---------------------------------------------------------------------------
# nz_call_procedure_async — launch
# ---------------------------------------------------------------------------


class CallProcedureAsyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    database: str = Field(min_length=1, max_length=128)
    procedure_schema: str = Field(alias="schema", min_length=1, max_length=128)
    procedure: str = Field(min_length=1, max_length=128)
    args: list[ScalarArg] | None = None
    signature: str | None = Field(default=None, max_length=2048)
    confirm: bool = False


class CallProcedureAsyncOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str
    session_id: int | None = None
    hint_es: str
    hint_en: str


@tool(
    name="nz_call_procedure_async",
    description=(
        "Launch a stored procedure via CALL in a background thread and return a job_id "
        "immediately without blocking. Use when the SP runs longer than a few seconds. "
        "Poll status with nz_job_poll(job_id) every 30 s. "
        "Cancellation is not available via MCP — a DBA can abort the session manually "
        "with nzsession using the session_id exposed by nz_job_poll. "
        "Requires admin mode and confirm=true. "
        "Do not use for short SPs — use nz_call_procedure instead."
    ),
    mode="admin",
    input_model=CallProcedureAsyncInput,
    output_model=CallProcedureAsyncOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_call_procedure_async(
    params: CallProcedureAsyncInput,
    *,
    config_path: Path | None = None,
) -> CallProcedureAsyncOutput:
    profile = get_active_profile(path=config_path)
    raw = launch_call_procedure(
        profile,
        database=params.database,
        schema=params.procedure_schema,
        procedure=params.procedure,
        args=list(params.args) if params.args is not None else None,
        signature=params.signature,
        confirm=params.confirm,
    )
    return CallProcedureAsyncOutput(**raw)


# ---------------------------------------------------------------------------
# nz_job_poll — poll status / retrieve result
# ---------------------------------------------------------------------------


class JobPollInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)


class JobPollOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str
    session_id: int | None = None
    elapsed_ms: int
    partial_notices: list[str] = Field(default_factory=list)
    return_value: str | None = None
    messages: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    error: dict[str, Any] | None = None


@tool(
    name="nz_job_poll",
    description=(
        "Poll the status of an async job started by nz_call_procedure_async. "
        "Returns status (running/done/failed/cancelling/cancelled) and the full result "
        "(return_value, messages, duration_ms) when done. "
        "partial_notices may be empty while the SP is running — nzpy delivers NOTICE "
        "messages with the resultset at completion, not incrementally. "
        "The job store is in-memory: all jobs are lost if the MCP server restarts. "
        "Do not poll more often than every 10 s. "
        "Do not use for jobs started by nz_call_procedure (synchronous)."
    ),
    mode="read",
    input_model=JobPollInput,
    output_model=JobPollOutput,
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def nz_job_poll(
    params: JobPollInput,
) -> JobPollOutput:
    raw = poll_job(params.job_id)
    return JobPollOutput(**raw)
