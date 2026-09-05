"""Unit tests for ``catalog.execute`` (inject_limit and execute_select)."""

from __future__ import annotations

from itertools import chain, repeat
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlglot
from nzpy import ProgrammingError

from nz_mcp.catalog import execute as execute_mod
from nz_mcp.catalog.execute import (
    _column_meta_from_cursor,
    _limit_value_span,
    _type_label_from_oid_cell,
    execute_select,
    fetch_explain_text,
    inject_limit,
)
from nz_mcp.config import Profile
from nz_mcp.errors import GuardRejectedError, NetezzaError


def test_inject_limit_adds_limit_when_missing() -> None:
    out = inject_limit("SELECT a FROM t", 42)
    assert out == "SELECT a FROM t\nLIMIT 42"


def test_inject_limit_lowers_existing_limit() -> None:
    out = inject_limit("SELECT 1 LIMIT 999", 50)
    assert out == "SELECT 1 LIMIT 50"


def test_inject_limit_union() -> None:
    out = inject_limit("SELECT 1 UNION ALL SELECT 2", 7)
    assert out == "SELECT 1 UNION ALL SELECT 2\nLIMIT 7"


def test_inject_limit_not_select_raises() -> None:
    with pytest.raises(ValueError):
        inject_limit("DELETE FROM t WHERE id = 1", 10)


# Issue #137: the executed text must be the text sql_guard validated. Re-serializing the
# sqlglot tree with the postgres dialect rewrote Netezza SQL on its way to the server.
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT NVL(NOMBRE, 'x') AS N FROM DBO.T",
        "SELECT DECODE(ESTADO, 1, 'A', 2, 'B', 'Z') AS E FROM DBO.T",
        "SELECT NVL2(ID, 'a', 'b') AS V FROM DBO.T",
        "SELECT ID FROM DBO.T ORDER BY ID NULLS LAST",
        "SELECT ID FROM DBO.T WHERE regexp_like(NOMBRE, '^A')",
        "SELECT STRPOS(NOMBRE, 'a') AS P FROM DBO.T",
        "SELECT INSTR(NOMBRE, 'a') AS P FROM DBO.T",
        "SELECT LAST_DAY(FECHA) AS V FROM DBO.T",
        "SELECT DATE_PART('year', FECHA) AS V FROM DBO.T",
        "SELECT SUBSTR(NOMBRE, 2, 3) AS V FROM DBO.T",
        "SELECT ID FROM DBO.T WHERE X = 'it''s'",
        'SELECT "MiCol" FROM DBO.T',
    ],
)
def test_inject_limit_preserves_original_statement(sql: str) -> None:
    assert inject_limit(sql, 100) == f"{sql}\nLIMIT 100"


def test_inject_limit_keeps_a_lower_user_limit() -> None:
    """A caller asking for 3 rows must not silently get ``max_rows`` rows."""
    assert inject_limit("SELECT ID FROM DBO.T LIMIT 3", 100) == "SELECT ID FROM DBO.T LIMIT 3"


def test_inject_limit_does_not_duplicate_limit() -> None:
    out = inject_limit("SELECT ID FROM DBO.T LIMIT 999", 100)
    assert out.upper().count("LIMIT") == 1
    assert out == "SELECT ID FROM DBO.T LIMIT 100"


def test_inject_limit_keeps_offset_when_lowering() -> None:
    out = inject_limit("SELECT ID FROM DBO.T LIMIT 999 OFFSET 20", 50)
    assert out == "SELECT ID FROM DBO.T LIMIT 50 OFFSET 20"


def test_inject_limit_replaces_limit_all() -> None:
    out = inject_limit("SELECT ID FROM DBO.T LIMIT ALL", 50)
    assert out == "SELECT ID FROM DBO.T LIMIT 50"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM (SELECT b FROM t LIMIT 5) x",
        "WITH c AS (SELECT b FROM t LIMIT 5) SELECT * FROM c",
    ],
)
def test_inject_limit_ignores_limit_inside_parentheses(sql: str) -> None:
    assert inject_limit(sql, 10) == f"{sql}\nLIMIT 10"


def test_inject_limit_keeps_limit_zero() -> None:
    """``LIMIT 0`` asks for the column metadata only; it is already under any cap."""
    assert inject_limit("SELECT ID FROM DBO.T LIMIT 0", 100) == "SELECT ID FROM DBO.T LIMIT 0"


# A LIMIT whose value is not one integer token cannot be bounded by an in-place rewrite:
# the span would have to guess where the expression ends, which produced the malformed
# "SELECT a FROM t LIMIT 101+2)" for "LIMIT (1+2)".
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t LIMIT (1+2)",
        "SELECT a FROM t LIMIT (1 + 2)",
        "SELECT a FROM t LIMIT (SELECT 5)",
        "SELECT a FROM t LIMIT $1",
        "SELECT a FROM t LIMIT NULL",
        "SELECT a FROM t LIMIT 1e2",
        "SELECT a FROM t LIMIT 3.0",
        "SELECT a FROM t LIMIT 2, 5",
        "SELECT 1 UNION ALL SELECT 2 LIMIT (1+2)",
    ],
)
def test_inject_limit_rejects_a_non_literal_limit(sql: str) -> None:
    with pytest.raises(GuardRejectedError) as excinfo:
        inject_limit(sql, 10)
    assert excinfo.value.code == "LIMIT_NOT_A_LITERAL"


def test_inject_limit_never_returns_malformed_sql_for_a_computed_limit() -> None:
    """Regression: the rewrite used to eat the opening parenthesis and leave the rest."""
    with pytest.raises(GuardRejectedError):
        inject_limit("SELECT a FROM t LIMIT (1+2)", 10)


def test_inject_limit_rejects_mysql_style_offset_comma_count() -> None:
    """``LIMIT 2, 5`` returns 5 rows, not 2: reading the first token would under-count."""
    with pytest.raises(GuardRejectedError):
        inject_limit("SELECT a FROM t LIMIT 2, 5", 3)


def test_limit_value_span_rejects_a_limit_with_nothing_after_it() -> None:
    """Defensive: ``parse_one`` rejects ``... LIMIT`` first, but the helper must not index
    past the end of the token list."""
    tokens = sqlglot.tokenize("SELECT a FROM t LIMIT", read="postgres")
    with pytest.raises(GuardRejectedError):
        _limit_value_span(tokens, len(tokens) - 1, None)


def test_limit_value_span_rejects_a_value_the_tree_does_not_back() -> None:
    """Only ``LIMIT ALL`` may carry a value token with no row count in the parse tree."""
    tokens = sqlglot.tokenize("SELECT a FROM t LIMIT 5", read="postgres")
    with pytest.raises(GuardRejectedError):
        _limit_value_span(tokens, len(tokens) - 2, None)


def test_inject_limit_drops_trailing_semicolon_before_appending() -> None:
    assert inject_limit("SELECT a FROM t ;", 10) == "SELECT a FROM t\nLIMIT 10"


def test_inject_limit_keeps_trailing_semicolon_when_it_touches_nothing() -> None:
    """Nothing to bound, nothing to edit: the text must travel byte for byte."""
    sql = "SELECT a FROM t LIMIT 3  ;  \n"
    assert inject_limit(sql, 100) == sql


def test_inject_limit_keeps_trailing_semicolon_when_lowering() -> None:
    assert inject_limit("SELECT a FROM t LIMIT 999;", 100) == "SELECT a FROM t LIMIT 100;"


def test_inject_limit_appends_on_a_new_line_after_a_line_comment() -> None:
    """A trailing ``--`` comment would swallow a ``LIMIT`` appended on the same line."""
    out = inject_limit("SELECT a FROM t -- why\n", 10)
    assert out.splitlines()[-1] == "LIMIT 10"


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
