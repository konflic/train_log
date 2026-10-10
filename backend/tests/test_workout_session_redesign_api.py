"""Behavioral contract for explicit starts, plans, and immutable snapshots."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
WORKOUTS = "/api/v1/workouts"
PLANS = "/api/v1/training-plans"
STARTED_AT = "2026-02-01T08:00:00Z"


def register_and_login(client: TestClient, email: str = "session@example.com") -> None:
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
        ).status_code
        == 201
    )
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code
        == 200
    )


def start_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "started_at": STARTED_AT,
        "session_type": "freestyle",
    }
    payload.update(overrides)
    return payload


def empty_save(detail: dict[str, object], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "revision": detail["revision"],
        "save_id": str(uuid.uuid4()),
        "name": detail["name"],
        "notes": detail["notes"],
        "bodyweight_kg": detail["bodyweight_kg"],
        "ended_at": None,
        "exercises": [],
    }
    payload.update(overrides)
    return payload


def plan_payload() -> dict[str, object]:
    return {
        "name": "Pull day",
        "notes": "Reusable targets",
        "exercises": [
            {
                "catalog_id": "dumbbell-curl",
                "notes": "Controlled",
                "sets": [
                    {
                        "target_reps": 8,
                        "target_weight_kg": 12,
                        "side": "bilateral",
                        "bw_percent_override": None,
                    }
                ],
            }
        ],
    }


def test_explicit_start_is_idempotent_and_blocks_a_different_active_session(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    assert api_client.get(WORKOUTS, params={"status": "active"}).json()["total"] == 0

    payload = start_payload()
    first = api_client.post(WORKOUTS, json=payload)
    assert first.status_code == 201
    assert first.json()["session_type"] == "freestyle"

    retry = api_client.post(WORKOUTS, json=payload)
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]

    competing = api_client.post(WORKOUTS, json=start_payload())
    assert competing.status_code == 409
    assert competing.json()["code"] == "active_session_exists"
    active = api_client.get(WORKOUTS, params={"status": "active"}).json()
    assert active["total"] == 1
    assert active["items"][0]["id"] == first.json()["id"]


def test_concurrent_clients_create_exactly_one_active_session(make_app) -> None:
    app = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as first,
        TestClient(app, headers={"Origin": ORIGIN}) as second,
    ):
        register_and_login(first, "concurrent-start@example.com")
        assert (
            second.post(
                "/api/v1/auth/login",
                json={"email": "concurrent-start@example.com", "password": PASSWORD},
            ).status_code
            == 200
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda item: item[0].post(WORKOUTS, json=item[1]),
                    [(first, start_payload()), (second, start_payload())],
                )
            )

        assert sorted(response.status_code for response in responses) == [201, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json()["code"] == "active_session_exists"
        assert first.get(WORKOUTS, params={"status": "active"}).json()["total"] == 1


def test_bodyweight_is_copied_from_settings_and_cannot_be_overridden(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    assert (
        api_client.patch("/api/v1/auth/me", json={"bodyweight_default_kg": 81}).status_code == 200
    )
    detail = api_client.post(WORKOUTS, json=start_payload()).json()
    assert detail["bodyweight_kg"] == 81

    changed = api_client.put(
        f"{WORKOUTS}/{detail['id']}",
        json=empty_save(detail, bodyweight_kg=90),
    )
    assert changed.status_code == 422
    assert changed.json()["errors"] == [
        {
            "field": "bodyweight_kg",
            "message": "recorded bodyweight is a read-only Settings snapshot",
        }
    ]
    assert api_client.get(f"{WORKOUTS}/{detail['id']}").json()["bodyweight_kg"] == 81


def test_plan_browsing_and_crud_do_not_start_a_session(api_client: TestClient) -> None:
    register_and_login(api_client)
    created = api_client.post(PLANS, json=plan_payload())
    assert created.status_code == 201
    plan = created.json()
    assert plan["revision"] == 0
    assert api_client.get(WORKOUTS, params={"status": "active"}).json()["total"] == 0

    fetched = api_client.get(f"{PLANS}/{plan['id']}")
    assert fetched.status_code == 200
    updated_payload = plan_payload() | {"name": "Pull day A", "revision": 0}
    updated = api_client.put(f"{PLANS}/{plan['id']}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["revision"] == 1
    assert api_client.get(WORKOUTS, params={"status": "active"}).json()["total"] == 0


def test_start_from_plan_copies_an_independent_unfinished_graph(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    plan = api_client.post(PLANS, json=plan_payload()).json()
    request = start_payload(
        session_type="from_plan",
        source_plan_id=plan["id"],
        source_plan_revision=plan["revision"],
    )
    started = api_client.post(WORKOUTS, json=request)
    assert started.status_code == 201
    session = started.json()
    assert session["name"] == "Workout on 2026-02-01"
    assert session["source_plan_id"] == plan["id"]
    assert session["exercises"][0]["id"] != plan["exercises"][0]["id"]
    copied_set = session["exercises"][0]["sets"][0]
    assert copied_set["id"] != plan["exercises"][0]["sets"][0]["id"]
    assert copied_set["done"] is False
    assert copied_set["rpe"] is None

    assert (
        api_client.delete(
            f"{PLANS}/{plan['id']}",
            params={"revision": plan["revision"]},
            headers={"Content-Type": "application/json"},
        ).status_code
        == 204
    )
    preserved = api_client.get(f"{WORKOUTS}/{session['id']}").json()
    assert preserved["name"] == "Workout on 2026-02-01"
    assert preserved["exercises"] == session["exercises"]
    retry = api_client.post(WORKOUTS, json=request)
    assert retry.status_code == 200
    assert retry.json()["id"] == session["id"]


def test_stale_or_foreign_plan_start_is_atomic(make_app) -> None:
    app = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as alice,
        TestClient(app, headers={"Origin": ORIGIN}) as bob,
    ):
        register_and_login(alice, "alice-plan@example.com")
        register_and_login(bob, "bob-plan@example.com")
        plan = alice.post(PLANS, json=plan_payload()).json()

        stale = alice.post(
            WORKOUTS,
            json=start_payload(
                session_type="from_plan",
                source_plan_id=plan["id"],
                source_plan_revision=plan["revision"] + 1,
            ),
        )
        assert stale.status_code == 409
        assert alice.get(WORKOUTS, params={"status": "active"}).json()["total"] == 0

        foreign = bob.post(
            WORKOUTS,
            json=start_payload(
                session_type="from_plan",
                source_plan_id=plan["id"],
                source_plan_revision=plan["revision"],
            ),
        )
        assert foreign.status_code == 409
        assert foreign.json()["code"] == "plan_unavailable"
        assert bob.get(WORKOUTS, params={"status": "active"}).json()["total"] == 0
