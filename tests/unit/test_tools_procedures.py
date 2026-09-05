"""Tests for procedure MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nz_mcp.config import MAX_ROWS_CAP
from nz_mcp.tools.procedures import (
    PROC_DDL_DEFAULT_MAX_BYTES,
    PROC_DDL_LARGE_WARNING,
    PROC_DDL_MAX_BYTES_CAP,
    PROC_DDL_MIN_MAX_BYTES,
    PROC_DDL_WARN_BYTES,
    DescribeProcedureInput,
    GetProcedureDdlInput,
    GetProceduresDdlBatchInput,
    GetProcedureSectionInput,
    GetProcedureSizeInput,
    ListProceduresInput,
    nz_describe_procedure,
    nz_get_procedure_ddl,
    nz_get_procedure_section,
    nz_get_procedure_size,
    nz_get_procedures_ddl_batch,
    nz_list_procedures,
)


def test_list_input_accepts_schema_alias() -> None:
    p = ListProceduresInput.model_validate({"database": "D", "schema": "PUBLIC"})
    assert p.procedure_schema == "PUBLIC"


def test_nz_list_procedures_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_list(
        _profile: object,
        database: str,
        schema: str,
        pattern: str | None = None,
    ) -> list[dict[str, str]]:
        assert database == "D"
        assert schema == "PUBLIC"
        assert pattern is None
        return [
            {
                "name": "SP1",
                "owner": "ADMIN",
                "language": "NZPLSQL",
                "arguments": "(INT)",
                "returns": "INT",
            },
        ]

    monkeypatch.setattr("nz_mcp.tools.procedures.list_procedures", _fake_list)
    out = nz_list_procedures(
        ListProceduresInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert len(out.procedures) == 1
    assert out.procedures[0].name == "SP1"
    assert out.duration_ms >= 0


def test_nz_describe_procedure_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_describe(
        *_a: object,
        **_k: object,
    ) -> dict[str, object]:
        return {
            "name": "SP",
            "owner": "ADMIN",
            "language": "NZPLSQL",
            "arguments": [{"name": "x", "type": "INT"}],
            "returns": "INT",
            "created_at": None,
            "lines": 3,
            "sections_detected": ["header", "body"],
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.describe_procedure", _fake_describe)
    out = nz_describe_procedure(
        DescribeProcedureInput(database="D", procedure_schema="PUBLIC", procedure="SP"),
        config_path=two_profiles,
    )
    assert out.name == "SP"
    assert out.arguments[0].name == "x"
    assert out.duration_ms >= 0


def test_nz_get_procedure_ddl_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    def _fake_ddl(*_a: object, **_k: object) -> str:
        return "CREATE OR REPLACE PROCEDURE ..."

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="SP"),
        config_path=two_profiles,
    )
    assert "CREATE OR REPLACE" in out.ddl
    assert out.size_bytes == len(out.ddl.encode("utf-8"))
    assert out.warning is None
    assert out.duration_ms >= 0


def test_nz_get_procedure_ddl_large_emits_warning(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Raising max_bytes above the warn threshold still surfaces the size warning."""
    big = "P" * (PROC_DDL_WARN_BYTES + 1)

    def _fake_ddl(*_a: object, **_k: object) -> str:
        return big

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP",
            max_bytes=PROC_DDL_MAX_BYTES_CAP,
        ),
        config_path=two_profiles,
    )
    assert out.warning == PROC_DDL_LARGE_WARNING
    assert out.truncated is False
    assert out.hint is None
    assert out.size_bytes == len(big.encode("utf-8"))


def test_nz_get_procedure_section_happy(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_sec(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "section": "body",
            "from_line": 2,
            "to_line": 5,
            "content": "x",
            "truncated": False,
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_section", _fake_sec)
    out = nz_get_procedure_section(
        GetProcedureSectionInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP",
            section="body",
        ),
        config_path=two_profiles,
    )
    assert out.section == "body"
    assert out.from_line == 2
    assert out.duration_ms >= 0


def test_nz_get_procedures_ddl_batch_happy(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_batch(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "procedures": [
                {
                    "name": "SP1",
                    "owner": "ADMIN",
                    "arguments": "()",
                    "returns": "INT",
                    "ddl": "CREATE OR REPLACE ...",
                    "signature": "()",
                    "last_altered": "2026",
                    "size_bytes": 100,
                }
            ],
            "total_size_bytes": 100,
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.get_all_procedures_ddl", _fake_batch)
    out = nz_get_procedures_ddl_batch(
        GetProceduresDdlBatchInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert out.count == 1
    assert out.total_size_bytes == 100
    assert out.procedures[0].name == "SP1"
    assert out.warning is None
    assert out.duration_ms >= 0


def test_nz_get_procedures_ddl_batch_warning_individual(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_batch(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "procedures": [
                {
                    "name": "SP1",
                    "owner": "A",
                    "arguments": "",
                    "returns": "",
                    "ddl": "",
                    "signature": "",
                    "last_altered": "",
                    "size_bytes": PROC_DDL_WARN_BYTES + 1,
                }
            ],
            "total_size_bytes": PROC_DDL_WARN_BYTES + 1,
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.get_all_procedures_ddl", _fake_batch)
    out = nz_get_procedures_ddl_batch(
        GetProceduresDdlBatchInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert out.warning == "One or more procedures exceed ~100 KB in DDL size."


def test_nz_get_procedures_ddl_batch_warning_total(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _fake_batch(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "procedures": [],
            "total_size_bytes": 1024 * 1024 + 1,
        }

    monkeypatch.setattr("nz_mcp.tools.procedures.get_all_procedures_ddl", _fake_batch)
    out = nz_get_procedures_ddl_batch(
        GetProceduresDdlBatchInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert out.warning == "Total DDL size exceeds ~1 MB."


# ── variant field on nz_get_procedure_ddl ─────────────────────────────────────


def test_nz_get_procedure_ddl_default_variant_is_raw(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Default variant is 'raw' — back-compat: returned ddl must be the raw source."""
    raw_source = (
        "CREATE OR REPLACE PROCEDURE S.P() RETURNS INT LANGUAGE NZPLSQL AS -- comment\n"
        "BEGIN_PROC\n"
        "  x := 1; -- assign\n"
        "END_PROC;"
    )

    def _fake_ddl(*_a: object, **_k: object) -> str:
        return raw_source

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="P"),
        config_path=two_profiles,
    )
    # default variant=raw → ddl contains comments
    assert "-- comment" in out.ddl
    assert "-- assign" in out.ddl
    # both sizes always present
    assert out.size_bytes_raw >= out.size_bytes_clean
    assert out.size_bytes == out.size_bytes_raw


def test_nz_get_procedure_ddl_variant_raw_explicit(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Explicit variant='raw' behaves identically to the default."""
    raw_source = (
        "CREATE OR REPLACE PROCEDURE S.P() RETURNS INT LANGUAGE NZPLSQL AS -- comment\n"
        "BEGIN_PROC\n"
        "  x := 1;\n"
        "END_PROC;"
    )

    def _fake_ddl(*_a: object, **_k: object) -> str:
        return raw_source

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="P", variant="raw"),
        config_path=two_profiles,
    )
    assert "-- comment" in out.ddl
    assert out.size_bytes == out.size_bytes_raw


def test_nz_get_procedure_ddl_variant_clean_strips_comments(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """variant='clean' returns DDL without -- or /* */ comments."""
    raw_source = (
        "/* header block */\n"
        "CREATE OR REPLACE PROCEDURE S.P() RETURNS INT LANGUAGE NZPLSQL AS\n"
        "BEGIN_PROC\n"
        "  x := 1; -- assign x\n"
        "  /* another block */ y := 2;\n"
        "END_PROC;"
    )

    def _fake_ddl(*_a: object, **_k: object) -> str:
        return raw_source

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(
            database="D", procedure_schema="PUBLIC", procedure="P", variant="clean"
        ),
        config_path=two_profiles,
    )
    assert "--" not in out.ddl
    assert "/*" not in out.ddl
    assert "x := 1;" in out.ddl
    assert "y := 2;" in out.ddl
    # size_bytes reflects the clean variant
    assert out.size_bytes == out.size_bytes_clean
    assert out.size_bytes_raw > out.size_bytes_clean


def test_nz_get_procedure_ddl_sizes_always_present(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """size_bytes_raw and size_bytes_clean must be present in every response."""
    raw_source = (
        "CREATE OR REPLACE PROCEDURE S.P() RETURNS INT LANGUAGE NZPLSQL AS\n"
        "BEGIN_PROC\n"
        "  NULL;\n"
        "END_PROC;"
    )

    def _fake_ddl(*_a: object, **_k: object) -> str:
        return raw_source

    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", _fake_ddl)
    for variant in ("raw", "clean"):
        out = nz_get_procedure_ddl(
            GetProcedureDdlInput(
                database="D",
                procedure_schema="PUBLIC",
                procedure="P",
                variant=variant,
            ),
            config_path=two_profiles,
        )
        assert out.size_bytes_raw >= 0
        assert out.size_bytes_clean >= 0
        assert out.size_bytes_raw >= out.size_bytes_clean


# ── nz_get_procedure_size ─────────────────────────────────────────────────────


def test_nz_get_procedure_size_happy(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    """Standard procedure returns metrics without body."""
    # We mock the low level fetch/pick to test the actual catalog logic
    row = {
        "PROCEDURE": "MY_SP",
        "PROCEDURESIGNATURE": "MY_SP()",
        "ARGUMENTS": "",
        "RETURNS": "INT",
        "PROCEDURESOURCE": "BEGIN_PROC\n  BEGIN\n    x := 1;\n  END;\nEND_PROC;",
        "OWNER": "ADMIN",
    }
    monkeypatch.setattr("nz_mcp.catalog.procedures._fetch_procedure_rows", lambda *a, **k: [row])
    monkeypatch.setattr("nz_mcp.catalog.procedures._pick_procedure_row", lambda *a, **k: row)

    out = nz_get_procedure_size(
        GetProcedureSizeInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="MY_SP",
        ),
        config_path=two_profiles,
    )
    assert out.name == "MY_SP"
    assert out.signature == "MY_SP()"
    assert out.size_bytes_raw > 0
    assert out.size_bytes_clean == out.size_bytes_raw
    assert out.lines_raw == out.lines_clean
    assert "body" in out.sections_detected


def test_nz_get_procedure_size_with_comments(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Procedure with comments must reflect clean < raw metrics."""
    row = {
        "PROCEDURE": "SP_COMMENTS",
        "PROCEDURESIGNATURE": "SP_COMMENTS()",
        "ARGUMENTS": "",
        "RETURNS": "INT",
        "PROCEDURESOURCE": (
            "BEGIN_PROC\n  BEGIN\n    -- c1\n    -- c2\n    -- c3\n    x := 1;\n  END;\nEND_PROC;"
        ),
        "OWNER": "ADMIN",
    }
    monkeypatch.setattr("nz_mcp.catalog.procedures._fetch_procedure_rows", lambda *a, **k: [row])
    monkeypatch.setattr("nz_mcp.catalog.procedures._pick_procedure_row", lambda *a, **k: row)

    out = nz_get_procedure_size(
        GetProcedureSizeInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP_COMMENTS",
        ),
        config_path=two_profiles,
    )
    assert out.size_bytes_clean < out.size_bytes_raw
    assert out.lines_clean < out.lines_raw


def test_nz_get_procedure_size_with_overload(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Overloads must be resolvable via signature."""
    row = {
        "PROCEDURE": "SP_OVERLOAD",
        "PROCEDURESIGNATURE": "SP_OVERLOAD(INT)",
        "ARGUMENTS": "(INT)",
        "RETURNS": "INT",
        "PROCEDURESOURCE": "BEGIN_PROC\n  BEGIN\n  END;\nEND_PROC;",
        "OWNER": "ADMIN",
    }
    monkeypatch.setattr("nz_mcp.catalog.procedures._fetch_procedure_rows", lambda *a, **k: [row])
    monkeypatch.setattr("nz_mcp.catalog.procedures._pick_procedure_row", lambda *a, **k: row)

    out = nz_get_procedure_size(
        GetProcedureSizeInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="SP_OVERLOAD",
            signature="SP_OVERLOAD(INT)",
        ),
        config_path=two_profiles,
    )
    assert out.signature == "SP_OVERLOAD(INT)"


# ── issue #165: output caps for nz_list_procedures / nz_get_procedure_ddl ────


def _fake_rows(count: int) -> list[dict[str, str]]:
    return [
        {
            "name": f"SP{i}",
            "owner": "ADMIN",
            "language": "NZPLSQL",
            "arguments": "(INT)",
            "returns": "INT",
        }
        for i in range(count)
    ]


def _patch_list(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    rows = _fake_rows(count)
    monkeypatch.setattr(
        "nz_mcp.tools.procedures.list_procedures",
        lambda *_a, **_k: rows,
    )


def test_nz_list_procedures_under_cap_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _patch_list(monkeypatch, 3)
    out = nz_list_procedures(
        ListProceduresInput(database="D", procedure_schema="PUBLIC", max_rows=10),
        config_path=two_profiles,
    )
    assert len(out.procedures) == 3
    assert out.truncated is False
    assert out.hint is None


def test_nz_list_procedures_truncates_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _patch_list(monkeypatch, 714)
    out = nz_list_procedures(
        ListProceduresInput(database="D", procedure_schema="PUBLIC", max_rows=5),
        config_path=two_profiles,
    )
    assert len(out.procedures) == 5
    assert out.procedures[0].name == "SP0"
    assert out.truncated is True
    assert out.hint is not None
    assert "714" in out.hint
    assert "pattern" in out.hint
    assert "max_rows" in out.hint


def test_nz_list_procedures_defaults_to_profile_max_rows(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Without max_rows the active profile default (100) applies."""
    _patch_list(monkeypatch, 101)
    out = nz_list_procedures(
        ListProceduresInput(database="D", procedure_schema="PUBLIC"),
        config_path=two_profiles,
    )
    assert len(out.procedures) == 100
    assert out.truncated is True


def test_list_procedures_input_rejects_max_rows_over_cap() -> None:
    with pytest.raises(ValidationError):
        ListProceduresInput.model_validate(
            {"database": "D", "schema": "PUBLIC", "max_rows": MAX_ROWS_CAP + 1},
        )


def _big_ddl(source_lines: int) -> str:
    body = "\n".join(f"  x := {i}; -- filler comment padding the line" for i in range(source_lines))
    return f"CREATE OR REPLACE PROCEDURE S.P()\nLANGUAGE NZPLSQL AS\nBEGIN_PROC\n{body}\nEND_PROC;"


def test_nz_get_procedure_ddl_truncates_by_default_and_hints(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    ddl = _big_ddl(4000)
    assert len(ddl.encode("utf-8")) > PROC_DDL_DEFAULT_MAX_BYTES
    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", lambda *_a, **_k: ddl)

    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="P"),
        config_path=two_profiles,
    )
    assert out.truncated is True
    assert out.size_bytes <= PROC_DDL_DEFAULT_MAX_BYTES
    assert out.size_bytes_raw == len(ddl.encode("utf-8"))
    assert out.hint is not None
    assert "nz_get_procedure_size" in out.hint
    assert "nz_get_procedure_section" in out.hint
    assert "from_line=" in out.hint
    # The DDL header (2 lines) is not counted in the source resume line.
    resume = int(out.hint.split("from_line=")[1].split(",")[0])
    assert resume == len(out.ddl.splitlines()) - 1


def test_nz_get_procedure_ddl_under_cap_keeps_full_text(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    ddl = _big_ddl(10)
    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", lambda *_a, **_k: ddl)

    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(database="D", procedure_schema="PUBLIC", procedure="P"),
        config_path=two_profiles,
    )
    assert out.ddl == ddl
    assert out.truncated is False
    assert out.hint is None


def test_nz_get_procedure_ddl_clean_variant_respects_max_bytes(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    ddl = _big_ddl(4000)
    monkeypatch.setattr("nz_mcp.tools.procedures.get_procedure_ddl", lambda *_a, **_k: ddl)

    out = nz_get_procedure_ddl(
        GetProcedureDdlInput(
            database="D",
            procedure_schema="PUBLIC",
            procedure="P",
            variant="clean",
            max_bytes=PROC_DDL_MIN_MAX_BYTES,
        ),
        config_path=two_profiles,
    )
    assert out.truncated is True
    assert out.size_bytes <= PROC_DDL_MIN_MAX_BYTES
    assert "-- filler" not in out.ddl
    assert out.hint is not None


def test_get_procedure_ddl_input_rejects_max_bytes_over_cap() -> None:
    with pytest.raises(ValidationError):
        GetProcedureDdlInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "procedure": "P",
                "max_bytes": PROC_DDL_MAX_BYTES_CAP + 1,
            },
        )
