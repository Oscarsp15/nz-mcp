"""connection.py — stub raises NOT_IMPLEMENTED in v0.1.0a0."""
from __future__ import annotations

import pytest

from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import ConnectionError as NzConnectionError


def test_open_connection_raises_not_implemented() -> None:
    profile = Profile(
        name="x",
        host="h",
        port=5480,
        database="DB",
        user="u",
        mode="read",
    )
    with pytest.raises(NzConnectionError) as exc:
        open_connection(profile, "pw")
    assert exc.value.code == "NOT_IMPLEMENTED"
