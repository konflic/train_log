"""Stage 8b statistics summary API tests (Gate G8b).

End-to-end coverage over the public route: authentication, the exact response
shape and canonical muscle-group ordering, a full create/save/finish flow,
inclusive local-date filtering with the shared history parser and the caller's
UTC offset, empty reversed ranges, owner isolation without count leaks, the
explicit 500 for an unsafe aggregate, and the OpenAPI description.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import insert_exercise, insert_set, insert_workout

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.services.stats import MUSCLE_GROUP_ORDER
from app.timestamps import to_timestamp

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
SUMMARY_URL = "/api/v1/stats/summary"
WORKOUTS_URL = "/api/v1/workouts"
ME_URL = "/api/v1/auth/me"

SUMMARY_FIELDS = {
    "workout_count",
    "completed_set_count",
    "training_day_count",
    "total_volume_kg_reps",
    "unknown_load_set_count",
    "volume_complete",
    "muscle_group_frequency",
    "current_week_streak",
}
FREQUENCY_FIELDS = {"muscle_group", "workout_count"}


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


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


def get_summary(client: TestClient, **params: str) -> dict[str, Any]:
    response = client.get(SUMMARY_URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def frequencies(body: dict[str, Any]) -> dict[str, int]:
    return {item["muscle_group"]: item["workout_count"] for item in body["muscle_group_frequency"]}


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


def finish_session(
    client: TestClient,
    *,
    started_at: str,
    ended_at: str,
    catalog_id: str = "bench-press",
    sets: list[dict[str, Any]] | None = None,
    bodyweight_kg: int | None = None,
    exercise_id: int = 1,
) -> str:
    """Create, fill, and finish one session through the public save protocol."""
    if bodyweight_kg is not None:
        profile = client.patch("/api/v1/auth/me", json={"bodyweight_default_kg": bodyweight_kg})
        assert profile.status_code == 200, profile.text
    created = client.post(WORKOUTS_URL, json={"id": str(uuid.uuid4()), "started_at": started_at})
    assert created.status_code == 201, created.text
    workout_id = str(created.json()["id"])
    recorded_bodyweight = created.json()["bodyweight_kg"]
    resolved_sets = sets if sets is not None else [set_body(uid(exercise_id * 100 + 1))]
    saved = client.put(
        f"{WORKOUTS_URL}/{workout_id}",
        json=save_body(
            bodyweight_kg=recorded_bodyweight,
            ended_at=ended_at,
            exercises=[
                {
                    "id": uid(exercise_id),
                    "catalog_id": catalog_id,
                    "notes": None,
                    "sets": resolved_sets,
                }
            ],
        ),
    )
    assert saved.status_code == 200, saved.text
    return workout_id


def seed_finished_workout(
    database_path: Path,
    user_id: str,
    workout_id: str,
    *,
    started_at: str,
    ended_at: str | None = None,
    catalog_id: str = "bench-press",
    reps: int = 8,
    weight_kg: int | None = 100,
) -> None:
    """Insert one finished workout with a single completed set directly."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(
            conn,
            workout_id,
            user_id=user_id,
            started_at=started_at,
            ended_at=ended_at or started_at,
        )
        insert_exercise(
            conn,
            f"{workout_id}-e0",
            workout_id=workout_id,
            catalog_id=catalog_id,
            load_type="single_weight",
            side_count=1,
        )
        insert_set(
            conn,
            f"{workout_id}-s0",
            exercise_id=f"{workout_id}-e0",
            reps=reps,
            weight_kg=weight_kg,
            done=1,
        )


# --- authentication and shape --------------------------------------------------


def test_summary_requires_authentication(make_app) -> None:
    app: FastAPI = make_app()
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        response = client.get(SUMMARY_URL)
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert response.headers["content-type"] == "application/problem+json"


def test_empty_history_reports_the_exact_contract(alice: TestClient) -> None:
    body = get_summary(alice)
    assert set(body) == SUMMARY_FIELDS
    assert body["workout_count"] == 0
    assert body["completed_set_count"] == 0
    assert body["training_day_count"] == 0
    # An empty selection is a known zero, never an unknown total.
    assert body["total_volume_kg_reps"] == 0
    assert body["unknown_load_set_count"] == 0
    assert body["volume_complete"] is True
    assert body["current_week_streak"] == 0
    assert [item["muscle_group"] for item in body["muscle_group_frequency"]] == list(
        MUSCLE_GROUP_ORDER
    )
    for item in body["muscle_group_frequency"]:
        assert set(item) == FREQUENCY_FIELDS
        assert item["workout_count"] == 0


def test_finished_public_flow_reports_counts_volume_and_groups(alice: TestClient) -> None:
    # Bench 8x100 = 800 plus bench 8x12 = 96 (chest), then split curls
    # 2x12x8 = 192 (arms).
    finish_session(
        alice,
        started_at="2026-01-15T08:00:00Z",
        ended_at="2026-01-15T09:00:00Z",
        sets=[
            set_body(uid(101)),
            set_body(uid(102), reps=8, weight_kg=12),
        ],
        bodyweight_kg=80,
    )
    finish_session(
        alice,
        started_at="2026-01-17T08:00:00Z",
        ended_at="2026-01-17T09:00:00Z",
        catalog_id="dumbbell-curl",
        sets=[set_body(uid(201), reps=8, weight_kg=12)],
        exercise_id=2,
    )
    body = get_summary(alice)
    assert body["workout_count"] == 2
    assert body["completed_set_count"] == 3
    assert body["training_day_count"] == 2
    assert body["total_volume_kg_reps"] == 800 + 96 + 192
    assert body["unknown_load_set_count"] == 0
    assert body["volume_complete"] is True
    counts = frequencies(body)
    assert counts["chest"] == 1
    assert counts["arms"] == 1
    assert counts["back"] == 0
    # Fixed historic dates keep the ongoing-week streak at zero.
    assert body["current_week_streak"] == 0


def test_active_workouts_never_contribute(alice: TestClient) -> None:
    created = alice.post(
        WORKOUTS_URL, json={"id": str(uuid.uuid4()), "started_at": "2026-01-15T08:00:00Z"}
    )
    assert created.status_code == 201
    workout_id = str(created.json()["id"])
    saved = alice.put(
        f"{WORKOUTS_URL}/{workout_id}",
        json=save_body(
            exercises=[
                {
                    "id": uid(1),
                    "catalog_id": "bench-press",
                    "notes": None,
                    "sets": [set_body(uid(2))],
                }
            ],
        ),
    )
    assert saved.status_code == 200
    body = get_summary(alice)
    assert body["workout_count"] == 0
    assert body["completed_set_count"] == 0
    assert body["total_volume_kg_reps"] == 0
    assert body["volume_complete"] is True


def test_unknown_volume_reports_null_total_and_incomplete_flag(alice: TestClient) -> None:
    # A completed pure-bodyweight set without a recorded bodyweight is
    # eligible but has unknown volume.
    finish_session(
        alice,
        started_at="2026-01-15T08:00:00Z",
        ended_at="2026-01-15T09:00:00Z",
        catalog_id="push-up",
        sets=[set_body(uid(301), reps=10, weight_kg=None)],
    )
    body = get_summary(alice)
    assert body["workout_count"] == 1
    assert body["completed_set_count"] == 1
    assert body["total_volume_kg_reps"] is None
    assert body["unknown_load_set_count"] == 1
    assert body["volume_complete"] is False
    assert frequencies(body)["chest"] == 1


# --- date filters ------------------------------------------------------------------


def test_date_filters_select_inclusive_local_dates(alice: TestClient) -> None:
    finish_session(
        alice,
        started_at="2026-01-10T08:00:00Z",
        ended_at="2026-01-10T09:00:00Z",
        exercise_id=1,
    )
    finish_session(
        alice,
        started_at="2026-01-20T08:00:00Z",
        ended_at="2026-01-20T09:00:00Z",
        exercise_id=2,
    )
    assert get_summary(alice, date_from="2026-01-15")["workout_count"] == 1
    assert get_summary(alice, date_to="2026-01-15")["workout_count"] == 1
    assert get_summary(alice, date_from="2026-01-10", date_to="2026-01-10")["workout_count"] == 1
    assert get_summary(alice, date_from="2026-01-10", date_to="2026-01-20")["workout_count"] == 2


def test_utc_offset_moves_the_local_day_grouping(alice: TestClient) -> None:
    # 22:30 UTC is already the next local day at UTC+3.
    finish_session(
        alice,
        started_at="2026-01-10T22:30:00Z",
        ended_at="2026-01-10T23:30:00Z",
    )
    assert get_summary(alice, date_from="2026-01-10", date_to="2026-01-10")["workout_count"] == 1
    patched = alice.patch(ME_URL, json={"utc_offset_minutes": 180})
    assert patched.status_code == 200
    assert get_summary(alice, date_from="2026-01-11", date_to="2026-01-11")["workout_count"] == 1
    assert get_summary(alice, date_from="2026-01-10", date_to="2026-01-10")["workout_count"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "not-a-date"},
        {"date_from": "2026-02-30"},  # impossible calendar day
        {"date_from": "2026-01-01T00:00:00Z"},  # instants are not dates
        {"date_from": "1899-12-31"},  # below the shared supported minimum
        {"date_to": "9999-01-01"},  # above the shared supported maximum
    ],
)
def test_invalid_dates_share_the_history_parser_rejections(
    alice: TestClient, params: dict[str, str]
) -> None:
    response = alice.get(SUMMARY_URL, params=params)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert response.headers["content-type"] == "application/problem+json"


def test_reversed_range_returns_an_empty_summary(alice: TestClient) -> None:
    finish_session(
        alice,
        started_at="2026-01-10T08:00:00Z",
        ended_at="2026-01-10T09:00:00Z",
    )
    body = get_summary(alice, date_from="2026-01-20", date_to="2026-01-10")
    assert body["workout_count"] == 0
    assert body["completed_set_count"] == 0
    assert body["total_volume_kg_reps"] == 0
    assert body["volume_complete"] is True


# --- streaks -------------------------------------------------------------------------


def test_a_recent_finished_workout_keeps_a_week_streak(
    alice: TestClient, migrated_db: Path
) -> None:
    now = datetime.now(UTC)
    started = to_timestamp(now - timedelta(hours=1))
    ended = to_timestamp(now - timedelta(minutes=30))
    with connect(migrated_db) as conn:
        row = conn.execute("SELECT id FROM users WHERE email = 'alice@example.com'").fetchone()
    assert row is not None
    seed_finished_workout(
        migrated_db,
        str(row["id"]),
        str(uuid.uuid4()),
        started_at=started,
        ended_at=ended,
    )
    body = get_summary(alice)
    assert body["workout_count"] == 1
    # The workout is in the current local week or the immediately previous
    # one, so the ongoing-week rule always counts exactly that single week.
    assert body["current_week_streak"] == 1


# --- isolation and range safety --------------------------------------------------------


def test_other_users_workouts_never_contribute(
    alice_and_bob: tuple[TestClient, TestClient],
) -> None:
    alice, bob = alice_and_bob
    finish_session(
        bob,
        started_at="2026-01-15T08:00:00Z",
        ended_at="2026-01-15T09:00:00Z",
    )
    body = get_summary(alice)
    assert body["workout_count"] == 0
    assert body["total_volume_kg_reps"] == 0
    assert frequencies(body) == dict.fromkeys(MUSCLE_GROUP_ORDER, 0)
    assert get_summary(bob)["workout_count"] == 1


def test_unsafe_aggregate_is_an_explicit_problem_response(
    alice: TestClient, migrated_db: Path
) -> None:
    row = None
    with connect(migrated_db) as conn:
        row = conn.execute("SELECT id FROM users WHERE email = 'alice@example.com'").fetchone()
    assert row is not None
    workout_id = str(uuid.uuid4())
    # Two sets whose individual volumes equal the safe maximum; only their
    # sum exceeds it. The save protocol cannot create these rows (write
    # validation bounds derived values), so they are seeded directly.
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_workout(
            conn,
            workout_id,
            user_id=str(row["id"]),
            started_at="2026-01-15T08:00:00Z",
            ended_at="2026-01-15T09:00:00Z",
        )
        insert_exercise(
            conn,
            f"{workout_id}-e0",
            workout_id=workout_id,
            catalog_id="bench-press",
            load_type="single_weight",
            side_count=1,
        )
        for index in range(2):
            insert_set(
                conn,
                f"{workout_id}-s{index}",
                exercise_id=f"{workout_id}-e0",
                set_index=index,
                reps=1,
                weight_kg=MAX_SAFE_INTEGER,
                done=1,
            )
    response = alice.get(SUMMARY_URL)
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "stats_range_exceeded"
    assert response.headers["content-type"] == "application/problem+json"


# --- OpenAPI ---------------------------------------------------------------------------


def test_openapi_describes_the_summary_contract(alice: TestClient) -> None:
    spec = alice.get("/openapi.json").json()
    components = spec["components"]["schemas"]
    for name in ("StatsSummaryResponse", "MuscleGroupFrequencyResponse"):
        assert components[name]["additionalProperties"] is False
    summary_props = components["StatsSummaryResponse"]["properties"]
    assert set(summary_props) == SUMMARY_FIELDS
    assert set(components["StatsSummaryResponse"]["required"]) == SUMMARY_FIELDS
    # The total is a nullable integer, never a float.
    assert summary_props["total_volume_kg_reps"]["anyOf"] == [
        {"type": "integer", "minimum": 0, "maximum": MAX_SAFE_INTEGER},
        {"type": "null"},
    ]
    assert summary_props["volume_complete"]["type"] == "boolean"
    frequency = summary_props["muscle_group_frequency"]
    assert frequency["minItems"] == 8
    assert frequency["maxItems"] == 8
    assert components["MuscleGroupFrequencyResponse"]["properties"]["muscle_group"]["enum"] == [
        "chest",
        "back",
        "legs",
        "shoulders",
        "arms",
        "core",
        "full_body",
        "other",
    ]
    operation = spec["paths"][SUMMARY_URL]["get"]
    assert "stats" in operation["tags"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/StatsSummaryResponse"
    }
