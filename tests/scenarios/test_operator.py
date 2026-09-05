"""Role scenario: operator moving the session around (issue #179).

Switching profile or database must land on the *next* call, with nothing sticky left
from the previous one. The double records which database each connection was opened
against, so the assertions look at the driver, not only at the tool's own answer.
"""

from __future__ import annotations

import pytest

from tests.scenarios.conftest import ToolSession
from tests.scenarios.netezza_double import FakeColumn, FakeNetezza, FakeTable

pytestmark = pytest.mark.scenario


@pytest.fixture
def two_databases(netezza: FakeNetezza) -> FakeNetezza:
    netezza.add_database("DEV")
    netezza.add_database("PROD")
    netezza.add_schema("DEV", "DBO")
    netezza.add_schema("PROD", "DBO")
    netezza.add_table(
        "DEV",
        "DBO",
        "CLIENTES",
        FakeTable(columns=[FakeColumn("ID", "INTEGER")], rows=[(1,)]),
    )
    netezza.add_table(
        "PROD",
        "DBO",
        "VENTAS",
        FakeTable(columns=[FakeColumn("IMPORTE", "NUMERIC(10,2)")], rows=[(42,)]),
    )
    return netezza


def test_operator_switch_lands_on_the_next_call(
    session: ToolSession,
    two_databases: FakeNetezza,
) -> None:
    """Five tools chained: the session context each one sees is the switched one."""
    current = session.call("nz_current_profile")
    assert current["profile"] == "analyst"
    assert current["database_default"] == "DEV"
    assert "dba" in current["available_profiles"]

    switched = session.call("nz_switch_profile", profile=current["available_profiles"][1])
    assert switched["switched_to"] == "dba"
    after_switch = session.call("nz_current_profile")
    assert after_switch["profile"] == "dba"
    assert after_switch["mode"] == "admin"

    databases = [item["name"] for item in session.call("nz_list_databases")["databases"]]
    assert databases == ["DEV", "PROD"]
    assert session.netezza.connections_opened[-1] == "DEV"

    moved = session.call("nz_switch_database", database=databases[1])
    assert moved["switched_to"] == "PROD"
    assert moved["previous_database"] == "DEV"

    tables = [
        item["name"]
        for item in session.call("nz_list_tables", database="PROD", schema="DBO")["tables"]
    ]
    assert tables == ["VENTAS"]
    # The connection really moved: no stale database left from the previous call.
    assert session.netezza.connections_opened[-1] == "PROD"

    sample = session.call("nz_table_sample", database="PROD", schema="DBO", table=tables[0], rows=1)
    assert sample["row_count"] == 1
    assert session.call("nz_current_profile")["database_default"] == "PROD"


def test_operator_cannot_reach_the_old_database_after_switching(
    session: ToolSession,
    two_databases: FakeNetezza,
) -> None:
    """Negative walk: the session is bound to one database, and the mode still rules."""
    session.call("nz_switch_profile", profile="dba")
    session.call("nz_switch_database", database="PROD")

    stale = session.error("nz_table_sample", database="DEV", schema="DBO", table="CLIENTES", rows=1)
    assert stale["code"] == "INVALID_INPUT"
    assert "PROD" in stale["message_en"]

    session.call("nz_switch_profile", profile="analyst")
    denied = session.error(
        "nz_drop_table",
        database="PROD",
        schema="DBO",
        table="VENTAS",
        confirm=True,
    )
    assert denied["code"] == "PERMISSION_DENIED"
    assert denied["context"] == {"required": "admin", "actual": "read"}
    assert session.netezza.table("PROD", "DBO", "VENTAS") is not None

    unknown = session.error("nz_switch_profile", profile="nope")
    assert unknown["code"] == "PROFILE_NOT_FOUND"
    assert session.call("nz_current_profile")["profile"] == "analyst"
