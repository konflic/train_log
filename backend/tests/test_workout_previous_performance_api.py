"""Stage 8a inline previous-performance API tests (Gate G8a).

End-to-end coverage over the public routes: the additive `previous_performance`
member of the workout detail shape, GET/PUT/retry response equality, the
finished-save snapshot, a repeat-last copy with draft sets, owner isolation,
historical stability across profile and catalog edits, read-only enforcement of
the new member, and its OpenAPI description.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.numbers import MAX_SAFE_INTEGER

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
WORKOUTS_URL = "/api/v1/workouts"
EXERCISES_URL = "/api/v1/exercises"

PREVIOUS_START = "2026-01-01T08:00:00Z"
PREVIOUS_END = "2026-01-01T09:00:00Z"
CURRENT_START = "2026-02-01T08:00:00Z"
CURRENT_END = "2026-02-01T09:00:00Z"
LATER_START = "2026-03-01T08:00:00Z"
LATER_END = "2026-03-01T09:00:00Z"

CATALOG = "bench-press"

EXERCISE_FIELDS = {
    "id",
    "catalog_id",
    "order_index",
    "notes",
    "load_type",
    "bodyweight_percent",
    "side_count",
    "sets",
    "previous_performance",
}
PREVIOUS_FIELDS = {
    "workout_id",
    "started_at",
    "bodyweight_kg",
    "exercise_id",
    "order_index",
    "load_type",
    "bodyweight_percent",
    "side_count",
    "sets",
    "pairs",
}
PREVIOUS_SET_FIELDS = {
    "id",
    "set_index",
    "side",
    "reps",
    "weight_kg",
    "bw_percent_override",
    "values",
}
PAIR_FIELDS = {
    "current_set_id",
    "previous_set_id",
    "load_compatible",
    "current",
    "previous",
    "delta",
}
VALUE_FIELDS = {
    "reps",
    "external_load_kg",
    "effective_load_kg",
    "volume_kg_reps",
    "estimated_1rm_kg",
}


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


def set_body(set_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": set_id,
        "reps": 8,
        "weight_kg": 100,
        "bw_percent_override": None,
        "rpe": None,
        "side": "bilateral",
        "done": True,
    }
    payload.update(overrides)
    return payload


def exercise_body(
    exercise_id: str, *, catalog_id: str = CATALOG, sets: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": exercise_id,
        "catalog_id": catalog_id,
        "notes": None,
        "sets": sets if sets is not None else [],
    }


def save_body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "revision": 0,
        "save_id": str(uuid.uuid4()),
        "name": None,
        "notes": None,
        "bodyweight_kg": None,
        "ended_at": None,
        "exercises": [],
    }
    payload.update(overrides)
    return payload


def register_and_login(client: TestClient, email: str = "user@example.com") -> str:
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return str(registered.json()["id"])


@pytest.fixture()
def alice(make_app) -> Iterator[TestClient]:
    app: FastAPI = make_app()
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        register_and_login(client, email="alice@example.com")
        yield client


@pytest.fixture()
def alice_and_bob(make_app) -> Iterator[tuple[TestClient, TestClient]]:
    app: FastAPI = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as alice,
        TestClient(app, headers={"Origin": ORIGIN}) as bob,
    ):
        register_and_login(alice, email="alice@example.com")
        register_and_login(bob, email="bob@example.com")
        yield alice, bob


def create(client: TestClient, started_at: str) -> str:
    response = client.post(WORKOUTS_URL, json={"id": str(uuid.uuid4()), "started_at": started_at})
    assert response.status_code == 201
    return str(response.json()["id"])


def save(client: TestClient, workout_id: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.put(f"{WORKOUTS_URL}/{workout_id}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def detail(client: TestClient, workout_id: str) -> dict[str, Any]:
    response = client.get(f"{WORKOUTS_URL}/{workout_id}")
    assert response.status_code == 200
    return response.json()


def seed_finished_session(
    client: TestClient,
    *,
    started_at: str = PREVIOUS_START,
    ended_at: str = PREVIOUS_END,
    exercise_id: int = 1,
    sets: list[dict[str, Any]] | None = None,
    bodyweight_kg: int | None = None,
) -> tuple[str, str, list[str]]:
    """Create, fill, and finish one session; returns its id, exercise id, set ids."""
    workout_id = create(client, started_at)
    resolved_sets = sets if sets is not None else [set_body(uid(exercise_id * 10 + 1))]
    save(
        client,
        workout_id,
        save_body(
            revision=0,
            bodyweight_kg=bodyweight_kg,
            ended_at=ended_at,
            exercises=[exercise_body(uid(exercise_id), sets=resolved_sets)],
        ),
    )
    return workout_id, uid(exercise_id), [item["id"] for item in resolved_sets]


# --- response shape -----------------------------------------------------------


def test_detail_carries_the_previous_performance_member(alice: TestClient) -> None:
    previous_id, previous_exercise, previous_sets = seed_finished_session(
        alice, sets=[set_body(uid(11), reps=8, weight_kg=100)]
    )
    current_id = create(alice, CURRENT_START)
    current_set = uid(21)
    saved = save(
        alice,
        current_id,
        save_body(
            revision=0,
            ended_at=CURRENT_END,
            exercises=[exercise_body(uid(2), sets=[set_body(current_set, reps=10, weight_kg=105)])],
        ),
    )
    exercise = saved["exercises"][0]
    assert set(exercise) == EXERCISE_FIELDS
    previous = exercise["previous_performance"]
    assert previous == {
        "workout_id": previous_id,
        "started_at": PREVIOUS_START,
        "bodyweight_kg": None,
        "exercise_id": previous_exercise,
        "order_index": 0,
        "load_type": "single_weight",
        "bodyweight_percent": None,
        "side_count": 1,
        "sets": [
            {
                "id": previous_sets[0],
                "set_index": 0,
                "side": "bilateral",
                "reps": 8,
                "weight_kg": 100,
                "bw_percent_override": None,
                "values": {
                    "reps": 8,
                    "external_load_kg": 100,
                    "effective_load_kg": 100,
                    "volume_kg_reps": 800,
                    "estimated_1rm_kg": 126,
                },
            }
        ],
        "pairs": [
            {
                "current_set_id": current_set,
                "previous_set_id": previous_sets[0],
                "load_compatible": True,
                "current": {
                    "reps": 10,
                    "external_load_kg": 105,
                    "effective_load_kg": 105,
                    "volume_kg_reps": 1050,
                    "estimated_1rm_kg": 140,
                },
                "previous": {
                    "reps": 8,
                    "external_load_kg": 100,
                    "effective_load_kg": 100,
                    "volume_kg_reps": 800,
                    "estimated_1rm_kg": 126,
                },
                "delta": {
                    "reps": 2,
                    "external_load_kg": 5,
                    "effective_load_kg": 5,
                    "volume_kg_reps": 250,
                    "estimated_1rm_kg": 14,
                },
            }
        ],
    }
    assert set(previous) == PREVIOUS_FIELDS
    assert set(previous["sets"][0]) == PREVIOUS_SET_FIELDS
    assert set(previous["sets"][0]["values"]) == VALUE_FIELDS
    assert set(previous["pairs"][0]) == PAIR_FIELDS
    assert set(previous["pairs"][0]["delta"]) == VALUE_FIELDS
    # The member is additive: the pre-existing detail shape is unchanged.
    assert detail(alice, current_id) == saved


def test_a_workout_without_history_reports_null_previous_performance(
    alice: TestClient,
) -> None:
    workout_id = create(alice, CURRENT_START)
    assert detail(alice, workout_id)["exercises"] == []
    saved = save(
        alice,
        workout_id,
        save_body(revision=0, exercises=[exercise_body(uid(1), sets=[set_body(uid(11))])]),
    )
    assert saved["exercises"][0]["previous_performance"] is None
    # An active view still reports the field, and finishing does not add history.
    finished = save(
        alice,
        workout_id,
        save_body(
            revision=1,
            ended_at=CURRENT_END,
            exercises=[exercise_body(uid(1), sets=[set_body(uid(11))])],
        ),
    )
    assert finished["exercises"][0]["previous_performance"] is None


def test_an_active_view_exposes_last_time_before_any_set_is_done(
    alice: TestClient,
) -> None:
    previous_id, _, previous_sets = seed_finished_session(
        alice,
        sets=[set_body(uid(11), reps=8, weight_kg=100), set_body(uid(12), reps=6, weight_kg=95)],
    )
    current_id = create(alice, CURRENT_START)
    saved = save(
        alice,
        current_id,
        save_body(
            revision=0,
            exercises=[
                exercise_body(
                    uid(2),
                    sets=[
                        set_body(uid(21), reps=None, weight_kg=None, done=False),
                        set_body(uid(22), reps=None, weight_kg=None, done=False),
                    ],
                )
            ],
        ),
    )
    previous = saved["exercises"][0]["previous_performance"]
    assert previous["workout_id"] == previous_id
    assert [item["id"] for item in previous["sets"]] == previous_sets
    assert [item["values"]["reps"] for item in previous["sets"]] == [8, 6]
    # Nothing is completed yet, so nothing is compared.
    assert previous["pairs"] == []


# --- GET / PUT / retry equality -----------------------------------------------


def test_put_and_get_return_equal_detail_representations(alice: TestClient) -> None:
    seed_finished_session(alice, sets=[set_body(uid(11), reps=8, weight_kg=100)])
    current_id = create(alice, CURRENT_START)
    body = save_body(
        revision=0,
        exercises=[exercise_body(uid(2), sets=[set_body(uid(21), reps=9, weight_kg=102)])],
    )
    first = save(alice, current_id, body)
    assert detail(alice, current_id) == first
    # A later save that completes a new set updates the comparison in both.
    second = save(
        alice,
        current_id,
        save_body(
            revision=1,
            exercises=[
                exercise_body(
                    uid(2),
                    sets=[
                        set_body(uid(21), reps=9, weight_kg=102),
                        set_body(uid(22), reps=5, weight_kg=90),
                    ],
                )
            ],
        ),
    )
    assert detail(alice, current_id) == second
    pairs = second["exercises"][0]["previous_performance"]["pairs"]
    # Only the first current set existed last time; the new one is unmatched.
    assert [pair["current_set_id"] for pair in pairs] == [uid(21)]


def test_an_exact_save_retry_returns_the_same_detail(alice: TestClient) -> None:
    previous_id, _, _ = seed_finished_session(
        alice, sets=[set_body(uid(11), reps=8, weight_kg=100)]
    )
    current_id = create(alice, CURRENT_START)
    body = save_body(
        revision=0,
        ended_at=CURRENT_END,
        exercises=[exercise_body(uid(2), sets=[set_body(uid(21), reps=10, weight_kg=105)])],
    )
    accepted = save(alice, current_id, body)

    # History is live for GET, but an exact receipt retry must replay the
    # response that acknowledged this save rather than a newly selected session.
    intervening_id, _, _ = seed_finished_session(
        alice,
        started_at="2026-01-15T08:00:00Z",
        ended_at="2026-01-15T09:00:00Z",
        exercise_id=3,
        sets=[set_body(uid(31), reps=9, weight_kg=102)],
    )
    assert (
        detail(alice, current_id)["exercises"][0]["previous_performance"]["workout_id"]
        == intervening_id
    )
    retry = save(alice, current_id, body)
    assert retry == accepted
    assert retry["exercises"][0]["previous_performance"]["workout_id"] == previous_id
    assert retry["revision"] == accepted["revision"] == 1
    assert retry["exercises"][0]["previous_performance"]["pairs"][0]["delta"]["reps"] == 2


def test_save_rejects_unsafe_derived_values(alice: TestClient) -> None:
    workout_id = create(alice, CURRENT_START)
    response = alice.put(
        f"{WORKOUTS_URL}/{workout_id}",
        json=save_body(
            revision=0,
            exercises=[
                exercise_body(
                    uid(2),
                    sets=[set_body(uid(21), reps=2, weight_kg=MAX_SAFE_INTEGER)],
                )
            ],
        ),
    )
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "exercises.0.sets.0",
            "message": "derived set values exceed the safe integer range",
        }
    ]


def test_the_finishing_save_reports_previous_performance(alice: TestClient) -> None:
    previous_id, _, _ = seed_finished_session(alice)
    current_id = create(alice, CURRENT_START)
    finished = save(
        alice,
        current_id,
        save_body(
            revision=0,
            ended_at=CURRENT_END,
            exercises=[exercise_body(uid(2), sets=[set_body(uid(21), reps=8, weight_kg=100)])],
        ),
    )
    previous = finished["exercises"][0]["previous_performance"]
    # The workout that was just finished is never its own history.
    assert previous["workout_id"] == previous_id
    assert previous["pairs"][0]["delta"]["reps"] == 0
    assert previous["pairs"][0]["delta"]["volume_kg_reps"] == 0


# --- owner isolation ----------------------------------------------------------


def test_another_users_training_never_becomes_history(
    alice_and_bob: tuple[TestClient, TestClient],
) -> None:
    alice, bob = alice_and_bob
    foreign_id, foreign_exercise, foreign_sets = seed_finished_session(
        bob, sets=[set_body(uid(11), reps=20, weight_kg=200)]
    )
    current_id = create(alice, CURRENT_START)
    response = alice.put(
        f"{WORKOUTS_URL}/{current_id}",
        json=save_body(
            revision=0,
            exercises=[exercise_body(uid(2), sets=[set_body(uid(21), reps=8, weight_kg=100)])],
        ),
    )
    assert response.status_code == 200
    assert response.json()["exercises"][0]["previous_performance"] is None
    # No foreign identifier appears anywhere in the body.
    for secret in (foreign_id, foreign_exercise, *foreign_sets):
        assert secret not in response.text
    assert detail(alice, current_id)["exercises"][0]["previous_performance"] is None


# --- historical stability -----------------------------------------------------


def test_profile_and_catalog_edits_do_not_change_reported_history(alice: TestClient) -> None:
    created = alice.post(
        EXERCISES_URL,
        json={
            "name": "Heavy Curl",
            "muscle_group": "arms",
            "equipment": "dumbbell",
            "load_type": "split_weight",
            "bodyweight_percent": None,
            "side_count": 2,
        },
    )
    assert created.status_code == 201
    catalog_id = str(created.json()["id"])

    previous_id = create(alice, PREVIOUS_START)
    save(
        alice,
        previous_id,
        save_body(
            revision=0,
            bodyweight_kg=75,
            ended_at=PREVIOUS_END,
            exercises=[
                exercise_body(
                    uid(1), catalog_id=catalog_id, sets=[set_body(uid(11), reps=8, weight_kg=12)]
                )
            ],
        ),
    )
    current_id = create(alice, CURRENT_START)
    body = save_body(
        revision=0,
        bodyweight_kg=75,
        ended_at=CURRENT_END,
        exercises=[
            exercise_body(
                uid(2), catalog_id=catalog_id, sets=[set_body(uid(21), reps=8, weight_kg=14)]
            )
        ],
    )
    before = save(alice, current_id, body)
    pair = before["exercises"][0]["previous_performance"]["pairs"][0]
    # Two 12 kg dumbbells: 12 * 2 * 8 = 192 kg-reps.
    assert pair["previous"]["external_load_kg"] == 24
    assert pair["previous"]["volume_kg_reps"] == 192
    assert pair["current"]["external_load_kg"] == 28
    assert pair["delta"]["volume_kg_reps"] == 224 - 192

    # A profile edit and a catalog edit both apply only to future instances.
    assert alice.patch("/api/v1/auth/me", json={"bodyweight_default_kg": 120}).status_code == 200
    assert alice.patch(f"{EXERCISES_URL}/{catalog_id}", json={"side_count": 1}).status_code == 200

    after = detail(alice, current_id)
    assert after == before
    assert after["exercises"][0]["load_type"] == "split_weight"
    assert after["exercises"][0]["side_count"] == 2
    assert after["bodyweight_kg"] == 75


def test_recorded_bodyweights_drive_the_comparison(alice: TestClient) -> None:
    previous_id, _, _ = seed_finished_session(
        alice, sets=[set_body(uid(11), reps=8, weight_kg=100)], bodyweight_kg=70
    )
    current_id = create(alice, CURRENT_START)
    saved = save(
        alice,
        current_id,
        save_body(
            revision=0,
            bodyweight_kg=90,
            exercises=[exercise_body(uid(2), sets=[set_body(uid(21), reps=8, weight_kg=100)])],
        ),
    )
    previous = saved["exercises"][0]["previous_performance"]
    assert previous["workout_id"] == previous_id
    assert previous["bodyweight_kg"] == 70
    assert saved["bodyweight_kg"] == 90
    # No bodyweight percentage is recorded, so both sides stay at the external
    # load and the profile difference fabricates no progression.
    assert previous["pairs"][0]["delta"]["effective_load_kg"] == 0


# --- repeat-last --------------------------------------------------------------


def test_a_repeat_with_draft_sets_does_not_become_history(alice: TestClient) -> None:
    original_id, original_exercise, original_sets = seed_finished_session(
        alice, sets=[set_body(uid(11), reps=8, weight_kg=100)]
    )
    # Repeat-last: new ids, copied values, every set back to a draft.
    repeat_id = create(alice, LATER_START)
    repeated = save(
        alice,
        repeat_id,
        save_body(
            revision=0,
            ended_at=LATER_END,
            exercises=[
                exercise_body(
                    uid(2), sets=[set_body(uid(21), reps=8, weight_kg=100, done=False, rpe=None)]
                )
            ],
        ),
    )
    repeat_previous = repeated["exercises"][0]["previous_performance"]
    assert repeat_previous["workout_id"] == original_id
    assert [item["id"] for item in repeat_previous["sets"]] == original_sets
    assert repeat_previous["pairs"] == []

    current_id = create(alice, "2026-04-01T08:00:00Z")
    saved = save(
        alice,
        current_id,
        save_body(
            revision=0,
            ended_at="2026-04-01T09:00:00Z",
            exercises=[exercise_body(uid(3), sets=[set_body(uid(31), reps=10, weight_kg=105)])],
        ),
    )
    previous = saved["exercises"][0]["previous_performance"]
    # The unfinished repeat is skipped; the original remains the history.
    assert previous["workout_id"] == original_id
    assert previous["exercise_id"] == original_exercise
    assert previous["pairs"][0]["previous_set_id"] == original_sets[0]
    assert previous["pairs"][0]["delta"]["reps"] == 2


# --- read-only enforcement and OpenAPI ----------------------------------------


def test_previous_performance_is_rejected_as_save_input(alice: TestClient) -> None:
    seed_finished_session(alice)
    current_id = create(alice, CURRENT_START)
    submitted = exercise_body(uid(2), sets=[set_body(uid(21))])
    submitted["previous_performance"] = None
    response = alice.put(
        f"{WORKOUTS_URL}/{current_id}",
        json=save_body(revision=0, exercises=[submitted]),
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_openapi_describes_previous_performance_as_a_nullable_addition(
    alice: TestClient,
) -> None:
    components = alice.get("/openapi.json").json()["components"]["schemas"]
    for name in (
        "PreviousPerformanceResponse",
        "PreviousSetResponse",
        "PreviousSetPairResponse",
        "SetValuesResponse",
    ):
        assert components[name]["additionalProperties"] is False
    exercise = components["ExerciseNodeResponse"]
    # Additive and nullable: the existing detail members stay required.
    assert exercise["properties"]["previous_performance"]["anyOf"] == [
        {"$ref": "#/components/schemas/PreviousPerformanceResponse"},
        {"type": "null"},
    ]
    assert "previous_performance" in exercise["required"]
    pair = components["PreviousSetPairResponse"]["properties"]
    assert pair["load_compatible"]["type"] == "boolean"
    for member in ("current", "previous", "delta"):
        assert pair[member]["$ref"] == "#/components/schemas/SetValuesResponse"
    # Every reported value is a nullable integer, never a float.
    for field, value in components["SetValuesResponse"]["properties"].items():
        assert value["anyOf"] == [{"type": "integer"}, {"type": "null"}], field
    assert components["PreviousSetResponse"]["properties"]["side"] == {
        "enum": ["left", "right", "bilateral"],
        "title": "Side",
        "type": "string",
    }
