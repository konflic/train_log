import shutil
import sqlite3
from pathlib import Path

import pytest
from helpers import (
    insert_exercise,
    insert_set,
    insert_user,
    insert_workout,
)

from app.backup import BackupError, create_backup, main, verify_database
from app.db import connect, write_transaction


def _seed_graph(conn: sqlite3.Connection) -> None:
    insert_user(conn, bodyweight_default_kg=81)
    insert_workout(conn, bodyweight_kg=80, ended_at="2026-01-01T01:00:00Z")
    insert_exercise(conn)
    insert_set(conn, "set-1", set_index=0, reps=8, weight_kg=12, done=1)
    insert_set(conn, "set-2", set_index=1, reps=6, weight_kg=14, done=1)


def test_backup_while_wal_active_then_restore_and_verify(tmp_path: Path, migrated_db: Path) -> None:
    backup_path = tmp_path / "backups" / "backup.db"
    with connect(migrated_db) as writer:
        with write_transaction(writer) as txn:
            _seed_graph(txn)
        # The writer is still open, so the committed data lives in the -wal
        # file and a plain file copy of the main database would be stale.
        wal_path = Path(f"{migrated_db}-wal")
        assert wal_path.exists()
        assert wal_path.stat().st_size > 0
        create_backup(migrated_db, backup_path)

    assert backup_path.exists()
    # A backup is a single self-contained file (no WAL sidecars).
    assert not Path(f"{backup_path}-wal").exists()

    restored = tmp_path / "restored.db"
    shutil.copyfile(backup_path, restored)
    verify_database(restored)

    with connect(restored) as conn:
        rows = conn.execute(
            "SELECT s.set_index, s.reps, s.weight_kg FROM sets s "
            "JOIN exercises e ON e.id = s.exercise_id "
            "ORDER BY s.set_index"
        ).fetchall()
        assert [(r["set_index"], r["reps"], r["weight_kg"]) for r in rows] == [
            (0, 8, 12),
            (1, 6, 14),
        ]
        workout = conn.execute(
            "SELECT bodyweight_kg, ended_at FROM workouts WHERE id = 'workout-1'"
        ).fetchone()
        assert workout is not None
        assert int(workout["bodyweight_kg"]) == 80
        assert workout["ended_at"] == "2026-01-01T01:00:00Z"
        user = conn.execute("SELECT utc_offset_minutes FROM users WHERE id = 'user-1'").fetchone()
        assert user is not None
        assert int(user["utc_offset_minutes"]) == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_verify_passes_on_empty_migrated_database(migrated_db: Path) -> None:
    verify_database(migrated_db)


def test_backup_refuses_to_overwrite(tmp_path: Path, migrated_db: Path) -> None:
    destination = tmp_path / "backup.db"
    create_backup(migrated_db, destination)
    with pytest.raises(FileExistsError):
        create_backup(migrated_db, destination)


def test_backup_rejects_missing_source_without_creating_files(tmp_path: Path) -> None:
    source = tmp_path / "missing.db"
    destination = tmp_path / "backup.db"

    with pytest.raises(FileNotFoundError, match="backup source"):
        create_backup(source, destination)

    assert not source.exists()
    assert not destination.exists()


def test_failed_backup_removes_incomplete_destination(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.db"
    destination = tmp_path / "backup.db"
    source.write_bytes(b"this is not a sqlite database")

    with pytest.raises(BackupError, match="cannot back up"):
        create_backup(source, destination)

    assert not destination.exists()


def test_verify_rejects_non_database_file(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is definitely not a sqlite database file" * 10)
    with pytest.raises(BackupError, match="cannot verify"):
        verify_database(junk)


def test_verify_detects_foreign_key_violation(migrated_db: Path) -> None:
    with connect(migrated_db) as conn, write_transaction(conn) as txn:
        insert_user(txn)
        insert_workout(txn)
    # Corrupt referential integrity behind the checker's back.
    raw = sqlite3.connect(migrated_db)
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("DELETE FROM users WHERE id = 'user-1'")
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(BackupError, match="foreign_key_check"):
        verify_database(migrated_db)


def test_cli_backup_and_verify(
    tmp_path: Path, migrated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "cli-backup.db"
    assert main(["backup", str(migrated_db), str(destination)]) == 0
    assert main(["verify", str(destination)]) == 0
    assert main(["backup", str(migrated_db), str(destination)]) == 1
    captured = capsys.readouterr()
    assert "backup written" in captured.out
    assert "verification passed" in captured.out
    assert "error" in captured.err
