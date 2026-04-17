"""Security tests for cross-database identifier interpolation."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nz_mcp.catalog.identifier import render_cross_db, validate_database_identifier
from nz_mcp.errors import InvalidInputError

_VALIDATED_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("PROD", "PROD"),
        ("DESA_MODELOS", "DESA_MODELOS"),
        ("A1", "A1"),
        ("MYDB_2024", "MYDB_2024"),
        ("desa_modelos", "DESA_MODELOS"),
    ],
)
def test_validate_database_identifier_accepts_valid_values(name: str, expected: str) -> None:
    assert validate_database_identifier(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "1DB",
        "DB;DROP TABLE",
        "DB--",
        "my db",
        'D".."',
        "",
        "A" * 129,
        "ÑAÑO",
        "SYS.TBL",
        "-DB",
    ],
)
def test_validate_database_identifier_rejects_adversarial_values(name: str) -> None:
    with pytest.raises(InvalidInputError) as exc:
        validate_database_identifier(name)
    assert exc.value.code == "INVALID_DATABASE_NAME"


def test_render_cross_db_replaces_all_markers() -> None:
    sql = "SELECT * FROM <BD>.._V_TABLE t JOIN <BD>.._V_SCHEMA s ON t.SCHEMA=s.SCHEMA"
    rendered = render_cross_db(sql, "desa_modelos")
    assert "<BD>" not in rendered
    assert rendered.count("DESA_MODELOS..") == 2


def test_render_cross_db_fails_when_marker_is_unresolved() -> None:
    with pytest.raises(InvalidInputError) as exc:
        render_cross_db("SELECT * FROM <BD>_V_TABLE", "PROD")
    assert exc.value.code == "INVALID_DATABASE_NAME"


@given(st.text())
def test_validate_database_identifier_matches_security_regex(raw_name: str) -> None:
    normalized = raw_name.strip().upper()
    is_valid = _VALIDATED_PATTERN.fullmatch(normalized) is not None
    if is_valid:
        assert validate_database_identifier(raw_name) == normalized
    else:
        with pytest.raises(InvalidInputError) as exc:
            validate_database_identifier(raw_name)
        assert exc.value.code == "INVALID_DATABASE_NAME"
