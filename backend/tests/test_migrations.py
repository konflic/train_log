import shutil
from pathlib import Path

import pytest
from helpers import (
    insert_catalog_entry,
    insert_exercise,
    insert_set,
    insert_user,
    insert_workout,
)

import migrate
from app.db import connect, write_transaction
from migrate import MigrationError, discover_migrations

EXPECTED_TABLES = {
    "users",
    "sessions",
    "exercise_catalog",
    "workouts",
    "exercises",
    "sets",
    "schema_migrations",
}

EXPECTED_INDEXES = {
    "idx_sessions_expires_at",
    "uidx_exercise_catalog_default_name",
    "uidx_exercise_catalog_owner_name",
    "idx_workouts_user_started",
    "idx_exercises_catalog_workout",
}


def _write(directory: Path, filename: str, sql: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(sql, encoding="utf-8")


def test_migrate_from_empty_creates_strict_schema_and_seed(tmp_path: Path) -> None:
    database_path = tmp_path / "basefit.db"
    applied = migrate.migrate(database_path)
    assert [m.name for m in applied] == ["0001_initial_schema", "0002_seed_catalog"]

    with connect(database_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= EXPECTED_TABLES

        strict_rows = conn.execute(
            "SELECT name, strict FROM pragma_table_list "
            "WHERE type = 'table' AND schema = 'main' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        assert strict_rows
        assert all(int(row["strict"]) == 1 for row in strict_rows)

        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert indexes >= EXPECTED_INDEXES

        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        versions = [
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        assert versions == [1, 2]

        seed = conn.execute(
            "SELECT COUNT(*) AS n FROM exercise_catalog WHERE is_default = 1 AND created_by IS NULL"
        ).fetchone()
        assert seed is not None
        assert int(seed["n"]) >= 10

        journal = conn.execute("PRAGMA journal_mode").fetchone()
        assert journal is not None
        assert str(journal[0]).lower() == "wal"


def test_rerun_is_noop(tmp_path: Path) -> None:
    database_path = tmp_path / "basefit.db"
    migrate.migrate(database_path)
    with connect(database_path) as conn:
        before = [
            (row["version"], row["name"], row["applied_at"])
            for row in conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            )
        ]
        seed_before = conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()

    assert migrate.migrate(database_path) == []

    with connect(database_path) as conn:
        after = [
            (row["version"], row["name"], row["applied_at"])
            for row in conn.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            )
        ]
        seed_after = conn.execute("SELECT COUNT(*) FROM exercise_catalog").fetchone()
    assert after == before
    assert seed_after is not None and seed_before is not None
    assert int(seed_after[0]) == int(seed_before[0])


def test_failed_migration_rolls_back_completely(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write(
        migrations_dir,
        "0001_ok.sql",
        "CREATE TABLE ok_table (id INTEGER NOT NULL PRIMARY KEY) STRICT;\n"
        "INSERT INTO ok_table (id) VALUES (1);",
    )
    _write(
        migrations_dir,
        "0002_bad.sql",
        "CREATE TABLE bad_table (id INTEGER NOT NULL PRIMARY KEY) STRICT;\n"
        "INSERT INTO bad_table (id) VALUES (1);\n"
        "INSERT INTO missing_table (id) VALUES (2);",
    )
    database_path = tmp_path / "basefit.db"

    with pytest.raises(MigrationError, match="0002_bad"):
        migrate.migrate(database_path, migrations_dir=migrations_dir)

    with connect(database_path) as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        # The successful migration persists; the failed one leaves no DDL...
        assert "ok_table" in names
        assert "bad_table" not in names
        # ...no data...
        ok_count = conn.execute("SELECT COUNT(*) FROM ok_table").fetchone()
        assert ok_count is not None
        assert int(ok_count[0]) == 1
        # ...and no version record.
        versions = [
            int(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations")
        ]
        assert versions == [1]

    # After fixing the file, a re-run applies only the pending migration.
    _write(
        migrations_dir,
        "0002_bad.sql",
        "CREATE TABLE bad_table (id INTEGER NOT NULL PRIMARY KEY) STRICT;",
    )
    applied = migrate.migrate(database_path, migrations_dir=migrations_dir)
    assert [m.version for m in applied] == [2]
    with connect(database_path) as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "bad_table" in names


@pytest.mark.parametrize("forbidden", ["COMMIT", "ROLLBACK", "PRAGMA user_version = 7"])
def test_migration_cannot_escape_runner_transaction(tmp_path: Path, forbidden: str) -> None:
    migrations_dir = tmp_path / "migrations"
    _write(
        migrations_dir,
        "0001_forbidden.sql",
        f"CREATE TABLE partial_state (id INTEGER NOT NULL PRIMARY KEY) STRICT;\n{forbidden};",
    )
    database_path = tmp_path / "basefit.db"

    with pytest.raises(MigrationError, match="0001_forbidden"):
        migrate.migrate(database_path, migrations_dir=migrations_dir)

    with connect(database_path) as conn:
        partial_state = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'partial_state'"
        ).fetchone()
        assert partial_state is not None
        assert int(partial_state[0]) == 0
        versions = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert versions == []
        user_version = conn.execute("PRAGMA user_version").fetchone()
        assert user_version is not None
        assert int(user_version[0]) == 0


def test_unknown_recorded_version_is_refused(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write(
        migrations_dir,
        "0001_ok.sql",
        "CREATE TABLE ok_table (id INTEGER NOT NULL PRIMARY KEY) STRICT;",
    )
    database_path = tmp_path / "basefit.db"
    migrate.migrate(database_path, migrations_dir=migrations_dir)

    with connect(database_path) as conn, write_transaction(conn) as txn:
        txn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (7, '0007_ghost', '2026-01-01T00:00:00Z')"
        )

    with pytest.raises(MigrationError, match="0007"):
        migrate.migrate(database_path, migrations_dir=migrations_dir)


def test_discovery_rejects_malformed_directories(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="not found"):
        discover_migrations(tmp_path / "missing")

    bad_name = tmp_path / "bad_name"
    _write(bad_name, "1_initial.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="unexpected"):
        discover_migrations(bad_name)

    duplicates = tmp_path / "duplicates"
    _write(duplicates, "0001_a.sql", "SELECT 1;")
    _write(duplicates, "0001_b.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="duplicate"):
        discover_migrations(duplicates)


def test_upgrade_from_previous_migration_preserves_data(tmp_path: Path) -> None:
    database_path = tmp_path / "basefit.db"
    previous_dir = tmp_path / "previous"
    previous_dir.mkdir()
    shutil.copy(
        migrate.MIGRATIONS_DIR / "0001_initial_schema.sql",
        previous_dir / "0001_initial_schema.sql",
    )
    assert [m.version for m in migrate.migrate(database_path, previous_dir)] == [1]

    # Representative data recorded while the database was one version behind.
    with connect(database_path) as conn, write_transaction(conn) as txn:
        insert_user(txn, bodyweight_default_kg=81, utc_offset_minutes=180)
        insert_catalog_entry(txn, name="My Curl")
        insert_workout(txn, bodyweight_kg=80)
        insert_exercise(txn, catalog_id="cat-custom-1")
        insert_set(txn, reps=8, weight_kg=12, done=1)

    assert [m.version for m in migrate.migrate(database_path)] == [2]

    with connect(database_path) as conn:
        user = conn.execute(
            "SELECT email, bodyweight_default_kg, utc_offset_minutes FROM users WHERE id = 'user-1'"
        ).fetchone()
        assert user is not None
        assert user["email"] == "user-1@example.com"
        assert int(user["bodyweight_default_kg"]) == 81
        assert int(user["utc_offset_minutes"]) == 180

        set_row = conn.execute(
            "SELECT w.bodyweight_kg, e.catalog_id, s.reps, s.weight_kg "
            "FROM sets s "
            "JOIN exercises e ON e.id = s.exercise_id "
            "JOIN workouts w ON w.id = e.workout_id "
            "WHERE s.id = 'set-1'"
        ).fetchone()
        assert set_row is not None
        assert int(set_row["bodyweight_kg"]) == 80
        assert set_row["catalog_id"] == "cat-custom-1"
        assert int(set_row["reps"]) == 8
        assert int(set_row["weight_kg"]) == 12

        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert indexes >= EXPECTED_INDEXES
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        # The new seed coexists with the pre-existing custom entry.
        names = {row["name"] for row in conn.execute("SELECT name FROM exercise_catalog")}
        assert "My Curl" in names
        assert "Pull-up" in names

        versions = [
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        assert versions == [1, 2]
