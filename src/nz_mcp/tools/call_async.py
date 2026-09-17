"""Async stored-procedure tools: launch and poll."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.catalog.call import ReturnScalar
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
    session_id: int | None = Field(
        default=None,
        description=(
            "Netezza session ID (SELECT CURRENT_SID). Always null at launch: the "
            "background thread hasn't opened the connection yet. Appears in the first "
            "nz_job_poll response."
        ),
    )
    poll_after_s: int = Field(
        description="Suggested delay before the first nz_job_poll call, in seconds. "
        "Not a fixed 30 s — grows the longer the job keeps running."
    )
    hint_es: str
    hint_en: str


@tool(
    name="nz_call_procedure_async",
    description=(
        "Launch a stored procedure via CALL in a background thread and return a job_id "
        "immediately without blocking. Use when the SP runs longer than a few seconds. "
        "Poll with nz_job_poll(job_id) using its poll_after_s as the delay, not a fixed "
        "30 s. Cancellation isn't available via MCP — a DBA can abort with nzsession "
        "using the session_id from nz_job_poll. Requires admin mode and confirm=true. "
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
    elapsed_ms: int = Field(
        description="Wall-clock time since nz_call_procedure_async was called "
        "(includes connection setup, not just the SP itself). Keeps growing every poll."
    )
    poll_after_s: int | None = Field(
        default=None,
        description="Suggested delay before the next poll, in seconds. "
        "null once the job is done/failed/cancelled — no need to poll again.",
    )
    partial_notices: list[str] = Field(default_factory=list)
    return_value: ReturnScalar = None
    messages: list[str] = Field(default_factory=list)
    duration_ms: int | None = Field(
        default=None,
        description="How long the CALL itself took inside Netezza, in milliseconds. "
        "Only set once status == 'done' — this is the number that answers "
        "'how long did the SP take', not elapsed_ms.",
    )
    error: dict[str, Any] | None = None


@tool(
    name="nz_job_poll",
    description=(
        "Polls an async job from nz_call_procedure_async: status "
        "(running/done/failed/cancelling/cancelled) and the full result when done. "
        "elapsed_ms is wall-clock time since launch; duration_ms is the CALL's own time "
        "inside Netezza (set only when done) — don't confuse them. Use poll_after_s "
        "as the next delay, not a fixed interval. partial_notices may be empty while "
        "running (NOTICEs arrive with the resultset at completion). Job store is "
        "in-memory, lost on restart. Not for nz_call_procedure (synchronous)."
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
