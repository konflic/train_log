"""Explicit request and response schemas for reusable training plans."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.schemas.common import NonNegativeInteger, Percentage, Reps, WeightKg
from app.schemas.workouts import (
    MAX_EXERCISES_PER_WORKOUT,
    MAX_SETS_PER_EXERCISE,
    MAX_SETS_PER_WORKOUT,
    CatalogIdText,
    ExerciseNotesText,
    Side,
    WorkoutNameText,
    WorkoutNotesText,
)


class TrainingPlanSetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_reps: Reps | None
    target_weight_kg: WeightKg | None
    side: Side
    bw_percent_override: Percentage | None


class TrainingPlanExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: CatalogIdText
    notes: ExerciseNotesText | None
    sets: list[TrainingPlanSetInput] = Field(max_length=MAX_SETS_PER_EXERCISE)


class TrainingPlanContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WorkoutNameText
    notes: WorkoutNotesText | None
    exercises: list[TrainingPlanExerciseInput] = Field(max_length=MAX_EXERCISES_PER_WORKOUT)

    @model_validator(mode="after")
    def validate_graph_size(self) -> TrainingPlanContent:
        if sum(len(exercise.sets) for exercise in self.exercises) > MAX_SETS_PER_WORKOUT:
            raise ValueError(f"graph exceeds {MAX_SETS_PER_WORKOUT} sets per plan")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        return self


class CreateTrainingPlanRequest(TrainingPlanContent):
    pass


class UpdateTrainingPlanRequest(TrainingPlanContent):
    revision: NonNegativeInteger


class TrainingPlanSetResponse(TrainingPlanSetInput):
    id: str
    set_index: int


class TrainingPlanExerciseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    sets: list[TrainingPlanSetResponse]


class TrainingPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    notes: str | None
    revision: int
    exercises: list[TrainingPlanExerciseResponse]


class TrainingPlanSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    notes: str | None
    revision: int


class TrainingPlanListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TrainingPlanSummaryResponse]
    total: int
    page: StrictInt
    page_size: StrictInt
