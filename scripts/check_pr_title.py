#!/usr/bin/env python
"""Validate PR title (read from $PR_TITLE env var).

Source of truth: docs/standards/git-workflow.md (section 3).
"""

from __future__ import annotations

import os
import re
import sys

PR_TITLE_REGEX = re.compile(
    r"^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)"
    r"(\([a-z0-9-]+\))?(!)?: [^\s].{0,71}$"
)


def main() -> int:
    title = os.environ.get("PR_TITLE", "").strip()
    if not title:
        print("FAIL: PR_TITLE vacío.", file=sys.stderr)
        return 1
    if not PR_TITLE_REGEX.match(title):
        print(
            f"FAIL: título del PR no cumple el regex.\n"
            f"  Recibido: {title!r}\n"
            f"  Formato:  <tipo>(<scope>)<!>: <descripción>\n"
            f"  Ver docs/standards/git-workflow.md sección 3.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
