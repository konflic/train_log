"""Statistics summary endpoint (PLAN.md §7).

`GET /stats/summary` reports the caller's own eligible history: finished
workouts holding at least one completed set. The optional `date_from`/`date_to`
local-date bounds share the workout-history parser and filter every member
except `current_week_streak`, which always covers full history. Unknown volume
stays `null` while an empty selection is a known zero, and muscle-group
frequency follows the catalog's current classification because workout
exercise snapshots do not store the group.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.common import HistoryDate
from app.auth import CurrentUser
from app.config import Settings
from app.errors import ApiError
from app.numbers import NumericRangeError
from app.schemas.stats import MuscleGroupFrequencyResponse, StatsSummaryResponse
from app.services import stats

router = APIRouter(prefix="/stats", tags=["stats"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get("/summary", response_model=StatsSummaryResponse)
def get_stats_summary(
    request: Request,
    user: CurrentUser,
    date_from: HistoryDate | None = None,
    date_to: HistoryDate | None = None,
) -> StatsSummaryResponse:
    """The caller's bounded statistics summary for the selected local dates."""
    try:
        summary = stats.get_stats_summary(
            _settings(request).database_path,
            user_id=user.id,
            # Calendar grouping always uses the caller's current fixed offset
            # applied to the whole history (PLAN.md §7).
            utc_offset_minutes=user.utc_offset_minutes,
            date_from=date_from,
            date_to=date_to,
        )
    except NumericRangeError:
        # An aggregate beyond the shared JSON-safe range is a server-side
        # anomaly (per-set values are write-validated); fail explicitly rather
        # than emit an imprecise number or overload the unknown-volume null.
        raise ApiError(
            "Aggregated statistics exceed the supported integer range",
            code="stats_range_exceeded",
        ) from None
    return StatsSummaryResponse(
        workout_count=summary.workout_count,
        completed_set_count=summary.completed_set_count,
        training_day_count=summary.training_day_count,
        total_volume_kg_reps=summary.total_volume_kg_reps,
        unknown_load_set_count=summary.unknown_load_set_count,
        volume_complete=summary.volume_complete,
        # model_validate re-checks the stored group text against the response
        # schema's literal.
        muscle_group_frequency=[
            MuscleGroupFrequencyResponse.model_validate(
                {"muscle_group": item.muscle_group, "workout_count": item.workout_count}
            )
            for item in summary.muscle_group_frequency
        ],
        current_week_streak=summary.current_week_streak,
    )
