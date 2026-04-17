"""Unit tests for ``diagnostic.collect_diagnostic`` (no Netezza, no secrets in output)."""

from __future__ import annotations

from pathlib import Path

import keyring
import pytest
from keyring.backends.fail import Keyring as FailKeyring

from nz_mcp import __version__
from nz_mcp.diagnostic import collect_diagnostic, format_diagnostic_report, report_json_for_audit


def test_collect_happy_two_profiles(two_profiles: Path) -> None:
    report = collect_diagnostic()
    assert report.profiles_count == 2
    assert set(report.profiles_names) == {"dev", "prod"}
    assert report.active_profile == "dev"
    assert report.profiles_load_ok is True
    assert report.nz_mcp_version == __version__
    assert report.locale in ("es", "en")
    assert report.profiles_path_exists is True


def test_collect_no_profiles(tmp_profiles: Path) -> None:
    report = collect_diagnostic()
    assert report.profiles_count == 0
    assert report.profiles_names == ()
    assert report.profiles_path_exists is False
    assert report.active_profile is None


def test_json_audit_excludes_sensitive_payload(two_profiles: Path) -> None:
    """Profile TOML contains host/user — they must not appear in the diagnostic JSON."""
    raw = report_json_for_audit(collect_diagnostic())
    forbidden = (
        "nz-dev.example.com",
        "nz-prod.example.com",
        "svc_dev",
        "svc_prod",
    )
    for bad in forbidden:
        assert bad not in raw, f"unexpected substring: {bad!r}"


def _fail_keyring_backend() -> object:
    return FailKeyring()  # type: ignore[no-untyped-call]


def test_keyring_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path) -> None:
    monkeypatch.setattr(keyring, "get_keyring", _fail_keyring_backend)
    report = collect_diagnostic()
    assert report.keyring_available is False
    assert report.is_healthy is False


def test_invalid_profiles_toml(tmp_profiles: Path) -> None:
    tmp_profiles.write_text("not valid {{{", encoding="utf-8")
    report = collect_diagnostic()
    assert report.profiles_load_ok is False


def test_format_shows_critical_when_unhealthy(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    monkeypatch.setattr(keyring, "get_keyring", _fail_keyring_backend)
    report = collect_diagnostic()
    text = format_diagnostic_report(report, locale="en")
    assert "Critical issues" in text
    assert "keyring" in text.lower()
