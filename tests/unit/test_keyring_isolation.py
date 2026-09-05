"""The autouse keyring isolation must never leak to unit tests.

Integration tests are the single exemption (issue #190): they need a real credential to
reach a real Netezza. These tests pin the exact conditions of that exemption and prove a
unit test cannot fall into it, not even with ``NZ_MCP_RUN_INTEGRATION=1`` exported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import keyring
import pytest

from nz_mcp.auth import SERVICE
from tests.conftest import (
    INTEGRATION_DIR,
    RUN_INTEGRATION_ENV,
    _readonly_real_keyring,
    _uses_real_keyring,
)


class _FakeNode:
    """Minimal stand-in for ``request.node``: marker lookup plus module path."""

    def __init__(self, *, marked: bool, path: Path) -> None:
        self._marked = marked
        self.path = path

    def get_closest_marker(self, name: str) -> object | None:
        return object() if (self._marked and name == "integration") else None


class _FakeRequest:
    def __init__(self, node: _FakeNode) -> None:
        self.node = node


def _request(*, marked: bool, path: Path) -> Any:
    return _FakeRequest(_FakeNode(marked=marked, path=path))


_INSIDE = INTEGRATION_DIR / "test_real_list_databases.py"
_OUTSIDE = INTEGRATION_DIR.parent / "unit" / "test_keyring_isolation.py"


def test_real_keyring_needs_env_marker_and_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUN_INTEGRATION_ENV, "1")
    assert _uses_real_keyring(_request(marked=True, path=_INSIDE)) is True


@pytest.mark.parametrize(
    ("env", "marked", "path"),
    [
        (None, True, _INSIDE),  # opt-in missing
        ("0", True, _INSIDE),  # opt-in not exactly "1"
        ("1", False, _INSIDE),  # not marked as integration
        ("1", True, _OUTSIDE),  # marked, but living outside tests/integration/
    ],
)
def test_real_keyring_denied_unless_every_condition_holds(
    monkeypatch: pytest.MonkeyPatch,
    env: str | None,
    marked: bool,
    path: Path,
) -> None:
    if env is None:
        monkeypatch.delenv(RUN_INTEGRATION_ENV, raising=False)
    else:
        monkeypatch.setenv(RUN_INTEGRATION_ENV, env)
    assert _uses_real_keyring(_request(marked=marked, path=path)) is False


def test_unit_test_reads_an_empty_in_memory_keyring() -> None:
    """End to end: an unmarked test sees the in-memory store, never the OS keyring."""
    keyring.set_password(SERVICE, "profile:only-in-memory", "not-a-real-secret")
    assert keyring.get_password(SERVICE, "profile:only-in-memory") == "not-a-real-secret"
    assert keyring.get_password(SERVICE, "profile:never-stored-anywhere") is None


def test_integration_mode_blocks_writes_to_the_real_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _readonly_real_keyring(monkeypatch)
    with pytest.raises(AssertionError, match="must not write to the real keyring"):
        keyring.set_password(SERVICE, "profile:x", "not-a-real-secret")
    with pytest.raises(AssertionError, match="must not write to the real keyring"):
        keyring.delete_password(SERVICE, "profile:x")
