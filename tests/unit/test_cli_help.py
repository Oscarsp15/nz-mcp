"""The help screen (issue #209): order, wording, and what a legacy console can render.

``nz-mcp`` with no arguments prints this screen, so it is the first thing anyone sees. The
checks here are the three ways it used to fail someone who had just installed the package:
the commands came out in the order they happened to be written, the descriptions quoted
internals nobody outside the repository has read, and non-ASCII punctuation turned into
question marks on a Windows console running a legacy code page.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from nz_mcp.cli import app
from nz_mcp.i18n import MESSAGES

_ESC: Final[str] = "\x1b["

#: Every command, in the order someone needs them: install, prove it works, live with it,
#: diagnose, and last the two you rarely type by hand. Typer lists commands in registration
#: order, so this sequence *is* the help screen.
_EXPECTED_ORDER: Final[tuple[str, ...]] = (
    "init",
    "test-connection",
    "list-profiles",
    "switch-profile",
    "add-profile",
    "edit-profile",
    "remove-profile",
    "doctor",
    "probe-catalog",
    "version",
    "serve",
)

#: Console code pages still shipped by default on Windows: 437 on an en-US install, 850 on a
#: Spanish one. Both carry the lowercase accented vowels, the "n" with tilde and the inverted
#: question mark that real Spanish needs; neither carries em dashes, ellipsis characters or
#: uppercase accented vowels.
_LEGACY_CODE_PAGES: Final[tuple[str, ...]] = ("cp437", "cp850")

#: Substrings that mean the text was written for someone who has read the source: MCP tool
#: names, reStructuredText markup, module and configuration file names.
_INTERNAL_JARGON: Final[tuple[str, ...]] = ("nz_", "``", ".py", ".toml")


def _help_texts() -> dict[str, str]:
    """Every catalog entry that ends up on the help screen, keyed by ``KEY[locale]``."""
    texts: dict[str, str] = {}
    for key, message in MESSAGES.items():
        if key.startswith("CLI.HELP."):
            texts[f"{key}[es]"] = message["es"]
            texts[f"{key}[en]"] = message["en"]
    return texts


def test_commands_are_listed_in_the_order_they_are_used() -> None:
    """Registration order is presentation order, and presentation order is the journey.

    Before this, ``version`` came first and ``init`` second, purely because of where they sat
    in the file: the command someone needs on minute one was buried in an arbitrary list.
    """
    assert [command.name for command in app.registered_commands] == list(_EXPECTED_ORDER)


def test_the_top_of_the_help_names_the_command_to_start_with() -> None:
    """A list of eleven commands with no entry point leaves the reader to guess."""
    top = app.info.help or ""
    assert "nz-mcp init" in top


def test_every_command_takes_its_description_from_the_catalog() -> None:
    """A description left to the docstring is English forever: docstrings do not translate."""
    described = {text for key, text in _help_texts().items() if not key.startswith("CLI.HELP.OPT.")}
    for command in app.registered_commands:
        assert command.help, f"{command.name} has no help= and would fall back to its docstring"
        assert command.help in described, f"{command.name} does not use a catalog description"


@pytest.mark.parametrize("jargon", _INTERNAL_JARGON)
def test_no_help_text_leaks_internal_jargon(jargon: str) -> None:
    """Whoever reads the help has not read the code, the tool catalog or the profiles file."""
    offenders = {key: text for key, text in _help_texts().items() if jargon in text}
    assert offenders == {}, f"{jargon!r} in help text: {offenders}"


@pytest.mark.parametrize("code_page", _LEGACY_CODE_PAGES)
def test_help_text_survives_a_legacy_windows_code_page(code_page: str) -> None:
    """A character the code page lacks prints as a question mark on the main platform.

    That is not hypothetical: the em dash in the old ``doctor`` line rendered as
    ``keyring ? no Netezza`` on a stock Windows console, which is what put this in the issue.
    """
    for key, text in _help_texts().items():
        try:
            text.encode(code_page)
        except UnicodeEncodeError as exc:  # pragma: no cover - only on a regression
            pytest.fail(f"{key} cannot be rendered on {code_page}: {exc.object[exc.start]!r}")


def _run_help(*, lang: str) -> subprocess.CompletedProcess[str]:
    """Run ``--help`` in a subprocess with both streams piped, i.e. never a terminal.

    A subprocess and not an in-memory runner on purpose: the language is resolved while the
    module is imported, so a monkeypatched environment variable in this process would come
    too late to change anything.
    """
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["NZ_MCP_LANG"] = lang
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("FORCE_COLOR", None)
    env.pop("NO_COLOR", None)
    return subprocess.run(
        [sys.executable, "-m", "nz_mcp", "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=root,
        env=env,
    )


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("es", "Crea tu primer perfil"),
        ("en", "Create your first connection profile"),
    ],
)
def test_the_help_screen_speaks_the_configured_language(lang: str, expected: str) -> None:
    """It used to be English always, two minutes before the assistant answered in Spanish."""
    proc = _run_help(lang=lang)
    assert proc.returncode == 0, proc.stderr
    assert expected in proc.stdout


def test_the_rendered_help_starts_with_init_and_ends_with_serve() -> None:
    """The order has to survive typer's rendering, not just the registration list."""
    body = _run_help(lang="es").stdout
    assert body.index(" init ") < body.index(" serve ")


def test_redirected_help_is_plain_text() -> None:
    """Piped into a file or another process, the first screen must stay readable text."""
    proc = _run_help(lang="es")
    assert _ESC not in proc.stdout
    assert _ESC not in proc.stderr
