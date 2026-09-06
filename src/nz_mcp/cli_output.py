"""Single writer for everything the ``nz-mcp`` command line puts on screen.

Why this module exists
----------------------
``nz-mcp serve`` speaks MCP JSON-RPC over **stdout**: one stray byte there
corrupts the protocol and the MCP client dies without a readable error. Before
this layer, ``cli.py`` called ``typer.echo`` / ``typer.secho`` directly in 58
places, and both default to stdout — so the protocol stayed clean by discipline
rather than by construction. Here the channel is decided once, in code a
contract test exercises, instead of once per call site.

Channel policy — decided here and nowhere else
----------------------------------------------
:func:`emit` writes to **stdout**. It carries the *payload* of a command: what
a script may pipe or redirect. Today that is the version string, the profile
names, the diagnostic report, ``--json`` documents and the Claude Desktop
snippet. Payload is never styled.

:func:`status` and its shorthands (:func:`note`, :func:`heading`,
:func:`success`, :func:`warn`, :func:`fail`) write to **stderr**. They carry
everything a person reads that is not the payload: progress, confirmations,
warnings, errors. Decoration lives here and only here, and so does any future
spinner or table.

:func:`ask`, :func:`ask_int`, :func:`ask_secret` and :func:`confirm` put their
prompt on **stderr** and read the answer from stdin. A question is not payload
either.

Colour and terminal detection
-----------------------------
:func:`color_enabled` is the only place that decides whether ANSI sequences may
be produced: a real terminal (``isatty``), no ``NO_COLOR``, no ``TERM=dumb``.
The result is passed explicitly to ``click``, which strips the sequences when
colour is off, so redirected or piped output stays plain text.

Protocol reservation
--------------------
``serve`` calls :func:`reserve_stdout_for_protocol` before handing stdout to the
MCP transport. From that point :func:`emit` raises instead of writing: a loud,
attributable failure beats a silently corrupted JSON-RPC stream.
"""

from __future__ import annotations

import os
import sys
from typing import Final, Literal, Protocol

import typer

Style = Literal["plain", "heading", "success", "warning", "error"]

_STYLE_COLORS: Final[dict[Style, str | None]] = {
    "plain": None,
    "heading": None,
    "success": typer.colors.GREEN,
    "warning": typer.colors.YELLOW,
    "error": typer.colors.RED,
}

_DUMB_TERM: Final[str] = "dumb"

# One-way switch flipped by ``serve``. A dict keeps the state mutable without a
# ``global`` statement and lets tests reset it explicitly.
_STATE: Final[dict[str, bool]] = {"stdout_reserved": False}


class SupportsIsatty(Protocol):
    """Anything that can report whether it is attached to a terminal."""

    def isatty(self) -> bool:
        """Return ``True`` when the stream is a terminal."""


def color_enabled(stream: SupportsIsatty | None = None) -> bool:
    """Report whether ANSI styling may be written to ``stream`` (default: stderr).

    Colour is opt-out in three independent ways, all honoured here so that no
    command has to re-implement the check: the ``NO_COLOR`` convention, the
    ``TERM=dumb`` convention, and the absence of a real terminal (redirection,
    pipes, CI).
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").strip().lower() == _DUMB_TERM:
        return False
    target = sys.stderr if stream is None else stream
    return bool(target.isatty())


def reserve_stdout_for_protocol() -> None:
    """Declare stdout off-limits for human text; called before serving MCP over stdio.

    Idempotent and deliberately one-way: a process that has started speaking
    JSON-RPC never goes back to being a terminal UI.
    """
    _STATE["stdout_reserved"] = True


def stdout_is_reserved() -> bool:
    """Return whether stdout has been handed over to the MCP protocol."""
    return _STATE["stdout_reserved"]


def emit(message: str = "") -> None:
    """Write command payload to stdout, unstyled.

    Raises:
        RuntimeError: When stdout has been reserved for the MCP protocol. This
            is the by-construction half of the guarantee that the contract test
            ``tests/contract/test_serve_stdout_protocol_only.py`` checks at
            runtime.
    """
    if _STATE["stdout_reserved"]:
        raise RuntimeError(
            "stdout is reserved for MCP JSON-RPC in serve mode; "
            "write to stderr with nz_mcp.cli_output.status() instead",
        )
    typer.echo(message)


def status(message: str, *, style: Style = "plain") -> None:
    """Write a human-facing line to stderr, styled only when the terminal allows it."""
    typer.secho(
        message,
        fg=_STYLE_COLORS[style],
        bold=style == "heading",
        err=True,
        color=color_enabled(sys.stderr),
    )


def note(message: str) -> None:
    """Neutral status line on stderr."""
    status(message)


def heading(message: str) -> None:
    """Section title on stderr."""
    status(message, style="heading")


def success(message: str) -> None:
    """Confirmation that something went well, on stderr."""
    status(message, style="success")


def warn(message: str) -> None:
    """Something worth knowing that does not stop the command, on stderr."""
    status(message, style="warning")


def fail(message: str) -> None:
    """Something that stopped or degraded the command, on stderr."""
    status(message, style="error")


def ask(prompt: str, *, default: str | None = None, show_default: bool = True) -> str:
    """Ask for a line of text: question on stderr, answer read from stdin."""
    return str(typer.prompt(prompt, default=default, show_default=show_default, err=True))


def ask_int(prompt: str, *, default: int) -> int:
    """Ask for an integer, with the same channel policy as :func:`ask`."""
    return int(typer.prompt(prompt, default=default, type=int, err=True))


def ask_secret(prompt: str) -> str:
    """Ask for a credential with echo disabled and confirmation; the value is never printed."""
    return str(typer.prompt(prompt, hide_input=True, confirmation_prompt=True, err=True))


def confirm(prompt: str, *, default: bool = False) -> bool:
    """Ask a yes/no question on stderr."""
    return bool(typer.confirm(prompt, default=default, err=True))


__all__: Final[tuple[str, ...]] = (
    "Style",
    "SupportsIsatty",
    "ask",
    "ask_int",
    "ask_secret",
    "color_enabled",
    "confirm",
    "emit",
    "fail",
    "heading",
    "note",
    "reserve_stdout_for_protocol",
    "status",
    "stdout_is_reserved",
    "success",
    "warn",
)
