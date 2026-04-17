"""Sanitization helpers for logs.

Rule: nothing in the log pipeline must reveal credentials or query results.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)(password|pwd|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
)
_REPLACEMENT: Final[str] = "***"
_SPLIT_PARTS_WITH_SEP: Final[int] = 3
_MIN_KNOWN_SECRET_LEN: Final[int] = 4


def sanitize(text: str, *, known_secrets: Iterable[str] | None = None) -> str:
    """Mask secret-looking patterns and any explicit known secrets.

    Args:
        text: text to sanitize.
        known_secrets: explicit values to mask (typically the active profile password).

    Returns:
        text with all detected secrets replaced by ``***``.
    """
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: _mask(m.group(0)), out)
    if known_secrets:
        for secret in known_secrets:
            if secret and len(secret) >= _MIN_KNOWN_SECRET_LEN:
                out = out.replace(secret, _REPLACEMENT)
    return out


def _mask(match_text: str) -> str:
    parts = re.split(r"([=:])", match_text, maxsplit=1)
    if len(parts) == _SPLIT_PARTS_WITH_SEP:
        head, sep, _value = parts
        return f"{head}{sep}{_REPLACEMENT}"
    return _REPLACEMENT
