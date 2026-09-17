"""``nz-mcp tools`` (issue #354): the catalog, read from the registry the server serves.

The command exists so that the catalog can be read from a terminal at all. What these tests
pin is the property that makes it worth having: it is not a second list of tools that could
drift from the real one. The registry is the only source, so the checks here compare the
command's output against that registry and against what ``tools/list`` advertises, and fail
the moment the two stop agreeing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from nz_mcp.cli import app
from nz_mcp.server import list_tools
from nz_mcp.tools.registry import TOOLS

runner = CliRunner()

_KNOWN_TOOLS = ("nz_query_select", "nz_list_tables", "nz_summarize_partitions")


def _listed() -> list[dict[str, Any]]:
    result = runner.invoke(app, ["tools", "--json"])
    assert result.exit_code == 0, result.stderr
    return cast(list[dict[str, Any]], json.loads(result.stdout))


def test_tools_lists_every_registered_tool() -> None:
    """Anti-drift guard: a tool added to the registry must appear with no other edit."""
    assert {entry["name"] for entry in _listed()} == set(TOOLS)


def test_tools_matches_what_the_mcp_server_advertises() -> None:
    """The CLI reads the same registry ``tools/list`` answers from, not a copy of it."""
    assert {entry["name"] for entry in _listed()} == {listing.name for listing in list_tools()}


def test_the_count_is_the_size_of_the_registry() -> None:
    assert len(_listed()) == len(TOOLS)


def test_every_listed_tool_carries_a_description_and_its_mode() -> None:
    for entry in _listed():
        assert entry["description"].strip(), entry["name"]
        assert entry["mode"] in ("read", "write", "admin"), entry["name"]


def test_json_output_is_valid_and_carries_the_annotations() -> None:
    listed = _listed()
    assert listed
    assert all(isinstance(entry["annotations"], dict) for entry in listed)


def test_the_default_view_prints_the_names_as_payload_on_stdout() -> None:
    result = runner.invoke(app, ["tools"])
    assert result.exit_code == 0
    for name in _KNOWN_TOOLS:
        assert name in result.stdout


def test_the_default_view_reports_how_many_were_listed_on_stderr() -> None:
    result = runner.invoke(app, ["tools"])
    assert str(len(TOOLS)) in result.stderr


def test_the_name_filter_keeps_only_the_matching_tools() -> None:
    result = runner.invoke(app, ["tools", "--name", "procedure", "--json"])
    listed = json.loads(result.stdout)
    assert listed
    assert {entry["name"] for entry in listed} == {name for name in TOOLS if "procedure" in name}


def test_the_name_filter_ignores_case() -> None:
    lower = runner.invoke(app, ["tools", "--name", "table", "--json"])
    upper = runner.invoke(app, ["tools", "--name", "TABLE", "--json"])
    assert json.loads(lower.stdout) == json.loads(upper.stdout)


def test_a_filter_that_matches_nothing_is_an_empty_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``[]`` is the machine answer; a script must not have to parse prose to learn it."""
    monkeypatch.setenv("NZ_MCP_LANG", "en")
    result = runner.invoke(app, ["tools", "--name", "zzz", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_a_filter_that_matches_nothing_says_so_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "en")
    result = runner.invoke(app, ["tools", "--name", "zzz"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "zzz" in result.stderr


def test_tools_works_without_a_profile_and_without_a_connection(tmp_profiles: Path) -> None:
    """No profile exists and Netezza is unreachable: the catalog is still readable."""
    assert not tmp_profiles.exists()
    result = runner.invoke(app, ["tools", "--json"])
    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == len(TOOLS)
