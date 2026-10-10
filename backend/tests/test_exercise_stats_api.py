"""Per-exercise statistics API tests (exercise information screen, Gate A).

Covers eligibility (finished workouts and completed sets only), repeated
occurrence aggregation, the latest-12 selection with its `(started_at, id)`
tie-break and oldest-to-newest emission, the shared volume null/partial/zero
completeness semantics at lifetime and session level, estimated-1RM reuse of
the existing server arithmetic and eligibility rules, snapshot stability
against later catalog/profile edits, explicit aggregate-overflow failure, and
the established 404 privacy behavior for foreign and unknown ids.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import insert_exercise, insert_set, insert_user, insert_workout

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER, estimated_one_rep_max

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
EXERCISES_URL = "/api/v1/exercises"

STATS_FIELDS = {
    "training_count",
    "completed_set_count",
    "total_volume_kg_reps",
    "unknown_load_set_count",
    "volume_complete",
    "best_estimated_1rm_kg",
    "sessions",
}
SESSION_FIELDS = {
    "workout_id",
    "started_at",
    "completed_set_count",
    "volume_kg_reps",
    "unknown_load_set_count",
    "volume_complete",
}


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
    return body


def get_stats(client: TestClient, catalog_id: str) -> dict:
    response = client.get(f"{EXERCISES_URL}/{catalog_id}/stats")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATS_FIELDS
    for session in body["sessions"]:
        assert set(session) == SESSION_FIELDS
    return body


def finish_workout(
    database_path: Path,
    *,
    user_id: str,
    workout_id: str,
    started_at: str,
    ended_at: str,
    bodyweight_kg: int | None,
    catalog_id: str = "bench-press",
    sets: list[tuple[int | None, int | None, int]],
    load_type: str = "single_weight",
    bodyweight_percent: int | None = None,
    side_count: int = 1,
    extra_exercise: bool = False,
    extra_sets: list[tuple[int | None, int | None, int]] | None = None,
    active: bool = False,
) -> None:
    """One workout with a finished (or active) lifecycle and completed sets.

    `sets` entries are `(reps, weight_kg, done)`; a repeated occurrence of the
    same catalog exercise can be added through `extra_exercise`/`extra_sets`.
    """
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(
            conn,
            workout_id,
            user_id=user_id,
            started_at=started_at,
            ended_at=None if active else ended_at,
            bodyweight_kg=bodyweight_kg,
            create_request_hash=f"create-{workout_id}",
        )
        insert_exercise(
            conn,
            f"{workout_id}-exercise-1",
            workout_id=workout_id,
            catalog_id=catalog_id,
            order_index=0,
            load_type=load_type,
            bodyweight_percent=bodyweight_percent,
            side_count=side_count,
        )
        for index, (reps, weight, done) in enumerate(sets):
            insert_set(
                conn,
                f"{workout_id}-set-{index}",
                exercise_id=f"{workout_id}-exercise-1",
                set_index=index,
                reps=reps,
                weight_kg=weight,
                done=done,
            )
        if extra_exercise:
            insert_exercise(
                conn,
                f"{workout_id}-exercise-2",
                workout_id=workout_id,
                catalog_id=catalog_id,
                order_index=1,
                load_type=load_type,
                bodyweight_percent=bodyweight_percent,
                side_count=side_count,
            )
            for index, (reps, weight, done) in enumerate(extra_sets or []):
                insert_set(
                    conn,
                    f"{workout_id}-set-extra-{index}",
                    exercise_id=f"{workout_id}-exercise-2",
                    set_index=index,
                    reps=reps,
                    weight_kg=weight,
                    done=done,
                )


def day(number: int) -> str:
    return f"2026-01-{number:02d}T10:00:00Z"


@pytest.fixture()
def signed_in(api_client: TestClient, migrated_db: Path) -> tuple[TestClient, str, Path]:
    user_id = register_and_login(api_client)
    return api_client, user_id, migrated_db


def test_empty_history_returns_known_zeros(signed_in) -> None:
    client, _, _ = signed_in
    body = get_stats(client, "bench-press")
    assert body == {
        "training_count": 0,
        "completed_set_count": 0,
        "total_volume_kg_reps": 0,
        "unknown_load_set_count": 0,
        "volume_complete": True,
        "best_estimated_1rm_kg": None,
        "sessions": [],
    }


def test_active_workouts_and_incomplete_sets_do_not_contribute(signed_in) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="active-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[(8, 50, 1)],
        active=True,
    )
    finish_workout(
        database,
        user_id=user_id,
        workout_id="finished-1",
        started_at=day(2),
        ended_at=day(2),
        bodyweight_kg=80,
        sets=[(8, 50, 1), (None, None, 0)],
    )
    body = get_stats(client, "bench-press")
    assert body["training_count"] == 1
    assert body["completed_set_count"] == 1
    assert body["total_volume_kg_reps"] == 8 * 50
    assert [session["workout_id"] for session in body["sessions"]] == ["finished-1"]


def test_repeated_occurrences_aggregate_into_one_session(signed_in) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[(5, 20, 1)],
        extra_exercise=True,
        extra_sets=[(5, 30, 1)],
    )
    body = get_stats(client, "bench-press")
    assert body["training_count"] == 1
    assert body["completed_set_count"] == 2
    assert body["total_volume_kg_reps"] == 5 * 20 + 5 * 30
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["workout_id"] == "w-1"
    assert session["completed_set_count"] == 2
    assert session["volume_kg_reps"] == 250
    assert session["volume_complete"] is True
    assert session["unknown_load_set_count"] == 0


def test_latest_twelve_selection_and_order(signed_in) -> None:
    client, user_id, database = signed_in
    for number in range(1, 15):
        finish_workout(
            database,
            user_id=user_id,
            workout_id=f"w-{number:02d}",
            started_at=day(number),
            ended_at=day(number),
            bodyweight_kg=80,
            sets=[(5, number, 1)],
        )
    body = get_stats(client, "bench-press")
    # Lifetime totals cover the full history...
    assert body["training_count"] == 14
    assert body["completed_set_count"] == 14
    # ...while the series carries exactly the latest 12, oldest-to-newest.
    assert [session["workout_id"] for session in body["sessions"]] == [
        f"w-{number:02d}" for number in range(3, 15)
    ]
    assert [session["started_at"] for session in body["sessions"]] == [
        day(number) for number in range(3, 15)
    ]


def test_series_tie_break_is_deterministic_by_id(signed_in) -> None:
    client, user_id, database = signed_in
    # Thirteen workouts share one start instant; the (started_at DESC, id
    # DESC) order drops the smallest id and emits the rest ascending.
    for number in range(1, 14):
        finish_workout(
            database,
            user_id=user_id,
            workout_id=f"w-{number:02d}",
            started_at=day(1),
            ended_at=day(1),
            bodyweight_kg=80,
            sets=[(5, 10, 1)],
        )
    body = get_stats(client, "bench-press")
    assert body["training_count"] == 13
    assert [session["workout_id"] for session in body["sessions"]] == [
        f"w-{number:02d}" for number in range(2, 14)
    ]


def test_volume_completeness_semantics(signed_in) -> None:
    client, user_id, database = signed_in
    # Known zero: a completed set with zero external load is a known volume.
    finish_workout(
        database,
        user_id=user_id,
        workout_id="zero-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[(5, 0, 1)],
    )
    body = get_stats(client, "bench-press")
    assert body["total_volume_kg_reps"] == 0
    assert body["volume_complete"] is True
    assert body["sessions"][0]["volume_kg_reps"] == 0
    assert body["sessions"][0]["volume_complete"] is True


def test_partial_and_unknown_volume(signed_in) -> None:
    client, user_id, database = signed_in
    # Bodyweight sets of a workout without a recorded bodyweight are unknown.
    finish_workout(
        database,
        user_id=user_id,
        workout_id="partial-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=None,
        catalog_id="push-up",
        load_type="bodyweight",
        bodyweight_percent=65,
        sets=[(10, None, 1)],
    )
    finish_workout(
        database,
        user_id=user_id,
        workout_id="unknown-1",
        started_at=day(2),
        ended_at=day(2),
        bodyweight_kg=None,
        catalog_id="push-up",
        load_type="bodyweight",
        bodyweight_percent=65,
        sets=[(8, None, 1), (6, None, 1)],
    )
    body = get_stats(client, "push-up")
    # All eligible loads unknown: volume null, never zero.
    assert body["total_volume_kg_reps"] is None
    assert body["volume_complete"] is False
    assert body["unknown_load_set_count"] == 3
    for session in body["sessions"]:
        assert session["volume_kg_reps"] is None
        assert session["volume_complete"] is False


def test_partial_sum_is_known_with_positive_unknown_count(signed_in) -> None:
    client, user_id, database = signed_in
    # A single-weight snapshot with a bodyweight percentage: workout A records
    # a bodyweight (known load) while workout B does not (unknown load), so
    # the lifetime total is the known partial sum with completeness false.
    with connect(database) as conn, write_transaction(conn):
        conn.execute(
            "INSERT INTO exercise_catalog (id, name, muscle_group, load_type, "
            "bodyweight_percent, side_count, is_default, created_by) "
            "VALUES ('cat-mixed', 'Mixed Load', 'legs', 'single_weight', "
            "50, 1, 0, :owner)",
            {"owner": user_id},
        )
    finish_workout(
        database,
        user_id=user_id,
        workout_id="known-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        catalog_id="cat-mixed",
        bodyweight_percent=50,
        sets=[(10, 20, 1)],
    )
    finish_workout(
        database,
        user_id=user_id,
        workout_id="unknown-2",
        started_at=day(2),
        ended_at=day(2),
        bodyweight_kg=None,
        catalog_id="cat-mixed",
        bodyweight_percent=50,
        sets=[(10, 20, 1)],
    )
    body = get_stats(client, "cat-mixed")
    assert body["total_volume_kg_reps"] == (20 + 80 * 50 // 100) * 10
    assert body["volume_complete"] is False
    assert body["unknown_load_set_count"] == 1
    known_session, unknown_session = body["sessions"]
    assert known_session["workout_id"] == "known-1"
    assert known_session["volume_kg_reps"] == 600
    assert known_session["volume_complete"] is True
    assert unknown_session["workout_id"] == "unknown-2"
    assert unknown_session["volume_kg_reps"] is None
    assert unknown_session["volume_complete"] is False


def test_estimated_1rm_reuses_existing_arithmetic(signed_in) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[
            (1, 100, 1),  # one rep uses the external load directly
            (8, 12, 1),  # 12 * (30 + 8) // 30 = 15 (floor)
            (11, 5, 1),  # above ten reps never contributes
        ],
    )
    body = get_stats(client, "bench-press")
    expected = max(
        value
        for value in (
            estimated_one_rep_max(
                external_load_kg=100, reps=1, load_type="single_weight", bodyweight_percent=None
            ),
            estimated_one_rep_max(
                external_load_kg=12, reps=8, load_type="single_weight", bodyweight_percent=None
            ),
            estimated_one_rep_max(
                external_load_kg=5, reps=11, load_type="single_weight", bodyweight_percent=None
            ),
        )
        if value is not None
    )
    assert body["best_estimated_1rm_kg"] == expected == 100


def test_estimated_1rm_uses_split_weight_side_multiplier(signed_in) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        catalog_id="dumbbell-curl",
        load_type="split_weight",
        side_count=2,
        sets=[(5, 12, 1)],
    )
    body = get_stats(client, "dumbbell-curl")
    # external = 12 * 2 = 24; 24 * (30 + 5) // 30 = 28.
    assert body["best_estimated_1rm_kg"] == 24 * 35 // 30 == 28
    assert body["total_volume_kg_reps"] == 5 * 24


def test_bodyweight_and_weighted_bodyweight_have_no_estimated_1rm(signed_in) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="bw-1",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        catalog_id="pull-up",
        load_type="bodyweight",
        bodyweight_percent=100,
        sets=[(8, None, 1)],
    )
    body = get_stats(client, "pull-up")
    assert body["best_estimated_1rm_kg"] is None
    assert body["total_volume_kg_reps"] == 8 * 80

    with connect(database) as conn, write_transaction(conn):
        conn.execute(
            "INSERT INTO exercise_catalog (id, name, muscle_group, load_type, "
            "bodyweight_percent, side_count, is_default, created_by) "
            "VALUES ('cat-weighted-bw', 'Weighted Dip X', 'arms', "
            "'single_weight', 30, 1, 0, :owner)",
            {"owner": user_id},
        )
    finish_workout(
        database,
        user_id=user_id,
        workout_id="wbw-1",
        started_at=day(2),
        ended_at=day(2),
        bodyweight_kg=80,
        catalog_id="cat-weighted-bw",
        bodyweight_percent=30,
        sets=[(5, 10, 1)],
    )
    weighted = get_stats(client, "cat-weighted-bw")
    assert weighted["best_estimated_1rm_kg"] is None
    assert weighted["total_volume_kg_reps"] == 5 * (10 + 80 * 30 // 100)


def test_set_override_uses_recorded_snapshot_inputs(signed_in) -> None:
    client, user_id, database = signed_in
    with connect(database) as conn, write_transaction(conn):
        conn.execute(
            "INSERT INTO exercise_catalog (id, name, muscle_group, load_type, "
            "bodyweight_percent, side_count, is_default, created_by) "
            "VALUES ('cat-override', 'Override Press', 'chest', "
            "'single_weight', 50, 1, 0, :owner)",
            {"owner": user_id},
        )
        insert_workout(
            conn,
            "w-override",
            user_id=user_id,
            started_at=day(1),
            ended_at=day(1),
            bodyweight_kg=80,
            create_request_hash="create-override",
        )
        insert_exercise(
            conn,
            "e-override",
            workout_id="w-override",
            catalog_id="cat-override",
            load_type="single_weight",
            bodyweight_percent=50,
            side_count=1,
        )
        insert_set(
            conn,
            "s-override",
            exercise_id="e-override",
            reps=10,
            weight_kg=20,
            bw_percent_override=25,
            done=1,
        )
    body = get_stats(client, "cat-override")
    # The set override replaces the snapshot percentage: 20 + 80*25//100 = 40.
    assert body["total_volume_kg_reps"] == 10 * 40


def test_history_survives_catalog_and_profile_edits(signed_in) -> None:
    client, user_id, database = signed_in
    entry = client.post(
        EXERCISES_URL,
        json={
            "name": "Snapshot Press",
            "muscle_group": "chest",
            "load_type": "single_weight",
            "bodyweight_percent": 50,
        },
    ).json()
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-snap",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        catalog_id=entry["id"],
        bodyweight_percent=50,
        sets=[(10, 20, 1)],
    )
    before = get_stats(client, entry["id"])
    assert before["total_volume_kg_reps"] == 10 * (20 + 80 * 50 // 100)

    # Edit the catalog entry's load settings and the profile bodyweight.
    patched = client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"bodyweight_percent": 90})
    assert patched.status_code == 200
    profile = client.patch("/api/v1/auth/me", json={"bodyweight_default_kg": 100})
    assert profile.status_code == 200

    after = get_stats(client, entry["id"])
    assert after["total_volume_kg_reps"] == before["total_volume_kg_reps"]


def test_aggregate_overflow_fails_explicitly(signed_in) -> None:
    client, user_id, database = signed_in
    for number in (1, 2):
        with connect(database) as conn, write_transaction(conn):
            insert_workout(
                conn,
                f"w-huge-{number}",
                user_id=user_id,
                started_at=day(number),
                ended_at=day(number),
                bodyweight_kg=80,
                create_request_hash=f"create-huge-{number}",
            )
            insert_exercise(
                conn,
                f"e-huge-{number}",
                workout_id=f"w-huge-{number}",
                catalog_id="bench-press",
                load_type="single_weight",
                side_count=1,
            )
            insert_set(
                conn,
                f"s-huge-{number}",
                exercise_id=f"e-huge-{number}",
                reps=1,
                weight_kg=MAX_SAFE_INTEGER,
                done=1,
            )
    response = client.get(f"{EXERCISES_URL}/bench-press/stats")
    assert response.status_code == 500
    assert problem(response)["code"] == "stats_range_exceeded"


def test_stats_are_owner_scoped(signed_in, make_app) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-owner",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[(8, 50, 1)],
    )
    body = get_stats(client, "bench-press")
    assert body["training_count"] == 1

    # Another account has empty statistics for the same default id and can
    # never see the first account's custom entry (404, not empty stats).
    app: FastAPI = make_app()
    with TestClient(app, headers={"Origin": ORIGIN}) as bob:
        register_and_login(bob, email="bob@example.com")
        bob_body = get_stats(bob, "bench-press")
        assert bob_body["training_count"] == 0
        assert bob_body["sessions"] == []

        with connect(database) as conn, write_transaction(conn):
            conn.execute(
                "INSERT INTO exercise_catalog (id, name, muscle_group, load_type, "
                "bodyweight_percent, side_count, is_default, created_by) "
                "VALUES ('cat-alice-only', 'Alice Only', 'arms', 'single_weight', "
                "NULL, 1, 0, :owner)",
                {"owner": user_id},
            )
        foreign = bob.get(f"{EXERCISES_URL}/cat-alice-only/stats")
        assert foreign.status_code == 404
        unknown = bob.get(f"{EXERCISES_URL}/no-such-entry/stats")
        assert unknown.status_code == 404
        assert problem(foreign)["code"] == problem(unknown)["code"] == "not_found"


def test_other_users_sets_do_not_count(signed_in, make_app) -> None:
    client, user_id, database = signed_in
    finish_workout(
        database,
        user_id=user_id,
        workout_id="w-alice",
        started_at=day(1),
        ended_at=day(1),
        bodyweight_kg=80,
        sets=[(8, 50, 1)],
    )
    with connect(database) as conn, write_transaction(conn):
        insert_user(conn, "user-bob", email="bob-direct@example.com")
    finish_workout(
        database,
        user_id="user-bob",
        workout_id="w-bob",
        started_at=day(2),
        ended_at=day(2),
        bodyweight_kg=90,
        sets=[(5, 100, 1)],
    )
    body = get_stats(client, "bench-press")
    assert body["training_count"] == 1
    assert body["total_volume_kg_reps"] == 8 * 50
    assert body["best_estimated_1rm_kg"] == 50 * 38 // 30
