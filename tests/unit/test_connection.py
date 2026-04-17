"""Tests for Netezza connection adapter."""

from __future__ import annotations

import pytest

from nz_mcp.config import Profile
from nz_mcp.connection import APPLICATION_NAME, open_connection
from nz_mcp.errors import ConnectionError as NzConnectionError


def _profile() -> Profile:
    return Profile(
        name="dev",
        host="nz-dev.example.com",
        port=5480,
        database="DEV",
        user="svc_dev",
        mode="read",
        timeout_s_default=45,
    )


def test_open_connection_calls_nzpy_with_expected_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()
    test_secret = "".join(["test", "-pw"])

    def _fake_connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _fake_connect)
    result = open_connection(_profile(), test_secret)

    assert result is sentinel
    assert captured["user"] == "svc_dev"
    assert captured["host"] == "nz-dev.example.com"
    assert captured["port"] == 5480
    assert captured["database"] == "DEV"
    assert captured["password"] == test_secret
    assert captured["timeout"] == 45
    assert captured["application_name"] == APPLICATION_NAME
    assert captured["securityLevel"] == 1


def test_open_connection_wraps_driver_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_connect(**_kwargs: object) -> object:
        raise RuntimeError("dial timeout")

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _raise_connect)

    with pytest.raises(NzConnectionError) as exc:
        open_connection(_profile(), "".join(["test", "-pw"]))

    assert exc.value.code == "CONNECTION_FAILED"
    assert exc.value.context["host"] == "nz-dev.example.com"
    assert "dial timeout" in exc.value.context["detail"]
