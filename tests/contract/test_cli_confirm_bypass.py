"""Contract: the CLI's three ``confirm`` prompts never block a script (cli-redesign gap 1).

``docs/design/cli-redesign-proposal.md`` §2, finding 2, names exactly three blocking yes/no
questions in the whole CLI - ``remove-profile`` (``cli.py``, ``remove_profile_cmd``) and the
wizard's overwrite and validate-before-saving questions (``_confirm_overwrite_or_exit``,
``_validate_before_saving``, both reached from ``init``/``add-profile``) - and none of them
had a way to answer without a terminal. ``--yes``/``-y`` is that way now, and this is the
test that keeps it true: with a closed stdin (what ``CliRunner.invoke`` gives when ``input``
is not passed, and what CI gives every command), each of the three either

- answers itself when ``--yes`` is given, without ever reading a keystroke, or
- fails once, with the translated ``CLI.CONFIRM_NO_TTY`` message and exit code 1 - never the
  framework's generic "Aborted!", and never left waiting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nz_mcp.auth import get_password, store_password
from nz_mcp.cli import app
from nz_mcp.config import list_profile_names, load_profiles_file

runner = CliRunner()


def test_remove_profile_without_yes_and_closed_stdin_fails_with_actionable_message(
    two_profiles: Path,
) -> None:
    result = runner.invoke(app, ["remove-profile", "prod"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "Aborted!" not in combined
    assert "--yes" in combined
    assert list_profile_names(two_profiles) == ["dev", "prod"]


def test_remove_profile_yes_deletes_with_no_stdin_at_all(two_profiles: Path) -> None:
    store_password("prod", "prodpass456")
    result = runner.invoke(app, ["remove-profile", "prod", "--yes"])
    assert result.exit_code == 0
    assert list_profile_names(two_profiles) == ["dev"]


def test_wizard_overwrite_confirm_yes_skips_the_question(two_profiles: Path) -> None:
    """``--yes`` answers the overwrite question without ever printing it - the wizard moves
    straight on to the next thing it needs (the host prompt), which closed stdin still
    cannot answer, so the command still fails, just past the confirm this bypasses.
    """
    result = runner.invoke(app, ["add-profile", "dev", "--yes"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "sobrescrib" not in combined.lower()
    assert "overwrite it" not in combined.lower()


def test_wizard_overwrite_confirm_without_yes_fails_with_actionable_message(
    two_profiles: Path,
) -> None:
    result = runner.invoke(app, ["add-profile", "dev"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "Aborted!" not in combined
    assert "--yes" in combined
    assert load_profiles_file(two_profiles).profiles["dev"]["host"] == "nz-dev.example.com"


def test_wizard_validate_ask_confirm_yes_does_not_block(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """A brand-new profile has no overwrite question - ``--yes`` only has the
    validate-before-saving confirm to answer, and answering it "yes" runs the ladder instead
    of raising, exactly as if a person had typed ``y``.
    """
    from nz_mcp import cli
    from nz_mcp.profile_check import CheckOutcome, ValidationReport
    from nz_mcp.secret import Secret

    draft = cli._ProfileDraft(
        host="nz.example.com",
        port=5480,
        database="DB",
        user="svc",
        password=Secret("pw123456"),
        mode="read",
        security_level=2,
        ca_certs=None,
    )
    monkeypatch.setattr(cli, "_collect_draft", lambda name, previous, locale: draft)

    ran_ladder: list[bool] = []

    def _fake_run_ladder(profile: object, password: object, locale: object) -> ValidationReport:
        ran_ladder.append(True)
        return ValidationReport(outcomes=(CheckOutcome(level="connect", status="ok"),))

    monkeypatch.setattr(cli, "_run_ladder", _fake_run_ladder)

    result = runner.invoke(app, ["add-profile", "new", "--yes"])
    assert result.exit_code == 0
    assert ran_ladder == [True]
    assert get_password("new") == "pw123456"


def test_wizard_yes_saves_anyway_when_the_ladder_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The realistic CI shape: no VPN, the ladder fails - and a fourth prompt used to wait.

    Past "validar antes de guardar?" (answered "yes" by ``--yes``), a failing ladder used to
    fall into ``_prompt_failure_choice`` - "retry, fix a field, save anyway, cancel" - which
    had no ``--yes`` bypass of its own and no closed-stdin guard either: it hit ``typer.ask``
    directly and aborted with the exact generic message this flag exists to avoid. Under
    ``--yes`` a failed ladder must save anyway (the "g" outcome) without ever asking.
    """
    from nz_mcp import cli
    from nz_mcp.profile_check import CheckOutcome, ValidationReport
    from nz_mcp.secret import Secret

    draft = cli._ProfileDraft(
        host="nz.example.com",
        port=5480,
        database="DB",
        user="svc",
        password=Secret("pw123456"),
        mode="read",
        security_level=2,
        ca_certs=None,
    )
    monkeypatch.setattr(cli, "_collect_draft", lambda name, previous, locale: draft)

    def _failing_run_ladder(profile: object, password: object, locale: object) -> ValidationReport:
        return ValidationReport(outcomes=(CheckOutcome(level="connect", status="failed"),))

    monkeypatch.setattr(cli, "_run_ladder", _failing_run_ladder)

    result = runner.invoke(app, ["add-profile", "new", "--yes"])
    assert result.exit_code == 0
    combined = result.stdout + result.stderr
    assert "Aborted" not in combined
    assert get_password("new") == "pw123456"
