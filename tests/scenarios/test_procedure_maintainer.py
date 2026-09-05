"""Role scenario: procedure maintainer (issue #179).

The walk the owner does by hand: find a procedure, size it, read its DDL, hit the
truncation cap, **follow the hint literally** and continue with
``nz_get_procedure_section``, then clone it and read the clone back.

Step 4 is the reason this file exists. The hint of ``nz_get_procedure_ddl`` quotes
``from_line`` in ``PROCEDURESOURCE`` numbering, while the DDL the caller is holding has
a rebuilt header on top that ``PROCEDURESOURCE`` does not contain. Both numbering
systems are off by that header, and nothing but this scenario checks that the tool
that emits the hint and the tool that consumes it agree (verified by hand in PR #170).
"""

from __future__ import annotations

import re

import pytest

from tests.scenarios.conftest import ToolSession
from tests.scenarios.netezza_double import FakeNetezza, FakeProcedure

pytestmark = pytest.mark.scenario

# Both locales of HINT.PROCEDURE_DDL_TRUNCATED carry the same call snippet.
_HINT_RANGE = re.compile(r"section='range',\s*from_line=(?P<from>\d+),\s*to_line=(?P<to>\d+)")

_SOURCE_LINES = 140
_PROCEDURE = "SP_CARGA_DIARIA"
_CLONE = "SP_CARGA_DIARIA_BK"


def _body() -> str:
    """A body long enough that the DDL does not fit in the smallest allowed budget."""
    lines = ["DECLARE", "  v_rows INTEGER;", "BEGIN", "  v_rows := 0;"]
    lines += [
        f"  v_rows := v_rows + {i}; -- step {i} of the nightly load"
        for i in range(1, _SOURCE_LINES + 1)
    ]
    lines += ["  RETURN v_rows;", "END;"]
    return "\n".join(lines)


@pytest.fixture
def source(netezza: FakeNetezza) -> str:
    """Seed two procedures and return the body of the big one, as the catalog stores it."""
    netezza.add_database("DEV")
    netezza.add_schema("DEV", "DBO")
    body = _body()
    netezza.add_procedure(
        "DEV",
        "DBO",
        FakeProcedure(
            name=_PROCEDURE,
            arguments="(DATE)",
            returns="INTEGER",
            signature=f"{_PROCEDURE}(DATE)",
            source=body,
        ),
    )
    netezza.add_procedure(
        "DEV",
        "DBO",
        FakeProcedure(
            name="SP_OTRA_COSA",
            arguments="()",
            returns="INTEGER",
            signature="SP_OTRA_COSA()",
            source="BEGIN\n  RETURN 1;\nEND;",
        ),
    )
    return body


def _read_until_truncated(session: ToolSession, procedure: str) -> dict[str, object]:
    return session.call(
        "nz_get_procedure_ddl",
        database="DEV",
        schema="DBO",
        procedure=procedure,
        max_bytes=1024,
    )


def test_maintainer_walk_follows_the_truncation_hint(session: ToolSession, source: str) -> None:
    """Six tools chained; each call uses the previous answer verbatim."""
    listed = session.call("nz_list_procedures", database="DEV", schema="DBO", pattern="SP_CARGA%")
    names = [item["name"] for item in listed["procedures"]]
    assert names == [_PROCEDURE], "the pattern must not drag the second procedure in"
    procedure = names[0]

    size = session.call("nz_get_procedure_size", database="DEV", schema="DBO", procedure=procedure)
    assert size["lines_raw"] > len(source.splitlines())
    assert size["size_bytes_raw"] > 1024

    ddl = _read_until_truncated(session, procedure)
    assert ddl["truncated"] is True
    hint = ddl["hint"]
    assert isinstance(hint, str)
    match = _HINT_RANGE.search(hint)
    assert match is not None, f"hint does not spell out the next call: {hint!r}"
    from_line = int(match.group("from"))
    to_line = int(match.group("to"))

    # The client follows the hint with the exact parameters it was given.
    section = session.call(
        "nz_get_procedure_section",
        database="DEV",
        schema="DBO",
        procedure=procedure,
        section="range",
        from_line=from_line,
        to_line=to_line,
    )

    source_lines = source.splitlines()
    delivered = str(ddl["ddl"]).splitlines()
    # DDL numbering is not source numbering: the rebuilt header is not in
    # PROCEDURESOURCE, so the hint's from_line is short of the delivered line count.
    header_lines = len(delivered) - (from_line - 1)
    assert header_lines >= 2, "the double must reproduce the header skew"
    assert delivered[0].startswith("CREATE OR REPLACE PROCEDURE DBO.")
    # Everything already delivered is exactly source lines 1..from_line-1.
    assert delivered[header_lines:] == source_lines[: from_line - 1]

    got = section["content"].splitlines()
    assert section["from_line"] == from_line
    # No gap and no overlap: the section starts on the first line not delivered.
    assert got[0] == source_lines[from_line - 1]
    assert got == source_lines[from_line - 1 : int(section["to_line"])]


def test_maintainer_clones_and_reads_the_clone_back(session: ToolSession, source: str) -> None:
    """The clone is a catalog object afterwards, readable with the same read tool."""
    listed = session.call("nz_list_procedures", database="DEV", schema="DBO", pattern="SP_CARGA%")
    procedure = listed["procedures"][0]["name"]

    switched = session.call("nz_switch_profile", profile="dba")
    assert switched["mode"] == "admin"

    cloned = session.call(
        "nz_clone_procedure",
        source_database="DEV",
        source_schema="DBO",
        source_procedure=procedure,
        target_database="DEV",
        target_schema="DBO",
        target_procedure=_CLONE,
        dry_run=False,
        confirm=True,
    )
    assert cloned["executed"] is True

    stored = session.netezza.procedure("DEV", "DBO", _CLONE)
    assert stored is not None, "the CREATE never reached the driver"

    clone_ddl = session.call(
        "nz_get_procedure_ddl",
        database="DEV",
        schema="DBO",
        procedure=_CLONE,
    )
    assert clone_ddl["truncated"] is False
    body = str(clone_ddl["ddl"]).split("LANGUAGE NZPLSQL AS\n", 1)[1]
    assert source.strip() in body, "the clone lost part of the body on the round trip"


def test_read_profile_stops_at_the_clone(session: ToolSession, source: str) -> None:
    """Negative walk: reads go through, the write step is refused before any SQL."""
    listed = session.call("nz_list_procedures", database="DEV", schema="DBO", pattern="SP_CARGA%")
    procedure = listed["procedures"][0]["name"]
    ddl = _read_until_truncated(session, procedure)
    assert ddl["truncated"] is True

    error = session.error(
        "nz_clone_procedure",
        source_database="DEV",
        source_schema="DBO",
        source_procedure=procedure,
        target_database="DEV",
        target_schema="DBO",
        target_procedure=_CLONE,
        dry_run=False,
        confirm=True,
    )
    assert error["code"] == "PERMISSION_DENIED"
    assert error["context"]["required"] == "admin"
    assert error["context"]["actual"] == "read"
    assert session.netezza.procedure("DEV", "DBO", _CLONE) is None
    assert session.netezza.statements(starting_with="CREATE") == []
