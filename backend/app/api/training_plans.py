"""Authenticated CRUD endpoints for reusable training plans."""

from typing import Annotated, cast

from fastapi import APIRouter, Query, Request, Response

from app.auth import CurrentUser
from app.config import Settings
from app.errors import ConflictError, NotFoundError, UnprocessableEntityError
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_NUMBER, MAX_PAGE_SIZE
from app.schemas.training_plans import (
    CreateTrainingPlanRequest,
    TrainingPlanExerciseResponse,
    TrainingPlanListResponse,
    TrainingPlanResponse,
    TrainingPlanSetResponse,
    TrainingPlanSummaryResponse,
    UpdateTrainingPlanRequest,
)
from app.schemas.workouts import Side
from app.services import training_plans

router = APIRouter(prefix="/training-plans", tags=["training-plans"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _response(plan: training_plans.TrainingPlan) -> TrainingPlanResponse:
    return TrainingPlanResponse(
        id=plan.id,
        name=plan.name,
        notes=plan.notes,
        revision=plan.revision,
        exercises=[
            TrainingPlanExerciseResponse(
                id=exercise.id,
                catalog_id=exercise.catalog_id,
                order_index=exercise.order_index,
                notes=exercise.notes,
                sets=[
                    TrainingPlanSetResponse(
                        id=item.id,
                        set_index=item.set_index,
                        target_reps=item.target_reps,
                        target_weight_kg=item.target_weight_kg,
                        side=cast(Side, item.side),
                        bw_percent_override=item.bw_percent_override,
                    )
                    for item in exercise.sets
                ],
            )
            for exercise in plan.exercises
        ],
    )


def _catalog_error(exc: training_plans.TrainingPlanCatalogError) -> UnprocessableEntityError:
    return UnprocessableEntityError(
        "Training plan validation failed",
        members={"errors": [{"field": "exercises", "message": str(exc)}]},
    )


@router.get("", response_model=TrainingPlanListResponse)
def list_training_plans(
    request: Request,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE_NUMBER)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, alias="pageSize")] = DEFAULT_PAGE_SIZE,
) -> TrainingPlanListResponse:
    result = training_plans.list_plans(
        _settings(request).database_path,
        owner_id=user.id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return TrainingPlanListResponse(
        items=[
            TrainingPlanSummaryResponse(
                id=item.id,
                name=item.name,
                notes=item.notes,
                revision=item.revision,
            )
            for item in result.items
        ],
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TrainingPlanResponse, status_code=201)
def create_training_plan(
    payload: CreateTrainingPlanRequest, request: Request, user: CurrentUser
) -> TrainingPlanResponse:
    try:
        plan = training_plans.create_plan(
            _settings(request).database_path, owner_id=user.id, content=payload
        )
    except training_plans.TrainingPlanCatalogError as exc:
        raise _catalog_error(exc) from None
    return _response(plan)


@router.get("/{plan_id}", response_model=TrainingPlanResponse)
def get_training_plan(plan_id: str, request: Request, user: CurrentUser) -> TrainingPlanResponse:
    plan = training_plans.get_plan(
        _settings(request).database_path, owner_id=user.id, plan_id=plan_id
    )
    if plan is None:
        raise NotFoundError("Training plan not found")
    return _response(plan)


@router.put("/{plan_id}", response_model=TrainingPlanResponse)
def update_training_plan(
    plan_id: str, payload: UpdateTrainingPlanRequest, request: Request, user: CurrentUser
) -> TrainingPlanResponse:
    try:
        plan = training_plans.update_plan(
            _settings(request).database_path,
            owner_id=user.id,
            plan_id=plan_id,
            expected_revision=payload.revision,
            content=payload,
        )
    except training_plans.TrainingPlanNotFoundError:
        raise NotFoundError("Training plan not found") from None
    except training_plans.TrainingPlanRevisionConflictError as exc:
        raise ConflictError(
            "The training plan has moved past this revision",
            code="revision_conflict",
            members={"current_revision": exc.current_revision},
        ) from None
    except training_plans.TrainingPlanCatalogError as exc:
        raise _catalog_error(exc) from None
    return _response(plan)


@router.delete("/{plan_id}", status_code=204)
def delete_training_plan(
    plan_id: str,
    request: Request,
    user: CurrentUser,
    revision: Annotated[int, Query(ge=0)],
) -> Response:
    try:
        training_plans.delete_plan(
            _settings(request).database_path,
            owner_id=user.id,
            plan_id=plan_id,
            expected_revision=revision,
        )
    except training_plans.TrainingPlanNotFoundError:
        raise NotFoundError("Training plan not found") from None
    except training_plans.TrainingPlanRevisionConflictError as exc:
        raise ConflictError(
            "The training plan has moved past this revision",
            code="revision_conflict",
            members={"current_revision": exc.current_revision},
        ) from None
    return Response(status_code=204)
