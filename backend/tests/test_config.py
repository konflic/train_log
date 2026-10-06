import pytest

from app.config import (
    DEFAULT_APP_ENV,
    DEFAULT_APP_ORIGIN,
    DEFAULT_DATABASE_PATH,
    DEFAULT_SESSION_TTL_SECONDS,
    load_settings,
)


def test_defaults_for_local_development() -> None:
    settings = load_settings(env={})
    assert settings.database_path == DEFAULT_DATABASE_PATH
    assert settings.session_ttl_seconds == DEFAULT_SESSION_TTL_SECONDS
    assert settings.app_origin == DEFAULT_APP_ORIGIN
    assert settings.cookie_secure is False
    assert settings.app_env == DEFAULT_APP_ENV


def test_environment_overrides() -> None:
    settings = load_settings(
        env={
            "DATABASE_PATH": "/var/lib/basefit/basefit.db",
            "SESSION_TTL_SECONDS": "3600",
            "APP_ORIGIN": "https://basefit.example.com",
            "COOKIE_SECURE": "true",
            "APP_ENV": "production",
        }
    )
    assert settings.database_path == "/var/lib/basefit/basefit.db"
    assert settings.session_ttl_seconds == 3600
    assert settings.app_origin == "https://basefit.example.com"
    assert settings.cookie_secure is True
    assert settings.app_env == "production"


def test_boolean_parsing_accepts_common_spellings() -> None:
    for raw in ("1", "true", "TRUE", " yes ", "On"):
        assert load_settings(env={"COOKIE_SECURE": raw}).cookie_secure is True
    for raw in ("0", "false", "FALSE", " no ", "Off"):
        assert load_settings(env={"COOKIE_SECURE": raw}).cookie_secure is False


def test_empty_values_fall_back_to_defaults() -> None:
    settings = load_settings(
        env={
            "DATABASE_PATH": "",
            "SESSION_TTL_SECONDS": "  ",
            "COOKIE_SECURE": "",
        }
    )
    assert settings.database_path == DEFAULT_DATABASE_PATH
    assert settings.session_ttl_seconds == DEFAULT_SESSION_TTL_SECONDS
    assert settings.cookie_secure is False


@pytest.mark.parametrize("raw", ["maybe", "2"])
def test_invalid_boolean_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        load_settings(env={"COOKIE_SECURE": raw})


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "1.5"])
def test_invalid_ttl_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="SESSION_TTL_SECONDS"):
        load_settings(env={"SESSION_TTL_SECONDS": raw})
