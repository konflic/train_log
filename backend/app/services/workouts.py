"""Workout storage: idempotent creation, history listing, and graph reads.

Every lookup is scoped to the owner, so another user's workout is
indistinguishable from an unknown id (`None`, PLAN.md §4). Creation is
idempotent by fingerprint: the primary key is the authoritative race check, and
a retried create returns the existing owned row only when the canonical
`create_request_hash` (owner + validated content) matches; any other reuse of
the id is a conflict. The profile bodyweight is copied into the row inside the
write transaction and later profile edits never rewrite it (PLAN.md §4).

History listing filters by status and by local calendar dates resolved through
the user's fixed UTC offset into half-open canonical-UTC ranges; stored
timestamps share one fixed-width format, so text comparison is chronological.
The order `(started_at DESC, id DESC)` is a total order and therefore stable
across pages. Graph reads use exactly three queries (workout, exercises, sets)
regardless of graph size — never one query per set (PLAN.md §5).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.timestamps import now_timestamp, to_timestamp

WORKOUT_COLUMNS = (
    "id",
    "user_id",
    "name",
    "started_at",
    "ended_at",
    "notes",
    "bodyweight_kg",
    "revision",
    "create_request_hash",
    "last_save_id",
    "last_save_hash",
    "created_at",
    "updated_at",
)

EXERCISE_COLUMNS = (
    "id",
    "catalog_id",
    "order_index",
    "notes",
    "load_type",
    "bodyweight_percent",
    "side_count",
)

SET_COLUMNS = (
    "id",
    "exercise_id",
    "set_index",
    "reps",
    "weight_kg",
    "bw_percent_override",
    "rpe",
    "side",
    "done",
)

WorkoutStatus = Literal["active", "finished"]


class CreateConflictError(Exception):
    """The workout id exists with different content or a different owner."""


@dataclass(frozen=True, slots=True)
class WorkoutRecord:
    """One `workouts` row. Never serialized directly; APIs use schemas."""

    id: str
    user_id: str
    name: str | None
    started_at: str
    ended_at: str | None
    notes: str | None
    bodyweight_kg: int | None
    revision: int
    create_request_hash: str
    last_save_id: str | None
    last_save_hash: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SetRecord:
    """One `sets` row with the stored 0/1 flag decoded."""

    id: str
    exercise_id: str
    set_index: int
    reps: int | None
    weight_kg: int | None
    bw_percent_override: int | None
    rpe: int | None
    side: str
    done: bool


@dataclass(frozen=True, slots=True)
class ExerciseRecord:
    """One `exercises` row with its snapshot and ordered sets."""

    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    load_type: str
    bodyweight_percent: int | None
    side_count: int
    sets: tuple[SetRecord, ...]


@dataclass(frozen=True, slots=True)
class WorkoutGraph:
    """A workout row plus its complete ordered exercise/set graph."""

    workout: WorkoutRecord
    exercises: tuple[ExerciseRecord, ...]


@dataclass(frozen=True, slots=True)
class WorkoutPage:
    """One history page plus the total number of matching workouts."""

    items: list[WorkoutRecord]
    total: int


def row_to_workout(row: sqlite3.Row) -> WorkoutRecord:
    return WorkoutRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=row["name"],
        started_at=str(row["started_at"]),
        ended_at=row["ended_at"],
        notes=row["notes"],
        bodyweight_kg=row["bodyweight_kg"],
        revision=int(row["revision"]),
        create_request_hash=str(row["create_request_hash"]),
        last_save_id=row["last_save_id"],
        last_save_hash=row["last_save_hash"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def create_request_hash(*, user_id: str, workout_id: str, started_at: str) -> str:
    """Fingerprint a validated create request canonically (PLAN.md §6).

    The owner is part of the fingerprint: two users submitting identical
    content for the same UUID never match, so a create can never return or
    overwrite another user's row. Compact sorted-key JSON over already
    normalized values makes the hash independent of field order and spelling.
    """
    canonical = json.dumps(
        {"user_id": user_id, "id": workout_id, "started_at": started_at},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_workout(
    database_path: str | Path,
    *,
    owner_id: str,
    workout_id: str,
    started_at: str,
    request_hash: str,
) -> tuple[WorkoutRecord, bool]:
    """Insert an empty active workout at revision 0; return it plus `created`.

    `created=False` means an idempotent retry: the id already belongs to this
    owner with the same fingerprint, and the existing row is returned
    unchanged. Any other id reuse raises `CreateConflictError`. The profile
    bodyweight is copied inside the same transaction; an unknown profile stays
    `null`.
    """
    now = now_timestamp()
    with connect(database_path) as conn, write_transaction(conn):
        profile = conn.execute(
            "SELECT bodyweight_default_kg FROM users WHERE id = :owner_id",
            {"owner_id": owner_id},
        ).fetchone()
        bodyweight_kg = profile["bodyweight_default_kg"] if profile is not None else None
        try:
            conn.execute(
                "INSERT INTO workouts (id, user_id, name, started_at, ended_at, "
                "notes, bodyweight_kg, revision, create_request_hash, "
                "last_save_id, last_save_hash, created_at, updated_at) "
                "VALUES (:id, :user_id, NULL, :started_at, NULL, NULL, "
                ":bodyweight_kg, 0, :create_request_hash, NULL, NULL, :now, :now)",
                {
                    "id": workout_id,
                    "user_id": owner_id,
                    "started_at": started_at,
                    "bodyweight_kg": bodyweight_kg,
                    "create_request_hash": request_hash,
                    "now": now,
                },
            )
        except sqlite3.IntegrityError as exc:
            # The primary key is the authoritative race check: re-read the
            # winner and accept only an exact owner+fingerprint match. A
            # missing owner fails the user FK and is re-raised unchanged.
            if "workouts.id" not in str(exc):
                raise
            existing = conn.execute(
                f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE id = :id",
                {"id": workout_id},
            ).fetchone()
            if (
                existing is None
                or str(existing["user_id"]) != owner_id
                or str(existing["create_request_hash"]) != request_hash
            ):
                raise CreateConflictError(workout_id) from exc
            return row_to_workout(existing), False
        return (
            WorkoutRecord(
                id=workout_id,
                user_id=owner_id,
                name=None,
                started_at=started_at,
                ended_at=None,
                notes=None,
                bodyweight_kg=bodyweight_kg,
                revision=0,
                create_request_hash=request_hash,
                last_save_id=None,
                last_save_hash=None,
                created_at=now,
                updated_at=now,
            ),
            True,
        )


def local_date_bounds(
    *,
    date_from: date | None,
    date_to: date | None,
    utc_offset_minutes: int,
) -> tuple[str | None, str | None]:
    """Resolve inclusive local dates into a half-open canonical-UTC range.

    A local day starts at midnight in the user's fixed UTC offset, which is
    `offset` minutes ahead of UTC; both `date_from` and `date_to` are
    inclusive, so the upper bound is midnight after `date_to`.
    """

    def midnight_utc(day: date) -> str:
        moment = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(
            minutes=utc_offset_minutes
        )
        return to_timestamp(moment)

    start = midnight_utc(date_from) if date_from is not None else None
    # date_to is inclusive; the schema bounds keep +1 day inside datetime range.
    end = midnight_utc(date_to + timedelta(days=1)) if date_to is not None else None
    return start, end


def list_workouts(
    database_path: str | Path,
    *,
    user_id: str,
    limit: int,
    offset: int,
    status: WorkoutStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    utc_offset_minutes: int = 0,
) -> WorkoutPage:
    """One stable-ordered history page for the owner, newest first."""
    if limit < 1:
        raise ValueError(f"limit must be positive; got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be nonnegative; got {offset}")
    if offset > MAX_SAFE_INTEGER:
        raise ValueError(f"offset must not exceed {MAX_SAFE_INTEGER}; got {offset}")
    if status not in (None, "active", "finished"):
        raise ValueError(f"unknown status filter: {status!r}")

    clauses = ["user_id = :user_id"]
    params: dict[str, Any] = {"user_id": user_id}
    if status == "active":
        clauses.append("ended_at IS NULL")
    elif status == "finished":
        clauses.append("ended_at IS NOT NULL")
    started_from, started_to = local_date_bounds(
        date_from=date_from, date_to=date_to, utc_offset_minutes=utc_offset_minutes
    )
    if started_from is not None:
        # Canonical UTC text has one fixed width, so text order is time order.
        clauses.append("started_at >= :started_from")
        params["started_from"] = started_from
    if started_to is not None:
        clauses.append("started_at < :started_to")
        params["started_to"] = started_to
    where = " AND ".join(clauses)

    with connect(database_path) as conn, conn:
        # Keep the count and page rows on one snapshot while saves commit.
        conn.execute("BEGIN")
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM workouts WHERE {where}", params
        ).fetchone()
        rows = conn.execute(
            f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE {where} "
            "ORDER BY started_at DESC, id DESC LIMIT :limit OFFSET :offset",
            dict(params, limit=limit, offset=offset),
        ).fetchall()
    return WorkoutPage(items=[row_to_workout(row) for row in rows], total=int(total_row["total"]))


def get_workout_graph(
    database_path: str | Path, workout_id: str, *, user_id: str
) -> WorkoutGraph | None:
    """Fetch the owned workout and its full graph; foreign/unknown are `None`.

    Exactly three queries regardless of graph size: the workout row, its
    exercises in stored order, and all their sets joined through the exercises
    in `(order_index, set_index)` order.
    """
    with connect(database_path) as conn, conn:
        # All three graph queries must describe the same committed revision.
        conn.execute("BEGIN")
        workout_row = conn.execute(
            f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts "
            "WHERE id = :id AND user_id = :user_id",
            {"id": workout_id, "user_id": user_id},
        ).fetchone()
        if workout_row is None:
            return None
        exercise_rows = conn.execute(
            f"SELECT {', '.join(EXERCISE_COLUMNS)} FROM exercises "
            "WHERE workout_id = :id ORDER BY order_index",
            {"id": workout_id},
        ).fetchall()
        set_rows = conn.execute(
            f"SELECT {', '.join(f's.{name}' for name in SET_COLUMNS)} "
            "FROM sets s JOIN exercises e ON e.id = s.exercise_id "
            "WHERE e.workout_id = :id ORDER BY e.order_index, s.set_index",
            {"id": workout_id},
        ).fetchall()

    sets_by_exercise: dict[str, list[SetRecord]] = {str(row["id"]): [] for row in exercise_rows}
    for row in set_rows:
        sets_by_exercise[str(row["exercise_id"])].append(
            SetRecord(
                id=str(row["id"]),
                exercise_id=str(row["exercise_id"]),
                set_index=int(row["set_index"]),
                reps=row["reps"],
                weight_kg=row["weight_kg"],
                bw_percent_override=row["bw_percent_override"],
                rpe=row["rpe"],
                side=str(row["side"]),
                done=bool(row["done"]),
            )
        )
    exercises = tuple(
        ExerciseRecord(
            id=str(row["id"]),
            catalog_id=str(row["catalog_id"]),
            order_index=int(row["order_index"]),
            notes=row["notes"],
            load_type=str(row["load_type"]),
            bodyweight_percent=row["bodyweight_percent"],
            side_count=int(row["side_count"]),
            sets=tuple(sets_by_exercise[str(row["id"])]),
        )
        for row in exercise_rows
    )
    return WorkoutGraph(workout=row_to_workout(workout_row), exercises=exercises)
