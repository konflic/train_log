"""Statistics summary response schemas (PLAN.md §7).

The Phase 1 summary is a fixed, bounded payload: no pagination, no time
series, and no averages. Every member is an exact nonnegative integer, an
explicit boolean, or `null` for an unknown total. `total_volume_kg_reps` is
`null` exactly when the selection holds at least one eligible set and every
eligible volume is unknown; an empty selection is a known zero.
`muscle_group_frequency` always carries all eight groups in the canonical
catalog order, and `current_week_streak` covers full history regardless of the
date filters.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.schemas.common import NonNegativeInteger
from app.schemas.exercises import MuscleGroup

# The service emits every group exactly once, so the length is part of the
# contract rather than an implementation detail.
MUSCLE_GROUP_COUNT = 8


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
