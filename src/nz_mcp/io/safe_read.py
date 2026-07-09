"""Safe filesystem reader for DDL input files.

Mirror of :mod:`nz_mcp.io.safe_write`: local-disk only, no Netezza, no network.
Reuses the same path policy (absolute, no ``..``, no ``~``, no control chars) so a
tool that compiles DDL from ``input_path`` cannot be steered outside the intended
filesystem. Adds an existence check and a byte-size cap (DDL files are code, not
data dumps).
"""

from __future__ import annotations

from typing import Final

from nz_mcp.io.safe_write import _validate_path_policy

# Procedure/view DDL is source code; 1 MiB is already far above any realistic
# single object and keeps a malicious/accidental huge file from being slurped.
MAX_INPUT_DDL_BYTES: Final[int] = 1024 * 1024


def read_input_ddl(path: str) -> str:
    """Read and return the UTF-8 text of ``path`` under the safe-read policy.

    Args:
        path: Absolute path to the DDL file. Must comply with the shared path
            policy (see :mod:`nz_mcp.io.safe_write`) and must already exist.

    Returns:
        The file contents decoded as UTF-8.

    Raises:
        ValueError: When ``path`` is empty, relative, contains ``..`` or ``~``,
            includes control characters, exceeds :data:`MAX_INPUT_DDL_BYTES`, or
            is not valid UTF-8.
        FileNotFoundError: When the file does not exist.
        IsADirectoryError: When ``path`` points at a directory.
    """
    target = _validate_path_policy(path)
    if not target.exists():
        raise FileNotFoundError(f"El archivo no existe: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"La ruta es un directorio, no un archivo: {target}")

    size = target.stat().st_size
    if size > MAX_INPUT_DDL_BYTES:
        raise ValueError(
            f"El archivo excede el máximo permitido ({MAX_INPUT_DDL_BYTES} bytes): {size} bytes",
        )

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"El archivo no es UTF-8 válido: {target}") from exc
