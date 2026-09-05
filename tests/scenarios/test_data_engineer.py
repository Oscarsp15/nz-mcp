"""Role scenario: data engineer building and dropping a staging table (issue #179).

The chain asserts three things the per-tool suite cannot: the DDL one tool generates is
the DDL the driver receives, the object it creates is the one the next tool finds, and
the ``dry_run`` payload describes exactly what the real execution does.
"""

from __future__ import annotations

import pytest

from tests.scenarios.conftest import ToolSession
from tests.scenarios.netezza_double import FakeColumn, FakeNetezza, FakeTable

pytestmark = pytest.mark.scenario

_STAGING = "STG_CLIENTES"
_COLUMNS = [
    {"name": "ID", "type": "INTEGER", "nullable": False},
    {"name": "NOMBRE", "type": "VARCHAR(40)"},
]


@pytest.fixture
def warehouse(netezza: FakeNetezza) -> FakeNetezza:
    netezza.add_database("DEV")
    netezza.add_schema("DEV", "DBO")
    netezza.add_table(
        "DEV",
        "DBO",
        "CLIENTES",
        FakeTable(
            columns=[
                FakeColumn("ID", "INTEGER", nullable=False),
                FakeColumn("NOMBRE", "CHARACTER VARYING(40)"),
            ],
            rows=[(1, "ANA"), (2, "LUIS"), (3, "EVA")],
        ),
    )
    return netezza


def _count(session: ToolSession, schema: str, table: str) -> int:
    out = session.call("nz_query_select", sql=f"SELECT COUNT(*) AS N FROM {schema}.{table}")
    return int(out["rows"][0][0])


def test_engineer_builds_loads_and_cleans_a_staging_table(
    session: ToolSession,
    warehouse: FakeNetezza,
) -> None:
    """Six tools chained across two profiles; the object survives between calls."""
    assert session.call("nz_switch_profile", profile="dba")["mode"] == "admin"

    planned = session.call(
        "nz_create_table",
        database="DEV",
        schema="DBO",
        table=_STAGING,
        columns=_COLUMNS,
        dry_run=True,
    )
    assert planned["executed"] is False
    assert session.netezza.table("DEV", "DBO", _STAGING) is None

    created = session.call(
        "nz_create_table",
        database="DEV",
        schema="DBO",
        table=_STAGING,
        columns=_COLUMNS,
        dry_run=False,
        confirm=True,
    )
    assert created["executed"] is True
    # The dry run described the execution, and the execution is what the driver saw.
    assert created["ddl_to_execute"] == planned["ddl_to_execute"]
    assert session.netezza.statements(starting_with="CREATE TABLE") == [created["ddl_to_execute"]]

    # The table the DDL created is the one the listing tool now finds, same spelling.
    listed = [
        item["name"]
        for item in session.call("nz_list_tables", database="DEV", schema="DBO")["tables"]
    ]
    assert _STAGING in listed
    target = listed[listed.index(_STAGING)]

    described = session.call("nz_describe_table", database="DEV", schema="DBO", table=target)
    target_columns = [column["name"] for column in described["columns"]]
    assert target_columns == ["ID", "NOMBRE"]

    assert session.call("nz_switch_profile", profile="engineer")["mode"] == "write"
    loaded = session.call(
        "nz_insert_select",
        database="DEV",
        target_schema="DBO",
        target_table=target,
        target_columns=target_columns,
        select_sql=f"SELECT {', '.join(target_columns)} FROM DBO.CLIENTES",
        dry_run=False,
        confirm=True,
    )
    assert loaded["executed"] is True
    assert _count(session, "DBO", target) == 3

    assert session.call("nz_switch_profile", profile="dba")["mode"] == "admin"
    truncated = session.call(
        "nz_truncate",
        database="DEV",
        schema="DBO",
        table=target,
        confirm=True,
    )
    assert truncated["truncated"] is True
    assert _count(session, "DBO", target) == 0

    dropped = session.call(
        "nz_drop_table",
        database="DEV",
        schema="DBO",
        table=target,
        confirm=True,
    )
    assert dropped["dropped"] is True
    remaining = [
        item["name"]
        for item in session.call("nz_list_tables", database="DEV", schema="DBO")["tables"]
    ]
    assert _STAGING not in remaining


def test_read_profile_stops_at_the_first_write_step(
    session: ToolSession,
    warehouse: FakeNetezza,
) -> None:
    """Negative walk: the read step passes, the create is refused before any SQL."""
    listed = session.call("nz_list_tables", database="DEV", schema="DBO")["tables"]
    assert [item["name"] for item in listed] == ["CLIENTES"]

    error = session.error(
        "nz_create_table",
        database="DEV",
        schema="DBO",
        table=_STAGING,
        columns=_COLUMNS,
        dry_run=False,
        confirm=True,
    )
    assert error["code"] == "PERMISSION_DENIED"
    assert error["context"] == {"required": "admin", "actual": "read"}
    assert session.netezza.statements(starting_with="CREATE TABLE") == []
    assert session.netezza.table("DEV", "DBO", _STAGING) is None
