"""Request-ID assignment and access logging (PLAN.md §11).

Every HTTP request gets a random hex request ID: it is stored in the shared
scope state (so exception handlers can embed it in problem documents),
returned as the `X-Request-ID` response header, and logged with the method,
path, and status only. Bodies, cookies, tokens, and credentials are never
logged.
"""

from __future__ import annotations

import logging
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("basefit.access")


def request_id_from_scope(scope: Scope) -> str | None:
    """Read the request ID assigned by this middleware, if any."""
    state = scope.get("state")
    if isinstance(state, dict):
        request_id = state.get("request_id")
        if isinstance(request_id, str):
            return request_id
    return None


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 0

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # status_code 0 means the request failed before any response
            # started; the traceback itself is logged by the server layer.
            level = logging.WARNING if status_code >= 500 else logging.INFO
            logger.log(
                level,
                "%s %s -> %s request_id=%s",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code or "-",
                request_id,
            )
