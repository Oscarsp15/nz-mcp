"""Shared regex fragments for Netezza NZPLSQL ``CREATE PROCEDURE`` header validation."""

from __future__ import annotations

from typing import Final

# Outer ``(...)`` parameter list: allows one level of nested parens (``VARCHAR(20)``,
# ``NUMERIC(10,2)``). Deeper nesting is not matched end-to-end here by design.
PROCEDURE_PARAM_LIST_PATTERN: Final[str] = r"\((?:[^()]|\([^()]*\))*\)"
