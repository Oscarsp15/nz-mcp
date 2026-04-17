#!/usr/bin/env python
"""Validate commit message subject against the project regex.

Used as a `commit-msg` hook. Receives the path to the commit message file as argv[1].

Source of truth: docs/standards/git-workflow.md (section 2).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SUBJECT_REGEX = re.compile(
    r"^(feat|fix|chore|refactor|docs|test|security|perf|build|ci)"
    r"(\([a-z0-9-]+\))?(!)?: [^\s].{0,71}$"
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("FAIL: falta ruta del archivo de mensaje de commit.", file=sys.stderr)
        return 1
    msg_path = Path(argv[1])
    if not msg_path.exists():
        print(f"FAIL: no existe {msg_path}.", file=sys.stderr)
        return 1

    raw = msg_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines:
        print("FAIL: mensaje de commit vacío.", file=sys.stderr)
        return 1

    subject = lines[0].rstrip()

    if subject.startswith(("Merge ", "Revert ", "fixup!", "squash!")):
        return 0

    if not SUBJECT_REGEX.match(subject):
        print(
            f"FAIL: subject del commit no cumple el regex.\n"
            f"  Recibido: {subject!r}\n"
            f"  Formato:  <tipo>(<scope>)<!>: <descripción>\n"
            f"  Tipos:    feat|fix|chore|refactor|docs|test|security|perf|build|ci\n"
            f"  Reglas:   72 chars máximo, imperativo en español, primera letra minúscula,\n"
            f"            sin punto final, una intención por commit.\n"
            f"  Ejemplo:  feat(tools): añade nz_get_view_ddl\n"
            f"  Ver docs/standards/git-workflow.md sección 2.",
            file=sys.stderr,
        )
        return 1

    if len(lines) >= 2 and lines[1].strip():
        print(
            "FAIL: si hay body, debe haber línea en blanco entre subject y body.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
