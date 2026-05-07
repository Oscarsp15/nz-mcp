"""Tests for ``nz_find_table_references`` (issue #107)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nz_mcp.errors import InputTooBroadError
from nz_mcp.tools.procedures import (
    GetFindTableReferencesInput,
    nz_find_table_references,
)


def _proc(name: str, source: str, last_altered: str = "2026-04-15 10:30:00") -> dict[str, Any]:
    """Build the dict shape ``get_all_procedures_ddl`` produces per procedure."""
    ddl = f"CREATE OR REPLACE PROCEDURE PUB.{name}() RETURNS INT\nLANGUAGE NZPLSQL AS\n{source}"
    return {
        "name": name,
        "owner": "ADMIN",
        "arguments": "",
        "returns": "INT",
        "ddl": ddl,
        "signature": f"{name}()",
        "last_altered": last_altered,
        "size_bytes": len(ddl.encode("utf-8")),
    }


def _patch_get_all(
    monkeypatch: pytest.MonkeyPatch,
    procedures: list[dict[str, Any]],
    *,
    captured_pattern: list[str | None] | None = None,
) -> None:
    def _fake(
        _profile: object,
        _database: str,
        _schema: str,
        pattern: str | None = None,
    ) -> dict[str, Any]:
        if captured_pattern is not None:
            captured_pattern.append(pattern)
        # Mimic the catalog ``LIKE`` filter so tests can verify the wiring.
        if pattern:
            kept = [
                p for p in procedures if pattern.replace("%", "").lower() in str(p["name"]).lower()
            ]
        else:
            kept = list(procedures)
        return {
            "procedures": kept,
            "total_size_bytes": sum(int(p["size_bytes"]) for p in kept),
        }

    monkeypatch.setattr("nz_mcp.catalog.procedures.get_all_procedures_ddl", _fake)


def test_input_accepts_schema_alias_and_defaults() -> None:
    inp = GetFindTableReferencesInput.model_validate(
        {"database": "D", "schema": "PUBLIC", "table": "FOO"}
    )
    assert inp.procedure_schema == "PUBLIC"
    assert inp.table_database is None
    assert inp.table_schema is None
    assert inp.pattern is None


def test_input_rejects_extra_fields() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "table": "FOO",
                "kinds": ["read"],  # not allowed
            }
        )


def test_input_rejects_blank_pattern() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesInput.model_validate(
            {"database": "D", "schema": "PUBLIC", "table": "FOO", "pattern": ""}
        )


def test_read_only_sp_classified_as_read(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    procs = [_proc("SP_READS", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.scanned_count == 1
    assert out.match_count == 1
    assert out.references[0].usage == "read"
    assert out.references[0].occurrences_read == 1
    assert out.references[0].occurrences_write == 0


def test_write_only_sp_classified_as_write(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    procs = [_proc("SP_WRITES", "BEGIN_PROC\nINSERT INTO foo VALUES (1);\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.references[0].usage == "write"
    assert out.references[0].occurrences_write == 1


def test_both_when_sp_reads_and_writes(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    src = "BEGIN_PROC\nINSERT INTO foo SELECT 1;\nSELECT * FROM foo;\nEND_PROC;"
    procs = [_proc("SP_BOTH", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.references[0].usage == "both"
    assert out.references[0].occurrences_read == 1
    assert out.references[0].occurrences_write == 1


def test_multiple_occurrences_counted_correctly(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = (
        "BEGIN_PROC\n"
        "INSERT INTO foo SELECT 1;\n"
        "INSERT INTO foo SELECT 2;\n"
        "SELECT 1 FROM foo;\n"
        "SELECT 1 FROM bar JOIN foo ON 1;\n"
        "SELECT 1 FROM baz LEFT JOIN foo ON 1;\n"
        "END_PROC;"
    )
    procs = [_proc("SP_MULTI", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.references[0].occurrences_read == 3
    assert out.references[0].occurrences_write == 2


def test_token_boundary_no_match(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    src = "BEGIN_PROC\nSELECT 1 FROM FooBar;\nINSERT INTO BarFoo VALUES (1);\nEND_PROC;"
    procs = [_proc("SP_NOPE", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.match_count == 0


def test_comment_does_not_count(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    src = "BEGIN_PROC\n-- DELETE FROM foo;\n/* INSERT INTO foo VALUES (1); */\nSELECT 1;\nEND_PROC;"
    procs = [_proc("SP_COMMENTED", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.match_count == 0


def test_string_literal_does_not_count(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    src = "BEGIN_PROC\nINSERT INTO bar VALUES ('DELETE FROM foo');\nEND_PROC;"
    procs = [_proc("SP_LIT", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.match_count == 0


def test_table_database_filter_excludes_other_db(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "BEGIN_PROC\nSELECT 1 FROM otherdb.s.foo;\nEND_PROC;"
    procs = [_proc("SP_QUAL", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", table_database="db1"
        ),
        config_path=two_profiles,
    )
    assert out.match_count == 0


def test_table_schema_filter_includes_unqualified(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    src = "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;"
    procs = [_proc("SP_UNQ", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", table_schema="s1"
        ),
        config_path=two_profiles,
    )
    assert out.match_count == 1


def test_pattern_narrows_scan(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    captured: list[str | None] = []
    procs = [
        _proc("SP_KEEP", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;"),
        _proc("SP_DROP", "BEGIN_PROC\nINSERT INTO foo VALUES (1);\nEND_PROC;"),
    ]
    _patch_get_all(monkeypatch, procs, captured_pattern=captured)

    out = nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", pattern="SP_KEEP%"
        ),
        config_path=two_profiles,
    )
    # Stub honors the pattern by simple substring; only SP_KEEP survives.
    assert captured == ["SP_KEEP%"]
    assert out.scanned_count == 1
    assert out.match_count == 1
    assert out.references[0].procedure_name == "SP_KEEP"


def test_truncation_when_more_than_1000_references(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    # Create 1001 SPs that all reference foo with varying occurrence counts.
    procs: list[dict[str, Any]] = []
    for i in range(1001):
        # Give SP_0 the highest read count so the sort can be verified.
        n_reads = 100 if i == 0 else 1
        body = "\n".join(["SELECT 1 FROM foo;"] * n_reads)
        procs.append(_proc(f"SP_{i:04d}", f"BEGIN_PROC\n{body}\nEND_PROC;"))
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.scanned_count == 1001
    assert out.truncated is True
    assert out.match_count == 1000
    # Sorted desc by total occurrences → SP_0000 (with 100 reads) is first.
    assert out.references[0].procedure_name == "SP_0000"
    assert out.references[0].occurrences_read == 100


def test_input_too_broad_when_scan_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    # 5001 SPs (one over the hard cap). Use a tiny placeholder body — counts
    # don't matter because the scan must abort before classification.
    procs = [_proc(f"SP_{i:05d}", "BEGIN_PROC\nNULL;\nEND_PROC;") for i in range(5001)]
    _patch_get_all(monkeypatch, procs)

    with pytest.raises(InputTooBroadError) as exc:
        nz_find_table_references(
            GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
            config_path=two_profiles,
        )
    assert exc.value.code == "INPUT_TOO_BROAD"
    assert exc.value.context.get("scanned") == 5001
    assert exc.value.context.get("cap") == 5000


def test_results_sorted_descending_by_total_occurrences(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    high_body = "SELECT 1 FROM foo;\nSELECT 1 FROM foo;\nINSERT INTO foo VALUES (1);\n"
    mid_body = "INSERT INTO foo SELECT 1;\nSELECT 1 FROM foo;\n"
    procs = [
        _proc("SP_LOW", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;"),
        _proc("SP_HIGH", f"BEGIN_PROC\n{high_body}END_PROC;"),
        _proc("SP_MID", f"BEGIN_PROC\n{mid_body}END_PROC;"),
    ]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    names = [r.procedure_name for r in out.references]
    assert names == ["SP_HIGH", "SP_MID", "SP_LOW"]


def test_duration_ms_non_negative(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    procs = [_proc("SP_X", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.duration_ms >= 0
