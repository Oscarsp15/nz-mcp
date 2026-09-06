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

:func:`steps` is the determinate sibling of :func:`progress`, for the one wait in this CLI
with a real denominator. Same channel, same transience, same silence without a terminal.

:func:`table` is the layer's own vocabulary for "aligned columns", per condition 3 of
ADR 0027. It returns **text** rather than writing anywhere, so the caller decides the
channel: today the profile list emits it as payload on stdout. Its ``rich`` console is
built against an in-memory buffer and owns no file descriptor at all, which is the
second of the two shapes condition 1 admits (ADR 0027, addendum 1: *no console writes
to stdout*) — and the stricter one, since a buffer cannot reach stderr either.

What a table gives up when it does not fit
------------------------------------------
Written here because "it gets cut off somewhere" is not a design (issue #220). The order
is fixed and every step of it has a test:

1. **Nothing disappears.** No column is hidden and no row is dropped. A hidden column
   takes with it the fact that it existed, which is the one mistake a person cannot
   notice and cannot undo.
2. **A column never narrows below its own header.** Headers stay whole, so the table
   keeps being readable *as* a table however hard it is squeezed.
3. **The widest column pays first**, one cell at a time, until the row fits. It is the
   host today and the query id in the probe report; what it is never is ``Modo`` or
   ``Activo``, which are short because their values are short and should not be shaved so
   that a long hostname can stay whole.
4. **A cell that has to lose characters loses them from the middle.** ``10.51.10.242``
   and ``10.51.10.243`` differ at the end and ``nz-prod-01.corp`` and
   ``nz-prod-02.corp`` in the middle-front: cutting the tail off either turns the answer
   the table exists to give — *which one is this?* — into a guess. Head and tail are kept
   and ``...`` says what happened.
5. **When not even the headers fit, it stops being a table.** Each row comes out as a
   ``key: value`` block, which is the shape ``list-profiles`` already uses for a single
   profile. Below that width there is nothing to align and forcing columns would be
   choosing decoration over the data.

Without a terminal there is no window to measure, and none is guessed: the width is the
fixed :data:`_WIDTH_WITHOUT_TERMINAL`. Columns are still sized to their content, so a
redirect or a pipe gets exactly the same bytes it got before any of this existed — a file
is kept and read later, and truncating one to fit a window nobody is looking at would be
losing data to no one's benefit.

**As long as the content fits in that fixed width**, and the exact promise is worth
writing down rather than rounding up. A cell wider than 200 cells — a hostname near the
DNS limit is the realistic way to get one — did not survive before this either: ``rich``
cut it at the column and marked the cut with a real ellipsis character, so the **end of
the value was lost** and the marker itself renders as ``?`` on a Windows console with a
legacy code page. Now the same cell loses its middle instead, keeps both ends and says so
in ASCII. Neither version keeps it whole; they are not the same bytes; this one is the
better of the two and that is all it claims.

Colour and terminal detection
-----------------------------
:func:`color_enabled` is the only place that decides whether ANSI sequences may
be produced: a real terminal (``isatty``), no ``NO_COLOR``, no ``TERM=dumb``.
The result is passed explicitly to ``click``, which strips the sequences when
colour is off, so redirected or piped output stays plain text.

:func:`interactive_ui_blocker` is the same detection asked a harder question:
may a **full-screen** application start here? It is the gate of ADR 0028,
condition 1, and it lives in this module for the reason everything else about
terminals does - one place decides. It returns a value and builds nothing; it
does not import ``textual`` and never will. The wizard is the only caller.

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
import shutil
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Final, Literal, Protocol, TextIO

import typer
from rich import box
from rich.console import Console, detect_legacy_windows
from rich.table import Table

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

#: Width of the determinate progress bar, in characters. Short on purpose: it shares the line
#: with the counter and the name of the step in flight, and the name is the part that says
#: where a run got stuck.
_BAR_WIDTH: Final[int] = 20

#: Characters of that bar. ASCII, for the same reason as the spinner frames.
_BAR_DONE: Final[str] = "#"
_BAR_TODO: Final[str] = "-"

#: Line width used when the text is not going to a terminal at all: redirected, piped, in
#: CI, read by another process. Fixed on purpose - there is no window to measure and the
#: environment is not asked to invent one. Columns are still sized to their content, so
#: what lands in a file is exactly as wide as the data; this is a ceiling against a
#: pathological value, not a layout target.
_WIDTH_WITHOUT_TERMINAL: Final[int] = 200

#: What ``rich`` puts between two columns of an ASCII table: space, bar, space. Needed to
#: know, before rendering, how much width the separators are going to take.
_COLUMN_SEPARATOR_WIDTH: Final[int] = 3

#: Stands in for the characters a cell had to give up. ASCII, like every other marker this
#: layer draws: a Windows console on a legacy code page renders a real ellipsis as ``?``.
_ELLIPSIS: Final[str] = "..."

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


#: Escape hatch of ADR 0028, condition 1. Anyone whose terminal, multiplexer or remote
#: session makes the full-screen wizard a bad deal sets this once in their shell profile
#: and never thinks about it again.
NO_TUI_ENV: Final[str] = "NZ_MCP_NO_TUI"

#: Why the full-screen wizard did not start, when it did not. Names, not sentences: the
#: caller decides whether any of this is worth showing, and tests assert on them.
InteractiveBlocker = Literal[
    "opted_out",
    "term_dumb",
    "no_terminal",
    "terminal_without_capabilities",
    "console_without_vt",
    "window_too_small",
]

#: The terminfo capability a full-screen application cannot do without: absolute cursor
#: addressing. A terminal type that does not declare it cannot be painted on, whatever
#: else it can do.
_CURSOR_ADDRESSING: Final[str] = "cup"


def _terminfo_declares_full_screen(term: str) -> bool:
    """Whether the terminfo database describes ``term`` as paintable.

    POSIX only; on Windows there is no terminfo and the question is answered by
    :func:`rich.console.detect_legacy_windows` instead.

    ``curses.setupterm`` is the same lookup every curses program does, and the entry it
    finds has to declare absolute cursor addressing - the one capability a full-screen
    wizard cannot work around. Anything that goes wrong - no terminfo database at all, a
    broken entry, a build of Python without ``curses`` - counts as "no guarantees",
    because that is what it is.

    One thing this deliberately does **not** promise: that an unknown terminal type is
    rejected. Measured on the CI runners, ncurses answers a name it has never seen with a
    usable fallback entry rather than an error, and that behaviour differs between builds.
    So the portable part of the trigger is the one the caller applies - ``TERM`` has to be
    set at all - and this lookup is what catches the systems where the database really is
    missing or useless.
    """
    try:
        import curses  # noqa: PLC0415 - POSIX only, and only on this path
    except ImportError:  # pragma: no cover - CPython ships curses on POSIX
        return False
    try:
        # The descriptor is passed explicitly. Left to itself ``setupterm`` calls
        # ``sys.stdout.fileno()``, and under a test runner - or anywhere else that
        # replaced the stream - that raises and the lookup would report "unknown" for a
        # terminal that is perfectly well known.
        curses.setupterm(term, _STDERR_FD)
    except (curses.error, OSError, TypeError, ValueError):
        return False
    return curses.tigetstr(_CURSOR_ADDRESSING) is not None


def _terminal_type_is_capable() -> bool:
    """Whether ``TERM`` describes something a full-screen application can be drawn on.

    The seventh trigger, and the one that was missing: ``TERM=dumb`` is not the only way
    to end up without guarantees. An **empty or unset** ``TERM`` is routine inside
    containers and in some multiplexed SSH sessions, and an unknown value is routine on a
    host whose terminfo database does not carry the client's terminal type. In both cases
    there is a real terminal on all three streams and a perfectly valid window size, so
    none of the other six triggers fires - and the wizard would start with no guarantee
    that a single escape sequence or key it sends means anything.

    Only asked on POSIX. On Windows ``TERM`` is normally unset and says nothing; there the
    equivalent question is whether the console speaks VT, which is the trigger after this
    one.
    """
    if os.name != "posix":
        return True
    term = os.environ.get("TERM", "").strip()
    return bool(term) and _terminfo_declares_full_screen(term)


def _opted_out_of_the_tui() -> bool:
    """Whether ``NZ_MCP_NO_TUI`` asks for the chained questions.

    Any value counts except the two that conventionally mean "no", so that
    ``NZ_MCP_NO_TUI=1`` and ``NZ_MCP_NO_TUI=true`` do the same obvious thing and
    ``NZ_MCP_NO_TUI=0`` does not silently disable a wizard someone wanted.
    """
    value = os.environ.get(NO_TUI_ENV, "").strip().lower()
    return bool(value) and value not in ("0", "false")


def interactive_ui_blocker(*, min_width: int, min_height: int) -> InteractiveBlocker | None:
    """Report why a full-screen application must not start here, or ``None`` if it may.

    This is the gate of ADR 0028, condition 1, and it lives here because every piece of
    terminal detection this project owns lives here. It decides a value; it builds
    nothing, imports no TUI library and has no opinion about what the caller does next.

    The gate has to be ours. Measured on ``textual`` 8.2.8: the word ``dumb`` does not
    appear anywhere in the package, and the single ``isatty`` in its drivers decides *how*
    to read input rather than *whether* to start. A TUI library will try to paint wherever
    it is allowed to; declining is this project's job.

    The six start-up triggers, in the order that costs least to check:

    1. ``NZ_MCP_NO_TUI`` - an explicit request, honoured without argument.
    2. ``TERM=dumb`` - a terminal that has told us it understands nothing.
    3. No terminal at all on input, payload or status: redirected, piped, in CI, or
       driven by another process. Note that ``nz-mcp init > block.json``, which the
       install guide suggests, lands here on purpose.
    4. On POSIX, a ``TERM`` that is empty, unset or unknown to terminfo, or that does not
       declare cursor addressing. Common inside containers and in some multiplexed SSH
       sessions, and invisible to every other trigger: the streams are terminals and the
       window is a good size.
    5. A Windows console that does not speak VT sequences. Legacy code pages turn box
       drawing into ``?``; the wizard is ASCII, but a console without VT cannot position
       a cursor either. Triggers 4 and 5 are the same question asked per platform.
    6. A window below the declared minimum. The seventh trigger - shrinking below it
       *during* the session - cannot be seen from here and belongs to the application.

    Args:
        min_width: Narrowest window the caller can draw itself in, in cells.
        min_height: Shortest window the caller can draw itself in, in cells.

    Returns:
        The name of the first trigger that fired, or ``None`` when none did.
    """
    # The triggers as data rather than as a chain of returns: the list of reasons a wizard
    # may not start is the interesting part of this function, and a test can walk it.
    triggers: tuple[tuple[InteractiveBlocker, Callable[[], bool]], ...] = (
        ("opted_out", _opted_out_of_the_tui),
        ("term_dumb", _term_is_dumb),
        ("no_terminal", lambda: not _standard_streams_are_terminals()),
        ("terminal_without_capabilities", lambda: not _terminal_type_is_capable()),
        ("console_without_vt", detect_legacy_windows),
        ("window_too_small", lambda: _window_is_smaller_than(min_width, min_height)),
    )
    return next((name for name, fired in triggers if fired()), None)


def _term_is_dumb() -> bool:
    return os.environ.get("TERM", "").strip().lower() == _DUMB_TERM


def _standard_streams_are_terminals() -> bool:
    return all(_is_a_terminal(stream) for stream in (sys.stdin, sys.stdout, sys.stderr))


def _window_is_smaller_than(min_width: int, min_height: int) -> bool:
    size = shutil.get_terminal_size()
    return size.columns < min_width or size.lines < min_height


def interactive_ui_enabled(*, min_width: int, min_height: int) -> bool:
    """Whether a full-screen application may start. See :func:`interactive_ui_blocker`."""
    return interactive_ui_blocker(min_width=min_width, min_height=min_height) is None


def _is_a_terminal(stream: object) -> bool:
    """Whether ``stream`` is a real terminal, tolerating a stream that has been replaced.

    Test runners and wrappers swap the standard streams for objects that do not implement
    the whole protocol; anything that cannot answer the question is treated as not a
    terminal, which degrades rather than crashes.
    """
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):  # pragma: no cover - stream closed underneath us
        return False


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


def _render_step(done: int, total: int, label: str) -> str:
    """One frame of the determinate indicator: bar, counter and what is running now."""
    filled = round(_BAR_WIDTH * done / total) if total else _BAR_WIDTH
    bar = _BAR_DONE * filled + _BAR_TODO * (_BAR_WIDTH - filled)
    return f"[{bar}] {done}/{total} {label}"


@contextlib.contextmanager
def steps(total: int) -> Iterator[Callable[[int, str], None]]:
    """Show a determinate progress indicator on stderr while the block runs.

    The counterpart to :func:`progress`, and the exception that proves its rule. A percentage
    is only honest where the denominator is real, which in this CLI happens exactly once: the
    catalog probe runs a **known** list of queries, so ``7/14`` is counted, not invented.
    Everywhere else Netezza does not report how far a query has got and the indicator stays
    indeterminate.

    The line is transient and rewritten in place: it names the step currently running, which
    is what tells you where a run got stuck, and it is erased when the block ends so the
    report that follows is not printed under a trail of dead progress lines.

    Without a terminal — redirected, piped, in CI, or ``TERM=dumb`` — **nothing at all is
    written**: no frames, no carriage returns, no escape sequences. Redirecting the report to
    a file therefore yields the report and nothing else.

    Args:
        total: How many steps there are. Known in advance; that is the whole point.

    Yields:
        A callable ``(done, label)`` the caller invokes once per step, where ``label`` names
        the step and is already localized. Never a credential.
    """
    if not animation_enabled():
        yield lambda _done, _label: None
        return
    widest = 0

    def update(done: int, label: str) -> None:
        nonlocal widest
        frame = _render_step(done, total, label)
        widest = max(widest, len(frame))
        _write_live("\r" + frame.ljust(widest))

    try:
        yield update
    finally:
        # Erase with spaces and a carriage return only: no escape sequence, so nothing here
        # depends on what the terminal understands.
        _write_live("\r" + " " * widest + "\r")


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


def display_width(stream: SupportsIsatty | None = None) -> int:
    """Columns available for aligned output on ``stream`` (default: stdout).

    Defaults to stdout because that is the channel the only payload table travels on; the
    probe report, which a person reads on stderr, passes that stream explicitly. Asking
    per stream rather than once for the process is the difference between shrinking a
    table to the window someone is looking at and shrinking a redirected file to a window
    that has nothing to do with it.

    ``shutil.get_terminal_size`` reads ``COLUMNS`` before asking the operating system, so
    the documented way to override a terminal's width also overrides this - which is what
    the report of issue #220 used, and what makes the behaviour reproducible by hand.
    """
    target = sys.stdout if stream is None else stream
    if not _is_a_terminal(target):
        return _WIDTH_WITHOUT_TERMINAL
    return shutil.get_terminal_size().columns


def _natural_widths(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[int]:
    """Width each column would take if nothing were squeezed: its widest cell, header included."""
    return [
        max(len(header), *(len(row[index]) for row in rows)) if rows else len(header)
        for index, header in enumerate(headers)
    ]


def _fitted_widths(
    natural: Sequence[int], floors: Sequence[int], available: int
) -> list[int] | None:
    """Widths that fit in ``available``, or ``None`` when not even the floors do.

    Steps 2 and 3 of the sacrifice order in the module docstring: the widest column gives
    up one cell at a time until the row fits, and no column ever goes below its floor. One
    cell at a time rather than a proportional formula because it is the same thing for
    tables this size and it is obviously right at a glance, which a ratio is not.
    """
    separators = _COLUMN_SEPARATOR_WIDTH * (len(natural) - 1)
    if sum(floors) + separators > available:
        return None
    widths = list(natural)
    excess = sum(widths) + separators - available
    while excess > 0:
        # Ties go to the leftmost column, which only matters for determinism: two columns
        # of the same width are equally good candidates and a test needs one answer.
        widest = max(
            (index for index, width in enumerate(widths) if width > floors[index]),
            key=lambda index: (widths[index], -index),
        )
        widths[widest] -= 1
        excess -= 1
    return widths


def _truncate_middle(value: str, width: int) -> str:
    """Fit ``value`` in ``width`` cells by dropping characters from the **middle**.

    Head and tail are what tell two hosts, two databases or two query ids apart; a tail cut
    turns ``nz-prod-01.corp.example.com`` and ``nz-prod-02.corp.example.com`` into the same
    string. When the column is narrower than the marker itself there is nothing left to
    preserve and the value is simply cut - a degenerate case that needs the whole table to
    be at its floors to happen at all.
    """
    if len(value) <= width:
        return value
    if width <= len(_ELLIPSIS):
        return value[:width]
    kept = width - len(_ELLIPSIS)
    head = kept - kept // 2
    tail = kept // 2
    return value[:head] + _ELLIPSIS + (value[len(value) - tail :] if tail else "")


def _as_records(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render each row as a ``key: value`` block, for a window too narrow to hold columns.

    Nothing is truncated here: there is no alignment left to protect, so a long value wraps
    the way any other line of prose does and the data survives whole. Empty cells are left
    out - without a column above it, a label with nothing after it reads as missing data
    rather than as the blank it is.
    """
    blocks = [
        "\n".join(
            f"{header}: {cell}" for header, cell in zip(headers, row, strict=True) if cell.strip()
        )
        for row in rows
    ]
    return "\n\n".join(block for block in blocks if block)


def table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], *, width: int | None = None
) -> str:
    """Render ``rows`` as aligned columns and return the text, without writing it anywhere.

    A table earns its place when there are two or more comparable rows and someone has to
    pick one, or spot the odd one out column by column. With a single row there is nothing
    to compare and a caller should print ``key: value`` instead; this function does not
    second-guess that decision, it just aligns what it is given.

    It does decide **how to give up width**, and what it gives up first is written in the
    module docstring: nothing is hidden, headers stay whole, the widest column pays, cells
    lose their middle, and below the width of the headers themselves the rows come out as
    ``key: value`` blocks instead of as columns.

    Three deliberate choices:

    - **It returns text.** The caller owns the channel, so the same renderer serves payload
      on stdout and a human report on stderr. It also means the one ``rich`` console this
      project builds writes to a memory buffer and holds no file descriptor, which satisfies
      condition 1 of ADR 0027 (addendum 1: *no console writes to stdout*) more strictly than
      ``Console(stderr=True)`` does: this one cannot reach stderr either.
    - **ASCII frame, no colour.** ``box.ASCII`` and ``no_color`` are not a fallback for
      hostile terminals, they are the output: a Windows console on a legacy code page turns
      the Unicode box characters ``rich`` would otherwise pick into ``?``, and colour that
      carries meaning is unreadable for whoever does not see it or redirects it to a file.
      What is left is a header rule and column separators, which is all a table needs.
    - **No outer frame and no trailing blanks.** Padding a row out to the frame puts
      invisible characters in a redirected file for no gain.

    Args:
        headers: Column titles, already localized.
        rows: One sequence of already formatted cells per row, same length as ``headers``.
        width: Cells to fit into. Defaults to :func:`display_width` of stdout; passed
            explicitly by the callers that write elsewhere, and by tests, which is how the
            behaviour at every width is pinned without opening a terminal.

    Returns:
        The rendered table, newline separated and without a trailing newline. Or, when the
        window cannot hold even the headers, the same data as ``key: value`` blocks.
    """
    available = display_width() if width is None else width
    natural = _natural_widths(headers, rows)
    fitted = _fitted_widths(natural, [len(header) for header in headers], available)
    if fitted is None:
        return _as_records(headers, rows)
    grid = Table(box=box.ASCII, show_edge=False, pad_edge=False)
    for header in headers:
        grid.add_column(header)
    for row in rows:
        grid.add_row(
            *(_truncate_middle(cell, cells) for cell, cells in zip(row, fitted, strict=True))
        )
    buffer = io.StringIO()
    Console(
        # Every cell already fits its column, so this width only has to be big enough not
        # to wrap what was measured: ``rich`` is left with the alignment and the frame, and
        # none of the decisions above are taken twice, differently.
        file=buffer,
        width=max(available, 1),
        no_color=True,
        emoji=False,
        highlight=False,
        markup=False,
        legacy_windows=False,
    ).print(grid)
    return "\n".join(line.rstrip() for line in buffer.getvalue().splitlines())


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
    "NO_TUI_ENV",
    "InteractiveBlocker",
    "Style",
    "SupportsIsatty",
    "animation_enabled",
    "ask",
    "ask_int",
    "ask_secret",
    "color_enabled",
    "confirm",
    "display_width",
    "emit",
    "fail",
    "heading",
    "interactive_ui_blocker",
    "interactive_ui_enabled",
    "note",
    "progress",
    "status",
    "stdout_is_reserved",
    "stdout_reserved_for_protocol",
    "steps",
    "success",
    "table",
    "warn",
)
