"""Exercise catalog endpoints (PLAN.md §4, §6).

Lists combine the global defaults with the caller's private custom entries;
search is a Unicode case-insensitive substring match on the name and the
order is stable (casefolded name, `id` tie-break) across bounded pages.
Mutations manage custom entries only: defaults are immutable through the API
(403), and another user's entry is indistinguishable from an unknown id (404).
An entry referenced by workout history cannot be deleted (409). Editing a
custom entry applies to future workout instances; recorded exercise snapshots
are never rewritten. The Stage 3 conventions apply unchanged: problem+json
errors, request ids, Origin/JSON CSRF checks on every mutating verb, body
size limits, and empty 204 responses.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.auth import CurrentUser
from app.config import Settings
from app.errors import ConflictError, ForbiddenError, NotFoundError
from app.schemas.exercises import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_SEARCH_LENGTH,
    CreateExerciseRequest,
    Equipment,
    ExerciseListResponse,
    ExerciseResponse,
    MuscleGroup,
    UpdateExerciseRequest,
)
from app.services import catalog
from app.services.catalog import CatalogEntry, DuplicateNameError, EntryInUseError

router = APIRouter(prefix="/exercises", tags=["exercises"])

PageNumber = Annotated[int, Query(ge=1)]
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
            "equipment": entry.equipment,
            "load_type": entry.load_type,
            "bodyweight_percent": entry.bodyweight_percent,
            "side_count": entry.side_count,
            "is_default": entry.is_default,
        }
    )


def _require_visible_entry(request: Request, entry_id: str, user_id: str) -> CatalogEntry:
    entry = catalog.get_visible_entry(_settings(request).database_path, entry_id, viewer_id=user_id)
    if entry is None:
        raise NotFoundError("Exercise not found")
    return entry


def _name_taken() -> ConflictError:
    return ConflictError("A custom exercise with this name already exists", code="name_taken")


def _merged_content(entry: CatalogEntry, patch: UpdateExerciseRequest) -> dict[str, Any]:
    """Merge stored content with provided patch fields and validate the result.

    Cross-field load rules hold for the merged entry, so a partial update can
    never produce content a full create would reject; failures surface with
    the same 422 problem document as direct body validation.
    """
    merged: dict[str, Any] = {
        "name": entry.name,
        "muscle_group": entry.muscle_group,
        "equipment": entry.equipment,
        "load_type": entry.load_type,
        "bodyweight_percent": entry.bodyweight_percent,
        "side_count": entry.side_count,
    }
    merged.update(patch.model_dump(exclude_unset=True))
    try:
        validated = CreateExerciseRequest.model_validate(merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None
    return validated.model_dump()


@router.get("", response_model=ExerciseListResponse)
def list_exercises(
    request: Request,
    user: CurrentUser,
    page: PageNumber = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
    search: SearchText | None = None,
    muscle_group: MuscleGroup | None = None,
    equipment: Equipment | None = None,
) -> ExerciseListResponse:
    """Defaults plus the caller's customs, with optional search and filters."""
    result = catalog.list_entries(
        _settings(request).database_path,
        viewer_id=user.id,
        limit=page_size,
        offset=(page - 1) * page_size,
        search=search,
        muscle_group=muscle_group,
        equipment=equipment,
    )
    return ExerciseListResponse(
        items=[_exercise_response(entry) for entry in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ExerciseResponse, status_code=201)
def create_exercise(
    payload: CreateExerciseRequest, request: Request, user: CurrentUser
) -> ExerciseResponse:
    """Create an owner-private custom entry with a server-generated UUID id."""
    try:
        entry = catalog.create_custom_entry(
            _settings(request).database_path,
            owner_id=user.id,
            name=payload.name,
            muscle_group=payload.muscle_group,
            equipment=payload.equipment,
            load_type=payload.load_type,
            bodyweight_percent=payload.bodyweight_percent,
            side_count=payload.side_count,
        )
    except DuplicateNameError:
        raise _name_taken() from None
    return _exercise_response(entry)


@router.get("/{entry_id}", response_model=ExerciseResponse)
def get_exercise(entry_id: str, request: Request, user: CurrentUser) -> ExerciseResponse:
    entry = _require_visible_entry(request, entry_id, user.id)
    return _exercise_response(entry)


@router.patch("/{entry_id}", response_model=ExerciseResponse)
def update_exercise(
    entry_id: str, payload: UpdateExerciseRequest, request: Request, user: CurrentUser
) -> ExerciseResponse:
    """Edit the caller's custom entry; defaults are immutable (403)."""
    entry = _require_visible_entry(request, entry_id, user.id)
    if entry.is_default:
        raise ForbiddenError("Default catalog entries cannot be edited", code="default_immutable")
    updates = _merged_content(entry, payload)
    try:
        updated = catalog.update_custom_entry(
            _settings(request).database_path, entry_id, owner_id=user.id, updates=updates
        )
    except DuplicateNameError:
        raise _name_taken() from None
    if updated is None:
        # The entry vanished between the visibility check and the update.
        raise NotFoundError("Exercise not found")
    return _exercise_response(updated)


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
            "This exercise is used by workout history and cannot be deleted",
            code="entry_in_use",
        ) from None
    if not deleted:
        # The entry vanished between the visibility check and the delete.
        raise NotFoundError("Exercise not found")
    return Response(status_code=204)
