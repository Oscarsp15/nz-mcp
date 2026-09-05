"""Actionable ES/EN hints for the error payload the AI receives.

The model never sees a stack trace: the error payload *is* the whole diagnosis. This
module turns a raw failure into something the model can act on with no extra context:

* a pydantic ``ValidationError`` becomes one compact ``field: reason`` per offending
  field, plus a hint naming the arguments to add or drop;
* a stable error ``code`` plus its ``context`` becomes a hint pointing at the tool
  that answers the question (``nz_list_tables`` for a missing table, ...).

Rule: a hint is either specific or absent. "Check your arguments" is noise, and noise
is paid in tokens on every failed call. See docs/adr/0023-mensajes-error-accionables.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from nz_mcp.i18n import both

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import ValidationError
    from pydantic_core import ErrorDetails

# A model that got six fields wrong is not reading the schema; listing every one of
# them only grows the payload. The count of the ones left out is still reported.
_MAX_REPORTED_ERRORS: Final[int] = 5

# Object kinds whose "not found" has a listing tool that answers it. Databases are
# absent on purpose: nz_switch_database already returns the visible ones in its detail.
_LISTING_TOOL_HINTS: Final[dict[str, str]] = {
    "table": "OBJECT_NOT_FOUND.HINT.TABLE",
    "procedure": "OBJECT_NOT_FOUND.HINT.PROCEDURE",
}

# Ordered rules, first match wins, matched lowercase against the sanitized driver text.
# Kept as data (not nested ifs) so a newly observed message costs one tuple entry.
# "Multiple-row VALUES lists are not supported" is verbatim NPS wording (see issue #133).
_NETEZZA_HINT_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("MULTI_ROW_VALUES", ("multiple-row values",)),
    ("ATTRIBUTE_NOT_FOUND", ("attribute '", "column does not exist")),
    ("RELATION_NOT_FOUND", ("relation does not exist", "table does not exist")),
    ("PERMISSION_DENIED", ("permission denied", "not authorized")),
)


def summarize_validation_error(exc: ValidationError) -> str:
    """Render a pydantic failure as ``field: reason`` pairs, one per offending field.

    ``str(exc)`` is a multi-line dump that carries a docs URL per error and echoes the
    input value back. Neither helps a model fix the call, and the echoed value can be
    query data, so both are dropped.
    """
    errors = exc.errors(include_url=False, include_input=False)
    rendered = [f"{_render_loc(e['loc'])}: {e['msg']}" for e in errors[:_MAX_REPORTED_ERRORS]]
    hidden = len(errors) - len(rendered)
    if hidden > 0:
        rendered.append(f"(+{hidden} more)")
    return "; ".join(rendered)


def hints_for_validation_error(exc: ValidationError) -> dict[str, str] | None:
    """Name the arguments to add or to drop, or ``None`` when the fix is neither.

    Missing fields win over unknown ones: a call short of a required argument cannot
    succeed even after removing every unexpected one.
    """
    errors = exc.errors(include_url=False, include_input=False)
    missing = _fields_with_type(errors, "missing")
    if missing:
        return both("INVALID_INPUT.HINT.MISSING_FIELDS", fields=", ".join(missing))
    unexpected = _fields_with_type(errors, "extra_forbidden")
    if unexpected:
        return both("INVALID_INPUT.HINT.UNEXPECTED_FIELDS", fields=", ".join(unexpected))
    return None


def hints_for_error(code: str, context: Mapping[str, Any]) -> dict[str, str] | None:
    """Derive a hint from a typed error, or ``None`` when no rule is specific enough."""
    if code == "OBJECT_NOT_FOUND":
        return _object_not_found_hints(context)
    if code == "NETEZZA_ERROR":
        return _netezza_hints(str(context.get("detail", "")))
    return None


def _object_not_found_hints(context: Mapping[str, Any]) -> dict[str, str] | None:
    """Point at the listing tool for the object kind, when the scope is known.

    Without ``database`` and ``schema`` the hint could only name a tool without its
    arguments, which the model already knows: no hint at all is cheaper.
    """
    key = _LISTING_TOOL_HINTS.get(str(context.get("object_type", "")).lower())
    database = context.get("database")
    schema = context.get("schema")
    if key is None or not database or not schema:
        return None
    return both(key, database=database, schema=schema)


def _netezza_hints(detail: str) -> dict[str, str] | None:
    """Map a driver message to the hint that unblocks it, if any rule matches."""
    lowered = detail.lower()
    for cause, needles in _NETEZZA_HINT_RULES:
        if any(needle in lowered for needle in needles):
            return both(f"NETEZZA_ERROR.HINT.{cause}")
    return None


def _fields_with_type(errors: Sequence[ErrorDetails], error_type: str) -> list[str]:
    return [_render_loc(e["loc"]) for e in errors if e["type"] == error_type]


def _render_loc(loc: tuple[int | str, ...]) -> str:
    """``('rows', 0, 'id')`` becomes ``rows.0.id``; an empty loc means the whole payload."""
    return ".".join(str(part) for part in loc) if loc else "(root)"
