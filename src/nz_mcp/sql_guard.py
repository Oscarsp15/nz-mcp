"""SQL guard — second defensive barrier.

Classifies a SQL statement using ``sqlglot`` and enforces the rules per profile mode.
See docs/architecture/security-model.md for the full matrix.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

import sqlglot
from sqlglot import expressions as exp

from nz_mcp.catalog.identifier import render_cross_db, validate_catalog_identifier
from nz_mcp.config import PermissionMode
from nz_mcp.errors import GuardRejectedError, InvalidInputError, PermissionDeniedError
from nz_mcp.procedure_head_pattern import PROCEDURE_PARAM_LIST_PATTERN


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
    CALL = "CALL"
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
# Kinds whose WHERE clause must both exist and actually restrict rows.
_WHERE_REQUIRED_KINDS: Final[frozenset[StatementKind]] = frozenset(
    {StatementKind.UPDATE, StatementKind.DELETE}
)

_NZPLSQL_MARKER: Final[re.Pattern[str]] = re.compile(
    r"\bLANGUAGE\s+NZPLSQL\s+AS\b",
    re.IGNORECASE,
)
# Environment guard: identifiers prefixed ``PROD_`` (databases, schemas, objects) are
# treated as production references. When the active profile database is not itself a
# ``PROD_`` database, referencing them from generated DDL/CALL SQL is rejected so a
# development session cannot compile or invoke code that targets production.
_PROD_PREFIX: Final[str] = "PROD_"
_PROD_REF_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\bPROD_[A-Za-z0-9_]*\b",
    re.IGNORECASE,
)
_NZPLSQL_PROC_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+"
    r"(?P<sch>[A-Za-z][A-Za-z0-9_]*)\s*\.\s*(?P<proc>[A-Za-z][A-Za-z0-9_]*)"
    rf"\s*{PROCEDURE_PARAM_LIST_PATTERN}"
    r"(?:\s+RETURNS\b[\s\S]*)?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# ``sqlglot`` cannot parse ``CALL`` (falls back to a generic Command and logs a warning).
# We intercept it with a dedicated pattern: qualified name + a parenthesised list of ``?``
# placeholders only. Literal arguments are rejected on purpose — arguments must be
# parameterized (see docs/adr/0015-sql-guard-call-statement.md).
_CALL_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^\s*CALL\s+"
    r"(?P<sch>[A-Za-z][A-Za-z0-9_]*)\s*\.\s*(?P<proc>[A-Za-z][A-Za-z0-9_]*)"
    r"\s*\(\s*(?P<args>[?\s,]*)\)\s*$",
    re.IGNORECASE,
)
# Netezza NPS places ``IF EXISTS`` after the qualified name (not ANSI ``DROP TABLE IF EXISTS ...``).
_NETEZZA_DROP_TABLE_IF_EXISTS_SUFFIX: Final[re.Pattern[str]] = re.compile(
    r"^\s*DROP\s+TABLE\s+"
    r"(?P<sch>[A-Za-z][A-Za-z0-9_]*)\s*\.\s*(?P<tbl>[A-Za-z][A-Za-z0-9_]*)"
    r"\s+IF\s+EXISTS\s*$",
    re.IGNORECASE,
)

# Catalog overrides (``catalog_overrides`` in profiles.toml) replace a registered catalog
# query, so they are always reads. ``<BD>..`` markers are rendered against this throwaway
# database name for parsing only; the stored override text is never rewritten.
_OVERRIDE_PROBE_DATABASE: Final[str] = "NZMCPGUARD"


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    kind: StatementKind
    has_where: bool
    raw: str


def validate(
    sql: str,
    *,
    mode: PermissionMode,
    confirm_full_table: bool = False,
) -> ParsedStatement:
    """Parse ``sql``, classify, and enforce the rules for ``mode``.

    ``confirm_full_table`` is the caller's explicit declaration that an ``UPDATE`` /
    ``DELETE`` whose WHERE clause is statically always true is intended. It never
    grants privileges and never waives the WHERE requirement.

    Raises :class:`GuardRejectedError` with a stable ``code`` on rejection.
    """
    if not sql or not sql.strip():
        raise GuardRejectedError(code="EMPTY_STATEMENT")

    if _NZPLSQL_MARKER.search(sql):
        return _validate_nzplsql_procedure(sql, mode=mode)

    if _NETEZZA_DROP_TABLE_IF_EXISTS_SUFFIX.match(sql.strip()):
        return _validate_netezza_drop_if_exists_suffix(sql, mode=mode)

    if _CALL_HEAD.match(sql.strip()):
        return _validate_call(sql, mode=mode)

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

    # Permission mode is checked first on purpose: a caller who may not run the statement
    # at all must be told that, not invited to retry with ``confirm_full_table``.
    _enforce(kind=kind, has_where=has_where, mode=mode)
    _assert_selective_where(expr, kind=kind, confirm_full_table=confirm_full_table)

    return ParsedStatement(kind=kind, has_where=has_where, raw=sql)


def assert_env_safe(sql: str, *, active_database: str) -> None:
    """Reject ``PROD_`` references when the active database is not a production one.

    Environment safety rail for the write/DDL/CALL tools: when the active profile
    targets a non-production database (its name does not start with ``PROD_``), any
    ``PROD_``-prefixed identifier in ``sql`` (e.g. ``PROD_ANALITICA..T``) is treated
    as an accidental cross-environment reference and rejected. The check is a
    conservative textual scan — a string literal containing ``PROD_`` also trips it;
    that is intentional (fail closed). See docs/adr/0014-tool-execute-ddl.md.
    """
    if active_database.strip().upper().startswith(_PROD_PREFIX):
        return
    refs = sorted({m.group(0).upper() for m in _PROD_REF_PATTERN.finditer(sql)})
    if refs:
        raise GuardRejectedError(
            code="PROD_REF_IN_NONPROD",
            refs=", ".join(refs),
            active_database=active_database,
        )


def validate_catalog_override(sql: str, *, query_id: str, profile: str) -> ParsedStatement:
    """Validate a profile ``catalog_overrides`` entry as a read-only ``SELECT``.

    An override is user-supplied SQL that replaces a registered catalog query, so it goes
    through the same barrier as any other statement (``mode="read"``) plus two extra
    restrictions: it must classify as ``SELECT`` (``SHOW`` / ``EXPLAIN`` do not return the
    rows the catalog callers unpack) and it must not carry an ``INTO`` target, which would
    materialize a table — a write wearing a read's clothes.

    ``query_id`` and ``profile`` are labels only: they name the offending entry in the
    error so the user knows which line of ``profiles.toml`` to fix. The override SQL is
    never echoed back.
    """
    probe_sql = _render_override_probe(sql, query_id=query_id, profile=profile)
    try:
        parsed = validate(probe_sql, mode="read")
    except (GuardRejectedError, PermissionDeniedError) as exc:
        raise _override_rejected(query_id, profile, exc.code) from exc

    if parsed.kind is not StatementKind.SELECT:
        raise _override_rejected(query_id, profile, "NOT_A_SELECT", statement_kind=str(parsed.kind))
    # ``validate`` already parsed ``probe_sql`` as a single statement, so this cannot raise.
    if sqlglot.parse_one(probe_sql, read="postgres").args.get("into") is not None:
        raise _override_rejected(query_id, profile, "SELECT_INTO")

    return ParsedStatement(kind=parsed.kind, has_where=parsed.has_where, raw=sql)


def _render_override_probe(sql: str, *, query_id: str, profile: str) -> str:
    """Resolve ``<BD>..`` markers so the override parses like any other statement."""
    if "<BD>" not in sql:
        return sql
    try:
        return render_cross_db(sql, _OVERRIDE_PROBE_DATABASE)
    except InvalidInputError as exc:
        raise _override_rejected(query_id, profile, "UNRESOLVED_BD_MARKER") from exc


def _override_rejected(
    query_id: str,
    profile: str,
    reason: str,
    *,
    statement_kind: str | None = None,
) -> GuardRejectedError:
    """Build the rejection, keeping ``reason`` a stable token the hint layer can match.

    Any extra detail travels in its own context key (``statement_kind``), never appended
    to ``reason``: a caller branching on the reason must not have to parse it.
    """
    context: dict[str, str] = {"query_id": query_id, "profile": profile, "reason": reason}
    if statement_kind is not None:
        context["statement_kind"] = statement_kind
    return GuardRejectedError(code="CATALOG_OVERRIDE_REJECTED", **context)


def _validate_nzplsql_procedure(sql: str, *, mode: PermissionMode) -> ParsedStatement:
    """Validate ``CREATE ... PROCEDURE ... LANGUAGE NZPLSQL AS`` without parsing the body.

    ``sqlglot`` cannot classify NZPLSQL procedure bodies; the header is validated with
    regex and catalog identifier rules. The body is treated as opaque (trusted when
    sourced from server catalog DDL, e.g. clone).
    """
    if mode != "admin":
        raise PermissionDeniedError(required="admin", actual=mode)

    parts = _NZPLSQL_MARKER.split(sql, maxsplit=1)
    expected_segments = 2
    if len(parts) != expected_segments or not parts[1].strip():
        raise GuardRejectedError(
            code="UNKNOWN_STATEMENT",
            detail="Malformed NZPLSQL procedure (missing body after LANGUAGE NZPLSQL AS).",
        )

    head = parts[0].strip()
    if ";" in head:
        raise GuardRejectedError(code="STACKED_NOT_ALLOWED", count=2)

    m = _NZPLSQL_PROC_HEAD.fullmatch(head)
    if not m:
        raise GuardRejectedError(code="UNKNOWN_STATEMENT", detail="Malformed procedure header.")

    try:
        validate_catalog_identifier(m.group("sch"))
        validate_catalog_identifier(m.group("proc"))
    except InvalidInputError as exc:
        raise GuardRejectedError(
            code="UNKNOWN_STATEMENT",
            detail="Invalid procedure identifier.",
        ) from exc

    return ParsedStatement(kind=StatementKind.CREATE, has_where=False, raw=sql)


def _validate_call(sql: str, *, mode: PermissionMode) -> ParsedStatement:
    """Validate ``CALL schema.proc(?, …)`` (placeholder args only) and gate to admin."""
    m = _CALL_HEAD.match(sql.strip())
    if not m:
        raise GuardRejectedError(code="UNKNOWN_STATEMENT", detail="Malformed CALL statement.")
    try:
        validate_catalog_identifier(m.group("sch"))
        validate_catalog_identifier(m.group("proc"))
    except InvalidInputError as exc:
        raise GuardRejectedError(
            code="UNKNOWN_STATEMENT",
            detail="Invalid CALL identifier.",
        ) from exc
    _enforce(kind=StatementKind.CALL, has_where=False, mode=mode)
    return ParsedStatement(kind=StatementKind.CALL, has_where=False, raw=sql)


def _validate_netezza_drop_if_exists_suffix(sql: str, *, mode: PermissionMode) -> ParsedStatement:
    """Accept Netezza ``DROP TABLE schema.table IF EXISTS`` (suffix form)."""
    m = _NETEZZA_DROP_TABLE_IF_EXISTS_SUFFIX.match(sql.strip())
    if not m:
        raise GuardRejectedError(
            code="UNKNOWN_STATEMENT",
            detail="Malformed Netezza DROP TABLE ... IF EXISTS.",
        )

    try:
        validate_catalog_identifier(m.group("sch"))
        validate_catalog_identifier(m.group("tbl"))
    except InvalidInputError as exc:
        raise GuardRejectedError(
            code="UNKNOWN_STATEMENT",
            detail="Invalid DROP TABLE identifier.",
        ) from exc

    _enforce(kind=StatementKind.DROP, has_where=False, mode=mode)
    return ParsedStatement(kind=StatementKind.DROP, has_where=False, raw=sql)


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


def _is_select_only_union_tree(expr: exp.Expr) -> bool:
    """True if ``expr`` is a ``SELECT`` or a ``UNION`` / ``UNION ALL`` tree of only ``SELECT``s."""
    if isinstance(expr, exp.Select):
        return True
    if isinstance(expr, exp.Union):
        return _is_select_only_union_tree(expr.this) and _is_select_only_union_tree(expr.expression)
    return False


def _classify(expr: exp.Expr) -> StatementKind:
    for cls, kind in _SIMPLE_KIND_MAP:
        if isinstance(expr, cls):
            return kind
    if isinstance(expr, exp.Union) and _is_select_only_union_tree(expr):
        return StatementKind.SELECT
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


# --- Tautological WHERE detection ---------------------------------------------
# Requiring a WHERE clause is worthless if ``WHERE 1=1`` satisfies it. Deciding
# whether an arbitrary predicate is a tautology is undecidable, so this is a
# deliberately narrow, sound-by-construction constant folder over the AST:
# literal-only comparisons plus AND / OR / NOT / parentheses. Anything that reads
# data (columns, functions, subqueries) stays UNDECIDED and is allowed through.
# See docs/adr/0020-sql-guard-tautological-where.md for the exact boundary.

_LiteralValue = Decimal | str | bool

_COMPARATORS: Final[dict[type[exp.Expression], Callable[[_LiteralValue, _LiteralValue], bool]]] = {
    exp.EQ: operator.eq,
    exp.NEQ: operator.ne,
    exp.GT: operator.gt,
    exp.GTE: operator.ge,
    exp.LT: operator.lt,
    exp.LTE: operator.le,
}


def _assert_selective_where(
    expr: exp.Expr,
    *,
    kind: StatementKind,
    confirm_full_table: bool,
) -> None:
    """Reject a mutation whose WHERE is statically always true, unless opted in."""
    if kind not in _WHERE_REQUIRED_KINDS or confirm_full_table:
        return
    where = expr.args.get("where")
    if where is None:
        return
    if _static_truth(where.this) is True:
        raise GuardRejectedError(code="WHERE_ALWAYS_TRUE", kind=str(kind))


def _static_truth(node: exp.Expression) -> bool | None:
    """Fold ``node`` to ``True`` / ``False``; ``None`` means "cannot decide statically"."""
    if isinstance(node, exp.Paren):
        return _static_truth(node.this)
    if isinstance(node, exp.Not):
        inner = _static_truth(node.this)
        return None if inner is None else not inner
    if isinstance(node, exp.And):
        return _fold(_static_truth(node.this), _static_truth(node.expression), conjunction=True)
    if isinstance(node, exp.Or):
        return _fold(_static_truth(node.this), _static_truth(node.expression), conjunction=False)
    return _leaf_truth(node)


def _fold(left: bool | None, right: bool | None, *, conjunction: bool) -> bool | None:
    """Three-valued AND / OR: an undecided operand only survives short-circuiting."""
    dominant = not conjunction  # False decides an AND; True decides an OR
    if left is dominant or right is dominant:
        return dominant
    if left is None or right is None:
        return None
    return not dominant


def _leaf_truth(node: exp.Expression) -> bool | None:
    """Truth value of a predicate leaf: a bare literal or a literal-only comparison."""
    if type(node) in _COMPARATORS:
        return _compare(node)
    return _value_truth(_literal_value(node))


def _compare(node: exp.Expression) -> bool | None:
    left = _literal_value(node.this)
    right = _literal_value(node.expression)
    if left is not None and right is not None and type(left) is type(right):
        return _COMPARATORS[type(node)](left, right)
    # ``col = col`` restricts nothing beyond NULL rows. Not a tautology in strict SQL
    # semantics, but treated as full-table intent on purpose (over-approximation is
    # cheap here: the caller can still proceed with confirm_full_table).
    if isinstance(node, exp.EQ) and _same_column(node.this, node.expression):
        return True
    return None


def _same_column(left: exp.Expression, right: exp.Expression) -> bool:
    """True when both sides are the very same (textually identical) column reference."""
    if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
        return False
    return left.sql(dialect="postgres").upper() == right.sql(dialect="postgres").upper()


def _value_truth(value: _LiteralValue | None) -> bool | None:
    """Truthiness of a bare literal predicate (``WHERE TRUE``, ``WHERE 1``)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value != 0
    return None


def _literal_value(node: exp.Expression) -> _LiteralValue | None:
    """Constant value of ``node``; ``None`` when it is not a literal."""
    if isinstance(node, exp.Paren):
        return _literal_value(node.this)
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Neg):
        inner = _literal_value(node.this)
        return -inner if isinstance(inner, Decimal) else None
    if isinstance(node, exp.Literal):
        return str(node.this) if node.is_string else _to_decimal(node.this)
    return None


def _to_decimal(raw: object) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


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

    # CALL executes arbitrary procedure code (an EXECUTE-class operation); gate to admin,
    # same tier as DDL. See docs/adr/0015-sql-guard-call-statement.md.
    if kind is StatementKind.CALL:
        if mode == "admin":
            return
        raise GuardRejectedError(code="STATEMENT_NOT_ALLOWED", kind=str(kind), mode=mode)

    raise GuardRejectedError(code="STATEMENT_NOT_ALLOWED", kind=str(kind), mode=mode)
