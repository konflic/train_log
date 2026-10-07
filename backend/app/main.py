"""FastAPI application entry point and shared API conventions.

`create_app(settings)` composes the middleware stack (request ID outermost,
then CSRF Origin checks, then body size limits), the versioned routers, and
the problem+json exception handlers reused by every later resource stage.
The health endpoint remains for smoke tests and E2E readiness checks.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth import router as auth_router
from app.auth import LoginThrottle
from app.config import Settings, load_settings
from app.db import DatabaseBusyError, validate_sqlite_runtime
from app.errors import ApiError, ServiceBusyError, problem_response
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.csrf import CsrfMiddleware
from app.middleware.request_id import RequestIdMiddleware, request_id_from_scope

logger = logging.getLogger("basefit.app")

# Non-Secure cookies are only permitted for the local HTTP environments used in
# development and automated E2E; every remote/production-like environment must
# send Secure cookies (PLAN.md §11).
INSECURE_COOKIE_ALLOWED_ENVS = frozenset({"development", "test"})


class HealthResponse(BaseModel):
    """Public health payload."""

    status: str


def create_api_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["meta"])

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    router.include_router(auth_router)
    return router


def _validation_members(exc: RequestValidationError) -> dict[str, object]:
    """Field locations and messages only; never the rejected input values."""
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]
    return {"errors": errors}


def register_error_handlers(app: FastAPI) -> None:
    """Map every failure mode onto one problem+json shape (RFC 9457-style)."""

    @app.exception_handler(ApiError)
    def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(
            exc.status_code,
            title=exc.default_title,
            detail=exc.detail,
            code=exc.code,
            request_id=request_id_from_scope(request.scope),
            headers=exc.headers,
            members=exc.members,
        )

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422,
            title="Validation Error",
            detail="Request validation failed",
            code="validation_error",
            request_id=request_id_from_scope(request.scope),
            members=_validation_members(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return problem_response(
            exc.status_code,
            title=detail,
            detail=detail,
            code="http_error",
            request_id=request_id_from_scope(request.scope),
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(DatabaseBusyError)
    def handle_database_busy(request: Request, exc: DatabaseBusyError) -> JSONResponse:
        # Retryable; the client's local draft must be preserved (PLAN.md §2).
        busy = ServiceBusyError("The database is busy; retry shortly")
        logger.warning(
            "database busy on %s request_id=%s",
            request.scope.get("path", "-"),
            request_id_from_scope(request.scope),
        )
        return problem_response(
            busy.status_code,
            title=busy.default_title,
            detail=busy.detail,
            code=busy.code,
            request_id=request_id_from_scope(request.scope),
            headers={"Retry-After": "1"},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    # Fail startup when the linked SQLite cannot support STRICT tables
    # (PLAN.md §3); never assume the runtime version.
    validate_sqlite_runtime()
    resolved = load_settings() if settings is None else settings
    if not resolved.cookie_secure and resolved.app_env not in INSECURE_COOKIE_ALLOWED_ENVS:
        # Non-Secure cookies are only allowed for local HTTP dev/test.
        raise ValueError(
            "COOKIE_SECURE must be true unless APP_ENV is one of "
            f"{sorted(INSECURE_COOKIE_ALLOWED_ENVS)} (local HTTP)"
        )

    app = FastAPI(title="BaseFit API", version="0.1.0")
    app.state.settings = resolved
    app.state.login_throttle = LoginThrottle()

    # add_middleware prepends: the last added runs outermost.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(create_api_v1_router())
    register_error_handlers(app)
    return app


app = create_app()
