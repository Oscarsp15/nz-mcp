"""Safe filesystem writer for exported DDL.

This module is intentionally small and pure: it does not touch Netezza nor the
network. It validates a caller-supplied path, then writes the given bytes to
disk under a hardened policy:

* Path must be **absolute**.
* No path traversal segments (``..``).
* No tilde expansion (``~``).
* No control characters in any segment.
* Parent directory must already exist.
* Existing file is rejected unless ``overwrite=True``.
* On POSIX the file is created with permissions ``0600``.
* On Windows, ACL inheritance from the parent applies (Python ``os.chmod``
  cannot set POSIX bits there). The behaviour is documented in the ADR
  ``docs/adr/0013-export-ddl-output-path.md``.

The function returns a :class:`WriteResult` with the resolved path, the
number of bytes written and a SHA-256 hex digest of the payload — all values
are suitable for the calling tool's ``meta`` block.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Final

_FILE_MODE_OWNER_RW: Final[int] = 0o600
_ASCII_CONTROL_BOUNDARY: Final[int] = 0x20  # below this codepoint = C0 control
_ASCII_DEL: Final[int] = 0x7F


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of a successful :func:`write_export_ddl` call.

    Attributes:
        path: Absolute path to the written file as a normalised string.
        bytes_written: Length of the payload after UTF-8 encoding.
        sha256: SHA-256 hexadecimal digest of the payload bytes.
    """

    path: str
    bytes_written: int
    sha256: str


def _has_control_chars(text: str) -> bool:
    """Return ``True`` if ``text`` contains any ASCII control character.

    DDL paths must not contain ``\\x00``-``\\x1f`` nor ``\\x7f``; those would
    break shell pipelines and downstream tooling and are never legitimate in a
    catalog-derived filename.
    """
    return any(ord(ch) < _ASCII_CONTROL_BOUNDARY or ord(ch) == _ASCII_DEL for ch in text)


def _validate_path_policy(path: str) -> Path:
    """Validate ``path`` against the safe-write policy.

    Returns the parsed :class:`pathlib.Path` on success; otherwise raises
    :class:`ValueError` with an actionable Spanish message (matches the i18n
    convention used elsewhere in the package for filesystem-related rejections
    that map to ``INVALID_INPUT``).
    """
    if not path:
        raise ValueError("output_path no puede estar vacío")

    if _has_control_chars(path):
        raise ValueError("output_path contiene caracteres de control no permitidos")

    if "~" in path:
        raise ValueError("output_path no puede contener '~'; expansión de home está deshabilitada")

    # ``PurePath`` normalises separators per platform without touching the
    # filesystem. We keep the user's casing as-is.
    pure = PurePath(path)
    if not pure.is_absolute():
        raise ValueError(f"output_path debe ser absoluto, recibí: {path!r}")

    # Reject any '..' segment in any portion of the path. ``PurePath.parts``
    # preserves them on both POSIX and Windows.
    if any(part == ".." for part in pure.parts):
        raise ValueError("output_path contiene un segmento '..'; path traversal no permitido")

    return Path(pure)


def validate_output_path(path: str) -> Path:
    """Public entry point for early path validation (before any I/O).

    Used by tools that want to fail fast on a malformed ``output_path``
    *before* fetching potentially expensive remote data. The returned
    :class:`pathlib.Path` is policy-clean but not yet checked against the
    filesystem (parent existence and overwrite semantics are validated when
    :func:`write_export_ddl` actually opens the file).
    """
    return _validate_path_policy(path)


def _ensure_parent_directory(target: Path) -> None:
    """Verify the parent directory exists and is a directory.

    We deliberately do not auto-create directories: that would make
    accidental misuses (typos, wrong host) silently materialise paths.
    """
    parent = target.parent
    if not parent.exists():
        raise FileNotFoundError(f"La carpeta destino no existe: {parent}")
    if not parent.is_dir():
        raise FileNotFoundError(f"La ruta padre existe pero no es un directorio: {parent}")


def _ensure_writable_target(target: Path, *, overwrite: bool) -> None:
    """Reject existing targets unless overwrite was explicitly requested."""
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"El archivo ya existe: {target}; usa overwrite=True para sobrescribir"
        )


def _is_posix() -> bool:
    """Indirection over ``os.name`` so tests can monkeypatch the platform check."""
    return os.name == "posix"


def _apply_owner_only_permissions(target: Path) -> None:
    """Set POSIX permissions to ``0600``; on Windows this is a no-op.

    On Windows ``os.chmod`` only toggles the read-only bit, not POSIX mode.
    The ADR documents that owner ACL inheritance from the parent directory is
    the chosen behaviour there.
    """
    if not _is_posix():
        return
    target.chmod(_FILE_MODE_OWNER_RW)


def write_export_ddl(content: str, path: str, overwrite: bool) -> WriteResult:
    """Write ``content`` to ``path`` under the safe-write policy.

    Args:
        content: DDL text to persist. Always encoded as UTF-8 *without* BOM,
            byte-identical to what callers receive in the embedded resource
            block — no header, no reformatting, no line-ending translation.
        path: Absolute target path. Must comply with the policy described in
            the module docstring.
        overwrite: If ``True``, an existing file at ``path`` is replaced;
            otherwise existence is fatal.

    Returns:
        :class:`WriteResult` with the absolute path, bytes written and SHA-256
        hex digest of the payload.

    Raises:
        ValueError: When ``path`` is empty, relative, contains ``..`` or
            ``~``, or includes control characters.
        FileNotFoundError: When the parent directory does not exist.
        FileExistsError: When the file exists and ``overwrite`` is ``False``.
    """
    target = _validate_path_policy(path)
    _ensure_parent_directory(target)
    _ensure_writable_target(target, overwrite=overwrite)

    payload = content.encode("utf-8")

    # ``newline=""`` is irrelevant here because we open in binary; passing the
    # bytes verbatim guarantees byte identity with the resource block text.
    with target.open("wb") as fh:
        fh.write(payload)

    _apply_owner_only_permissions(target)

    digest = hashlib.sha256(payload).hexdigest()
    return WriteResult(path=str(target), bytes_written=len(payload), sha256=digest)
