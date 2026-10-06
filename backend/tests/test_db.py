import sqlite3
import threading
from pathlib import Path

import pytest

from app.db import (
    DatabaseBusyError,
    DatabaseRuntimeError,
    connect,
    initialize_database,
    validate_sqlite_runtime,
    write_transaction,
)

INSERT_USER = (
    "INSERT INTO users (id, email, password_hash, created_at, updated_at) "
    "VALUES ('u1', 'u1@example.com', 'hash', '2026-01-01T00:00:00Z', "
    "'2026-01-01T00:00:00Z')"
)


def test_validate_sqlite_runtime_accepts_linked_version() -> None:
    # The gate environment must satisfy PLAN.md §3 (>= 3.37 for STRICT).
    validate_sqlite_runtime()


def test_validate_sqlite_runtime_rejects_too_old() -> None:
    with pytest.raises(DatabaseRuntimeError, match="STRICT"):
        validate_sqlite_runtime(min_version=(99, 0))


def test_initialize_database_enables_wal_and_creates_parents(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "dir" / "basefit.db"
    initialize_database(database_path)
    assert database_path.exists()
    with connect(database_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "wal"
    # Re-initializing an existing database is a no-op, not an error.
    initialize_database(database_path)
    with connect(database_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "wal"


def test_connect_sets_foreign_keys_and_row_factory(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row is not None
        assert int(row[0]) == 1
        entry = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' LIMIT 1"
        ).fetchone()
        assert isinstance(entry, sqlite3.Row)
        assert entry["name"]


def test_connection_is_thread_confined(migrated_db: Path) -> None:
    errors: list[Exception] = []

    with connect(migrated_db) as conn:

        def use_from_other_thread() -> None:
            try:
                conn.execute("SELECT 1")
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=use_from_other_thread)
        thread.start()
        thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)


def test_write_transaction_commits(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            txn.execute(INSERT_USER)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        assert count is not None
        assert int(count[0]) == 1


def test_write_transaction_rolls_back_on_error(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with pytest.raises(RuntimeError, match="boom"), write_transaction(conn) as txn:
            txn.execute(INSERT_USER)
            raise RuntimeError("boom")
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        assert count is not None
        assert int(count[0]) == 0
        # The connection is usable again after the rollback.
        with write_transaction(conn) as txn:
            txn.execute(INSERT_USER)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        assert count is not None
        assert int(count[0]) == 1


def test_lock_timeout_is_retryable_and_succeeds_after_release(
    migrated_db: Path,
) -> None:
    with connect(migrated_db) as writer:
        # Hold the write lock outside any helper transaction.
        writer.execute("BEGIN IMMEDIATE")
        try:
            with connect(migrated_db, busy_timeout_ms=50) as blocked:
                with pytest.raises(DatabaseBusyError), write_transaction(blocked) as txn:
                    txn.execute(INSERT_USER)
                assert not blocked.in_transaction
        finally:
            writer.execute("ROLLBACK")

    # Retrying after the lock is released succeeds; nothing was discarded.
    with connect(migrated_db, busy_timeout_ms=50) as retry:
        with write_transaction(retry) as txn:
            txn.execute(INSERT_USER)
        count = retry.execute("SELECT COUNT(*) FROM users").fetchone()
        assert count is not None
        assert int(count[0]) == 1


def test_negative_busy_timeout_rejected(migrated_db: Path) -> None:
    with (
        pytest.raises(ValueError, match="busy_timeout_ms"),
        connect(migrated_db, busy_timeout_ms=-1),
    ):
        pass
