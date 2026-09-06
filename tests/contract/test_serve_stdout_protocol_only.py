"""Contract: the stdout of ``nz-mcp serve`` carries MCP JSON-RPC frames and nothing else.

Issue #203. The pre-existing contract test (``test_stdio_stdout_json_lines.py``) proves that
*structlog* does not write to stdout, but it never starts the ``serve`` command, so a stray
``typer.echo`` on that code path would ship unnoticed and break every MCP client.

This module closes that hole with three complementary checks, because any single one of them
could be walked around:

1. :func:`test_serve_stdout_carries_only_jsonrpc_frames` really starts ``serve`` as a
   subprocess, speaks a full JSON-RPC handshake to it and inspects every byte it wrote to
   stdout. It is the runtime proof.
2. :func:`test_the_violation_detector_rejects_polluted_stdout` feeds polluted samples to the
   same detector the first test uses, so a detector that silently stopped detecting anything
   cannot make the suite green.
3. :func:`test_no_module_writes_to_the_terminal_outside_the_output_layer` parses the source
   of every module under ``src/nz_mcp`` and rejects direct terminal writes. This is what keeps
   the guarantee alive when someone adds a *new* command tomorrow: the runtime check only
   covers the ``serve`` path, this one covers the whole package.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

#: Modules allowed to talk to the terminal directly. Exactly one: the output layer.
_OUTPUT_LAYER: Final[str] = "cli_output.py"

#: Attribute calls that write to (or read from) the terminal behind the CLI's back.
_FORBIDDEN_ATTRIBUTES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("typer", "echo"),
        ("typer", "secho"),
        ("typer", "prompt"),
        ("typer", "confirm"),
        ("click", "echo"),
        ("click", "secho"),
        ("click", "prompt"),
        ("click", "confirm"),
    }
)

_ANSI: Final[re.Pattern[str]] = re.compile("\x1b\\[")

_FRAME: Final[str] = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"

#: Seconds allowed for the whole handshake. Generous: CI runners import the MCP SDK cold.
_SERVE_TIMEOUT_S: Final[int] = 120


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _handshake_payload() -> str:
    """Initialize, acknowledge and ask for the tool catalog, newline-delimited."""
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "nz-mcp-contract-test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    return "".join(json.dumps(request) + "\n" for request in requests)


def _serve_env(home: Path) -> dict[str, str]:
    """Environment for the subprocess, hostile on purpose.

    ``NZ_MCP_LANG=es`` would surface any translated banner; ``FORCE_COLOR`` and a colour-capable
    ``TERM`` would surface any styling that ignores terminal detection. Neither may reach stdout.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_project_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["NZ_MCP_HOME"] = str(home)
    env["NZ_MCP_LANG"] = "es"
    env["PYTHONIOENCODING"] = "utf-8"
    env["FORCE_COLOR"] = "1"
    env["TERM"] = "xterm-256color"
    env.pop("NO_COLOR", None)
    return env


def _run_serve(home: Path) -> subprocess.CompletedProcess[str]:
    """Start the real ``serve`` command and drive a JSON-RPC session over its stdio."""
    proc = subprocess.run(
        [sys.executable, "-m", "nz_mcp", "serve"],
        input=_handshake_payload(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_SERVE_TIMEOUT_S,
        cwd=_project_root(),
        env=_serve_env(home),
    )
    return proc


def collect_protocol_violations(stdout: str) -> list[str]:
    """Return one message per stdout line that is not a well-formed JSON-RPC frame.

    Anything else — a banner, a blank line, an ANSI sequence, a bare JSON document — is a
    protocol violation, because the MCP client parses this stream line by line.
    """
    violations: list[str] = []
    for number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            violations.append(f"line {number}: blank line on the protocol stream")
            continue
        if _ANSI.search(line):
            violations.append(f"line {number}: ANSI escape sequence on stdout")
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            violations.append(f"line {number}: not JSON: {line[:120]!r}")
            continue
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            violations.append(f"line {number}: JSON without a JSON-RPC envelope: {line[:120]!r}")
    return violations


@pytest.mark.contract
def test_serve_stdout_carries_only_jsonrpc_frames(tmp_path: Path) -> None:
    """Start ``serve`` for real and assert its stdout is pure protocol, before and during."""
    proc = _run_serve(tmp_path)
    assert proc.returncode == 0, proc.stderr

    violations = collect_protocol_violations(proc.stdout)
    assert violations == [], (
        "nz-mcp serve wrote non-protocol bytes to stdout: "
        + "; ".join(violations)
        + " — every human-facing message must go through nz_mcp.cli_output (stderr)."
    )

    frames = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    answered = {frame.get("id") for frame in frames}
    assert {1, 2} <= answered, f"handshake was not answered: {frames}"
    listing = next(frame for frame in frames if frame.get("id") == 2)
    assert listing["result"]["tools"], "tools/list came back empty; the session did not work"


@pytest.mark.contract
@pytest.mark.parametrize(
    "polluted",
    [
        pytest.param("Starting nz-mcp...\n" + _FRAME, id="banner-before-the-frame"),
        pytest.param(_FRAME + "OK: connected\n", id="status-line-after-the-frame"),
        pytest.param(_FRAME + "\x1b[32mdone\x1b[0m\n", id="ansi-styling"),
        pytest.param(_FRAME + "\n", id="blank-line"),
        pytest.param('{"hello": "world"}\n' + _FRAME, id="json-without-envelope"),
    ],
)
def test_the_violation_detector_rejects_polluted_stdout(polluted: str) -> None:
    """The detector must fail on pollution; otherwise the test above proves nothing."""
    assert collect_protocol_violations(polluted) != []


@pytest.mark.contract
def test_the_violation_detector_accepts_a_clean_stream() -> None:
    assert collect_protocol_violations(_FRAME + _FRAME) == []


def _terminal_writes(tree: ast.AST) -> list[str]:
    """Find direct terminal writes in a parsed module."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print":
                found.append(f"line {node.lineno}: print()")
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and (func.value.id, func.attr) in _FORBIDDEN_ATTRIBUTES
            ):
                found.append(f"line {node.lineno}: {func.value.id}.{func.attr}()")
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr == "stdout"
        ):
            found.append(f"line {node.lineno}: sys.stdout")
    return found


@pytest.mark.contract
def test_no_module_writes_to_the_terminal_outside_the_output_layer() -> None:
    """Every human-facing byte must be routed by ``nz_mcp.cli_output``.

    Without this, the runtime check above only protects the commands that exist today: a new
    command added tomorrow could call ``typer.echo`` and, if anything ever imported it from the
    ``serve`` path, corrupt the protocol again.
    """
    package = _project_root() / "src" / "nz_mcp"
    offenders: dict[str, list[str]] = {}
    for module in sorted(package.rglob("*.py")):
        if module.name == _OUTPUT_LAYER:
            continue
        writes = _terminal_writes(ast.parse(module.read_text(encoding="utf-8")))
        if writes:
            offenders[str(module.relative_to(package))] = writes
    assert offenders == {}, (
        f"direct terminal writes found outside {_OUTPUT_LAYER}: {offenders} — "
        "use nz_mcp.cli_output.emit() for command payload or .status() for anything a person reads."
    )
