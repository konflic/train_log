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
across pages. Graph reads use three queries (workout, exercises, sets) plus at
most three more for inline previous performance, all independent of graph size —
never one query per set (PLAN.md §5).

Stage 6a adds the read-only, transaction-bound validation half of bulk-save.
It classifies every submitted nested id as retained under its exact parent or
globally new, resolves immutable exercise snapshots, and validates sets against
those snapshots before later stages perform any mutation.

Stage 6b adds `apply_validated_graph`, the internal, transaction-bound mutation
half: it replaces the writable metadata and the complete child graph from a
`ValidatedSaveGraph`, deleting omitted rows and reindexing retained rows through
temporary positions so unique indexes are never violated by a reorder. It stays
internal and leaves lifecycle/receipt fields for the save protocol.

Stage 6c adds `save_workout`, the public bulk-save protocol behind
`PUT /workouts/{id}`: inside one `BEGIN IMMEDIATE` transaction it resolves the
`save_id` receipt (exact retry vs. conflict), enforces the revision match, the
finished-workout guard, revision exhaustion, and the finish-time rules, applies
the validated graph, and records revision/receipt/`updated_at` atomically. The
authoritative response graph is captured on the write connection before commit,
so a second writer cannot replace it between commit and response.

Stage 7 adds `delete_workout`, the revision-checked hard delete behind
`DELETE /workouts/{id}?revision=N`: inside one `BEGIN IMMEDIATE` transaction it
compares the submitted revision to the stored owner-scoped row and removes it,
cascading to exercises and sets. Both active and finished workouts are
deletable, and nothing is retained: no receipt, tombstone, or timestamp update.

Stage 8a attaches inline previous performance to every graph read. For each
distinct catalog id in the viewed workout it selects the most recent finished,
strictly earlier, owner-scoped session that has at least one completed set for
that catalog id, pairs occurrences by workout order and completed sets by side
and per-side ordinal, and derives every reported value from the recorded
workout bodyweights and exercise snapshots — never from the current profile or
catalog. Comparison values are nulled when the recorded load settings differ, so
a later catalog edit cannot fabricate progression. Derived arithmetic is checked
when a graph is saved; legacy rows with unsafe derived values remain readable
with null load metrics. The latest PUT's previous-performance tuple is stored as
part of its bounded receipt so exact retries remain stable (PLAN.md §7).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER, NumericRangeError, calculate_set_load, integer_delta
from app.schemas.common import LoadType
from app.schemas.workouts import (
    MAX_WORKOUT_NAME_LENGTH,
    SaveSetRequest,
    SaveWorkoutRequest,
    Side,
)
from app.timestamps import now_timestamp, parse_timestamp, to_timestamp

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
    "session_type",
    "source_plan_id",
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


class ActiveSessionConflictError(Exception):
    """A different unfinished workout already belongs to the account."""


class PlanRevisionConflictError(Exception):
    """The selected plan changed after it was previewed."""


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


class SaveConflictError(Exception):
    """Base for save-protocol conflicts; carries only the stored revision."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f"current revision is {current_revision}")
        self.current_revision = current_revision


class SaveIdConflictError(SaveConflictError):
    """The latest accepted `save_id` was reused with different content."""


class RevisionConflictError(SaveConflictError):
    """The request revision does not match the stored revision."""


class RevisionExhaustedError(SaveConflictError):
    """The stored revision reached `MAX_SAFE_INTEGER`; no safe successor exists."""


class WorkoutFinishedError(SaveConflictError):
    """A new save targets a finished workout (read-only except exact retry)."""


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
    session_type: str | None
    source_plan_id: str | None


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
class PreviousSession:
    """The selected previous workout for one catalog id (PLAN.md §7)."""

    id: str
    started_at: str
    bodyweight_kg: int | None


@dataclass(frozen=True, slots=True)
class SetValues:
    """Reported integer values for one set; ``None`` means unknown.

    Used for a previous occurrence's completed sets and for both sides plus the
    delta of one compared pair, so every reported value shares one shape.
    """

    reps: int | None
    external_load_kg: int | None
    effective_load_kg: int | None
    volume_kg_reps: int | None
    estimated_1rm_kg: int | None


@dataclass(frozen=True, slots=True)
class PreviousSet:
    """One completed set of a paired previous occurrence with derived values."""

    id: str
    set_index: int
    side: str
    reps: int | None
    weight_kg: int | None
    bw_percent_override: int | None
    values: SetValues


@dataclass(frozen=True, slots=True)
class PreviousSetPair:
    """One side-aware pairing of a current set with a previous completed set."""

    current_set_id: str
    previous_set_id: str
    load_compatible: bool
    current: SetValues
    previous: SetValues
    delta: SetValues


@dataclass(frozen=True, slots=True)
class ExercisePreviousPerformance:
    """The paired previous occurrence of one current workout exercise.

    `sets` is the previous occurrence's complete completed-set list (visible
    before any current set is done), while `pairs` carries only the matched
    comparisons; an unmatched set has no pair and therefore no delta.
    """

    workout_id: str
    started_at: str
    bodyweight_kg: int | None
    exercise_id: str
    order_index: int
    load_type: str
    bodyweight_percent: int | None
    side_count: int
    sets: tuple[PreviousSet, ...]
    pairs: tuple[PreviousSetPair, ...]


def _encode_previous_performance(
    records: tuple[ExercisePreviousPerformance | None, ...],
) -> str:
    """Serialize the latest PUT's derived history for exact receipt retries."""
    return json.dumps(
        [None if record is None else asdict(record) for record in records],
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _decode_set_values(value: Any) -> SetValues:
    if not isinstance(value, dict):
        raise TypeError("set values must be an object")
    return SetValues(
        reps=value["reps"],
        external_load_kg=value["external_load_kg"],
        effective_load_kg=value["effective_load_kg"],
        volume_kg_reps=value["volume_kg_reps"],
        estimated_1rm_kg=value["estimated_1rm_kg"],
    )


def _decode_previous_performance(
    serialized: str,
) -> tuple[ExercisePreviousPerformance | None, ...]:
    """Restore an internal receipt snapshot; malformed storage is fatal."""
    try:
        value = json.loads(serialized)
        if not isinstance(value, list):
            raise TypeError("previous performance must be an array")
        records: list[ExercisePreviousPerformance | None] = []
        for item in value:
            if item is None:
                records.append(None)
                continue
            if not isinstance(item, dict):
                raise TypeError("previous performance entry must be an object")
            sets = tuple(
                PreviousSet(
                    id=previous_set["id"],
                    set_index=previous_set["set_index"],
                    side=previous_set["side"],
                    reps=previous_set["reps"],
                    weight_kg=previous_set["weight_kg"],
                    bw_percent_override=previous_set["bw_percent_override"],
                    values=_decode_set_values(previous_set["values"]),
                )
                for previous_set in item["sets"]
            )
            pairs = tuple(
                PreviousSetPair(
                    current_set_id=pair["current_set_id"],
                    previous_set_id=pair["previous_set_id"],
                    load_compatible=pair["load_compatible"],
                    current=_decode_set_values(pair["current"]),
                    previous=_decode_set_values(pair["previous"]),
                    delta=_decode_set_values(pair["delta"]),
                )
                for pair in item["pairs"]
            )
            records.append(
                ExercisePreviousPerformance(
                    workout_id=item["workout_id"],
                    started_at=item["started_at"],
                    bodyweight_kg=item["bodyweight_kg"],
                    exercise_id=item["exercise_id"],
                    order_index=item["order_index"],
                    load_type=item["load_type"],
                    bodyweight_percent=item["bodyweight_percent"],
                    side_count=item["side_count"],
                    sets=sets,
                    pairs=pairs,
                )
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("stored previous-performance receipt is invalid") from exc
    return tuple(records)


@dataclass(frozen=True, slots=True)
class WorkoutGraph:
    """A workout row plus its complete ordered exercise/set graph.

    `previous_performance` is parallel to `exercises`: one entry per exercise,
    `None` when that occurrence has no comparable previous session.
    """

    workout: WorkoutRecord
    exercises: tuple[ExerciseRecord, ...]
    previous_performance: tuple[ExercisePreviousPerformance | None, ...]


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
        session_type=row["session_type"],
        source_plan_id=row["source_plan_id"],
    )


def _validate_set_for_snapshot(
    submitted_set: SaveSetRequest,
    *,
    field_prefix: str,
    load_type: LoadType,
    bodyweight_percent: int | None,
    side_count: int,
    bodyweight_kg: int | None,
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
    effective_percent = (
        submitted_set.bw_percent_override
        if submitted_set.bw_percent_override is not None
        else bodyweight_percent
    )
    try:
        calculate_set_load(
            reps=submitted_set.reps,
            weight_kg=submitted_set.weight_kg,
            load_type=load_type,
            side_count=side_count,
            bodyweight_kg=bodyweight_kg,
            bodyweight_percent=effective_percent,
        )
    except NumericRangeError:
        raise GraphValidationError(
            field_prefix, "derived set values exceed the safe integer range"
        ) from None


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
                bodyweight_kg=payload.bodyweight_kg,
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
    `last_save_id`, `last_save_hash`, the derived-history receipt, and
    `updated_at` untouched — the public save protocol owns those
    lifecycle/receipt fields.

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


def save_request_hash(*, owner_id: str, workout_id: str, payload: SaveWorkoutRequest) -> str:
    """Fingerprint a validated full-state save request canonically (PLAN.md §6).

    Compact sorted-key JSON over the owner id, the path workout id, and the
    exact normalized request body - `revision`, `save_id`, explicit nulls, and
    array order included; server snapshots and derived indexes cannot appear
    because the request schema rejects them. The owner/workout binding makes
    identical content submitted by another user or for another workout never
    match the stored receipt. Normalization happens during schema validation,
    so a retry spelled differently (uppercase UUIDs, `+00:00` offsets) hashes
    identically.
    """
    canonical = json.dumps(
        {
            "owner_id": owner_id,
            "workout_id": workout_id,
            "body": payload.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workout_name(started_at: str, utc_offset_minutes: int, plan_name: str | None = None) -> str:
    """Return the fixed display name for a session in the owner's local date.

    A session started from a plan is named after that plan; a freestyle session
    gets the generic label. The label is truncated so the generated name always
    fits the bulk-save name limit and a client can echo it back unchanged.
    """
    try:
        local_date = (parse_timestamp(started_at) + timedelta(minutes=utc_offset_minutes)).date()
    except OverflowError:
        local_date = date.max if utc_offset_minutes > 0 else date.min
    suffix = f" on {local_date:%Y-%m-%d}"
    label = "Freestyle workout" if plan_name is None else plan_name
    label = label[: MAX_WORKOUT_NAME_LENGTH - len(suffix)].rstrip() or "Workout"
    return f"{label}{suffix}"


def save_workout(
    database_path: str | Path,
    *,
    owner_id: str,
    workout_id: str,
    payload: SaveWorkoutRequest,
) -> WorkoutGraph:
    """Apply one full-state bulk-save and return the authoritative new graph.

    The complete save protocol runs inside one `BEGIN IMMEDIATE` transaction
    (IMPLEMENTATION.md Stage 6c, in order): load the owned row (missing and
    foreign ids are indistinguishable; PUT never creates), resolve the `save_id`
    receipt (exact retry vs. `save_id_conflict`), enforce the revision match,
    the finished-workout guard, revision exhaustion, and the finish-time rules,
    re-resolve all Stage 6a invariants against transaction rows, apply the
    Stage 6b replacement, and record the incremented revision, request receipt,
    derived-history snapshot, `ended_at`, and one transaction timestamp as
    `updated_at` in the same commit. The response graph is read back on the write
    connection before the commit and returned only after it succeeds, so a
    second writer cannot replace it between commit and response.
    """
    # Database-independent fingerprinting happens before taking the writer lock.
    request_hash = save_request_hash(owner_id=owner_id, workout_id=workout_id, payload=payload)
    with connect(database_path) as conn, write_transaction(conn):
        row = conn.execute(
            f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts "
            "WHERE id = :id AND user_id = :owner_id",
            {"id": workout_id, "owner_id": owner_id},
        ).fetchone()
        if row is None:
            raise WorkoutNotFoundError
        stored = row_to_workout(row)

        # Receipt resolution precedes every other check: an exact retry of the
        # latest accepted save (including the accepted finish) returns the
        # stored graph and derived-history snapshot with no validation,
        # mutation, or revision increment.
        if payload.save_id == stored.last_save_id:
            if request_hash != stored.last_save_hash:
                raise SaveIdConflictError(stored.revision)
            snapshot_row = conn.execute(
                "SELECT snapshot FROM workout_save_previous_performance WHERE workout_id = ?",
                (workout_id,),
            ).fetchone()
            retry_graph = _read_workout_graph(
                conn,
                workout_id,
                user_id=owner_id,
                previous_performance_snapshot=(
                    None if snapshot_row is None else str(snapshot_row["snapshot"])
                ),
            )
            if retry_graph is None:
                raise RuntimeError("workout vanished inside its own save transaction")
            return retry_graph

        if payload.revision != stored.revision:
            # Retries of superseded receipts land here too: only the latest
            # receipt is retained, so an older save_id is a normal conflict.
            raise RevisionConflictError(stored.revision)
        if stored.ended_at is not None:
            raise WorkoutFinishedError(stored.revision)
        if stored.revision >= MAX_SAFE_INTEGER:
            raise RevisionExhaustedError(stored.revision)
        if payload.bodyweight_kg != stored.bodyweight_kg:
            raise GraphValidationError(
                "bodyweight_kg", "recorded bodyweight is a read-only Settings snapshot"
            )

        # Exact retries and protocol conflicts resolved above do not need the
        # clock. For a new save, one timestamp is both the finish ceiling and
        # `updated_at`.
        now = now_timestamp()
        if payload.ended_at is not None:
            # Canonical fixed-width UTC text: text order is time order. There
            # is no clock-skew allowance; the ceiling is the sampled `now`.
            if payload.ended_at < stored.started_at:
                raise GraphValidationError("ended_at", "finish time is before the workout start")
            if payload.ended_at > now:
                raise GraphValidationError("ended_at", "finish time is in the future")

        validated = validate_save_graph(
            conn, owner_id=owner_id, workout_id=workout_id, payload=payload
        )
        apply_validated_graph(conn, workout_id=workout_id, graph=validated)
        conn.execute(
            "UPDATE workouts SET revision = :revision, last_save_id = :save_id, "
            "last_save_hash = :save_hash, ended_at = :ended_at, updated_at = :now "
            "WHERE id = :id AND user_id = :owner_id",
            {
                "revision": stored.revision + 1,
                "save_id": payload.save_id,
                "save_hash": request_hash,
                "ended_at": payload.ended_at,
                "now": now,
                "id": workout_id,
                "owner_id": owner_id,
            },
        )
        # Captured on the write connection: the transaction commits while this
        # value is returned, so callers only see a graph whose save succeeded.
        saved_graph = _read_workout_graph(conn, workout_id, user_id=owner_id)
        if saved_graph is None:
            raise RuntimeError("workout vanished inside its own save transaction")
        conn.execute(
            "INSERT INTO workout_save_previous_performance (workout_id, snapshot) "
            "VALUES (:id, :snapshot) ON CONFLICT (workout_id) DO UPDATE "
            "SET snapshot = excluded.snapshot",
            {
                "snapshot": _encode_previous_performance(saved_graph.previous_performance),
                "id": workout_id,
            },
        )
        return saved_graph


def delete_workout(
    database_path: str | Path,
    *,
    owner_id: str,
    workout_id: str,
    revision: int,
) -> None:
    """Hard-delete one owned workout at its exact stored revision.

    Inside one `BEGIN IMMEDIATE` transaction, select the owned row's revision
    (missing, already-deleted, and foreign ids are indistinguishable and raise
    `WorkoutNotFoundError`), compare it to the submitted revision (a mismatch
    raises `RevisionConflictError` without mutating anything), then delete the
    row; the existing `ON DELETE CASCADE` foreign keys remove its exercises and
    sets. Both active and finished workouts are deletable, and no receipt or
    tombstone is retained: a retry after a successful but unobserved deletion is
    an ordinary `WorkoutNotFoundError`.
    """
    with connect(database_path) as conn, write_transaction(conn):
        row = conn.execute(
            "SELECT revision FROM workouts WHERE id = :id AND user_id = :owner_id",
            {"id": workout_id, "owner_id": owner_id},
        ).fetchone()
        if row is None:
            raise WorkoutNotFoundError
        stored_revision = int(row["revision"])
        if revision != stored_revision:
            raise RevisionConflictError(stored_revision)
        conn.execute(
            "DELETE FROM workouts WHERE id = :id AND user_id = :owner_id",
            {"id": workout_id, "owner_id": owner_id},
        )


def create_request_hash(
    *,
    user_id: str,
    workout_id: str,
    started_at: str,
    session_type: str = "freestyle",
    source_plan_id: str | None = None,
    source_plan_revision: int | None = None,
    legacy_shape: bool = False,
) -> str:
    """Fingerprint a validated create request canonically (PLAN.md §6).

    The owner is part of the fingerprint: two users submitting identical
    content for the same UUID never match, so a create can never return or
    overwrite another user's row. Compact sorted-key JSON over already
    normalized values makes the hash independent of field order and spelling.
    """
    content: dict[str, object] = {
        "user_id": user_id,
        "id": workout_id,
        "started_at": started_at,
    }
    if not legacy_shape:
        content.update(
            session_type=session_type,
            source_plan_id=source_plan_id,
            source_plan_revision=source_plan_revision,
        )
    canonical = json.dumps(
        content,
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
    session_type: str = "freestyle",
    source_plan_id: str | None = None,
    source_plan_revision: int | None = None,
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
        existing = conn.execute(
            f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE id = :id",
            {"id": workout_id},
        ).fetchone()
        if existing is not None:
            if (
                str(existing["user_id"]) != owner_id
                or str(existing["create_request_hash"]) != request_hash
            ):
                raise CreateConflictError(workout_id)
            return row_to_workout(existing), False

        active = conn.execute(
            "SELECT id FROM workouts WHERE user_id = :owner_id AND ended_at IS NULL LIMIT 1",
            {"owner_id": owner_id},
        ).fetchone()
        if active is not None:
            raise ActiveSessionConflictError(str(active["id"]))

        plan = None
        plan_exercises: list[sqlite3.Row] = []
        plan_sets: dict[str, list[sqlite3.Row]] = {}
        if session_type == "from_plan":
            plan = conn.execute(
                "SELECT id, name, revision FROM training_plans "
                "WHERE id = :id AND user_id = :owner_id",
                {"id": source_plan_id, "owner_id": owner_id},
            ).fetchone()
            if plan is None:
                raise CatalogUnavailableError
            if int(plan["revision"]) != source_plan_revision:
                raise PlanRevisionConflictError
            plan_exercises = conn.execute(
                "SELECT pe.id, pe.catalog_id, pe.order_index, pe.notes, c.load_type, "
                "c.bodyweight_percent, c.side_count FROM training_plan_exercises pe "
                "JOIN exercise_catalog c ON c.id = pe.catalog_id "
                "WHERE pe.plan_id = ? ORDER BY pe.order_index",
                (source_plan_id,),
            ).fetchall()
            plan_exercise_ids = [str(item["id"]) for item in plan_exercises]
            plan_sets = {item: [] for item in plan_exercise_ids}
            if plan_exercise_ids:
                placeholders = ", ".join("?" for _ in plan_exercise_ids)
                for item in conn.execute(
                    "SELECT plan_exercise_id, set_index, target_reps, target_weight_kg, "
                    "side, bw_percent_override FROM training_plan_sets "
                    f"WHERE plan_exercise_id IN ({placeholders}) "
                    "ORDER BY plan_exercise_id, set_index",
                    plan_exercise_ids,
                ).fetchall():
                    plan_sets[str(item["plan_exercise_id"])].append(item)

        profile = conn.execute(
            "SELECT bodyweight_default_kg, utc_offset_minutes FROM users WHERE id = :owner_id",
            {"owner_id": owner_id},
        ).fetchone()
        bodyweight_kg = profile["bodyweight_default_kg"] if profile is not None else None
        utc_offset_minutes = int(profile["utc_offset_minutes"]) if profile is not None else 0
        name = workout_name(
            started_at,
            utc_offset_minutes,
            plan_name=str(plan["name"]) if plan is not None else None,
        )
        try:
            conn.execute(
                "INSERT INTO workouts (id, user_id, name, started_at, ended_at, "
                "notes, bodyweight_kg, revision, create_request_hash, "
                "last_save_id, last_save_hash, created_at, updated_at, session_type, "
                "source_plan_id) "
                "VALUES (:id, :user_id, :name, :started_at, NULL, NULL, "
                ":bodyweight_kg, 0, :create_request_hash, NULL, NULL, :now, :now, "
                ":session_type, :source_plan_id)",
                {
                    "id": workout_id,
                    "user_id": owner_id,
                    "name": name,
                    "started_at": started_at,
                    "bodyweight_kg": bodyweight_kg,
                    "create_request_hash": request_hash,
                    "now": now,
                    "session_type": session_type,
                    "source_plan_id": source_plan_id,
                },
            )
        except sqlite3.IntegrityError as exc:
            # The primary key is the authoritative race check: re-read the
            # winner and accept only an exact owner+fingerprint match. A
            # missing owner fails the user FK and is re-raised unchanged.
            if "workouts.user_id" in str(exc):
                raise ActiveSessionConflictError(owner_id) from exc
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
        if plan is not None:
            for plan_exercise in plan_exercises:
                exercise_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO exercises (id, workout_id, catalog_id, order_index, notes, "
                    "load_type, bodyweight_percent, side_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        exercise_id,
                        workout_id,
                        str(plan_exercise["catalog_id"]),
                        int(plan_exercise["order_index"]),
                        plan_exercise["notes"],
                        str(plan_exercise["load_type"]),
                        plan_exercise["bodyweight_percent"],
                        int(plan_exercise["side_count"]),
                    ),
                )
                conn.executemany(
                    "INSERT INTO sets (id, exercise_id, set_index, reps, weight_kg, "
                    "bw_percent_override, rpe, side, done) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0)",
                    [
                        (
                            str(uuid.uuid4()),
                            exercise_id,
                            int(item["set_index"]),
                            item["target_reps"],
                            item["target_weight_kg"],
                            item["bw_percent_override"],
                            str(item["side"]),
                        )
                        for item in plan_sets[str(plan_exercise["id"])]
                    ],
                )
        created = conn.execute(
            f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone()
        if created is None:
            raise RuntimeError("created workout vanished")
        return row_to_workout(created), True


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


def workout_summary_totals(
    database_path: str | Path,
    *,
    user_id: str,
    workout_ids: Sequence[str],
) -> dict[str, tuple[int | None, bool]]:
    """Return completed-set volume and completeness for one history page."""
    if not workout_ids:
        return {}
    placeholders = ", ".join(f":workout_{index}" for index in range(len(workout_ids)))
    params: dict[str, Any] = {"user_id": user_id}
    params.update({f"workout_{index}": workout_id for index, workout_id in enumerate(workout_ids)})
    totals = {workout_id: {"completed": 0, "unknown": 0, "volume": 0} for workout_id in workout_ids}
    with connect(database_path) as conn:
        rows = conn.execute(
            f"""
            SELECT w.id AS workout_id, w.bodyweight_kg, e.load_type,
                   e.side_count, e.bodyweight_percent, s.reps, s.weight_kg,
                   s.bw_percent_override, s.done
            FROM workouts AS w
            JOIN exercises AS e ON e.workout_id = w.id
            JOIN sets AS s ON s.exercise_id = e.id
            WHERE w.user_id = :user_id AND w.id IN ({placeholders})
            """,
            params,
        ).fetchall()
    for row in rows:
        if not bool(row["done"]):
            continue
        total = totals[str(row["workout_id"])]
        total["completed"] += 1
        load = calculate_set_load(
            reps=row["reps"],
            weight_kg=row["weight_kg"],
            load_type=cast(LoadType, row["load_type"]),
            side_count=int(row["side_count"]),
            bodyweight_kg=row["bodyweight_kg"],
            bodyweight_percent=(
                row["bw_percent_override"]
                if row["bw_percent_override"] is not None
                else row["bodyweight_percent"]
            ),
        )
        if load.volume_kg_reps is None:
            total["unknown"] += 1
        else:
            total["volume"] += load.volume_kg_reps
    return {
        workout_id: (
            None
            if values["completed"] and values["unknown"] == values["completed"]
            else values["volume"],
            values["unknown"] == 0,
        )
        for workout_id, values in totals.items()
    }


def _row_to_set(row: sqlite3.Row) -> SetRecord:
    return SetRecord(
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


def _row_to_exercise(row: sqlite3.Row, sets: tuple[SetRecord, ...]) -> ExerciseRecord:
    return ExerciseRecord(
        id=str(row["id"]),
        catalog_id=str(row["catalog_id"]),
        order_index=int(row["order_index"]),
        notes=row["notes"],
        load_type=str(row["load_type"]),
        bodyweight_percent=row["bodyweight_percent"],
        side_count=int(row["side_count"]),
        sets=sets,
    )


def _effective_bodyweight_percent(record: SetRecord, exercise: ExerciseRecord) -> int | None:
    """A set's percentage: its override replaces the exercise snapshot."""
    if record.bw_percent_override is not None:
        return record.bw_percent_override
    return exercise.bodyweight_percent


def _set_values(
    record: SetRecord, *, exercise: ExerciseRecord, bodyweight_kg: int | None
) -> SetValues:
    """Derive one set's reported values from recorded inputs only (PLAN.md §3).

    The workout bodyweight is the one recorded for the set's own workout, so a
    later profile edit never rewrites a historical calculation.
    """
    try:
        loads = calculate_set_load(
            reps=record.reps,
            weight_kg=record.weight_kg,
            load_type=cast(LoadType, exercise.load_type),
            side_count=exercise.side_count,
            bodyweight_kg=bodyweight_kg,
            bodyweight_percent=_effective_bodyweight_percent(record, exercise),
        )
    except NumericRangeError:
        # Databases created before Stage 8 may contain individually valid inputs
        # whose derived values exceed the shared safe range. Keep those rows
        # readable without emitting an unsafe integer; new saves are rejected.
        return SetValues(
            reps=record.reps,
            external_load_kg=None,
            effective_load_kg=None,
            volume_kg_reps=None,
            estimated_1rm_kg=None,
        )
    return SetValues(
        reps=record.reps,
        external_load_kg=loads.external_load_kg,
        effective_load_kg=loads.effective_load_kg,
        volume_kg_reps=loads.volume_kg_reps,
        estimated_1rm_kg=loads.estimated_1rm_kg,
    )


def _without_load_values(values: SetValues) -> SetValues:
    """Reduce a comparison to reps when the recorded load settings differ."""
    return SetValues(
        reps=values.reps,
        external_load_kg=None,
        effective_load_kg=None,
        volume_kg_reps=None,
        estimated_1rm_kg=None,
    )


def _values_delta(current: SetValues, previous: SetValues) -> SetValues:
    return SetValues(
        reps=integer_delta(current.reps, previous.reps),
        external_load_kg=integer_delta(current.external_load_kg, previous.external_load_kg),
        effective_load_kg=integer_delta(current.effective_load_kg, previous.effective_load_kg),
        volume_kg_reps=integer_delta(current.volume_kg_reps, previous.volume_kg_reps),
        estimated_1rm_kg=integer_delta(current.estimated_1rm_kg, previous.estimated_1rm_kg),
    )


def _pair_sets(
    current: ExerciseRecord,
    previous: ExerciseRecord,
    *,
    current_bodyweight_kg: int | None,
    previous_bodyweight_kg: int | None,
) -> tuple[PreviousSetPair, ...]:
    """Pair completed sets by side and per-side ordinal, never across sides.

    Sets are already in `set_index` order on both sides, so the ordinal of a
    completed set within its own side is its comparison position. An unmatched
    current set is simply absent from the result and therefore has no delta.
    """
    previous_by_side: dict[str, list[SetRecord]] = {}
    for record in previous.sets:
        if record.done:
            previous_by_side.setdefault(record.side, []).append(record)

    snapshots_comparable = (
        current.load_type == previous.load_type and current.side_count == previous.side_count
    )
    ordinals: dict[str, int] = {}
    pairs: list[PreviousSetPair] = []
    for record in current.sets:
        if not record.done:
            continue
        ordinal = ordinals.get(record.side, 0)
        ordinals[record.side] = ordinal + 1
        candidates = previous_by_side.get(record.side)
        if candidates is None or ordinal >= len(candidates):
            continue
        matched = candidates[ordinal]
        current_values = _set_values(record, exercise=current, bodyweight_kg=current_bodyweight_kg)
        previous_values = _set_values(
            matched, exercise=previous, bodyweight_kg=previous_bodyweight_kg
        )
        # Side equality comes from the pairing itself; the recorded load type,
        # side count, and effective percentages decide whether the load-based
        # numbers mean the same thing on both sides.
        load_compatible = snapshots_comparable and _effective_bodyweight_percent(
            record, current
        ) == _effective_bodyweight_percent(matched, previous)
        if not load_compatible:
            current_values = _without_load_values(current_values)
            previous_values = _without_load_values(previous_values)
        pairs.append(
            PreviousSetPair(
                current_set_id=record.id,
                previous_set_id=matched.id,
                load_compatible=load_compatible,
                current=current_values,
                previous=previous_values,
                delta=_values_delta(current_values, previous_values),
            )
        )
    return tuple(pairs)


def _exercise_previous_performance(
    current: ExerciseRecord,
    previous: ExerciseRecord,
    *,
    session: PreviousSession,
    current_bodyweight_kg: int | None,
) -> ExercisePreviousPerformance:
    return ExercisePreviousPerformance(
        workout_id=session.id,
        started_at=session.started_at,
        bodyweight_kg=session.bodyweight_kg,
        exercise_id=previous.id,
        order_index=previous.order_index,
        load_type=previous.load_type,
        bodyweight_percent=previous.bodyweight_percent,
        side_count=previous.side_count,
        sets=tuple(
            PreviousSet(
                id=record.id,
                set_index=record.set_index,
                side=record.side,
                reps=record.reps,
                weight_kg=record.weight_kg,
                bw_percent_override=record.bw_percent_override,
                values=_set_values(record, exercise=previous, bodyweight_kg=session.bodyweight_kg),
            )
            for record in previous.sets
        ),
        pairs=_pair_sets(
            current,
            previous,
            current_bodyweight_kg=current_bodyweight_kg,
            previous_bodyweight_kg=session.bodyweight_kg,
        ),
    )


def _select_previous_sessions(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    workout_id: str,
    started_at: str,
    catalog_ids: Sequence[str],
) -> dict[str, PreviousSession]:
    """One query selecting the previous session for every distinct catalog id.

    Candidates are the caller's own finished workouts that started strictly
    earlier than the viewed workout (which is excluded by id, so an equal
    `started_at` can never select itself) and that hold at least one completed
    set for the catalog id. `ROW_NUMBER` over the documented total order
    `(started_at DESC, id DESC)` keeps one winner per catalog id, so the row
    count is bounded by the graph rather than by the training history.
    """
    placeholders = ", ".join("?" for _ in catalog_ids)
    rows = conn.execute(
        "SELECT catalog_id, workout_id, started_at, bodyweight_kg FROM ("
        "SELECT e.catalog_id AS catalog_id, w.id AS workout_id, "
        "w.started_at AS started_at, w.bodyweight_kg AS bodyweight_kg, "
        "ROW_NUMBER() OVER (PARTITION BY e.catalog_id "
        "ORDER BY w.started_at DESC, w.id DESC) AS position "
        "FROM exercises e JOIN workouts w ON w.id = e.workout_id "
        "WHERE w.user_id = ? AND w.id <> ? AND w.ended_at IS NOT NULL "
        "AND w.started_at < ? "
        f"AND e.catalog_id IN ({placeholders}) "
        "AND EXISTS (SELECT 1 FROM sets s WHERE s.exercise_id = e.id AND s.done = 1)"
        ") WHERE position = 1",
        [user_id, workout_id, started_at, *catalog_ids],
    ).fetchall()
    return {
        str(row["catalog_id"]): PreviousSession(
            id=str(row["workout_id"]),
            started_at=str(row["started_at"]),
            bodyweight_kg=row["bodyweight_kg"],
        )
        for row in rows
    }


def _select_previous_occurrences(
    conn: sqlite3.Connection,
    *,
    catalog_ids: Sequence[str],
    session_ids: Sequence[str],
) -> dict[tuple[str, str], tuple[ExerciseRecord, ...]]:
    """Two queries fetching the selected sessions' occurrences and their sets.

    Occurrences come back in `(workout_id, order_index)` order and completed
    sets in `set_index` order, so both the workout-order occurrence pairing and
    the per-side ordinals are positional. Only completed sets are read:
    unfinished history never contributes performance (PLAN.md §7). The
    `(workout_id, catalog_id)` pairs that actually selected a session are
    matched by the caller, so a session chosen for one catalog id cannot leak
    another catalog id's occurrences into a pairing.
    """
    session_placeholders = ", ".join("?" for _ in session_ids)
    catalog_placeholders = ", ".join("?" for _ in catalog_ids)
    exercise_rows = conn.execute(
        f"SELECT e.workout_id, {', '.join(f'e.{name}' for name in EXERCISE_COLUMNS)} "
        "FROM exercises e "
        f"WHERE e.workout_id IN ({session_placeholders}) "
        f"AND e.catalog_id IN ({catalog_placeholders}) "
        "ORDER BY e.workout_id, e.order_index",
        [*session_ids, *catalog_ids],
    ).fetchall()

    exercise_ids = [str(row["id"]) for row in exercise_rows]
    sets_by_exercise: dict[str, list[SetRecord]] = {exercise_id: [] for exercise_id in exercise_ids}
    if exercise_ids:
        placeholders = ", ".join("?" for _ in exercise_ids)
        for row in conn.execute(
            f"SELECT {', '.join(f's.{name}' for name in SET_COLUMNS)} FROM sets s "
            f"WHERE s.exercise_id IN ({placeholders}) AND s.done = 1 ORDER BY s.set_index",
            exercise_ids,
        ).fetchall():
            sets_by_exercise[str(row["exercise_id"])].append(_row_to_set(row))

    occurrences: dict[tuple[str, str], list[ExerciseRecord]] = {}
    for row in exercise_rows:
        key = (str(row["workout_id"]), str(row["catalog_id"]))
        occurrences.setdefault(key, []).append(
            _row_to_exercise(row, tuple(sets_by_exercise[str(row["id"])]))
        )
    return {key: tuple(value) for key, value in occurrences.items()}


def _read_previous_performance(
    conn: sqlite3.Connection,
    workout: WorkoutRecord,
    exercises: tuple[ExerciseRecord, ...],
    *,
    user_id: str,
) -> tuple[ExercisePreviousPerformance | None, ...]:
    """Attach previous-session data to each exercise, parallel to `exercises`.

    At most three additional queries independent of graph size; occurrence
    pairing is positional within each catalog id, so a current occurrence beyond
    the previous session's occurrence count has no comparison.
    """
    catalog_ids = list(dict.fromkeys(exercise.catalog_id for exercise in exercises))
    if not catalog_ids:
        return tuple(None for _ in exercises)

    sessions = _select_previous_sessions(
        conn,
        user_id=user_id,
        workout_id=workout.id,
        started_at=workout.started_at,
        catalog_ids=catalog_ids,
    )
    if not sessions:
        return tuple(None for _ in exercises)

    occurrences = _select_previous_occurrences(
        conn,
        catalog_ids=catalog_ids,
        session_ids=list(dict.fromkeys(session.id for session in sessions.values())),
    )

    positions: dict[str, int] = {}
    result: list[ExercisePreviousPerformance | None] = []
    for exercise in exercises:
        position = positions.get(exercise.catalog_id, 0)
        positions[exercise.catalog_id] = position + 1
        session = sessions.get(exercise.catalog_id)
        paired = None if session is None else occurrences.get((session.id, exercise.catalog_id), ())
        if session is None or paired is None or position >= len(paired):
            result.append(None)
            continue
        result.append(
            _exercise_previous_performance(
                exercise,
                paired[position],
                session=session,
                current_bodyweight_kg=workout.bodyweight_kg,
            )
        )
    return tuple(result)


def _read_workout_graph(
    conn: sqlite3.Connection,
    workout_id: str,
    *,
    user_id: str,
    previous_performance_snapshot: str | None = None,
) -> WorkoutGraph | None:
    """Build the owner-scoped graph from bounded queries on the caller's connection.

    The caller owns transaction control: `get_workout_graph` wraps this in a
    deferred read transaction, and `save_workout` calls it inside its write
    transaction so the response graph is captured before the commit. Previous
    performance is assembled on that same snapshot, which keeps GET and PUT
    detail responses equal and prevents racing a second read after commit. An
    exact retry may supply its stored derived-history snapshot instead.
    """
    workout_row = conn.execute(
        f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE id = :id AND user_id = :user_id",
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
        sets_by_exercise[str(row["exercise_id"])].append(_row_to_set(row))
    exercises = tuple(
        _row_to_exercise(row, tuple(sets_by_exercise[str(row["id"])])) for row in exercise_rows
    )
    workout = row_to_workout(workout_row)
    previous_performance = (
        _read_previous_performance(conn, workout, exercises, user_id=user_id)
        if previous_performance_snapshot is None
        else _decode_previous_performance(previous_performance_snapshot)
    )
    if len(previous_performance) != len(exercises):
        raise RuntimeError("stored previous-performance receipt does not match workout graph")
    return WorkoutGraph(
        workout=workout,
        exercises=exercises,
        previous_performance=previous_performance,
    )


def get_workout_graph(
    database_path: str | Path, workout_id: str, *, user_id: str
) -> WorkoutGraph | None:
    """Fetch the owned workout and its full graph; foreign/unknown are `None`.

    Three queries regardless of graph size — the workout row, its exercises in
    stored order, and all their sets joined through the exercises in
    `(order_index, set_index)` order — plus at most three more for inline
    previous performance, also independent of graph size.
    """
    with connect(database_path) as conn, conn:
        # Every graph and previous-performance query must describe the same
        # committed revision.
        conn.execute("BEGIN")
        return _read_workout_graph(conn, workout_id, user_id=user_id)
