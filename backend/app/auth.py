"""Password verification, opaque database sessions, and login throttling.

PLAN.md §11: Argon2id via the maintained `argon2-cffi` library (never a local
hash implementation), `secrets.token_urlsafe(32)` session tokens of which only
the SHA-256 hash is stored, per-request session lookup with expired-session
rejection, and bounded in-memory login throttling for the single-process
deployment. Raw tokens are never logged or persisted.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request, Response

from app.config import Settings
from app.db import connect, write_transaction
from app.errors import ThrottledError, UnauthorizedError
from app.services.users import USER_COLUMNS, UserRecord, get_user_by_email, row_to_user
from app.timestamps import is_expired, now_timestamp, timestamp_plus_seconds

SESSION_COOKIE_NAME = "basefit_session"
SESSION_COOKIE_PATH = "/api/v1"

# Throttle bounds (PLAN.md §11): small private deployment, single process.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300.0
THROTTLE_MAX_KEYS = 10_000

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with Argon2id using the library's current defaults."""
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password against an Argon2id hash; malformed hashes fail."""
    try:
        return bool(_password_hasher.verify(password_hash, password))
    except (VerificationError, InvalidHashError, ValueError):
        return False


@lru_cache(maxsize=1)
def _timing_equalizer_hash() -> str:
    """A dummy hash so unknown-email logins cost the same as known ones."""
    return hash_password("timing-equalizer-not-a-real-password")


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(database_path: str | Path, user_id: str, *, ttl_seconds: int) -> str:
    """Store a new session row and return the raw token (never persisted)."""
    token = generate_session_token()
    created_at = now_timestamp()
    expires_at = timestamp_plus_seconds(created_at, ttl_seconds)
    with connect(database_path) as conn, write_transaction(conn):
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (:token_hash, :user_id, :created_at, :expires_at)",
            {
                "token_hash": hash_session_token(token),
                "user_id": user_id,
                "created_at": created_at,
                "expires_at": expires_at,
            },
        )
    return token


def resolve_session(database_path: str | Path, token: str) -> UserRecord | None:
    """Look up the session's user; expired sessions are deleted and rejected."""
    token_hash = hash_session_token(token)
    columns = ", ".join(f"u.{name}" for name in USER_COLUMNS)
    with connect(database_path) as conn:
        row = conn.execute(
            f"SELECT {columns}, s.expires_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = :token_hash",
            {"token_hash": token_hash},
        ).fetchone()
        if row is None:
            return None
        if is_expired(str(row["expires_at"])):
            with write_transaction(conn):
                conn.execute(
                    "DELETE FROM sessions WHERE token_hash = :token_hash",
                    {"token_hash": token_hash},
                )
            return None
    return row_to_user(row)


def delete_session(database_path: str | Path, token: str) -> None:
    """Revoke one session by raw token (logout deletes the row, PLAN.md §11)."""
    with connect(database_path) as conn, write_transaction(conn):
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = :token_hash",
            {"token_hash": hash_session_token(token)},
        )


def authenticate(database_path: str | Path, *, email: str, password: str) -> UserRecord | None:
    """Verify normalized-email credentials; `None` is the only failure signal.

    An unknown email still runs one Argon2id verification so response time
    does not reveal whether the account exists; error details stay generic.
    """
    user = get_user_by_email(database_path, email)
    if user is None:
        verify_password(_timing_equalizer_hash(), password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the session cookie: HttpOnly, SameSite=Strict, Path=/api/v1.

    `Secure` follows `COOKIE_SECURE`; non-Secure cookies are only allowed for
    local HTTP development and `create_app` refuses that combination elsewhere.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        path=SESSION_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def require_user(request: Request) -> UserRecord:
    """FastAPI dependency: the authenticated user or a generic 401.

    The session is resolved from the database on every request; expired or
    unknown tokens are rejected with the same generic error.
    """
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise UnauthorizedError("Authentication required")
    user = resolve_session(settings.database_path, token)
    if user is None:
        raise UnauthorizedError("Authentication required")
    return user


# Reusable dependency alias so resource stages annotate `user: CurrentUser`.
CurrentUser = Annotated[UserRecord, Depends(require_user)]


@dataclass
class _ThrottleWindow:
    started_at: float
    failures: int = 0


@dataclass
class LoginThrottle:
    """Bounded fixed-window failed-login counter for one process.

    Keyed by client IP and by (IP, email); successful logins reset both. The
    key set is bounded: expired windows are pruned and the oldest entries are
    evicted when the cap is reached, so memory cannot grow without limit.
    The `clock` is injectable for deterministic tests.
    """

    max_attempts: int = LOGIN_MAX_ATTEMPTS
    window_seconds: float = LOGIN_WINDOW_SECONDS
    max_keys: int = THROTTLE_MAX_KEYS
    clock: Callable[[], float] = time.monotonic
    _windows: dict[str, _ThrottleWindow] = field(default_factory=dict, init=False)

    def _prune_expired(self, now: float) -> None:
        expired = [
            key
            for key, window in self._windows.items()
            if now - window.started_at >= self.window_seconds
        ]
        for key in expired:
            del self._windows[key]

    def check(self, key: str) -> float | None:
        """Return the retry-after seconds when throttled, else `None`."""
        window = self._windows.get(key)
        if window is None:
            return None
        now = self.clock()
        elapsed = now - window.started_at
        if elapsed >= self.window_seconds:
            del self._windows[key]
            return None
        if window.failures >= self.max_attempts:
            return self.window_seconds - elapsed
        return None

    def register_failure(self, key: str) -> None:
        now = self.clock()
        window = self._windows.get(key)
        if window is None or now - window.started_at >= self.window_seconds:
            if len(self._windows) >= self.max_keys:
                self._prune_expired(now)
            while len(self._windows) >= self.max_keys:
                del self._windows[next(iter(self._windows))]
            self._windows[key] = _ThrottleWindow(started_at=now, failures=1)
        else:
            window.failures += 1

    def reset(self, key: str) -> None:
        self._windows.pop(key, None)


def throttle_keys_for(request: Request, email: str) -> list[str]:
    client_ip = request.client.host if request.client is not None else "unknown"
    return [f"ip:{client_ip}", f"ip:{client_ip}|email:{email}"]


def enforce_login_throttle(request: Request, keys: list[str]) -> None:
    """Reject the attempt with 429 + Retry-After when any key is throttled."""
    throttle: LoginThrottle = request.app.state.login_throttle
    retry_after = 0.0
    for key in keys:
        remaining = throttle.check(key)
        if remaining is not None:
            retry_after = max(retry_after, remaining)
    if retry_after > 0:
        raise ThrottledError(
            "Too many failed login attempts; try again later",
            headers={"Retry-After": str(math.ceil(retry_after))},
        )
