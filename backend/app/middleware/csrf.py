"""Origin-based CSRF protection for mutating API requests (PLAN.md §11).

Every mutating browser request (POST/PUT/PATCH/DELETE) under `/api/v1`,
including login/register/logout, must carry the exact allowed `Origin` and a
JSON `Content-Type`; mismatches are rejected before routing. GET requests stay
side-effect-free and are exempt. SameSite=Strict cookies are an additional
defense, not the whole policy. Cross-origin credentialed access is never
enabled.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import ApiError, ForbiddenError, UnsupportedMediaTypeError, problem_response
from app.middleware.request_id import request_id_from_scope

API_PREFIX = "/api/v1"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
JSON_MEDIA_TYPE = "application/json"


class CsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        if method not in MUTATING_METHODS or not path.startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        allowed_origin = str(scope["app"].state.settings.app_origin)
        error: ApiError | None = None
        if headers.get("origin") != allowed_origin:
            # Absent or mismatched Origin is rejected in the browser MVP.
            error = ForbiddenError("Request Origin is not allowed", code="origin_not_allowed")
        else:
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != JSON_MEDIA_TYPE:
                error = UnsupportedMediaTypeError("Mutating API requests must send JSON")
        if error is not None:
            response = problem_response(
                error.status_code,
                title=error.default_title,
                detail=error.detail,
                code=error.code,
                request_id=request_id_from_scope(scope),
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
