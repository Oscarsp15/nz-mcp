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
table.

:func:`progress` is the same channel in its transient form: an indeterminate
activity indicator on stderr for the waits that are real, erased when the block
ends so the caller's result line replaces it. It is the only code allowed to
write a control character, and it writes none at all when there is no terminal.

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
``serve`` runs inside :func:`stdout_reserved_for_protocol`, which works at the
**file descriptor** level and not by convention: descriptor 1 is duplicated to a
private one, descriptor 1 itself is pointed at stderr, and the private duplicate is
handed to the MCP transport as an explicit stream.

The consequence is that the protocol has no name any more. ``sys.stdout`` still
exists and still works — it just resolves to descriptor 1, which is now stderr — so
``os.write(1, ...)``, a forgotten ``print``, a third-party library or a C extension
all land on stderr and physically cannot corrupt the JSON-RPC stream. Nothing
reaches the protocol except the object the transport was given. A name-based source
check can only ever be an incomplete blacklist; this is the part that holds by
construction.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import os
import sys
import threading
from collections.abc import Iterator
from typing import Final, Literal, Protocol, TextIO

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

#: Frames of the activity indicator, in ASCII on purpose. A Windows console running a
#: legacy code page renders anything outside ASCII as ``?``, which is what the CLI design
#: found while walking the install path, so braille dots and block characters are out.
_SPINNER_FRAMES: Final[tuple[str, ...]] = ("-", "\\", "|", "/")

#: Seconds between frames. Fast enough to read as motion, slow enough not to flood a
#: slow terminal or a serial console.
_SPINNER_INTERVAL_S: Final[float] = 0.12

#: Seconds of silence before the first frame is drawn. Below this, a person has not
#: started waiting yet and an indicator that appears and vanishes is flicker, not
#: information: a level that resolves instantly — a skipped one, a local error — prints
#: its result line and nothing else.
_SPINNER_GRACE_S: Final[float] = 0.25

#: How long :func:`progress` waits for the animation thread to clear its line. Only
#: relevant if the terminal blocks on write; the thread is a daemon either way.
_SPINNER_JOIN_S: Final[float] = 1.0

#: Standard descriptors. The guarantee is about these numbers, not about the
#: ``sys.stdout`` object: that is the whole point of doing it down here.
_STDOUT_FD: Final[int] = 1
_STDERR_FD: Final[int] = 2

# Flipped while ``serve`` owns stdout. A dict keeps the state mutable without a
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


def animation_enabled(stream: SupportsIsatty | None = None) -> bool:
    """Report whether a moving indicator may be drawn on ``stream`` (default: stderr).

    Deliberately not the same predicate as :func:`color_enabled`. ``NO_COLOR`` is a
    convention about *colour*, and an indicator carries information colour does not — the
    command is alive — so it survives ``NO_COLOR`` on a real terminal. What it does not
    survive is the absence of a terminal (redirection, pipe, CI) or ``TERM=dumb``, because
    then the carriage returns it relies on are just bytes in a file.
    """
    if os.environ.get("TERM", "").strip().lower() == _DUMB_TERM:
        return False
    target = sys.stderr if stream is None else stream
    return bool(target.isatty())


def _write_live(text: str) -> None:
    """Write an in-place update to stderr, ignoring a stream that closed underneath."""
    with contextlib.suppress(ValueError, OSError):
        sys.stderr.write(text)
        sys.stderr.flush()


def _animate(message: str, stop: threading.Event) -> None:
    """Redraw ``message`` with a rotating frame until ``stop`` is set, then clear the line."""
    if stop.wait(_SPINNER_GRACE_S):
        return
    for frame in itertools.cycle(_SPINNER_FRAMES):
        _write_live(f"\r{frame} {message}")
        if stop.wait(_SPINNER_INTERVAL_S):
            break
    # Erase with spaces rather than an ANSI clear-line: the indicator then needs no escape
    # sequence at all, only a carriage return, so nothing here depends on what the terminal
    # understands. The width covers the frame and the space that follow the carriage return.
    _write_live("\r" + " " * (len(message) + 2) + "\r")


@contextlib.contextmanager
def progress(message: str) -> Iterator[None]:
    """Show an indeterminate activity indicator on stderr while the block runs.

    Indeterminate on purpose. Netezza does not report how far a query has got, so the only
    honest thing a percentage could be built from does not exist: a bar that advances on
    its own is an animated lie, and the design rules it out everywhere except where a real
    denominator exists. This says "still working, on this step" and nothing more.

    The line is transient: it is erased when the block ends, so the caller's result line
    takes its place instead of piling up under it.

    Without a terminal — redirected to a file, piped into another process, running in CI,
    or ``TERM=dumb`` — **nothing at all is written**: no frames, no carriage returns, no
    escape sequences, no thread. What lands in the file is exactly what landed there before
    this indicator existed. That is checked, not assumed; see
    ``tests/unit/test_cli_progress.py``.

    Args:
        message: What is being waited on, already localized by the caller. Never a
            credential, and never anything that would be wrong to leave in a log.
    """
    if not animation_enabled():
        yield
        return
    stop = threading.Event()
    # Daemon: a hung write on the terminal must never keep the interpreter alive, and the
    # only state this thread owns is one line it is about to erase.
    worker = threading.Thread(target=_animate, args=(message, stop), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=_SPINNER_JOIN_S)


@contextlib.contextmanager
def stdout_reserved_for_protocol() -> Iterator[TextIO | None]:
    """Move the real stdout out of reach and yield it for the MCP transport.

    Three things happen, in this order:

    1. Descriptor 1 is duplicated. That private duplicate still points at the real
       standard output of the process — the pipe the MCP client reads.
    2. Descriptor 1 is overwritten with a duplicate of descriptor 2. Anything that
       writes to "stdout" the naive way, at any level of the stack, now writes to
       stderr: ``os.write(1, ...)``, ``print``, ``sys.stdout.write``, a C extension,
       a dependency this project never reviewed.
    3. The private duplicate is yielded as a text stream. The caller hands it to the
       transport explicitly, so the protocol is reachable *only* through that object.

    ``sys.stdout`` is deliberately **not** rebound to the protocol stream. Doing so
    would put the protocol back under a well-known name and a stray ``print`` — the
    single most likely mistake — would corrupt it again. Left alone, ``sys.stdout``
    keeps writing to descriptor 1, which is now stderr: harmless.

    It is a context manager, not a one-way switch, so a process that exercises
    ``serve`` — a test suite, a wrapper — gets its descriptors back afterwards.

    Yields:
        The protocol stream, or ``None`` when descriptor 1 cannot be duplicated (no
        usable stdout, as under ``pythonw``). ``None`` means "let the transport pick
        its own stream": there is nothing to protect in that case. The reservation
        flag is set either way, so :func:`emit` keeps refusing to write.
    """
    try:
        protocol_fd = os.dup(_STDOUT_FD)
    except OSError:
        _STATE["stdout_reserved"] = True
        try:
            yield None
        finally:
            _STATE["stdout_reserved"] = False
        return

    with contextlib.suppress(ValueError, OSError, AttributeError):
        sys.stdout.flush()
    os.dup2(_STDERR_FD, _STDOUT_FD)
    # ``closefd=False``: this wrapper never owns ``protocol_fd``; the finally block
    # below is the only place allowed to close it.
    protocol_stream = io.TextIOWrapper(
        os.fdopen(protocol_fd, "wb", closefd=False),
        encoding="utf-8",
        newline="\n",
        line_buffering=True,
    )
    _STATE["stdout_reserved"] = True
    try:
        yield protocol_stream
    finally:
        _STATE["stdout_reserved"] = False
        with contextlib.suppress(ValueError, OSError):
            protocol_stream.flush()
        os.dup2(protocol_fd, _STDOUT_FD)
        os.close(protocol_fd)


def stdout_is_reserved() -> bool:
    """Return whether stdout has been handed over to the MCP protocol."""
    return _STATE["stdout_reserved"]


def emit(message: str = "") -> None:
    """Write command payload to stdout, unstyled.

    Raises:
        RuntimeError: While stdout belongs to the MCP protocol. The descriptor
            swap in :func:`stdout_reserved_for_protocol` already makes such a
            write harmless, but harmless is not the same as intended: failing
            here names the line that should have used :func:`status`.
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
    "animation_enabled",
    "ask",
    "ask_int",
    "ask_secret",
    "color_enabled",
    "confirm",
    "emit",
    "fail",
    "heading",
    "note",
    "progress",
    "status",
    "stdout_is_reserved",
    "stdout_reserved_for_protocol",
    "success",
    "warn",
)
