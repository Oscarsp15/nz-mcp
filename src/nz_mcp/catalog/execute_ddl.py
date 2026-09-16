"""Compile caller-supplied procedure/view DDL (admin) with ``sql_guard`` + env guard.

Unlike ``clone_procedure`` (which reconstructs DDL from catalog source), this path
takes a full ``CREATE [OR REPLACE] PROCEDURE`` (NZPLSQL) or ``CREATE [OR REPLACE]
VIEW`` written by the caller — inline or read from a file — and compiles it against
the active profile database. The NZPLSQL body is opaque to ``sql_guard`` (validated
via the header path); the environment guard rejects ``PROD_`` references from a
non-production session.
"""

from __future__ import annotations

import re
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import GuardRejectedError, InvalidInputError, NetezzaError
from nz_mcp.io import read_input_ddl
from nz_mcp.logging_utils import sanitize
from nz_mcp.sql_guard import StatementKind, assert_env_safe
from nz_mcp.sql_guard import validate as guard_validate

_NZPLSQL_MARKER: Final[re.Pattern[str]] = re.compile(r"\bLANGUAGE\s+NZPLSQL\s+AS\b", re.IGNORECASE)
_CREATE_VIEW_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b",
    re.IGNORECASE,
)
_CREATE_PROC_NAME: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+"
    r"(?P<schema>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
# Netezza NZPLSQL body compile errors — verified in-vivo against NPS SaaS:
# "plpgsql: ERROR during compile of PROC near line N" (some NPS versions)
# "ERROR:  syntax error, unexpected WORD, expecting BEGIN at or near ..." (NPS 11.x SaaS)
# A "syntax error" from CALL schema.proc() always means the body failed to compile;
# routing errors ("Function does not exist") contain "does not exist" instead.
_COMPILE_ERROR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"plpgsql|ERROR\s+during\s+compile|compile\s+of\b|syntax\s+error",
    re.IGNORECASE,
)
_COMPILE_WARNING: Final[str] = (
    "DDL accepted by server. NZPLSQL body compilation is deferred to the first CALL — "
    "a syntax error will only surface then. Pass validate_compile=true to force a check now."
)


def _extract_proc_ref(ddl: str) -> str | None:
    """Extract 'SCHEMA.PROCNAME' from a CREATE PROCEDURE header."""
    m = _CREATE_PROC_NAME.search(ddl)
    if m is None:
        return None
    return f"{m.group('schema')}.{m.group('name')}"


def _run_compile_check(
    profile: Profile,
    ddl: str,
    password: str,
) -> tuple[bool | None, str | None]:
    """Issue a zero-arg CALL to force NZPLSQL body compilation.

    Returns (compiled, compile_error). A compile-marker error means the body
    is invalid (compiled=False, compile_error set). Any other exception (e.g.
    wrong arg count) means the body compiled OK. Returns (None, None) when the
    proc name cannot be extracted from the DDL.
    """
    proc_ref = _extract_proc_ref(ddl)
    if proc_ref is None:
        return None, None
    conn = cast(_ConnectionLike, open_connection(profile, password))
    try:
        with closing(conn.cursor()) as cur:
            cur.execute(f"CALL {proc_ref}()", ())
        return True, None
    except Exception as exc:
        err_msg = sanitize(str(exc), known_secrets={password})
        if _COMPILE_ERROR_PATTERN.search(err_msg):
            return False, err_msg
        return True, None
    finally:
        conn.close()


class _CursorLike(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def _resolve_ddl(sql: str | None, input_path: str | None) -> str:
    """Return the DDL text from exactly one of ``sql`` / ``input_path``."""
    if (sql is None) == (input_path is None):
        raise InvalidInputError(
            detail="Provide exactly one of 'sql' or 'input_path' for nz_execute_ddl.",
        )
    if input_path is not None:
        try:
            text = read_input_ddl(input_path)
        except (ValueError, FileNotFoundError, IsADirectoryError) as exc:
            raise InvalidInputError(detail=str(exc)) from exc
    else:
        text = sql if sql is not None else ""
    stripped = text.strip()
    if not stripped:
        raise InvalidInputError(detail="The DDL to execute is empty.")
    return stripped


def _assert_type_matches(ddl: str, statement_type: str) -> None:
    """Ensure the DDL shape matches the declared ``statement_type``."""
    has_marker = _NZPLSQL_MARKER.search(ddl) is not None
    if statement_type == "procedure":
        if not has_marker:
            raise InvalidInputError(
                detail=(
                    "statement_type='procedure' requires a CREATE PROCEDURE ... "
                    "LANGUAGE NZPLSQL AS statement."
                ),
            )
    elif statement_type == "view":
        if has_marker or _CREATE_VIEW_HEAD.match(ddl) is None:
            raise InvalidInputError(
                detail="statement_type='view' requires a CREATE [OR REPLACE] VIEW statement.",
            )
    else:
        raise InvalidInputError(detail="statement_type must be 'procedure' or 'view'.")


def execute_ddl(
    profile: Profile,
    *,
    sql: str | None,
    input_path: str | None,
    statement_type: str,
    dry_run: bool,
    confirm: bool,
    allow_prod_reads: bool = False,
    echo_sql: bool = True,
    validate_compile: bool = False,
) -> dict[str, Any]:
    """Validate and (optionally) compile a procedure/view DDL against the active DB.

    When ``echo_sql`` is false the real-execution branch omits the full DDL from the
    response (``sql_to_execute`` becomes ``None``), so callers can compile in batch
    without the whole statement being echoed back into their context. The ``dry_run``
    branch always returns the SQL regardless of ``echo_sql``: the preview is its point.

    When ``allow_prod_reads`` is true the ``PROD_REF_IN_NONPROD`` environment guard
    is skipped: the caller certifies it has already flipped every write target to the
    active (non-production) database and that any remaining ``PROD_`` references are
    read-only. Compiling a CREATE statement is inert — real writes only happen on
    CALL — so this only relaxes the compile-time textual scan, not runtime behaviour.
    All other validations (single statement, well-formed header, admin mode,
    statement_type) still apply. Default false preserves the fail-closed behaviour.

    Netezza compiles NZPLSQL bodies lazily: ``executed=true`` means the server accepted
    the DDL, not that the body is syntactically valid. When ``statement_type="procedure"``
    the result always carries a ``compile_warning`` explaining this. When
    ``validate_compile=true`` the function issues a zero-arg ``CALL schema.proc()``
    immediately after the CREATE to force compilation; a compile error is returned in
    ``compile_error`` and ``compiled`` is set to ``False``. If the error is not a compile
    error (e.g. wrong number of arguments), the body compiled successfully and
    ``compiled`` is ``True``. Note: if the procedure takes zero args and the body is
    valid, the CALL will actually execute it — callers opt in to that side effect.
    """
    ddl = _resolve_ddl(sql, input_path)
    _assert_type_matches(ddl, statement_type)

    parsed = guard_validate(ddl, mode="admin")
    if parsed.kind is not StatementKind.CREATE:
        raise GuardRejectedError(
            code="WRONG_STATEMENT_FOR_TOOL",
            tool="nz_execute_ddl",
            kind=str(parsed.kind),
        )

    if not allow_prod_reads:
        assert_env_safe(parsed.raw, active_database=profile.database)

    if dry_run:
        return {
            "dry_run": True,
            "sql_to_execute": parsed.raw,
            "executed": False,
            "duration_ms": 0,
        }

    if not confirm:
        raise InvalidInputError(
            code="CONFIRM_REQUIRED",
            detail="confirm=true is required when dry_run=false for nz_execute_ddl.",
        )

    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(parsed.raw, ())
    except NetezzaError:
        raise
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_ddl",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)

    compile_warning: str | None = None
    compile_error: str | None = None
    compiled: bool | None = None

    if statement_type == "procedure":
        compile_warning = _COMPILE_WARNING
        if validate_compile:
            compiled, compile_error = _run_compile_check(profile, ddl, password)

    return {
        "dry_run": False,
        "sql_to_execute": parsed.raw if echo_sql else None,
        "executed": True,
        "duration_ms": duration_ms,
        "compile_warning": compile_warning,
        "compile_error": compile_error,
        "compiled": compiled,
    }
