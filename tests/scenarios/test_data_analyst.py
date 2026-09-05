"""Role scenario: data analyst landing on an unknown schema (issue #179).

Every identifier used to call a tool comes from the previous tool's answer, verbatim.
That is the point: a listing that returns names a later tool cannot accept is a bug the
per-tool unit suite cannot see.
"""

from __future__ import annotations

import pytest

from tests.scenarios.conftest import ToolSession
from tests.scenarios.netezza_double import FakeColumn, FakeNetezza, FakeTable

pytestmark = pytest.mark.scenario


@pytest.fixture
def warehouse(netezza: FakeNetezza) -> FakeNetezza:
    netezza.add_database("DEV")
    netezza.add_database("PROD")
    netezza.add_schema("DEV", "DBO")
    netezza.add_table(
        "DEV",
        "DBO",
        "CLIENTES",
        FakeTable(
            columns=[
                FakeColumn("ID", "INTEGER", nullable=False),
                FakeColumn("NOMBRE", "CHARACTER VARYING(40)"),
                FakeColumn("SALDO", "NUMERIC(12,2)"),
            ],
            rows=[(1, "ANA", 100), (2, "LUIS", 250), (3, "EVA", 75)],
            distribution=("ID",),
            primary_key=("ID",),
        ),
    )
    netezza.add_table(
        "DEV",
        "DBO",
        "MOVIMIENTOS",
        FakeTable(columns=[FakeColumn("ID", "INTEGER")], rows=[(1,)]),
    )
    return netezza


def test_analyst_explores_and_queries_without_reformatting_names(
    session: ToolSession,
    warehouse: FakeNetezza,
) -> None:
    """Seven tools chained: listing -> describe -> sample -> query -> plan."""
    databases = [item["name"] for item in session.call("nz_list_databases")["databases"]]
    assert "DEV" in databases
    database = databases[databases.index("DEV")]

    schemas = [
        item["name"] for item in session.call("nz_list_schemas", database=database)["schemas"]
    ]
    schema = schemas[0]

    tables = session.call("nz_list_tables", database=database, schema=schema)["tables"]
    names = [item["name"] for item in tables]
    assert names == ["CLIENTES", "MOVIMIENTOS"]
    table = names[0]

    described = session.call(
        "nz_describe_table",
        database=database,
        schema=schema,
        table=table,
    )
    assert described["name"] == table
    columns = [column["name"] for column in described["columns"]]
    assert described["primary_key"] == ["ID"]
    assert described["distribution"]["type"] == "HASH"

    sample = session.call(
        "nz_table_sample",
        database=database,
        schema=schema,
        table=table,
        rows=2,
    )
    # The sample describes the same columns the description announced, in the same order.
    assert [column["name"] for column in sample["columns"]] == columns
    assert sample["row_count"] == 2

    # The query is built from the described column names, untouched.
    projection = ", ".join(columns[:2])
    sql = f"SELECT {projection} FROM {schema}.{table}"
    queried = session.call("nz_query_select", sql=sql, max_rows=3)
    assert [column["name"] for column in queried["columns"]] == columns[:2]
    assert queried["rows"] == [[1, "ANA"], [2, "LUIS"], [3, "EVA"]]

    plan = session.call("nz_explain", sql=sql)
    assert f"{schema}.{table}" in plan["plan"]


def test_analyst_in_read_mode_cannot_write_at_any_point(
    session: ToolSession,
    warehouse: FakeNetezza,
) -> None:
    """Negative walk: the read steps work, the first write step is refused."""
    tables = session.call("nz_list_tables", database="DEV", schema="DBO")["tables"]
    table = tables[0]["name"]

    error = session.error(
        "nz_insert",
        database="DEV",
        schema="DBO",
        table=table,
        rows=[{"ID": 4, "NOMBRE": "MARIO", "SALDO": 10}],
        dry_run=False,
        confirm=True,
    )
    assert error["code"] == "PERMISSION_DENIED"
    assert error["context"] == {"required": "write", "actual": "read"}
    assert session.netezza.statements(starting_with="INSERT") == []
    stored = session.netezza.table("DEV", "DBO", table)
    assert stored is not None
    assert len(stored.rows) == 3, "no row may reach the driver in read mode"
