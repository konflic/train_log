"""Row-insertion helpers shared by schema, migration, and backup tests.

Value parameters intentionally accept wrong types (`float`, `str`) so tests
can assert STRICT/CHECK rejection at the database layer.
"""

from __future__ import annotations

import sqlite3

TS = "2026-01-01T00:00:00Z"

Number = int | float | str | None


def insert_user(
    conn: sqlite3.Connection,
    user_id: str = "user-1",
    *,
    email: str | None = None,
    bodyweight_default_kg: Number = None,
    utc_offset_minutes: Number = 0,
    created_at: str = TS,
) -> None:
    conn.execute(
        "INSERT INTO users (id, email, password_hash, bodyweight_default_kg, "
        "utc_offset_minutes, created_at, updated_at) "
        "VALUES (:id, :email, 'hash', :bodyweight, :offset, :created_at, :created_at)",
        {
            "id": user_id,
            "email": f"{user_id}@example.com" if email is None else email,
            "bodyweight": bodyweight_default_kg,
            "offset": utc_offset_minutes,
            "created_at": created_at,
        },
    )


def insert_session(
    conn: sqlite3.Connection,
    token_hash: str = "token-hash-1",
    *,
    user_id: str = "user-1",
    created_at: str = TS,
    expires_at: str = "2026-01-02T00:00:00Z",
) -> None:
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
        "VALUES (:token_hash, :user_id, :created_at, :expires_at)",
        {
            "token_hash": token_hash,
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": expires_at,
        },
    )


def insert_catalog_entry(
    conn: sqlite3.Connection,
    entry_id: str = "cat-custom-1",
    *,
    name: str = "Custom Curl",
    muscle_group: str = "arms",
    equipment: str = "dumbbell",
    load_type: str = "split_weight",
    bodyweight_percent: Number = None,
    side_count: Number = 2,
    is_default: Number = 0,
    created_by: str | None = "user-1",
) -> None:
    conn.execute(
        "INSERT INTO exercise_catalog (id, name, muscle_group, equipment, "
        "load_type, bodyweight_percent, side_count, is_default, created_by) "
        "VALUES (:id, :name, :muscle_group, :equipment, :load_type, "
        ":bodyweight_percent, :side_count, :is_default, :created_by)",
        {
            "id": entry_id,
            "name": name,
            "muscle_group": muscle_group,
            "equipment": equipment,
            "load_type": load_type,
            "bodyweight_percent": bodyweight_percent,
            "side_count": side_count,
            "is_default": is_default,
            "created_by": created_by,
        },
    )


def insert_workout(
    conn: sqlite3.Connection,
    workout_id: str = "workout-1",
    *,
    user_id: str = "user-1",
    started_at: str = TS,
    ended_at: str | None = None,
    bodyweight_kg: Number = None,
    revision: Number = 0,
    create_request_hash: str = "create-hash",
    last_save_id: str | None = None,
    last_save_hash: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO workouts (id, user_id, started_at, ended_at, "
        "bodyweight_kg, revision, create_request_hash, last_save_id, "
        "last_save_hash, created_at, updated_at) "
        "VALUES (:id, :user_id, :started_at, :ended_at, :bodyweight_kg, "
        ":revision, :create_request_hash, :last_save_id, :last_save_hash, "
        ":started_at, :started_at)",
        {
            "id": workout_id,
            "user_id": user_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "bodyweight_kg": bodyweight_kg,
            "revision": revision,
            "create_request_hash": create_request_hash,
            "last_save_id": last_save_id,
            "last_save_hash": last_save_hash,
        },
    )


def insert_exercise(
    conn: sqlite3.Connection,
    exercise_id: str = "exercise-1",
    *,
    workout_id: str = "workout-1",
    catalog_id: str = "dumbbell-curl",
    order_index: Number = 0,
    load_type: str = "split_weight",
    bodyweight_percent: Number = None,
    side_count: Number = 2,
) -> None:
    conn.execute(
        "INSERT INTO exercises (id, workout_id, catalog_id, order_index, "
        "load_type, bodyweight_percent, side_count) "
        "VALUES (:id, :workout_id, :catalog_id, :order_index, :load_type, "
        ":bodyweight_percent, :side_count)",
        {
            "id": exercise_id,
            "workout_id": workout_id,
            "catalog_id": catalog_id,
            "order_index": order_index,
            "load_type": load_type,
            "bodyweight_percent": bodyweight_percent,
            "side_count": side_count,
        },
    )


def insert_set(
    conn: sqlite3.Connection,
    set_id: str = "set-1",
    *,
    exercise_id: str = "exercise-1",
    set_index: Number = 0,
    reps: Number = 8,
    weight_kg: Number = 12,
    bw_percent_override: Number = None,
    rpe: Number = None,
    side: str = "bilateral",
    done: Number = 1,
) -> None:
    conn.execute(
        "INSERT INTO sets (id, exercise_id, set_index, reps, weight_kg, "
        "bw_percent_override, rpe, side, done) "
        "VALUES (:id, :exercise_id, :set_index, :reps, :weight_kg, "
        ":bw_percent_override, :rpe, :side, :done)",
        {
            "id": set_id,
            "exercise_id": exercise_id,
            "set_index": set_index,
            "reps": reps,
            "weight_kg": weight_kg,
            "bw_percent_override": bw_percent_override,
            "rpe": rpe,
            "side": side,
            "done": done,
        },
    )


def insert_graph(
    conn: sqlite3.Connection,
    *,
    user_id: str = "user-1",
    workout_id: str = "workout-1",
    exercise_id: str = "exercise-1",
    catalog_id: str = "dumbbell-curl",
) -> None:
    """Insert a minimal user → workout → exercise chain (no sets)."""
    insert_user(conn, user_id)
    insert_workout(conn, workout_id, user_id=user_id)
    insert_exercise(conn, exercise_id, workout_id=workout_id, catalog_id=catalog_id)
