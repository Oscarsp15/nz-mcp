"""Execute validated read-only SQL against Netezza (SELECT stream + EXPLAIN text)."""

from __future__ import annotations

import json
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

import sqlglot
from nzpy import ProgrammingError
from sqlglot import expressions as exp

from nz_mcp.auth import get_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import NetezzaError
from nz_mcp.logging_utils import sanitize

FETCH_BATCH: Final[int] = 200
RESPONSE_BYTES_CAP: Final[int] = 100 * 1024

# Common PostgreSQL / Netezza type OIDs (driver may return OID ints in cursor.description).
_TYPE_OID_TO_NAME: Final[dict[int, str]] = {
    16: "bool",
    19: "name",
    20: "bigint",
    21: "smallint",
    23: "integer",
    25: "text",
    700: "real",
    701: "double precision",
    1042: "char",
    1043: "varchar",
    1082: "date",
    1114: "timestamp",
    1700: "numeric",
}


class _CursorLike(Protocol):
    description: Any

    def execute(self, sql: str) -> None: ...
    def fetchmany(self, size: int) -> list[Any]: ...
    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    def cursor(self) -> _CursorLike: ...
    def close(self) -> None: ...


def inject_limit(sql: str, max_rows: int) -> str:
    """Return SQL with ``LIMIT`` applied or lowered to ``max_rows`` when already present."""
    expr = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(expr, (exp.Select, exp.Union)):
        raise ValueError("inject_limit expects a SELECT or UNION statement")
    current: int | None = None
    lim = expr.args.get("limit")
    if isinstance(lim, exp.Limit):
        lit = lim.this
        if isinstance(lit, exp.Literal):
            try:
                current = int(lit.this)
            except (TypeError, ValueError):
                current = None
    applied = max_rows if current is None else min(current, max_rows)
    limited = expr.limit(applied)
    return limited.sql(dialect="postgres")


def execute_select(
    profile: Profile,
    sql: str,
    *,
    max_rows: int,
    timeout_s: int,
) -> dict[str, Any]:
    """Run a single validated SELECT, streaming rows until caps or deadline."""
    password = get_password(profile.name)
    exec_profile = profile.model_copy(update={"timeout_s_default": timeout_s})

    deadline = time.monotonic() + timeout_s
    columns_meta: list[dict[str, str]] = []
    rows: list[list[Any]] = []
    truncated = False
    hint_key: str | None = None
    hint_fmt: dict[str, object] = {}

    connection = cast(_ConnectionLike, open_connection(exec_profile, password))
    start = time.monotonic()
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql)
            columns_meta = _column_meta_from_cursor(cursor)
            remaining = max_rows

            while remaining > 0:
                if time.monotonic() > deadline:
                    truncated = True
                    hint_key = "HINT.RESULT_TRUNCATED_BY_TIMEOUT"
                    hint_fmt = {"timeout_s": timeout_s}
                    break
                batch = cursor.fetchmany(min(FETCH_BATCH, remaining))
                if not batch:
                    break
                for raw in batch:
                    row_cells = list(raw) if isinstance(raw, (tuple, list)) else [raw]
                    rows.append(row_cells)
                    remaining -= 1
                    if _approx_rows_json_bytes(rows) >= RESPONSE_BYTES_CAP:
                        truncated = True
                        hint_key = "HINT.RESULT_TRUNCATED_BY_BYTES"
                        hint_fmt = {"max_kb": RESPONSE_BYTES_CAP // 1024}
                        break
                    if remaining <= 0:
                        truncated = True
                        hint_key = "HINT.RESULT_TRUNCATED_BY_ROWS"
                        hint_fmt = {"n": max_rows}
                        break
                if truncated:
                    break

    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="execute_select",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()

    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "columns": columns_meta,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "duration_ms": duration_ms,
        "hint_key": hint_key,
        "hint_fmt": hint_fmt,
    }


def fetch_explain_text(profile: Profile, explain_sql: str) -> str:
    """Execute ``EXPLAIN`` / ``EXPLAIN VERBOSE`` and return plan text.

    On some NPS versions the plan is delivered as server notices (no row description);
    nzpy then raises ``ProgrammingError: no result set`` on fetch — we join ``cursor.notices``.
    """
    password = get_password(profile.name)
    connection = cast(_ConnectionLike, open_connection(profile, password))
    chunks: list[str] = []
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute(explain_sql)
            try:
                while True:
                    batch = cursor.fetchmany(FETCH_BATCH)
                    if not batch:
                        break
                    for raw in batch:
                        cell = (raw[0] if raw else "") if isinstance(raw, (tuple, list)) else raw
                        chunks.append("" if cell is None else str(cell))
            except ProgrammingError as exc:
                if "no result set" not in str(exc).lower():
                    raise
            if chunks:
                return "\n".join(chunks).strip()
            notice_texts = list(getattr(cursor, "notices", None) or [])
            if notice_texts:
                return "\n".join(n.strip() for n in notice_texts if n).strip()
            return ""
    except Exception as exc:  # noqa: BLE001, RUF100
        raise NetezzaError(
            operation="explain",
            database=profile.database,
            detail=sanitize(str(exc), known_secrets={password}),
        ) from exc
    finally:
        connection.close()


def _type_label_from_oid_cell(cell: Any) -> str:
    if isinstance(cell, int):
        return _TYPE_OID_TO_NAME.get(cell, str(cell))
    if isinstance(cell, str) and cell.isdigit():
        oid = int(cell)
        return _TYPE_OID_TO_NAME.get(oid, cell)
    if cell is None:
        return "unknown"
    return str(cell)


def _column_meta_from_cursor(cursor: _CursorLike) -> list[dict[str, str]]:
    _min_parts = 2
    desc = getattr(cursor, "description", None)
    if not desc:
        return []
    out: list[dict[str, str]] = []
    for col in desc:
        if isinstance(col, (tuple, list)) and len(col) >= _min_parts:
            name = str(col[0]) if col[0] is not None else ""
            ctype = _type_label_from_oid_cell(col[1])
            out.append({"name": name, "type": ctype})
        elif isinstance(col, (tuple, list)) and len(col) >= 1:
            out.append({"name": str(col[0]), "type": "unknown"})
        else:
            out.append({"name": str(col), "type": "unknown"})
    return out


def _approx_rows_json_bytes(rows: list[list[Any]]) -> int:
    return len(json.dumps(rows, default=str).encode("utf-8"))
