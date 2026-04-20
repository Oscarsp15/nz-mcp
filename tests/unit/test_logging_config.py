"""Tests for stdio-safe logging (issue #86)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    src = str(_project_root() / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        cwd=_project_root(),
        env=_env_for_subprocess(),
    )


def test_configure_logging_routes_root_handlers_to_stderr() -> None:
    code = """
import logging
import sys
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
root = logging.getLogger()
streams = [h.stream for h in root.handlers if hasattr(h, "stream")]
assert streams, "expected at least one stream handler on root"
assert all(s is sys.stderr for s in streams), streams
print("ok")
"""
    proc = _run_isolated(code)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_structlog_log_does_not_reach_stdout() -> None:
    code = """
import json
import sys
import structlog
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
structlog.get_logger("x").info("evt", payload="data")
sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\\n")
"""
    proc = _run_isolated(code)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["jsonrpc"] == "2.0"
    assert "evt" in proc.stderr or "payload" in proc.stderr or proc.stderr.strip()


def test_stdout_only_json_lines_after_structlog_subprocess() -> None:
    """Each non-empty stdout line must parse as JSON (no structlog text on stdout)."""
    code = """
import json
import sys
import structlog
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
structlog.get_logger("audit").info("clone_procedure_plan", source_database="DB")
for i in range(2):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, "result": {}}) + "\\n")
"""
    proc = _run_isolated(code)
    assert proc.returncode == 0, proc.stderr
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        json.loads(line)


def test_nzpy_logger_is_silenced_to_warning() -> None:
    """nzpy's per-packet DEBUG/INFO noise must not reach stderr under stdio.

    Clients that wrap nz-mcp render UI on stderr (e.g. nz-workbench's
    kb-bootstrap progress bar) — leaving nzpy at its default level shreds
    that UI.
    """
    code = """
import logging
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
lvl = logging.getLogger("nzpy").getEffectiveLevel()
assert lvl >= logging.WARNING, f"expected >=WARNING, got {lvl}"
# Child loggers inherit the level.
child = logging.getLogger("nzpy.Connection")
assert child.getEffectiveLevel() >= logging.WARNING
print("ok")
"""
    proc = _run_isolated(code)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_mcp_sdk_logger_is_silenced_to_warning() -> None:
    """The MCP SDK emits one INFO per tool call; silence it under stdio."""
    code = """
import logging
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
# Parent and the concrete child the SDK uses.
for name in ("mcp", "mcp.server.lowlevel.server"):
    lvl = logging.getLogger(name).getEffectiveLevel()
    assert lvl >= logging.WARNING, f"{name}: expected >=WARNING, got {lvl}"
print("ok")
"""
    proc = _run_isolated(code)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout
