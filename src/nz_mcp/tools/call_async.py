"""Async stored-procedure tools: launch and poll."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nz_mcp.auth import get_password
from nz_mcp.catalog.call_async import cancel_job, launch_call_procedure, poll_job
from nz_mcp.config import get_active_profile
from nz_mcp.errors import InvalidInputError
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
        "Poll status with nz_job_poll(job_id) every 30 s; cancel with nz_job_cancel(job_id). "
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
        "Returns status (running/done/failed/cancelling/cancelled), partial_notices "
        "while running, and the full result (return_value, messages, duration_ms) on done. "
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


# ---------------------------------------------------------------------------
# nz_job_cancel — abort a running job via ABORT SESSION
# ---------------------------------------------------------------------------


class JobCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    confirm: bool = False


class JobCancelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str
    previous_status: str | None = None
    session_id: int | None = None
    abort_error: str | None = None
    message_es: str
    message_en: str


@tool(
    name="nz_job_cancel",
    description=(
        "Cancel a running async job by sending ABORT SESSION to Netezza via a second admin "
        "connection. Requires confirm=true. "
        "Returns status='cancelling' (ABORT sent) or 'already_done' (job already finished). "
        "If ABORT fails (permissions), abort_error describes the problem and the session_id is "
        "returned so a DBA can run ABORT SESSION <session_id> manually. "
        "Only works for jobs launched by nz_call_procedure_async."
    ),
    mode="admin",
    input_model=JobCancelInput,
    output_model=JobCancelOutput,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def nz_job_cancel(
    params: JobCancelInput,
    *,
    config_path: Path | None = None,
) -> JobCancelOutput:
    if not params.confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required for nz_job_cancel.",
        )
    profile = get_active_profile(path=config_path)
    password = get_password(profile.name)
    raw = cancel_job(params.job_id, profile=profile, password=password)
    return JobCancelOutput(**raw)
