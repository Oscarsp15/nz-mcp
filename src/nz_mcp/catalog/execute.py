"""Execute validated read-only SQL against Netezza (SELECT stream + EXPLAIN text)."""

from __future__ import annotations

import json
import time
from contextlib import closing
from typing import Any, Final, Protocol, cast

import sqlglot
from nzpy import ProgrammingError
from sqlglot import Token, TokenType
from sqlglot import expressions as exp

from nz_mcp.auth import get_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import GuardRejectedError, NetezzaError
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


def _statement_body(sql: str, tokens: list[Token]) -> str:
    """Return ``sql`` without its trailing semicolon, so a clause can be appended."""
    if tokens and tokens[-1].token_type is TokenType.SEMICOLON:
        return sql[: tokens[-1].start].rstrip()
    return sql.rstrip()


def _top_level_limit_index(tokens: list[Token]) -> int | None:
    """Return the index of the statement-level ``LIMIT`` keyword, if there is one.

    A ``LIMIT`` inside parentheses belongs to a subquery or a CTE and is left alone.
    """
    depth = 0
    for index, tok in enumerate(tokens):
        if tok.token_type is TokenType.L_PAREN:
            depth += 1
        elif tok.token_type is TokenType.R_PAREN:
            depth -= 1
        elif tok.token_type is TokenType.LIMIT and depth == 0:
            return index
    return None


def _limit_value_span(
    tokens: list[Token],
    limit_index: int,
    limit: exp.Limit | None,
) -> tuple[int, int, int | None]:
    """Return ``(start, end, row_count)`` for a ``LIMIT`` whose value is a single token.

    ``row_count`` is ``None`` for ``LIMIT ALL`` (unbounded). The offsets are returned only
    when the token right after ``LIMIT`` is provably the **whole** value: either the parse
    tree says the row count is an integer literal and that token spells exactly it, or the
    tree carries no row count at all and the token is the ``ALL`` keyword (sqlglot parses
    ``LIMIT ALL`` away). Every other shape is rejected instead of rewritten: an in-place
    rewrite by offset cannot cover an arbitrary expression, and a span that guesses where
    the expression ends turns ``LIMIT (1 + 2)`` into ``LIMIT 101 + 2)``.
    """
    if limit_index + 1 >= len(tokens):
        raise _limit_not_a_literal()
    value_tok = tokens[limit_index + 1]
    span = (value_tok.start, value_tok.end + 1)
    if limit is None:
        if value_tok.token_type is TokenType.ALL:
            return (*span, None)
        raise _limit_not_a_literal()
    count = limit.expression
    if (
        isinstance(count, exp.Literal)
        and not count.is_string
        and value_tok.token_type is TokenType.NUMBER
        and value_tok.text.isdigit()
        and value_tok.text == str(count.this)
    ):
        return (*span, int(value_tok.text))
    raise _limit_not_a_literal()


def _limit_not_a_literal() -> GuardRejectedError:
    """Refuse to bound a statement whose ``LIMIT`` cannot be rewritten token by token."""
    return GuardRejectedError(code="LIMIT_NOT_A_LITERAL")


def inject_limit(sql: str, max_rows: int) -> str:
    """Return ``sql`` bounded by a statement-level ``LIMIT`` of at most ``max_rows``.

    The statement is **never re-serialized**: sqlglot only reads it, to confirm it is a
    SELECT / UNION and to locate an existing ``LIMIT``. What reaches Netezza is the text
    the caller wrote and ``sql_guard`` validated, with at most the ``LIMIT`` value edited
    in place. Re-printing the tree with the postgres dialect rewrote Netezza SQL on its
    way out (``NVL`` to ``COALESCE``, ``DECODE`` / ``NVL2`` to ``CASE``, ``STRPOS`` to
    ``POSITION``, ``LAST_DAY`` to a ``DATE_TRUNC`` expression, dropped ``NULLS LAST``)
    and, because the limit literal was read from the wrong argument, silently raised a
    caller's ``LIMIT 3`` to ``max_rows`` (issue #137).

    Raises ``GuardRejectedError`` when the statement carries a ``LIMIT`` whose value is
    not a single-token integer literal (nor ``ALL``): such a statement cannot be bounded
    by an in-place rewrite, and running it unbounded is not an option.
    """
    expr = sqlglot.parse_one(sql, read="postgres")
    if not isinstance(expr, (exp.Select, exp.Union)):
        raise ValueError("inject_limit expects a SELECT or UNION statement")
    tokens = sqlglot.tokenize(sql, read="postgres")
    limit_index = _top_level_limit_index(tokens)
    if limit_index is None:
        # A newline, not a space: a trailing line comment would swallow the clause.
        return f"{_statement_body(sql, tokens)}\nLIMIT {max_rows}"
    limit = expr.args.get("limit")
    start, end, current = _limit_value_span(
        tokens,
        limit_index,
        limit if isinstance(limit, exp.Limit) else None,
    )
    if current is not None and current <= max_rows:
        return sql
    return f"{sql[:start]}{max_rows}{sql[end:]}"


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
