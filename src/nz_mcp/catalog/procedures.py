"""Catalog access for stored procedures (``_V_PROCEDURE``)."""

from __future__ import annotations

import re
from contextlib import closing
from typing import Any, Final, Protocol, cast

from nz_mcp.auth import get_password
from nz_mcp.catalog.identifier import render_cross_db, validate_catalog_identifier
from nz_mcp.catalog.nzplsql_parser import (
    find_begin_proc_line,
    header_content,
    line_slice,
    parse_sections,
)
from nz_mcp.catalog.resolver import resolve_query
from nz_mcp.catalog.row_shape import is_sequence_row
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import (
    InvalidInputError,
    NetezzaError,
    ObjectNotFoundError,
    OverloadAmbiguousError,
    SectionNotFoundError,
)
from nz_mcp.logging_utils import sanitize

_MAX_RANGE_LINES: Final[int] = 500
_MIN_TOKENS_NAMED_ARG: Final[int] = 2

_ROW_LIST_MIN: Final[int] = 6

# Column order from ``GET_PROCEDURE_DDL`` / ``GET_PROCEDURE_SECTION`` SELECT.
_DDL_TUPLE_INDEX: Final[dict[str, int]] = {
    "PROCEDURE": 0,
    "OWNER": 1,
    "ARGUMENTS": 2,
    "RETURNS": 3,
    "PROCEDURESOURCE": 4,
    "PROCEDURESIGNATURE": 5,
}


class _ListCursor(Protocol):
    def execute(
        self,
        sql: str,
        params: tuple[str, str | None, str | None],
    ) -> None: ...

    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _OneCursor(Protocol):
    def execute(self, sql: str, params: tuple[str, str]) -> None: ...
    def fetchall(self) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionList(Protocol):
    def cursor(self) -> _ListCursor: ...
    def close(self) -> None: ...


class _ConnectionOne(Protocol):
    def cursor(self) -> _OneCursor: ...
    def close(self) -> None: ...


def list_procedures(
    profile: Profile,
    database: str,
    schema: str,
    pattern: str | None = None,
) -> list[dict[str, str]]:
    """Return procedures from ``_v_procedure`` for ``database`` / ``schema``."""
    validate_catalog_identifier(schema)
    like_pattern = pattern if pattern else None
    params: tuple[str, str | None, str | None] = (schema, like_pattern, like_pattern)
    password = get_password(profile.name)
    base_sql = resolve_query("list_procedures", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionList, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="list_procedures",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    return [_row_to_list_item(row) for row in rows]


def describe_procedure(
    profile: Profile,
    database: str,
    schema: str,
    procedure: str,
    signature: str | None = None,
) -> dict[str, Any]:
    """Return procedure metadata without exposing the full body text."""
    rows = _fetch_procedure_rows(profile, database, schema, procedure)
    row = _pick_procedure_row(rows, signature, procedure)
    source = _ddl_get(row, "PROCEDURESOURCE")
    sections = parse_sections(source)
    lines = 0 if not source else len(source.splitlines())
    arg_struct = parse_procedure_arguments(_ddl_get(row, "ARGUMENTS"))

    owner = _ddl_get(row, "OWNER")
    name = _ddl_get(row, "PROCEDURE")
    returns = _ddl_get(row, "RETURNS")

    detected: list[str] = []
    for key in ("header", "declare", "body", "exception"):
        if key in sections:
            detected.append(key)

    return {
        "name": name,
        "owner": owner,
        "language": "NZPLSQL",
        "arguments": arg_struct,
        "returns": returns,
        "created_at": None,
        "lines": lines,
        "sections_detected": detected,
    }


def get_procedure_ddl(
    profile: Profile,
    database: str,
    schema: str,
    procedure: str,
    signature: str | None = None,
) -> str:
    """Return reconstructed ``CREATE OR REPLACE PROCEDURE`` DDL text."""
    rows = _fetch_procedure_rows(profile, database, schema, procedure)
    row = _pick_procedure_row(rows, signature, procedure)
    return _build_procedure_ddl(schema, row)


def get_procedure_section(
    profile: Profile,
    database: str,
    schema: str,
    procedure: str,
    section: str,
    signature: str | None = None,
    from_line: int | None = None,
    to_line: int | None = None,
) -> dict[str, Any]:
    """Extract a slice of ``PROCEDURESOURCE`` by logical section or raw line range."""
    rows = _fetch_procedure_rows(profile, database, schema, procedure)
    row = _pick_procedure_row(rows, signature, procedure)
    source = _ddl_get(row, "PROCEDURESOURCE")

    if section == "range":
        if from_line is None or to_line is None:
            raise InvalidInputError(
                detail="from_line and to_line are required when section is 'range'.",
            )
        if from_line < 1 or to_line < from_line:
            raise InvalidInputError(detail="Invalid line range for section 'range'.")
        truncated = (to_line - from_line + 1) > _MAX_RANGE_LINES
        eff_to = min(to_line, from_line + _MAX_RANGE_LINES - 1) if truncated else to_line
        content = line_slice(source, from_line, eff_to)
        return {
            "section": "range",
            "from_line": from_line,
            "to_line": eff_to,
            "content": content,
            "truncated": truncated,
        }

    sections = parse_sections(source)
    begin_proc_line = find_begin_proc_line(source)

    if section == "header":
        if begin_proc_line is None:
            raise SectionNotFoundError(section="header")
        text = header_content(source, begin_proc_line)
        if not text.strip():
            raise SectionNotFoundError(section="header")
        end_ln = begin_proc_line if begin_proc_line > 1 else 1
        return {
            "section": "header",
            "from_line": 1,
            "to_line": end_ln,
            "content": text,
            "truncated": False,
        }

    if section not in ("declare", "body", "exception"):
        raise InvalidInputError(detail=f"Unknown section {section!r}.")

    if section == "body" and "body" not in sections:
        raise SectionNotFoundError(section="body")

    if section not in sections:
        raise SectionNotFoundError(section=section)

    start, end = sections[section]
    content = line_slice(source, start, end)
    return {
        "section": section,
        "from_line": start,
        "to_line": end,
        "content": content,
        "truncated": False,
    }


def parse_procedure_arguments(arguments: str) -> list[dict[str, str]]:
    """Parse ``_V_PROCEDURE.ARGUMENTS`` into ``[{name, type}, ...]``."""
    raw = arguments.strip()
    if not raw or raw.upper() == "NULL":
        return []
    inner = raw[1:-1] if raw.startswith("(") and raw.endswith(")") else raw
    parts = _split_top_level_commas(inner)
    out: list[dict[str, str]] = []
    for i, part in enumerate(parts):
        chunk = part.strip()
        if not chunk:
            continue
        tokens = chunk.split()
        if len(tokens) >= _MIN_TOKENS_NAMED_ARG and re.match(
            r"^[A-Za-z_][A-Za-z0-9_]*$", tokens[0]
        ):
            out.append({"name": tokens[0], "type": " ".join(tokens[1:])})
        else:
            out.append({"name": f"arg{i + 1}", "type": chunk})
    return out


def _split_top_level_commas(s: str) -> list[str]:
    depth = 0
    cur: list[str] = []
    parts: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def _normalize_signature(sig: str) -> str:
    """Normalize overload signatures for comparison (spacing-insensitive)."""
    return "".join(sig.upper().split())


def _fetch_procedure_rows(
    profile: Profile,
    database: str,
    schema: str,
    procedure: str,
) -> list[Any]:
    validate_catalog_identifier(schema)
    validate_catalog_identifier(procedure)
    params: tuple[str, str] = (schema, procedure)
    password = get_password(profile.name)
    base_sql = resolve_query("get_procedure_ddl", profile)
    sql = render_cross_db(base_sql, database=database)

    connection = cast(_ConnectionOne, open_connection(profile, password))
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="get_procedure_ddl",
            database=database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    if not rows:
        raise ObjectNotFoundError(
            detail=(
                "No procedure row returned — object may not exist or may not be visible "
                f"(database={database!r}, schema={schema!r}, procedure={procedure!r})."
            ),
        )
    return rows


def _pick_procedure_row(rows: list[Any], signature: str | None, procedure: str) -> Any:
    if len(rows) == 1:
        only = rows[0]
        if signature is None:
            return only
        got = _normalize_signature(_ddl_get(only, "PROCEDURESIGNATURE"))
        if got == _normalize_signature(signature):
            return only
        raise ObjectNotFoundError(
            detail=(f"No procedure overload matches signature {signature!r} for {procedure!r}."),
        )

    sigs = [_normalize_signature(_ddl_get(r, "PROCEDURESIGNATURE")) for r in rows]
    if signature is None:
        unique = {s for s in sigs if s}
        if len(unique) <= 1:
            return rows[0]
        raise OverloadAmbiguousError(procedure=procedure, signatures=sorted(unique))

    want = _normalize_signature(signature)
    matches = [r for r in rows if _normalize_signature(_ddl_get(r, "PROCEDURESIGNATURE")) == want]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ObjectNotFoundError(
            detail=(f"No procedure overload matches signature {signature!r} for {procedure!r}."),
        )
    raise OverloadAmbiguousError(procedure=procedure, signatures=sigs)


def _row_to_list_item(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        proc = row.get("PROCEDURE") or row.get("procedure")
        owner = row.get("OWNER") or row.get("owner")
        args = row.get("ARGUMENTS") or row.get("arguments")
        ret = row.get("RETURNS") or row.get("returns")
        if proc is None or owner is None:
            raise NetezzaError(
                operation="list_procedures",
                detail="Unexpected row shape from _v_procedure",
            )
        return {
            "name": str(proc),
            "owner": str(owner),
            "language": "NZPLSQL",
            "arguments": "" if args is None else str(args),
            "returns": "" if ret is None else str(ret),
        }
    if is_sequence_row(row, _ROW_LIST_MIN):
        return {
            "name": str(row[0]),
            "owner": str(row[1]),
            "language": "NZPLSQL",
            "arguments": str(row[2]),
            "returns": str(row[3]),
        }
    raise NetezzaError(operation="list_procedures", detail="Unexpected row shape from _v_procedure")


def _ddl_get(row: Any, field: str) -> str:
    if isinstance(row, dict):
        lower = field.lower()
        for k in (field, lower):
            if k in row and row[k] is not None:
                return str(row[k])
        return ""
    idx = _DDL_TUPLE_INDEX.get(field)
    if idx is not None and is_sequence_row(row, idx + 1):
        cell = row[idx]
        return "" if cell is None else str(cell)
    return ""


def _build_procedure_ddl(schema: str, row: Any) -> str:
    proc = _ddl_get(row, "PROCEDURE").strip()
    args = _ddl_get(row, "ARGUMENTS").strip()
    returns = _ddl_get(row, "RETURNS").strip()
    source = _ddl_get(row, "PROCEDURESOURCE")
    sig = _ddl_get(row, "PROCEDURESIGNATURE").strip()
    sig_use = sig if sig else (f"({args})" if args else "()")
    sch = validate_catalog_identifier(schema)
    ret_clause = f"RETURNS {returns}" if returns else ""
    head = f"CREATE OR REPLACE PROCEDURE {sch}.{proc}{sig_use}"
    if ret_clause:
        head = f"{head}\n{ret_clause}"
    return f"{head}\nLANGUAGE NZPLSQL AS\n{source}"
