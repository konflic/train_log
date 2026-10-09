"""Auth endpoints: register, login, logout, and profile (PLAN.md §6, §11).

Conventions established here and reused by later resource stages: RFC
9457-style problem+json errors, explicit public response schemas, rejection
of unknown/server-controlled input fields, and empty 204 responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.auth import (
    SESSION_COOKIE_NAME,
    CurrentUser,
    LoginThrottle,
    authenticate,
    clear_session_cookie,
    create_session,
    delete_session,
    enforce_login_throttle,
    hash_password,
    set_session_cookie,
    throttle_keys_for,
)
from app.config import Settings
from app.errors import ConflictError, UnauthorizedError
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.services import users
from app.services.users import DuplicateEmailError, UserRecord

router = APIRouter(prefix="/auth", tags=["auth"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        bodyweight_default_kg=user.bodyweight_default_kg,
        sex=user.sex,
        age=user.age,
        utc_offset_minutes=user.utc_offset_minutes,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, request: Request) -> UserResponse:
    """Create an account. Registration never logs the user in."""
    try:
        user = users.create_user(
            _settings(request).database_path,
            email=payload.email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name,
            bodyweight_default_kg=payload.bodyweight_default_kg,
            sex=payload.sex,
            age=payload.age,
        )
    except DuplicateEmailError:
        raise ConflictError(
            "An account with this email already exists", code="email_taken"
        ) from None
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> UserResponse:
    """Verify credentials and set the session cookie."""
    settings = _settings(request)
    throttle: LoginThrottle = request.app.state.login_throttle
    throttle_keys = throttle_keys_for(request, payload.email)
    enforce_login_throttle(request, throttle_keys)

    user = authenticate(settings.database_path, email=payload.email, password=payload.password)
    if user is None:
        for key in throttle_keys:
            throttle.register_failure(key)
        # Generic error: identical for unknown email and wrong password.
        raise UnauthorizedError("Invalid email or password")
    for key in throttle_keys:
        throttle.reset(key)

    token = create_session(
        settings.database_path, user.id, ttl_seconds=settings.session_ttl_seconds
    )
    set_session_cookie(response, token, settings)
    return _user_response(user)


@router.post("/logout", status_code=204)
def logout(request: Request, user: CurrentUser) -> Response:
    """Delete the current session row and clear the cookie (empty 204)."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        delete_session(_settings(request).database_path, token)
    response = Response(status_code=204)
    clear_session_cookie(response, _settings(request))
    return response


@router.get("/me", response_model=UserResponse)
def read_profile(user: CurrentUser) -> UserResponse:
    return _user_response(user)


@router.patch("/me", response_model=UserResponse)
def update_profile(
    payload: UpdateProfileRequest, request: Request, user: CurrentUser
) -> UserResponse:
    """Update writable profile fields of the authenticated account only."""
    updates = payload.model_dump(exclude_unset=True)
    updated = users.update_profile(_settings(request).database_path, user.id, updates)
    if updated is None:
        # require_user resolved this session moments ago; the row vanished.
        raise UnauthorizedError("Authentication required")
    return _user_response(updated)
