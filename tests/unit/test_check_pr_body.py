"""Tests for scripts/check_pr_body.py.

Imports the script via importlib to avoid adding it to the package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_pr_body.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_pr_body", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_check_pr_body"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
_REQUIRED = _mod.REQUIRED_HEADINGS


def _full_body() -> str:
    return "\n\n".join(f"{h}\ncontenido\n" for h in _REQUIRED)


def test_full_template_passes() -> None:
    missing = _mod.missing_headings(_full_body())
    assert missing == []


@pytest.mark.parametrize("heading", list(_REQUIRED))
def test_each_missing_heading_detected(heading: str) -> None:
    body = "\n\n".join(f"{h}\ncontenido\n" for h in _REQUIRED if h != heading)
    missing = _mod.missing_headings(body)
    assert missing == [heading]


def test_empty_body_lists_all() -> None:
    missing = _mod.missing_headings("")
    assert missing == list(_REQUIRED)


def test_body_with_only_closes_fails() -> None:
    body = "Closes #13\n\nImplementa la tool doctor."
    missing = _mod.missing_headings(body)
    assert missing == list(_REQUIRED)


def test_heading_must_appear_verbatim() -> None:
    """Substring/normalized match is NOT accepted — the template uses exact text."""
    body = "# Que cambia?\n# Issue\n# Accion"
    missing = _mod.missing_headings(body)
    assert missing == list(_REQUIRED)


def test_case_sensitive_accents() -> None:
    """Accents count. `Que cambia` (sin acento) NO debe pasar por `¿Qué cambia?`."""
    body = "## Que cambia?\ncontenido\n\n" + "\n\n".join(
        f"{h}\ncontenido\n" for h in _REQUIRED[1:]
    )
    missing = _mod.missing_headings(body)
    assert "## ¿Qué cambia?" in missing


def test_cli_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_BODY", _full_body())
    assert _mod.main() == 0


def test_cli_missing_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PR_BODY", "Closes #1")
    assert _mod.main() == 1
    err = capsys.readouterr().err
    assert "estructura mínima" in err
    for heading in _REQUIRED:
        assert heading in err


def test_cli_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PR_BODY", raising=False)
    assert _mod.main() == 1
