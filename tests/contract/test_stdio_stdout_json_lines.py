"""Contract: MCP stdio JSON-RPC must not be mixed with log text on stdout (issue #86)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    src = str(_project_root() / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


@pytest.mark.contract
def test_stdio_stdout_lines_are_json_after_structlog_emitted() -> None:
    """Regression: structlog must not write to stdout; only JSON lines may appear."""
    code = """
import json
import sys
import structlog
from nz_mcp.logging_config import configure_logging_for_stdio
configure_logging_for_stdio()
structlog.get_logger("x").info("evt", k="v")
sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}}) + "\\n")
"""
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        cwd=_project_root(),
        env=_env_for_subprocess(),
    )
    assert proc.returncode == 0, proc.stderr
    for line in proc.stdout.splitlines():
        if line.strip():
            obj = json.loads(line)
            assert obj.get("jsonrpc") == "2.0"
