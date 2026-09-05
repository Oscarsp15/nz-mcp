"""Regression tests for issue #191: no traceback may render the profile password.

The leak was never in a message we build -- ``logging_utils.sanitize`` already covers
those -- but in what the interpreter itself renders. A long traceback prints the
**arguments of every frame**, and ``password`` was one of them: once in
``open_connection`` and three more times in the ``nzpy`` frames below it (``connect``,
``Connection.__init__``, plus the chained cause). Any pasted failure output leaked the
credential of the active profile.

These tests provoke a *real* failure inside ``open_connection`` -- a closed port on
localhost, so no network, no VPN and no mock of the driver -- and render the exception
with pytest's own formatter, the one that produced the leak, asserting that:

* the credential never appears, whatever ``--tb`` style is used;
* the fields needed to diagnose the failure (host, port, database, user) still do.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from contextlib import closing
from typing import Final, Literal

import pytest
from _pytest._code import ExceptionInfo

from nz_mcp.auth import get_password, store_password
from nz_mcp.config import Profile
from nz_mcp.connection import open_connection
from nz_mcp.errors import ConnectionError as NzConnectionError
from nz_mcp.profile_check import run_checks
from nz_mcp.secret import Secret

#: Not a real credential: a value distinctive enough to be greppable in the output.
SECRET: Final[str] = "n0t-a-real-passw0rd-191"  # noqa: S105 - fixture value

#: Every traceback style pytest can be asked for. The fix must not depend on the
#: developer remembering ``--tb=short`` (acceptance criterion of #191).
TbStyle = Literal["long", "short", "line", "native", "value"]
TB_STYLES: Final[tuple[TbStyle, ...]] = ("long", "short", "line", "native", "value")

#: One failing connection is enough for every style: rendering is what is under test,
#: and each attempt costs a socket timeout.
Renderer = Callable[[TbStyle], str]


def _closed_port() -> int:
    """Return a local port nothing listens on: connecting fails without any network."""
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _unreachable_profile() -> Profile:
    return Profile(
        name="leak-check",
        host="127.0.0.1",
        port=_closed_port(),
        database="LEAKDB",
        user="leakuser",
        mode="read",
        max_rows_default=10,
        timeout_s_default=1,
    )


def _renderer_of(call: Callable[[], object]) -> Renderer:
    """Run ``call``, expect it to fail, and return a renderer over the captured failure.

    The renderer reproduces what pytest prints on a failing test: frame arguments,
    locals and the chained ``__cause__``, which is where the driver frames live.
    """
    try:
        call()
    except BaseException:  # the point is to render whatever blew up
        info: ExceptionInfo[BaseException] = ExceptionInfo.from_current()
    else:
        raise AssertionError("expected the connection to fail")

    def render(style: TbStyle) -> str:
        return str(info.getrepr(style=style, funcargs=True, showlocals=True, chain=True))

    return render


@pytest.fixture(scope="module")
def open_connection_failure() -> Renderer:
    profile = _unreachable_profile()
    # A plain ``str`` on purpose: the caller does nothing to protect the credential.
    return _renderer_of(lambda: open_connection(profile, SECRET))


@pytest.fixture
def run_checks_failure(monkeypatch: pytest.MonkeyPatch) -> Renderer:
    """A failure the ladder does *not* catch, so its own frames reach the traceback.

    ``run_checks`` grades every expected failure into an outcome, so the leak surfaces
    on the unexpected one: a driver that blows up with something the ladder does not
    handle. The wizard calls it with a draft password that never reached the keyring.
    """
    profile = _unreachable_profile()

    def exploding_connect(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("driver blew up in an unforeseen way")

    monkeypatch.setattr("nz_mcp.profile_check.open_connection", exploding_connect)
    return _renderer_of(lambda: run_checks(profile, SECRET, levels=1))


@pytest.mark.adversarial
@pytest.mark.parametrize("style", TB_STYLES)
def test_open_connection_failure_never_renders_the_password(
    open_connection_failure: Renderer, style: TbStyle
) -> None:
    assert SECRET not in open_connection_failure(style)


@pytest.mark.adversarial
@pytest.mark.parametrize("style", TB_STYLES)
def test_run_checks_failure_never_renders_the_password(
    run_checks_failure: Renderer, style: TbStyle
) -> None:
    """The wizard ladder holds a draft password in every helper frame; same rule."""
    assert SECRET not in run_checks_failure(style)


@pytest.mark.adversarial
def test_open_connection_failure_still_shows_what_to_debug(
    open_connection_failure: Renderer,
) -> None:
    """Redaction must not cost diagnosability: the connection coordinates stay visible."""
    rendered = open_connection_failure("long")
    for visible in ("127.0.0.1", "LEAKDB", "leakuser"):
        assert visible in rendered
    # The password argument is still named in the frame; only its value is gone.
    assert "password = Secret(***)" in rendered


@pytest.mark.adversarial
def test_connection_error_message_never_carries_the_password() -> None:
    """The typed error the caller may print is sanitized too (unchanged behavior)."""
    profile = _unreachable_profile()
    with pytest.raises(NzConnectionError) as excinfo:
        open_connection(profile, SECRET)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in repr(excinfo.value)


@pytest.mark.adversarial
def test_get_password_hands_out_a_redacted_secret() -> None:
    """Structural guarantee: every catalog caller receives an unprintable credential.

    ``get_password`` is the single door the credential comes through, so wrapping it
    there covers ``catalog/*``, ``cli.py`` and any future caller without them opting in.
    """
    store_password("leak-check", SECRET)
    password = get_password("leak-check")
    assert isinstance(password, Secret)
    assert SECRET not in repr(password)
    assert SECRET not in str(password)
    assert SECRET not in f"{password}"
    # ... while still being the real credential for the driver and the sanitizer.
    assert password == SECRET
    assert password.reveal() == SECRET
