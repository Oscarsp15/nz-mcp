"""How the CLI uses the full-screen wizard, and what happens on each way out of it.

The seam under test is one function, ``cli._collect_draft``: it either opens a screen or
asks eight questions, and either way the rest of the command is the code that was already
there - the three-level ladder, the four ways out of a failure, and the write to
``profiles.toml`` and the keyring. That is condition 2 of ADR 0028, and the point of these
tests is that the *shared* half really is shared.

The application itself is exercised in ``test_wizard_app.py`` with a real ``Pilot``. Here
it is replaced by a stub, so what is under test is the wiring: which exit leads where, and
what survives each one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
import typer
from typer.testing import CliRunner

from nz_mcp import cli
from nz_mcp import cli_output as out
from nz_mcp.auth import get_password
from nz_mcp.cli import app
from nz_mcp.config import get_profile, load_profiles_file
from nz_mcp.wizard import DraftFields, WizardResult, WizardStatus

runner = CliRunner()

_PASSWORD: Final[str] = "pw123456"  # noqa: S105 - fixture value, not a real credential

_FORM = DraftFields(
    host="nz.example.com",
    port="5490",
    database="PROD",
    user="svc",
    mode="write",
    security_level="3",
    ca_certs="/etc/ssl/nz.pem",
)


class _Cursor:
    def execute(self, sql: str, params: object = None) -> None:
        del sql, params

    def fetchone(self) -> tuple[str]:
        return ("NPS 11.2.1.11",)

    def fetchall(self) -> list[tuple[str, str]]:
        return [("DB", "ADMIN")]

    def close(self) -> None:
        pass


class _Conn:
    def cursor(self) -> _Cursor:
        return _Cursor()

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def spanish_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es")


@pytest.fixture(autouse=True)
def netezza_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every connection succeeds: this file is about the wiring, not about the ladder."""
    monkeypatch.setattr("nz_mcp.profile_check.open_connection", lambda *_: _Conn())


def _open_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the terminal can host a full-screen application."""
    monkeypatch.setattr(out, "interactive_ui_enabled", lambda **_: True)


def _close_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(out, "interactive_ui_enabled", lambda **_: False)


def _stub_wizard(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: WizardStatus,
    fields: DraftFields = _FORM,
    types_the_credential: bool = True,
) -> list[str]:
    """Replace the application with a stub that ends the way a test wants it to.

    It calls ``ask_password`` when the test says the credential was typed, because that is
    what the real screen does: the value goes into the CLI's own holder and only a boolean
    crosses back.
    """
    calls: list[str] = []

    def collect(
        *,
        profile: str,
        initial: DraftFields,
        password_set: bool,
        ask_password: Callable[[], bool],
        locale: str,
    ) -> WizardResult:
        del initial, locale
        calls.append(profile)
        captured = ask_password() if types_the_credential else password_set
        return WizardResult(status=status, fields=fields, password_set=captured)

    monkeypatch.setattr(cli, "collect_profile_draft", collect)
    return calls


def test_the_form_answers_reach_profiles_toml_and_the_keyring(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The completed path: the screen collects, the code that was already there saves."""
    _open_the_gate(monkeypatch)
    opened = _stub_wizard(monkeypatch, status="completed")

    result = runner.invoke(app, ["add-profile", "dev"], input=f"{_PASSWORD}\n{_PASSWORD}\ny\n")

    assert result.exit_code == 0, result.stderr
    assert opened == ["dev"]
    profile = get_profile("dev", path=tmp_profiles)
    assert (profile.host, profile.port, profile.database) == ("nz.example.com", 5490, "PROD")
    assert (profile.user, profile.mode, profile.security_level) == ("svc", "write", 3)
    assert profile.ca_certs == "/etc/ssl/nz.pem"
    assert get_password("dev") == _PASSWORD


def test_the_shared_validation_ladder_still_runs_after_the_screen_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """Risk 4 of ADR 0028, contained: the results are rewritten on the ordinary terminal.

    A full-screen interface clears the screen when it exits, so anything it showed goes
    with it. The three ladder lines therefore belong outside it - which is also why they
    are still the same three lines someone can copy into an issue.
    """
    _open_the_gate(monkeypatch)
    _stub_wizard(monkeypatch, status="completed")

    result = runner.invoke(app, ["add-profile", "dev"], input=f"{_PASSWORD}\n{_PASSWORD}\ny\n")

    assert result.exit_code == 0
    assert "1/3 Conexión: OK" in result.stderr
    assert "2/3 Lectura del catálogo: OK" in result.stderr
    assert "3/3 Visibilidad en PROD: OK" in result.stderr
    assert "los tres niveles han pasado" in result.stderr
    # And the snippet is still payload on stdout, exactly as before.
    assert '"NZ_MCP_PROFILE": "dev"' in result.stdout


def test_cancelling_the_screen_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    _open_the_gate(monkeypatch)
    _stub_wizard(monkeypatch, status="cancelled", types_the_credential=False)

    result = runner.invoke(app, ["add-profile", "dev"], input="")

    assert result.exit_code == 1
    assert "Cancelado" in result.stderr
    assert not tmp_profiles.exists()


def test_shrinking_the_window_falls_back_to_the_questions_without_losing_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The sixth trigger, seen from the command instead of from the application.

    The screen gives back what was typed; those answers become the **defaults** of the
    chained questions, so pressing Enter through them reproduces the same profile. The
    credential is not asked for twice either: it was already given, and re-asking is the
    one thing this wizard promises never to do.
    """
    _open_the_gate(monkeypatch)
    _stub_wizard(monkeypatch, status="degraded")

    # Two lines for the credential the screen collected, then Enter through the eight
    # questions accepting every default, then "y" for the validation.
    answers = f"{_PASSWORD}\n{_PASSWORD}\n" + "\n" * 7 + "y\n"
    result = runner.invoke(app, ["add-profile", "dev"], input=answers)

    assert result.exit_code == 0, result.stderr
    assert "sigo con preguntas" in result.stderr
    profile = get_profile("dev", path=tmp_profiles)
    assert (profile.host, profile.port, profile.database) == ("nz.example.com", 5490, "PROD")
    assert (profile.user, profile.mode, profile.security_level) == ("svc", "write", 3)
    assert profile.ca_certs == "/etc/ssl/nz.pem"
    assert get_password("dev") == _PASSWORD


def test_a_terminal_that_cannot_host_a_screen_never_builds_one(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The most important guarantee of ADR 0028: nobody is left unable to configure.

    With the gate closed, the command is the chained questions it has always been, and the
    application is not merely unused - it is never constructed.
    """
    _close_the_gate(monkeypatch)

    def explode(**_: object) -> WizardResult:
        raise AssertionError("the full-screen wizard was built with the gate closed")

    monkeypatch.setattr(cli, "collect_profile_draft", explode)

    answers = "\n".join(
        ["nz.example.com", "5480", "DB", "svc", _PASSWORD, _PASSWORD, "read", "2", "", "y"]
    )
    result = runner.invoke(app, ["add-profile", "dev"], input=answers + "\n")

    assert result.exit_code == 0, result.stderr
    assert get_profile("dev", path=tmp_profiles).host == "nz.example.com"
    assert get_password("dev") == _PASSWORD


def test_init_and_add_profile_are_the_same_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """ADR 0028 amends the ADR 0005 for one command, and these two are that one command."""
    _open_the_gate(monkeypatch)
    opened = _stub_wizard(monkeypatch, status="completed")

    result = runner.invoke(app, ["init"], input=f"first\n{_PASSWORD}\n{_PASSWORD}\ny\n")

    assert result.exit_code == 0, result.stderr
    assert opened == ["first"]
    assert load_profiles_file(tmp_profiles).active == "first"


#: The nine commands ADR 0028 names one by one as unchanged. ``test-connection`` and
#: ``probe-catalog`` need a profile, so they are given the one this fixture writes.
_TEXT_ONLY_COMMANDS: Final[tuple[tuple[str, ...], ...]] = (
    ("version",),
    ("doctor",),
    ("list-profiles",),
    ("switch-profile", "dev"),
    ("edit-profile", "dev", "--mode", "read"),
    ("remove-profile", "dev"),
    ("test-connection",),
    ("probe-catalog",),
)


@pytest.mark.parametrize("command", _TEXT_ONLY_COMMANDS, ids=lambda c: c[0])
def test_no_other_command_ever_opens_a_screen(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path, command: tuple[str, ...]
) -> None:
    """ "The rest of the commands do not change" - enforced, not asserted in a document.

    The gate is forced **open**, which is the hostile setting: if any of these ever grew an
    interface, this is where it would show. Building one fails the test by name.
    """
    _open_the_gate(monkeypatch)

    def explode(**_: object) -> WizardResult:
        raise AssertionError(f"{command[0]} built a full-screen wizard")

    monkeypatch.setattr(cli, "collect_profile_draft", explode)

    # remove-profile asks for confirmation; answering no is enough to reach the check.
    result = runner.invoke(app, list(command), input="n\n")

    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_the_credential_collector_keeps_what_it_already_had_when_the_prompt_is_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C on the credential prompt returns to the screen; it does not tear it down."""
    holder = cli._CredentialHolder()
    collect = cli._credential_collector(holder, "es")

    monkeypatch.setattr(out, "ask_secret", lambda _prompt: _PASSWORD)
    assert collect() is True
    assert holder.value is not None
    assert holder.value.reveal() == _PASSWORD

    def abort(_prompt: str) -> str:
        raise typer.Abort

    monkeypatch.setattr(out, "ask_secret", abort)
    assert collect() is True, "an abort must not discard the credential already given"


def test_the_credential_collector_reports_nothing_when_it_has_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = cli._CredentialHolder()
    collect = cli._credential_collector(holder, "es")

    def abort(_prompt: str) -> str:
        raise typer.Abort

    monkeypatch.setattr(out, "ask_secret", abort)
    assert collect() is False
    assert holder.value is None
