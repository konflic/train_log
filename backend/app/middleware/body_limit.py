"""Request body size limits (PLAN.md §11: bounded request/body sizes).

Declared sizes are rejected from the `Content-Length` header before the app
runs; streamed bodies are counted as they arrive and abort with the same
413 problem document. The limit leaves room for the Stage 6 full-graph saves
while keeping every request bounded.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import BodyTooLargeError, problem_response
from app.middleware.request_id import request_id_from_scope

MAX_BODY_BYTES = 256 * 1024


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _too_large_response(self, scope: Scope) -> JSONResponse:
        return problem_response(
            BodyTooLargeError.status_code,
            title=BodyTooLargeError.default_title,
            detail=f"Request body must not exceed {self.max_bytes} bytes",
            code=BodyTooLargeError.default_code,
            request_id=request_id_from_scope(scope),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            response = self._too_large_response(scope)
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Raised where the app reads the body; the registered
                    # ApiError handler turns it into the 413 problem document.
                    raise BodyTooLargeError(f"Request body must not exceed {self.max_bytes} bytes")
            return message

        await self.app(scope, limited_receive, send)
