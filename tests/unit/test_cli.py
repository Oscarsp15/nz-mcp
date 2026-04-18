"""CLI smoke tests via typer.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nz_mcp import __version__
from nz_mcp.auth import store_password
from nz_mcp.cli import app
from nz_mcp.errors import CredentialNotFoundError

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_list_profiles_empty(tmp_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "sin perfiles" in result.stdout


def test_list_profiles_with_two(two_profiles: Path) -> None:
    result = runner.invoke(app, ["list-profiles"])
    assert result.exit_code == 0
    assert "dev" in result.stdout
    assert "prod" in result.stdout


def test_edit_profile_updates_mode(two_profiles: Path) -> None:
    result = runner.invoke(app, ["edit-profile", "dev", "--mode", "write"])
    assert result.exit_code == 0
    assert "Updated" in result.stdout
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
    assert "No changes" in result.stdout


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

    monkeypatch.setattr("nz_mcp.cli.open_connection", _open)
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 0
    assert "OK: connected to" in result.stdout
    assert "NPS 7.2.1-1" in result.stdout
    assert "svc_dev" in result.stdout


def test_test_connection_profile_flag_ok(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    store_password("prod", "prodpass456")

    def _open(_prof: object, _pwd: str) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr("nz_mcp.cli.open_connection", _open)
    result = runner.invoke(app, ["test-connection", "--profile", "prod"])
    assert result.exit_code == 0
    assert "svc_prod" in result.stdout


def test_test_connection_execute_error_redacts_password(
    monkeypatch: pytest.MonkeyPatch, two_profiles: Path
) -> None:
    store_password("dev", "devpass123")

    monkeypatch.setattr("nz_mcp.cli.open_connection", lambda _p, _w: _FakeConn(fail_execute=True))
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

    monkeypatch.setattr("nz_mcp.cli.open_connection", _boom)
    result = runner.invoke(app, ["test-connection"])
    assert result.exit_code == 1
    assert "timeout" in result.stdout + result.stderr
