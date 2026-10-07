"""Shared pytest setup and fixtures.

`migrate.py` lives at the backend root (not inside the installed `app`
package), so the backend root is added to `sys.path` before test modules
import it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# TestClient's default base_url; the CSRF check compares Origin against it.
TEST_ORIGIN = "http://testserver"


@pytest.fixture()
def migrated_db(tmp_path: Path) -> Path:
    """A temporary database migrated to the latest real schema."""
    from migrate import migrate

    database_path = tmp_path / "basefit.db"
    migrate(database_path)
    return database_path


@pytest.fixture()
def make_app(migrated_db: Path) -> Callable[..., FastAPI]:
    """Build an app over the migrated temporary database with dev defaults."""

    def _make(
        *,
        session_ttl_seconds: int = 3600,
        app_origin: str = TEST_ORIGIN,
        cookie_secure: bool = False,
        app_env: str = "development",
    ) -> FastAPI:
        return create_app(
            Settings(
                database_path=str(migrated_db),
                session_ttl_seconds=session_ttl_seconds,
                app_origin=app_origin,
                cookie_secure=cookie_secure,
                app_env=app_env,
            )
        )

    return _make


@pytest.fixture()
def api_client(make_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    """A client whose mutating requests carry the allowed Origin."""
    with TestClient(make_app(), headers={"Origin": TEST_ORIGIN}) as client:
        yield client
