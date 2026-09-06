"""Contract: the stdout of ``nz-mcp serve`` carries MCP JSON-RPC frames and nothing else.

Issue #203. The pre-existing contract test (``test_stdio_stdout_json_lines.py``) proves that
*structlog* does not write to stdout, but it never starts the ``serve`` command, so a stray
``typer.echo`` on that code path would ship unnoticed and break every MCP client.

This module closes that hole with four complementary checks. None of them is sufficient alone,
and the order matters — the last one is the only guarantee that does not depend on knowing the
name of the thing that writes:

1. :func:`test_serve_stdout_carries_only_jsonrpc_frames` really starts ``serve`` as a
   subprocess and drives a whole session: handshake, tool catalog, and two ``tools/call``
   dispatches. Tool handlers are the deepest code in the process, so a session that stopped at
   ``tools/list`` would leave them untested.
2. :func:`test_the_violation_detector_rejects_polluted_stdout` feeds polluted samples to the
   same detector the first test uses, so a detector that silently stopped detecting anything
   cannot make the suite green.
3. :func:`test_no_module_writes_to_the_terminal_outside_the_output_layer` parses the source of
   every module under ``src/nz_mcp`` and rejects direct routes to standard output, resolving
   import aliases first. It keeps the guarantee alive when someone adds a *new* command
   tomorrow — but it is a **blacklist**, and a blacklist by name can always be worked around
   (``os.write(1, ...)`` names nothing greppable). Treat it as review help, not as the barrier.
4. :func:`test_a_raw_write_to_descriptor_1_cannot_reach_the_protocol` is the barrier. It proves
   that while ``serve`` holds stdout, a raw write to descriptor 1 lands on stderr and the
   protocol stream is untouched, because ``cli_output.stdout_reserved_for_protocol`` moved it
   out of reach. This one does not care who writes, or how.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Final

import pytest

#: Modules allowed to talk to the terminal directly. Exactly one: the output layer.
_OUTPUT_LAYER: Final[str] = "cli_output.py"

#: Fully qualified names that reach standard output without going through the layer.
#: Names are resolved through the module's own import aliases first, so renaming an
#: import (``import sys as s``) does not slip past. This is a blacklist and therefore
#: incomplete by nature — the guarantee lives in the descriptor swap at runtime; this
#: check is here to catch the mistake at review time, with the offending line named.
_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "print",
        "typer.echo",
        "typer.secho",
        "typer.prompt",
        "typer.confirm",
        "click.echo",
        "click.secho",
        "click.prompt",
        "click.confirm",
        "os.write",
        "os.writev",
        "sys.stdout",
        "sys.__stdout__",
    }
)

#: Attributes that must not be fetched dynamically off ``sys`` / ``os`` either.
_FORBIDDEN_DYNAMIC: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("sys", "stdout"),
        ("sys", "__stdout__"),
        ("os", "write"),
        ("os", "writev"),
    }
)

#: Third-party packages that exactly one place in the project may import, and where that
#: place is. Importing one of them anywhere else is the violation by itself, whatever is
#: done with it afterwards.
#:
#: - ``rich``: ``rich.console.Console`` writes to **stdout** by default — exactly the byte
#:   that corrupts the JSON-RPC of ``serve`` — so condition 2 of ADR 0027 confines the whole
#:   package to ``cli_output.py``, where the channel is decided once.
#: - ``textual``: condition 2 of ADR 0029 confines it to the wizard package, and pointedly
#:   **not** to the output layer, which would then be two things at once. It writes to
#:   ``sys.__stdout__``, which a name-based protection would miss entirely; the descriptor
#:   swap covers it, and this keeps it away from the ``serve`` import graph as well.
#:
#: The values are paths under ``src/nz_mcp`` and match as prefixes, so a whole directory
#: can own a package. Everything outside its home is forbidden — including, for each of
#: these two, the home of the other.
_LAYER_ONLY_MODULES: Final[dict[str, str]] = {
    "rich": "cli_output.py",
    "textual": "wizard",
}

_ANSI: Final[re.Pattern[str]] = re.compile("\x1b\\[")

_FRAME: Final[str] = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"

#: Seconds allowed for the whole handshake. Generous: CI runners import the MCP SDK cold.
_SERVE_TIMEOUT_S: Final[int] = 120


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _session_payload() -> str:
    """A full session, newline-delimited: handshake, catalog and a real tool call.

    Stopping at ``tools/list`` would only exercise the greeting: a stray write inside a tool
    handler — the deepest and least reviewed code in the process — would never run. So the
    session also dispatches a registered tool. It answers with an error because no profile is
    configured, and that is the point: handler, error classification, hint lookup and response
    serialization all execute, and none of them may put a byte on the protocol stream.
    """
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
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nz_list_databases", "arguments": {}},
        },
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


def _drive_serve(home: Path, expected_ids: set[int]) -> tuple[str, str, int | None]:
    """Start the real ``serve`` command and hold the session open until it has answered.

    Writing every request and closing stdin in one go — what ``subprocess.run`` does — makes
    the test racy: the transport stops on end of input and whatever was still in flight is
    lost. Here stdin stays open until the answers for ``expected_ids`` have arrived, so a
    missing answer is a real failure and not a scheduling accident.

    Returns:
        The complete stdout, the complete stderr, and the exit code.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "nz_mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=_project_root(),
        env=_serve_env(home),
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.extend(proc.stdout or []), daemon=True)
    reader.start()

    try:
        proc.stdin.write(_session_payload())
        proc.stdin.flush()
        deadline = time.monotonic() + _SERVE_TIMEOUT_S
        while time.monotonic() < deadline and not expected_ids <= _answered_ids(lines):
            time.sleep(0.05)
    finally:
        with contextlib.suppress(OSError, ValueError):
            proc.stdin.close()
        try:
            proc.wait(timeout=_SERVE_TIMEOUT_S)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hung server
            proc.kill()
            proc.wait(timeout=_SERVE_TIMEOUT_S)
        reader.join(timeout=_SERVE_TIMEOUT_S)
        stderr = proc.stderr.read()

    return "".join(lines), stderr, proc.returncode


def _answered_ids(lines: list[str]) -> set[int]:
    """Ids answered so far, ignoring anything that is not a JSON-RPC frame.

    Garbage is deliberately tolerated here: detecting it is
    :func:`collect_protocol_violations`'s job, and this loop must not crash before the
    assertion that reports it.
    """
    answered: set[int] = set()
    for line in list(lines):
        with contextlib.suppress(json.JSONDecodeError, AttributeError):
            frame = json.loads(line)
            if isinstance(frame, dict) and isinstance(frame.get("id"), int):
                answered.add(frame["id"])
    return answered


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
    stdout, stderr, returncode = _drive_serve(tmp_path, expected_ids={1, 2, 3})
    assert returncode == 0, stderr

    violations = collect_protocol_violations(stdout)
    assert violations == [], (
        "nz-mcp serve wrote non-protocol bytes to stdout: "
        + "; ".join(violations)
        + " — every human-facing message must go through nz_mcp.cli_output (stderr)."
    )

    frames = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    answered = {frame.get("id") for frame in frames}
    assert {1, 2, 3} <= answered, f"the session was not answered in full: {frames}"
    listing = next(frame for frame in frames if frame.get("id") == 2)
    assert listing["result"]["tools"], "tools/list came back empty; the session did not work"
    # The tool call must have reached a handler, not died in the transport.
    call = next(frame for frame in frames if frame.get("id") == 3)
    assert "result" in call or "error" in call, f"the tool call was not dispatched: {call}"


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


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map the names a module uses locally to the real module or attribute behind them.

    ``import sys as s`` makes ``s.stdout`` mean ``sys.stdout``, and ``from sys import
    stdout`` makes a bare ``stdout`` mean the same thing. Comparing against the literal
    string ``"sys"``, as the first version of this check did, is bypassed by both.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    root = alias.name.split(".")[0]
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Resolve a dotted expression to its real fully qualified name, or ``None``."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def _is_forbidden(name: str | None) -> bool:
    """Whether ``name`` is a forbidden target, or an attribute reached through one."""
    if name is None:
        return False
    return name in _FORBIDDEN_NAMES or any(
        name.startswith(f"{forbidden}.") for forbidden in _FORBIDDEN_NAMES
    )


def _dynamic_lookup(node: ast.Call, aliases: dict[str, str]) -> str | None:
    """Catch ``getattr(sys, "stdout")`` and friends, which no dotted check would see."""
    if _qualified_name(node.func, aliases) != "getattr" or len(node.args) < 2:
        return None
    owner = _qualified_name(node.args[0], aliases)
    attribute = node.args[1]
    if not isinstance(attribute, ast.Constant) or not isinstance(attribute.value, str):
        return None
    if (owner, attribute.value) in _FORBIDDEN_DYNAMIC:
        return f"getattr({owner}, {attribute.value!r})"
    return None


def _layer_only_imports(tree: ast.AST, forbidden: frozenset[str] | None = None) -> list[str]:
    """Find imports of confined packages that the module being parsed may not name.

    ``forbidden`` defaults to *every* confined package, which is what a caller checking a
    snippet in isolation wants. The walk over the real tree passes the subset that applies
    to each file, because each package is allowed in exactly one place.
    """
    names = _LAYER_ONLY_MODULES.keys() if forbidden is None else forbidden
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in names
            )
        elif (
            isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in names
        ):
            found.append(f"line {node.lineno}: from {node.module} import ...")
    return found


def _confined_elsewhere(relative: Path) -> frozenset[str]:
    """Which confined packages this module is not allowed to import."""
    return frozenset(
        package
        for package, home in _LAYER_ONLY_MODULES.items()
        if relative.parts[: len(Path(home).parts)] != Path(home).parts
    )


def _terminal_writes(tree: ast.AST) -> list[str]:
    """Find every direct route to standard output in a parsed module."""
    aliases = _import_aliases(tree)
    found: dict[tuple[int, str], None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dynamic = _dynamic_lookup(node, aliases)
            if dynamic is not None:
                found[(node.lineno, dynamic)] = None
            name = _qualified_name(node.func, aliases)
            if _is_forbidden(name) and name is not None:
                # Reported without parentheses so the call and the attribute access it
                # contains collapse into a single entry per line.
                found[(node.lineno, name)] = None
        elif isinstance(node, ast.Attribute | ast.Name):
            name = _qualified_name(node, aliases)
            if name in _FORBIDDEN_NAMES:
                found[(node.lineno, name)] = None
    return [f"line {lineno}: {name}" for lineno, name in found]


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
        relative = module.relative_to(package)
        tree = ast.parse(module.read_text(encoding="utf-8"))
        # The output layer is the one module allowed to write to the terminal; it is not
        # allowed to import every confined package, so the second check still applies.
        writes = [] if module.name == _OUTPUT_LAYER else _terminal_writes(tree)
        writes += _layer_only_imports(tree, _confined_elsewhere(relative))
        if writes:
            offenders[str(relative)] = writes
    assert offenders == {}, (
        f"direct terminal writes found outside {_OUTPUT_LAYER}: {offenders} — "
        "use nz_mcp.cli_output.emit() for command payload or .status() for anything a person reads."
    )


@pytest.mark.contract
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import rich\n", id="import-rich"),
        pytest.param("from rich.console import Console\n", id="from-rich-console"),
        pytest.param("import rich.table as tbl\n", id="aliased-rich-submodule"),
    ],
)
def test_rich_may_not_be_imported_outside_the_output_layer(source: str) -> None:
    """Condition 2 of ADR 0027, enforced instead of merely written down.

    ``Console()`` defaults to stdout, so the library that best serves the CLI's presentation
    is also the one that most easily breaks ``serve``. Confining it to the layer means a
    stray ``from rich.console import Console`` fails CI rather than a user's MCP client.
    """
    assert _layer_only_imports(ast.parse(source)) != []


@pytest.mark.contract
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import textual\n", id="import-textual"),
        pytest.param("from textual.app import App\n", id="from-textual-app"),
        pytest.param("import textual.widgets as w\n", id="aliased-textual-submodule"),
    ],
)
def test_textual_may_not_be_imported_outside_the_wizard(source: str) -> None:
    """Condition 2 of ADR 0029, enforced instead of merely written down.

    ``textual`` is a whole application framework with its own event loop, and it writes to
    ``sys.__stdout__``. Confining it to ``src/nz_mcp/wizard/`` keeps a future major inside
    one directory and keeps it out of the ``serve`` import graph, where the JSON-RPC lives.
    """
    assert _layer_only_imports(ast.parse(source)) != []


@pytest.mark.contract
def test_each_confined_package_is_forbidden_in_the_other_ones_home() -> None:
    """The confinement is symmetric: the wizard does not import ``rich`` either.

    It gets ``rich`` underneath ``textual``, which is the same rendering stack the output
    layer already uses. Naming it directly would be a second route to the same library and
    the beginning of a second way to decide a channel.
    """
    assert _confined_elsewhere(Path("wizard/app.py")) == frozenset({"rich"})
    assert _confined_elsewhere(Path("cli_output.py")) == frozenset({"textual"})
    assert _confined_elsewhere(Path("cli.py")) == frozenset({"rich", "textual"})


@pytest.mark.contract
def test_the_layer_only_check_ignores_unrelated_imports() -> None:
    assert _layer_only_imports(ast.parse("import typer\nfrom nz_mcp import i18n\n")) == []


#: Every route that got past the first version of this check, kept as a regression list.
_EVASIONS: Final[tuple[tuple[str, str], ...]] = (
    ("raw-descriptor", "import os\nos.write(1, b'noise')\n"),
    ("dunder-stdout", "import sys\nsys.__stdout__.write('noise')\n"),
    ("getattr-stdout", "import sys\ngetattr(sys, 'stdout').write('noise')\n"),
    ("aliased-sys", "import sys as s\ns.stdout.write('noise')\n"),
    ("aliased-click", "import click as c\nc.echo('noise')\n"),
    ("aliased-typer", "import typer as ty\nty.secho('noise')\n"),
    ("from-import-stdout", "from sys import stdout\nstdout.write('noise')\n"),
    ("aliased-os-write", "import os as operating\noperating.write(1, b'noise')\n"),
    ("plain-stdout", "import sys\nsys.stdout.write('noise')\n"),
    ("stream-handler", "import logging\nimport sys\nlogging.StreamHandler(sys.stdout)\n"),
    ("plain-print", "print('noise')\n"),
    ("plain-typer", "import typer\ntyper.echo('noise')\n"),
)


@pytest.mark.contract
@pytest.mark.parametrize("source", [pytest.param(src, id=name) for name, src in _EVASIONS])
def test_the_ast_check_catches_every_known_evasion(source: str) -> None:
    """Regression list: each of these reached stdout unnoticed at some point."""
    assert _terminal_writes(ast.parse(source)) != []


@pytest.mark.contract
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import sys\nsys.stderr.write('status')\n", id="stderr-is-fine"),
        pytest.param("from nz_mcp import cli_output as out\nout.emit('payload')\n", id="the-layer"),
        pytest.param("import os\nos.environ.get('X')\n", id="other-os-calls"),
    ],
)
def test_the_ast_check_does_not_flag_legitimate_code(source: str) -> None:
    """A check that flags everything gets disabled, and then protects nothing."""
    assert _terminal_writes(ast.parse(source)) == []


@pytest.mark.contract
def test_a_raw_write_to_descriptor_1_cannot_reach_the_protocol(tmp_path: Path) -> None:
    """The real guarantee: with stdout reserved, ``os.write(1, ...)`` lands on stderr.

    The name-based check above is a blacklist and will always be incomplete — ``os.write`` is
    the proof, since it reaches the descriptor without naming anything the source can grep for.
    This test drives the reservation the same way ``serve`` does and shows that a raw write,
    a ``print`` and a write through the old ``sys.__stdout__`` all end up on stderr, while the
    protocol stream stays clean.
    """
    script = "\n".join(
        [
            "import os",
            "import sys",
            "from nz_mcp import cli_output",
            "with cli_output.stdout_reserved_for_protocol() as protocol:",
            "    assert protocol is not None",
            "    os.write(1, b'raw write to descriptor 1\\n')",
            "    print('a forgotten print')",
            "    sys.__stdout__.write('a write through the original object\\n')",
            "    sys.__stdout__.flush()",
            "    protocol.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {}}) + '\\n')",
            "    protocol.flush()",
        ]
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import json\n" + script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_SERVE_TIMEOUT_S,
        cwd=_project_root(),
        env=_serve_env(tmp_path),
    )

    assert proc.returncode == 0, proc.stderr
    assert collect_protocol_violations(proc.stdout) == [], (
        "a naive write reached the protocol stream: " + proc.stdout
    )
    for noise in ("raw write to descriptor 1", "a forgotten print", "the original object"):
        assert noise in proc.stderr, f"{noise!r} did not land on stderr"
