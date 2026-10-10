"""Stage 5 workout API tests (Gate G5).

Covers authentication, create/retry idempotency with the canonical
fingerprint, create conflicts (different content, cross-user id reuse without
leaks), input normalization and strict rejection of malformed or
server-controlled fields, history listing (owner scoping, status and local-date
filters through the profile UTC offset, stable newest-first paging), the
full-graph detail read with recorded load inputs and the saved receipt, the
bodyweight snapshot surviving profile edits, and the shared problem+json,
request-id, and CSRF conventions.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import insert_exercise, insert_set, insert_workout

from app.db import connect, write_transaction

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
WORKOUTS_URL = "/api/v1/workouts"

STARTED_AT = "2026-01-01T08:00:00Z"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

DETAIL_FIELDS = {
    "id",
    "name",
    "started_at",
    "ended_at",
    "notes",
    "bodyweight_kg",
    "revision",
    "last_save_id",
    "session_type",
    "source_plan_id",
    "exercises",
}
SUMMARY_FIELDS = {
    "id",
    "name",
    "started_at",
    "ended_at",
    "bodyweight_kg",
    "revision",
    "session_type",
    "source_plan_id",
}
PROBLEM_FIELDS = {"type", "title", "status", "detail", "code", "request_id"}


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


def create_payload(**overrides: object) -> dict:
    payload: dict = {"id": str(uuid.uuid4()), "started_at": STARTED_AT}
    payload.update(overrides)
    return payload


def create_workout(client: TestClient, **overrides: object):
    return client.post(WORKOUTS_URL, json=create_payload(**overrides))


def update_profile(client: TestClient, **fields: object):
    return client.patch("/api/v1/auth/me", json=fields)


def finish_workout(database_path: Path, workout_id: str, ended_at: str) -> None:
    """Seed a finished workout directly for the read-side history filters.

    These Stage 5 list tests exercise status/date filtering, not the save
    protocol, so they set `ended_at` directly rather than going through the
    (now available) `PUT /workouts/{id}` finish path covered in Stage 6c.
    """
    with connect(database_path) as conn, write_transaction(conn):
        conn.execute(
            "UPDATE workouts SET ended_at = :ended_at WHERE id = :id",
            {"ended_at": ended_at, "id": workout_id},
        )


@contextmanager
def two_users(make_app) -> Iterator[tuple[TestClient, TestClient, str, str]]:
    """Two authenticated clients on one app: (alice, bob, alice_id, bob_id)."""
    app: FastAPI = make_app()
    with (
        TestClient(app, headers={"Origin": ORIGIN}) as alice,
        TestClient(app, headers={"Origin": ORIGIN}) as bob,
    ):
        alice_id = register_and_login(alice, email="alice@example.com")
        bob_id = register_and_login(bob, email="bob@example.com")
        yield alice, bob, alice_id, bob_id


# --- authentication -----------------------------------------------------------


def test_all_endpoints_require_authentication(api_client: TestClient) -> None:
    responses = [
        api_client.get(WORKOUTS_URL),
        api_client.get(f"{WORKOUTS_URL}/{uuid.uuid4()}"),
        api_client.post(WORKOUTS_URL, json=create_payload()),
    ]
    for response in responses:
        assert response.status_code == 401
        assert problem(response)["code"] == "unauthorized"


# --- create -------------------------------------------------------------------


def test_create_returns_authoritative_detail(api_client: TestClient) -> None:
    register_and_login(api_client)
    assert update_profile(api_client, bodyweight_default_kg=80).status_code == 200
    payload = create_payload()
    response = api_client.post(WORKOUTS_URL, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["id"] == payload["id"]
    assert UUID_RE.fullmatch(body["id"])
    assert body["name"] == "Workout on 2026-01-01"
    assert body["started_at"] == STARTED_AT
    assert body["ended_at"] is None  # active
    assert body["notes"] is None
    # The profile default is recorded as a snapshot input (PLAN.md §4).
    assert body["bodyweight_kg"] == 80
    assert body["revision"] == 0
    assert body["last_save_id"] is None
    assert body["session_type"] == "freestyle"
    assert body["source_plan_id"] is None
    assert body["exercises"] == []


def test_create_names_the_workout_for_the_profile_local_date(api_client: TestClient) -> None:
    register_and_login(api_client)
    assert update_profile(api_client, utc_offset_minutes=60).status_code == 200

    response = create_workout(api_client, started_at="2026-01-01T23:30:00Z")

    assert response.status_code == 201
    assert response.json()["name"] == "Workout on 2026-01-02"


def test_create_records_null_bodyweight_when_profile_unknown(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    response = create_workout(api_client)
    assert response.status_code == 201
    assert response.json()["bodyweight_kg"] is None


def test_create_retry_returns_existing_workout(api_client: TestClient) -> None:
    register_and_login(api_client)
    payload = create_payload()
    first = api_client.post(WORKOUTS_URL, json=payload)
    assert first.status_code == 201
    retry = api_client.post(WORKOUTS_URL, json=payload)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    listing = api_client.get(WORKOUTS_URL).json()
    assert listing["total"] == 1


def test_create_retry_matches_after_input_normalization(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = str(uuid.uuid4())
    first = api_client.post(
        WORKOUTS_URL,
        json=create_payload(id=workout_id.upper(), started_at="2026-01-01T11:00:00+03:00"),
    )
    assert first.status_code == 201
    assert first.json()["id"] == workout_id
    assert first.json()["started_at"] == STARTED_AT
    # The fingerprint covers the normalized values, so a differently spelled
    # retry of the same logical request is still the same create.
    retry = api_client.post(WORKOUTS_URL, json=create_payload(id=workout_id, started_at=STARTED_AT))
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert api_client.get(WORKOUTS_URL).json()["total"] == 1


def test_create_accepts_canonical_early_year(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = create_workout(api_client, started_at="0999-01-01T00:00:00Z")
    assert response.status_code == 201
    assert response.json()["started_at"] == "0999-01-01T00:00:00Z"


def test_create_conflict_on_same_id_different_content(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = str(uuid.uuid4())
    assert create_workout(api_client, id=workout_id).status_code == 201
    response = create_workout(api_client, id=workout_id, started_at="2026-02-02T00:00:00Z")
    assert response.status_code == 409
    assert problem(response)["code"] == "create_conflict"
    # The stored workout is untouched.
    stored = api_client.get(f"{WORKOUTS_URL}/{workout_id}").json()
    assert stored["started_at"] == STARTED_AT
    assert stored["revision"] == 0
    assert api_client.get(WORKOUTS_URL).json()["total"] == 1


def test_create_cross_user_id_reuse_conflicts_without_leaks(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        payload = create_payload()
        assert alice.post(WORKOUTS_URL, json=payload).status_code == 201
        # Identical content, different owner: conflict, never the stored row.
        response = bob.post(WORKOUTS_URL, json=payload)
        assert response.status_code == 409
        body = problem(response)
        assert body["code"] == "create_conflict"
        assert set(body) == PROBLEM_FIELDS
        assert bob.get(WORKOUTS_URL).json()["total"] == 0
        assert bob.get(f"{WORKOUTS_URL}/{payload['id']}").status_code == 404
        assert alice.get(f"{WORKOUTS_URL}/{payload['id']}").status_code == 200


def test_create_rejects_server_controlled_fields(api_client: TestClient) -> None:
    register_and_login(api_client)
    for field, value in [
        ("revision", 5),
        ("bodyweight_kg", 80),
        ("name", "Leg day"),
        ("notes", "felt strong"),
        ("ended_at", "2026-01-01T09:00:00Z"),
        ("last_save_id", str(uuid.uuid4())),
        ("user_id", "someone-else"),
    ]:
        response = create_workout(api_client, **{field: value})
        assert response.status_code == 422, field
        assert problem(response)["code"] == "validation_error"


def test_create_rejects_malformed_inputs(api_client: TestClient) -> None:
    register_and_login(api_client)
    payloads = [
        {"id": "not-a-uuid", "started_at": STARTED_AT},
        {"id": 123, "started_at": STARTED_AT},
        {"id": str(uuid.uuid4()), "started_at": "2026-01-01T08:00:00"},  # naive
        {"id": str(uuid.uuid4()), "started_at": "2026-01-01"},  # date only
        {"id": str(uuid.uuid4()), "started_at": "yesterday"},
        {"id": str(uuid.uuid4()), "started_at": "0001-01-01T00:00:00+14:00"},
        {"id": str(uuid.uuid4()), "started_at": "9999-12-31T23:59:59-12:00"},
        {"id": str(uuid.uuid4()), "started_at": 1767225600},  # numeric
        {"id": str(uuid.uuid4())},  # missing started_at
        {"started_at": STARTED_AT},  # missing id
        {},
    ]
    for payload in payloads:
        response = api_client.post(WORKOUTS_URL, json=payload)
        assert response.status_code == 422, payload
        assert problem(response)["code"] == "validation_error"


# --- detail read --------------------------------------------------------------


def seed_graph(database_path: Path, user_id: str) -> str:
    """A finished-looking graph with snapshots, sides, and a stored receipt."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(
            conn,
            "w-graph",
            user_id=user_id,
            started_at=STARTED_AT,
            bodyweight_kg=75,
            revision=2,
            last_save_id="save-1",
            last_save_hash="hash-1",
        )
        insert_exercise(
            conn,
            "e-1",
            workout_id="w-graph",
            catalog_id="dumbbell-curl",
            order_index=0,
            load_type="split_weight",
            bodyweight_percent=None,
            side_count=2,
        )
        insert_exercise(
            conn,
            "e-2",
            workout_id="w-graph",
            catalog_id="pull-up",
            order_index=1,
            load_type="bodyweight",
            bodyweight_percent=100,
            side_count=1,
        )
        insert_set(conn, "s-1", exercise_id="e-1", set_index=0, reps=None, weight_kg=None, done=0)
        insert_set(conn, "s-2", exercise_id="e-1", set_index=1, reps=10, weight_kg=12, rpe=8)
        insert_set(
            conn,
            "s-3",
            exercise_id="e-2",
            set_index=0,
            reps=6,
            weight_kg=None,
            bw_percent_override=90,
            side="left",
        )
    return "w-graph"


def test_get_detail_returns_full_graph(api_client: TestClient, migrated_db: Path) -> None:
    user_id = register_and_login(api_client)
    workout_id = seed_graph(migrated_db, user_id)
    response = api_client.get(f"{WORKOUTS_URL}/{workout_id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": "w-graph",
        "name": None,
        "started_at": STARTED_AT,
        "ended_at": None,
        "notes": None,
        "bodyweight_kg": 75,
        "revision": 2,
        "last_save_id": "save-1",
        "session_type": None,
        "source_plan_id": None,
        "exercises": [
            {
                "id": "e-1",
                "catalog_id": "dumbbell-curl",
                "order_index": 0,
                "notes": None,
                "load_type": "split_weight",
                "bodyweight_percent": None,
                "side_count": 2,
                "sets": [
                    {
                        "id": "s-1",
                        "set_index": 0,
                        "reps": None,
                        "weight_kg": None,
                        "bw_percent_override": None,
                        "rpe": None,
                        "side": "bilateral",
                        "done": False,
                    },
                    {
                        "id": "s-2",
                        "set_index": 1,
                        "reps": 10,
                        "weight_kg": 12,
                        "bw_percent_override": None,
                        "rpe": 8,
                        "side": "bilateral",
                        "done": True,
                    },
                ],
                # No eligible earlier session exists for this graph.
                "previous_performance": None,
            },
            {
                "id": "e-2",
                "catalog_id": "pull-up",
                "order_index": 1,
                "notes": None,
                "load_type": "bodyweight",
                "bodyweight_percent": 100,
                "side_count": 1,
                "sets": [
                    {
                        "id": "s-3",
                        "set_index": 0,
                        "reps": 6,
                        "weight_kg": None,
                        "bw_percent_override": 90,
                        "rpe": None,
                        "side": "left",
                        "done": True,
                    },
                ],
                "previous_performance": None,
            },
        ],
    }
    # The internal hashes never reach the public shape.
    assert "last_save_hash" not in response.text
    assert "create_request_hash" not in response.text
    assert "hash-1" not in response.text


def test_get_detail_foreign_or_unknown_404(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        workout_id = create_workout(alice).json()["id"]
        foreign = bob.get(f"{WORKOUTS_URL}/{workout_id}")
        assert foreign.status_code == 404
        assert problem(foreign)["code"] == "not_found"
        unknown = alice.get(f"{WORKOUTS_URL}/{uuid.uuid4()}")
        assert unknown.status_code == 404
        assert alice.get(f"{WORKOUTS_URL}/{workout_id}").status_code == 200


# --- history listing ------------------------------------------------------------


def seed_listing(client: TestClient, database_path: Path) -> list[str]:
    """Three own workouts (one finished) plus one foreign; returns own ids."""
    user_id = str(client.get("/api/v1/auth/me").json()["id"])
    ids = [str(uuid.uuid4()) for _ in range(3)]
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(conn, ids[0], user_id=user_id, started_at="2026-01-01T08:00:00Z")
        insert_workout(
            conn,
            ids[1],
            user_id=user_id,
            started_at="2026-01-02T08:00:00Z",
            ended_at="2026-01-02T09:30:00Z",
        )
        insert_workout(conn, ids[2], user_id=user_id, started_at="2026-01-03T22:00:00Z")
    return ids


def test_list_returns_own_summaries_newest_first(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    ids = seed_listing(api_client, migrated_db)
    response = api_client.get(WORKOUTS_URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert [item["id"] for item in body["items"]] == list(reversed(ids))
    for item in body["items"]:
        assert set(item) == SUMMARY_FIELDS
    finished_flags = [item["ended_at"] is not None for item in body["items"]]
    assert finished_flags == [False, True, False]


def test_list_status_filter(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    ids = seed_listing(api_client, migrated_db)
    active = api_client.get(WORKOUTS_URL, params={"status": "active"}).json()
    assert [item["id"] for item in active["items"]] == [ids[2], ids[0]]
    assert active["total"] == 2
    finished = api_client.get(WORKOUTS_URL, params={"status": "finished"}).json()
    assert [item["id"] for item in finished["items"]] == [ids[1]]


def test_list_date_filters_are_inclusive_local_days(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    ids = seed_listing(api_client, migrated_db)
    single = api_client.get(
        WORKOUTS_URL, params={"date_from": "2026-01-02", "date_to": "2026-01-02"}
    ).json()
    assert [item["id"] for item in single["items"]] == [ids[1]]
    ranged = api_client.get(WORKOUTS_URL, params={"date_from": "2026-01-02"}).json()
    assert [item["id"] for item in ranged["items"]] == [ids[2], ids[1]]


def test_list_date_filters_follow_the_profile_offset(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    ids = seed_listing(api_client, migrated_db)
    # At UTC+3 the 22:00Z workout is already the next local day.
    assert update_profile(api_client, utc_offset_minutes=180).status_code == 200
    shifted = api_client.get(WORKOUTS_URL, params={"date_from": "2026-01-04"}).json()
    assert [item["id"] for item in shifted["items"]] == [ids[2]]
    assert update_profile(api_client, utc_offset_minutes=0).status_code == 200
    unshifted = api_client.get(WORKOUTS_URL, params={"date_from": "2026-01-04"}).json()
    assert unshifted["items"] == []
    assert unshifted["total"] == 0


def test_list_is_owner_scoped(make_app, migrated_db: Path) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        alice_ids = seed_listing(alice, migrated_db)
        bob_list = bob.get(WORKOUTS_URL).json()
        assert bob_list["total"] == 0
        assert bob_list["items"] == []
        alice_list = alice.get(WORKOUTS_URL).json()
        assert sorted(item["id"] for item in alice_list["items"]) == sorted(alice_ids)


def test_list_pagination_is_stable(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    ids = seed_listing(api_client, migrated_db)
    first = api_client.get(WORKOUTS_URL, params={"pageSize": 2, "page": 1}).json()
    second = api_client.get(WORKOUTS_URL, params={"pageSize": 2, "page": 2}).json()
    assert first["total"] == second["total"] == 3
    assert first["page"] == 1
    assert second["page"] == 2
    assert [item["id"] for item in first["items"]] == [ids[2], ids[1]]
    assert [item["id"] for item in second["items"]] == [ids[0]]
    beyond = api_client.get(WORKOUTS_URL, params={"pageSize": 2, "page": 3}).json()
    assert beyond["items"] == []
    assert beyond["total"] == 3


def test_list_rejects_invalid_params(api_client: TestClient) -> None:
    register_and_login(api_client)
    params: list[dict[str, Any]] = [
        {"page": 0},
        {"page": -1},
        {"pageSize": 0},
        {"pageSize": 101},
        {"status": "bogus"},
        {"date_from": "not-a-date"},
        {"date_from": "2026-02-30"},  # impossible calendar day
        {"date_from": "2026-01-01T08:00:00Z"},  # non-midnight times are not dates
        {"date_from": "2026-01-01T00:00:00Z"},  # midnight is still not a calendar date
        {"date_from": "1767225600"},  # Unix seconds are instants, not calendar dates
        {"date_from": "1767225600000"},  # nor are Unix milliseconds
        {"date_from": "1899-12-31"},  # below the bounded range
        {"date_to": "9999-12-31"},  # above the bounded range
    ]
    for query in params:
        response = api_client.get(WORKOUTS_URL, params=query)
        assert response.status_code == 422, query
        assert problem(response)["code"] == "validation_error"


# --- recorded snapshots ---------------------------------------------------------


def test_recorded_bodyweight_survives_profile_edits(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    assert update_profile(api_client, bodyweight_default_kg=80).status_code == 200
    workout_id = create_workout(api_client).json()["id"]
    assert update_profile(api_client, bodyweight_default_kg=95).status_code == 200
    # The recorded snapshot is unchanged; new workouts record the new default.
    assert api_client.get(f"{WORKOUTS_URL}/{workout_id}").json()["bodyweight_kg"] == 80
    finish_workout(migrated_db, workout_id, "2026-01-01T09:00:00Z")
    new_id = create_workout(api_client).json()["id"]
    assert api_client.get(f"{WORKOUTS_URL}/{new_id}").json()["bodyweight_kg"] == 95
    listing = api_client.get(WORKOUTS_URL).json()
    by_id = {item["id"]: item for item in listing["items"]}
    assert by_id[workout_id]["bodyweight_kg"] == 80
    assert by_id[new_id]["bodyweight_kg"] == 95


def test_profile_bodyweight_cleared_after_create_keeps_snapshot(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    assert update_profile(api_client, bodyweight_default_kg=80).status_code == 200
    workout_id = create_workout(api_client).json()["id"]
    assert update_profile(api_client, bodyweight_default_kg=None).status_code == 200
    finish_workout(migrated_db, workout_id, "2026-01-01T09:00:00Z")
    assert create_workout(api_client).json()["bodyweight_kg"] is None
    assert api_client.get(f"{WORKOUTS_URL}/{workout_id}").json()["bodyweight_kg"] == 80


# --- shared conventions ---------------------------------------------------------


def test_post_follows_csrf_and_json_conventions(make_app) -> None:
    app = make_app()
    with TestClient(app) as client:  # no Origin header at all
        missing_origin = client.post(WORKOUTS_URL, json=create_payload())
        assert missing_origin.status_code == 403
        assert problem(missing_origin)["code"] == "origin_not_allowed"
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        register_and_login(client)
        response = client.post(
            WORKOUTS_URL,
            content=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 415
        assert problem(response)["code"] == "json_required"


def test_responses_carry_request_ids(api_client: TestClient) -> None:
    register_and_login(api_client)
    created = create_workout(api_client)
    assert re.fullmatch(r"[0-9a-f]{32}", created.headers["X-Request-ID"])
    fetched = api_client.get(f"{WORKOUTS_URL}/{created.json()['id']}")
    assert re.fullmatch(r"[0-9a-f]{32}", fetched.headers["X-Request-ID"])
    missing = api_client.get(f"{WORKOUTS_URL}/{uuid.uuid4()}")
    body = problem(missing)
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
