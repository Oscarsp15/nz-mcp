"""What an aligned table gives up when the window is too narrow (issue #220).

The report was that ``list-profiles`` printed exactly the same thing at ``COLUMNS=40`` as
in a wide terminal, so the terminal cut the rows wherever it happened to run out. The fix
is not "make it fit": it is a **declared order of sacrifice**, written in the docstring of
``cli_output`` and pinned here step by step, because a table that loses whatever it
happens to lose is a table nobody can trust to answer *which profile is this*.

Every test injects the width. Nothing here opens a terminal, which is what makes the
narrow cases testable at all.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from nz_mcp import cli_output
from nz_mcp.diagnostic import DiagnosticReport, format_diagnostic_report

_ANSI_SEQUENCE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: The real shape of the profile table: five columns, one of them much longer than its
#: header and two that are short because their values are short.
_HEADERS: Final[list[str]] = ["Perfil", "Host", "Base de datos", "Modo", "Activo"]
_ROWS: Final[list[list[str]]] = [
    ["nzsaas", "10.51.10.242", "DESA_MODELOS", "admin", "*"],
    ["prod", "nz-prod-01.corp.example.com", "RETAIL_ANALYTICS", "read", ""],
]

#: Width at which the five headers plus their separators stop fitting: 6 + 4 + 13 + 4 + 6
#: plus four separators of three cells each.
_HEADERS_ONLY_WIDTH: Final[int] = 45


class _FakeStream:
    """A stand-in for a standard stream that knows whether it is a terminal."""

    def __init__(self, *, terminal: bool) -> None:
        self._terminal = terminal

    def isatty(self) -> bool:
        return self._terminal


def _widest_line(rendered: str) -> int:
    return max(len(line) for line in rendered.splitlines())


@pytest.mark.parametrize("width", [200, 100, 72, 60, 50, _HEADERS_ONLY_WIDTH])
def test_the_table_never_exceeds_the_width_it_was_given(width: int) -> None:
    """The whole point. Above the headers-only width, the rows fit the window."""
    assert _widest_line(cli_output.table(_HEADERS, _ROWS, width=width)) <= width


def test_a_wide_window_changes_nothing() -> None:
    """Adapting must not mean rewriting what already fitted.

    The table is sized to its content first and only shrinks under pressure, so a terminal
    wide enough gets the same bytes it got before any of this existed.
    """
    wide = cli_output.table(_HEADERS, _ROWS, width=200)
    assert "nz-prod-01.corp.example.com" in wide
    assert cli_output._ELLIPSIS not in wide


def test_the_widest_column_pays_first() -> None:
    """Step 3 of the order: pressure lands on the host, not on ``Modo`` or ``Activo``.

    A narrow window is exactly when the short columns matter most - *which* profile is
    active, and *what* may it do - so shaving them to keep a hostname whole would be
    trading the answer for the detail.
    """
    rendered = cli_output.table(_HEADERS, _ROWS, width=60)
    assert "admin" in rendered
    assert "read" in rendered
    assert "DESA_MODELOS" in rendered
    assert "nz-prod-01.corp.example.com" not in rendered


def test_a_cell_loses_its_middle_and_keeps_both_ends() -> None:
    """Step 4, and the reason the order is written down rather than left to the terminal.

    Two hosts in the same subnet differ at the end and two hosts in the same domain differ
    at the front. A tail cut answers "which one is this?" with the same string twice.
    """
    rows = [
        ["a", "10.51.10.242", "DB", "read", ""],
        ["b", "10.51.10.243", "DB", "read", ""],
    ]
    lines = cli_output.table(_HEADERS, rows, width=48).splitlines()
    first, second = lines[2], lines[3]
    assert first != second
    # Both ends survive, and they are exactly the ends that tell these two apart.
    assert "| 10...42 |" in first
    assert "| 10...43 |" in second


def test_no_column_is_ever_hidden_and_no_row_dropped() -> None:
    """Steps 1 and 2: whatever the width, every header and every row is still there.

    Hiding a column is the one loss a person cannot notice, because what disappears is the
    evidence that anything did.
    """
    for width in (200, 80, 60, 50, _HEADERS_ONLY_WIDTH, 40, 20):
        rendered = cli_output.table(_HEADERS, _ROWS, width=width)
        for header in _HEADERS:
            assert header in rendered
        assert "nzsaas" in rendered
        assert "prod" in rendered


def test_below_the_headers_it_stops_being_a_table() -> None:
    """Step 5. Columns narrower than their own titles are decoration, not information.

    The fallback is the shape ``list-profiles`` already uses for a single profile, so it is
    not a new thing to learn - and nothing is truncated in it, because there is no
    alignment left to protect.
    """
    rendered = cli_output.table(_HEADERS, _ROWS, width=_HEADERS_ONLY_WIDTH - 1)
    assert "|" not in rendered
    assert "Host: nz-prod-01.corp.example.com" in rendered
    assert "Perfil: nzsaas" in rendered
    # One blank line between records, and only there: the blocks are what separates rows.
    assert rendered.count("\n\n") == 1


def test_a_record_block_leaves_out_the_cells_that_are_empty() -> None:
    """A label with nothing after it reads as missing data, not as the blank it is."""
    rendered = cli_output.table(_HEADERS, _ROWS, width=30)
    assert "Activo: *" in rendered
    assert "Activo:\n" not in rendered


def test_exactly_at_the_headers_width_the_table_survives() -> None:
    """The boundary is inclusive, and it is where the floors of every column are reached."""
    rendered = cli_output.table(_HEADERS, _ROWS, width=_HEADERS_ONLY_WIDTH)
    assert "|" in rendered
    assert _widest_line(rendered) == _HEADERS_ONLY_WIDTH


def test_an_empty_table_is_not_a_crash() -> None:
    """Headers with no rows: nothing to align, and nothing to blow up on either."""
    assert cli_output.table(_HEADERS, []).splitlines()[0].startswith("Perfil")


def test_without_a_terminal_no_width_is_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect or a pipe gets the data whole, whatever ``COLUMNS`` happens to say.

    A file is kept and read later, in a window that has nothing to do with the one the
    command ran in; shrinking it to a terminal that is not there would lose data for
    nobody's benefit. So the width is fixed, and the content still decides the columns.
    """
    monkeypatch.setattr("sys.stdout", _FakeStream(terminal=False))
    monkeypatch.setenv("COLUMNS", "40")
    assert cli_output.display_width() == cli_output._WIDTH_WITHOUT_TERMINAL
    assert "nz-prod-01.corp.example.com" in cli_output.table(_HEADERS, _ROWS)


def test_with_a_terminal_the_width_is_the_terminal_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And ``COLUMNS`` overrides it, which is how the issue was reported by hand."""
    monkeypatch.setattr("sys.stdout", _FakeStream(terminal=True))
    monkeypatch.setenv("COLUMNS", "58")
    monkeypatch.setenv("LINES", "24")
    assert cli_output.display_width() == 58
    assert _widest_line(cli_output.table(_HEADERS, _ROWS)) <= 58


def test_each_stream_is_asked_about_its_own_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The payload table and the report table do not travel on the same channel.

    ``list-profiles`` writes its table to stdout and ``probe-catalog --verbose`` writes its
    own to stderr, so a run with stdout redirected and stderr on a terminal has to size
    each one to where it actually lands - the file whole, the report to the window.
    """
    monkeypatch.setattr("sys.stdout", _FakeStream(terminal=False))
    monkeypatch.setattr("sys.stderr", _FakeStream(terminal=True))
    monkeypatch.setenv("COLUMNS", "58")
    assert cli_output.display_width() == cli_output._WIDTH_WITHOUT_TERMINAL
    assert cli_output.display_width(sys.stderr) == 58


def test_the_truncation_marker_is_ascii() -> None:
    """A Windows console on a legacy code page turns a real ellipsis into ``?``.

    Same rule as the spinner frames, the progress bar and the status markers: the marker
    that says "there was more here" has to survive the console this product mostly runs on.
    """
    assert cli_output._ELLIPSIS.isascii()
    assert cli_output.table(_HEADERS, _ROWS, width=50).isascii()


# --- the other wide surfaces, reviewed with the same criterion ----------------


def test_the_help_screen_fits_the_window_it_is_printed_in() -> None:
    """The help is the other screen that can be too wide, and it already adapts.

    Not this project's code - typer renders it through ``rich``, which reads ``COLUMNS`` -
    but the issue asked for the review and a review that changes nothing still has to leave
    a test behind, or the next change to the help panels breaks it silently.
    """
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["NZ_MCP_LANG"] = "es"
    env["COLUMNS"] = "40"
    env["NO_COLOR"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "nz_mcp", "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=root,
        env=env,
    )
    lines = _ANSI_SEQUENCE.sub("", completed.stdout).splitlines()
    assert lines
    assert max(len(line) for line in lines) <= 40


def test_the_diagnostic_report_never_truncates_a_value() -> None:
    """``doctor`` is one entity with many attributes, so it is ``key: value`` and stays so.

    There are no columns to keep aligned, which means there is nothing to gain by cutting a
    long path and everything to lose: the report exists to be pasted into an issue, and a
    path with its middle missing is a path nobody can act on. A window narrower than a line
    wraps it, and wrapping keeps every character.
    """
    long_path = "/home/" + "a" * 120 + "/.nz-mcp"
    report = DiagnosticReport(
        nz_mcp_version="0.1.0a3",
        python_version="3.11.5",
        platform="Windows-10",
        config_dir=long_path,
        config_dir_exists=True,
        config_dir_writable=True,
        profiles_path=long_path + "/profiles.toml",
        profiles_path_exists=True,
        profiles_load_ok=True,
        profiles_count=2,
        profiles_names=("nzsaas", "prod"),
        active_profile="prod",
        keyring_backend="WinVaultKeyring",
        keyring_available=True,
        locale="es",
    )
    rendered = format_diagnostic_report(report, locale="es")
    assert long_path in rendered
    assert cli_output._ELLIPSIS not in rendered
