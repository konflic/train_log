"""Statistics response schemas (PLAN.md §7).

The Phase 1 summary is a fixed, bounded payload: no pagination, no time
series, and no averages. Every member is an exact nonnegative integer, an
explicit boolean, or `null` for an unknown total. `total_volume_kg_reps` is
`null` exactly when the selection holds at least one eligible set and every
eligible volume is unknown; an empty selection is a known zero.
`muscle_group_frequency` always carries all eight groups in the canonical
catalog order, and `current_week_streak` covers full history regardless of
the date filters.

The per-exercise statistics (exercise information screen) reuse the same
eligibility, null, and completeness semantics at both lifetime and session
level, and add a bounded latest-12-session volume series ordered
oldest-to-newest. It is not the general Phase 3 statistics suite.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.numbers import MAX_SAFE_INTEGER
from app.schemas.common import NonNegativeInteger
from app.schemas.exercises import MuscleGroup

# The service emits every group exactly once, so the length is part of the
# contract rather than an implementation detail.
MUSCLE_GROUP_COUNT = 8

# The exercise volume series covers the latest eligible finished workouts.
MAX_EXERCISE_STATS_SESSIONS = 12


class MuscleGroupFrequencyResponse(BaseModel):
    """One muscle group's eligible-workout count in the selected range.

    The count deduplicates workouts within the group and follows the catalog
    entry's current classification; workout exercise snapshots do not store
    the muscle group (Stage 8b resolved decision 7).
    """

    model_config = ConfigDict(extra="forbid")

    muscle_group: MuscleGroup
    workout_count: NonNegativeInteger


class StatsSummaryResponse(BaseModel):
    """GET /stats/summary: the caller's own eligible-history statistics.

    Only finished workouts with at least one completed set contribute. Volumes
    derive from recorded workout bodyweights and exercise snapshots, so later
    profile or catalog load-setting edits never rewrite the reported totals.
    """

    model_config = ConfigDict(extra="forbid")

    workout_count: NonNegativeInteger
    completed_set_count: NonNegativeInteger
    training_day_count: NonNegativeInteger
    total_volume_kg_reps: NonNegativeInteger | None
    unknown_load_set_count: NonNegativeInteger
    volume_complete: StrictBool
    muscle_group_frequency: Annotated[
        list[MuscleGroupFrequencyResponse],
        Field(min_length=MUSCLE_GROUP_COUNT, max_length=MUSCLE_GROUP_COUNT),
    ]
    current_week_streak: NonNegativeInteger


class ExerciseStatsSessionResponse(BaseModel):
    """One eligible finished workout's aggregate for the requested exercise.

    Repeated occurrences of the catalog exercise inside one workout are
    aggregated into this single session point. `volume_kg_reps` is `null`
    exactly when every eligible set's load is unknown; a partial sum keeps
    `volume_complete=false` with a positive `unknown_load_set_count`.
    """

    model_config = ConfigDict(extra="forbid")

    workout_id: str
    started_at: str
    completed_set_count: Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE_INTEGER)]
    volume_kg_reps: NonNegativeInteger | None
    unknown_load_set_count: NonNegativeInteger
    volume_complete: StrictBool


class ExerciseStatsResponse(BaseModel):
    """GET /exercises/{id}/stats: the caller's per-exercise progress summary.

    Lifetime totals cover all eligible history; `sessions` carries at most the
    latest 12 eligible workouts under `(started_at DESC, id DESC)`, emitted
    oldest-to-newest. `best_estimated_1rm_kg` reuses the server 1RM contract
    and stays `null` for bodyweight, weighted-bodyweight, and ineligible sets.
    """

    model_config = ConfigDict(extra="forbid")

    training_count: NonNegativeInteger
    completed_set_count: NonNegativeInteger
    total_volume_kg_reps: NonNegativeInteger | None
    unknown_load_set_count: NonNegativeInteger
    volume_complete: StrictBool
    best_estimated_1rm_kg: NonNegativeInteger | None
    sessions: Annotated[
        list[ExerciseStatsSessionResponse],
        Field(max_length=MAX_EXERCISE_STATS_SESSIONS),
    ]
