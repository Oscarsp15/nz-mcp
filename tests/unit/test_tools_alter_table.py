"""Unit tests for the ``nz_alter_table`` catalog helper and tool handler."""

from __future__ import annotations

from typing import Any, cast

import pytest

from nz_mcp.catalog.alter_table import execute_alter_table
from nz_mcp.config import Profile
from nz_mcp.errors import InvalidInputError, NetezzaError
from nz_mcp.sql_guard import ParsedStatement, StatementKind


def _admin_profile(*, database: str = "DEV") -> Profile:
    return Profile(name="a", host="h", port=5480, database=database, user="u", mode="admin")


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append(sql)

    def close(self) -> None:
        pass


class _RecordingConn:
    def __init__(self) -> None:
        self.cursor_obj = _RecordingCursor()

    def cursor(self) -> _RecordingCursor:
        return self.cursor_obj

    def close(self) -> None:
        pass


class _BoomCursor:
    def execute(self, *_a: object, **_k: object) -> None:
        raise RuntimeError("nz oops")

    def close(self) -> None:
        pass


class _BoomConn:
    def cursor(self) -> _BoomCursor:
        return _BoomCursor()

    def close(self) -> None:
        pass


def _execute(
    profile: Profile,
    *,
    add_columns: list[dict[str, Any]] | None = None,
    set_defaults: list[dict[str, Any]] | None = None,
    drop_defaults: list[str] | None = None,
    rename_columns: list[dict[str, Any]] | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    return execute_alter_table(
        profile,
        database=profile.database,
        schema="PUBLIC",
        table="T",
        add_columns=add_columns or [],
        set_defaults=set_defaults or [],
        drop_defaults=drop_defaults or [],
        rename_columns=rename_columns or [],
        dry_run=dry_run,
        confirm=confirm,
    )


def test_dry_run_groups_add_columns_and_orders_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[object] = []

    def _open(*_a: object) -> None:
        opened.append(True)

    monkeypatch.setattr("nz_mcp.catalog.alter_table.open_connection", _open)
    monkeypatch.setattr("nz_mcp.catalog.alter_table.get_password", lambda _n: "pw")

    out = _execute(
        _admin_profile(),
        add_columns=[
            {"name": "C1", "type": "INTEGER"},
            {"name": "C2", "type": "VARCHAR(10)"},
        ],
        set_defaults=[{"column": "C3", "default": 5}],
        drop_defaults=["C4"],
        rename_columns=[{"from": "C5", "to": "C6"}],
    )

    assert out["dry_run"] is True
    assert out["executed"] is False
    assert out["statements_executed"] == 0
    assert out["statements_to_execute"] == [
        "ALTER TABLE PUBLIC.T ADD COLUMN C1 INTEGER, ADD COLUMN C2 VARCHAR(10)",
        "ALTER TABLE PUBLIC.T ALTER COLUMN C3 SET DEFAULT 5",
        "ALTER TABLE PUBLIC.T ALTER COLUMN C4 DROP DEFAULT",
        "ALTER TABLE PUBLIC.T RENAME COLUMN C5 TO C6",
    ]
    assert opened == []


def test_dry_run_renders_not_null_and_quoted_string_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nz_mcp.catalog.alter_table.open_connection", lambda *_a: _RecordingConn())
    monkeypatch.setattr("nz_mcp.catalog.alter_table.get_password", lambda _n: "pw")

    out = _execute(
        _admin_profile(),
        add_columns=[
            {"name": "N", "type": "VARCHAR(20)", "nullable": False, "default": "hi"},
        ],
    )

    assert out["statements_to_execute"] == [
        "ALTER TABLE PUBLIC.T ADD COLUMN N VARCHAR(20) NOT NULL DEFAULT 'hi'",
    ]


def test_real_execution_requires_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.alter_table.open_connection", lambda *_a: _RecordingConn())
    monkeypatch.setattr("nz_mcp.catalog.alter_table.get_password", lambda _n: "pw")

    with pytest.raises(InvalidInputError) as ei:
        _execute(_admin_profile(), drop_defaults=["C4"], dry_run=False, confirm=False)

    assert ei.value.code == "CONFIRM_REQUIRED"


def test_real_execution_runs_all_statements_on_one_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RecordingConn()
    opened: list[object] = []

    def _open(_p: object, _w: object) -> _RecordingConn:
        opened.append(fake)
        return fake

    monkeypatch.setattr("nz_mcp.catalog.alter_table.open_connection", _open)
    monkeypatch.setattr("nz_mcp.catalog.alter_table.get_password", lambda _n: "pw")

    out = _execute(
        _admin_profile(),
        add_columns=[{"name": "C1", "type": "INTEGER"}],
        set_defaults=[{"column": "C3", "default": "x"}],
        drop_defaults=["C4"],
        rename_columns=[{"from": "C5", "to": "C6"}],
        dry_run=False,
        confirm=True,
    )

    assert out["executed"] is True
    assert out["dry_run"] is False
    assert out["statements_executed"] == 4
    assert out["statements_to_execute"] is None
    assert fake.cursor_obj.executed == [
        "ALTER TABLE PUBLIC.T ADD COLUMN C1 INTEGER",
        "ALTER TABLE PUBLIC.T ALTER COLUMN C3 SET DEFAULT 'x'",
        "ALTER TABLE PUBLIC.T ALTER COLUMN C4 DROP DEFAULT",
        "ALTER TABLE PUBLIC.T RENAME COLUMN C5 TO C6",
    ]
    assert len(opened) == 1


def test_no_operations_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile())


def test_invalid_column_type_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), add_columns=[{"name": "ID", "type": "INTEGER; DROP"}])


def test_execution_failure_wrapped_as_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nz_mcp.catalog.alter_table.open_connection", lambda *_a: _BoomConn())
    monkeypatch.setattr("nz_mcp.catalog.alter_table.get_password", lambda _n: "pw")

    with pytest.raises(NetezzaError):
        _execute(_admin_profile(), drop_defaults=["C4"], dry_run=False, confirm=True)


def test_add_columns_entry_not_a_dict_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), add_columns=cast("list[dict[str, Any]]", [None]))


def test_add_columns_entry_missing_name_or_type_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), add_columns=[{"type": "INTEGER"}])
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), add_columns=[{"name": "C1"}])


def test_set_defaults_entry_missing_column_or_default_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), set_defaults=[{"default": 1}])
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), set_defaults=[{"column": "C1"}])


def test_rename_columns_entry_missing_from_or_to_rejected() -> None:
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), rename_columns=[{"to": "B"}])
    with pytest.raises(InvalidInputError):
        _execute(_admin_profile(), rename_columns=[{"from": "A"}])


def test_guard_non_alter_kind_raises_netezza_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nz_mcp.catalog.alter_table.guard_validate",
        lambda *_a, **_k: ParsedStatement(
            kind=StatementKind.SELECT,
            has_where=False,
            raw="SELECT 1",
        ),
    )

    with pytest.raises(NetezzaError):
        _execute(_admin_profile(), drop_defaults=["C4"])


def test_tool_handler_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from nz_mcp.tools.alter_table import AlterTableInput, AlterTableOutput, nz_alter_table
    from nz_mcp.tools.ddl import ColumnDef

    monkeypatch.setattr(
        "nz_mcp.tools.alter_table.get_active_profile", lambda **_k: _admin_profile()
    )

    out = nz_alter_table(
        AlterTableInput(
            database="DEV",
            table_schema="PUBLIC",
            table="T",
            add_columns=[ColumnDef(name="C1", type="INTEGER")],
        ),
    )

    assert isinstance(out, AlterTableOutput)
    assert out.dry_run is True
    assert out.executed is False
    assert out.statements_executed == 0
    assert out.statements_to_execute == ["ALTER TABLE PUBLIC.T ADD COLUMN C1 INTEGER"]
