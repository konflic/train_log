"""Exercise detail and description API tests (exercise information screen).

Covers the summary/detail split (the bounded list never carries guidance or
description text), default guidance from the version-controlled registry,
custom description create/update/explicit-clear with Unicode trimming and
codepoint bounds, default immutability, and the established 404 privacy and
problem+json conventions for the detail representation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
EXERCISES_URL = "/api/v1/exercises"

SUMMARY_FIELDS = {
    "id",
    "name",
    "muscle_group",
    "load_type",
    "bodyweight_percent",
    "side_count",
    "is_default",
}
DETAIL_FIELDS = SUMMARY_FIELDS | {"description", "guidance"}
MAX_DESCRIPTION_LENGTH = 1000


def register_and_login(client: TestClient, email: str = "user@example.com") -> str:
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return str(registered.json()["id"])


def problem(response) -> dict:
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == response.status_code
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body


@contextmanager
def two_users(make_app) -> Iterator[tuple[TestClient, TestClient]]:
    app: FastAPI = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as alice,
        TestClient(app, headers={"Origin": ORIGIN}) as bob,
    ):
        register_and_login(alice, email="alice@example.com")
        register_and_login(bob, email="bob@example.com")
        yield alice, bob


def create_custom(client: TestClient, **overrides: object):
    payload: dict = {
        "name": "Custom Curl",
        "muscle_group": "arms",
        "load_type": "split_weight",
        "side_count": 2,
    }
    payload.update(overrides)
    return client.post(EXERCISES_URL, json=payload)


# --- summary/detail split ------------------------------------------------------


def test_list_summaries_carry_no_description_or_guidance(api_client: TestClient) -> None:
    register_and_login(api_client)
    body = api_client.get(EXERCISES_URL).json()
    assert body["total"] > 0
    for item in body["items"]:
        assert set(item) == SUMMARY_FIELDS
        assert "description" not in item
        assert "guidance" not in item
    assert "technique_steps" not in api_client.get(EXERCISES_URL).text


def test_default_detail_returns_validated_guidance(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.get(f"{EXERCISES_URL}/pull-up")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == "pull-up"
    assert body["is_default"] is True
    assert isinstance(body["description"], str) and body["description"].strip()
    guidance = body["guidance"]
    assert guidance is not None
    assert set(guidance) == {"technique_steps", "form_tips", "animation_key", "sources"}
    assert guidance["animation_key"] == "pull-up"
    assert len(guidance["technique_steps"]) >= 2
    assert len(guidance["form_tips"]) >= 1
    assert all(step.strip() for step in guidance["technique_steps"])
    assert all(tip.strip() for tip in guidance["form_tips"])
    assert len(guidance["sources"]) >= 1
    for source in guidance["sources"]:
        assert set(source) == {"title", "url"}
        assert source["url"].startswith("https://")


# --- custom descriptions --------------------------------------------------------


def test_create_custom_with_description_roundtrips(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = create_custom(api_client, description="  My favourite arm work.  ")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["description"] == "My favourite arm work."
    assert body["guidance"] is None
    fetched = api_client.get(f"{EXERCISES_URL}/{body['id']}").json()
    assert fetched == body


def test_create_custom_without_description_stores_null(api_client: TestClient) -> None:
    register_and_login(api_client)
    body = create_custom(api_client).json()
    assert body["description"] is None
    assert body["guidance"] is None


def test_create_blank_description_normalizes_to_null(api_client: TestClient) -> None:
    register_and_login(api_client)
    for blank in ("", "   ", "\t\n\u00a0\u2028  "):
        response = create_custom(api_client, name=f"Blank {len(blank)}", description=blank)
        assert response.status_code == 201
        assert response.json()["description"] is None


def test_description_length_counts_codepoints(api_client: TestClient) -> None:
    register_and_login(api_client)
    # 1,000 single-codepoint characters (outside the BMP) are accepted...
    exact = create_custom(api_client, name="Exact", description="💪" * MAX_DESCRIPTION_LENGTH)
    assert exact.status_code == 201
    assert exact.json()["description"] == "💪" * MAX_DESCRIPTION_LENGTH
    # ...1,001 are rejected.
    too_long = create_custom(
        api_client, name="Too long", description="💪" * (MAX_DESCRIPTION_LENGTH + 1)
    )
    assert too_long.status_code == 422
    assert problem(too_long)["code"] == "validation_error"


def test_description_rejects_non_string(api_client: TestClient) -> None:
    register_and_login(api_client)
    for invalid in (5, True, ["text"], {"text": 1}):
        response = create_custom(api_client, name=f"Invalid {invalid}", description=invalid)
        assert response.status_code == 422
        assert problem(response)["code"] == "validation_error"


def test_patch_updates_and_clears_description(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_custom(api_client, description="Initial note").json()
    updated = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}", json={"description": "  Revised note  "}
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Revised note"
    # Absent description stays untouched.
    renamed = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"name": "Renamed"})
    assert renamed.json()["description"] == "Revised note"
    # Explicit null clears; blank normalizes to null as well.
    cleared = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"description": None})
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None
    blanked = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"description": "  \n "})
    assert blanked.json()["description"] is None


def test_patch_description_bounds_are_enforced(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_custom(api_client).json()
    too_long = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}",
        json={"description": "x" * (MAX_DESCRIPTION_LENGTH + 1)},
    )
    assert too_long.status_code == 422
    assert problem(too_long)["code"] == "validation_error"


def test_default_descriptions_are_immutable(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.patch(
        f"{EXERCISES_URL}/bench-press", json={"description": "Rewritten by a user"}
    )
    assert response.status_code == 403
    assert problem(response)["code"] == "default_immutable"
    assert "Rewritten" not in api_client.get(f"{EXERCISES_URL}/bench-press").text


def test_custom_details_never_fabricate_guidance(api_client: TestClient) -> None:
    register_and_login(api_client)
    body = create_custom(api_client, description="Personal entry").json()
    response = api_client.get(f"{EXERCISES_URL}/{body['id']}")
    detail = response.json()
    assert detail["guidance"] is None
    assert "technique_steps" not in response.text


def test_detail_visibility_matches_summary_rules(make_app) -> None:
    with two_users(make_app) as (alice, bob):
        entry = create_custom(alice, description="Alice only").json()
        unknown = alice.get(f"{EXERCISES_URL}/no-such-entry")
        assert unknown.status_code == 404
        assert problem(unknown)["code"] == "not_found"
        # A foreign custom is indistinguishable from an unknown id: the same
        # status, code, title, and detail (only the request id differs).
        foreign = bob.get(f"{EXERCISES_URL}/{entry['id']}")
        assert foreign.status_code == 404
        foreign_problem = problem(foreign)
        unknown_problem = problem(unknown)
        assert {key: foreign_problem[key] for key in ("status", "code", "title", "detail")} == {
            key: unknown_problem[key] for key in ("status", "code", "title", "detail")
        }


@pytest.mark.parametrize("method", ["get_detail", "patch", "stats"])
def test_detail_endpoints_require_authentication(api_client: TestClient, method: str) -> None:
    if method == "get_detail":
        response = api_client.get(f"{EXERCISES_URL}/pull-up")
    elif method == "patch":
        response = api_client.patch(f"{EXERCISES_URL}/pull-up", json={"description": "x"})
    else:
        response = api_client.get(f"{EXERCISES_URL}/pull-up/stats")
    assert response.status_code == 401
    assert problem(response)["code"] == "unauthorized"
