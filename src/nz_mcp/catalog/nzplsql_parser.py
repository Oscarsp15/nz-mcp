"""Lightweight NZPLSQL section parser for stored procedures (markers only, not a full AST)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, Literal

# Markers are matched outside of single-quoted string regions (masking applied first).
_BEGIN_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bBEGIN_PROC\b")
_DECLARE: Final[re.Pattern[str]] = re.compile(r"(?i)\bDECLARE\b")
_EXCEPTION: Final[re.Pattern[str]] = re.compile(r"(?i)\bEXCEPTION\b")
_END_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bEND_PROC\b")
_BEGIN_NOT_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bBEGIN\b")
_END_STMT: Final[re.Pattern[str]] = re.compile(r"(?i)^\s*END\s*;\s*$")
_END_LOOP_IF_CASE: Final[re.Pattern[str]] = re.compile(r"(?i)^\s*END\s+(LOOP|IF|CASE)\b")


def mask_single_quoted_strings(source: str) -> str:
    """Replace characters inside single-quoted literals with spaces (preserve length)."""
    out = list(source)
    i = 0
    n = len(source)
    in_quote = False
    while i < n:
        ch = source[i]
        if not in_quote:
            if ch == "'":
                in_quote = True
                i += 1
                continue
            i += 1
            continue
        # in quote
        if ch == "'":
            if i + 1 < n and source[i + 1] == "'":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                continue
            in_quote = False
            i += 1
            continue
        out[i] = " "
        i += 1
    return "".join(out)


def parse_sections(source: str) -> dict[str, tuple[int, int]]:
    """Return 1-indexed inclusive line ranges per detected section.

    Keys may include: ``header``, ``declare``, ``body``, ``exception``.
    Omitted keys mean the section does not exist in the source.

    Supports catalog markers ``BEGIN_PROC`` / ``END_PROC`` (some NPS builds) and
    plain ``DECLARE`` / ``BEGIN`` / ``END;`` bodies as stored from user sources.
    """
    if not source.strip():
        return {}

    masked = mask_single_quoted_strings(source)
    lines = source.splitlines()
    masked_lines = masked.splitlines()
    n = len(lines)
    if n == 0:
        return {}

    begin_proc_line = _first_line_matching(masked_lines, _BEGIN_PROC)
    if begin_proc_line is not None:
        return _parse_sections_begin_proc_markers(masked_lines, lines, n, begin_proc_line)

    return _parse_sections_plain_nzplsql(masked_lines)


def _parse_sections_begin_proc_markers(
    masked_lines: list[str],
    lines: list[str],
    n: int,
    begin_proc_line: int,
) -> dict[str, tuple[int, int]]:
    end_proc_line = _first_line_matching(masked_lines, _END_PROC)

    declare_line = _first_line_matching_after(masked_lines, _DECLARE, begin_proc_line + 1)

    main_begin_line = _find_main_begin(masked_lines, begin_proc_line, declare_line)

    exception_line = (
        _first_line_matching_after(masked_lines, _EXCEPTION, main_begin_line + 1)
        if main_begin_line is not None
        else None
    )

    closing_end_line = _find_closing_end(lines, main_begin_line, exception_line, end_proc_line, n)

    sections: dict[str, tuple[int, int]] = {}

    if begin_proc_line > 1:
        sections["header"] = (1, begin_proc_line - 1)
    else:
        line1 = lines[0]
        mbp = _BEGIN_PROC.search(mask_single_quoted_strings(line1))
        if mbp is not None and mbp.start() > 0:
            sections["header"] = (1, 1)

    if declare_line is not None and main_begin_line is not None and declare_line < main_begin_line:
        sections["declare"] = (declare_line, main_begin_line - 1)

    if main_begin_line is None:
        return sections

    if exception_line is not None:
        body_end = exception_line - 1
        if body_end >= main_begin_line + 1:
            sections["body"] = (main_begin_line + 1, body_end)
        if closing_end_line is not None and closing_end_line > exception_line:
            exc_end = closing_end_line - 1
            if exc_end >= exception_line + 1:
                sections["exception"] = (exception_line + 1, exc_end)
    elif closing_end_line is not None and closing_end_line > main_begin_line + 1:
        sections["body"] = (main_begin_line + 1, closing_end_line - 1)
    elif (
        closing_end_line is None
        and end_proc_line is not None
        and end_proc_line > main_begin_line + 1
    ):
        sections["body"] = (main_begin_line + 1, end_proc_line - 1)

    return sections


def _parse_sections_plain_nzplsql(
    masked_lines: list[str],
) -> dict[str, tuple[int, int]]:
    declare_line = _first_line_matching(masked_lines, _DECLARE)
    start_search = 1 if declare_line is None else declare_line + 1
    main_begin_line = _first_plain_begin(masked_lines, start_search)
    if main_begin_line is None:
        return {}

    exception_line = _first_line_matching_after(masked_lines, _EXCEPTION, main_begin_line + 1)

    closing_end_line = _find_plain_outer_end(masked_lines, main_begin_line)
    if closing_end_line is None:
        return {}

    sections: dict[str, tuple[int, int]] = {}

    if declare_line is not None and declare_line > 1:
        sections["header"] = (1, declare_line - 1)
    elif declare_line is None and main_begin_line > 1:
        sections["header"] = (1, main_begin_line - 1)

    if declare_line is not None and declare_line < main_begin_line:
        sections["declare"] = (declare_line, main_begin_line - 1)

    if exception_line is not None:
        body_end = exception_line - 1
        if body_end >= main_begin_line + 1:
            sections["body"] = (main_begin_line + 1, body_end)
        if closing_end_line > exception_line:
            exc_end = closing_end_line - 1
            if exc_end >= exception_line + 1:
                sections["exception"] = (exception_line + 1, exc_end)
    elif closing_end_line > main_begin_line + 1:
        sections["body"] = (main_begin_line + 1, closing_end_line - 1)

    return sections


def _first_plain_begin(masked_lines: list[str], start_line: int) -> int | None:
    # Use len(masked_lines) as the bound — *not* the source line count, which
    # can be larger when multi-line string literals are collapsed by masking.
    for i in range(start_line, len(masked_lines) + 1):
        line = masked_lines[i - 1]
        if _BEGIN_PROC.search(line):
            continue
        if _BEGIN_NOT_PROC.search(line):
            return i
    return None


def _find_plain_outer_end(masked_lines: list[str], main_begin_line: int) -> int | None:
    """Find the ``END;`` that closes the outer ``BEGIN`` at ``main_begin_line``.

    Uses ``len(masked_lines)`` as the loop bound instead of the source line
    count.  ``mask_single_quoted_strings`` replaces newlines inside string
    literals with spaces, so ``masked.splitlines()`` can be shorter than
    ``source.splitlines()``.  Using the source count caused ``IndexError``
    for procedures containing multi-line string literals (see issue #113).
    """
    depth = 1
    i = main_begin_line + 1
    while i <= len(masked_lines):
        ml = masked_lines[i - 1]
        if _line_is_nested_end_keyword(ml):
            i += 1
            continue
        if _END_STMT.match(ml):
            depth -= 1
            if depth == 0:
                return i
            i += 1
            continue
        if _plain_begin_increments_depth(ml):
            depth += 1
        i += 1
    return None


def _plain_begin_increments_depth(line: str) -> bool:
    if _BEGIN_PROC.search(line):
        return False
    return _BEGIN_NOT_PROC.search(line) is not None


def _line_is_nested_end_keyword(line: str) -> bool:
    return _END_LOOP_IF_CASE.match(line.strip()) is not None


def _first_line_matching(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    for i, line in enumerate(lines, start=1):
        if pattern.search(line):
            return i
    return None


def _first_line_matching_after(
    lines: list[str], pattern: re.Pattern[str], start_idx: int
) -> int | None:
    for i in range(start_idx, len(lines) + 1):
        if pattern.search(lines[i - 1]):
            return i
    return None


def _find_main_begin(
    masked_lines: list[str],
    begin_proc_line: int,
    declare_line: int | None,
) -> int | None:
    start = begin_proc_line + 1
    if declare_line is not None:
        start = declare_line + 1
    for i in range(start, len(masked_lines) + 1):
        line = masked_lines[i - 1]
        if _BEGIN_PROC.search(line):
            continue
        if _BEGIN_NOT_PROC.search(line):
            return i
    return None


def _find_closing_end(
    lines: list[str],
    main_begin_line: int | None,
    exception_line: int | None,
    end_proc_line: int | None,
    n: int,
) -> int | None:
    """Locate the ``END;`` that closes the main ``BEGIN`` / ``EXCEPTION`` block."""
    if main_begin_line is None:
        return None

    if end_proc_line is not None and end_proc_line > 1:
        cand = end_proc_line - 1
        if 1 <= cand <= n and _END_STMT.match(lines[cand - 1]) is not None:
            return cand

    scan_lo = (exception_line + 1) if exception_line is not None else (main_begin_line + 1)
    scan_hi = n if end_proc_line is None else end_proc_line - 1
    closing: int | None = None
    for i in range(scan_hi, scan_lo - 1, -1):
        if _END_STMT.match(lines[i - 1]) is not None:
            closing = i
            break
    return closing


def line_slice(source: str, from_line: int, to_line: int) -> str:
    """Inclusive 1-indexed line slice; empty if invalid range."""
    lines = source.splitlines()
    if from_line < 1 or to_line < from_line or from_line > len(lines):
        return ""
    end = min(to_line, len(lines))
    chunk = lines[from_line - 1 : end]
    return "\n".join(chunk)


def _scan_quoted_token(source: str, start: int, quote_char: str) -> int:
    """Return the index just past the closing *quote_char*, handling doubled escapes.

    Handles ``''`` (escaped single quote) and ``""`` (escaped double quote).
    """
    j = start + 1
    n = len(source)
    while j < n:
        if source[j] == quote_char:
            if j + 1 < n and source[j + 1] == quote_char:
                j += 2  # escaped quote — keep going
                continue
            j += 1  # closing quote found
            break
        j += 1
    return j


def strip_comments(source: str) -> str:
    """Remove NZPLSQL ``--`` and ``/* … */`` comments from procedure source.

    Preserves ``--`` and ``/*`` that appear inside single-quoted string
    literals (``'…'``) or double-quoted identifiers (``"…"``).

    Collapses runs of more than one consecutive blank line to a single blank.
    Trailing whitespace is stripped from every line.

    Security note: this function only removes characters — it never inserts
    or reorders tokens, so it cannot introduce SQL injection vectors.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        # single-quoted string literal — pass through verbatim
        if ch == "'":
            j = _scan_quoted_token(source, i, "'")
            out.append(source[i:j])
            i = j
            continue

        # double-quoted identifier — pass through verbatim
        if ch == '"':
            j = _scan_quoted_token(source, i, '"')
            out.append(source[i:j])
            i = j
            continue

        # line comment (-- …) — skip to end of line, preserve newline
        if ch == "-" and i + 1 < n and source[i + 1] == "-":
            while i < n and source[i] != "\n":
                i += 1
            continue

        # block comment (/* … */) — skip until closing */
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i += 2
            while i < n:
                if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                    i += 2
                    break
                i += 1
            continue

        out.append(ch)
        i += 1

    result = "".join(out)
    # Strip trailing whitespace on each line (comments often leave trailing spaces).
    # Use split('\n') instead of splitlines() so a trailing newline is preserved.
    result = "\n".join(line.rstrip() for line in result.split("\n"))
    # Collapse runs of 3+ newlines (= 2+ consecutive blank lines) to at most 2.
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def find_begin_proc_line(source: str) -> int | None:
    """Return 1-indexed line of the first ``BEGIN_PROC`` marker, if any."""
    masked = mask_single_quoted_strings(source)
    for i, line in enumerate(masked.splitlines(), start=1):
        if _BEGIN_PROC.search(line):
            return i
    return None


def header_content(source: str, begin_proc_line: int) -> str:
    """Text before the first ``BEGIN_PROC`` token (may be a prefix of the first line)."""
    masked_line = mask_single_quoted_strings(source.splitlines()[begin_proc_line - 1])
    m = _BEGIN_PROC.search(masked_line)
    if m is None:
        return ""
    prefix = source.splitlines()[begin_proc_line - 1][: m.start()]
    if begin_proc_line > 1:
        head = "\n".join(source.splitlines()[: begin_proc_line - 1])
        return f"{head}\n{prefix}".strip()
    return prefix.strip()


# ── statement iteration (`;`-bounded, string/comment-aware) ──────────────────


StatementKind = Literal["CREATE TABLE", "CREATE TEMP TABLE", "INSERT INTO"]


@dataclass(frozen=True, slots=True)
class StatementInfo:
    """Single SQL statement extracted from a procedure body.

    ``sql`` is the raw text of the statement (including the trailing ``;``).
    ``line_start`` / ``line_end`` are 1-indexed inclusive line numbers
    referring to the **original raw** source the caller passed in.
    """

    sql: str
    line_start: int
    line_end: int


def _skip_line_comment(source: str, i: int, n: int) -> int:
    """Return index just past the end-of-line of a ``--`` line comment.

    The newline itself is **not** consumed so the outer loop can update line counters.
    """
    while i < n and source[i] != "\n":
        i += 1
    return i


def _skip_block_comment(source: str, i: int, n: int) -> tuple[int, int]:
    """Return ``(new_i, newlines_skipped)`` after consuming a ``/* … */`` block."""
    newlines = 0
    i += 2  # skip opening ``/*``
    while i < n:
        if source[i] == "\n":
            newlines += 1
        if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
            return i + 2, newlines
        i += 1
    return i, newlines


def iter_statements(source: str) -> Iterator[StatementInfo]:
    """Yield ``;``-bounded statements from ``source`` safely.

    A ``;`` only ends a statement when it is **outside** of:

    * single-quoted string literals (``'foo;bar'``), with ``''`` escape support,
    * double-quoted identifiers (``"a;b"``), with ``""`` escape support,
    * line comments (``-- ... \\n``),
    * block comments (``/* ... */``, non-nested).

    ``line_start`` / ``line_end`` map to the raw source's line numbers, with
    ``line_start`` pointing at the first **non-comment, non-blank** character
    of the statement so callers can jump straight to the SQL when auditing.
    Whitespace-only / empty trailing chunks are skipped.

    The yielded ``sql`` text is exactly the source slice between boundaries
    (caller can call :func:`strip_comments` on it for analysis without losing
    the original line mapping).
    """
    n = len(source)
    if n == 0:
        return

    i = 0
    stmt_start = 0
    stmt_start_line: int | None = None  # set on first real char in current chunk
    line = 1

    while i < n:
        ch = source[i]

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch in ("'", '"'):
            if stmt_start_line is None:
                stmt_start_line = line
            j = _scan_quoted_token(source, i, ch)
            line += source.count("\n", i, j)
            i = j
            continue

        if ch == "-" and i + 1 < n and source[i + 1] == "-":
            i = _skip_line_comment(source, i, n)
            continue

        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i, newlines = _skip_block_comment(source, i, n)
            line += newlines
            continue

        if ch == ";":
            chunk = source[stmt_start : i + 1]
            if chunk.strip() and stmt_start_line is not None:
                yield StatementInfo(
                    sql=chunk,
                    line_start=stmt_start_line,
                    line_end=line,
                )
            i += 1
            stmt_start = i
            stmt_start_line = None
            continue

        # Any other meaningful character is the first real char of the chunk
        # if we have not yet set ``stmt_start_line``.
        if ch not in " \t\r" and stmt_start_line is None:
            stmt_start_line = line
        i += 1

    # Trailing text without a final ``;`` is intentionally ignored — it cannot be
    # a complete statement under our boundary rule.


# ── target-table detection on CREATE / INSERT statements ─────────────────────


# Captures the table name token: optional backticks/quotes, allowing
# ``schema.table``, ``bd.schema.table`` and ``bd..table`` (Netezza double-dot).
_TABLE_NAME_TOKEN: Final[str] = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
# Two optional dot-prefixed qualifiers supports both ``schema.table``,
# ``bd.schema.table`` and Netezza ``bd..table`` (empty middle qualifier).
_QUALIFIED_NAME: Final[str] = (
    rf"(?:{_TABLE_NAME_TOKEN}?\s*\.\s*)?"
    rf"(?:{_TABLE_NAME_TOKEN}?\s*\.\s*)?"
    rf"{_TABLE_NAME_TOKEN}"
)

# NOTE: these patterns are intentionally **not anchored** with ``\A``. A
# statement chunk produced by :func:`iter_statements` may start with leading
# block-control tokens accumulated since the previous ``;`` boundary —
# ``BEGIN``, ``IF … THEN``, ``ELSE``, ``ELSIF``, ``EXCEPTION``, ``FOR …
# LOOP``, ``WHILE … LOOP``, etc. We search-anywhere with a word-boundary
# lookbehind so the verb is detected regardless of those prefixes, while
# string literals in the chunk are masked by the caller before searching to
# prevent false positives like ``'INSERT INTO foo'``.
_RE_CREATE_TABLE: Final[re.Pattern[str]] = re.compile(
    rf"""
    (?<![A-Za-z0-9_])
    CREATE\s+
    (?P<temp>(?:TEMP|TEMPORARY)\s+)?
    TABLE\s+
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?P<name>{_QUALIFIED_NAME})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_INSERT_INTO: Final[re.Pattern[str]] = re.compile(
    rf"""
    (?<![A-Za-z0-9_])
    INSERT\s+INTO\s+
    (?P<name>{_QUALIFIED_NAME})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _last_segment_of_qualified(name: str) -> str:
    """Return ``table`` from ``bd.schema.table`` / ``bd..table`` / ``schema.table``."""
    parts = [p.strip() for p in name.split(".")]
    last = parts[-1]
    return last.strip('"')


def classify_target_statement(stmt_sql: str) -> tuple[StatementKind, str] | None:
    """If ``stmt_sql`` contains a CREATE [TEMP] TABLE or INSERT INTO, return ``(kind, target)``.

    ``target`` is the last segment of the qualified name (table name as written,
    without surrounding quotes — case preserved). The input must already have
    comments stripped. Returns ``None`` for any other statement kind, including
    out-of-scope verbs (MERGE, UPDATE, DELETE, TRUNCATE).

    The verb is searched anywhere in the chunk, not only at the start, so that
    statements yielded by :func:`iter_statements` whose prefix is a leading
    block-control token (``BEGIN``, ``IF … THEN``, ``ELSE``, ``EXCEPTION``,
    ``FOR … LOOP``, ``WHILE``, etc.) are still classified correctly. Single-
    quoted string literals are masked before scanning so verbs that appear
    only inside a literal (``'INSERT INTO foo'``) do not produce a match.
    When several CREATE/INSERT verbs are present in the same chunk, the one
    occurring **first** in source order wins, mirroring the previous
    semantics for chunks that already started at the verb.
    """
    masked = mask_single_quoted_strings(stmt_sql)

    create_match = _RE_CREATE_TABLE.search(masked)
    insert_match = _RE_INSERT_INTO.search(masked)

    if create_match is not None and (
        insert_match is None or create_match.start() <= insert_match.start()
    ):
        kind: StatementKind = "CREATE TEMP TABLE" if create_match.group("temp") else "CREATE TABLE"
        return kind, _last_segment_of_qualified(create_match.group("name"))

    if insert_match is not None:
        return "INSERT INTO", _last_segment_of_qualified(insert_match.group("name"))

    return None


@dataclass(frozen=True, slots=True)
class TargetingMatch:
    """A statement that creates or populates the requested table."""

    kind: StatementKind
    sql: str
    line_start: int
    line_end: int
    target_as_written: str


def extract_create_or_insert_targeting(
    source: str, table: str, *, kinds: tuple[StatementKind, ...] | None = None
) -> list[TargetingMatch]:
    """Return CREATE/INSERT statements whose target last segment equals ``table``.

    The match is case-insensitive on the table name. ``source`` is the raw
    procedure body (with comments). Each returned ``sql`` is the **clean**
    text (comments stripped) ending in ``;``, and ``line_start``/``line_end``
    point to the **raw** body so callers can audit the original.

    ``kinds`` filters by statement kind; ``None`` accepts all supported kinds.
    """
    if not table.strip():
        return []
    table_norm = table.strip().lower()
    allowed: set[StatementKind] = (
        {"CREATE TABLE", "CREATE TEMP TABLE", "INSERT INTO"} if kinds is None else set(kinds)
    )

    matches: list[TargetingMatch] = []
    for stmt in iter_statements(source):
        clean = strip_comments(stmt.sql).strip()
        if not clean:
            continue
        if not clean.endswith(";"):
            clean = f"{clean};"
        classified = classify_target_statement(clean)
        if classified is None:
            continue
        kind, target = classified
        if kind not in allowed:
            continue
        if target.lower() != table_norm:
            continue
        matches.append(
            TargetingMatch(
                kind=kind,
                sql=clean,
                line_start=stmt.line_start,
                line_end=stmt.line_end,
                target_as_written=target,
            )
        )
    return matches


# ── table reference detection (issue #107) ───────────────────────────────────


ReferenceKind = Literal["read", "write"]


# A quoted SQL identifier such as ``"foo"`` is at least two characters long
# (the surrounding double quotes); we use this constant to keep the magic
# number out of comparisons.
_MIN_QUOTED_IDENT_LEN: Final[int] = 2

# A fully qualified Netezza identifier has at most three parts:
# ``database.schema.table`` (or ``database..table`` with empty middle).
_MAX_QUALIFIER_PARTS: Final[int] = 3
_TWO_PARTS: Final[int] = 2


# Read verbs: FROM / JOIN (with all OUTER variants) / USING (
# We explicitly allow LEFT/RIGHT/INNER/FULL/CROSS prefixes plus optional OUTER.
_READ_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    (?:
        FROM
      | (?:(?:LEFT|RIGHT|INNER|FULL|CROSS)\s+)?(?:OUTER\s+)?JOIN
      | USING\s*\(
    )
    \s+
    """,
    re.IGNORECASE | re.VERBOSE,
)


# A FROM that is part of ``DELETE FROM`` belongs to the write classifier; we
# detect it post-hoc (matching the prefix that immediately precedes the read
# match) and skip the read scan for that occurrence.
_DELETE_FROM_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[^A-Za-z0-9_])DELETE\s+\Z", re.IGNORECASE
)


# Write verbs we recognize. Each pattern matches the verb head; the table
# reference that follows is captured by ``_parse_qualified_ref`` separately.
# ``CREATE [TEMP|TEMPORARY] TABLE [IF NOT EXISTS]`` covers the standard CTAS
# form (``CREATE TABLE foo AS SELECT …``) which lacks the ``INTO`` keyword;
# it would otherwise slip past the ``INTO`` alternative below.
_WRITE_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    (?:
        INSERT\s+INTO
      | UPDATE
      | DELETE\s+FROM
      | MERGE\s+INTO
      | TRUNCATE\s+TABLE
      | DROP\s+TABLE(?:\s+IF\s+EXISTS)?
      | CREATE\s+(?:(?:TEMP|TEMPORARY)\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?
      | INTO
    )
    \s+
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _strip_quote(token: str | None) -> str | None:
    if token is None:
        return None
    if len(token) >= _MIN_QUOTED_IDENT_LEN and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def _match_ident(text: str, start: int) -> tuple[str, int] | None:
    """Match an identifier (quoted or unquoted) at ``start``; return ``(token, end)``."""
    n = len(text)
    if start >= n:
        return None
    ch = text[start]
    if ch == '"':
        end = _scan_quoted_token(text, start, '"')
        return text[start:end], end
    if ch.isalpha() or ch == "_":
        i = start + 1
        while i < n and (text[i].isalnum() or text[i] == "_"):
            i += 1
        return text[start:i], i
    return None


def _parse_qualified_ref(text: str, start: int) -> tuple[str | None, str | None, str, int] | None:
    """Parse a qualified table reference at ``start`` in ``text``.

    Returns ``(database, schema, table, end_index)`` or ``None`` if no
    identifier is found. Empty middle parts (``bd..table`` Netezza form) are
    represented as ``None`` for that qualifier slot.
    """
    n = len(text)
    if start >= n:
        return None

    # Skip leading whitespace.
    i = start
    while i < n and text[i] in " \t\r\n":
        i += 1

    parts: list[str | None] = []
    first = _match_ident(text, i)
    if first is None:
        return None
    parts.append(first[0])
    i = first[1]

    while len(parts) < _MAX_QUALIFIER_PARTS and i < n:
        j = i
        while j < n and text[j] in " \t":
            j += 1
        if j >= n or text[j] != ".":
            break
        j += 1
        while j < n and text[j] in " \t":
            j += 1
        nxt = _match_ident(text, j)
        if nxt is None:
            # Empty qualifier — only valid as middle slot for ``bd..table``.
            parts.append(None)
            i = j
            continue
        parts.append(nxt[0])
        i = nxt[1]

    if len(parts) == 1:
        return None, None, _strip_quote(parts[0]) or "", i
    if len(parts) == _TWO_PARTS:
        return None, _strip_quote(parts[0]), _strip_quote(parts[1]) or "", i
    # Three parts: db, schema, table; schema may be None for ``db..table``.
    return _strip_quote(parts[0]), _strip_quote(parts[1]), _strip_quote(parts[2]) or "", i


def _qualifier_matches(actual: str | None, requested: str | None) -> bool:
    """Return True when ``actual`` is acceptable for ``requested``.

    If ``requested`` is None, any ``actual`` (including None) is accepted.
    If ``requested`` is given, ``actual`` must equal it case-insensitively or
    be None — interpreted as "current schema/database", which we accept.
    """
    if requested is None:
        return True
    if actual is None:
        return True
    return actual.lower() == requested.lower()


def iter_table_references_in_statement(
    stmt_sql: str,
    table: str,
    *,
    table_database: str | None = None,
    table_schema: str | None = None,
) -> Iterator[ReferenceKind]:
    """Yield ``"read"`` / ``"write"`` for each occurrence of ``table`` in ``stmt_sql``.

    ``stmt_sql`` should be a single statement as produced by
    :func:`iter_statements`. The caller is responsible for passing text where
    ``--`` and ``/* */`` comments are no longer present (for example by first
    running :func:`strip_comments`); single-quoted string literals inside the
    statement are masked here so ``'DELETE FROM foo'`` does not produce a
    reference.

    Classification rules:

    * **read** — table follows ``FROM`` / ``JOIN`` (incl. ``LEFT``/``RIGHT``/
      ``INNER``/``FULL``/``CROSS`` and ``OUTER``) / ``USING (``.
    * **write** — table follows the leading verb of one of: ``INSERT INTO``,
      ``UPDATE``, ``DELETE FROM``, ``MERGE INTO``, ``TRUNCATE TABLE``,
      ``DROP TABLE [IF EXISTS]``,
      ``CREATE [TEMP|TEMPORARY] TABLE [IF NOT EXISTS]``, or the trailing
      ``... INTO <table>`` form (CTAS / SELECT INTO).
    * Token boundaries are respected — ``Foo`` does not match ``FooBar`` /
      ``BarFoo``.
    * ``table_database`` / ``table_schema`` filter qualifiers; missing
      qualifiers in the source text are treated as "current schema/database"
      and always accepted.
    """
    if not table.strip():
        return
    table_norm = table.strip().lower()

    # Mask single-quoted strings so 'DELETE FROM foo' literals are skipped.
    masked = mask_single_quoted_strings(stmt_sql)

    yield from _scan_prefix(
        masked, _WRITE_PREFIX, table_norm, table_database, table_schema, "write"
    )
    yield from _scan_prefix(masked, _READ_PREFIX, table_norm, table_database, table_schema, "read")


def _scan_prefix(
    text: str,
    prefix: re.Pattern[str],
    table_norm: str,
    table_database: str | None,
    table_schema: str | None,
    kind: ReferenceKind,
) -> Iterator[ReferenceKind]:
    for match in prefix.finditer(text):
        # Skip ``FROM`` matches that belong to a ``DELETE FROM`` write verb so
        # the same occurrence is not classified twice (write + read). We test
        # by slicing the prefix text up to the read match start; the ``\Z``
        # anchor in ``_DELETE_FROM_PREFIX`` ensures only an immediately
        # preceding ``DELETE\s+`` triggers the skip.
        if kind == "read" and _DELETE_FROM_PREFIX.search(text[: match.start()]):
            continue
        ref = _parse_qualified_ref(text, match.end())
        if ref is None:
            continue
        db, schema, name, _end = ref
        if name.lower() != table_norm:
            continue
        if not _qualifier_matches(db, table_database):
            continue
        if not _qualifier_matches(schema, table_schema):
            continue
        yield kind


def count_table_references(
    source: str,
    table: str,
    *,
    table_database: str | None = None,
    table_schema: str | None = None,
) -> tuple[int, int]:
    """Return ``(read_occurrences, write_occurrences)`` for ``table`` in ``source``.

    ``source`` is the raw procedure body. Comments are stripped per-statement
    before scanning so commented-out verbs are not counted.
    """
    if not table.strip():
        return 0, 0
    reads = 0
    writes = 0
    for stmt in iter_statements(source):
        clean = strip_comments(stmt.sql)
        if not clean.strip():
            continue
        for kind in iter_table_references_in_statement(
            clean,
            table,
            table_database=table_database,
            table_schema=table_schema,
        ):
            if kind == "read":
                reads += 1
            else:
                writes += 1
    return reads, writes
