"""Unit tests for ``catalog.execute`` (inject_limit and execute_select)."""

from __future__ import annotations

from itertools import chain, repeat
from typing import Any

import pytest

from nz_mcp.catalog import execute as execute_mod
from nz_mcp.catalog.execute import execute_select, fetch_explain_text, inject_limit
from nz_mcp.config import Profile


def test_inject_limit_adds_limit_when_missing() -> None:
    out = inject_limit("SELECT a FROM t", 42)
    assert "LIMIT" in out.upper()
    assert "42" in out


def test_inject_limit_lowers_existing_limit() -> None:
    out = inject_limit("SELECT 1 LIMIT 999", 50)
    assert "LIMIT" in out.upper()
    assert "50" in out


def test_inject_limit_union() -> None:
    out = inject_limit("SELECT 1 UNION ALL SELECT 2", 7)
    assert "LIMIT" in out.upper()
    assert "7" in out


def test_inject_limit_not_select_raises() -> None:
    with pytest.raises(ValueError):
        inject_limit("DELETE FROM t WHERE id = 1", 10)


def test_execute_select_streams_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        description = (("n", 23),)

        def __init__(self) -> None:
            self._pos = 0
            self._data: list[tuple[Any, ...]] = [(1,), (2,), (3,)]

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
            start = self._pos
            self._pos = min(len(self._data), self._pos + size)
            return list(self._data[start : self._pos])

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    out = execute_select(profile, "SELECT 1", max_rows=10, timeout_s=30)
    assert out["row_count"] == 3
    assert out["rows"] == [[1], [2], [3]]
    assert out["columns"] == [{"name": "n", "type": "23"}]
    assert out["truncated"] is False
    assert out["hint_key"] is None


def test_execute_select_respects_max_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )
    many = [(i,) for i in range(20)]

    class _Cur:
        description = (("n", 23),)
        _pos = 0

        def __init__(self) -> None:
            self._data = many

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
            start = self._pos
            self._pos = min(len(self._data), self._pos + size)
            return list(self._data[start : self._pos])

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    out = execute_select(profile, "SELECT 1", max_rows=2, timeout_s=30)
    assert out["row_count"] == 2
    assert out["truncated"] is True
    assert out["hint_key"] == "HINT.RESULT_TRUNCATED"


def test_execute_select_bytes_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execute_mod, "RESPONSE_BYTES_CAP", 80)
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )
    fat = "x" * 200

    class _Cur:
        description = (("c", 25),)

        def __init__(self) -> None:
            self._pos = 0
            self._data = [(fat,), (fat,)]

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
            start = self._pos
            self._pos = min(len(self._data), self._pos + size)
            return list(self._data[start : self._pos])

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    out = execute_select(profile, "SELECT 1", max_rows=50, timeout_s=30)
    assert out["truncated"] is True
    assert out["hint_key"] == "HINT.BYTES_CAP_REACHED"


def test_execute_select_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        description = (("n", 23),)

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[tuple[Any, ...]]:
            return [(1,)]

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    _seq = iter(chain((0.0, 9.0e9), repeat(100.0)))

    def _mono() -> float:
        return next(_seq)

    monkeypatch.setattr(execute_mod.time, "monotonic", _mono)

    out = execute_select(profile, "SELECT 1", max_rows=10, timeout_s=1)
    assert out["truncated"] is True
    assert out["hint_key"] == "HINT.EXECUTION_DEADLINE"


def test_fetch_explain_text_concatenates_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        description = (("QUERY PLAN", 25),)

        def __init__(self) -> None:
            self._batches: list[list[tuple[str, ...]]] = [
                [("step1",), ("step2",)],
                [],
            ]
            self._qi = 0

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[tuple[Any, ...]]:
            if self._qi >= len(self._batches):
                return []
            chunk = self._batches[self._qi]
            self._qi += 1
            return list(chunk)

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    text = fetch_explain_text(profile, "EXPLAIN SELECT 1")
    assert "step1" in text and "step2" in text
