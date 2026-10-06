"""Shared pytest setup and fixtures.

`migrate.py` lives at the backend root (not inside the installed `app`
package), so the backend root is added to `sys.path` before test modules
import it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture()
def migrated_db(tmp_path: Path) -> Path:
    """A temporary database migrated to the latest real schema."""
    from migrate import migrate

    database_path = tmp_path / "basefit.db"
    migrate(database_path)
    return database_path
