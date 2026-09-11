"""Contract: console preparation (ADR 0033, issue #255) never touches the ``serve`` path.

``cli_output.stdout_reserved_for_protocol`` is the only thing standing between the MCP
JSON-RPC stream and a stray byte, and ADR 0033 promises the new console-preparation step
never runs anywhere near it. Two layers, because a name comparison alone is a blacklist and
this project has already watched that shape of guard fail (ADR 0030, point 1):

1. :func:`test_console_prep_never_runs_when_serve_is_invoked` and
   :func:`test_console_prep_runs_for_every_other_command` exercise the cheap, named belt:
   ``cli.entry_point`` calling :func:`nz_mcp.cli_output.prepare_windows_console` only when
   ``ctx.invoked_subcommand != "serve"``. Called directly, with a minimal stand-in for
   ``click``'s context, rather than through a full ``CliRunner`` invocation of ``nz-mcp
   serve``: that was tried first and rejected, because it runs
   ``configure_logging_for_stdio()`` for real, which binds ``structlog`` to whatever
   ``sys.stderr`` is at that moment - a stream ``CliRunner`` closes when the call returns -
   and poisons every later test in the same process that logs through it.
2. :func:`test_a_piped_stdout_is_never_reconfigured_no_matter_who_calls_this` proves the
   suspenders: it calls :func:`nz_mcp.cli_output.prepare_windows_console` itself, with no
   command name anywhere in the picture, against a piped ``stdout`` - the shape ``serve``
   always has once its client has connected. Whether or not the belt above is ever bypassed,
   this is what actually keeps a redirected ``stdout`` untouched.
"""

from __future__ import annotations

import atexit
import ctypes
import os
import sys

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


class _PipedStream:
    """Stands in for ``serve``'s real ``stdout``: never a console, and records any attempt
    to reconfigure it.
    """

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self.reconfigure_calls: list[dict[str, object]] = []

    def isatty(self) -> bool:
        return self._tty

    def reconfigure(self, **kwargs: object) -> None:
        self.reconfigure_calls.append(kwargs)


class _AlwaysSucceedsKernel32:
    """A ``kernel32`` double where every call succeeds - the favourable case this test needs
    to isolate the one thing that must still hold: which *stream* gets reconfigured.
    """

    def GetConsoleOutputCP(self) -> int:  # noqa: N802
        return 850

    def SetConsoleOutputCP(self, code_page: int) -> int:  # noqa: N802
        return 1

    def GetStdHandle(self, std_handle: int) -> int:  # noqa: N802
        return std_handle

    def GetConsoleMode(self, handle: int, mode_ptr: object) -> int:  # noqa: N802
        return 1

    def SetConsoleMode(self, handle: int, mode: int) -> int:  # noqa: N802
        return 1


def test_a_piped_stdout_is_never_reconfigured_no_matter_who_calls_this(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural guarantee, with no ``"serve"`` string anywhere in this test.

    ``serve`` talks JSON-RPC over a pipe once its client has connected, so its real
    ``stdout`` never passes ``isatty()``. This calls ``prepare_windows_console`` on its own -
    not through ``entry_point``, not gated by any command name - so it keeps proving the same
    thing even if the belt in the tests above were deleted tomorrow.
    """
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv(cli_output.NO_CONSOLE_PREP_ENV, raising=False)

    class _Windll:
        kernel32 = _AlwaysSucceedsKernel32()

    monkeypatch.setattr(ctypes, "windll", _Windll(), raising=False)
    piped_stdout = _PipedStream(tty=False)
    console_stderr = _PipedStream(tty=True)
    monkeypatch.setattr(sys, "stdout", piped_stdout)
    monkeypatch.setattr(sys, "stderr", console_stderr)
    monkeypatch.setattr(atexit, "register", lambda _restore: None)

    cli_output.prepare_windows_console()

    assert piped_stdout.reconfigure_calls == []
