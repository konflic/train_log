"""Backup and restore verification for the SQLite database (PLAN.md §5).

Backups use the online `sqlite3.Connection.backup()` API, which is safe
while WAL is active; never plain-copy the main database file. A restored
backup is verified with `PRAGMA integrity_check`, `PRAGMA foreign_key_check`,
and a representative workout-graph read. Back up before destructive schema
migrations.

CLI:
    python -m app.backup backup <source.db> <backup.db>
    python -m app.backup verify <database.db>
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from app.db import DatabaseError, connect


class BackupError(Exception):
    """A backup could not be created, or a database failed verification."""


def create_backup(source_path: str | Path, backup_path: str | Path) -> None:
    """Copy a live database to `backup_path` with the sqlite3 backup API.

    Produces a single self-contained file (no WAL sidecars) and refuses to
    overwrite an existing file.
    """
    source_file = Path(source_path)
    if not source_file.is_file():
        raise FileNotFoundError(f"backup source does not exist or is not a file: {source_file}")

    destination = Path(backup_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        source = sqlite3.connect(f"{source_file.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"cannot open backup source {source_file}: {exc}") from exc

    try:
        # Reserve the name atomically so a concurrent process cannot be
        # overwritten between an existence check and sqlite3.connect().
        with destination.open("xb"):
            pass
        try:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        except sqlite3.Error as exc:
            destination.unlink(missing_ok=True)
            raise BackupError(f"cannot back up {source_file}: {exc}") from exc
    finally:
        source.close()


def verify_database(database_path: str | Path) -> None:
    """Verify a restored (or live) database; raise `BackupError` on failure.

    Checks: `integrity_check` reports ok, `foreign_key_check` finds no
    violations, and the most recent workout graph is readable with a fixed
    small number of queries. An empty database passes when its schema reads
    cleanly.
    """
    try:
        with connect(database_path) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            integrity = str(row[0]) if row is not None else ""
            if integrity != "ok":
                raise BackupError(f"integrity_check failed: {integrity}")
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise BackupError(
                    f"foreign_key_check reported {len(violations)} violation(s): "
                    f"{[tuple(v) for v in violations[:5]]}"
                )
            _read_representative_workout(conn)
    except sqlite3.Error as exc:
        raise BackupError(f"cannot verify {database_path}: {exc}") from exc


def _read_representative_workout(conn: sqlite3.Connection) -> None:
    """Read the most recent workout graph (workout, exercises, sets)."""
    workout = conn.execute(
        "SELECT id FROM workouts ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if workout is None:
        # Still exercise every graph table so a missing/broken schema fails.
        for table in ("users", "exercise_catalog", "exercises", "sets"):
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return
    conn.execute(
        "SELECT id, catalog_id, order_index FROM exercises "
        "WHERE workout_id = :workout_id ORDER BY order_index, id",
        {"workout_id": workout["id"]},
    ).fetchall()
    conn.execute(
        "SELECT s.id, s.set_index, s.reps, s.weight_kg FROM sets s "
        "JOIN exercises e ON e.id = s.exercise_id "
        "WHERE e.workout_id = :workout_id "
        "ORDER BY e.order_index, s.set_index, s.id",
        {"workout_id": workout["id"]},
    ).fetchall()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.backup",
        description="Back up a live BaseFit database or verify a restored one.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_cmd = subparsers.add_parser(
        "backup", help="create a consistent backup of a live database"
    )
    backup_cmd.add_argument("source", help="database file to back up")
    backup_cmd.add_argument("destination", help="backup file to create (must not exist)")
    verify_cmd = subparsers.add_parser(
        "verify", help="run integrity, foreign-key, and workout-read checks"
    )
    verify_cmd.add_argument("database", help="database file to verify")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            create_backup(args.source, args.destination)
            print(f"backup written to {args.destination}")
        else:
            verify_database(args.database)
            print(f"verification passed: {args.database}")
    except (BackupError, DatabaseError, FileExistsError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
