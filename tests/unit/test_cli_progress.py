"""The activity indicator: visible when someone is watching, absent when nobody is.

Issue #205. Two halves that only prove something together:

* :func:`test_a_redirected_run_gets_the_result_line_and_nothing_else` runs a **real
  subprocess** whose stderr is a pipe. In-process capture would not be the same claim: pytest
  substitutes ``sys.stderr`` at the Python level, so it never exercises the thing a user
  actually does — ``2> salida.txt`` — where the redirection happens at the file descriptor and
  the answer comes from the operating system. The bytes asserted here are the bytes that would
  land in that file.
* :func:`test_a_real_terminal_gets_frames_and_gets_its_line_back` forces the other branch and
  shows the indicator does draw, and does clean up after itself. Without it, the first test
  would also pass on an implementation that never draws anything at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Final

import pytest

from nz_mcp import cli_output

#: Long enough for the grace period to expire and several frames to be drawn.
_ENOUGH_TO_DRAW_S: Final[float] = cli_output._SPINNER_GRACE_S + 4 * cli_output._SPINNER_INTERVAL_S

_RESULT_LINE: Final[str] = "1/3 Connection: OK"

_CHILD_SOURCE: Final[str] = "\n".join(
    [
        "import time",
        "from nz_mcp import cli_output as out",
        "with out.progress('opening the session to nz.example.com:5480'):",
        f"    time.sleep({_ENOUGH_TO_DRAW_S})",
        f"out.note({_RESULT_LINE!r})",
    ]
)


class _FakeTerminal:
    """A stderr that claims to be a terminal and remembers every write."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self._lock = threading.Lock()

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        with self._lock:
            self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def rendered(self) -> str:
        with self._lock:
            return "".join(self.writes)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_child(**extra_env: str) -> bytes:
    """Run the child script with stderr on a pipe and return its raw stderr bytes."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_project_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra_env)
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _CHILD_SOURCE],
        check=False,
        capture_output=True,
        timeout=120,
        cwd=_project_root(),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout == b"", f"the indicator must never touch stdout: {proc.stdout!r}"
    return proc.stderr


def _normalized(stderr: bytes) -> bytes:
    """Collapse the platform line ending so a bare carriage return stands out.

    Windows turns every ``\\n`` into ``\\r\\n`` on the way out, so a raw ``b"\\r" not in``
    check would fail on a perfectly clean run. Removing the pairs first leaves only the
    carriage returns an in-place redraw would have written.
    """
    return stderr.replace(b"\r\n", b"\n")


def test_a_redirected_run_gets_the_result_line_and_nothing_else() -> None:
    """Piped stderr: the result line, and not one byte of animation around it."""
    body = _normalized(_run_child())

    assert body == _RESULT_LINE.encode() + b"\n", (
        f"a redirected run must read exactly as it did before the indicator existed, got {body!r}"
    )
    assert b"\r" not in body, "an in-place redraw reached a stream that is not a terminal"
    assert b"\x1b" not in body, "an escape sequence reached a stream that is not a terminal"


def test_a_hostile_environment_does_not_talk_the_detection_into_animating() -> None:
    """``FORCE_COLOR`` and a colour-capable ``TERM`` do not make a pipe into a terminal.

    Environment variables are what a CI runner sets; ``isatty`` is what the pipe answers.
    The design says detect, do not trust, and this is the case where trusting would show.
    """
    body = _normalized(_run_child(FORCE_COLOR="1", TERM="xterm-256color"))

    assert body == _RESULT_LINE.encode() + b"\n"
    assert b"\r" not in body


def test_a_dumb_terminal_gets_no_animation_either(monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setenv("TERM", "dumb")

    assert cli_output.animation_enabled() is False


def test_no_color_still_allows_the_indicator(monkeypatch: pytest.MonkeyPatch) -> None:
    """``NO_COLOR`` is about colour; "the command is alive" is not colour.

    Colour and motion are deliberately different predicates: someone who turns colour off
    on a real terminal has not asked to be left staring at a frozen screen.
    """
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)

    assert cli_output.color_enabled() is False
    assert cli_output.animation_enabled() is True


def test_a_real_terminal_gets_frames_and_gets_its_line_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a terminal the indicator draws, names the wait, and erases itself on the way out."""
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.delenv("TERM", raising=False)

    with cli_output.progress("opening the session"):
        time.sleep(_ENOUGH_TO_DRAW_S)

    rendered = terminal.rendered()
    assert "opening the session" in rendered, "the indicator did not name what it waits on"
    assert any(f"\r{frame} " in rendered for frame in cli_output._SPINNER_FRAMES)
    assert "\x1b" not in rendered, "the indicator must not need an escape sequence to redraw"
    assert rendered.endswith("\r"), "the indicator left its line on screen instead of erasing it"
    # The erase is spaces, not an ANSI clear: the last write blanks the whole drawn line.
    assert " " * len("opening the session") in terminal.writes[-1]


def test_a_wait_shorter_than_the_grace_period_draws_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that resolves instantly must not flash an indicator on and off.

    Skipped ladder levels resolve in microseconds. Drawing for them would be the flicker the
    design calls noise, and it would also scroll the real result lines around for no reason.
    """
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.delenv("TERM", raising=False)

    with cli_output.progress("this resolves at once"):
        pass

    assert terminal.rendered() == ""


_STEPS_CHILD_SOURCE: Final[str] = "\n".join(
    [
        "from nz_mcp import cli_output as out",
        "with out.steps(3) as step:",
        "    for n in (1, 2, 3):",
        "        step(n, f'query_{n}')",
        f"out.note({_RESULT_LINE!r})",
    ]
)


def test_the_determinate_indicator_writes_nothing_without_a_terminal() -> None:
    """Redirected, ``probe-catalog`` must leave the report in the file and nothing else.

    A subprocess with a real pipe, not an in-process capture: what is asserted here is what
    would land in ``informe.txt``, decided by the operating system and not by pytest.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_project_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = "xterm-256color"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _STEPS_CHILD_SOURCE],
        check=False,
        capture_output=True,
        timeout=120,
        cwd=_project_root(),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout == b"", "the indicator must never touch stdout"
    body = _normalized(proc.stderr)
    assert body == _RESULT_LINE.encode() + b"\n"
    assert b"\r" not in body
    assert b"\x1b" not in body


def test_the_determinate_indicator_counts_and_names_the_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A percentage is only honest with a real denominator, and it must name the step.

    The name is the part that answers "on which one did it hang?" — the question fourteen
    queries of silence used to leave open. It is also what makes the bar worth drawing at all.
    """
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.delenv("TERM", raising=False)

    with cli_output.steps(14) as step:
        step(1, "list_databases")
        step(7, "table_stats")

    rendered = terminal.rendered()
    assert "1/14" in rendered
    assert "7/14 table_stats" in rendered
    assert cli_output._BAR_DONE in rendered
    assert cli_output._BAR_TODO in rendered
    assert "\x1b" not in rendered, "redrawing must not need an escape sequence"
    assert rendered.endswith("\r"), "the indicator left its line on screen instead of erasing it"


def test_the_determinate_indicator_erases_the_widest_line_it_drew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long step name followed by a short one must not leave half a word behind."""
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.delenv("TERM", raising=False)

    with cli_output.steps(2) as step:
        step(1, "a_very_long_catalog_query_identifier")
        step(2, "short")

    assert "a_very_long_catalog_query_identifier" not in terminal.writes[-1]
    assert terminal.writes[-1].count(" ") >= len("a_very_long_catalog_query_identifier")


def test_the_indicator_lets_a_failure_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """It decorates a wait; it never swallows what happened during it."""
    terminal = _FakeTerminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.delenv("TERM", raising=False)

    with (
        pytest.raises(RuntimeError, match="driver said no"),
        cli_output.progress("opening the session"),
    ):
        raise RuntimeError("driver said no")

    assert terminal.rendered() == ""
