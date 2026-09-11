"""How the CLI wires "Ver perfiles" into ``nz-mcp`` with no arguments (issue #240).

The seam under test is ``cli._open_profiles_screen``: it either opens the screen or falls
straight back to ``list-profiles``, and the four ways out of the screen - an action, the
empty state's "configurar", Escape, and a window too small - each lead to a specific place
in ``cli.py``. The application itself is exercised with a real ``Pilot`` in
``test_profiles_screen_app.py``; here it is replaced by a stub, following the same split
``test_cli_wizard_interactive.py`` already uses for the wizard, so what is under test is the
wiring rather than a second copy of the screen's own behaviour.

Acceptance criterion 10 of issue #240 - "``nz-mcp list-profiles`` and the rest of the
commands do not change" - is checked directly: typed on the command line, the screen never
builds, gate open or not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from nz_mcp import cli
from nz_mcp import cli_output as out
from nz_mcp.cli import app
from nz_mcp.config import active_profile_name, load_profiles_file
from nz_mcp.menu import MIN_HEIGHT as MENU_MIN_HEIGHT
from nz_mcp.menu import MIN_WIDTH as MENU_MIN_WIDTH
from nz_mcp.menu import MenuChoice
from nz_mcp.profiles_screen import MIN_HEIGHT as PROFILES_MIN_HEIGHT
from nz_mcp.profiles_screen import MIN_WIDTH as PROFILES_MIN_WIDTH
from nz_mcp.profiles_screen import ProfilesChoice

runner = CliRunner()

#: The task the six-task menu hands back when "Ver perfiles" is chosen (ADR 0032).
_PROFILES_CHOSEN: Final[MenuChoice] = MenuChoice(status="chosen", command="list-profiles")


def _gate(*, menu: bool, profiles: bool) -> object:
    """A stand-in for ``interactive_ui_enabled`` that answers by which screen is asking.

    The menu's own gate (60x18) and this screen's (72x18) share a height, so the two are
    told apart by width - asserted here rather than assumed, so a future change to either
    minimum fails this helper instead of silently testing the wrong gate.
    """
    assert MENU_MIN_WIDTH != PROFILES_MIN_WIDTH, "the two gates must stay distinguishable"

    def enabled(*, min_width: int, min_height: int) -> bool:
        if min_width == MENU_MIN_WIDTH and min_height == MENU_MIN_HEIGHT:
            return menu
        if min_width == PROFILES_MIN_WIDTH and min_height == PROFILES_MIN_HEIGHT:
            return profiles
        raise AssertionError(f"unexpected gate size {min_width}x{min_height}")

    return enabled


def _open_both_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(out, "interactive_ui_enabled", _gate(menu=True, profiles=True))


def _refuse_to_open_the_profiles_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(**_: object) -> ProfilesChoice:
        raise AssertionError("the profiles screen was built even though its gate was closed")

    monkeypatch.setattr(cli, "choose_profile", explode)


@pytest.fixture(autouse=True)
def spanish_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es")


# --- reaching the screen, and never reaching it from the plain command -----------------


def test_choosing_ver_perfiles_opens_the_screen_when_both_gates_are_open(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    _open_both_gates(monkeypatch)
    seen: dict[str, object] = {}

    def stub_choose_profile(*, rows: object, locale: object) -> ProfilesChoice:
        seen["rows"] = rows
        seen["locale"] = locale
        return ProfilesChoice(status="cancelled")

    monkeypatch.setattr(cli, "choose_profile", stub_choose_profile)
    # Escape from "Ver perfiles" reopens the six-task menu (ADR 0032); the second time
    # through, Escape from the menu itself ends the process the way it always did.
    monkeypatch.setattr(
        cli,
        "choose_command",
        _sequence([_PROFILES_CHOSEN, MenuChoice(status="cancelled")]),
    )

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stderr
    rows = seen["rows"]
    assert isinstance(rows, tuple)
    assert [row.name for row in rows] == ["dev", "prod"]
    assert next(row for row in rows if row.name == "dev").active is True
    assert next(row for row in rows if row.name == "prod").active is False
    # No password was stored for either profile: known without a connection, so "warning".
    assert {row.status for row in rows} == {"warning"}


def test_list_profiles_typed_directly_never_opens_the_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """Acceptance criterion 10 of issue #240: the plain command is unaffected."""
    _open_both_gates(monkeypatch)
    _refuse_to_open_the_profiles_screen(monkeypatch)

    result = runner.invoke(app, ["list-profiles"])

    assert result.exit_code == 0, result.stderr
    assert "No hay ning" in result.stderr


def test_a_window_too_small_for_the_screen_falls_back_to_the_plain_command(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The menu's own gate can pass while this screen's own, larger minimum does not."""
    monkeypatch.setattr(out, "interactive_ui_enabled", _gate(menu=True, profiles=False))
    monkeypatch.setattr(cli, "choose_command", lambda **_: _PROFILES_CHOSEN)
    _refuse_to_open_the_profiles_screen(monkeypatch)

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stderr
    assert "No hay ning" in result.stderr


def test_a_profiles_file_that_does_not_parse_falls_back_to_the_plain_command(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    tmp_profiles.write_text("not valid toml [[[", encoding="utf-8")
    _open_both_gates(monkeypatch)
    _refuse_to_open_the_profiles_screen(monkeypatch)
    monkeypatch.setattr(cli, "choose_command", lambda **_: _PROFILES_CHOSEN)

    result = runner.invoke(app, [])

    assert result.exit_code == 1
    assert "CONFIG" in result.stderr or "inválid" in result.stderr.lower()


# --- the four ways "Ver perfiles" ends --------------------------------------------------


def test_an_action_dispatches_to_the_command_that_already_exists(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """ "Usar" really runs ``switch-profile``, end to end, with no stub in between."""
    _open_both_gates(monkeypatch)
    monkeypatch.setattr(
        cli,
        "choose_command",
        _sequence([_PROFILES_CHOSEN]),
    )
    chosen = ProfilesChoice(status="chosen", profile="prod", action="use")
    monkeypatch.setattr(cli, "choose_profile", lambda **_: chosen)

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stderr
    file = load_profiles_file(two_profiles)
    assert active_profile_name(file) == "prod"


def test_removing_defaults_to_cancelled_and_names_the_profile(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Acceptance criterion 4 of issue #240, exercised through the real ``remove-profile``."""
    _open_both_gates(monkeypatch)
    monkeypatch.setattr(cli, "choose_command", _sequence([_PROFILES_CHOSEN]))
    monkeypatch.setattr(
        cli,
        "choose_profile",
        lambda **_: ProfilesChoice(status="chosen", profile="prod", action="remove"),
    )

    result = runner.invoke(app, [], input="\n")  # Enter accepts the default: no.

    assert result.exit_code == 1
    assert "prod" in result.stderr
    assert "prod" in load_profiles_file(two_profiles).profiles


def test_the_empty_state_runs_init(monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path) -> None:
    _open_both_gates(monkeypatch)
    monkeypatch.setattr(cli, "choose_command", _sequence([_PROFILES_CHOSEN]))
    monkeypatch.setattr(cli, "choose_profile", lambda **_: ProfilesChoice(status="configure"))
    launched: list[str] = []
    monkeypatch.setattr(cli, "_launch", lambda _ctx, name: launched.append(name))

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stderr
    assert launched == ["init"]


def test_escape_reopens_the_six_task_menu_instead_of_ending_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _open_both_gates(monkeypatch)
    calls = _sequence([_PROFILES_CHOSEN, MenuChoice(status="chosen", command="version")])
    monkeypatch.setattr(cli, "choose_command", calls)
    monkeypatch.setattr(cli, "choose_profile", lambda **_: ProfilesChoice(status="cancelled"))

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stderr
    assert calls.call_count == 2


def test_a_window_shrunk_below_the_minimum_mid_session_prints_the_help(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _open_both_gates(monkeypatch)
    monkeypatch.setattr(cli, "choose_command", lambda **_: _PROFILES_CHOSEN)
    monkeypatch.setattr(cli, "choose_profile", lambda **_: ProfilesChoice(status="degraded"))

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "init" in result.stdout


# --- the mapping from action to command, without the CLI runner ------------------------


def test_every_action_maps_to_its_own_command_and_argv() -> None:
    mapping = cli._PROFILE_ACTION_COMMANDS
    assert mapping["use"][0] == "switch-profile"
    assert mapping["use"][1]("dev") == ["dev"]
    assert mapping["test"][0] == "test-connection"
    assert mapping["test"][1]("dev") == ["--profile", "dev"]
    assert mapping["edit"][0] == "edit-profile"
    assert mapping["edit"][1]("dev") == ["dev"]
    assert mapping["remove"][0] == "remove-profile"
    assert mapping["remove"][1]("dev") == ["dev"]


def test_profile_rows_read_status_locally_without_opening_a_connection(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """Acceptance criterion 1 of issue #240, at the source that builds the rows."""

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a connection was opened just to read the row status")

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", explode)

    rows = cli._profile_rows()

    assert {row.name for row in rows} == {"dev", "prod"}
    assert all(row.status == "warning" for row in rows), "no password is stored yet"


class _Sequence:
    """Callable stand-in that hands back each result in order and counts its calls."""

    def __init__(self, results: list[object]) -> None:
        self._results = list(results)
        self.call_count = 0

    def __call__(self, **_kwargs: object) -> object:
        self.call_count += 1
        return self._results.pop(0)


def _sequence(results: list[object]) -> _Sequence:
    """A callable that returns each of ``results`` in order, and remembers how often it ran.

    Plain ``side_effect``-style stand-in: the module under test calls these as keyword-only
    functions (``choose_command(entries=..., locale=..., context=...)``), so a
    ``unittest.mock`` iterator would work too, but this keeps the call count visible without
    importing ``unittest.mock`` for one counter.
    """

    return _Sequence(results)
