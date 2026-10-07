"""SQLite connection and transaction helpers (PLAN.md §2, §5).

One connection per synchronous service call: opened, used, and closed on the
same thread (`check_same_thread=True`; never shared between requests). WAL is
enabled once during database initialization; `foreign_keys=ON` and a bounded
busy timeout are set on every connection. Writes run inside short
`BEGIN IMMEDIATE` transactions; a lock timeout surfaces as the retryable
`DatabaseBusyError` and never discards caller data.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# STRICT tables require SQLite >= 3.37 (PLAN.md §3); the linked runtime is
# validated at startup rather than assumed.
MIN_SQLITE_VERSION = (3, 37)
MIN_SQLITE_VERSION_TEXT = "3.37"

DEFAULT_BUSY_TIMEOUT_MS = 5_000


def _sql_casefold(value: object) -> str | None:
    """Full-Unicode case folding for SQL text.

    SQLite's built-in `LIKE`, `upper()`/`lower()`, and `COLLATE NOCASE` only
    case-fold ASCII. Every connection exposes this deterministic function so
    caseless search and ordering behave identically for any UTF-8 text
    (Python's `str.casefold()` implements Unicode case folding). Non-text
    input folds to NULL.
    """
    return value.casefold() if isinstance(value, str) else None


class DatabaseError(Exception):
    """Base class for database-layer failures."""


class DatabaseRuntimeError(DatabaseError):
    """The linked SQLite runtime is too old for STRICT tables."""


class DatabaseBusyError(DatabaseError):
    """A writer held the database lock past the busy timeout.

    Retryable: callers must preserve the client's draft and may retry the
    operation once the lock is released.
    """


def validate_sqlite_runtime(min_version: tuple[int, ...] = MIN_SQLITE_VERSION) -> None:
    """Fail startup when the linked SQLite cannot support STRICT tables."""
    if sqlite3.sqlite_version_info < min_version:
        raise DatabaseRuntimeError(
            f"SQLite >= {MIN_SQLITE_VERSION_TEXT} is required for STRICT tables; "
            f"linked runtime is {sqlite3.sqlite_version}"
        )


def initialize_database(database_path: str | Path) -> None:
    """Create the database file if needed and enable WAL once.

    The journal mode is persistent in the file header, so later connections
    do not set it again. Also validates the SQLite runtime and creates the
    parent directory.
    """
    validate_sqlite_runtime()
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
        mode = str(row[0]).lower() if row is not None else ""
        if mode != "wal":
            raise DatabaseError(f"could not enable WAL on {path} (journal_mode={mode!r})")


@contextmanager
def connect(
    database_path: str | Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> Iterator[sqlite3.Connection]:
    """Open a configured connection for the calling thread and close it.

    `isolation_level=None` gives explicit transaction control: transactions
    exist only where `BEGIN` is issued (see `write_transaction`).
    """
    if busy_timeout_ms < 0:
        raise ValueError(f"busy_timeout_ms must be nonnegative; got {busy_timeout_ms}")
    conn = sqlite3.connect(
        database_path,
        timeout=busy_timeout_ms / 1000,
        check_same_thread=True,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.create_function("casefold", 1, _sql_casefold, deterministic=True)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _rollback_quietly(conn: sqlite3.Connection) -> None:
    with contextlib.suppress(sqlite3.Error):
        conn.execute("ROLLBACK")


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside one short `BEGIN IMMEDIATE` transaction.

    Commits on clean exit; rolls back on any error so a failed write leaves
    no partial state. Lock timeouts (on `BEGIN` or `COMMIT`) raise the
    retryable `DatabaseBusyError`.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if _is_busy(exc):
            raise DatabaseBusyError(str(exc)) from exc
        raise
    try:
        yield conn
    except BaseException:
        _rollback_quietly(conn)
        raise
    try:
        conn.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        _rollback_quietly(conn)
        if _is_busy(exc):
            raise DatabaseBusyError(str(exc)) from exc
        raise
