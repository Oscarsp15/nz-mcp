"""i18n catalog tests — parity ES/EN, resolver, and formatting."""

from __future__ import annotations

import pytest

from nz_mcp import i18n
from nz_mcp.i18n import MESSAGES, both, resolve_locale, t


def test_every_message_has_es_and_en() -> None:
    for key, msg in MESSAGES.items():
        assert "es" in msg, f"Missing ES for {key}"
        assert "en" in msg, f"Missing EN for {key}"
        assert msg["es"].strip(), f"Empty ES for {key}"
        assert msg["en"].strip(), f"Empty EN for {key}"


def test_resolve_locale_explicit_wins() -> None:
    assert resolve_locale("es") == "es"
    assert resolve_locale("en") == "en"


def test_resolve_locale_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NZ_MCP_LANG", "es_AR.UTF-8")
    monkeypatch.delenv("LANG", raising=False)
    assert resolve_locale() == "es"


def test_resolve_locale_default_when_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NZ_MCP_LANG", raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert resolve_locale() == i18n.DEFAULT_LOCALE


def test_t_formats_placeholders() -> None:
    text = t("HINT.RESULT_TRUNCATED", "es", n=42)
    assert "42" in text


def test_t_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        t("DOES_NOT_EXIST", "en")


def test_both_returns_both_locales() -> None:
    out = both("HINT.RESULT_TRUNCATED", n=10)
    assert set(out) == {"es", "en"}
    assert "10" in out["es"] and "10" in out["en"]
