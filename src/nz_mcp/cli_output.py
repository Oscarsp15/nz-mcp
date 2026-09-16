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

:func:`terminal_level` is the question ADR 0031 asks on top of those two: *how much of
what we draw arrives whole?* It answers 0 (ASCII, no escape sequence: the floor the
whole CLI is measured against) or 1 (a modern terminal), from the environment and
``isatty`` alone, and ``NZ_MCP_UI_LEVEL`` forces it either way. It decides nothing
about what is drawn yet — the level-0 output is pinned character by character in
``tests/unit/test_cli_output.py``, and that pin is the contract every later level
has to keep.

:func:`prepare_windows_console` is ADR 0033's answer to a measurement ADR 0031 made
correctly and still left a real user unable to see the redesign: a Windows console on a
legacy code page is not a fact to accept, it is a fact to try to change first. On Windows,
and only when a real console is attached, it turns on ``ENABLE_VIRTUAL_TERMINAL_PROCESSING``
for both standard output handles and switches the console to code page 65001 - the same
constant :func:`_windows_console_renders_unicode` already compared against - before
reconfiguring ``sys.stdout`` and ``sys.stderr`` to UTF-8, because Python opened both against
the *old* code page and a console change alone would not reach them. Every failure of the
console API is swallowed: preparing the console is an improvement, never a requirement, and
``NZ_MCP_NO_CONSOLE_PREP`` opts out of the attempt entirely. What it changes is undone with
``atexit`` when the process exits, whatever the reason. It is called exactly once, from
``cli.entry_point``, for every command except ``serve`` - see the module docstring's
"Protocol reservation" section below for why that exclusion cannot be an afterthought.

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

import atexit
import contextlib
import io
import itertools
import os
import re
import shutil
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Final, Literal, Protocol, TextIO

import typer
from rich import box
from rich.console import Console
from rich.table import Table

Style = Literal["plain", "heading", "success", "warning", "error"]

#: The basic 8-colour palette level 0 has always used. Kept as-is: level 0 is a contract
#: (ADR 0031, point 4) and this dict is what it has always drawn from - a plain name, no
#: escape sequence unless ``color_enabled`` and (now) :func:`terminal_level` both allow one.
_STYLE_COLORS: Final[dict[Style, str | None]] = {
    "plain": None,
    "heading": None,
    "success": typer.colors.GREEN,
    "warning": typer.colors.YELLOW,
    "error": typer.colors.RED,
}

#: ADR 0031, point 7: the level-1 palette, measured at >= 3:1 on both a white and a black
#: background - the only thing a fixed byte can guarantee without knowing the terminal's own
#: colour. Five hexes, each with one job; nothing here is a level-2 colour, which is ADR 0032's
#: and answers a different question (its own fixed background, so its own 4.5:1 listón).
_ACCENT_HEX: Final[str] = "#00A3A3"
_OK_HEX: Final[str] = "#1F9D55"
_WARNING_HEX: Final[str] = "#B26B00"
_ERROR_HEX: Final[str] = "#C62828"

#: What :func:`table` colours identifiers is *nothing* (ADR 0031, point 7, rule 2): headers and
#: borders get the accent, cell content keeps the terminal's own foreground. There is no
#: "muted" constant here because nothing in this module paints with it yet.


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """Split ``#rrggbb`` into the three ints ``click``'s truecolour ``fg`` wants."""
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


#: Level-1 replacement for :data:`_STYLE_COLORS`: the same five keys, the ADR 0031 palette
#: instead of the basic eight. Selected only once :func:`terminal_level` has said 1, never a
#: fallback for a terminal that cannot show truecolour - that terminal is level 0 already
#: (ADR 0031, point 2, signal 7 on Windows; a POSIX terminal too old for ``cup`` fails signal 6
#: first).
_LEVEL_1_STYLE_COLORS: Final[dict[Style, tuple[int, int, int] | None]] = {
    "plain": None,
    "heading": _rgb(_ACCENT_HEX),
    "success": _rgb(_OK_HEX),
    "warning": _rgb(_WARNING_HEX),
    "error": _rgb(_ERROR_HEX),
}

#: ADR 0031, point 7: a state is shape *and* word *and* colour, never colour alone. Only the
#: three states that :func:`status` actually carries get a glyph; ``plain`` and ``heading`` are
#: not states.
_STATE_GLYPHS: Final[dict[Style, str]] = {
    "success": "\N{BLACK CIRCLE}",  # "●"
    "warning": "\N{BLACK UP-POINTING TRIANGLE}",  # "▲"
    "error": "\N{MULTIPLICATION X}",  # "✕"
}

_ANSI_RESET: Final[str] = "\x1b[0m"

#: Matches a whole SGR sequence, for the padding math in :func:`steps`: a coloured level-1
#: frame is wider in bytes than it is on screen, and the erase line has to blank what is on
#: screen, not what is in the string.
_ANSI_SGR_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")


def _ansi_fg(hex_color: str) -> str:
    """The raw truecolour escape for ``hex_color``, for the one surface that cannot ask ``click``
    to build it: the live-redrawn frames of :func:`progress` and :func:`steps`, which write
    straight to the stream themselves and never go through ``typer.secho``.
    """
    red, green, blue = _rgb(hex_color)
    return f"\x1b[38;2;{red};{green};{blue}m"


def _visible_length(text: str) -> int:
    """``len(text)`` with any SGR sequence removed - what actually occupies a cell on screen."""
    return len(_ANSI_SGR_RE.sub("", text))


_DUMB_TERM: Final[str] = "dumb"

#: Frames of the activity indicator, in ASCII on purpose. A Windows console running a
#: legacy code page renders anything outside ASCII as ``?``, which is what the CLI design
#: found while walking the install path, so braille dots and block characters are out.
_SPINNER_FRAMES: Final[tuple[str, ...]] = ("-", "\\", "|", "/")

#: Level-1 spinner: ``rich``'s own "dots" set (ten Braille frames), rendered in the accent
#: colour. Level 0 never sees these - a legacy code page draws a Braille dot as ``?``, which is
#: the finding behind ADR 0027 and the reason these stay behind :func:`terminal_level`.
_SPINNER_FRAMES_LEVEL_1: Final[tuple[str, ...]] = (
    "\N{BRAILLE PATTERN DOTS-124}",
    "\N{BRAILLE PATTERN DOTS-145}",
    "\N{BRAILLE PATTERN DOTS-1456}",
    "\N{BRAILLE PATTERN DOTS-456}",
    "\N{BRAILLE PATTERN DOTS-3456}",
    "\N{BRAILLE PATTERN DOTS-356}",
    "\N{BRAILLE PATTERN DOTS-236}",
    "\N{BRAILLE PATTERN DOTS-1236}",
    "\N{BRAILLE PATTERN DOTS-123}",
    "\N{BRAILLE PATTERN DOTS-1234}",
)

#: Seconds between frames. Fast enough to read as motion, slow enough not to flood a
#: slow terminal or a serial console.
_SPINNER_INTERVAL_S: Final[float] = 0.12

#: Ten frames read as smoother motion than the four ASCII ones at the same wall-clock speed
#: would, so the interval can drop a little without the eye reading it as flicker.
_SPINNER_INTERVAL_LEVEL_1_S: Final[float] = 0.08

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

#: Level-1 bar: solid and light Unicode blocks, the filled part in the accent colour
#: (ADR 0031, point 5: "glifo, color semántico y barra de progreso"). Same width as level 0,
#: only the material changes.
_BAR_DONE_LEVEL_1: Final[str] = "\N{FULL BLOCK}"
_BAR_TODO_LEVEL_1: Final[str] = "\N{LIGHT SHADE}"

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


#: Escape hatch of ADR 0031, point 3. Forces the level in both directions: ``1`` where the
#: detection would have said 0 — a terminal the heuristics do not know but its owner does —
#: and ``0`` where it would have said 1, for whoever wants yesterday's bytes, byte for byte.
#: It names this program, so it wins over ``NO_COLOR``, which is a global convention.
UI_LEVEL_ENV: Final[str] = "NZ_MCP_UI_LEVEL"

#: What :func:`terminal_level` can answer: Nivel B (0) or Nivel A (1) — ADR 0035 removed
#: the third, full-screen level this used to leave room for.
TerminalLevel = Literal[0, 1]

#: The only spellings the escape hatch accepts, after stripping. Anything else — ``2``
#: included, on purpose — is treated as absent and the detection runs (ADR 0031, point 3).
_LEVEL_SPELLINGS: Final[dict[str, TerminalLevel]] = {"0": 0, "1": 1}

#: The code page in which a Windows console renders every character we draw. Any other —
#: 850 measured in Git Bash on Windows 11, 437 on a fresh console — turns a glyph outside
#: ASCII into ``?``, which is the finding behind ADR 0027.
_UTF8_CODE_PAGE: Final[int] = 65001


def _forced_level() -> TerminalLevel | None:
    return _LEVEL_SPELLINGS.get(os.environ.get(UI_LEVEL_ENV, "").strip())


def _console_output_code_page() -> int | None:
    """The code page of the Windows console, or ``None`` where there is no console API.

    The API is looked up rather than imported: ``ctypes.windll`` does not exist on POSIX,
    and a module that touched it on import — or on the common path — would not load there.
    Only asked once the caller has established the platform is Windows; the lookup is what
    keeps the function itself runnable, and testable, on every platform.
    """
    import ctypes  # noqa: PLC0415 - only on the Windows path

    console_api: Callable[[], int] | None = getattr(
        getattr(getattr(ctypes, "windll", None), "kernel32", None), "GetConsoleOutputCP", None
    )
    if console_api is None:
        return None
    try:
        return int(console_api())
    except (OSError, ValueError, TypeError):
        return None


def _windows_console_renders_unicode() -> bool:
    """Whether a Windows console will draw a character outside ASCII as itself, not as ``?``.

    Signal 7 of ADR 0031, and the case that cannot be reduced to "is it Windows". Measured
    on the owner's machine: Git Bash on Windows 11 reports ``TERM=xterm-256color`` and a
    console code page of **850**, so a detector that trusted ``TERM`` would draw ``●`` into
    a console that prints ``?``. Either of two facts is enough to know Unicode arrives whole:
    Windows Terminal is hosting us (``WT_SESSION``), or the console is already on UTF-8.

    Not asked on POSIX, where there is no console code page and the equivalent question is
    terminfo's, one signal earlier.
    """
    if os.name != "nt":
        return True
    if os.environ.get("WT_SESSION") is not None:
        return True
    return _console_output_code_page() == _UTF8_CODE_PAGE


#: Escape hatch of ADR 0033. Any value counts as *yes* except the two that conventionally
#: mean "no", so that whoever sets it does not have their console touched at all - no code
#: page, no console mode, no stream reconfiguration.
NO_CONSOLE_PREP_ENV: Final[str] = "NZ_MCP_NO_CONSOLE_PREP"

#: ``nStdHandle`` values ``GetStdHandle`` accepts for the two streams this layer draws on -
#: the menu on stdout, ``status()`` and its shorthands on stderr (ADR 0033, point 2).
_STD_OUTPUT_HANDLE: Final[int] = -11
_STD_ERROR_HANDLE: Final[int] = -12

#: Console mode bit that turns on interpretation of ANSI/VT escape sequences (Windows 10,
#: version 1511, and later). Without it a legacy console prints ``\x1b[...`` literally
#: instead of colouring anything, which is worse than not trying.
_ENABLE_VIRTUAL_TERMINAL_PROCESSING: Final[int] = 0x0004


def _opted_out_of_console_prep() -> bool:
    """Whether ``NZ_MCP_NO_CONSOLE_PREP`` asks to leave the console exactly as found."""
    value = os.environ.get(NO_CONSOLE_PREP_ENV, "").strip().lower()
    return bool(value) and value not in ("0", "false")


#: Names of the five ``kernel32`` calls :func:`_prepare_windows_console` needs, in the order
#: it uses them. A tuple rather than five separate lookups so a missing one is a single
#: ``None`` check instead of five, which is also what keeps the caller's branch count sane.
_CONSOLE_API_NAMES: Final[tuple[str, ...]] = (
    "GetConsoleOutputCP",
    "SetConsoleOutputCP",
    "GetStdHandle",
    "GetConsoleMode",
    "SetConsoleMode",
)


def _console_functions(kernel32: object) -> tuple[Any, ...] | None:
    """The five ``kernel32`` calls, looked up together, or ``None`` if any is missing.

    Grouping the lookup here - instead of five ``if x is None: return None`` guards inline -
    is what lets the caller narrow all five with a single check: unpacking a tuple mypy
    knows is not ``None`` yields five ``Any`` values, none of them ``Any | None``.
    """
    functions = tuple(getattr(kernel32, name, None) for name in _CONSOLE_API_NAMES)
    return None if None in functions else functions


def _prepare_windows_console() -> Callable[[], None] | None:
    """Try to switch the real Windows console to UTF-8 and turn on VT processing.

    Returns a callable that restores the code page and the two console modes this touched,
    or ``None`` when nothing changed - either there was nothing to change or the console API
    refused somewhere along the way. Every failure it can raise is caught here: preparing
    the console is an improvement (ADR 0033), never a requirement, and the caller falls back
    to measuring whatever it finds, exactly as it did before this function existed.

    The API is looked up rather than imported at module level, for the same reason
    :func:`_console_output_code_page` looks it up: ``ctypes.windll`` does not exist on
    POSIX, and this keeps the module importable there without ever touching it.
    """
    import ctypes  # noqa: PLC0415 - Windows-only path

    console_api_errors: tuple[type[BaseException], ...] = (
        ctypes.ArgumentError,
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    )

    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    if kernel32 is None:
        return None
    functions = _console_functions(kernel32)
    if functions is None:
        return None
    get_output_cp, set_output_cp, get_std_handle, get_mode, set_mode = functions

    try:
        # ``GetStdHandle`` returns a pointer-sized HANDLE. The default ``restype`` (``c_int``)
        # would truncate it on 64-bit Windows; forcing ``c_void_p`` keeps it whole. The two
        # mode functions get the matching ``argtypes`` for the same reason, on the handle
        # they are given back.
        get_std_handle.restype = ctypes.c_void_p
        get_mode.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        set_mode.argtypes = (ctypes.c_void_p, ctypes.c_uint32)

        original_code_page = int(get_output_cp())
        if not set_output_cp(_UTF8_CODE_PAGE):
            return None

        original_modes: list[tuple[object, int]] = []
        for std_handle in (_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE):
            handle = get_std_handle(std_handle)
            mode = ctypes.c_uint32()
            if not get_mode(handle, ctypes.pointer(mode)):
                continue
            if set_mode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                original_modes.append((handle, mode.value))
    except console_api_errors:
        return None

    def restore() -> None:
        with contextlib.suppress(*console_api_errors):
            for handle, mode in original_modes:
                set_mode(handle, mode)
            set_output_cp(original_code_page)

    return restore


def prepare_windows_console() -> None:
    """Improve the real Windows console before anything asks it what it can draw (ADR 0033).

    Four gates, each enough on its own to do nothing:

    1. Not Windows — nothing to prepare, and no ``ctypes`` import happens on this path.
    2. :data:`NO_CONSOLE_PREP_ENV` opted out.
    3. Neither stdout nor stderr is attached to a real console — nothing a person would see
       the improvement on, and nothing this function may safely touch. Deliberately an
       ``or``, not an ``and``: the code page and the VT mode are properties of the console
       itself, not of one descriptor, so either stream being a real console is reason enough
       to *attempt* the console-wide part of this. What is **not** decided by this ``or`` is
       which Python stream gets reconfigured - that is answered per stream below, precisely
       because this gate cannot tell ``nz-mcp list-profiles > out.txt`` (stdout redirected,
       stderr the console) from the fully-interactive case, and must not treat them the same.
    4. The console API itself refused, in whatever way — see :func:`_prepare_windows_console`.

    When it succeeds: the console output code page becomes UTF-8 (65001) and the two standard
    output handles gain ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` - both console-wide, so both
    happen whenever gate 3 opens. ``sys.stdout`` and ``sys.stderr`` are reconfigured to the
    same encoding **only the ones that are themselves a real console** - checked again here,
    per stream, not inherited from gate 3. A console change alone does not reach the streams
    Python already opened against the old code page, and reconfiguring a stream that is *not*
    the console - a redirected ``stdout`` while ``stderr`` is a terminal - would silently
    change the bytes of a file ADR 0031 promises are level 0's, byte for byte, whether or not
    anything about the console changed. Skipping the reconfiguration of the stream that *is*
    the console would leave exactly the mojibake this function exists to prevent.

    Everything it changed is restored by an :func:`atexit` callback, not by a ``finally``
    around the caller: the entry-point callback and the command body are two separate steps
    of ``click``'s own dispatch, not one nested inside the other, so a ``finally`` written in
    the callback would never see a command's exception. ``atexit`` runs regardless — on a
    clean return, on an uncaught exception, on an unhandled ``Ctrl+C`` — because all three are
    ordinary interpreter shutdown from its point of view.

    The one caller is ``cli.entry_point``, once per process, for every command except
    ``serve``, which is excluded there by command name before this function is ever reached
    (ADR 0033, point 5). That name check is a belt, not the suspenders: the structural
    guarantee is the per-stream check above, which means a stray future caller that forgot
    the name comparison still cannot touch a redirected ``stdout`` - the one ``serve`` needs
    left alone - because a piped descriptor never passes :func:`_is_a_terminal`.
    """
    if os.name != "nt":
        return
    if _opted_out_of_console_prep():
        return
    if not (_is_a_terminal(sys.stdout) or _is_a_terminal(sys.stderr)):
        return
    restore = _prepare_windows_console()
    if restore is None:
        return
    atexit.register(restore)
    # Each stream is reconfigured only if *that* stream is the console: ``list-profiles >
    # out.txt`` run from a real console has an ``stdout`` that is a file and an ``stderr``
    # that is the console the ``or`` above found. Reconfiguring both because *one* of them
    # is a console would change the bytes of a redirected level-0 payload - the exact thing
    # ADR 0031 pins byte for byte - and it is this per-stream check, not the ``serve`` name
    # comparison below, that keeps that promise structurally.
    for stream in (sys.stdout, sys.stderr):
        if not _is_a_terminal(stream):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(AttributeError, OSError, ValueError):
                reconfigure(encoding="utf-8")


def terminal_level(stream: SupportsIsatty | None = None) -> TerminalLevel:
    """How much of what this CLI draws arrives whole on ``stream`` (default: stderr).

    The single capability question of ADR 0031. Level **0** is ASCII without a single
    escape sequence — the floor, and the output that is pinned character by character in
    the tests; level **1** is a modern terminal that keeps colour and Unicode intact. Pure:
    it reads the environment and asks ``isatty()``; it opens nothing, writes nothing and
    keeps no state, so the whole matrix of environments is testable with ``monkeypatch``.

    Signals, in order; the first that answers wins, and every doubt falls to 0:

    1. ``NZ_MCP_UI_LEVEL`` set to ``0`` or ``1`` — the only explicit signal and the only one
       that can raise the level. It wins over ``NO_COLOR`` because it names this program.
       Any other value counts as absent, without a warning: this is read on every command.
    2. ``NO_COLOR`` present, with any value including empty.
    3. ``TERM=dumb``.
    4. ``CI`` present. A build log is a file someone reads a month later, and some runners
       attach a pseudo-terminal, where ``isatty`` says yes and is wrong.
    5. ``stream`` is not a terminal: redirected, piped, replaced by a wrapper.
    6. On POSIX, a ``TERM`` that is empty, unset or unusable to terminfo.
    7. On Windows, a console outside Windows Terminal that is not on code page 65001.
    """
    forced = _forced_level()
    if forced is not None:
        return forced
    target = sys.stderr if stream is None else stream
    # Same shape as the gate below: the list of reasons to stay on the floor is the
    # interesting part, and ``any`` stops at the first one, in this order.
    floor_signals: tuple[Callable[[], bool], ...] = (
        lambda: os.environ.get("NO_COLOR") is not None,
        _term_is_dumb,
        lambda: os.environ.get("CI") is not None,
        lambda: not _is_a_terminal(target),
        lambda: not _terminal_type_is_capable(),
        lambda: not _windows_console_renders_unicode(),
    )
    return 0 if any(fired() for fired in floor_signals) else 1


def stdout_terminal_level() -> TerminalLevel:
    """:func:`terminal_level` of stdout, for the caller that draws for the payload channel.

    Exists so that no other module ever has to spell ``sys.stdout``: the reservation contract
    (ADR 0027, addendum 1; ``tests/contract/test_serve_stdout_protocol_only.py``) forbids naming
    that descriptor anywhere outside this module, reading included, because a name-based check
    can only ever be a blacklist and the file descriptor swap of
    :func:`stdout_reserved_for_protocol` is what actually holds. ``list-profiles`` is the one
    caller (ADR 0031, point 1: a caller asks about its own channel; the profile table travels
    on stdout, the same way :func:`display_width`'s own default already does).
    """
    return terminal_level(sys.stdout)


#: The terminfo capability a terminal cannot be drawn on without: absolute cursor
#: addressing. A terminal type that does not declare it cannot be positioned on, whatever
#: else it can do.
_CURSOR_ADDRESSING: Final[str] = "cup"


def _terminfo_declares_full_screen(term: str) -> bool:
    """Whether the terminfo database describes ``term`` as paintable.

    POSIX only; on Windows there is no terminfo and the question is answered by
    :func:`_windows_console_renders_unicode` instead.

    ``curses.setupterm`` is the same lookup every curses program does, and the entry it
    finds has to declare absolute cursor addressing - the one capability Nivel A cannot
    work around. Anything that goes wrong - no terminfo database at all, a broken entry, a
    build of Python without ``curses`` - counts as "no guarantees", because that is what
    it is.

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
    """Whether ``TERM`` describes something Nivel A can safely draw on.

    Signal 6 of :func:`terminal_level` (ADR 0031, point 2): ``TERM=dumb`` is not the only
    way to end up without guarantees. An **empty or unset** ``TERM`` is routine inside
    containers and in some multiplexed SSH sessions, and an unknown value is routine on a
    host whose terminfo database does not carry the client's terminal type. In both cases
    there is a real terminal with no guarantee that a single escape sequence means
    anything, so this falls back to the floor rather than risk one.

    Only asked on POSIX. On Windows ``TERM`` is normally unset and says nothing; there the
    equivalent question is whether the console speaks VT, which is signal 7.
    """
    if os.name != "posix":
        return True
    term = os.environ.get("TERM", "").strip()
    return bool(term) and _terminfo_declares_full_screen(term)


def _term_is_dumb() -> bool:
    return os.environ.get("TERM", "").strip().lower() == _DUMB_TERM


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


def _animate(message: str, stop: threading.Event, level: TerminalLevel) -> None:
    """Redraw ``message`` with a rotating frame until ``stop`` is set, then clear the line.

    Level 0 keeps the four ASCII frames it always had, with no escape sequence. Level 1 cycles
    the ten-frame Braille set in the accent colour (ADR 0031, point 5) - more frames read as
    smoother motion, which is the whole ask of "spinner fluido". Either way the erase width is
    the same two cells (frame, space) plus the message: the accent colour changes what is
    written, never how much of the line it occupies.
    """
    if stop.wait(_SPINNER_GRACE_S):
        return
    frames = _SPINNER_FRAMES_LEVEL_1 if level == 1 else _SPINNER_FRAMES
    interval = _SPINNER_INTERVAL_LEVEL_1_S if level == 1 else _SPINNER_INTERVAL_S
    accent = _ansi_fg(_ACCENT_HEX)
    for frame in itertools.cycle(frames):
        drawn = f"{accent}{frame}{_ANSI_RESET}" if level == 1 else frame
        _write_live(f"\r{drawn} {message}")
        if stop.wait(interval):
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
    worker = threading.Thread(target=_animate, args=(message, stop, terminal_level()), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=_SPINNER_JOIN_S)


def _render_step(done: int, total: int, label: str, level: TerminalLevel) -> str:
    """One frame of the determinate indicator: bar, counter and what is running now.

    Level 0 keeps the ``#``/``-`` bar with no escape sequence. Level 1 fills the same width
    with Unicode blocks in the accent colour (ADR 0031, point 5) - the counter and the label
    stay in the terminal's own foreground, because they are content, not structure (point 7,
    rule 2).
    """
    filled = round(_BAR_WIDTH * done / total) if total else _BAR_WIDTH
    empty = _BAR_WIDTH - filled
    if level == 1:
        filled_run = _ansi_fg(_ACCENT_HEX) + _BAR_DONE_LEVEL_1 * filled + _ANSI_RESET
        bar = filled_run + _BAR_TODO_LEVEL_1 * empty
    else:
        bar = _BAR_DONE * filled + _BAR_TODO * empty
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
    level = terminal_level()
    widest = 0

    def update(done: int, label: str) -> None:
        nonlocal widest
        frame = _render_step(done, total, label, level)
        # A level-1 frame carries SGR bytes that occupy no cell on screen: the padding math
        # has to measure what is drawn, not what is written, or the erase line comes up short.
        visible = _visible_length(frame)
        widest = max(widest, visible)
        _write_live("\r" + frame + " " * (widest - visible))

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
    """Write a human-facing line to stderr, styled only when the terminal allows it.

    Level 0 keeps drawing exactly what it always has: the plain word, in the basic eight
    colours, gated by :func:`color_enabled` alone would have been enough - except it is not
    (ADR 0031, point 8, trap 2). ``color_enabled`` never asks about ``CI`` or an unknown
    ``TERM``, so a build runner with a real pty attached can pass it while
    :func:`terminal_level` still says 0, and that gap is exactly where a stray escape sequence
    - bold included - would leak into a log file someone reads a month later. So the gate here
    is :func:`terminal_level`, which is a strict superset of :func:`color_enabled`'s checks:
    everywhere the two used to agree, they still do.

    Level 1 adds the ADR 0031 palette in place of the basic eight, and, for the three states
    that carry one, the glyph that goes with it - shape, word and colour together, never colour
    alone (ADR 0031, point 7, rule 1).
    """
    level_1 = terminal_level(sys.stderr) == 1
    glyph = _STATE_GLYPHS.get(style) if level_1 else None
    text = f"{glyph} {message}" if glyph else message
    typer.secho(
        text,
        fg=_LEVEL_1_STYLE_COLORS[style] if level_1 else _STYLE_COLORS[style],
        bold=level_1 and style == "heading",
        err=True,
        color=level_1,
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


#: Extra cells :func:`table` reserves for the outer frame at level 1: one border character
#: and one padding space on each side, so text never touches the frame. Level 0 draws no
#: outer frame (``show_edge=False``) and reserves nothing; level 1 does, and the width budget
#: has to know about it before ``rich`` ever sees a column, or a table that just fit the
#: window would overflow it by exactly this much.
_LEVEL_1_EDGE_WIDTH: Final[int] = 4


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    width: int | None = None,
    level: TerminalLevel = 0,
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
    - **Level 0: ASCII frame, no colour.** ``box.ASCII`` and ``no_color`` are not a fallback
      for hostile terminals, they are the floor's output (ADR 0031, point 4): a Windows console
      on a legacy code page turns the Unicode box characters ``rich`` would otherwise pick into
      ``?``, and colour that carries meaning is unreadable for whoever does not see it or
      redirects it to a file. What is left is a header rule and column separators, which is all
      a table needs, with no outer frame and no trailing blanks: padding a row out to a frame
      puts invisible characters in a redirected file for no gain.
    - **Level 1: rounded frame, accent on header and border.** ADR 0031, point 5, and its own
      point 7, rule 2: the accent draws the structure - headers, the frame - and cell content
      keeps the terminal's own foreground. Identifiers are not recoloured, so nothing here needs
      a per-cell style, and the width budget this function already computes is untouched except
      for the two cells :data:`_LEVEL_1_EDGE_WIDTH` reserves for the frame itself.

    Args:
        headers: Column titles, already localized.
        rows: One sequence of already formatted cells per row, same length as ``headers``.
        width: Cells to fit into. Defaults to :func:`display_width` of stdout; passed
            explicitly by the callers that write elsewhere, and by tests, which is how the
            behaviour at every width is pinned without opening a terminal.
        level: The capability level to draw for (:func:`terminal_level` of the caller's own
            channel). Defaults to 0 - the floor - on purpose: a caller that does not ask for
            level 1 gets exactly what it always got, which is what keeps this default safe for
            every existing call site and for the level-0 contract tests, none of which pass it.

    Returns:
        The rendered table, newline separated and without a trailing newline. Or, when the
        window cannot hold even the headers, the same data as ``key: value`` blocks.
    """
    available = display_width() if width is None else width
    edge_reserve = _LEVEL_1_EDGE_WIDTH if level == 1 else 0
    natural = _natural_widths(headers, rows)
    fitted = _fitted_widths(natural, [len(header) for header in headers], available - edge_reserve)
    if fitted is None:
        return _as_records(headers, rows)
    grid = Table(
        box=box.ROUNDED if level == 1 else box.ASCII,
        show_edge=level == 1,
        pad_edge=level == 1,
        header_style=f"bold {_ACCENT_HEX}" if level == 1 else None,
        border_style=_ACCENT_HEX if level == 1 else None,
    )
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
        no_color=level == 0,
        # Only forced at level 1: the buffer itself never answers ``isatty()``, and without
        # this ``rich`` would silently fall back to no colour, defeating the whole point of
        # asking for one. The colour system is pinned rather than auto-detected for the same
        # reason width is passed explicitly: a memory buffer has no ``COLORTERM`` to read, and
        # every hex in the ADR 0031 palette is meant to reach the terminal exactly, not
        # downgraded to the nearest of sixteen.
        color_system="truecolor" if level == 1 else None,
        force_terminal=level == 1,
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
    "NO_CONSOLE_PREP_ENV",
    "UI_LEVEL_ENV",
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
    "note",
    "prepare_windows_console",
    "progress",
    "status",
    "stdout_is_reserved",
    "stdout_reserved_for_protocol",
    "stdout_terminal_level",
    "steps",
    "success",
    "table",
    "terminal_level",
    "warn",
)
