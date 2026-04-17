#!/usr/bin/env python
"""Reject scratch / self-help files from being committed to the repo.

Defense in depth against AI agents that create temporary files
(notes, plans, scratch, drafts) inside the repository.

Sources of truth:
- Whitelist and blacklist documented inline below.
- Used by both the pre-commit hook and CI (`validate-conventions.yml`).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

# === Whitelist of root-level files that are allowed ===
ALLOWED_ROOT_FILES: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "README.md",
        "README.en.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "SECURITY.md",
        "pyproject.toml",
        ".gitignore",
        ".python-version",
        ".pre-commit-config.yaml",
        ".secrets.baseline",
    }
)

# === Whitelist of top-level directories that are allowed ===
ALLOWED_TOP_DIRS: frozenset[str] = frozenset(
    {
        "src",
        "tests",
        "docs",
        ".github",
        "scripts",
    }
)

# === Blacklist tokens — any of these as a stem-token (split by `_` or `-`)
#     in the file name triggers rejection.
SCRATCH_TOKENS: frozenset[str] = frozenset(
    {
        "notes",
        "notas",
        "scratch",
        "todo",
        "plan",
        "planes",
        "wip",
        "draft",
        "drafts",
        "borrador",
        "analysis",
        "analisis",
        "tmp",
        "temp",
        "debug",
        "sandbox",
        "playground",
        "untitled",
        "deleteme",
        "borrame",
        "trash",
        "old",
        "backup",
    }
)

# === Compound markers (joined with _) like local_test, test_local, my_test
COMPOUND_MARKERS: tuple[tuple[str, str], ...] = (
    ("local", "test"),
    ("test", "local"),
    ("my", "test"),
)

# === Suspicious file extensions / suffixes (case-insensitive)
BAD_SUFFIX_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r".*\.(bak|orig|swp|swo|tmp|log)$", re.IGNORECASE),
    re.compile(r".*~$"),
)

# === Blacklist of suspicious directories anywhere in the path ===
SCRATCH_DIRS: frozenset[str] = frozenset(
    {
        ".scratch",
        ".tmp",
        ".temp",
        ".notes",
        ".cache",
        ".aider",
        ".cursor",
        ".windsurf",
        ".cline",
        ".roo",
        "agent_workspace",
        "ai_workspace",
        "scratch",
        "playground",
        "sandbox",
    }
)


def _staged_files() -> list[str]:
    """Return list of files staged for commit (or all tracked files when run in CI)."""
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def _changed_files_against(base_ref: str) -> list[str]:
    """Return files added in the diff against ``base_ref`` (used in CI)."""
    out = subprocess.check_output(
        ["git", "diff", base_ref, "--name-only", "--diff-filter=A"],
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def is_violation(path: str) -> tuple[bool, str]:
    """Return (is_violation, reason) for a single repository-relative path."""
    posix = PurePosixPath(path)
    parts = posix.parts
    if not parts:
        return False, ""

    # 1) Whitelist root files
    if len(parts) == 1:
        if parts[0] in ALLOWED_ROOT_FILES:
            return False, ""
        return True, f"root file '{parts[0]}' not in whitelist"

    # 2) Whitelist top-level directories
    top = parts[0]
    if top not in ALLOWED_TOP_DIRS:
        return True, f"top-level directory '{top}/' not in whitelist"

    # 3) Blacklist suspicious directories anywhere in the path
    for component in parts[:-1]:
        if component in SCRATCH_DIRS:
            return True, f"suspicious directory '{component}/' in path"

    # 4) Blacklist by file name
    name = parts[-1]

    for pattern in BAD_SUFFIX_REGEXES:
        if pattern.match(name):
            return True, f"file '{name}' has forbidden suffix"

    stem = name.rsplit(".", 1)[0].lower()
    tokens = re.split(r"[_\-]", stem)
    for token in tokens:
        if token in SCRATCH_TOKENS:
            return True, f"file name '{name}' contains scratch token '{token}'"

    for first, second in COMPOUND_MARKERS:
        if first in tokens and second in tokens:
            return True, f"file name '{name}' contains compound marker '{first}_{second}'"

    return False, ""


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--against":
        files = _changed_files_against(argv[2])
    else:
        files = _staged_files()

    violations: list[tuple[str, str]] = []
    for path in files:
        is_bad, reason = is_violation(path)
        if is_bad:
            violations.append((path, reason))

    if violations:
        print(
            "FAIL: archivos temporales / auto-ayuda detectados.\n"
            "Estos archivos NO deben entrar al repo. Revisa AGENTS.md (regla inviolable)\n"
            "y docs/standards/maintainability.md (sección 'Archivos prohibidos en el repo').\n",
            file=sys.stderr,
        )
        for path, reason in violations:
            print(f"  - {path}\n      motivo: {reason}", file=sys.stderr)
        print(
            "\nSi el archivo es legítimo, añadilo a la whitelist en scripts/check_repo_hygiene.py\n"
            "y abrí ADR documentando por qué (las whitelists son contrato, no impulso).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
