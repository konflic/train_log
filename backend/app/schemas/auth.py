"""Auth request/response schemas (PLAN.md §6, §11).

Public responses are explicit: they never include `password_hash`, session
tokens, or other server-controlled fields, and requests reject unknown or
server-controlled inputs (`extra="forbid"`). Emails are normalized (trimmed,
lowercased) before storage; strict typing rejects booleans and numbers in
string/integer fields per the Stage 2 integer contract.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import BodyweightKg

MAX_EMAIL_LENGTH = 254
MIN_EMAIL_LENGTH = 3
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MAX_DISPLAY_NAME_LENGTH = 100
UTC_OFFSET_MIN_MINUTES = -720
UTC_OFFSET_MAX_MINUTES = 840

Email = Annotated[str, Field(strict=True, max_length=MAX_EMAIL_LENGTH)]
Password = Annotated[
    str, Field(strict=True, min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
]
DisplayName = Annotated[str, Field(strict=True, max_length=MAX_DISPLAY_NAME_LENGTH)]
UtcOffsetMinutes = Annotated[
    int, Field(strict=True, ge=UTC_OFFSET_MIN_MINUTES, le=UTC_OFFSET_MAX_MINUTES)
]
Age = Annotated[int, Field(strict=True, ge=1, le=120)]
Sex = Literal["male", "female"]


def normalize_email(value: str) -> str:
    """Trim and lowercase an email address, rejecting malformed input.

    Conservative format check (one `@`, non-empty parts, a dotted domain, no
    whitespace); full RFC parsing is deliberately out of scope.
    """
    normalized = value.strip().lower()
    if not MIN_EMAIL_LENGTH <= len(normalized) <= MAX_EMAIL_LENGTH:
        raise ValueError(
            f"email must be between {MIN_EMAIL_LENGTH} and {MAX_EMAIL_LENGTH} characters"
        )
    if any(character.isspace() for character in normalized):
        raise ValueError("email must not contain whitespace")
    local, at, domain = normalized.partition("@")
    if not at or not local or not domain:
        raise ValueError("email must contain a local part and a domain around one '@'")
    if "@" in domain or ".." in normalized:
        raise ValueError("email is malformed")
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("email domain must contain a dot")
    return normalized


def normalize_display_name(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("display_name must not be blank")
    return trimmed


class RegisterRequest(BaseModel):
    """Public registration input; role/status are never accepted (PLAN.md §4)."""

    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password
    display_name: DisplayName | None = None
    bodyweight_default_kg: BodyweightKg | None = None
    sex: Sex | None = None
    age: Age | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_display_name(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class UpdateProfileRequest(BaseModel):
    """PATCH /auth/me input.

    Absent fields are untouched; explicit `null` clears `display_name`,
    `bodyweight_default_kg`, `sex`, and `age`. `utc_offset_minutes` is NOT
    NULL in storage, so an explicit null is rejected. At least one field must
    be provided.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    bodyweight_default_kg: BodyweightKg | None = None
    sex: Sex | None = None
    age: Age | None = None
    utc_offset_minutes: UtcOffsetMinutes | None = None

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_display_name(value)

    @model_validator(mode="after")
    def validate_patch_fields(self) -> UpdateProfileRequest:
        provided = self.model_fields_set
        if not provided:
            raise ValueError("at least one profile field must be provided")
        if "utc_offset_minutes" in provided and self.utc_offset_minutes is None:
            raise ValueError("utc_offset_minutes cannot be null")
        return self


class UserResponse(BaseModel):
    """The only public user shape: no password hash, token, or secrets."""

    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str | None
    bodyweight_default_kg: int | None
    sex: Sex | None
    age: int | None
    utc_offset_minutes: int
