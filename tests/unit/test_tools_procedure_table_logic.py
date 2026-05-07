"""Tests for ``nz_get_procedure_table_logic`` (issue #109)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.errors import ResponseTooLargeError
from nz_mcp.tools.procedures import (
    PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES,
    GetProcedureTableLogicInput,
    nz_get_procedure_table_logic,
)


def _row(source: str) -> dict[str, object]:
    return {
        "PROCEDURE": "SP_X",
        "PROCEDURESIGNATURE": "SP_X()",
        "ARGUMENTS": "",
        "RETURNS": "INT",
        "PROCEDURESOURCE": source,
        "OWNER": "ADMIN",
    }


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    row = _row(source)
    monkeypatch.setattr("nz_mcp.catalog.procedures._fetch_procedure_rows", lambda *a, **k: [row])
    monkeypatch.setattr("nz_mcp.catalog.procedures._pick_procedure_row", lambda *a, **k: row)


def test_input_accepts_schema_alias_and_defaults_kinds() -> None:
    inp = GetProcedureTableLogicInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "procedure": "SP", "table": "FOO"}
    )
    assert inp.procedure_schema == "PUBLIC"
    assert inp.kinds == ["create", "insert"]


def test_input_rejects_unknown_kind() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetProcedureTableLogicInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "procedure": "SP",
                "table": "FOO",
                "kinds": ["update"],
            }
        )


def test_simple_create_temp_table_returns_one_statement(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    # In a real ``_v_procedure`` body, the CREATE/INSERT we care about always
    # lives between ``;``-bounded predecessors (DECLARE blocks, prior statements).
    src = "NULL;\nCREATE TEMP TABLE foo AS SELECT 1;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 1
    assert out.not_found is False
    assert out.statements[0].kind == "CREATE TEMP TABLE"
    assert out.statements[0].sql.endswith(";")
    assert out.duration_ms >= 0


def test_create_then_insert_returns_two_in_order(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "NULL;\nCREATE TABLE foo AS SELECT 1;\nINSERT INTO foo SELECT 2;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 2
    assert [s.kind for s in out.statements] == ["CREATE TABLE", "INSERT INTO"]


def test_comments_stripped_from_returned_sql_but_boundaries_intact(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = (
        "-- header\n"
        "CREATE TEMP TABLE foo AS /* mid; comment */\n"
        "  SELECT 1; -- inline; remark\n"
        "SELECT 2;\n"
    )
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 1
    sql = out.statements[0].sql
    assert "--" not in sql
    assert "/*" not in sql
    assert sql.endswith(";")


def test_string_literal_with_semicolon_does_not_split_statement(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "INSERT INTO foo VALUES ('a;b');\nSELECT 1;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 1
    assert "'a;b'" in out.statements[0].sql


def test_table_only_in_from_returns_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "INSERT INTO bar SELECT * FROM foo;\nSELECT * FROM foo JOIN baz ON 1;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 0
    assert out.not_found is True
    assert out.statements == []


def test_kinds_create_only_excludes_insert(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "CREATE TABLE foo AS SELECT 1;\nINSERT INTO foo SELECT 2;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP",
            table="foo",
            kinds=["create"],
        ),
        config_path=two_profiles,
    )
    assert out.count == 1
    assert out.statements[0].kind == "CREATE TABLE"


def test_case_insensitive_match_echoes_source_casing(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "CREATE TABLE Foo AS SELECT 1;\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.count == 1
    # Echo preserves the source casing of the first match.
    assert out.table == "Foo"


def test_line_numbers_refer_to_raw_source(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = (
        "-- header line 1\n"  # 1
        "-- header line 2\n"  # 2
        "CREATE TEMP TABLE foo AS\n"  # 3
        "  SELECT 1\n"  # 4
        "  FROM bar;\n"  # 5
    )
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    assert out.statements[0].line_start == 3
    assert out.statements[0].line_end == 5


def test_response_too_large_raises(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    """When the cumulative ``sql`` size exceeds 200 KB, the tool raises."""
    big_select = "SELECT '" + "X" * (PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES + 1024) + "'"
    src = f"CREATE TEMP TABLE foo AS\n{big_select};\n"
    _patch_fetch(monkeypatch, src)

    with pytest.raises(ResponseTooLargeError) as exc:
        nz_get_procedure_table_logic(
            GetProcedureTableLogicInput(
                database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
            ),
            config_path=two_profiles,
        )
    assert exc.value.code == "RESPONSE_TOO_LARGE"


def test_size_bytes_matches_utf8_length(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "CREATE TEMP TABLE foo AS SELECT 'ñ';\n"
    _patch_fetch(monkeypatch, src)

    out = nz_get_procedure_table_logic(
        GetProcedureTableLogicInput(
            database="D", procedure_schema="PUBLIC", procedure="SP", table="foo"
        ),
        config_path=two_profiles,
    )
    s = out.statements[0]
    assert s.size_bytes == len(s.sql.encode("utf-8"))
