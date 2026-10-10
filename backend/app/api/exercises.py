"""Exercise catalog endpoints (PLAN.md §4, §6).

Lists combine the global defaults with the caller's private custom entries;
search is a Unicode case-insensitive substring match on the name and the
order is stable (casefolded name, `id` tie-break) across bounded pages. The
list carries compact summaries only; `GET /exercises/{id}` and the custom
POST/PATCH responses carry the detail shape (summary plus the optional
description and, for seeded defaults, the validated guidance bundle from the
version-controlled registry). `GET /exercises/{id}/stats` reports the
caller's own per-exercise totals and latest-12-session volume series.
Mutations manage custom entries only: defaults are immutable through the API
(403), and another user's entry is indistinguishable from an unknown id (404).
An entry referenced by workout history cannot be deleted (409). Editing a
custom entry applies to future workout instances; recorded exercise snapshots
are never rewritten. The Stage 3 conventions apply unchanged: problem+json
errors, request ids, Origin/JSON CSRF checks on every mutating verb, body
size limits, and empty 204 responses.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.auth import CurrentUser
from app.config import Settings
from app.errors import ApiError, ConflictError, ForbiddenError, NotFoundError
from app.guidance import DEFAULT_GUIDANCE, ExerciseGuidance
from app.numbers import NumericRangeError
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_NUMBER, MAX_PAGE_SIZE
from app.schemas.exercises import (
    MAX_SEARCH_LENGTH,
    CreateExerciseRequest,
    ExerciseDetailResponse,
    ExerciseListResponse,
    ExerciseResponse,
    MuscleGroup,
    UpdateExerciseRequest,
)
from app.schemas.stats import ExerciseStatsResponse, ExerciseStatsSessionResponse
from app.services import catalog, exercise_stats
from app.services.catalog import CatalogEntry, DuplicateNameError, EntryInUseError

router = APIRouter(prefix="/exercises", tags=["exercises"])

PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, alias="pageSize")]
SearchText = Annotated[str, Query(max_length=MAX_SEARCH_LENGTH)]


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _exercise_response(entry: CatalogEntry) -> ExerciseResponse:
    # model_validate keeps the public shape explicit (no `created_by`) and
    # re-checks the stored values against the response schema's literals.
    return ExerciseResponse.model_validate(
        {
            "id": entry.id,
            "name": entry.name,
            "muscle_group": entry.muscle_group,
            "load_type": entry.load_type,
            "bodyweight_percent": entry.bodyweight_percent,
            "side_count": entry.side_count,
            "is_default": entry.is_default,
        }
    )


def _guidance_payload(entry: CatalogEntry) -> dict[str, object] | None:
    """The registry bundle for a seeded default; customs never have guidance.

    Defaults without a registry entry (impossible while the consistency test
    is green) degrade to `guidance=null` rather than fabricating content.
    """
    if not entry.is_default:
        return None
    guidance: ExerciseGuidance | None = DEFAULT_GUIDANCE.get(entry.id)
    if guidance is None:
        return None
    return {
        "technique_steps": list(guidance.technique_steps),
        "form_tips": list(guidance.form_tips),
        "animation_key": guidance.animation_key,
        "sources": [{"title": source.title, "url": source.url} for source in guidance.sources],
    }


def _detail_response(entry: CatalogEntry) -> ExerciseDetailResponse:
    # model_validate re-checks the registry content against the response
    # schema's bounds on every serialization.
    return ExerciseDetailResponse.model_validate(
        {
            "id": entry.id,
            "name": entry.name,
            "muscle_group": entry.muscle_group,
            "load_type": entry.load_type,
            "bodyweight_percent": entry.bodyweight_percent,
            "side_count": entry.side_count,
            "is_default": entry.is_default,
            "description": entry.description,
            "guidance": _guidance_payload(entry),
        }
    )


def _require_visible_entry(request: Request, entry_id: str, user_id: str) -> CatalogEntry:
    entry = catalog.get_visible_entry(_settings(request).database_path, entry_id, viewer_id=user_id)
    if entry is None:
        raise NotFoundError("Exercise not found")
    return entry


def _name_taken() -> ConflictError:
    return ConflictError("A custom exercise with this name already exists", code="name_taken")


@router.get("", response_model=ExerciseListResponse)
def list_exercises(
    request: Request,
    user: CurrentUser,
    page: PageNumber = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
    search: SearchText | None = None,
    muscle_group: MuscleGroup | None = None,
) -> ExerciseListResponse:
    """Defaults plus the caller's customs, with optional search and filters."""
    result = catalog.list_entries(
        _settings(request).database_path,
        viewer_id=user.id,
        limit=page_size,
        offset=(page - 1) * page_size,
        search=search,
        muscle_group=muscle_group,
    )
    return ExerciseListResponse(
        items=[_exercise_response(entry) for entry in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ExerciseDetailResponse, status_code=201)
def create_exercise(
    payload: CreateExerciseRequest, request: Request, user: CurrentUser
) -> ExerciseDetailResponse:
    """Create an owner-private custom entry with a server-generated UUID id."""
    try:
        entry = catalog.create_custom_entry(
            _settings(request).database_path,
            owner_id=user.id,
            name=payload.name,
            muscle_group=payload.muscle_group,
            load_type=payload.load_type,
            bodyweight_percent=payload.bodyweight_percent,
            side_count=payload.side_count,
            description=payload.description,
        )
    except DuplicateNameError:
        raise _name_taken() from None
    return _detail_response(entry)


@router.get("/{entry_id}", response_model=ExerciseDetailResponse)
def get_exercise(entry_id: str, request: Request, user: CurrentUser) -> ExerciseDetailResponse:
    entry = _require_visible_entry(request, entry_id, user.id)
    return _detail_response(entry)


@router.get("/{entry_id}/stats", response_model=ExerciseStatsResponse)
def get_exercise_stats(entry_id: str, request: Request, user: CurrentUser) -> ExerciseStatsResponse:
    """The caller's lifetime totals and latest-12 volume series for one entry.

    A foreign custom id is indistinguishable from an unknown id (404), and
    every statistic derives from recorded workout snapshots only.
    """
    _require_visible_entry(request, entry_id, user.id)
    try:
        stats = exercise_stats.get_exercise_stats(
            _settings(request).database_path,
            user_id=user.id,
            catalog_id=entry_id,
        )
    except NumericRangeError:
        # An aggregate beyond the shared JSON-safe range is a server-side
        # anomaly (per-set values are write-validated); fail explicitly rather
        # than emit an imprecise number or a fabricated missing-data state.
        raise ApiError(
            "Aggregated statistics exceed the supported integer range",
            code="stats_range_exceeded",
        ) from None
    return ExerciseStatsResponse(
        training_count=stats.training_count,
        completed_set_count=stats.completed_set_count,
        total_volume_kg_reps=stats.total_volume_kg_reps,
        unknown_load_set_count=stats.unknown_load_set_count,
        volume_complete=stats.volume_complete,
        best_estimated_1rm_kg=stats.best_estimated_1rm_kg,
        sessions=[
            ExerciseStatsSessionResponse.model_validate(
                {
                    "workout_id": session.workout_id,
                    "started_at": session.started_at,
                    "completed_set_count": session.completed_set_count,
                    "volume_kg_reps": session.volume_kg_reps,
                    "unknown_load_set_count": session.unknown_load_set_count,
                    "volume_complete": session.volume_complete,
                }
            )
            for session in stats.sessions
        ],
    )


@router.patch("/{entry_id}", response_model=ExerciseDetailResponse)
def update_exercise(
    entry_id: str, payload: UpdateExerciseRequest, request: Request, user: CurrentUser
) -> ExerciseDetailResponse:
    """Edit the caller's custom entry; defaults are immutable (403)."""
    entry = _require_visible_entry(request, entry_id, user.id)
    if entry.is_default:
        raise ForbiddenError("Default catalog entries cannot be edited", code="default_immutable")
    try:
        updated = catalog.update_custom_entry(
            _settings(request).database_path,
            entry_id,
            owner_id=user.id,
            updates=payload.model_dump(exclude_unset=True),
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None
    except DuplicateNameError:
        raise _name_taken() from None
    if updated is None:
        # The entry vanished between the visibility check and the update.
        raise NotFoundError("Exercise not found")
    return _detail_response(updated)


@router.delete("/{entry_id}", status_code=204)
def delete_exercise(entry_id: str, request: Request, user: CurrentUser) -> Response:
    """Delete the caller's unreferenced custom entry (empty 204)."""
    entry = _require_visible_entry(request, entry_id, user.id)
    if entry.is_default:
        raise ForbiddenError("Default catalog entries cannot be deleted", code="default_immutable")
    try:
        deleted = catalog.delete_custom_entry(
            _settings(request).database_path, entry_id, owner_id=user.id
        )
    except EntryInUseError:
        raise ConflictError(
            "This exercise is used by a workout or training plan and cannot be deleted",
            code="entry_in_use",
        ) from None
    if not deleted:
        # The entry vanished between the visibility check and the delete.
        raise NotFoundError("Exercise not found")
    return Response(status_code=204)
