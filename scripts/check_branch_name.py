#!/usr/bin/env python
"""Validate current branch name against the project regex.

Source of truth: docs/standards/git-workflow.md (section 1).
"""

from __future__ import annotations

import re
import subprocess
import sys

BRANCH_REGEX = re.compile(
    r"^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)/"
    r"(\d+-)?[a-z0-9]+(-[a-z0-9]+){0,8}$"
)
RELEASE_REGEX = re.compile(r"^release/v\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$")
PROTECTED = {"main"}
MAX_TOTAL_LEN = 50


def current_branch() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()


def main() -> int:
    branch = current_branch()
    if branch in PROTECTED:
        print(f"FAIL: no se permite push directo a '{branch}'.", file=sys.stderr)
        return 1
    if RELEASE_REGEX.match(branch):
        return 0
    if not BRANCH_REGEX.match(branch):
        print(
            f"FAIL: branch '{branch}' no cumple el regex.\n"
            f"Formato esperado: <tipo>/[<n>-]<slug-en-kebab-case>\n"
            f"Tipos: feat|fix|chore|refactor|docs|test|security|perf|build|ci\n"
            f"Ejemplo: feat/42-nz-list-procedures\n"
            f"Ver docs/standards/git-workflow.md secciones 1.",
            file=sys.stderr,
        )
        return 1
    if len(branch) > MAX_TOTAL_LEN:
        print(
            f"FAIL: branch '{branch}' excede {MAX_TOTAL_LEN} caracteres ({len(branch)}).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
