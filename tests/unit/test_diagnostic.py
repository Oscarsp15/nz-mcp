"""Unit tests for ``diagnostic.collect_diagnostic`` (no Netezza, no secrets in output)."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import keyring
import pytest
from keyring.backends.fail import Keyring as FailKeyring

from nz_mcp import __version__
from nz_mcp.diagnostic import collect_diagnostic, format_diagnostic_report, report_json_for_audit


def test_collect_happy_two_profiles(two_profiles: Path) -> None:
    report = collect_diagnostic(min_width=60, min_height=18)
    assert report.profiles_count == 2
    assert set(report.profiles_names) == {"dev", "prod"}
    assert report.active_profile == "dev"
    assert report.profiles_load_ok is True
    assert report.nz_mcp_version == __version__
    assert report.locale in ("es", "en")
    assert report.profiles_path_exists is True


def test_collect_no_profiles(tmp_profiles: Path) -> None:
    report = collect_diagnostic(min_width=60, min_height=18)
    assert report.profiles_count == 0
    assert report.profiles_names == ()
    assert report.profiles_path_exists is False
    assert report.active_profile is None


def test_json_audit_excludes_sensitive_payload(two_profiles: Path) -> None:
    """Profile TOML contains host/user — they must not appear in the diagnostic JSON."""
    raw = report_json_for_audit(collect_diagnostic(min_width=60, min_height=18))
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
    report = collect_diagnostic(min_width=60, min_height=18)
    assert report.keyring_available is False
    assert report.is_healthy is False


def test_invalid_profiles_toml(tmp_profiles: Path) -> None:
    tmp_profiles.write_text("not valid {{{", encoding="utf-8")
    report = collect_diagnostic(min_width=60, min_height=18)
    assert report.profiles_load_ok is False


def test_format_shows_critical_when_unhealthy(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    monkeypatch.setattr(keyring, "get_keyring", _fail_keyring_backend)
    report = collect_diagnostic(min_width=60, min_height=18)
    text = format_diagnostic_report(report, locale="en")
    assert "Critical issues" in text
    assert "keyring" in text.lower()


def test_terminal_block_reports_level_0_and_its_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """A muted degradation is the bug this block exists for: say the level and the reason."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("NZ_MCP_UI_LEVEL", raising=False)

    report = collect_diagnostic(min_width=60, min_height=18)

    assert report.terminal_level == 0
    assert report.full_screen_blocker is not None
    text = format_diagnostic_report(report, locale="es")
    assert "Nivel del terminal: 0" in text
    assert "ASCII sin color" in text


def test_terminal_block_names_the_forced_level(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """``NZ_MCP_UI_LEVEL=0`` is an escape hatch, and the report has to admit it is on.

    The trigger is forced rather than provoked: under pytest the output is not a terminal,
    so ``no_terminal`` fires first and would hide the one this test is about.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("NZ_MCP_UI_LEVEL", "0")
    monkeypatch.setattr("nz_mcp.diagnostic.interactive_ui_blocker", lambda **_k: "terminal_level_0")

    report = collect_diagnostic(min_width=60, min_height=18)

    assert report.terminal_level == 0
    assert report.full_screen_blocker == "terminal_level_0"
    assert "NZ_MCP_UI_LEVEL=1" in format_diagnostic_report(report, locale="es")


def test_terminal_block_says_full_screen_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The other half of the contract: when nothing blocks, no trigger is named."""
    monkeypatch.setattr("nz_mcp.diagnostic.terminal_level", lambda *_a, **_k: 1)
    monkeypatch.setattr("nz_mcp.diagnostic.interactive_ui_blocker", lambda **_k: None)

    report = collect_diagnostic(min_width=60, min_height=18)

    assert report.terminal_level == 1
    assert report.full_screen_blocker is None
    text = format_diagnostic_report(report, locale="es")
    assert "disponible" in text
    assert "cerrada" not in text


def test_terminal_block_reports_a_window_that_is_too_small(
    monkeypatch: pytest.MonkeyPatch, tmp_profiles: Path
) -> None:
    """The trigger a reader can act on in one second, so it must name the window."""
    monkeypatch.setattr("nz_mcp.diagnostic.terminal_level", lambda *_a, **_k: 1)
    monkeypatch.setattr("nz_mcp.diagnostic.interactive_ui_blocker", lambda **_k: "window_too_small")

    report = collect_diagnostic(min_width=60, min_height=18)

    assert "demasiado pequena" in format_diagnostic_report(report, locale="es")
    assert "too small" in format_diagnostic_report(report, locale="en")


def test_every_blocker_has_its_own_text_in_both_languages() -> None:
    """No trigger may fall back to a generic line: eight reasons, eight texts, two languages."""
    from nz_mcp.cli_output import InteractiveBlocker
    from nz_mcp.i18n import MESSAGES, t

    blockers = get_args(InteractiveBlocker)
    assert len(blockers) == 8
    seen: set[str] = set()
    for blocker in blockers:
        key = f"DOCTOR.TERMINAL.BLOCKER.{blocker.upper()}"
        assert key in MESSAGES, f"{blocker} has no text"
        for locale in ("es", "en"):
            text = t(key, locale)
            assert text and text != key
            assert text not in seen, f"{blocker} reuses another trigger's text"
            seen.add(text)
