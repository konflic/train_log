"""Exercise catalog request/response schemas (PLAN.md §4, §6).

Custom entries carry content fields only: `id`, `is_default`, and `created_by`
are server-controlled and rejected as unknown input. Cross-field load rules
mirror the database CHECKs (pure-bodyweight entries require a percentage; only
`split_weight` may cover two sides), so invalid entries fail with 422 at the
API boundary. `PATCH` is partial input; the service merges it with the latest
stored entry inside the write transaction and revalidates the result through
`CreateExerciseRequest`, so a partial update cannot produce an entry a full
create would reject.

Names are Unicode text: bounds count codepoints, trimming is Unicode-aware,
and stored case is preserved. Uniqueness is exact-match within scope (the
partial unique indexes are authoritative), so case variants may coexist.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.numbers import MAX_SAFE_INTEGER
from app.schemas.common import LoadType, Percentage, SideCount

MAX_NAME_LENGTH = 100
# A search longer than the maximum stored name can never match.
MAX_SEARCH_LENGTH = MAX_NAME_LENGTH
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
# Keep the largest possible offset within the shared JSON/SQLite integer range.
MAX_PAGE_NUMBER = MAX_SAFE_INTEGER // MAX_PAGE_SIZE

MuscleGroup = Literal["chest", "back", "legs", "shoulders", "arms", "core", "full_body", "other"]
Equipment = Literal[
    "barbell", "dumbbell", "kettlebell", "machine", "cable", "bodyweight", "band", "other"
]

CatalogName = Annotated[str, Field(strict=True, min_length=1, max_length=MAX_NAME_LENGTH)]


def normalize_name(value: str) -> str:
    """Trim surrounding Unicode whitespace; the name must remain non-blank."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("name must not be blank")
    return trimmed


class CreateExerciseRequest(BaseModel):
    """POST /exercises input; also the validated full-content shape for PATCH."""

    model_config = ConfigDict(extra="forbid")

    name: CatalogName
    muscle_group: MuscleGroup
    equipment: Equipment
    load_type: LoadType
    bodyweight_percent: Percentage | None = None
    side_count: SideCount = 1

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_name(value)

    @model_validator(mode="after")
    def validate_load_rules(self) -> CreateExerciseRequest:
        if self.load_type == "bodyweight" and self.bodyweight_percent is None:
            raise ValueError("bodyweight exercises require bodyweight_percent")
        if self.load_type != "split_weight" and self.side_count != 1:
            raise ValueError("side_count must be 1 unless load_type is split_weight")
        return self


class UpdateExerciseRequest(BaseModel):
    """PATCH /exercises/{id} input.

    Absent fields stay untouched; explicit `null` clears `bodyweight_percent`
    only (every other content column is NOT NULL in storage). At least one
    field must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    name: CatalogName | None = None
    muscle_group: MuscleGroup | None = None
    equipment: Equipment | None = None
    load_type: LoadType | None = None
    bodyweight_percent: Percentage | None = None
    side_count: SideCount | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_name(value)

    @model_validator(mode="after")
    def validate_patch_fields(self) -> UpdateExerciseRequest:
        provided = self.model_fields_set
        if not provided:
            raise ValueError("at least one exercise field must be provided")
        not_nullable = sorted(
            name
            for name in ("name", "muscle_group", "equipment", "load_type", "side_count")
            if name in provided and getattr(self, name) is None
        )
        if not_nullable:
            raise ValueError(f"fields cannot be null: {', '.join(not_nullable)}")
        return self


class ExerciseResponse(BaseModel):
    """One public catalog entry; `created_by` is internal and never exposed."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    muscle_group: MuscleGroup
    equipment: Equipment
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    is_default: bool


class ExerciseListResponse(BaseModel):
    """One bounded page of the visible catalog (PLAN.md §6: total + paging)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ExerciseResponse]
    total: int
    page: int
    page_size: int
