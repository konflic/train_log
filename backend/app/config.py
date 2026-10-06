"""Application configuration loaded from environment variables.

Local-development defaults are documented in README.md; production
deployments must set every variable explicitly. No other configuration
source exists (no dotenv, no YAML, no database-selection adapter).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})

DEFAULT_DATABASE_PATH = "data/basefit.db"
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60
DEFAULT_APP_ORIGIN = "http://localhost:5173"
DEFAULT_APP_ENV = "development"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for one API process."""

    database_path: str
    session_ttl_seconds: int
    app_origin: str
    cookie_secure: bool
    app_env: str


def _get(source: Mapping[str, str], name: str, default: str) -> str:
    """Return the variable's value; missing or blank falls back to the default."""
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    return raw


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of 1/0, true/false, yes/no, on/off; got {raw!r}")


def _parse_positive_int(name: str, raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive; got {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build settings from `env` (defaults to os.environ)."""
    source: Mapping[str, str] = os.environ if env is None else env
    return Settings(
        database_path=_get(source, "DATABASE_PATH", DEFAULT_DATABASE_PATH),
        session_ttl_seconds=_parse_positive_int(
            "SESSION_TTL_SECONDS",
            _get(source, "SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)),
        ),
        app_origin=_get(source, "APP_ORIGIN", DEFAULT_APP_ORIGIN),
        cookie_secure=_parse_bool("COOKIE_SECURE", _get(source, "COOKIE_SECURE", "false")),
        app_env=_get(source, "APP_ENV", DEFAULT_APP_ENV),
    )
