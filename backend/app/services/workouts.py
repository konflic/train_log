"""Workout storage: creation, reads, and internal bulk-save validation.

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

Stage 6a adds the read-only, transaction-bound validation half of bulk-save.
It classifies every submitted nested id as retained under its exact parent or
globally new, resolves immutable exercise snapshots, and validates sets against
those snapshots before later stages perform any mutation.

Stage 6b adds `apply_validated_graph`, the internal, transaction-bound mutation
half: it replaces the writable metadata and the complete child graph from a
`ValidatedSaveGraph`, deleting omitted rows and reindexing retained rows through
temporary positions so unique indexes are never violated by a reorder. It stays
internal and leaves lifecycle/receipt fields for Stage 6c; no public PUT route
exists until the complete save protocol is implemented in Stage 6c.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.common import LoadType
from app.schemas.workouts import SaveSetRequest, SaveWorkoutRequest, Side
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
SQLITE_MAX_INTEGER = (1 << 63) - 1


class CreateConflictError(Exception):
    """The workout id exists with different content or a different owner."""


class WorkoutNotFoundError(Exception):
    """The target workout is missing or does not belong to the caller."""


class GraphConflictError(Exception):
    """A submitted nested id or retained catalog identity conflicts with storage."""


class CatalogUnavailableError(Exception):
    """A new exercise references an unknown or caller-invisible catalog row."""


class GraphValidationError(Exception):
    """A set value is invalid for its resolved historical snapshot."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


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


@dataclass(frozen=True, slots=True)
class ValidatedSet:
    """A submitted set with its dense index and persisted-id decision."""

    id: str
    set_index: int
    reps: int | None
    weight_kg: int | None
    bw_percent_override: int | None
    rpe: int | None
    side: Side
    done: bool
    is_new: bool


@dataclass(frozen=True, slots=True)
class ValidatedExercise:
    """A submitted exercise with a resolved immutable load snapshot."""

    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    sets: tuple[ValidatedSet, ...]
    is_new: bool


@dataclass(frozen=True, slots=True)
class ValidatedSaveGraph:
    """Complete writable state after all Stage 6a storage decisions."""

    revision: int
    save_id: str
    name: str | None
    notes: str | None
    bodyweight_kg: int | None
    ended_at: str | None
    exercises: tuple[ValidatedExercise, ...]


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


def _validate_set_for_snapshot(
    submitted_set: SaveSetRequest,
    *,
    field_prefix: str,
    load_type: LoadType,
    bodyweight_percent: int | None,
    side_count: int,
) -> None:
    """Validate rules that depend on a retained or newly copied snapshot."""
    allowed_sides: set[Side]
    if load_type == "split_weight" and side_count == 1:
        allowed_sides = {"left", "right"}
    else:
        allowed_sides = {"bilateral"}
    if submitted_set.side not in allowed_sides:
        raise GraphValidationError(
            f"{field_prefix}.side", "side is incompatible with the exercise snapshot"
        )
    if submitted_set.bw_percent_override is not None and bodyweight_percent is None:
        raise GraphValidationError(
            f"{field_prefix}.bw_percent_override",
            "bodyweight override requires a bodyweight contribution",
        )
    if load_type == "bodyweight" and submitted_set.weight_kg is not None:
        raise GraphValidationError(
            f"{field_prefix}.weight_kg", "bodyweight sets require weight_kg to be null"
        )
    if submitted_set.done and (submitted_set.reps is None or submitted_set.reps <= 0):
        raise GraphValidationError(f"{field_prefix}.reps", "completed sets require positive reps")
    if submitted_set.done and load_type != "bodyweight" and submitted_set.weight_kg is None:
        raise GraphValidationError(
            f"{field_prefix}.weight_kg", "completed weighted sets require weight_kg"
        )


def validate_save_graph(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    workout_id: str,
    payload: SaveWorkoutRequest,
) -> ValidatedSaveGraph:
    """Resolve and validate one complete save graph without mutating storage.

    The caller owns the write transaction. Requiring an active transaction
    keeps every ownership, id, visibility, and snapshot decision on the same
    database state that Stage 6b will later mutate.
    """
    if not conn.in_transaction:
        raise RuntimeError("save graph validation requires an active transaction")

    workout_row = conn.execute(
        "SELECT 1 FROM workouts WHERE id = :id AND user_id = :owner_id",
        {"id": workout_id, "owner_id": owner_id},
    ).fetchone()
    if workout_row is None:
        raise WorkoutNotFoundError

    exercise_ids = [exercise.id for exercise in payload.exercises]
    stored_exercises: dict[str, sqlite3.Row] = {}
    if exercise_ids:
        placeholders = ", ".join("?" for _ in exercise_ids)
        rows = conn.execute(
            "SELECT id, workout_id, catalog_id, load_type, bodyweight_percent, side_count "
            f"FROM exercises WHERE id IN ({placeholders})",
            exercise_ids,
        ).fetchall()
        stored_exercises = {str(row["id"]): row for row in rows}

    for exercise in payload.exercises:
        stored = stored_exercises.get(exercise.id)
        if stored is not None and (
            str(stored["workout_id"]) != workout_id
            or str(stored["catalog_id"]) != exercise.catalog_id
        ):
            raise GraphConflictError

    set_ids = [item.id for exercise in payload.exercises for item in exercise.sets]
    stored_sets: dict[str, sqlite3.Row] = {}
    if set_ids:
        placeholders = ", ".join("?" for _ in set_ids)
        rows = conn.execute(
            f"SELECT id, exercise_id FROM sets WHERE id IN ({placeholders})",
            set_ids,
        ).fetchall()
        stored_sets = {str(row["id"]): row for row in rows}

    for exercise in payload.exercises:
        for submitted_set in exercise.sets:
            stored = stored_sets.get(submitted_set.id)
            if stored is not None and str(stored["exercise_id"]) != exercise.id:
                raise GraphConflictError

    new_exercises = [
        exercise for exercise in payload.exercises if exercise.id not in stored_exercises
    ]
    new_catalog_ids = list(dict.fromkeys(exercise.catalog_id for exercise in new_exercises))
    visible_catalog: dict[str, sqlite3.Row] = {}
    if new_catalog_ids:
        placeholders = ", ".join("?" for _ in new_catalog_ids)
        rows = conn.execute(
            "SELECT id, load_type, bodyweight_percent, side_count FROM exercise_catalog "
            f"WHERE id IN ({placeholders}) AND (is_default = 1 OR created_by = ?)",
            [*new_catalog_ids, owner_id],
        ).fetchall()
        visible_catalog = {str(row["id"]): row for row in rows}
        if len(visible_catalog) != len(new_catalog_ids):
            raise CatalogUnavailableError

    validated_exercises: list[ValidatedExercise] = []
    for exercise_index, exercise in enumerate(payload.exercises):
        stored_exercise = stored_exercises.get(exercise.id)
        snapshot = (
            visible_catalog[exercise.catalog_id] if stored_exercise is None else stored_exercise
        )
        load_type = cast(LoadType, str(snapshot["load_type"]))
        bodyweight_percent = snapshot["bodyweight_percent"]
        side_count = int(snapshot["side_count"])

        validated_sets: list[ValidatedSet] = []
        for set_index, submitted_set in enumerate(exercise.sets):
            field_prefix = f"exercises.{exercise_index}.sets.{set_index}"
            _validate_set_for_snapshot(
                submitted_set,
                field_prefix=field_prefix,
                load_type=load_type,
                bodyweight_percent=bodyweight_percent,
                side_count=side_count,
            )
            validated_sets.append(
                ValidatedSet(
                    id=submitted_set.id,
                    set_index=set_index,
                    reps=submitted_set.reps,
                    weight_kg=submitted_set.weight_kg,
                    bw_percent_override=submitted_set.bw_percent_override,
                    rpe=submitted_set.rpe,
                    side=submitted_set.side,
                    done=submitted_set.done,
                    is_new=submitted_set.id not in stored_sets,
                )
            )
        validated_exercises.append(
            ValidatedExercise(
                id=exercise.id,
                catalog_id=exercise.catalog_id,
                order_index=exercise_index,
                notes=exercise.notes,
                load_type=load_type,
                bodyweight_percent=bodyweight_percent,
                side_count=side_count,
                sets=tuple(validated_sets),
                is_new=stored_exercise is None,
            )
        )

    return ValidatedSaveGraph(
        revision=payload.revision,
        save_id=payload.save_id,
        name=payload.name,
        notes=payload.notes,
        bodyweight_kg=payload.bodyweight_kg,
        ended_at=payload.ended_at,
        exercises=tuple(validated_exercises),
    )


def apply_validated_graph(
    conn: sqlite3.Connection,
    *,
    workout_id: str,
    graph: ValidatedSaveGraph,
) -> None:
    """Replace a workout's writable metadata and child graph atomically.

    This is the internal Stage 6b persistence primitive. It requires the
    caller's already-open write transaction and a `ValidatedSaveGraph` produced
    by `validate_save_graph` immediately beforehand on the same connection, so
    every parent/catalog/id relationship is resolved before the first mutation
    and no revalidation of a raw request happens here. It neither opens nor
    commits a transaction, and it deliberately leaves `ended_at`, `revision`,
    `last_save_id`, `last_save_hash`, and `updated_at` untouched — the public
    save protocol owns those lifecycle/receipt fields in Stage 6c.

    Reordering is unique-index safe (PLAN.md §5): for each parent, retained rows
    first move to distinct temporary indexes above both the stored and final
    ranges, then to their final dense positions, so two occupied positions are
    never swapped directly. Omitted sets are deleted from retained exercises
    before omitted exercises are deleted, and an omitted exercise's own sets are
    left to its `ON DELETE CASCADE` backstop. Retained rows keep their parent,
    catalog identity, and load snapshots; only new rows carry copied snapshots.
    """
    if not conn.in_transaction:
        raise RuntimeError("applying a save graph requires an active transaction")

    submitted_exercises = graph.exercises
    submitted_exercise_ids = {exercise.id for exercise in submitted_exercises}

    # Resolve the stored child state to delete omitted rows and to compute
    # reordering bases before issuing the first mutation.
    stored_exercise_index: dict[str, int] = {
        str(row["id"]): int(row["order_index"])
        for row in conn.execute(
            "SELECT id, order_index FROM exercises WHERE workout_id = :id",
            {"id": workout_id},
        ).fetchall()
    }

    retained_exercises = [exercise for exercise in submitted_exercises if not exercise.is_new]
    retained_exercise_ids = [exercise.id for exercise in retained_exercises]
    # Stored sets per retained exercise: {exercise_id: {set_id: set_index}}.
    stored_set_index: dict[str, dict[str, int]] = {
        exercise_id: {} for exercise_id in retained_exercise_ids
    }
    if retained_exercise_ids:
        placeholders = ", ".join("?" for _ in retained_exercise_ids)
        for row in conn.execute(
            f"SELECT id, exercise_id, set_index FROM sets WHERE exercise_id IN ({placeholders})",
            retained_exercise_ids,
        ).fetchall():
            stored_set_index[str(row["exercise_id"])][str(row["id"])] = int(row["set_index"])

    exercise_temp_base = (
        max(
            max(
                (stored_exercise_index[exercise.id] for exercise in retained_exercises), default=-1
            ),
            len(submitted_exercises) - 1,
        )
        + 1
    )
    if retained_exercises and exercise_temp_base + len(retained_exercises) - 1 > SQLITE_MAX_INTEGER:
        raise OverflowError("temporary exercise index exceeds SQLite INTEGER range")

    set_temp_moves: list[dict[str, Any]] = []
    for exercise in retained_exercises:
        retained_sets = [item for item in exercise.sets if not item.is_new]
        if not retained_sets:
            continue
        set_temp_base = (
            max(
                max(stored_set_index[exercise.id][item.id] for item in retained_sets),
                len(exercise.sets) - 1,
            )
            + 1
        )
        if set_temp_base + len(retained_sets) - 1 > SQLITE_MAX_INTEGER:
            raise OverflowError("temporary set index exceeds SQLite INTEGER range")
        set_temp_moves.extend(
            {"temp": set_temp_base + position, "id": item.id}
            for position, item in enumerate(retained_sets)
        )

    # Writable workout metadata only; the finish/lifecycle/receipt columns are
    # Stage 6c's responsibility and are not written here.
    conn.execute(
        "UPDATE workouts SET name = :name, notes = :notes, bodyweight_kg = :bodyweight_kg "
        "WHERE id = :id",
        {
            "name": graph.name,
            "notes": graph.notes,
            "bodyweight_kg": graph.bodyweight_kg,
            "id": workout_id,
        },
    )

    # 1. Delete omitted sets from retained exercises (their parents persist).
    omitted_set_ids: list[str] = []
    for exercise in retained_exercises:
        submitted_set_ids = {item.id for item in exercise.sets}
        omitted_set_ids.extend(
            stored_id
            for stored_id in stored_set_index[exercise.id]
            if stored_id not in submitted_set_ids
        )
    if omitted_set_ids:
        placeholders = ", ".join("?" for _ in omitted_set_ids)
        conn.execute(f"DELETE FROM sets WHERE id IN ({placeholders})", omitted_set_ids)

    # 2. Delete omitted exercises; FK cascade removes their descendant sets.
    omitted_exercise_ids = [
        stored_id for stored_id in stored_exercise_index if stored_id not in submitted_exercise_ids
    ]
    if omitted_exercise_ids:
        placeholders = ", ".join("?" for _ in omitted_exercise_ids)
        conn.execute(f"DELETE FROM exercises WHERE id IN ({placeholders})", omitted_exercise_ids)

    # 3. Move retained exercises to distinct temporary indexes above both the
    #    occupied stored indexes and the final dense range.
    if retained_exercises:
        conn.executemany(
            "UPDATE exercises SET order_index = :temp WHERE id = :id",
            [
                {"temp": exercise_temp_base + position, "id": exercise.id}
                for position, exercise in enumerate(retained_exercises)
            ],
        )

    # 4. Move retained sets to distinct temporary indexes within each exercise.
    if set_temp_moves:
        conn.executemany("UPDATE sets SET set_index = :temp WHERE id = :id", set_temp_moves)

    # 5. Write retained content and final dense positions. Retained exercises
    #    keep their parent, catalog identity, and snapshot; retained sets keep
    #    their parent. Only notes/order and mutable set values change.
    if retained_exercises:
        conn.executemany(
            "UPDATE exercises SET notes = :notes, order_index = :order_index WHERE id = :id",
            [
                {"notes": exercise.notes, "order_index": exercise.order_index, "id": exercise.id}
                for exercise in retained_exercises
            ],
        )
    retained_set_updates: list[dict[str, Any]] = [
        {
            "reps": item.reps,
            "weight_kg": item.weight_kg,
            "bw_percent_override": item.bw_percent_override,
            "rpe": item.rpe,
            "side": item.side,
            "done": int(item.done),
            "set_index": item.set_index,
            "id": item.id,
        }
        for exercise in retained_exercises
        for item in exercise.sets
        if not item.is_new
    ]
    if retained_set_updates:
        conn.executemany(
            "UPDATE sets SET reps = :reps, weight_kg = :weight_kg, "
            "bw_percent_override = :bw_percent_override, rpe = :rpe, side = :side, "
            "done = :done, set_index = :set_index WHERE id = :id",
            retained_set_updates,
        )

    # 6. Insert new exercises with the snapshots copied during validation.
    new_exercise_inserts: list[dict[str, Any]] = [
        {
            "id": exercise.id,
            "workout_id": workout_id,
            "catalog_id": exercise.catalog_id,
            "order_index": exercise.order_index,
            "notes": exercise.notes,
            "load_type": exercise.load_type,
            "bodyweight_percent": exercise.bodyweight_percent,
            "side_count": exercise.side_count,
        }
        for exercise in submitted_exercises
        if exercise.is_new
    ]
    if new_exercise_inserts:
        conn.executemany(
            "INSERT INTO exercises (id, workout_id, catalog_id, order_index, notes, "
            "load_type, bodyweight_percent, side_count) VALUES (:id, :workout_id, "
            ":catalog_id, :order_index, :notes, :load_type, :bodyweight_percent, :side_count)",
            new_exercise_inserts,
        )

    # 7. Insert new sets for both new and retained exercises (parents exist).
    new_set_inserts: list[dict[str, Any]] = [
        {
            "id": item.id,
            "exercise_id": exercise.id,
            "set_index": item.set_index,
            "reps": item.reps,
            "weight_kg": item.weight_kg,
            "bw_percent_override": item.bw_percent_override,
            "rpe": item.rpe,
            "side": item.side,
            "done": int(item.done),
        }
        for exercise in submitted_exercises
        for item in exercise.sets
        if item.is_new
    ]
    if new_set_inserts:
        conn.executemany(
            "INSERT INTO sets (id, exercise_id, set_index, reps, weight_kg, "
            "bw_percent_override, rpe, side, done) VALUES (:id, :exercise_id, :set_index, "
            ":reps, :weight_kg, :bw_percent_override, :rpe, :side, :done)",
            new_set_inserts,
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
