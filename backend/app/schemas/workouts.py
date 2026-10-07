"""Workout create/read schemas (PLAN.md §5, §6).

Creation accepts only client-controlled content: a client-generated UUID and a
timezone-aware `started_at`. Everything else on a workout row (recorded
bodyweight, revision, fingerprints, server timestamps) is server-controlled and
rejected as unknown input. Both inputs are normalized to their canonical stored
form (hyphenated lowercase UUID text, `YYYY-MM-DDTHH:MM:SSZ` UTC) before
validation completes, so retried creates fingerprint identically regardless of
input spelling.

Read responses are explicit: the detail shape carries the recorded load inputs
(workout bodyweight plus each exercise's immutable snapshot) and the ordering
indexes; derived loads are computed by clients from these inputs (PLAN.md §3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import LoadType
from app.timestamps import to_timestamp

# History date filters are local calendar dates; the bounds keep the UTC
# boundary arithmetic (±1 day, ±14 h offset) inside years that format as
# canonical four-digit UTC text.
MIN_HISTORY_DATE = date(1900, 1, 1)
MAX_HISTORY_DATE = date(9998, 12, 31)

WorkoutStatus = Literal["active", "finished"]
Side = Literal["left", "right", "bilateral"]

# Raw UUID text may carry hyphens, braces, or a `urn:uuid:` prefix; the parsed
# canonical form is always 36 characters.
UuidText = Annotated[str, Field(strict=True, min_length=32, max_length=45)]
TimestampText = Annotated[str, Field(strict=True, max_length=64)]


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
    return to_timestamp(moment)


class CreateWorkoutRequest(BaseModel):
    """POST /workouts input: an empty active workout with a client-generated id.

    The profile bodyweight is recorded by the service, never accepted here; a
    client corrects it later through bulk-save (PLAN.md §4).
    """

    model_config = ConfigDict(extra="forbid")

    id: UuidText
    started_at: TimestampText

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return normalize_uuid(value)

    @field_validator("started_at")
    @classmethod
    def _normalize_started_at(cls, value: str) -> str:
        return normalize_timestamp(value)


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


class ExerciseNodeResponse(BaseModel):
    """One workout exercise: catalog reference plus its immutable snapshot."""

    model_config = ConfigDict(extra="forbid")

    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    sets: list[SetResponse]


class WorkoutSummaryResponse(BaseModel):
    """One history list item; `ended_at = null` means active (PLAN.md §4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None
    started_at: str
    ended_at: str | None
    bodyweight_kg: int | None
    revision: int


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
    exercises: list[ExerciseNodeResponse]


class WorkoutListResponse(BaseModel):
    """One bounded history page (PLAN.md §6: total + paging)."""

    model_config = ConfigDict(extra="forbid")

    items: list[WorkoutSummaryResponse]
    total: int
    page: int
    page_size: int
