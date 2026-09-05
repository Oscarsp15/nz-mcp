"""Tests for Netezza connection adapter."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence

import pytest

from nz_mcp.config import Profile
from nz_mcp.connection import (
    APPLICATION_NAME,
    CAUSE_AUTH_REJECTED,
    CAUSE_DATABASE_UNAVAILABLE,
    CAUSE_HOST_UNREACHABLE,
    CAUSE_TLS_FAILED,
    CAUSE_UNKNOWN,
    _DriverDiagnosticsHandler,
    classify_connection_failure,
    open_connection,
)
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.i18n import MESSAGES
from nz_mcp.secret import REDACTED, Secret


def _profile(*, security_level: int = 2, ca_certs: str | None = None) -> Profile:
    return Profile(
        name="dev",
        host="nz-dev.example.com",
        port=5480,
        database="DEV",
        user="svc_dev",
        mode="read",
        timeout_s_default=45,
        security_level=security_level,
        ca_certs=ca_certs,
    )


def test_open_connection_sends_the_real_password_when_given_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The driver must receive the credential, not its redacted rendering.

    Regression of 0.1.0a2: ``auth.get_password`` returns a ``Secret`` and this function
    re-binds its argument with ``Secret(password)``, so the real shape is a double wrap.
    ``str.__new__`` renders through ``__str__``, which is redacted, so every connection
    sent ``***`` and Netezza answered AUTH_REJECTED. The suite never caught it because
    every other test passes a plain ``str``.
    """
    captured: dict[str, object] = {}
    test_secret = Secret("".join(["test", "-pw"]))

    def _fake_connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _fake_connect)
    open_connection(_profile(), test_secret)

    sent = captured["password"]
    assert isinstance(sent, Secret)
    assert sent.reveal() == "test-pw"
    assert sent.encode() == b"test-pw"
    # And it still renders redacted, which is the whole point of the wrapper.
    assert str(sent) == REDACTED


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
    # Secure-by-default: profiles that do not set security_level negotiate SSL (preferred).
    assert captured["securityLevel"] == 2
    # Maps to WARNING inside nzpy; lower values flood stderr with per-packet DEBUG
    # that shreds client UIs rendering on stderr (e.g. nz-workbench progress bar).
    assert captured["logLevel"] == 2


def test_open_connection_propagates_profile_security_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _captured_level(security_level: int) -> object:
        captured: dict[str, object] = {}

        def _fake_connect(**kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _fake_connect)
        open_connection(_profile(security_level=security_level), "".join(["test", "-pw"]))
        return captured["securityLevel"]

    # Only-secured (SSL required), as the SaaS instance needs.
    assert _captured_level(3) == 3
    # Cleartext opt-in for a trusted lab network.
    assert _captured_level(1) == 1


def test_open_connection_skips_cert_verification_without_ca_certs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _fake_connect)
    open_connection(_profile(), "".join(["test", "-pw"]))

    # nzpy >=1.17.7 aborts the SSL handshake at security_level 2/3 unless told to skip
    # verification; it is a top-level connect kwarg, not a key of the ``ssl`` dict.
    assert captured["skipCertVerification"] is True
    assert "ssl" not in captured


def test_open_connection_verifies_cert_with_profile_ca_certs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _fake_connect)
    open_connection(_profile(ca_certs="/etc/nz/ca.pem"), "".join(["test", "-pw"]))

    # nzpy reads the CA bundle from ``ssl["ca_certs"]`` and enforces CERT_REQUIRED.
    assert captured["ssl"] == {"ca_certs": "/etc/nz/ca.pem"}
    assert captured["skipCertVerification"] is False


def test_open_connection_sanitizes_known_password_in_driver_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known_pw = "known-test-pw"

    def _raise_with_password(**_kwargs: object) -> object:
        raise RuntimeError(f"connection failed: dsn contains password={known_pw}")

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _raise_with_password)

    with pytest.raises(NzConnectionError) as exc:
        open_connection(_profile(), known_pw)

    detail = exc.value.context["detail"]
    assert known_pw not in detail


def test_open_connection_wraps_driver_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_connect(**_kwargs: object) -> object:
        raise RuntimeError("dial timeout")

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _raise_connect)

    with pytest.raises(NzConnectionError) as exc:
        open_connection(_profile(), "".join(["test", "-pw"]))

    assert exc.value.code == "CONNECTION_FAILED"
    assert exc.value.context["host"] == "nz-dev.example.com"
    assert "dial timeout" in exc.value.context["detail"]


# --- driver diagnostics capture ------------------------------------------------
#
# nzpy raises a generic "Error in handshake" for every handshake failure and logs the
# real reason on its own logger (``nzpy.Connection[<db>}]``), which propagates to
# ``nzpy``. The doubles below reproduce that split: log, then raise the generic error.
# Message texts are the ones observed against a real Netezza 11.2.1.11.

_HANDSHAKE_ERROR = "Error in handshake"
_AUTH_LOG = "Error occured, server response:hentication failed for user 'SVC_DEV' \x00"
_NO_DATABASE_LOG = 'Error occured, server response:FATAL 1:  Database "DEV" does not exist.\n\x00'
_TLS_LOG = "Problem establishing secured session"
_TEST_PW = "".join(["unit", "-test-pw"])


def _connect_double(log_messages: Sequence[str], exception: Exception) -> Callable[..., object]:
    def _fake_connect(**_kwargs: object) -> object:
        logger = logging.getLogger("nzpy.Connection[DEV}]")
        for message in log_messages:
            logger.warning(message)
        raise exception

    return _fake_connect


def _failure(
    monkeypatch: pytest.MonkeyPatch,
    log_messages: Sequence[str],
    exception: Exception,
    *,
    password: str = _TEST_PW,
) -> NzConnectionError:
    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", _connect_double(log_messages, exception))
    with pytest.raises(NzConnectionError) as exc:
        open_connection(_profile(), password)
    return exc.value


def test_detail_reports_rejected_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _failure(
        monkeypatch,
        [_AUTH_LOG, "Error in conn_connection_complete"],
        RuntimeError(_HANDSHAKE_ERROR),
    )

    assert err.context["cause"] == CAUSE_AUTH_REJECTED
    # NUL terminator and nzpy's own prefix are stripped; the server text survives verbatim.
    assert err.context["detail"] == f"{_HANDSHAKE_ERROR}: hentication failed for user 'SVC_DEV'"
    # The nzpy control-flow breadcrumb adds no diagnostic value and is dropped.
    assert "conn_connection_complete" not in err.context["detail"]


def test_detail_reports_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _failure(
        monkeypatch,
        [_NO_DATABASE_LOG, "Error in conn_connection_complete"],
        RuntimeError(_HANDSHAKE_ERROR),
    )

    assert err.context["cause"] == CAUSE_DATABASE_UNAVAILABLE
    assert 'Database "DEV" does not exist.' in err.context["detail"]


def test_detail_reports_unreachable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # No log record at all: the socket never reached the handshake.
    err = _failure(monkeypatch, [], RuntimeError("('communication error', TimeoutError())"))

    assert err.context["cause"] == CAUSE_HOST_UNREACHABLE
    assert "communication error" in err.context["detail"]


def test_detail_reports_tls_negotiation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _failure(
        monkeypatch,
        [_TLS_LOG, "Error in conn_send_handshake_info"],
        RuntimeError(_HANDSHAKE_ERROR),
    )

    assert err.context["cause"] == CAUSE_TLS_FAILED
    assert _TLS_LOG in err.context["detail"]


def test_causes_are_distinguishable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug: two very different failures used to yield the very same detail."""
    auth = _failure(monkeypatch, [_AUTH_LOG], RuntimeError(_HANDSHAKE_ERROR))
    no_db = _failure(monkeypatch, [_NO_DATABASE_LOG], RuntimeError(_HANDSHAKE_ERROR))

    assert auth.context["detail"] != no_db.context["detail"]
    assert auth.context["cause"] != no_db.context["cause"]
    assert auth.context["hint_es"] != no_db.context["hint_es"]
    assert auth.context["hint_en"] != no_db.context["hint_en"]


def test_hints_are_localized_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _failure(monkeypatch, [_NO_DATABASE_LOG], RuntimeError(_HANDSHAKE_ERROR))

    assert "DEV" in err.context["hint_es"]
    assert "svc_dev" in err.context["hint_en"]
    assert err.context["hint_es"] != err.context["hint_en"]


def test_unclassified_failure_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _failure(monkeypatch, ["something the driver never said before"], RuntimeError(""))

    assert err.context["cause"] == CAUSE_UNKNOWN
    assert err.context["detail"] == "something the driver never said before"


def test_diagnostics_handler_ignores_other_threads() -> None:
    """A concurrent connection's records must not reach this connection's detail.

    The ``nzpy`` logger is process-wide, and each caller sanitizes only with its own
    password, so a record from another thread could carry an unsanitized secret here.
    """
    handler = _DriverDiagnosticsHandler()
    logger = logging.getLogger("nzpy")
    logger.addHandler(handler)
    try:
        logger.warning("from this thread")
        other = threading.Thread(target=lambda: logger.warning("from another thread"))
        other.start()
        other.join()
    finally:
        logger.removeHandler(handler)

    assert handler.messages == ["from this thread"]


def test_captured_driver_text_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A password echoed by the driver must never reach detail, hints or the message."""
    known_pw = "sup3r-s3cret-value"
    err = _failure(
        monkeypatch,
        [f"Error occured, server response:auth failed (password={known_pw})", known_pw],
        RuntimeError(f"handshake aborted for {known_pw}"),
        password=known_pw,
    )

    assert known_pw not in err.context["detail"]
    assert known_pw not in err.context["hint_es"]
    assert known_pw not in err.context["hint_en"]
    assert known_pw not in str(err)


def test_every_cause_has_es_en_hint_keys() -> None:
    causes = (
        CAUSE_AUTH_REJECTED,
        CAUSE_DATABASE_UNAVAILABLE,
        CAUSE_HOST_UNREACHABLE,
        CAUSE_TLS_FAILED,
        CAUSE_UNKNOWN,
    )
    for cause in causes:
        assert f"CONNECTION_FAILED.HINT.{cause}" in MESSAGES


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Error in handshake: hentication failed for user 'X'", CAUSE_AUTH_REJECTED),
        ("Invalid username/password", CAUSE_AUTH_REJECTED),
        ('FATAL 1:  Database "X" does not exist.', CAUSE_DATABASE_UNAVAILABLE),
        ("permission denied for database X", CAUSE_DATABASE_UNAVAILABLE),
        ("('communication error', TimeoutError('timed out'))", CAUSE_HOST_UNREACHABLE),
        ("[Errno 111] Connection refused", CAUSE_HOST_UNREACHABLE),
        ("Problem establishing secured session", CAUSE_TLS_FAILED),
        ("Could not load CA certificate '/x/ca.pem'", CAUSE_TLS_FAILED),
        ("[SSL] certificate verify failed", CAUSE_TLS_FAILED),
        ("brand new driver message", CAUSE_UNKNOWN),
    ],
)
def test_classify_connection_failure(text: str, expected: str) -> None:
    assert classify_connection_failure(text) == expected


def test_capture_handler_is_always_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    """The capture must not survive the call, on success or on failure."""
    nzpy_logger = logging.getLogger("nzpy")
    before = list(nzpy_logger.handlers)

    monkeypatch.setattr("nz_mcp.connection.nzpy.connect", lambda **_kwargs: object())
    open_connection(_profile(), _TEST_PW)
    assert nzpy_logger.handlers == before

    monkeypatch.setattr(
        "nz_mcp.connection.nzpy.connect", _connect_double([_AUTH_LOG], RuntimeError("boom"))
    )
    with pytest.raises(NzConnectionError):
        open_connection(_profile(), _TEST_PW)
    assert nzpy_logger.handlers == before


def test_diagnostics_do_not_leak_between_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _failure(monkeypatch, [_AUTH_LOG], RuntimeError(_HANDSHAKE_ERROR))
    second = _failure(monkeypatch, [_TLS_LOG], RuntimeError(_HANDSHAKE_ERROR))

    assert "hentication failed" not in second.context["detail"]
    assert _TLS_LOG not in first.context["detail"]
