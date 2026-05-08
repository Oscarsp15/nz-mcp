"""Adversarial tests for ``nz_mcp.io.safe_write.write_export_ddl``.

The function is the only filesystem sink for ``nz_export_ddl``. It is
exercised in isolation here so the policy (path traversal rejection,
overwrite semantics, owner-only POSIX permissions, byte identity) is
anchored even if ``tools/export_ddl.py`` evolves later.
"""

from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path

import pytest

from nz_mcp.io.safe_write import WriteResult, write_export_ddl

_SAMPLE_DDL = "CREATE VIEW v AS SELECT 1;\nSELECT 2;\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Happy path ---------------------------------------------------------------


def test_write_export_ddl_happy_path(tmp_path: Path) -> None:
    target = tmp_path / "view.sql"
    result = write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)

    assert isinstance(result, WriteResult)
    assert result.path == str(target)
    assert result.bytes_written == len(_SAMPLE_DDL.encode("utf-8"))
    assert result.sha256 == _sha256(_SAMPLE_DDL)
    assert target.read_bytes() == _SAMPLE_DDL.encode("utf-8")


def test_write_export_ddl_byte_identity_no_bom_no_translation(tmp_path: Path) -> None:
    """Payload must be byte-identical: no BOM, no CRLF translation."""
    payload = "line1\nline2\nline3\n"
    target = tmp_path / "x.sql"

    write_export_ddl(payload, str(target), overwrite=False)

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "Unexpected UTF-8 BOM was emitted"
    assert raw == payload.encode("utf-8")
    assert b"\r\n" not in raw, "Newlines were rewritten to CRLF"


# --- Path policy (rejection cases) -------------------------------------------


def test_write_export_ddl_rejects_relative_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absoluto"):
        write_export_ddl(_SAMPLE_DDL, "relative/path.sql", overwrite=False)


def test_write_export_ddl_rejects_double_dot_segment(tmp_path: Path) -> None:
    poisoned = str(tmp_path / "sub" / ".." / "out.sql")
    with pytest.raises(ValueError, match="path traversal"):
        write_export_ddl(_SAMPLE_DDL, poisoned, overwrite=False)


def test_write_export_ddl_rejects_tilde(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="~"):
        write_export_ddl(_SAMPLE_DDL, "~/out.sql", overwrite=False)


def test_write_export_ddl_rejects_control_chars(tmp_path: Path) -> None:
    poisoned = str(tmp_path / "bad\x01name.sql")
    with pytest.raises(ValueError, match="control"):
        write_export_ddl(_SAMPLE_DDL, poisoned, overwrite=False)


def test_write_export_ddl_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="vacío"):
        write_export_ddl(_SAMPLE_DDL, "", overwrite=False)


# --- Filesystem state checks --------------------------------------------------


def test_write_export_ddl_missing_parent(tmp_path: Path) -> None:
    target = tmp_path / "does_not_exist" / "v.sql"
    with pytest.raises(FileNotFoundError, match="no existe"):
        write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)


def test_write_export_ddl_parent_is_file_not_directory(tmp_path: Path) -> None:
    fake_parent = tmp_path / "not-a-dir"
    fake_parent.write_text("blocking", encoding="utf-8")
    target = fake_parent / "v.sql"
    with pytest.raises(FileNotFoundError, match="no es un directorio"):
        write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)


def test_write_export_ddl_existing_without_overwrite_fails(tmp_path: Path) -> None:
    target = tmp_path / "v.sql"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError, match="overwrite=True"):
        write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)
    assert target.read_text(encoding="utf-8") == "old"


def test_write_export_ddl_existing_with_overwrite_replaces(tmp_path: Path) -> None:
    target = tmp_path / "v.sql"
    target.write_text("OLD", encoding="utf-8")
    first_sha = _sha256("OLD")

    result = write_export_ddl(_SAMPLE_DDL, str(target), overwrite=True)

    assert target.read_bytes() == _SAMPLE_DDL.encode("utf-8")
    assert result.sha256 == _sha256(_SAMPLE_DDL)
    assert result.sha256 != first_sha


def test_write_export_ddl_overwrite_idempotent_same_sha(tmp_path: Path) -> None:
    """Two writes with the same content produce the same digest."""
    target = tmp_path / "v.sql"
    first = write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)
    second = write_export_ddl(_SAMPLE_DDL, str(target), overwrite=True)
    assert first.sha256 == second.sha256
    assert first.bytes_written == second.bytes_written


# --- Permissions --------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_write_export_ddl_posix_mode_is_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "v.sql"
    write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_write_export_ddl_posix_branch_invokes_chmod(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Force the POSIX branch to execute regardless of host OS.

    On Windows the real ``Path.chmod`` only toggles the read-only bit, so we
    swap it for a recorder. This anchors the platform-conditional code path
    and brings ``safe_write.py`` to 100% coverage on every CI runner.
    """
    chmods: list[tuple[Path, int]] = []

    def _record_chmod(self: Path, mode: int) -> None:
        chmods.append((Path(self), mode))

    monkeypatch.setattr("nz_mcp.io.safe_write._is_posix", lambda: True)
    monkeypatch.setattr(Path, "chmod", _record_chmod)

    target = tmp_path / "v.sql"
    write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)

    assert chmods == [(target, 0o600)]


# --- WriteResult shape --------------------------------------------------------


def test_write_result_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "v.sql"
    result = write_export_ddl(_SAMPLE_DDL, str(target), overwrite=False)
    with pytest.raises(AttributeError):
        result.bytes_written = 0  # type: ignore[misc]
