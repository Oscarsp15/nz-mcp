"""update_check: the startup notice, its cache, its silence and its stderr-only output."""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from nz_mcp import __version__, update_check
from nz_mcp.i18n import Locale


class _Response:
    """Minimal stand-in for the ``urlopen`` context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _payload(*versions: str) -> dict[str, object]:
    return {"info": {"version": versions[-1]}, "releases": {version: [] for version in versions}}


def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NZ_MCP_HOME", str(tmp_path))


# --- version parsing ----------------------------------------------------------


def test_parse_latest_orders_prereleases_by_pep440() -> None:
    """``0.1.0a10`` is newer than ``0.1.0a4``; a lexicographic compare says the opposite."""
    assert update_check._parse_latest(_payload("0.1.0a4", "0.1.0a10", "0.1.0a3")) == "0.1.0a10"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "0.1.0",
        42,
        {},
        {"releases": "not-a-mapping"},
        {"info": {"version": 3}},
        {"releases": {"not a version": []}},
    ],
)
def test_parse_latest_ignores_unusable_payloads(payload: object) -> None:
    assert update_check._parse_latest(payload) is None


def test_parse_latest_accepts_info_version_without_releases() -> None:
    assert update_check._parse_latest({"info": {"version": "0.2.0"}}) == "0.2.0"


# --- the notice itself --------------------------------------------------------


@pytest.mark.parametrize(
    ("installer", "expected"),
    [
        ("uv", "uv tool upgrade nz-mcp"),
        ("pipx", "pipx upgrade nz-mcp --pip-args=--pre"),
        ("pip", "pip install --upgrade --pre nz-mcp"),
    ],
)
def test_update_notice_names_the_command_of_the_detected_installer(
    installer: update_check.Installer, expected: str
) -> None:
    notice = update_check.update_notice("0.1.0a3", "0.1.0a4", "en", installer)
    assert notice is not None
    assert "0.1.0a4" in notice
    assert "0.1.0a3" in notice
    assert expected in notice


@pytest.mark.parametrize(
    ("executable", "prefix", "expected"),
    [
        (
            r"C:\Users\x\AppData\Local\uv\tools\nz-mcp\Scripts\python.exe",
            r"C:\Users\x\AppData\Local\uv\tools\nz-mcp",
            "uv",
        ),
        ("/home/x/.local/share/uv/tools/nz-mcp/bin/python", "/home/x", "uv"),
        (
            "/home/x/.local/pipx/venvs/nz-mcp/bin/python",
            "/home/x/.local/pipx/venvs/nz-mcp",
            "pipx",
        ),
        (
            r"C:\Users\x\AppData\Local\pipx\venvs\nz-mcp\Scripts\python.exe",
            r"C:\Users\x\AppData\Local\pipx\venvs\nz-mcp",
            "pipx",
        ),
        (r"C:\venv\Scripts\python.exe", r"C:\venv", "pip"),
        ("/usr/bin/python3", "/usr", "pip"),
        ("/home/x/uv-projects/tools/bin/python", "/home/x/uv-projects/tools", "pip"),
    ],
)
def test_detect_installer_from_its_own_paths(
    executable: str, prefix: str, expected: str
) -> None:
    """The manager is read from the paths, so the notice never names the wrong tool."""
    assert update_check.detect_installer(executable, prefix) == expected


@pytest.mark.parametrize("latest", ["0.1.0a4", "0.1.0a2", None])
def test_update_notice_is_silent_without_a_newer_version(latest: str | None) -> None:
    assert update_check.update_notice("0.1.0a4", latest, "en") is None


def test_update_notice_is_silent_on_an_unparseable_version() -> None:
    assert update_check.update_notice("0.1.0a4", "not-a-version", "en") is None


@pytest.mark.parametrize("locale", ["es", "en"])
def test_update_notice_renders_in_both_locales(locale: Locale) -> None:
    notice = update_check.update_notice("0.1.0a3", "0.1.0a4", locale)
    assert notice is not None
    assert "nz-mcp" in notice
    assert "0.1.0a4" in notice


# --- stderr only: stdout is the MCP protocol channel --------------------------


def test_the_notice_goes_to_stderr_and_never_to_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One line, on stderr. A byte on stdout would corrupt ``serve``'s JSON-RPC."""
    monkeypatch.delenv(update_check.NO_UPDATE_CHECK_ENV, raising=False)
    monkeypatch.setattr(update_check, "latest_version", lambda **_: "0.1.0a9")
    monkeypatch.setattr(update_check, "installed_version", lambda: "0.1.0a1")

    update_check.run_update_check(locale="en")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "0.1.0a9" in captured.err
    assert captured.err.count("\n") == 1


# --- silence on every failure -------------------------------------------------


def test_a_network_failure_is_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.delenv(update_check.NO_UPDATE_CHECK_ENV, raising=False)

    def _offline(*_args: Any, **_kwargs: Any) -> _Response:
        raise OSError("offline")

    monkeypatch.setattr(update_check, "urlopen", _offline)

    update_check.run_update_check(locale="en")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_a_non_json_body_is_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.delenv(update_check.NO_UPDATE_CHECK_ENV, raising=False)
    monkeypatch.setattr(
        update_check, "urlopen", lambda *_a, **_k: _Response(b"<html>maintenance</html>")
    )

    update_check.run_update_check(locale="en")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# --- opt-out ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "disabled"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
    ],
)
def test_opt_out_spellings(monkeypatch: pytest.MonkeyPatch, value: str, disabled: bool) -> None:
    monkeypatch.setenv(update_check.NO_UPDATE_CHECK_ENV, value)
    assert update_check._disabled() is disabled


def test_opt_out_skips_the_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _isolated_home(monkeypatch, tmp_path)
    monkeypatch.setenv(update_check.NO_UPDATE_CHECK_ENV, "1")

    def _forbidden(*_args: Any, **_kwargs: Any) -> _Response:
        raise AssertionError("the opt-out must prevent any network call")

    monkeypatch.setattr(update_check, "urlopen", _forbidden)

    update_check.run_update_check(locale="en")
    update_check.start_update_check()

    assert capsys.readouterr().err == ""


# --- cache --------------------------------------------------------------------


def test_cache_avoids_a_second_fetch(tmp_path: Path) -> None:
    path = tmp_path / "update-check.json"
    calls: list[int] = []

    def _fetch() -> str | None:
        calls.append(1)
        return "0.1.0a5"

    assert update_check.latest_version(now=1_000.0, cache_path=path, fetch=_fetch) == "0.1.0a5"
    assert update_check.latest_version(now=1_060.0, cache_path=path, fetch=_fetch) == "0.1.0a5"
    assert len(calls) == 1


def test_cache_expires_after_the_ttl(tmp_path: Path) -> None:
    path = tmp_path / "update-check.json"
    calls: list[int] = []

    def _fetch() -> str | None:
        calls.append(1)
        return "0.1.0a6"

    update_check.latest_version(now=1_000.0, cache_path=path, fetch=_fetch)
    update_check.latest_version(
        now=1_000.0 + update_check._CACHE_TTL_S + 1, cache_path=path, fetch=_fetch
    )

    assert len(calls) == 2


def test_a_corrupt_cache_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "update-check.json"
    path.write_text("{not json", encoding="utf-8")
    calls: list[int] = []

    def _fetch() -> str | None:
        calls.append(1)
        return "0.1.0a7"

    assert update_check.latest_version(now=1.0, cache_path=path, fetch=_fetch) == "0.1.0a7"
    assert len(calls) == 1


def test_a_cache_that_cannot_be_written_is_not_an_error(tmp_path: Path) -> None:
    """A read-only config directory must not turn the courtesy check into a failure."""
    blocked = tmp_path / "update-check.json"
    blocked.write_text("a file where the parent directory should be", encoding="utf-8")

    assert (
        update_check.latest_version(now=1.0, cache_path=blocked / "child.json", fetch=lambda: "x")
        == "x"
    )


def test_a_cached_none_is_respected(tmp_path: Path) -> None:
    path = tmp_path / "update-check.json"
    path.write_text(json.dumps({"checked_at": 1_000.0, "latest": None}), encoding="utf-8")

    def _fetch() -> str | None:
        raise AssertionError("a fresh cache must prevent the network call")

    assert update_check.latest_version(now=1_060.0, cache_path=path, fetch=_fetch) is None


# --- installed version --------------------------------------------------------


def test_installed_version_falls_back_to_the_package_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_name: str) -> str:
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _missing)

    assert update_check.installed_version() == __version__
