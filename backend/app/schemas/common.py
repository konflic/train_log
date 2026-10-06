"""Strict primitive types and shared validation for integer-only inputs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.numbers import MAX_SAFE_INTEGER

StrictInteger = Annotated[int, Field(strict=True, ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
PositiveInteger = Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE_INTEGER)]
Percentage = Annotated[int, Field(strict=True, ge=1, le=100)]
Rpe = Annotated[int, Field(strict=True, ge=1, le=10)]
Index = NonNegativeInteger
Reps = NonNegativeInteger
WeightKg = NonNegativeInteger
BodyweightKg = PositiveInteger
SideCount = Annotated[int, Field(strict=True, ge=1, le=2)]

LoadType = Literal["single_weight", "split_weight", "bodyweight"]


class SetInput(BaseModel):
    """Validated set values after the exercise's recorded load type is known.

    Write schemas use this internally after resolving their immutable exercise
    snapshot, rather than accepting ``load_type`` from an API client.
    """

    model_config = ConfigDict(extra="forbid")

    load_type: LoadType
    reps: Reps | None = None
    weight_kg: WeightKg | None = None
    rpe: Rpe | None = None
    bw_percent_override: Percentage | None = None
    done: StrictBool

    @model_validator(mode="after")
    def validate_completion(self) -> SetInput:
        if self.load_type == "bodyweight" and self.weight_kg is not None:
            raise ValueError("bodyweight sets require weight_kg to be null")
        if self.done and (self.reps is None or self.reps <= 0):
            raise ValueError("completed sets require positive reps")
        if self.done and self.load_type != "bodyweight" and self.weight_kg is None:
            raise ValueError("completed weighted sets require weight_kg")
        return self
