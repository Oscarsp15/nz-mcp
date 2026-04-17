"""Profile loading from ``~/.nz-mcp/profiles.toml``.

Passwords are stored separately in the OS keyring (see auth.py), never here.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nz_mcp.errors import InvalidProfileError, ProfileNotFoundError

PermissionMode = Literal["read", "write", "admin"]

DEFAULT_MAX_ROWS: Final[int] = 100
DEFAULT_TIMEOUT_S: Final[int] = 30
MAX_ROWS_CAP: Final[int] = 1000
TIMEOUT_S_CAP: Final[int] = 300


def config_dir() -> Path:
    override = os.environ.get("NZ_MCP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".nz-mcp"


def profiles_path() -> Path:
    return config_dir() / "profiles.toml"


class Profile(BaseModel):
    """A connection profile. Mode is the only thing the AI cannot change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1)
    user: str = Field(min_length=1)
    mode: PermissionMode
    max_rows_default: int = Field(default=DEFAULT_MAX_ROWS, ge=1, le=MAX_ROWS_CAP)
    timeout_s_default: int = Field(default=DEFAULT_TIMEOUT_S, ge=1, le=TIMEOUT_S_CAP)


class ProfilesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: str | None = None
    profiles: dict[str, dict[str, object]] = Field(default_factory=dict)


def load_profiles_file(path: Path | None = None) -> ProfilesFile:
    target = path or profiles_path()
    if not target.exists():
        return ProfilesFile()
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InvalidProfileError(detail=str(exc)) from exc
    try:
        return ProfilesFile.model_validate(data)
    except ValidationError as exc:
        raise InvalidProfileError(detail=str(exc)) from exc


def list_profile_names(path: Path | None = None) -> list[str]:
    return sorted(load_profiles_file(path).profiles.keys())


def get_profile(name: str, path: Path | None = None) -> Profile:
    file = load_profiles_file(path)
    raw = file.profiles.get(name)
    if raw is None:
        raise ProfileNotFoundError(profile=name)
    try:
        return Profile.model_validate({"name": name, **raw})
    except ValidationError as exc:
        raise InvalidProfileError(profile=name, detail=str(exc)) from exc


def get_active_profile(path: Path | None = None) -> Profile:
    file = load_profiles_file(path)
    name = file.active or os.environ.get("NZ_MCP_PROFILE") or _single_profile_or_none(file)
    if not name:
        raise ProfileNotFoundError(profile="<active>")
    return get_profile(name, path=path)


def _single_profile_or_none(file: ProfilesFile) -> str | None:
    keys = list(file.profiles.keys())
    return keys[0] if len(keys) == 1 else None
