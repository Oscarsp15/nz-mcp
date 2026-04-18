"""Clone stored procedures between databases/schemas (admin DDL)."""

from __future__ import annotations

import hashlib
import re
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

import structlog

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import validate_catalog_identifier, validate_database_identifier
from nz_mcp.catalog.procedures import get_procedure_ddl, list_procedures
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import InvalidInputError, NetezzaError, ProcedureAlreadyExistsError
from nz_mcp.logging_utils import sanitize
from nz_mcp.procedure_head_pattern import PROCEDURE_PARAM_LIST_PATTERN
from nz_mcp.sql_guard import StatementKind
from nz_mcp.sql_guard import validate as guard_validate

_LOG = structlog.get_logger(__name__)
_MARKER: Final[str] = "\nLANGUAGE NZPLSQL AS\n"
_MAX_TRANSFORMS: Final[int] = 20
_MIN_LINES_FOR_RETURNS: Final[int] = 2
_DEFAULT_STRING_TYPE_LENGTH: Final[int] = 4000

# Heuristic: ``OTHERDB..OBJECT`` cross-database references in procedure body.
_CROSS_DB: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<db>[A-Z][A-Z0-9_]{0,127})\.\.(?P<rest>[A-Z][A-Z0-9_.]*)",
    re.IGNORECASE,
)


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _split_ddl_head_body(ddl: str) -> tuple[str, str]:
    if _MARKER not in ddl:
        raise InvalidInputError(
            detail="Procedure DDL missing LANGUAGE NZPLSQL AS marker — cannot split header/body.",
        )
    head, body = ddl.split(_MARKER, 1)
    return head.strip(), body


def _parse_first_procedure_line(line: str) -> tuple[str, str, str]:
    """Return schema, procedure, signature including parentheses."""
    m = re.match(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+"
        r"(?P<sch>[A-Z][A-Z0-9_]*)\.(?P<proc>[A-Z][A-Z0-9_]*)"
        rf"(?P<sig>{PROCEDURE_PARAM_LIST_PATTERN})\s*$",
        line.strip(),
        re.I,
    )
    if not m:
        raise InvalidInputError(detail="Could not parse CREATE PROCEDURE header line from DDL.")
    return (
        m.group("sch").upper(),
        m.group("proc").upper(),
        m.group("sig"),
    )


def _wrap_nzplsql_body(body: str) -> str:
    """Wrap raw procedure body for CREATE execution (catalog source omits delimiters)."""
    stripped = body.strip()
    if re.match(r"^\s*BEGIN_PROC\b", stripped, re.IGNORECASE) and re.search(
        r"\bEND_PROC\s*;?\s*$",
        stripped,
        re.IGNORECASE,
    ):
        return body
    return f"BEGIN_PROC\n{stripped}\nEND_PROC;\n"


def _extract_returns(head_block: str) -> str | None:
    lines = head_block.strip().splitlines()
    if len(lines) < _MIN_LINES_FOR_RETURNS:
        return None
    for ln in lines[1:]:
        if ln.strip().upper().startswith("RETURNS"):
            return ln.strip()
    return None


def _normalize_returns_for_netezza(returns_line: str | None) -> tuple[str | None, list[str]]:
    """Append default max length when catalog string types lack ``(n)`` (Netezza requires)."""
    if returns_line is None:
        return None, []
    warnings: list[str] = []
    stripped = returns_line.strip()
    n = _DEFAULT_STRING_TYPE_LENGTH
    if re.match(r"^RETURNS\s+VARCHAR\s*$", stripped, re.IGNORECASE):
        warnings.append(
            "RETURNS VARCHAR had no length in catalog DDL; "
            f"appended default ({n}) for Netezza execution.",
        )
        return f"RETURNS VARCHAR({n})", warnings
    if re.match(r"^RETURNS\s+CHARACTER\s+VARYING\s*$", stripped, re.IGNORECASE):
        warnings.append(
            f"RETURNS CHARACTER VARYING had no length in catalog DDL; appended default ({n}).",
        )
        return f"RETURNS CHARACTER VARYING({n})", warnings
    if re.match(r"^RETURNS\s+CHAR\s+VARYING\s*$", stripped, re.IGNORECASE):
        warnings.append(
            f"RETURNS CHAR VARYING had no length in catalog DDL; appended default ({n}).",
        )
        return f"RETURNS CHAR VARYING({n})", warnings
    return returns_line, []


def _apply_transformations(
    body: str,
    transformations: list[dict[str, Any]] | None,
) -> tuple[str, list[str]]:
    if not transformations:
        return body, []
    warnings: list[str] = []
    out = body
    for i, t in enumerate(transformations):
        from_s = str(t.get("from", ""))
        to_s = str(t.get("to", ""))
        use_regex = bool(t.get("regex", False))
        if not from_s:
            raise InvalidInputError(detail=f"Transformation {i}: 'from' must be non-empty.")
        if use_regex:
            try:
                pattern = re.compile(from_s)
            except re.error as exc:
                raise InvalidInputError(detail=f"Transformation {i}: invalid regex: {exc}") from exc
            if pattern.search(out) is None:
                warnings.append(f"Transformation {i}: regex matched no occurrences.")
            else:
                out = pattern.sub(to_s, out)
        elif from_s not in out:
            warnings.append(f"Transformation {i}: literal not found in body.")
        else:
            out = out.replace(from_s, to_s)
    return out, warnings


def _cross_db_warnings(body: str, target_database: str) -> list[str]:
    td = validate_database_identifier(target_database)
    seen: set[str] = set()
    out: list[str] = []
    for m in _CROSS_DB.finditer(body):
        db = m.group("db").upper()
        if db == td:
            continue
        key = m.group(0).upper()
        if key not in seen:
            seen.add(key)
            out.append(
                f"Body references cross-database notation {m.group(0)!r} — verify or rewrite for "
                f"database {td}.",
            )
    return out


def _procedure_named_exists(
    profile: Profile,
    database: str,
    schema: str,
    proc_name: str,
) -> bool:
    validate_catalog_identifier(schema)
    validate_catalog_identifier(proc_name)
    rows = list_procedures(profile, database, schema, pattern=None)
    pnu = proc_name.upper()
    return any(str(r.get("name", "")).upper() == pnu for r in rows)


def _build_target_ddl(
    *,
    head_block: str,
    body: str,
    target_schema: str,
    target_procedure: str,
    replace_if_exists: bool,
) -> tuple[str, list[str]]:
    lines = head_block.strip().splitlines()
    if not lines:
        raise InvalidInputError(detail="Empty procedure header.")
    _sch, _proc, sig = _parse_first_procedure_line(lines[0])
    ret = _extract_returns(head_block)
    ret, ret_warnings = _normalize_returns_for_netezza(ret)
    ts = validate_catalog_identifier(target_schema)
    tp = validate_catalog_identifier(target_procedure)
    kw = "CREATE OR REPLACE PROCEDURE" if replace_if_exists else "CREATE PROCEDURE"
    new_head = f"{kw} {ts}.{tp}{sig}"
    if ret:
        new_head = f"{new_head}\n{ret}"
    wrapped = _wrap_nzplsql_body(body)
    return f"{new_head}{_MARKER}{wrapped}", ret_warnings


def clone_procedure(
    profile: Profile,
    *,
    source_database: str,
    source_schema: str,
    source_procedure: str,
    source_signature: str | None,
    target_database: str,
    target_schema: str,
    target_procedure: str | None,
    replace_if_exists: bool,
    transformations: list[dict[str, Any]] | None,
    dry_run: bool,
    confirm: bool,
) -> dict[str, Any]:
    """Orchestrate procedure clone; returns a dict for MCP tool output."""
    if transformations is not None and len(transformations) > _MAX_TRANSFORMS:
        raise InvalidInputError(
            detail=f"At most {_MAX_TRANSFORMS} transformations allowed.",
        )

    sdb = validate_database_identifier(source_database)
    tdb = validate_database_identifier(target_database)
    ssch = validate_catalog_identifier(source_schema)
    tsch = validate_catalog_identifier(target_schema)
    sproc = validate_catalog_identifier(source_procedure)
    tproc = validate_catalog_identifier(target_procedure) if target_procedure else sproc

    source_ddl = get_procedure_ddl(profile, sdb, ssch, sproc, source_signature)
    head_block, body = _split_ddl_head_body(source_ddl)
    body, tw = _apply_transformations(body, transformations)
    xw = _cross_db_warnings(body, tdb)
    warnings = tw + xw

    target_ddl, ret_warnings = _build_target_ddl(
        head_block=head_block,
        body=body,
        target_schema=tsch,
        target_procedure=tproc,
        replace_if_exists=replace_if_exists,
    )
    warnings = warnings + ret_warnings

    parsed = guard_validate(target_ddl, mode="admin")
    if parsed.kind is not StatementKind.CREATE:
        raise NetezzaError(
            operation="clone_procedure",
            detail=f"Clone DDL classified as {parsed.kind}, expected CREATE.",
        )

    if _procedure_named_exists(profile, tdb, tsch, tproc) and not replace_if_exists:
        raise ProcedureAlreadyExistsError(
            database=tdb,
            schema=tsch,
            procedure=tproc,
            detail=f"Procedure {tsch}.{tproc} already exists in {tdb}.",
        )

    ddl_hash = hashlib.sha256(target_ddl.encode("utf-8")).hexdigest()
    _LOG.info(
        "clone_procedure_plan",
        source_database=sdb,
        source_schema=ssch,
        source_procedure=sproc,
        target_database=tdb,
        target_schema=tsch,
        target_procedure=tproc,
        ddl_hash=ddl_hash,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "dry_run": True,
            "ddl_to_execute": target_ddl,
            "executed": False,
            "warnings": warnings,
            "duration_ms": None,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_clone_procedure.",
        )

    exec_profile = profile.model_copy(update={"database": tdb})
    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(exec_profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="clone_procedure",
            database=tdb,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()
    duration_ms = int((time.monotonic() - start) * 1000)

    if not _procedure_named_exists(profile, tdb, tsch, tproc):
        raise NetezzaError(
            operation="clone_procedure",
            detail="Procedure was executed but is not visible on target after create.",
        )

    _LOG.info(
        "clone_procedure_executed",
        target_database=tdb,
        target_schema=tsch,
        target_procedure=tproc,
        ddl_hash=ddl_hash,
        duration_ms=duration_ms,
    )

    return {
        "dry_run": False,
        "ddl_to_execute": target_ddl,
        "executed": True,
        "warnings": warnings,
        "duration_ms": duration_ms,
    }
