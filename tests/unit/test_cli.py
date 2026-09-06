"""CLI smoke tests via typer.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nz_mcp import __version__
from nz_mcp.auth import get_password, store_password
from nz_mcp.cli import app
from nz_mcp.config import get_profile, list_profile_names, load_profiles_file
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.errors import CredentialNotFoundError, KeyringUnavailableError

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_list_profiles_empty(tmp_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "sin perfiles" in result.stderr
    assert result.stdout == ""


def test_list_profiles_with_two(two_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "dev" in result.stdout
    assert "prod" in result.stdout


def test_edit_profile_updates_mode(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "dev", "--mode", "write"])
    assert result.exit_code == 0
    assert "Updated" in result.stderr
    from nz_mcp.config import get_profile

    assert get_profile("dev", path=two_profiles).mode == "write"


def test_edit_profile_unknown_exits_1(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "nope", "--mode", "read"])
    assert result.exit_code == 1


def test_edit_profile_invalid_mode_exits_2(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "dev", "--mode", "invalid"])
    assert result.exit_code == 2


def test_edit_profile_no_flags_noop(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "dev"])
    assert result.exit_code == 0
    assert "No changes" in result.stderr


def test_serve_runs_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _fake_run_stdio_server() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("nz_mcp.cli.run_stdio_server", _fake_run_stdio_server)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert called is True


def test_doctor_smoke_ok(two_profiles: Path) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "nz-mcp" in out
    assert "python" in out


def _fail_keyring_backend() -> object:
    from keyring.backends.fail import Keyring as FailKeyring

    return FailKeyring()  # type: ignore[no-untyped-call]


def test_doctor_exit_1_when_keyring_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    import keyring as kr

    monkeypatch.setattr(kr, "get_keyring", _fail_keyring_backend)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1


class _FakeCursor:
    def __init__(self, *, version: str = "NPS 7.2.1-1", fail: bool = False) -> None:
        self._version = version
        self._fail = fail

    def execute(self, _sql: str) -> None:
        if self._fail:
            raise RuntimeError("auth failed password=UltraSecret999")

    def fetchone(self) -> tuple[str]:
        return (self._version,)

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self._fail_execute = fail_execute

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(fail=self._fail_execute)

    def close(self) -> None:
        pass


def test_test_connection_ok(monkeypatch: pytest.MonkeyPatch, two_profiles: Path) -> None:
    store_password("dev", "devpass123")

    def _open(_prof: object, _pwd: str) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _open)
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 0
    assert "OK: connected to" in result.stderr
    assert "NPS 7.2.1-1" in result.stderr
    assert "svc_dev" in result.stderr


def test_test_connection_profile_flag_ok(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    store_password("prod", "prodpass456")

    def _open(_prof: object, _pwd: str) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _open)
    result = runner.invoke(app, ["test-connection", "--profile", "prod"])
    assert result.exit_code == 0
    assert "svc_prod" in result.stderr


def test_test_connection_execute_error_redacts_password(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    store_password("dev", "devpass123")

    monkeypatch.setattr(
        "nz_mcp.profile_check.open_connection", lambda _p, _w: _FakeConn(fail_execute=True)
    )
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "UltraSecret999" not in combined
    assert "FAIL:" in combined


def test_test_connection_profile_not_found(two_profiles: Path) -> None:
    result = runner.invoke(app, ["test-connection", "--profile", "missing"])
    assert result.exit_code == 1


def test_test_connection_credential_not_found(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _no_password(name: str) -> str:
        raise CredentialNotFoundError(profile=name)

    monkeypatch.setattr("nz_mcp.cli.get_password", _no_password)
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 1
    assert "FAIL:" in result.stdout + result.stderr


def test_test_connection_open_connection_error(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    store_password("dev", "devpass123")
    from nz_mcp.errors import ConnectionError as ConnErr

    def _boom(_p: object, _w: str) -> None:
        raise ConnErr(host="h", port=1, database="d", user="u", detail="timeout")

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _boom)
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 1
    assert "timeout" in result.stdout + result.stderr


def test_test_connection_prints_cause_hint(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    """A failure carrying a per-cause hint shows it as its own actionable line."""
    store_password("dev", "devpass123")
    monkeypatch.setenv("NZ_MCP_LANG", "en")

    def _boom(_p: object, _w: str) -> None:
        raise NzConnectionError(
            host="h",
            port=1,
            database="d",
            user="u",
            detail="Error in handshake: hentication failed for user 'U'",
            cause="AUTH_REJECTED",
            hint_es="Netezza rechazó las credenciales.",
            hint_en="Netezza rejected the credentials.",
        )

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", _boom)
    result = runner.invoke(app, ["test-connection"])
    combined = result.stdout + result.stderr

    assert result.exit_code == 1
    assert "HINT: Netezza rejected the credentials." in combined


# --- profile lifecycle: add-profile / remove-profile --------------------------

# host, port, database, user, password x2, mode, security_level, ca_certs (skip),
# and "no" to the pre-save validation (no Netezza reachable from a unit test).
_WIZARD_INPUT = "nz.example.com\n5480\nDB\nsvc\npw123456\npw123456\nread\n2\n\nn\n"


def test_add_profile_creates_it_and_suggests_test_connection(tmp_profiles: Path) -> None:
    result = runner.invoke(app, ["add-profile", "dev", "--active"], input=_WIZARD_INPUT)
    assert result.exit_code == 0
    assert "nz-mcp test-connection --profile dev" in result.stderr
    assert load_profiles_file(tmp_profiles).active == "dev"
    assert get_profile("dev", path=tmp_profiles).host == "nz.example.com"
    assert get_password("dev") == "pw123456"


def test_add_profile_duplicate_declined_keeps_previous(two_profiles: Path) -> None:
    result = runner.invoke(app, ["add-profile", "dev"], input="n\n")
    assert result.exit_code == 1
    assert "nz-mcp remove-profile dev" in result.stdout + result.stderr
    assert get_profile("dev", path=two_profiles).host == "nz-dev.example.com"


def test_add_profile_duplicate_confirmed_replaces_section(two_profiles: Path) -> None:
    result = runner.invoke(app, ["add-profile", "dev"], input="y\n" + _WIZARD_INPUT)
    assert result.exit_code == 0
    assert two_profiles.read_text(encoding="utf-8").count("[profiles.dev]") == 1
    assert list_profile_names(two_profiles) == ["dev", "prod"]
    assert get_profile("dev", path=two_profiles).host == "nz.example.com"
    assert load_profiles_file(two_profiles).active == "dev"


def test_add_profile_reports_unparseable_file(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "en")
    tmp_profiles.write_text(
        '[profiles.dev]\nhost = "a"\n[profiles.dev]\nhost = "b"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["add-profile", "dev"], input=_WIZARD_INPUT)
    assert result.exit_code == 1
    assert "configuration file is invalid" in result.stdout + result.stderr


def test_remove_profile_deletes_section_and_password(two_profiles: Path) -> None:
    store_password("prod", "prodpass456")
    result = runner.invoke(app, ["remove-profile", "prod"], input="y\n")
    assert result.exit_code == 0
    assert list_profile_names(two_profiles) == ["dev"]
    assert load_profiles_file(two_profiles).active == "dev"
    with pytest.raises(CredentialNotFoundError):
        get_password("prod")


def test_remove_profile_clears_active_when_it_was_active(two_profiles: Path) -> None:
    store_password("dev", "devpass123")
    result = runner.invoke(app, ["remove-profile", "dev"], input="y\n")
    assert result.exit_code == 0
    file = load_profiles_file(two_profiles)
    assert file.active is None
    assert list(file.profiles) == ["prod"]
    assert "NZ_MCP_PROFILE" in result.stdout + result.stderr


def test_remove_profile_declined_changes_nothing(two_profiles: Path) -> None:
    store_password("dev", "devpass123")
    result = runner.invoke(app, ["remove-profile", "dev"], input="n\n")
    assert result.exit_code == 1
    assert list_profile_names(two_profiles) == ["dev", "prod"]
    assert get_password("dev") == "devpass123"


def test_remove_profile_unknown_lists_existing_ones(two_profiles: Path) -> None:
    result = runner.invoke(app, ["remove-profile", "ghost"], input="y\n")
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "ghost" in combined
    assert "dev, prod" in combined
    assert list_profile_names(two_profiles) == ["dev", "prod"]


def test_remove_profile_warns_but_proceeds_when_keyring_fails(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    def _boom(name: str) -> None:
        raise KeyringUnavailableError(profile=name, detail="no backend available")

    monkeypatch.setattr("nz_mcp.cli.delete_password", _boom)
    result = runner.invoke(app, ["remove-profile", "prod"], input="y\n")
    assert result.exit_code == 0
    assert list_profile_names(two_profiles) == ["dev"]
    assert "no backend available" in result.stdout + result.stderr


# --- switch-profile -----------------------------------------------------------


def test_switch_profile_sets_the_active_one(two_profiles: Path) -> None:
    result = runner.invoke(app, ["switch-profile", "prod"])
    assert result.exit_code == 0
    assert "prod" in result.stderr
    assert load_profiles_file(two_profiles).active == "prod"


def test_switch_profile_reports_the_granted_mode(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "prod", "--mode", "write"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["switch-profile", "prod"])
    assert result.exit_code == 0
    assert "write" in result.stderr


def test_switch_profile_unknown_lists_existing_ones(two_profiles: Path) -> None:
    result = runner.invoke(app, ["switch-profile", "ghost"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "ghost" in combined
    assert "dev, prod" in combined
    assert load_profiles_file(two_profiles).active == "dev"


def test_switch_profile_reports_unparseable_file(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "en")
    tmp_profiles.write_text('[profiles.dev]\nhost = "a"\nport = "nope"\n', encoding="utf-8")
    result = runner.invoke(app, ["switch-profile", "dev"])
    assert result.exit_code == 1
    assert "configuration file is invalid" in result.stdout + result.stderr
