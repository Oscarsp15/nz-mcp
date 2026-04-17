"""Tests for scripts/check_repo_hygiene.py.

Imports the script as a module via importlib to avoid adding it to the package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_repo_hygiene.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_repo_hygiene", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_check_repo_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()


def _is_violation(path: str) -> tuple[bool, str]:
    return _mod.is_violation(path)  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "README.md",
        "README.en.md",
        "LICENSE",
        "pyproject.toml",
        ".gitignore",
        ".python-version",
        ".pre-commit-config.yaml",
        ".secrets.baseline",
        "src/nz_mcp/__init__.py",
        "src/nz_mcp/tools/session.py",
        "tests/unit/test_errors.py",
        "tests/integration/README.md",
        "docs/AGENTS.md",
        "docs/architecture/overview.md",
        "docs/adr/0001-x.md",
        ".github/workflows/ci.yml",
        ".github/ISSUE_TEMPLATE/bug.yml",
        "scripts/check_branch_name.py",
    ],
)
def test_legitimate_paths_pass(path: str) -> None:
    bad, reason = _mod.is_violation(path)
    assert bad is False, f"{path} flagged: {reason}"


@pytest.mark.parametrize(
    "path",
    [
        "notes.md",
        "NOTES.md",
        "scratch.py",
        "TODO.md",
        "plan.md",
        "wip.txt",
        "draft.md",
        "borrador.md",
        "analysis.md",
        "tmp.py",
        "temp.json",
        "debug.py",
        "sandbox.py",
        "playground.py",
        "local_test.py",
        "test_local.py",
        "deleteme.txt",
        "borrame.md",
        "untitled.md",
        "src/nz_mcp/notes.md",
        "src/scratch_helper.py",
        "tests/draft_test.py",
        "docs/wip_plan.md",
        "src/foo.bak",
        "src/foo.orig",
        "anything.swp",
        "anything.tmp",
        "anything.log",
        "anything~",
    ],
)
def test_scratch_paths_blocked(path: str) -> None:
    bad, reason = _mod.is_violation(path)
    assert bad is True, f"{path} not flagged"
    assert reason  # non-empty


@pytest.mark.parametrize(
    "path",
    [
        ".scratch/notes.md",
        "agent_workspace/plan.md",
        ".aider/history.json",
        ".cursor/rules.md",
        "playground/anything.py",
        "src/.scratch/x.py",
    ],
)
def test_scratch_dirs_blocked(path: str) -> None:
    bad, reason = _mod.is_violation(path)
    assert bad is True, f"{path} not flagged"
    assert reason


@pytest.mark.parametrize(
    "path",
    [
        "random_root_file.md",
        "config.json",
        "weird/x.py",
        "out/result.csv",
    ],
)
def test_unwhitelisted_root_or_dir_blocked(path: str) -> None:
    bad, reason = _mod.is_violation(path)
    assert bad is True
    assert reason
