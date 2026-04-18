"""Tests for NZPLSQL section parser."""

from __future__ import annotations

from nz_mcp.catalog.nzplsql_parser import (
    find_begin_proc_line,
    header_content,
    line_slice,
    mask_single_quoted_strings,
    parse_sections,
)


def test_mask_preserves_length_and_strips_string_innards() -> None:
    src = "x 'ab BEGIN cd' y"
    masked = mask_single_quoted_strings(src)
    assert len(masked) == len(src)
    assert "BEGIN" not in masked.split("'")[1]


def test_parse_sections_full_procedure() -> None:
    src = """
CREATE OR REPLACE PROCEDURE P() AS BEGIN_PROC
DECLARE
  x INT;
BEGIN
  SELECT 1;
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
END_PROC;
""".strip()
    sec = parse_sections(src)
    assert "header" in sec
    assert "declare" in sec
    assert "body" in sec
    assert "exception" in sec
    body = sec["body"]
    body_text = line_slice(src, body[0], body[1])
    assert "SELECT 1" in body_text
    assert "EXCEPTION" not in body_text


def test_parse_sections_case_insensitive() -> None:
    src = """
create or replace procedure p() as begin_proc
declare x int;
begin
  null;
exception
  when others then null;
end;
end_proc;
""".strip()
    sec = parse_sections(src)
    assert "body" in sec


def test_marker_inside_string_ignored() -> None:
    src = """
CREATE P AS BEGIN_PROC
BEGIN
  x := 'BEGIN';
END;
END_PROC;
""".strip()
    sec = parse_sections(src)
    body = line_slice(src, sec["body"][0], sec["body"][1])
    assert "'BEGIN'" in body


def test_find_begin_proc_line() -> None:
    src = "LINE\nBEGIN_PROC\n"
    assert find_begin_proc_line(src) == 2


def test_header_content_prefix_on_same_line() -> None:
    src = "CREATE OR REPLACE PROCEDURE X AS BEGIN_PROC\nBEGIN\nEND;\nEND_PROC;\n"
    ln = find_begin_proc_line(src)
    assert ln == 1
    h = header_content(src, ln)
    assert h == "CREATE OR REPLACE PROCEDURE X AS"


def test_line_slice_inclusive() -> None:
    src = "a\nb\nc\nd\n"
    assert line_slice(src, 2, 3) == "b\nc"


def test_parse_sections_whitespace_only() -> None:
    assert parse_sections("  \n  ") == {}


def test_parse_sections_plain_unbalanced_begin_returns_empty() -> None:
    assert parse_sections("BEGIN\n") == {}


def test_parse_sections_marked_header_prefix_same_line_as_begin_proc() -> None:
    src = "PREFIX BEGIN_PROC\nDECLARE x INT;\nBEGIN\nNULL;\nEND;\nEND_PROC\n"
    sec = parse_sections(src)
    assert sec.get("header") == (1, 1)


def test_parse_sections_marked_body_when_endproc_after_closing_end() -> None:
    src = "BEGIN_PROC\nBEGIN\nNULL;\nEND;\nEND_PROC\n"
    sec = parse_sections(src)
    assert sec.get("body") == (3, 3)


def test_parse_sections_no_begin_proc() -> None:
    assert parse_sections("BEGIN\nEND;\n") == {}


def test_parse_sections_plain_declare_begin_with_nested_loop() -> None:
    src = """
DECLARE
  P_FecCorte ALIAS FOR $1;
  v_keyregla INT;
BEGIN
  FOR V_RecCascada IN SELECT KEYREGLA FROM t LOOP
    NULL;
  END LOOP;

  RETURN 0;
END;
""".strip()
    sec = parse_sections(src)
    assert "declare" in sec
    assert "body" in sec
    body = line_slice(src, sec["body"][0], sec["body"][1])
    assert "FOR V_RecCascada" in body
    assert "RETURN 0" in body
    assert "END LOOP" in body


def test_parse_sections_plain_with_exception_block() -> None:
    src = """
DECLARE x INT;
BEGIN
  SELECT 1;
EXCEPTION
  WHEN OTHERS THEN
    NULL;
END;
""".strip()
    sec = parse_sections(src)
    assert "body" in sec and "exception" in sec
    body = line_slice(src, sec["body"][0], sec["body"][1])
    assert "SELECT 1" in body
    assert "EXCEPTION" not in body
    exc = line_slice(src, sec["exception"][0], sec["exception"][1])
    assert "WHEN OTHERS" in exc


def test_parse_sections_mixed_begin_proc_and_inner_begin_end() -> None:
    src = """
CREATE P AS BEGIN_PROC
DECLARE x INT;
BEGIN
  BEGIN
    NULL;
  END;
END;
END_PROC;
""".strip()
    sec = parse_sections(src)
    assert "body" in sec
    body = line_slice(src, sec["body"][0], sec["body"][1])
    assert "BEGIN" in body and "END;" in body


def test_mask_doubled_quote_in_string() -> None:
    src = "x := 'a''b';\nBEGIN_PROC\n"
    assert find_begin_proc_line(src) == 2


def test_parse_sections_multiline_header() -> None:
    src = "LINE1\nLINE2\nBEGIN_PROC\nBEGIN\nNULL;\nEND;\nEND_PROC\n"
    sec = parse_sections(src)
    assert sec.get("header") == (1, 2)


def test_parse_sections_body_without_exception_endproc_fallback() -> None:
    src = "BEGIN_PROC\nBEGIN\nNULL\nEND_PROC\n"
    sec = parse_sections(src)
    assert "body" in sec
    assert sec["body"] == (3, 3)


def test_parse_sections_no_main_begin_is_no_body() -> None:
    src = """
CREATE P AS BEGIN_PROC
DECLARE x INT;
END_PROC;
""".strip()
    sec = parse_sections(src)
    assert "body" not in sec
