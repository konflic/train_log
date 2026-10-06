"""Explicit database migration command (PLAN.md §5).

Numbered SQL files in `migrations/` are applied once, in ascending version
order, each inside its own transaction together with its `schema_migrations`
record; the runner stops at the first failure and rolls that migration back
completely. Run migrations explicitly before starting the API (never per
worker):

    cd backend && python migrate.py       # honors DATABASE_PATH

Migration SQL files must not contain transaction control (BEGIN/COMMIT) or
PRAGMA statements; the runner owns transaction boundaries and connection
pragmas.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import load_settings
from app.db import DatabaseError, connect, initialize_database

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

FILENAME_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
        CHECK (applied_at GLOB
               '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT
"""


class MigrationError(Exception):
    """A migration file is invalid, or applying one failed."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str


def utc_now_timestamp() -> str:
    """Canonical UTC timestamp for migration records."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read and order every migration file; reject malformed directories."""
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")
    found: dict[int, Migration] = {}
    for path in sorted(directory.iterdir()):
        match = FILENAME_PATTERN.match(path.name)
        if match is None or not path.is_file():
            raise MigrationError(
                f"unexpected entry in migrations directory: {path.name!r} "
                "(expected NNNN_snake_case_name.sql)"
            )
        version = int(match.group("version"))
        if version in found:
            raise MigrationError(f"duplicate migration version {version:04d}: {path.name!r}")
        found[version] = Migration(
            version=version,
            name=path.stem,
            path=path,
            sql=path.read_text(encoding="utf-8"),
        )
    return [found[version] for version in sorted(found)]


def migrate(database_path: str | Path, migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Apply every pending migration; return the ones applied by this call.

    Re-running against an up-to-date database is a no-op. A database that
    records versions absent from `migrations_dir` is refused (it was
    migrated by newer code; files were not lost by accident).
    """
    available = discover_migrations(migrations_dir)
    initialize_database(database_path)
    applied: list[Migration] = []
    with connect(database_path) as conn:
        conn.execute(SCHEMA_MIGRATIONS_DDL)
        recorded = {
            int(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations")
        }
        unknown = sorted(recorded - {m.version for m in available})
        if unknown:
            raise MigrationError(
                f"database records migrations missing from {migrations_dir}: "
                f"{[f'{v:04d}' for v in unknown]}"
            )
        for migration in available:
            if migration.version in recorded:
                continue
            _apply_one(conn, migration)
            applied.append(migration)
    return applied


def _apply_one(conn: sqlite3.Connection, migration: Migration) -> None:
    """Run one migration and its version record inside a single transaction.

    `executescript` would implicitly commit an open transaction, so the
    explicit `BEGIN IMMEDIATE` is part of the script and the script leaves
    the transaction open; the parameterized version insert joins it and a
    single `COMMIT` makes both durable. Any failure rolls everything back:
    no partial DDL/data and no version record.
    """
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{migration.sql}")
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (:version, :name, :applied_at)",
            {
                "version": migration.version,
                "name": migration.name,
                "applied_at": utc_now_timestamp(),
            },
        )
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise MigrationError(f"migration {migration.name} failed: {exc}") from exc


def main() -> int:
    settings = load_settings()
    database_path = Path(settings.database_path)
    print(f"migrating {database_path}")
    try:
        applied = migrate(database_path)
    except (MigrationError, DatabaseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if applied:
        for migration in applied:
            print(f"applied {migration.name}")
    else:
        print("no pending migrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
