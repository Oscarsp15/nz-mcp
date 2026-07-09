"""Unit tests for the safe DDL input reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from nz_mcp.io.safe_read import MAX_INPUT_DDL_BYTES, read_input_ddl


def test_read_input_ddl_happy_path(tmp_path: Path) -> None:
    target = tmp_path / "proc.sql"
    target.write_text("CREATE OR REPLACE VIEW DBO.V AS SELECT 1 AS C\n", encoding="utf-8")
    assert read_input_ddl(str(target)).startswith("CREATE OR REPLACE VIEW")


def test_read_input_ddl_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absoluto"):
        read_input_ddl("relative/path.sql")


def test_read_input_ddl_rejects_traversal(tmp_path: Path) -> None:
    bad = str(tmp_path / ".." / "x.sql")
    with pytest.raises(ValueError, match="traversal"):
        read_input_ddl(bad)


def test_read_input_ddl_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_input_ddl(str(tmp_path / "nope.sql"))


def test_read_input_ddl_directory(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        read_input_ddl(str(tmp_path))


def test_read_input_ddl_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "big.sql"
    target.write_text("x" * 10, encoding="utf-8")
    monkeypatch.setattr("nz_mcp.io.safe_read.MAX_INPUT_DDL_BYTES", 5)
    with pytest.raises(ValueError, match="excede"):
        read_input_ddl(str(target))


def test_read_input_ddl_invalid_utf8(tmp_path: Path) -> None:
    target = tmp_path / "latin.sql"
    target.write_bytes(b"\xff\xfe invalid")
    with pytest.raises(ValueError, match="UTF-8"):
        read_input_ddl(str(target))


def test_max_input_ddl_bytes_is_one_mib() -> None:
    assert MAX_INPUT_DDL_BYTES == 1024 * 1024
