"""Unit tests for ``catalog.execute`` (inject_limit and execute_select)."""

from __future__ import annotations

from itertools import chain, repeat
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nzpy import ProgrammingError

from nz_mcp.catalog import execute as execute_mod
from nz_mcp.catalog.execute import (
    _column_meta_from_cursor,
    _type_label_from_oid_cell,
    execute_select,
    fetch_explain_text,
    inject_limit,
)
from nz_mcp.config import Profile
from nz_mcp.errors import NetezzaError


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
    assert out["columns"] == [{"name": "n", "type": "integer"}]
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
    assert out["hint_key"] == "HINT.RESULT_TRUNCATED_BY_ROWS"


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
    assert out["hint_key"] == "HINT.RESULT_TRUNCATED_BY_BYTES"


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

    monkeypatch.setattr(execute_mod, "time", SimpleNamespace(monotonic=_mono))

    out = execute_select(profile, "SELECT 1", max_rows=10, timeout_s=1)
    assert out["truncated"] is True
    assert out["hint_key"] == "HINT.RESULT_TRUNCATED_BY_TIMEOUT"


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


def test_fetch_explain_falls_back_to_cursor_notices(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        notices: list[str]

        def __init__(self) -> None:
            self.notices = ["Seq Scan on t", "  Cost: 0"]

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[tuple[Any, ...]]:
            raise ProgrammingError("no result set")

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
    assert "Seq Scan" in text


def test_column_meta_maps_oid_int_to_name() -> None:
    class _C:
        description = (("c", 1043),)

    meta = _column_meta_from_cursor(cast(Any, _C()))
    assert meta == [{"name": "c", "type": "varchar"}]


def test_column_meta_empty_description() -> None:
    class _C:
        description = None

    assert _column_meta_from_cursor(cast(Any, _C())) == []


def test_column_meta_non_sequence_and_single_part_descriptors() -> None:
    class _C:
        description = (123, ("only",))

    meta = _column_meta_from_cursor(cast(Any, _C()))
    assert meta == [{"name": "123", "type": "unknown"}, {"name": "only", "type": "unknown"}]


def test_column_meta_string_oid_and_unknown_int() -> None:
    class _C:
        description = (("a", "23"), ("b", 99999))

    meta = _column_meta_from_cursor(cast(Any, _C()))
    assert meta == [{"name": "a", "type": "integer"}, {"name": "b", "type": "99999"}]


def test_column_meta_null_type_cell() -> None:
    class _C:
        description = (("n", None),)

    meta = _column_meta_from_cursor(cast(Any, _C()))
    assert meta == [{"name": "n", "type": "unknown"}]


def test_type_label_from_oid_cell_fallback() -> None:
    assert _type_label_from_oid_cell("notdigits") == "notdigits"


def test_execute_select_accepts_scalar_fetch_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Driver may yield a non-sequence cell row; normalize to a one-column list."""
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        description = (("x", 23),)
        _done = False

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[Any]:
            if self._done:
                return []
            self._done = True
            return [42]

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
    assert out["rows"] == [[42]]


def test_fetch_explain_empty_when_no_notices(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        def __init__(self) -> None:
            self.notices: list[str] = []

        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[tuple[Any, ...]]:
            raise ProgrammingError("no result set")

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    assert fetch_explain_text(profile, "EXPLAIN SELECT 1") == ""


def test_fetch_explain_wraps_unrelated_programming_error(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Profile(
        name="dev",
        host="h",
        port=5480,
        database="D",
        user="u",
        mode="read",
    )

    class _Cur:
        def execute(self, _sql: str) -> None:
            return None

        def fetchmany(self, _size: int) -> list[tuple[Any, ...]]:
            raise ProgrammingError("permission denied for explain")

        def close(self) -> None:
            return None

    class _Conn:
        def cursor(self) -> _Cur:
            return _Cur()

        def close(self) -> None:
            return None

    monkeypatch.setattr(execute_mod, "get_password", lambda _n: "pw")
    monkeypatch.setattr(execute_mod, "open_connection", lambda _p, _pw: _Conn())

    with pytest.raises(NetezzaError) as exc:
        fetch_explain_text(profile, "EXPLAIN SELECT 1")

    assert exc.value.context.get("operation") == "explain"
