"""Unit tests for password hashing, sessions, users service, and throttling."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import cast

import pytest

import app.auth as auth_module
from app.auth import (
    LoginThrottle,
    authenticate,
    create_session,
    delete_session,
    generate_session_token,
    hash_password,
    hash_session_token,
    resolve_session,
    verify_password,
)
from app.db import connect
from app.schemas.auth import MAX_EMAIL_LENGTH, normalize_email
from app.services import users
from app.services.users import DuplicateEmailError

PASSWORD = "s3cret-passw0rd"


def make_user(db: Path, email: str = "a@example.com"):
    return users.create_user(db, email=email, password_hash=hash_password(PASSWORD))


def test_hash_password_is_argon2id_and_verifies() -> None:
    digest = hash_password(PASSWORD)
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, PASSWORD) is True
    assert verify_password(digest, "wrong-password") is False


def test_verify_password_rejects_malformed_hash() -> None:
    assert verify_password("not-a-hash", PASSWORD) is False
    assert verify_password("", PASSWORD) is False


def test_hash_password_is_salted() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_session_token_is_random_and_urlsafe() -> None:
    first, second = generate_session_token(), generate_session_token()
    assert first != second
    assert len(first) >= 43  # 32 bytes -> ~43 urlsafe chars
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)


def test_hash_session_token_is_stable_sha256() -> None:
    token = generate_session_token()
    digest = hash_session_token(token)
    assert digest == hash_session_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert token not in digest


def test_create_session_stores_hash_not_raw_token(migrated_db: Path) -> None:
    user = make_user(migrated_db)
    token = create_session(migrated_db, user.id, ttl_seconds=3600)
    with connect(migrated_db) as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hash_session_token(token)
    assert token not in rows[0]["token_hash"]


def test_resolve_session_returns_owner(migrated_db: Path) -> None:
    user = make_user(migrated_db)
    token = create_session(migrated_db, user.id, ttl_seconds=3600)
    resolved = resolve_session(migrated_db, token)
    assert resolved is not None
    assert resolved.id == user.id
    assert resolved.email == "a@example.com"


def test_resolve_session_unknown_token_is_none(migrated_db: Path) -> None:
    assert resolve_session(migrated_db, generate_session_token()) is None


def test_resolve_session_expired_is_rejected_and_deleted(migrated_db: Path) -> None:
    user = make_user(migrated_db)
    token = create_session(migrated_db, user.id, ttl_seconds=3600)
    with connect(migrated_db) as conn:
        conn.execute(
            "UPDATE sessions SET created_at = '1999-01-01T00:00:00Z', "
            "expires_at = '2000-01-01T00:00:00Z' WHERE user_id = :uid",
            {"uid": user.id},
        )
    assert resolve_session(migrated_db, token) is None
    with connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 0


def test_delete_session_revokes(migrated_db: Path) -> None:
    user = make_user(migrated_db)
    token = create_session(migrated_db, user.id, ttl_seconds=3600)
    delete_session(migrated_db, token)
    assert resolve_session(migrated_db, token) is None


def test_authenticate_verifies_credentials(migrated_db: Path) -> None:
    users.create_user(migrated_db, email="a@example.com", password_hash=hash_password(PASSWORD))
    assert authenticate(migrated_db, email="a@example.com", password=PASSWORD) is not None
    assert authenticate(migrated_db, email="a@example.com", password="nope") is None
    assert authenticate(migrated_db, email="ghost@example.com", password=PASSWORD) is None


def test_authenticate_unknown_email_runs_dummy_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(auth_module, "get_user_by_email", lambda database_path, email: None)
    monkeypatch.setattr(auth_module, "_timing_equalizer_hash", lambda: "dummy-hash")
    monkeypatch.setattr(
        auth_module,
        "verify_password",
        lambda password_hash, password: calls.append((password_hash, password)) or False,
    )

    assert authenticate("unused.db", email="ghost@example.com", password=PASSWORD) is None
    assert calls == [("dummy-hash", PASSWORD)]


@pytest.mark.parametrize("email", ["a", f"a@{'b' * MAX_EMAIL_LENGTH}.com"])
def test_normalize_email_rejects_values_outside_length_bounds(email: str) -> None:
    with pytest.raises(ValueError, match="email must be between"):
        normalize_email(email)


def test_create_user_rejects_duplicate_email(migrated_db: Path) -> None:
    users.create_user(migrated_db, email="a@example.com", password_hash=hash_password(PASSWORD))
    with pytest.raises(DuplicateEmailError):
        users.create_user(migrated_db, email="a@example.com", password_hash=hash_password(PASSWORD))


def test_create_user_does_not_misclassify_other_integrity_errors(migrated_db: Path) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="users.password_hash"):
        users.create_user(
            migrated_db,
            email="a@example.com",
            password_hash=cast(str, None),
        )


def test_get_user_by_id_returns_only_the_requested_user(migrated_db: Path) -> None:
    first = make_user(migrated_db)
    make_user(migrated_db, email="other@example.com")

    found = users.get_user_by_id(migrated_db, first.id)
    assert found is not None
    assert found.email == first.email
    assert users.get_user_by_id(migrated_db, "no-such-id") is None


def test_update_profile_whitelists_columns(migrated_db: Path) -> None:
    user = make_user(migrated_db)
    with pytest.raises(ValueError, match="unknown profile fields"):
        users.update_profile(migrated_db, user.id, {"email": "hacked@example.com"})
    with pytest.raises(ValueError, match="at least one field"):
        users.update_profile(migrated_db, user.id, {})
    updated = users.update_profile(migrated_db, user.id, {"utc_offset_minutes": 120})
    assert updated is not None
    assert updated.utc_offset_minutes == 120
    # email was never changed
    assert updated.email == "a@example.com"


def test_update_profile_missing_user_is_none(migrated_db: Path) -> None:
    assert users.update_profile(migrated_db, "no-such-id", {"display_name": "x"}) is None


def test_throttle_allows_then_blocks_within_window() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_attempts=3, window_seconds=300.0, clock=lambda: now[0])
    key = "ip:1.2.3.4"
    assert throttle.check(key) is None
    for _ in range(3):
        throttle.register_failure(key)
    retry_after = throttle.check(key)
    assert retry_after is not None
    assert 0 < retry_after <= 300.0


def test_throttle_window_expiry_uses_clock() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_attempts=2, window_seconds=60.0, clock=lambda: now[0])
    key = "ip:9.9.9.9"
    throttle.register_failure(key)
    throttle.register_failure(key)
    assert throttle.check(key) is not None
    now[0] += 61.0
    assert throttle.check(key) is None


def test_throttle_reset_clears() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_attempts=1, window_seconds=60.0, clock=lambda: now[0])
    key = "ip:5.5.5.5|email:a@b.co"
    throttle.register_failure(key)
    assert throttle.check(key) is not None
    throttle.reset(key)
    assert throttle.check(key) is None


def test_throttle_bounds_key_count() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_attempts=5, window_seconds=60.0, max_keys=2, clock=lambda: now[0])
    for index in range(5):
        throttle.register_failure(f"key-{index}")
    assert len(throttle._windows) <= 2
    # The oldest keys were evicted, so they are no longer throttled.
    assert throttle.check("key-0") is None


def test_throttle_prunes_expired_keys_before_evicting_active_keys() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_attempts=1, window_seconds=60.0, max_keys=2, clock=lambda: now[0])
    throttle.register_failure("expired")
    now[0] += 61.0
    throttle.register_failure("active")
    throttle.register_failure("new")

    assert set(throttle._windows) == {"active", "new"}
    assert throttle.check("active") is not None
