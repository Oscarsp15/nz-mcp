"""Contract: console preparation (ADR 0033, issue #255) never touches the ``serve`` path.

``cli_output.stdout_reserved_for_protocol`` is the only thing standing between the MCP
JSON-RPC stream and a stray byte, and ADR 0033 promises the new console-preparation step
never runs anywhere near it. This calls the real production ``cli.entry_point`` - the single
place that decides whether to call ``prepare_windows_console`` - with a minimal stand-in for
``click``'s context that carries just the one attribute the function reads before making
that decision.

A full ``CliRunner`` invocation of ``nz-mcp serve`` was tried first and rejected: it runs
``configure_logging_for_stdio()`` for real, which binds ``structlog`` to whatever
``sys.stderr`` is at that moment - a stream ``CliRunner`` closes when the call returns - and
poisons every later test in the same process that logs through it. Exercising
``entry_point`` directly proves the same guarantee without paying that cost or carrying that
risk into the rest of the suite.
"""

from __future__ import annotations

import pytest

from nz_mcp import cli, cli_output


class _FakeContext:
    """Stands in for ``typer.Context``: ``entry_point`` reads only this one attribute
    before deciding whether to call ``prepare_windows_console``.
    """

    def __init__(self, invoked_subcommand: str) -> None:
        self.invoked_subcommand = invoked_subcommand


def test_console_prep_never_runs_when_serve_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reservation of stdout for the MCP protocol must never share the console with this."""

    def explode() -> None:
        raise AssertionError("console preparation ran on the serve path")

    monkeypatch.setattr(cli_output, "prepare_windows_console", explode)

    cli.entry_point(_FakeContext("serve"))  # type: ignore[arg-type]


def test_console_prep_runs_for_every_other_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exclusion above is ``serve``-specific, not console preparation being dead code."""
    calls: list[None] = []
    monkeypatch.setattr(cli_output, "prepare_windows_console", lambda: calls.append(None))

    cli.entry_point(_FakeContext("version"))  # type: ignore[arg-type]

    assert len(calls) == 1
