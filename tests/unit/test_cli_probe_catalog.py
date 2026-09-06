"""``nz-mcp probe-catalog`` (issue #206): progress while it runs, one report when it ends.

Fourteen queries in a row is the longest wait the CLI has, and it used to be spent in silence:
``run_probe_catalog`` returned the whole run and only then was anything printed, so a run that
hung said nothing about *which* query it hung on. It then printed all fourteen lines, eleven of
them ``[OK]``, which is how a failure ends up buried in the middle of good news.

What is checked here is the split: the indicator is transient and belongs to a terminal, the
report is one block on stderr, and ``--json`` owns stdout on its own and did not change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from typer.testing import CliRunner

from nz_mcp import cli
from nz_mcp.catalog.probe import ProbeResult, ProbeRun, probe_run_to_json_dict
from nz_mcp.cli import app

runner = CliRunner()


def _result(
    query_id: str,
    status: str,
    *,
    ms: float | None = 1.5,
    rows: int | None = 3,
    error: str | None = None,
    detail: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        query_id=query_id,
        status=status,  # type: ignore[arg-type]
        duration_ms=ms,
        row_count=rows,
        error_detail=error,
        detail=detail,
    )


#: A run with one of each: enough to show ordering, and small enough to read in a failure.
_MIXED_RUN: Final[ProbeRun] = ProbeRun(
    profile_name="dev",
    config_error=None,
    results=(
        _result("list_databases", "ok"),
        _result("list_schemas", "ok"),
        _result("table_stats", "structural_warning", rows=None, error="relation does not exist"),
        _result("list_tables", "failure", ms=None, rows=None, error="syntax error near FROM"),
    ),
)

_CLEAN_RUN: Final[ProbeRun] = ProbeRun(
    profile_name="dev",
    config_error=None,
    results=(_result("list_databases", "ok"), _result("list_schemas", "ok")),
)


def _install_run(monkeypatch: pytest.MonkeyPatch, run: ProbeRun) -> list[tuple[str, int, int]]:
    """Replace the probe with a canned run and record what the progress callback was told."""
    announced: list[tuple[str, int, int]] = []

    def _fake(_profile: Any, *, on_query: Any = None) -> ProbeRun:
        for position, row in enumerate(run.results, start=1):
            if on_query is not None:
                on_query(row.query_id, position, len(run.results))
            announced.append((row.query_id, position, len(run.results)))
        return run

    monkeypatch.setattr(cli, "run_probe_catalog", _fake)
    return announced


def test_the_default_report_puts_what_needs_acting_on_first(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Failures, then warnings, then one closing sentence. The successes are not listed."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _MIXED_RUN)
    result = runner.invoke(app, ["probe-catalog"])

    assert result.exit_code == 1
    body = result.stderr
    assert body.index("[FAIL] list_tables") < body.index("[WARN] table_stats")
    assert "list_databases" not in body, "a query that worked does not deserve its own line"
    assert "2 de 4 consultas OK" in body


def test_the_report_ends_with_one_conclusion_and_one_next_step(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _CLEAN_RUN)
    result = runner.invoke(app, ["probe-catalog"])

    assert result.exit_code == 0
    assert "Las 2 consultas del catálogo responden." in result.stderr
    assert "--verbose" in result.stderr


def test_a_failing_run_points_at_the_thing_to_fix(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """The next step of a failure is not "run it again with --verbose"."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _MIXED_RUN)
    result = runner.invoke(app, ["probe-catalog"])
    assert "catalog_overrides" in result.stderr


def test_verbose_shows_every_query_in_a_table(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """With ``--verbose`` the point is comparing rows, which is what a table is for."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _MIXED_RUN)
    result = runner.invoke(app, ["probe-catalog", "--verbose"])

    body = result.stderr
    for query_id in ("list_databases", "list_schemas", "table_stats", "list_tables"):
        assert query_id in body
    assert "Consulta" in body
    # ASCII markers, untranslated: the same OK / WARN / FAIL the JSON and the README use.
    assert "WARN" in body
    assert "FAIL" in body


def test_json_is_the_only_thing_on_stdout_and_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """``--json`` is a machine surface: not reordered, not translated, not summarized."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _MIXED_RUN)
    result = runner.invoke(app, ["probe-catalog", "--json"])

    assert json.loads(result.stdout) == probe_run_to_json_dict(_MIXED_RUN)
    assert result.stderr == "", "the readable report must not double up on the machine surface"


def test_the_readable_report_never_touches_stdout(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """One report, one channel. Splitting it is how redirecting it lost the failures."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    _install_run(monkeypatch, _MIXED_RUN)
    result = runner.invoke(app, ["probe-catalog", "--verbose"])
    assert result.stdout == ""


def test_each_query_is_announced_before_it_runs(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Before, not after: a callback that fired on completion would never name the one that hung."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    announced = _install_run(monkeypatch, _MIXED_RUN)
    runner.invoke(app, ["probe-catalog"])

    assert [name for name, _, _ in announced] == [row.query_id for row in _MIXED_RUN.results]
    assert [position for _, position, _ in announced] == [1, 2, 3, 4]


def test_a_configuration_error_is_reported_instead_of_an_empty_summary(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Nothing ran, so "0 of 0 queries OK" would be a true sentence that says nothing."""
    monkeypatch.setenv("NZ_MCP_LANG", "es")
    broken = ProbeRun(profile_name="dev", config_error="no password in the keyring", results=())
    _install_run(monkeypatch, broken)
    result = runner.invoke(app, ["probe-catalog"])

    assert result.exit_code == 1
    assert "no password in the keyring" in result.stderr
    assert "consultas OK" not in result.stderr
