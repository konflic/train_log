"""Workout create/read endpoints (PLAN.md §5, §6).

`POST /workouts` creates an empty active workout from a client-generated UUID
and `started_at`, recording the profile bodyweight snapshot at revision 0. The
create is idempotent: retrying the same id with the same validated content
returns the existing owned workout (200 instead of 201), while any other reuse
of the id is a 409 — including the same content from a different user, whose
fingerprint never matches and who never sees the stored row. `GET /workouts`
lists the caller's history (status and local-date filters, bounded paging,
stable newest-first order); `GET /workouts/{id}` returns the authoritative
graph. Another user's workout is a plain 404. The Stage 3 conventions apply
unchanged: problem+json errors, request ids, Origin/JSON CSRF checks on
mutating verbs, and body size limits.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import BeforeValidator

from app.auth import CurrentUser
from app.config import Settings
from app.errors import ConflictError, NotFoundError
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_NUMBER, MAX_PAGE_SIZE
from app.schemas.workouts import (
    MAX_HISTORY_DATE,
    MIN_HISTORY_DATE,
    CreateWorkoutRequest,
    ExerciseNodeResponse,
    SetResponse,
    WorkoutDetailResponse,
    WorkoutListResponse,
    WorkoutStatus,
    WorkoutSummaryResponse,
)
from app.services import workouts
from app.services.workouts import CreateConflictError, ExerciseRecord, WorkoutGraph

router = APIRouter(prefix="/workouts", tags=["workouts"])

PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, alias="pageSize")]
StatusFilter = Annotated[WorkoutStatus, Query()]


def _parse_history_date(value: object) -> date:
    """Accept an ISO calendar date, never a coerced timestamp."""
    if not isinstance(value, str) or (
        len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
        or not (value[:4] + value[5:7] + value[8:]).isdigit()
    ):
        raise ValueError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("date must be a valid calendar date") from None


HistoryDate = Annotated[
    date,
    BeforeValidator(_parse_history_date),
    Query(ge=MIN_HISTORY_DATE, le=MAX_HISTORY_DATE),
]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _set_response(record: workouts.SetRecord) -> SetResponse:
    # model_validate keeps the public shape explicit and re-checks the stored
    # values against the response schema's literals.
    return SetResponse.model_validate(
        {
            "id": record.id,
            "set_index": record.set_index,
            "reps": record.reps,
            "weight_kg": record.weight_kg,
            "bw_percent_override": record.bw_percent_override,
            "rpe": record.rpe,
            "side": record.side,
            "done": record.done,
        }
    )


def _exercise_response(record: ExerciseRecord) -> ExerciseNodeResponse:
    return ExerciseNodeResponse.model_validate(
        {
            "id": record.id,
            "catalog_id": record.catalog_id,
            "order_index": record.order_index,
            "notes": record.notes,
            "load_type": record.load_type,
            "bodyweight_percent": record.bodyweight_percent,
            "side_count": record.side_count,
            "sets": [_set_response(item) for item in record.sets],
        }
    )


def _summary_response(record: workouts.WorkoutRecord) -> WorkoutSummaryResponse:
    return WorkoutSummaryResponse(
        id=record.id,
        name=record.name,
        started_at=record.started_at,
        ended_at=record.ended_at,
        bodyweight_kg=record.bodyweight_kg,
        revision=record.revision,
    )


def _detail_response(graph: WorkoutGraph) -> WorkoutDetailResponse:
    workout = graph.workout
    return WorkoutDetailResponse(
        id=workout.id,
        name=workout.name,
        started_at=workout.started_at,
        ended_at=workout.ended_at,
        notes=workout.notes,
        bodyweight_kg=workout.bodyweight_kg,
        revision=workout.revision,
        last_save_id=workout.last_save_id,
        exercises=[_exercise_response(exercise) for exercise in graph.exercises],
    )


@router.get("", response_model=WorkoutListResponse)
def list_workouts(
    request: Request,
    user: CurrentUser,
    page: PageNumber = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
    status: StatusFilter | None = None,
    date_from: HistoryDate | None = None,
    date_to: HistoryDate | None = None,
) -> WorkoutListResponse:
    """The caller's history, newest first, with status and local-date filters."""
    result = workouts.list_workouts(
        _settings(request).database_path,
        user_id=user.id,
        limit=page_size,
        offset=(page - 1) * page_size,
        status=status,
        date_from=date_from,
        date_to=date_to,
        # Date filters are the caller's local calendar dates (PLAN.md §4).
        utc_offset_minutes=user.utc_offset_minutes,
    )
    return WorkoutListResponse(
        items=[_summary_response(record) for record in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=WorkoutDetailResponse, status_code=201)
def create_workout(
    payload: CreateWorkoutRequest, request: Request, response: Response, user: CurrentUser
) -> WorkoutDetailResponse:
    """Create an empty active workout; an exact retry returns the existing one.

    The response is the authoritative current state at revision 0: recorded
    bodyweight snapshot, no graph, and no save receipt yet.
    """
    fingerprint = workouts.create_request_hash(
        user_id=user.id, workout_id=payload.id, started_at=payload.started_at
    )
    try:
        _, created = workouts.create_workout(
            _settings(request).database_path,
            owner_id=user.id,
            workout_id=payload.id,
            started_at=payload.started_at,
            request_hash=fingerprint,
        )
    except CreateConflictError:
        # Generic detail: the id may belong to another user, whose data must
        # stay indistinguishable from a plain content conflict.
        raise ConflictError(
            "A workout with this id already exists", code="create_conflict"
        ) from None
    if not created:
        response.status_code = 200
    graph = workouts.get_workout_graph(
        _settings(request).database_path, payload.id, user_id=user.id
    )
    if graph is None:
        # The row was created (or found) moments ago within this request.
        raise NotFoundError("Workout not found")
    return _detail_response(graph)


@router.get("/{workout_id}", response_model=WorkoutDetailResponse)
def get_workout(workout_id: str, request: Request, user: CurrentUser) -> WorkoutDetailResponse:
    """The owned workout's metadata and full ordered graph; foreign is 404."""
    graph = workouts.get_workout_graph(
        _settings(request).database_path, workout_id, user_id=user.id
    )
    if graph is None:
        raise NotFoundError("Workout not found")
    return _detail_response(graph)
