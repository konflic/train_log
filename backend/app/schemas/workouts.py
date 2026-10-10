"""Workout create/read/bulk-save schemas (PLAN.md §5, §6).

Creation accepts only client-controlled content: a client-generated UUID and a
timezone-aware `started_at`. Everything else on a workout row (recorded
bodyweight, revision, fingerprints, server timestamps) is server-controlled and
rejected as unknown input. Both inputs are normalized to their canonical stored
form (hyphenated lowercase UUID text, `YYYY-MM-DDTHH:MM:SSZ` UTC) before
validation completes, so retried creates fingerprint identically regardless of
input spelling.

The bulk-save (`PUT`) body is full state, not a patch: every field is required
and nullable fields must be sent explicitly as `null`, so omission is invalid
rather than meaning "keep" or "clear". UUID-typed ids are normalized before
duplicate checks and hashing; catalog ids are opaque visible-entry text and are
preserved exactly. Graph/text limits and payload-local duplicate ids are schema
failures; snapshot-dependent rules (side matrix, override permission,
completion) are resolved against stored/catalog rows by the service.

Read responses are explicit: the detail shape carries the recorded load inputs
(workout bodyweight plus each exercise's immutable snapshot) and the ordering
indexes; derived loads are computed by clients from these inputs (PLAN.md §3).
Stage 8a adds one additive read-only member, `previous_performance`, per
exercise: the paired occurrence of the most recent eligible earlier session with
its recorded inputs and the server-computed integer comparisons (PLAN.md §7).
Comparison values are historical facts about two recorded sessions, not
provisional client-side display values, so they are calculated on the server
from the same recorded inputs; display percentages remain a client calculation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.schemas.common import (
    BodyweightKg,
    LoadType,
    NonNegativeInteger,
    Percentage,
    Reps,
    Rpe,
    WeightKg,
)
from app.timestamps import to_timestamp

# Full-state bulk-save limits (IMPLEMENTATION.md Stage 6). They leave headroom
# within the shared 256 KiB request limit and bound SQL batches below SQLite's
# variable limit; the byte limit remains the final bound.
MAX_EXERCISES_PER_WORKOUT = 25
MAX_SETS_PER_EXERCISE = 20
MAX_SETS_PER_WORKOUT = 250
MAX_WORKOUT_NAME_LENGTH = 100
MAX_WORKOUT_NOTES_LENGTH = 2000
MAX_EXERCISE_NOTES_LENGTH = 300
MAX_CATALOG_ID_LENGTH = 100

WorkoutStatus = Literal["active", "finished"]
WorkoutSessionType = Literal["freestyle", "from_plan"]
Side = Literal["left", "right", "bilateral"]

# Raw UUID text may carry hyphens, braces, or a `urn:uuid:` prefix; the parsed
# canonical form is always 36 characters.
UuidText = Annotated[str, Field(strict=True, min_length=32, max_length=45)]
TimestampText = Annotated[str, Field(strict=True, max_length=64)]

# Catalog ids are opaque visible-entry ids, not normalized UUIDs; validated
# text is preserved exactly (no implicit trim or empty-to-null conversion).
CatalogIdText = Annotated[str, Field(strict=True, min_length=1, max_length=MAX_CATALOG_ID_LENGTH)]
WorkoutNameText = Annotated[str, Field(strict=True, max_length=MAX_WORKOUT_NAME_LENGTH)]
WorkoutNotesText = Annotated[str, Field(strict=True, max_length=MAX_WORKOUT_NOTES_LENGTH)]
ExerciseNotesText = Annotated[str, Field(strict=True, max_length=MAX_EXERCISE_NOTES_LENGTH)]


def normalize_uuid(value: str) -> str:
    """Parse a client-generated UUID and return its canonical hyphenated text."""
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError("id must be a valid UUID") from None
    return str(parsed)


def normalize_timestamp(value: str) -> str:
    """Parse an ISO-8601 date-time and return canonical UTC text.

    A timezone-aware input is required (PLAN.md §6: naive local times are
    ambiguous); any explicit offset is accepted and converted to UTC.
    Sub-second precision is truncated to whole seconds, the storage format.
    """
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("timestamp must be an ISO-8601 date-time") from None
    if moment.tzinfo is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    try:
        return to_timestamp(moment)
    except OverflowError:
        raise ValueError("timestamp is outside the supported UTC range") from None


class CreateWorkoutRequest(BaseModel):
    """POST /workouts input: an empty active workout with a client-generated id.

    The profile bodyweight is recorded by the service, never accepted here; a
    client corrects it later through bulk-save (PLAN.md §4).
    """

    model_config = ConfigDict(extra="forbid")

    id: UuidText
    started_at: TimestampText
    session_type: WorkoutSessionType = "freestyle"
    source_plan_id: UuidText | None = None
    source_plan_revision: NonNegativeInteger | None = None

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return normalize_uuid(value)

    @field_validator("started_at")
    @classmethod
    def _normalize_started_at(cls, value: str) -> str:
        return normalize_timestamp(value)

    @field_validator("source_plan_id")
    @classmethod
    def _normalize_source_plan_id(cls, value: str | None) -> str | None:
        return None if value is None else normalize_uuid(value)

    @model_validator(mode="after")
    def validate_session_source(self) -> CreateWorkoutRequest:
        planned = self.session_type == "from_plan"
        if planned != (self.source_plan_id is not None):
            raise ValueError("source_plan_id is required only for from_plan sessions")
        if planned != (self.source_plan_revision is not None):
            raise ValueError("source_plan_revision is required only for from_plan sessions")
        return self


class SaveSetRequest(BaseModel):
    """One set of the full-state graph; every field is required.

    Nullable values must be sent explicitly as `null`. `set_index` is rejected:
    the array position within its exercise is the only order input. Side,
    override-permission, and completion rules depend on the exercise's resolved
    snapshot and are enforced by the service, not here.
    """

    model_config = ConfigDict(extra="forbid")

    id: UuidText
    reps: Reps | None
    weight_kg: WeightKg | None
    bw_percent_override: Percentage | None
    rpe: Rpe | None
    side: Side
    done: StrictBool

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return normalize_uuid(value)


class SaveExerciseRequest(BaseModel):
    """One exercise of the full-state graph; every field is required.

    `catalog_id` references a currently visible entry for new instances and
    must equal the stored reference for retained ones (checked by the service).
    `order_index` and snapshot fields (`load_type`, `bodyweight_percent`,
    `side_count`) are server-controlled and rejected. An empty set array is
    valid.
    """

    model_config = ConfigDict(extra="forbid")

    id: UuidText
    catalog_id: CatalogIdText
    notes: ExerciseNotesText | None
    sets: list[SaveSetRequest] = Field(max_length=MAX_SETS_PER_EXERCISE)

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return normalize_uuid(value)


class SaveWorkoutRequest(BaseModel):
    """PUT /workouts/{id} input: the complete writable workout state.

    Full state, not a patch: `revision`, `save_id`, `name`, `notes`,
    `bodyweight_kg`, `ended_at`, and `exercises` are all required, and nullable
    fields must be explicit `null`. `started_at` is immutable after POST and is
    rejected, as is the workout id (it comes only from the path). An empty
    exercise array is valid and deletes the graph. Duplicate exercise ids
    (across the array) and duplicate set ids (across the entire submitted
    graph) are rejected after UUID normalization; error messages carry array
    positions only, never the rejected values.
    """

    model_config = ConfigDict(extra="forbid")

    revision: NonNegativeInteger
    save_id: UuidText
    name: WorkoutNameText | None
    notes: WorkoutNotesText | None
    bodyweight_kg: BodyweightKg | None
    ended_at: TimestampText | None
    exercises: list[SaveExerciseRequest] = Field(max_length=MAX_EXERCISES_PER_WORKOUT)

    @field_validator("save_id")
    @classmethod
    def _normalize_save_id(cls, value: str) -> str:
        return normalize_uuid(value)

    @field_validator("ended_at")
    @classmethod
    def _normalize_ended_at(cls, value: str | None) -> str | None:
        return None if value is None else normalize_timestamp(value)

    @model_validator(mode="after")
    def validate_graph(self) -> SaveWorkoutRequest:
        seen_exercise_ids: set[str] = set()
        seen_set_ids: set[str] = set()
        total_sets = 0
        for position, exercise in enumerate(self.exercises):
            if exercise.id in seen_exercise_ids:
                raise ValueError(f"duplicate exercise id at exercises.{position}")
            seen_exercise_ids.add(exercise.id)
            total_sets += len(exercise.sets)
            for set_position, submitted_set in enumerate(exercise.sets):
                if submitted_set.id in seen_set_ids:
                    raise ValueError(
                        f"duplicate set id at exercises.{position}.sets.{set_position}"
                    )
                seen_set_ids.add(submitted_set.id)
        if total_sets > MAX_SETS_PER_WORKOUT:
            raise ValueError(f"graph exceeds {MAX_SETS_PER_WORKOUT} sets per workout")
        return self


class SetResponse(BaseModel):
    """One stored set with its recorded inputs and completion flag."""

    model_config = ConfigDict(extra="forbid")

    id: str
    set_index: int
    reps: int | None
    weight_kg: int | None
    bw_percent_override: int | None
    rpe: int | None
    side: Side
    done: bool


class SetValuesResponse(BaseModel):
    """Reported integer values for one compared set; `null` means unknown.

    One shape serves a previous occurrence's derived values and the current,
    previous, and delta members of a pair, so a client renders any of them the
    same way. A `null` load-based value is either an unknown recorded input or
    an incompatible comparison; `load_compatible` distinguishes the two.
    """

    model_config = ConfigDict(extra="forbid")

    reps: int | None
    external_load_kg: int | None
    effective_load_kg: int | None
    volume_kg_reps: int | None
    estimated_1rm_kg: int | None


class PreviousSetResponse(BaseModel):
    """One completed set of the paired previous occurrence (PLAN.md §7).

    Recorded inputs plus the values derived from that session's own recorded
    bodyweight and exercise snapshot. Only `done=true` sets appear; unfinished
    history never contributes performance.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    set_index: int
    side: Side
    reps: int | None
    weight_kg: int | None
    bw_percent_override: int | None
    values: SetValuesResponse


class PreviousSetPairResponse(BaseModel):
    """One side-aware comparison between a current and a previous completed set.

    Pairs are matched by side and per-side ordinal and listed in current set
    order; both set ids are echoed so a client never relies on positions. An
    unmatched current set has no entry and therefore no delta. When
    `load_compatible` is false, only `reps` is compared and every load-based
    value is `null` on all three members, so a later catalog edit cannot
    fabricate progression.
    """

    model_config = ConfigDict(extra="forbid")

    current_set_id: str
    previous_set_id: str
    load_compatible: StrictBool
    current: SetValuesResponse
    previous: SetValuesResponse
    delta: SetValuesResponse


class PreviousPerformanceResponse(BaseModel):
    """The selected previous session occurrence paired with one current exercise.

    `sets` is the previous occurrence's complete completed-set list, so an
    active workout can show "last time" before any current set is done; `pairs`
    holds only the matched comparisons. All values come from that session's
    recorded bodyweight and immutable exercise snapshot.
    """

    model_config = ConfigDict(extra="forbid")

    workout_id: str
    started_at: str
    bodyweight_kg: int | None
    exercise_id: str
    order_index: int
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    sets: list[PreviousSetResponse]
    pairs: list[PreviousSetPairResponse]


class ExerciseNodeResponse(BaseModel):
    """One workout exercise: catalog reference plus its immutable snapshot.

    `previous_performance` is additive and `null` when no eligible previous
    session occurrence pairs with this exercise.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    sets: list[SetResponse]
    previous_performance: PreviousPerformanceResponse | None


class WorkoutSummaryResponse(BaseModel):
    """One history list item; `ended_at = null` means active (PLAN.md §4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None
    started_at: str
    ended_at: str | None
    bodyweight_kg: int | None
    revision: int
    session_type: WorkoutSessionType | None
    source_plan_id: str | None
    total_volume_kg_reps: int | None
    volume_complete: bool


class WorkoutDetailResponse(BaseModel):
    """The authoritative workout: metadata, receipt state, and ordered graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None
    started_at: str
    ended_at: str | None
    notes: str | None
    bodyweight_kg: int | None
    revision: int
    last_save_id: str | None
    session_type: WorkoutSessionType | None
    source_plan_id: str | None
    exercises: list[ExerciseNodeResponse]


class WorkoutListResponse(BaseModel):
    """One bounded history page (PLAN.md §6: total + paging)."""

    model_config = ConfigDict(extra="forbid")

    items: list[WorkoutSummaryResponse]
    total: int
    page: int
    page_size: int
