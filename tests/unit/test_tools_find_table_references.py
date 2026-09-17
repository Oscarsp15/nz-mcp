"""Tests for ``nz_find_table_references`` (issue #107)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nz_mcp.catalog.procedures import (
    FIND_TABLE_REFERENCES_HINT_THRESHOLD,
    FIND_TABLE_REFERENCES_SCAN_CAP,
)
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
    captured_timeout: list[int | None] | None = None,
    captured_fetch: list[str] | None = None,
) -> None:
    def _kept(pattern: str | None) -> list[dict[str, Any]]:
        # Mimic the catalog ``LIKE`` filter so tests can verify the wiring.
        if pattern:
            return [
                p for p in procedures if pattern.replace("%", "").lower() in str(p["name"]).lower()
            ]
        return list(procedures)

    def _fake(
        _profile: object,
        _database: str,
        _schema: str,
        pattern: str | None = None,
        *,
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        if captured_pattern is not None:
            captured_pattern.append(pattern)
        if captured_timeout is not None:
            captured_timeout.append(timeout_s)
        if captured_fetch is not None:
            captured_fetch.append("ddl")
        kept = _kept(pattern)
        return {
            "procedures": kept,
            "total_size_bytes": sum(int(p["size_bytes"]) for p in kept),
        }

    def _fake_list(
        _profile: object,
        _database: str,
        _schema: str,
        pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        # The cheap pre-count only needs names, never PROCEDURESOURCE.
        return [{"name": p["name"]} for p in _kept(pattern)]

    monkeypatch.setattr("nz_mcp.catalog.procedures.get_all_procedures_ddl", _fake)
    monkeypatch.setattr("nz_mcp.catalog.procedures.list_procedures", _fake_list)


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


def test_ctas_only_sp_classified_as_write(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """SP that only creates a table via standard CTAS (no INSERT INTO) must appear as write."""
    src = "BEGIN_PROC\nCREATE TEMP TABLE foo AS SELECT 1 FROM bar;\nEND_PROC;"
    procs = [_proc("SP_CTAS", src)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.match_count == 1
    assert out.references[0].procedure_name == "SP_CTAS"
    assert out.references[0].usage == "write"
    assert out.references[0].occurrences_write == 1
    assert out.references[0].occurrences_read == 0


def test_ctas_produces_both_read_and_write(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """CTAS writes the target and reads the source; searching for the source yields read."""
    src = "BEGIN_PROC\nCREATE TABLE foo AS SELECT col FROM bar;\nEND_PROC;"
    procs = [_proc("SP_CTAS_RW", src)]
    _patch_get_all(monkeypatch, procs)

    # bar is read by the CTAS
    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="bar"),
        config_path=two_profiles,
    )
    assert out.match_count == 1
    assert out.references[0].usage == "read"
    assert out.references[0].occurrences_read == 1
    assert out.references[0].occurrences_write == 0


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


# ── issue #308: cost warning, scan cap and timeout ───────────────────────────


class _FakeClock:
    """Stand-in for the ``time`` module: ``monotonic`` walks a scripted sequence."""

    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def monotonic(self) -> float:
        return next(self._values)


def test_no_hint_on_a_small_scan(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    procs = [_proc("SP_ONE", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.timed_out is False
    assert out.hint is None


def test_hint_when_scan_universe_reaches_threshold(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    procs = [
        _proc(f"SP_{i:04d}", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")
        for i in range(FIND_TABLE_REFERENCES_HINT_THRESHOLD)
    ]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    assert out.scanned_count == FIND_TABLE_REFERENCES_HINT_THRESHOLD
    assert out.timed_out is False
    assert out.hint is not None
    # The hint names the universe size and the way out.
    assert str(FIND_TABLE_REFERENCES_HINT_THRESHOLD) in out.hint
    assert "pattern" in out.hint


def test_max_procedures_tightens_the_cap(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    procs = [_proc(f"SP_{i}", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;") for i in range(3)]
    _patch_get_all(monkeypatch, procs)

    with pytest.raises(InputTooBroadError) as exc:
        nz_find_table_references(
            GetFindTableReferencesInput(
                database="D", procedure_schema="PUBLIC", table="foo", max_procedures=2
            ),
            config_path=two_profiles,
        )
    assert exc.value.context.get("scanned") == 3
    assert exc.value.context.get("cap") == 2


def test_max_procedures_fails_fast_without_fetching_ddl(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """The over-wide case must not pay for the batch DDL fetch (issue #308)."""
    fetched: list[str] = []
    procs = [_proc(f"SP_{i}", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;") for i in range(3)]
    _patch_get_all(monkeypatch, procs, captured_fetch=fetched)

    with pytest.raises(InputTooBroadError):
        nz_find_table_references(
            GetFindTableReferencesInput(
                database="D", procedure_schema="PUBLIC", table="foo", max_procedures=2
            ),
            config_path=two_profiles,
        )
    assert fetched == []


def test_max_procedures_within_cap_still_scans(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """A cap that the universe respects must not block the scan."""
    procs = [_proc(f"SP_{i}", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;") for i in range(2)]
    _patch_get_all(monkeypatch, procs)

    out = nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", max_procedures=10
        ),
        config_path=two_profiles,
    )
    assert out.scanned_count == 2
    assert out.match_count == 2


def test_default_scan_is_not_deadline_bound(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Without an explicit timeout_s a wide scan returns everything, not a partial."""
    captured: list[int | None] = []
    procs = [_proc("SP_A", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs, captured_timeout=captured)

    out = nz_find_table_references(
        GetFindTableReferencesInput(database="D", procedure_schema="PUBLIC", table="foo"),
        config_path=two_profiles,
    )
    # Nothing is forced onto the driver: open_connection keeps the profile default.
    assert captured == [None]
    assert out.timed_out is False
    assert out.match_count == 1


def test_max_procedures_above_the_hard_cap_is_rejected() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GetFindTableReferencesInput.model_validate(
            {
                "database": "D",
                "schema": "PUBLIC",
                "table": "FOO",
                "max_procedures": FIND_TABLE_REFERENCES_SCAN_CAP + 1,
            }
        )


def test_timeout_s_is_forwarded_to_the_batch_fetch(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    captured: list[int | None] = []
    procs = [_proc("SP_X", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs, captured_timeout=captured)

    nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", timeout_s=7
        ),
        config_path=two_profiles,
    )
    assert captured == [7]


def test_timed_out_when_scan_deadline_is_exceeded(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    procs = [_proc("SP_A", "BEGIN_PROC\nSELECT 1 FROM foo;\nEND_PROC;")]
    _patch_get_all(monkeypatch, procs)
    # First monotonic() sets the deadline (0 + 1s); the scan then reads 1000s and stops.
    monkeypatch.setattr(
        "nz_mcp.catalog.procedures.time",
        _FakeClock([0.0, 1000.0, 1000.0, 1000.0]),
    )

    out = nz_find_table_references(
        GetFindTableReferencesInput(
            database="D", procedure_schema="PUBLIC", table="foo", timeout_s=1
        ),
        config_path=two_profiles,
    )
    assert out.timed_out is True
    assert out.match_count == 0
    assert out.hint is not None
    assert "1" in out.hint
