"""Profile loading from ``~/.nz-mcp/profiles.toml``.

Passwords are stored separately in the OS keyring (see auth.py), never here.
"""

from __future__ import annotations

import contextlib
import os
import tomllib
from pathlib import Path
from typing import Any, Final, Literal

import tomli_w
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
    # Catalog overrides run as-is and do not go through sql_guard.
    catalog_overrides: dict[str, str] = Field(default_factory=dict)


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


def set_active_profile(name: str, path: Path | None = None) -> None:
    """Persist ``active = name`` in ``profiles.toml`` after validating the profile exists."""
    cfg = path or profiles_path()
    get_profile(name, path=cfg)
    raw: dict[str, Any] = tomllib.loads(cfg.read_text(encoding="utf-8"))
    raw["active"] = name
    tmp = cfg.with_suffix(cfg.suffix + ".tmp")
    tmp.write_text(tomli_w.dumps(raw), encoding="utf-8")
    tmp.replace(cfg)
    with contextlib.suppress(OSError):  # pragma: no cover - Windows ACLs differ
        cfg.chmod(0o600)


def get_profile(name: str, path: Path | None = None) -> Profile:
    file = load_profiles_file(path)
    raw = file.profiles.get(name)
    if raw is None:
        raise ProfileNotFoundError(profile=name, hint_es="", hint_en="")
    try:
        return Profile.model_validate({"name": name, **raw})
    except ValidationError as exc:
        raise InvalidProfileError(profile=name, detail=str(exc)) from exc


def get_active_profile(path: Path | None = None) -> Profile:
    file = load_profiles_file(path)
    name = file.active or os.environ.get("NZ_MCP_PROFILE") or single_profile_name_or_none(file)
    if not name:
        raise ProfileNotFoundError(profile="<active>", hint_es="", hint_en="")
    return get_profile(name, path=path)


def single_profile_name_or_none(file: ProfilesFile) -> str | None:
    """Return the profile name when ``file`` defines exactly one profile, else ``None``.

    Used to infer the active profile when ``active`` and ``NZ_MCP_PROFILE`` are unset.
    """
    keys = list(file.profiles.keys())
    return keys[0] if len(keys) == 1 else None


def update_profile_fields(
    name: str,
    path: Path | None = None,
    *,
    mode: PermissionMode | None = None,
    database: str | None = None,
    max_rows_default: int | None = None,
    timeout_s_default: int | None = None,
) -> Profile | None:
    """Update optional fields on a profile block. Returns ``None`` if nothing to change."""
    if all(v is None for v in (mode, database, max_rows_default, timeout_s_default)):
        return None
    target = path or profiles_path()
    if not target.exists():
        raise ProfileNotFoundError(profile=name, hint_es="", hint_en="")
    raw: dict[str, Any] = tomllib.loads(target.read_text(encoding="utf-8"))
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or name not in profiles:
        raise ProfileNotFoundError(profile=name, hint_es="", hint_en="")
    block = dict(profiles[name])
    if mode is not None:
        block["mode"] = mode
    if database is not None:
        block["database"] = database
    if max_rows_default is not None:
        block["max_rows_default"] = max_rows_default
    if timeout_s_default is not None:
        block["timeout_s_default"] = timeout_s_default
    merged = Profile.model_validate({"name": name, **block})
    profiles[name] = block
    raw["profiles"] = profiles
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(tomli_w.dumps(raw), encoding="utf-8")
    tmp.replace(target)
    with contextlib.suppress(OSError):  # pragma: no cover - Windows ACLs differ
        target.chmod(0o600)
    return merged
