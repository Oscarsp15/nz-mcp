"""SQL guard — second defensive barrier.

Classifies a SQL statement using ``sqlglot`` and enforces the rules per profile mode.
See docs/architecture/security-model.md for the full matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import sqlglot
from sqlglot import expressions as exp

from nz_mcp.config import PermissionMode
from nz_mcp.errors import GuardRejectedError


class StatementKind(StrEnum):
    SELECT = "SELECT"
    EXPLAIN = "EXPLAIN"
    SHOW = "SHOW"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"
    TRUNCATE = "TRUNCATE"
    DROP = "DROP"
    UNKNOWN = "UNKNOWN"


# Read-only kinds permitted in any mode.
_READ_KINDS: Final[frozenset[StatementKind]] = frozenset(
    {StatementKind.SELECT, StatementKind.EXPLAIN, StatementKind.SHOW}
)
# Mutation kinds permitted in write+ modes (with WHERE for UPDATE/DELETE).
_WRITE_KINDS: Final[frozenset[StatementKind]] = frozenset(
    {StatementKind.INSERT, StatementKind.UPDATE, StatementKind.DELETE}
)
# DDL kinds permitted only in admin mode.
_DDL_KINDS: Final[frozenset[StatementKind]] = frozenset(
    {StatementKind.CREATE, StatementKind.TRUNCATE, StatementKind.DROP}
)


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    kind: StatementKind
    has_where: bool
    raw: str


def validate(sql: str, *, mode: PermissionMode) -> ParsedStatement:
    """Parse ``sql``, classify, and enforce the rules for ``mode``.

    Raises :class:`GuardRejectedError` with a stable ``code`` on rejection.
    """
    if not sql or not sql.strip():
        raise GuardRejectedError(code="EMPTY_STATEMENT")

    try:
        parsed_list = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise GuardRejectedError(code="UNKNOWN_STATEMENT", detail=str(exc)) from exc

    non_empty = [p for p in parsed_list if p is not None]
    if len(non_empty) == 0:
        raise GuardRejectedError(code="EMPTY_STATEMENT")
    if len(non_empty) > 1:
        raise GuardRejectedError(code="STACKED_NOT_ALLOWED", count=len(non_empty))

    expr = non_empty[0]

    # Reject CTEs whose inner expression is a mutation (e.g. DELETE ... RETURNING).
    with_clause = expr.args.get("with") or expr.args.get("with_")
    if isinstance(expr, exp.Select) and with_clause is not None:
        for cte in with_clause.expressions:
            inner = cte.this
            if isinstance(inner, exp.Insert | exp.Update | exp.Delete):
                raise GuardRejectedError(
                    code="STATEMENT_NOT_ALLOWED",
                    kind="CTE_MUTATION",
                    mode=mode,
                )

    kind = _classify(expr)
    has_where = _has_where(expr)

    _enforce(kind=kind, has_where=has_where, mode=mode)

    return ParsedStatement(kind=kind, has_where=has_where, raw=sql)


_SIMPLE_KIND_MAP: Final[tuple[tuple[type[exp.Expr], StatementKind], ...]] = (
    (exp.Select, StatementKind.SELECT),
    (exp.Insert, StatementKind.INSERT),
    (exp.Update, StatementKind.UPDATE),
    (exp.Delete, StatementKind.DELETE),
    (exp.Create, StatementKind.CREATE),
    (exp.Drop, StatementKind.DROP),
    (exp.TruncateTable, StatementKind.TRUNCATE),
    (exp.Show, StatementKind.SHOW),
)


def _classify(expr: exp.Expr) -> StatementKind:
    for cls, kind in _SIMPLE_KIND_MAP:
        if isinstance(expr, cls):
            return kind
    if isinstance(expr, exp.Command):
        cmd = str(expr.name).upper()
        if cmd == "EXPLAIN":
            return StatementKind.EXPLAIN
        if cmd == "SHOW":
            return StatementKind.SHOW
    return StatementKind.UNKNOWN


def _has_where(expr: exp.Expr) -> bool:
    where = expr.args.get("where") if hasattr(expr, "args") else None
    return where is not None


def _enforce(*, kind: StatementKind, has_where: bool, mode: PermissionMode) -> None:
    if kind is StatementKind.UNKNOWN:
        raise GuardRejectedError(code="UNKNOWN_STATEMENT")

    if kind in _READ_KINDS:
        return

    if kind is StatementKind.UPDATE and not has_where:
        raise GuardRejectedError(code="UPDATE_REQUIRES_WHERE")
    if kind is StatementKind.DELETE and not has_where:
        raise GuardRejectedError(code="DELETE_REQUIRES_WHERE")

    if kind in _WRITE_KINDS:
        if mode in ("write", "admin"):
            return
        raise GuardRejectedError(code="STATEMENT_NOT_ALLOWED", kind=str(kind), mode=mode)

    if kind in _DDL_KINDS:
        if mode == "admin":
            return
        raise GuardRejectedError(code="STATEMENT_NOT_ALLOWED", kind=str(kind), mode=mode)

    raise GuardRejectedError(code="STATEMENT_NOT_ALLOWED", kind=str(kind), mode=mode)
