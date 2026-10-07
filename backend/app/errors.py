"""RFC 9457-style `application/problem+json` API error conventions (PLAN.md §6).

Every API failure is reported as a problem document with a stable machine
`code`, a human `title`/`detail`, the HTTP `status`, and the `request_id`
extension member when one was assigned. Error bodies never contain
credentials, session tokens, password hashes, or raw request input.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ApiError(Exception):
    """Base class for errors that map to a problem+json response.

    Subclasses fix the status/title/code; instances carry only a safe detail
    message and optional extra headers or problem extension members.
    """

    status_code: int = 500
    default_title: str = "Internal Server Error"
    default_code: str = "error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: Mapping[str, str] | None = None,
        members: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail if detail is not None else self.default_title)
        self.detail = detail if detail is not None else self.default_title
        self.code = code if code is not None else self.default_code
        self.headers: Mapping[str, str] = headers or {}
        self.members: Mapping[str, Any] = members or {}


class BadRequestError(ApiError):
    status_code = 400
    default_title = "Bad Request"
    default_code = "bad_request"


class UnauthorizedError(ApiError):
    status_code = 401
    default_title = "Unauthorized"
    default_code = "unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    default_title = "Forbidden"
    default_code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    default_title = "Not Found"
    default_code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    default_title = "Conflict"
    default_code = "conflict"


class BodyTooLargeError(ApiError):
    status_code = 413
    default_title = "Payload Too Large"
    default_code = "body_too_large"


class UnsupportedMediaTypeError(ApiError):
    status_code = 415
    default_title = "Unsupported Media Type"
    default_code = "json_required"


class ThrottledError(ApiError):
    status_code = 429
    default_title = "Too Many Requests"
    default_code = "throttled"


class ServiceBusyError(ApiError):
    """Retryable: the database writer held the lock past the busy timeout."""

    status_code = 503
    default_title = "Service Unavailable"
    default_code = "retryable"


def problem_response(
    status_code: int,
    *,
    title: str,
    detail: str,
    code: str,
    request_id: str | None = None,
    headers: Mapping[str, str] | None = None,
    members: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Build one problem+json response; extension members never echo input."""
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    if request_id is not None:
        body["request_id"] = request_id
    if members:
        body.update(members)
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )
