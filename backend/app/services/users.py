"""User account storage: creation, lookup, and profile updates.

Each service call opens, uses, and closes its own connection on the calling
thread (PLAN.md §2). Emails must already be normalized (trimmed, lowercased)
by the schema layer; the `UNIQUE` constraint is the authoritative duplicate
check, so registration cannot race into two accounts.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db import connect, write_transaction
from app.timestamps import now_timestamp

USER_COLUMNS = (
    "id",
    "email",
    "password_hash",
    "display_name",
    "bodyweight_default_kg",
    "utc_offset_minutes",
    "created_at",
    "updated_at",
)

# Writable profile columns; everything else on a user row is server-controlled.
PROFILE_COLUMNS = frozenset({"display_name", "bodyweight_default_kg", "utc_offset_minutes"})


class DuplicateEmailError(Exception):
    """An account with this normalized email already exists."""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """One `users` row. Never serialized directly; APIs use explicit schemas."""

    id: str
    email: str
    password_hash: str
    display_name: str | None
    bodyweight_default_kg: int | None
    utc_offset_minutes: int
    created_at: str
    updated_at: str


def row_to_user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        password_hash=str(row["password_hash"]),
        display_name=row["display_name"],
        bodyweight_default_kg=row["bodyweight_default_kg"],
        utc_offset_minutes=int(row["utc_offset_minutes"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _select_user_sql(where: str) -> str:
    columns = ", ".join(USER_COLUMNS)
    return f"SELECT {columns} FROM users WHERE {where}"


def create_user(
    database_path: str | Path,
    *,
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> UserRecord:
    """Insert a new user; raise `DuplicateEmailError` when the email exists."""
    user_id = str(uuid.uuid4())
    now = now_timestamp()
    try:
        with connect(database_path) as conn, write_transaction(conn):
            conn.execute(
                "INSERT INTO users (id, email, password_hash, display_name, "
                "bodyweight_default_kg, utc_offset_minutes, created_at, updated_at) "
                "VALUES (:id, :email, :password_hash, :display_name, NULL, 0, :now, :now)",
                {
                    "id": user_id,
                    "email": email,
                    "password_hash": password_hash,
                    "display_name": display_name,
                    "now": now,
                },
            )
    except sqlite3.IntegrityError as exc:
        if "users.email" in str(exc):
            raise DuplicateEmailError(email) from exc
        raise
    return UserRecord(
        id=user_id,
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        bodyweight_default_kg=None,
        utc_offset_minutes=0,
        created_at=now,
        updated_at=now,
    )


def get_user_by_id(database_path: str | Path, user_id: str) -> UserRecord | None:
    with connect(database_path) as conn:
        row = conn.execute(_select_user_sql("id = :id"), {"id": user_id}).fetchone()
    return row_to_user(row) if row is not None else None


def get_user_by_email(database_path: str | Path, email: str) -> UserRecord | None:
    """Look up a user by normalized email."""
    with connect(database_path) as conn:
        row = conn.execute(_select_user_sql("email = :email"), {"email": email}).fetchone()
    return row_to_user(row) if row is not None else None


def update_profile(
    database_path: str | Path,
    user_id: str,
    updates: Mapping[str, Any],
) -> UserRecord | None:
    """Apply whitelisted profile column updates; return the stored row.

    Returns `None` when the user does not exist. Column names come only from
    `PROFILE_COLUMNS`; values are always bound parameters.
    """
    if not updates:
        raise ValueError("update_profile requires at least one field")
    unknown = set(updates) - PROFILE_COLUMNS
    if unknown:
        raise ValueError(f"unknown profile fields: {sorted(unknown)}")

    assignments = ", ".join(f"{name} = :{name}" for name in sorted(updates))
    params: dict[str, Any] = dict(updates)
    params["updated_at"] = now_timestamp()
    params["id"] = user_id
    with connect(database_path) as conn, write_transaction(conn):
        cursor = conn.execute(
            f"UPDATE users SET {assignments}, updated_at = :updated_at WHERE id = :id",
            params,
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(_select_user_sql("id = :id"), {"id": user_id}).fetchone()
    return row_to_user(row) if row is not None else None
