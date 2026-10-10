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

The public catalog representation separates three concepts: the compact
summary (`ExerciseResponse`, the bounded list shape), the detail
(`ExerciseDetailResponse`: summary plus the optional description and, for
seeded defaults only, the validated guidance bundle), and the owner-specific
statistics (see `app.schemas.stats`). Guidance content comes from the
version-controlled registry (`app.guidance`) and is re-validated against its
response bounds on every serialization.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import LoadType, Percentage, SideCount

MAX_NAME_LENGTH = 100
# A search longer than the maximum stored name can never match.
MAX_SEARCH_LENGTH = MAX_NAME_LENGTH
MAX_DESCRIPTION_LENGTH = 1000

# Guidance registry bounds; the consistency test proves every registry entry
# obeys them, and each response is re-validated here as well.
MIN_GUIDANCE_STEPS = 1
MAX_GUIDANCE_STEPS = 8
MAX_GUIDANCE_STEP_LENGTH = 300
MIN_GUIDANCE_TIPS = 1
MAX_GUIDANCE_TIPS = 6
MAX_GUIDANCE_TIP_LENGTH = 200
MIN_GUIDANCE_SOURCES = 1
MAX_GUIDANCE_SOURCES = 4
MAX_GUIDANCE_SOURCE_TITLE_LENGTH = 200
MAX_GUIDANCE_SOURCE_URL_LENGTH = 500
ANIMATION_KEY_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

MuscleGroup = Literal["chest", "back", "legs", "shoulders", "arms", "abs", "full_body", "other"]

CatalogName = Annotated[str, Field(strict=True, min_length=1, max_length=MAX_NAME_LENGTH)]
CatalogDescription = Annotated[str, Field(strict=True, max_length=MAX_DESCRIPTION_LENGTH)]


def normalize_name(value: str) -> str:
    """Trim surrounding Unicode whitespace; the name must remain non-blank."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("name must not be blank")
    return trimmed


def normalize_description(value: str | None) -> str | None:
    """Trim surrounding Unicode whitespace; blank input becomes `None`."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class CreateExerciseRequest(BaseModel):
    """POST /exercises input; also the validated full-content shape for PATCH."""

    model_config = ConfigDict(extra="forbid")

    name: CatalogName
    muscle_group: MuscleGroup
    load_type: LoadType
    bodyweight_percent: Percentage | None = None
    side_count: SideCount = 1
    description: CatalogDescription | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_name(value)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        return normalize_description(value)

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
    and `description` (every other content column is NOT NULL in storage). At
    least one field must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    name: CatalogName | None = None
    muscle_group: MuscleGroup | None = None
    load_type: LoadType | None = None
    bodyweight_percent: Percentage | None = None
    side_count: SideCount | None = None
    description: CatalogDescription | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_name(value)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        return normalize_description(value)

    @model_validator(mode="after")
    def validate_patch_fields(self) -> UpdateExerciseRequest:
        provided = self.model_fields_set
        if not provided:
            raise ValueError("at least one exercise field must be provided")
        not_nullable = sorted(
            name
            for name in ("name", "muscle_group", "load_type", "side_count")
            if name in provided and getattr(self, name) is None
        )
        if not_nullable:
            raise ValueError(f"fields cannot be null: {', '.join(not_nullable)}")
        return self


class ExerciseResponse(BaseModel):
    """One public catalog summary entry; `created_by` is internal.

    The bounded list (`GET /exercises`) carries summaries only; descriptions
    and guidance arrive through the detail representation.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    muscle_group: MuscleGroup
    load_type: LoadType
    bodyweight_percent: int | None
    side_count: int
    is_default: bool


class GuidanceSourceResponse(BaseModel):
    """One cited source of the guidance bundle (title plus full HTTPS URL)."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=MAX_GUIDANCE_SOURCE_TITLE_LENGTH)]
    url: Annotated[str, Field(min_length=1, max_length=MAX_GUIDANCE_SOURCE_URL_LENGTH)]

    @field_validator("url")
    @classmethod
    def _require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("source URLs must use HTTPS")
        return value


class ExerciseGuidanceResponse(BaseModel):
    """The validated default-exercise guidance bundle.

    Only seeded defaults have guidance; custom entries always serialize
    `guidance = null` and never receive fabricated instructions or sources.
    """

    model_config = ConfigDict(extra="forbid")

    technique_steps: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_GUIDANCE_STEP_LENGTH)]],
        Field(min_length=MIN_GUIDANCE_STEPS, max_length=MAX_GUIDANCE_STEPS),
    ]
    form_tips: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_GUIDANCE_TIP_LENGTH)]],
        Field(min_length=MIN_GUIDANCE_TIPS, max_length=MAX_GUIDANCE_TIPS),
    ]
    animation_key: str
    sources: Annotated[
        list[GuidanceSourceResponse],
        Field(min_length=MIN_GUIDANCE_SOURCES, max_length=MAX_GUIDANCE_SOURCES),
    ]

    @field_validator("animation_key")
    @classmethod
    def _validate_animation_key(cls, value: str) -> str:
        if not ANIMATION_KEY_PATTERN.match(value):
            raise ValueError("animation_key must be a lowercase hyphenated slug")
        return value


class ExerciseDetailResponse(ExerciseResponse):
    """GET /exercises/{id} and the result of custom POST/PATCH.

    Summary fields plus the optional description (custom-owner editable,
    default-seeded and immutable) and, for defaults with reviewed content,
    the guidance bundle.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None
    guidance: ExerciseGuidanceResponse | None = None


class ExerciseListResponse(BaseModel):
    """One bounded page of the visible catalog (PLAN.md §6: total + paging)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ExerciseResponse]
    total: int
    page: int
    page_size: int
