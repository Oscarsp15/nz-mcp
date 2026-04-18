"""Lightweight NZPLSQL section parser for stored procedures (markers only, not a full AST)."""

from __future__ import annotations

import re
from typing import Final

# Markers are matched outside of single-quoted string regions (masking applied first).
_BEGIN_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bBEGIN_PROC\b")
_DECLARE: Final[re.Pattern[str]] = re.compile(r"(?i)\bDECLARE\b")
_EXCEPTION: Final[re.Pattern[str]] = re.compile(r"(?i)\bEXCEPTION\b")
_END_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bEND_PROC\b")
_BEGIN_NOT_PROC: Final[re.Pattern[str]] = re.compile(r"(?i)\bBEGIN\b")
_END_STMT: Final[re.Pattern[str]] = re.compile(r"(?i)^\s*END\s*;\s*$")
_END_LOOP_IF_CASE: Final[re.Pattern[str]] = re.compile(
    r"(?i)^\s*END\s+(LOOP|IF|CASE)\b"
)


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


def parse_sections(source: str) -> dict[str, tuple[int, int]]:  # noqa: PLR0912
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

    return _parse_sections_plain_nzplsql(masked_lines, lines, n)


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
    lines: list[str],
    n: int,
) -> dict[str, tuple[int, int]]:
    declare_line = _first_line_matching(masked_lines, _DECLARE)
    start_search = 1 if declare_line is None else declare_line + 1
    main_begin_line = _first_plain_begin(masked_lines, start_search, n)
    if main_begin_line is None:
        return {}

    exception_line = _first_line_matching_after(masked_lines, _EXCEPTION, main_begin_line + 1)

    closing_end_line = _find_plain_outer_end(masked_lines, main_begin_line, n)
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


def _first_plain_begin(masked_lines: list[str], start_line: int, n: int) -> int | None:
    for i in range(start_line, n + 1):
        line = masked_lines[i - 1]
        if _BEGIN_PROC.search(line):
            continue
        if _BEGIN_NOT_PROC.search(line):
            return i
    return None


def _find_plain_outer_end(masked_lines: list[str], main_begin_line: int, n: int) -> int | None:
    """Find the ``END;`` that closes the outer ``BEGIN`` at ``main_begin_line``."""
    depth = 1
    i = main_begin_line + 1
    while i <= n:
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
