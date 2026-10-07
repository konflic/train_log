"""Focused unit tests for Stage 3 request middleware."""

from __future__ import annotations

import asyncio

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.errors import BodyTooLargeError
from app.middleware.body_limit import BodySizeLimitMiddleware


def run_body_limit(chunks: list[bytes], *, max_bytes: int) -> tuple[list[bytes], list[Message]]:
    received: list[bytes] = []
    sent: list[Message] = []
    messages = iter(
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    )

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            received.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/register",
        "raw_path": b"/api/v1/auth/register",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    asyncio.run(BodySizeLimitMiddleware(app, max_bytes=max_bytes)(scope, receive, send))
    return received, sent


def test_streamed_body_at_limit_reaches_application() -> None:
    received, sent = run_body_limit([b"12", b"34"], max_bytes=4)
    assert received == [b"12", b"34"]
    assert sent == []


def test_streamed_body_over_limit_is_rejected_while_reading() -> None:
    with pytest.raises(BodyTooLargeError, match="must not exceed 3 bytes"):
        run_body_limit([b"12", b"34"], max_bytes=3)
