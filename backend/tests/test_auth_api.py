"""Stage 3 auth API tests (Gate G3).

Covers register/login/logout happy paths, cookie flags, expired-session
rejection, logout revocation, Origin/CSRF rejection on mutating verbs, login
throttling, secret-free output, profile scoping, and the shared problem+json,
request-ID, and size-limit conventions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE_NAME, LoginThrottle, hash_session_token
from app.config import Settings
from app.db import connect
from app.main import create_app

ORIGIN = "http://testserver"
EMAIL = "user@example.com"
PASSWORD = "correct-horse-battery"

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD, **extra: object):
    return client.post(REGISTER_URL, json={"email": email, "password": password, **extra})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post(LOGIN_URL, json={"email": email, "password": password})


def set_cookie_token(response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        attribute, _, value = header.partition(";")
        name, _, token = attribute.partition("=")
        if name.strip() == SESSION_COOKIE_NAME:
            return token.strip()
    return None


def set_cookie_attributes(response) -> set[str]:
    """Lowercased cookie attributes (flags), excluding the name=value pair."""
    header = response.headers["set-cookie"]
    return {part.strip().lower() for part in header.split(";")[1:]}


def problem(response) -> dict:
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == response.status_code
    return body


def register_and_login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    assert register(client, email=email, password=password).status_code == 201
    response = login(client, email=email, password=password)
    assert response.status_code == 200
    token = set_cookie_token(response)
    assert token is not None
    return token


# --- registration -----------------------------------------------------------


def test_register_returns_explicit_public_profile(api_client: TestClient) -> None:
    response = register(api_client)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "email",
        "display_name",
        "bodyweight_default_kg",
        "sex",
        "age",
        "utc_offset_minutes",
    }
    assert body["email"] == EMAIL
    assert body["display_name"] is None
    assert body["bodyweight_default_kg"] is None
    assert body["sex"] is None
    assert body["age"] is None
    assert body["utc_offset_minutes"] == 0
    # Registration does not log the user in.
    assert set_cookie_token(response) is None
    assert PASSWORD not in response.text


def test_register_trims_display_name(api_client: TestClient) -> None:
    response = register(api_client, display_name="  Ada  ")
    assert response.status_code == 201
    assert response.json()["display_name"] == "Ada"


def test_register_stores_metabolism_profile_inputs(api_client: TestClient) -> None:
    response = register(
        api_client,
        bodyweight_default_kg=75,
        sex="female",
        age=31,
    )
    assert response.status_code == 201
    assert response.json() | {"id": "ignored"} == {
        "id": "ignored",
        "email": EMAIL,
        "display_name": None,
        "bodyweight_default_kg": 75,
        "sex": "female",
        "age": 31,
        "utc_offset_minutes": 0,
    }


def test_register_normalizes_email_before_storage(
    api_client: TestClient, migrated_db: Path
) -> None:
    response = register(api_client, email="  MiXeD@Example.COM ")
    assert response.status_code == 201
    assert response.json()["email"] == "mixed@example.com"
    with connect(migrated_db) as conn:
        row = conn.execute("SELECT email FROM users").fetchone()
    assert row["email"] == "mixed@example.com"
    # Login with the normalized form succeeds.
    assert login(api_client, email="mixed@example.com").status_code == 200


def test_register_duplicate_email_conflicts(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201
    response = register(api_client, email="USER@example.com ")
    body = problem(response)
    assert response.status_code == 409
    assert body["code"] == "email_taken"


@pytest.mark.parametrize("field", ["role", "account_status", "password_hash", "id", "created_at"])
def test_register_rejects_unknown_or_server_controlled_fields(
    api_client: TestClient, field: str
) -> None:
    response = register(api_client, **{field: "whatever"})
    body = problem(response)
    assert response.status_code == 422
    assert body["code"] == "validation_error"


@pytest.mark.parametrize(
    "password",
    ["short1!", "x" * 257, 12345678, True, None, 8.5],
)
def test_register_rejects_invalid_passwords(api_client: TestClient, password: object) -> None:
    response = api_client.post(REGISTER_URL, json={"email": EMAIL, "password": password})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "email",
    [
        "no-at-sign",
        "a@b",
        "two@@example.com",
        "sp ace@example.com",
        "@example.com",
        "user@",
        "user@.com",
        "user@example..com",
        "user@example.com.",
        12345,
        None,
    ],
)
def test_register_rejects_malformed_emails(api_client: TestClient, email: object) -> None:
    response = api_client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert response.status_code == 422
    problem(response)


def test_validation_errors_do_not_echo_rejected_input(api_client: TestClient) -> None:
    response = api_client.post(
        REGISTER_URL, json={"email": "not-an-email-XYZZY", "password": PASSWORD}
    )
    assert response.status_code == 422
    assert "XYZZY" not in response.text


# --- login and cookies ------------------------------------------------------


def test_login_sets_scoped_httponly_samesite_cookie(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201
    response = login(api_client)
    assert response.status_code == 200
    attributes = set_cookie_attributes(response)
    assert "httponly" in attributes
    assert "samesite=strict" in attributes
    assert "path=/api/v1" in attributes
    assert "max-age=3600" in attributes
    # Local HTTP development is the only non-Secure cookie environment.
    assert "secure" not in attributes


def test_login_sets_secure_cookie_when_configured(make_app) -> None:
    with TestClient(make_app(cookie_secure=True), headers={"Origin": ORIGIN}) as client:
        assert register(client).status_code == 201
        response = login(client)
        assert "secure" in set_cookie_attributes(response)


def test_login_stores_only_the_token_hash(api_client: TestClient, migrated_db: Path) -> None:
    token = register_and_login(api_client)
    with connect(migrated_db) as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hash_session_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", rows[0]["token_hash"])


def test_login_failures_are_generic_and_identical(api_client: TestClient) -> None:
    assert register(api_client).status_code == 201
    wrong_password = login(api_client, password="wrong-password-entirely")
    unknown_email = login(api_client, email="nobody@example.com")
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    first = problem(wrong_password)
    second = problem(unknown_email)
    first.pop("request_id")
    second.pop("request_id")
    assert first == second
    assert set_cookie_token(wrong_password) is None
    assert set_cookie_token(unknown_email) is None


# --- sessions ---------------------------------------------------------------


def test_me_requires_authentication(api_client: TestClient) -> None:
    response = api_client.get(ME_URL)
    body = problem(response)
    assert response.status_code == 401
    assert body["code"] == "unauthorized"


def test_me_returns_the_session_owner(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.get(ME_URL)
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_expired_session_is_rejected_and_deleted(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    with connect(migrated_db) as conn:
        conn.execute(
            "UPDATE sessions SET created_at = '1999-01-01T00:00:00Z', "
            "expires_at = '2000-01-01T00:00:00Z'"
        )
    assert api_client.get(ME_URL).status_code == 401
    with connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 0


def test_logout_revokes_session_and_clears_cookie(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    response = api_client.post(LOGOUT_URL, json={})
    assert response.status_code == 204
    assert response.content == b""
    cleared = [
        header
        for header in response.headers.get_list("set-cookie")
        if SESSION_COOKIE_NAME in header
    ]
    assert cleared and "Max-Age=0" in cleared[0]
    with connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 0
    # The revoked session no longer authenticates, and logout now fails too.
    assert api_client.get(ME_URL).status_code == 401
    assert api_client.post(LOGOUT_URL, json={}).status_code == 401


# --- CSRF / Origin / content type -------------------------------------------


def test_mutating_requests_reject_missing_origin(make_app) -> None:
    with TestClient(make_app()) as client:
        payload = {"email": EMAIL, "password": PASSWORD}
        assert client.post(REGISTER_URL, json=payload).status_code == 403
        assert client.post(LOGIN_URL, json=payload).status_code == 403
        assert client.post(LOGOUT_URL, json={}).status_code == 403
        assert client.patch(ME_URL, json={"display_name": "x"}).status_code == 403


def test_mutating_requests_reject_wrong_origin(api_client: TestClient) -> None:
    response = api_client.post(
        REGISTER_URL,
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "http://evil.example"},
    )
    body = problem(response)
    assert response.status_code == 403
    assert body["code"] == "origin_not_allowed"


def test_mutating_requests_require_json_content_type(api_client: TestClient) -> None:
    response = api_client.post(
        REGISTER_URL,
        content=f'{{"email": "{EMAIL}", "password": "{PASSWORD}"}}',
        headers={"Content-Type": "text/plain"},
    )
    body = problem(response)
    assert response.status_code == 415
    assert body["code"] == "json_required"


def test_get_requests_are_exempt_from_origin_checks(make_app) -> None:
    with TestClient(make_app()) as client:
        headers = {"Origin": ORIGIN}
        assert (
            client.post(
                REGISTER_URL, json={"email": EMAIL, "password": PASSWORD}, headers=headers
            ).status_code
            == 201
        )
        assert (
            client.post(
                LOGIN_URL, json={"email": EMAIL, "password": PASSWORD}, headers=headers
            ).status_code
            == 200
        )
        # No Origin header on the GET: allowed and side-effect-free.
        assert client.get(ME_URL).status_code == 200
        assert client.get("/api/v1/health").status_code == 200


# --- throttling ---------------------------------------------------------------


def test_login_throttling_blocks_repeated_failures(make_app) -> None:
    app = make_app()
    now = [1000.0]
    app.state.login_throttle = LoginThrottle(
        max_attempts=3, window_seconds=300.0, clock=lambda: now[0]
    )
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        assert register(client).status_code == 201
        for _ in range(3):
            assert login(client, password="wrong-password-entirely").status_code == 401
        blocked = login(client)
        body = problem(blocked)
        assert blocked.status_code == 429
        assert body["code"] == "throttled"
        retry_after = int(blocked.headers["Retry-After"])
        assert 0 < retry_after <= 300
        # The per-IP bound covers other accounts too; registration is exempt.
        assert register(client, email="second@example.com").status_code == 201
        assert login(client, email="second@example.com").status_code == 429
        # After the window passes, the correct password works again.
        now[0] += 301.0
        assert login(client).status_code == 200


def test_successful_login_resets_throttle(make_app) -> None:
    app = make_app()
    app.state.login_throttle = LoginThrottle(
        max_attempts=3, window_seconds=300.0, clock=lambda: 1000.0
    )
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        assert register(client).status_code == 201
        assert login(client, password="wrong-password-entirely").status_code == 401
        assert login(client).status_code == 200
        # The first failure was reset; two fresh failures do not yet block.
        assert login(client, password="wrong-password-entirely").status_code == 401
        assert login(client, password="wrong-password-entirely").status_code == 401
        assert login(client).status_code == 200


# --- profile ------------------------------------------------------------------


def test_patch_profile_updates_writable_fields(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.patch(
        ME_URL,
        json={
            "display_name": "  Ada  ",
            "bodyweight_default_kg": 81,
            "sex": "female",
            "age": 34,
            "utc_offset_minutes": 180,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Ada"
    assert body["bodyweight_default_kg"] == 81
    assert body["sex"] == "female"
    assert body["age"] == 34
    assert body["utc_offset_minutes"] == 180
    stored = api_client.get(ME_URL).json()
    assert stored == body


def test_patch_profile_null_clears_optional_fields(api_client: TestClient) -> None:
    register_and_login(api_client)
    api_client.patch(
        ME_URL, json={"display_name": "Ada", "bodyweight_default_kg": 81, "utc_offset_minutes": 60}
    )
    api_client.patch(ME_URL, json={"sex": "male", "age": 30})
    response = api_client.patch(
        ME_URL,
        json={
            "display_name": None,
            "bodyweight_default_kg": None,
            "sex": None,
            "age": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] is None
    assert body["bodyweight_default_kg"] is None
    assert body["sex"] is None
    assert body["age"] is None
    # Absent fields stay untouched.
    assert body["utc_offset_minutes"] == 60


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"utc_offset_minutes": None},
        {"utc_offset_minutes": 841},
        {"utc_offset_minutes": -721},
        {"utc_offset_minutes": 30.5},
        {"utc_offset_minutes": "60"},
        {"utc_offset_minutes": True},
        {"bodyweight_default_kg": 0},
        {"bodyweight_default_kg": -5},
        {"bodyweight_default_kg": 81.5},
        {"bodyweight_default_kg": "81"},
        {"bodyweight_default_kg": True},
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "x" * 101},
        {"sex": "other"},
        {"sex": 5},
        {"age": 0},
        {"age": 121},
        {"age": 30.5},
        {"age": "30"},
        {"email": "other@example.com"},
        {"password": "another-strong-1"},
        {"role": "admin"},
        {"account_status": "disabled"},
    ],
)
def test_patch_profile_rejects_invalid_updates(api_client: TestClient, payload: dict) -> None:
    register_and_login(api_client)
    response = api_client.patch(ME_URL, json=payload)
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"


def test_patch_profile_requires_authentication(api_client: TestClient) -> None:
    assert api_client.patch(ME_URL, json={"display_name": "x"}).status_code == 401


def test_profile_writes_are_scoped_to_the_authenticated_account(make_app) -> None:
    app = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as alice,
        TestClient(app, headers={"Origin": ORIGIN}) as bob,
    ):
        register_and_login(alice, email="alice@example.com")
        register_and_login(bob, email="bob@example.com")
        assert alice.patch(ME_URL, json={"display_name": "Alice"}).status_code == 200
        assert bob.patch(ME_URL, json={"bodyweight_default_kg": 70}).status_code == 200

        alice_profile = alice.get(ME_URL).json()
        bob_profile = bob.get(ME_URL).json()
        assert alice_profile["display_name"] == "Alice"
        assert alice_profile["bodyweight_default_kg"] is None
        assert bob_profile["display_name"] is None
        assert bob_profile["bodyweight_default_kg"] == 70
        assert alice_profile["id"] != bob_profile["id"]


# --- shared conventions -------------------------------------------------------


def test_no_secrets_in_responses_or_logs(
    make_app, migrated_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    with caplog.at_level(logging.INFO), TestClient(app, headers={"Origin": ORIGIN}) as client:
        registered = register(client)
        logged_in = login(client)
        token = set_cookie_token(logged_in)
        assert token is not None
        profile = client.get(ME_URL)
        patched = client.patch(ME_URL, json={"display_name": "Tracker"})
        logged_out = client.post(LOGOUT_URL, json={})
    with connect(migrated_db) as conn:
        password_hash = conn.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
    secrets = [PASSWORD, token, password_hash]
    for response in (registered, logged_in, profile, patched, logged_out):
        for secret in secrets:
            assert secret not in response.text
    for secret in secrets:
        assert secret not in caplog.text


def test_request_ids_and_problem_documents(api_client: TestClient) -> None:
    healthy = api_client.get("/api/v1/health")
    request_id = healthy.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    rejected = api_client.get(ME_URL)
    body = problem(rejected)
    assert rejected.headers["X-Request-ID"] != request_id
    assert body["request_id"] == rejected.headers["X-Request-ID"]


def test_oversized_body_is_rejected(api_client: TestClient) -> None:
    response = register(api_client, password="x" * (300 * 1024))
    body = problem(response)
    assert response.status_code == 413
    assert body["code"] == "body_too_large"


def test_unknown_route_returns_problem_document(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    problem(response)


@pytest.mark.parametrize("app_env", ["production", "qa"])
def test_create_app_refuses_insecure_cookie_in_remote_envs(migrated_db: Path, app_env: str) -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        create_app(
            Settings(
                database_path=str(migrated_db),
                session_ttl_seconds=60,
                app_origin="https://basefit.example.com",
                cookie_secure=False,
                app_env=app_env,
            )
        )


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_create_app_allows_insecure_cookie_for_local_http(migrated_db: Path, app_env: str) -> None:
    app = create_app(
        Settings(
            database_path=str(migrated_db),
            session_ttl_seconds=60,
            app_origin="http://testserver",
            cookie_secure=False,
            app_env=app_env,
        )
    )
    assert app.state.settings.app_env == app_env
