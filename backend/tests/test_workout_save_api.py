"""Stage 6c public bulk-save API tests (Gate G6c).

`PUT /workouts/{id}` end-to-end coverage: authentication and CSRF/JSON
conventions; the authoritative 200 detail with its receipt; exact `save_id`
retries (no double increment, no duplicate rows, normalization-insensitive);
every stable failure shape (404 without revision, the four revision-bearing
409s, generic `graph_conflict`/`catalog_unavailable`, 422 field paths without
values, retryable 503); finish atomicity, boundaries, and the finished
read-only guard; no-op new saves; PUT-never-creates; snapshot/server-controlled
field rejection; reorder/add/remove through the public route; revision
exhaustion; and response-graph capture on the write connection before commit.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.workouts import SaveWorkoutRequest
from app.services import workouts
from app.services.workouts import save_request_hash

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
WORKOUTS_URL = "/api/v1/workouts"
EXERCISES_URL = "/api/v1/exercises"

STARTED_AT = "2026-01-01T08:00:00Z"
CATALOG = "bench-press"

DETAIL_FIELDS = {
    "id",
    "name",
    "started_at",
    "ended_at",
    "notes",
    "bodyweight_kg",
    "revision",
    "last_save_id",
    "exercises",
}
PROBLEM_FIELDS = {"type", "title", "status", "detail", "code", "request_id"}


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


EXERCISE_A = uid(1)
EXERCISE_B = uid(2)
EXERCISE_C = uid(3)
SET_A1 = uid(11)
SET_A2 = uid(12)
SET_B1 = uid(21)
SET_C1 = uid(31)
SET_NEW = uid(41)
SAVE_1 = uid(101)
SAVE_2 = uid(102)
SAVE_3 = uid(103)
SAVE_4 = uid(104)
SAVE_5 = uid(105)


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
    exercise_id: str,
    *,
    catalog_id: str = CATALOG,
    notes: str | None = None,
    sets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": exercise_id,
        "catalog_id": catalog_id,
        "notes": notes,
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


def problem(response) -> dict:
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == response.status_code
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body


def create(client: TestClient, started_at: str = STARTED_AT) -> str:
    response = client.post(WORKOUTS_URL, json={"id": str(uuid.uuid4()), "started_at": started_at})
    assert response.status_code == 201
    return str(response.json()["id"])


def put_save(client: TestClient, workout_id: str, body: dict[str, Any]):
    return client.put(f"{WORKOUTS_URL}/{workout_id}", json=body)


def get_detail(client: TestClient, workout_id: str) -> dict:
    response = client.get(f"{WORKOUTS_URL}/{workout_id}")
    assert response.status_code == 200
    return response.json()


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


class HookedConnection:
    """`sqlite3.Connection` proxy running a test hook around `execute` calls."""

    def __init__(self, conn: sqlite3.Connection, *, after: Callable[[str], None]) -> None:
        self._conn = conn
        self._after = after

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        result = self._conn.execute(statement, *args, **kwargs)
        self._after(statement)
        return result

    def __enter__(self) -> Any:
        return self._conn.__enter__()

    def __exit__(self, *exc_info: Any) -> Any:
        return self._conn.__exit__(*exc_info)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


# --- authentication and conventions --------------------------------------------


def test_put_requires_authentication(api_client: TestClient) -> None:
    response = put_save(api_client, str(uuid.uuid4()), save_body(save_id=SAVE_1))
    assert response.status_code == 401
    assert problem(response)["code"] == "unauthorized"


def test_put_follows_csrf_and_json_conventions(make_app) -> None:
    app = make_app()
    with TestClient(app) as client:  # no Origin header at all
        missing_origin = put_save(client, str(uuid.uuid4()), save_body(save_id=SAVE_1))
        assert missing_origin.status_code == 403
        assert problem(missing_origin)["code"] == "origin_not_allowed"
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        register_and_login(client)
        workout_id = create(client)
        response = client.put(
            f"{WORKOUTS_URL}/{workout_id}",
            content=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 415
        assert problem(response)["code"] == "json_required"


# --- accepted saves --------------------------------------------------------------


def test_save_returns_authoritative_detail_and_receipt(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    body = save_body(
        revision=0,
        save_id=SAVE_1,
        name="Push day",
        notes="felt strong",
        bodyweight_kg=82,
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1), set_body(SET_A2, reps=6)])],
    )
    response = put_save(api_client, workout_id, body)
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    detail = response.json()
    assert set(detail) == DETAIL_FIELDS
    assert detail["id"] == workout_id
    assert detail["revision"] == 1
    assert detail["last_save_id"] == SAVE_1
    assert detail["name"] == "Push day"
    assert detail["notes"] == "felt strong"
    assert detail["bodyweight_kg"] == 82
    assert detail["started_at"] == STARTED_AT
    assert detail["ended_at"] is None
    exercise = detail["exercises"][0]
    assert exercise["id"] == EXERCISE_A
    assert exercise["catalog_id"] == CATALOG
    assert exercise["order_index"] == 0
    # The new instance carries the copied catalog snapshot.
    assert (exercise["load_type"], exercise["side_count"], exercise["bodyweight_percent"]) == (
        "single_weight",
        1,
        None,
    )
    assert [(item["id"], item["set_index"]) for item in exercise["sets"]] == [
        (SET_A1, 0),
        (SET_A2, 1),
    ]
    assert exercise["sets"][1]["reps"] == 6
    # The public GET agrees exactly with the PUT response.
    assert get_detail(api_client, workout_id) == detail


def test_exact_retry_does_not_increment_or_duplicate(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    body = save_body(
        revision=0,
        save_id=SAVE_1,
        name="once",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1), set_body(SET_A2)])],
    )
    first = put_save(api_client, workout_id, body)
    assert first.status_code == 200
    retry = put_save(api_client, workout_id, body)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert retry.json()["revision"] == 1
    with connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 2


def test_retry_matches_after_input_normalization(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    body = save_body(
        revision=0,
        save_id=SAVE_1,
        name="normalized",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
    )
    assert put_save(api_client, workout_id, body).status_code == 200
    respelled = dict(body)
    respelled["save_id"] = SAVE_1.upper()
    respelled["exercises"] = [exercise_body(EXERCISE_A.upper(), sets=[set_body(SET_A1.upper())])]
    retry = put_save(api_client, workout_id, respelled)
    assert retry.status_code == 200
    assert retry.json()["revision"] == 1
    assert retry.json()["last_save_id"] == SAVE_1


def test_no_op_new_save_increments_revision(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    assert put_save(api_client, workout_id, save_body(revision=0, save_id=SAVE_1, name="same"))
    second = save_body(revision=1, save_id=SAVE_2, name="same")
    response = put_save(api_client, workout_id, second)
    assert response.status_code == 200
    # Identical user-visible content with a fresh save_id is a new accepted
    # save: every attempt receives its own receipt.
    assert response.json()["revision"] == 2
    assert response.json()["last_save_id"] == SAVE_2


def test_reorder_add_remove_through_put(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    first = save_body(
        revision=0,
        save_id=SAVE_1,
        exercises=[
            exercise_body(EXERCISE_A, sets=[set_body(SET_A1), set_body(SET_A2)]),
            exercise_body(EXERCISE_B, sets=[set_body(SET_B1)]),
        ],
    )
    assert put_save(api_client, workout_id, first).status_code == 200
    # Reverse-level reorder, drop SET_A1, add exercise C and a new set.
    second = save_body(
        revision=1,
        save_id=SAVE_2,
        exercises=[
            exercise_body(EXERCISE_B, sets=[set_body(SET_B1, reps=5)]),
            exercise_body(EXERCISE_C, sets=[set_body(SET_C1)]),
            exercise_body(EXERCISE_A, sets=[set_body(SET_A2), set_body(SET_NEW)]),
        ],
    )
    response = put_save(api_client, workout_id, second)
    assert response.status_code == 200
    detail = response.json()
    assert detail["revision"] == 2
    assert [(item["id"], item["order_index"]) for item in detail["exercises"]] == [
        (EXERCISE_B, 0),
        (EXERCISE_C, 1),
        (EXERCISE_A, 2),
    ]
    sets_by_exercise = {
        item["id"]: [(entry["id"], entry["set_index"]) for entry in item["sets"]]
        for item in detail["exercises"]
    }
    assert sets_by_exercise[EXERCISE_A] == [(SET_A2, 0), (SET_NEW, 1)]
    assert sets_by_exercise[EXERCISE_B] == [(SET_B1, 0)]
    assert sets_by_exercise[EXERCISE_C] == [(SET_C1, 0)]
    # The retained set's value was updated in place under the unique indexes.
    assert detail["exercises"][0]["sets"][0]["reps"] == 5
    assert get_detail(api_client, workout_id) == detail


# --- finish lifecycle -------------------------------------------------------------


def test_finish_is_atomic_and_read_only_afterwards(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    finish = save_body(
        revision=0,
        save_id=SAVE_1,
        name="done",
        ended_at="2026-01-01T09:30:00Z",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
    )
    response = put_save(api_client, workout_id, finish)
    assert response.status_code == 200
    detail = response.json()
    # The final sets and the finish timestamp commit together.
    assert detail["ended_at"] == "2026-01-01T09:30:00Z"
    assert detail["revision"] == 1
    assert [(item["id"], item["done"]) for item in detail["exercises"][0]["sets"]] == [
        (SET_A1, True)
    ]

    # The exact finish retry is served with 200 and no second increment.
    retry = put_save(api_client, workout_id, finish)
    assert retry.status_code == 200
    assert retry.json() == detail

    # A new save_id with identical content is a new write to a finished
    # workout, never an implicit retry.
    same_content = dict(finish)
    same_content["revision"] = 1
    same_content["save_id"] = SAVE_2
    response = put_save(api_client, workout_id, same_content)
    assert response.status_code == 409
    body = problem(response)
    assert body["code"] == "workout_finished"
    assert body["current_revision"] == 1

    # Reopening (clearing ended_at) is rejected by the same guard.
    reopen = dict(finish)
    reopen["revision"] = 1
    reopen["save_id"] = SAVE_3
    reopen["ended_at"] = None
    assert problem(put_save(api_client, workout_id, reopen))["code"] == "workout_finished"

    listing = api_client.get(WORKOUTS_URL, params={"status": "finished"}).json()
    assert [item["id"] for item in listing["items"]] == [workout_id]


def test_finish_time_violations_are_422(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)

    before_start = save_body(revision=0, save_id=SAVE_1, ended_at="2025-12-31T23:59:59Z")
    response = put_save(api_client, workout_id, before_start)
    assert response.status_code == 422
    body = problem(response)
    assert body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "ended_at"
    assert "2025" not in json.dumps(body["errors"])

    future = save_body(revision=0, save_id=SAVE_2, ended_at="2999-01-01T00:00:00Z")
    response = put_save(api_client, workout_id, future)
    assert response.status_code == 422
    body = problem(response)
    assert body["errors"][0]["field"] == "ended_at"
    assert "2999" not in json.dumps(body["errors"])

    # Validation failures left the workout untouched at revision 0...
    assert get_detail(api_client, workout_id)["revision"] == 0
    # ...and the equal-to-started_at boundary is accepted.
    boundary = save_body(revision=0, save_id=SAVE_3, ended_at=STARTED_AT)
    response = put_save(api_client, workout_id, boundary)
    assert response.status_code == 200
    assert response.json()["ended_at"] == STARTED_AT


# --- stable failures ---------------------------------------------------------------


def test_save_id_reuse_with_different_content_conflicts(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    assert (
        put_save(
            api_client, workout_id, save_body(revision=0, save_id=SAVE_1, name="original")
        ).status_code
        == 200
    )
    impostor = save_body(revision=1, save_id=SAVE_1, name="tampered")
    response = put_save(api_client, workout_id, impostor)
    assert response.status_code == 409
    body = problem(response)
    assert body["code"] == "save_id_conflict"
    assert body["current_revision"] == 1
    # Conflicts carry only the revision member, never the graph.
    assert set(body) == PROBLEM_FIELDS | {"current_revision"}
    current = get_detail(api_client, workout_id)
    assert current["name"] == "original"
    assert current["revision"] == 1


def test_stale_revision_conflicts_without_graph(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    assert (
        put_save(
            api_client, workout_id, save_body(revision=0, save_id=SAVE_1, name="v1")
        ).status_code
        == 200
    )
    stale = save_body(revision=0, save_id=SAVE_2, name="stale")
    response = put_save(api_client, workout_id, stale)
    assert response.status_code == 409
    body = problem(response)
    assert body["code"] == "revision_conflict"
    assert body["current_revision"] == 1
    assert set(body) == PROBLEM_FIELDS | {"current_revision"}
    current = get_detail(api_client, workout_id)
    assert current["name"] == "v1"
    assert current["revision"] == 1


def test_superseded_receipt_retry_conflicts(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    first = save_body(revision=0, save_id=SAVE_1, name="v1")
    assert put_save(api_client, workout_id, first).status_code == 200
    assert (
        put_save(
            api_client, workout_id, save_body(revision=1, save_id=SAVE_2, name="v2")
        ).status_code
        == 200
    )
    # Only the latest receipt is retained: the older exact payload is a normal
    # revision conflict, not a claimed success.
    response = put_save(api_client, workout_id, first)
    assert response.status_code == 409
    body = problem(response)
    assert body["code"] == "revision_conflict"
    assert body["current_revision"] == 2
    assert get_detail(api_client, workout_id)["name"] == "v2"


def test_put_never_creates_missing_workouts(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    missing_id = str(uuid.uuid4())
    response = put_save(api_client, missing_id, save_body(revision=0, save_id=SAVE_1))
    assert response.status_code == 404
    body = problem(response)
    assert body["code"] == "not_found"
    # A 404 carries no revision member and never creates the row.
    assert set(body) == PROBLEM_FIELDS
    with connect(migrated_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0] == 0


def test_foreign_workout_save_is_404(make_app, migrated_db: Path) -> None:
    with two_users(make_app) as (alice, bob, _alice_id, _bob_id):
        workout_id = create(alice)
        response = put_save(bob, workout_id, save_body(revision=0, save_id=SAVE_1, name="stolen"))
        assert response.status_code == 404
        assert set(problem(response)) == PROBLEM_FIELDS
        current = get_detail(alice, workout_id)
        assert current["revision"] == 0
        assert current["name"] is None


def test_graph_and_catalog_conflicts_are_generic(make_app, migrated_db: Path) -> None:
    with two_users(make_app) as (alice, bob, _alice_id, _bob_id):
        first_id = create(alice)
        second_id = create(alice)
        seeded = save_body(
            revision=0,
            save_id=SAVE_1,
            exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
        )
        assert put_save(alice, first_id, seeded).status_code == 200

        # A stored exercise of another workout cannot be adopted; the conflict
        # never discloses which id collided or where it lives.
        adopted = save_body(revision=0, save_id=SAVE_2, exercises=[exercise_body(EXERCISE_A)])
        response = put_save(alice, second_id, adopted)
        assert response.status_code == 409
        body = problem(response)
        assert body["code"] == "graph_conflict"
        assert set(body) == PROBLEM_FIELDS

        # Bob's custom catalog entry is indistinguishable from an unknown id.
        created_entry = bob.post(
            EXERCISES_URL,
            json={
                "name": "Bob Curl",
                "muscle_group": "arms",
                "equipment": "dumbbell",
                "load_type": "split_weight",
                "side_count": 2,
            },
        )
        assert created_entry.status_code == 201
        foreign = save_body(
            revision=0,
            save_id=SAVE_3,
            exercises=[
                exercise_body(EXERCISE_C, catalog_id=str(created_entry.json()["id"])),
            ],
        )
        response = put_save(alice, second_id, foreign)
        assert response.status_code == 409
        body = problem(response)
        assert body["code"] == "catalog_unavailable"
        assert set(body) == PROBLEM_FIELDS

        unknown = save_body(
            revision=0,
            save_id=SAVE_4,
            exercises=[exercise_body(EXERCISE_C, catalog_id="no-such-entry")],
        )
        assert problem(put_save(alice, second_id, unknown))["code"] == "catalog_unavailable"

        # No conflicting attempt left a partial write.
        current = get_detail(alice, second_id)
        assert current["revision"] == 0
        assert current["exercises"] == []


def test_revision_exhaustion_serves_only_exact_retries(
    api_client: TestClient, migrated_db: Path
) -> None:
    user_id = register_and_login(api_client)
    workout_id = create(api_client)
    accepted = save_body(revision=MAX_SAFE_INTEGER - 1, save_id=SAVE_1, name="final")
    receipt_hash = save_request_hash(
        owner_id=user_id,
        workout_id=workout_id,
        payload=SaveWorkoutRequest.model_validate(accepted),
    )
    with connect(migrated_db) as conn, write_transaction(conn):
        conn.execute(
            "UPDATE workouts SET revision = :revision, last_save_id = :save_id, "
            "last_save_hash = :save_hash WHERE id = :id",
            {
                "revision": MAX_SAFE_INTEGER,
                "save_id": SAVE_1,
                "save_hash": receipt_hash,
                "id": workout_id,
            },
        )
    # The receipt that exhausted the revision still serves its exact retry.
    retry = put_save(api_client, workout_id, accepted)
    assert retry.status_code == 200
    assert retry.json()["revision"] == MAX_SAFE_INTEGER
    # A new save cannot increment past the safe integer range.
    response = put_save(
        api_client,
        workout_id,
        save_body(revision=MAX_SAFE_INTEGER, save_id=SAVE_2, name="one more"),
    )
    assert response.status_code == 409
    body = problem(response)
    assert body["code"] == "revision_exhausted"
    assert body["current_revision"] == MAX_SAFE_INTEGER
    assert get_detail(api_client, workout_id)["revision"] == MAX_SAFE_INTEGER


# --- input validation through the public route --------------------------------------


def test_put_rejects_unknown_and_missing_fields(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)

    missing_notes = save_body(revision=0, save_id=SAVE_1)
    del missing_notes["notes"]
    missing_done = save_body(revision=0, save_id=SAVE_2)
    missing_done["exercises"] = [exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])]
    del missing_done["exercises"][0]["sets"][0]["done"]

    bad_bodies = [
        # started_at is immutable after POST; the id comes only from the path.
        save_body(revision=0, save_id=SAVE_1, started_at=STARTED_AT),
        save_body(revision=0, save_id=SAVE_1, id=workout_id),
        # Receipt and server-timestamp fields are server-controlled.
        save_body(revision=0, save_id=SAVE_1, last_save_id=None),
        save_body(revision=0, save_id=SAVE_1, updated_at=STARTED_AT),
        # Required nullable fields must be sent explicitly.
        missing_notes,
        missing_done,
    ]
    for body in bad_bodies:
        response = put_save(api_client, workout_id, body)
        assert response.status_code == 422
        assert problem(response)["code"] == "validation_error"

    # Snapshot and derived-index fields are rejected at both nested levels.
    for exercises in (
        [{**exercise_body(EXERCISE_A), "load_type": "single_weight"}],
        [{**exercise_body(EXERCISE_A), "order_index": 0}],
        [{**exercise_body(EXERCISE_A), "bodyweight_percent": None}],
        [exercise_body(EXERCISE_A, sets=[{**set_body(SET_A1), "set_index": 0}])],
        [exercise_body(EXERCISE_A, sets=[{**set_body(SET_A1), "exercise_id": EXERCISE_A}])],
    ):
        response = put_save(
            api_client, workout_id, save_body(revision=0, save_id=SAVE_3, exercises=exercises)
        )
        assert response.status_code == 422
        assert problem(response)["code"] == "validation_error"

    assert get_detail(api_client, workout_id)["revision"] == 0


def test_completed_and_draft_set_rules_through_put(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)

    # bench-press records a single_weight snapshot: completed sets need a
    # non-null weight, positive reps, and a bilateral side.
    violations = [
        (SAVE_1, set_body(SET_A1, weight_kg=None), "exercises.0.sets.0.weight_kg"),
        (SAVE_2, set_body(SET_A1, reps=0), "exercises.0.sets.0.reps"),
        (SAVE_3, set_body(SET_A1, side="left"), "exercises.0.sets.0.side"),
    ]
    for save_id, offending, field in violations:
        body = save_body(
            revision=0,
            save_id=save_id,
            exercises=[exercise_body(EXERCISE_A, sets=[offending])],
        )
        response = put_save(api_client, workout_id, body)
        assert response.status_code == 422
        problem_body = problem(response)
        assert problem_body["code"] == "validation_error"
        assert problem_body["errors"][0]["field"] == field
    assert get_detail(api_client, workout_id)["revision"] == 0

    # A draft set may omit reps and weight.
    draft = save_body(
        revision=0,
        save_id=SAVE_4,
        exercises=[
            exercise_body(
                EXERCISE_A, sets=[set_body(SET_A1, reps=None, weight_kg=None, done=False)]
            )
        ],
    )
    response = put_save(api_client, workout_id, draft)
    assert response.status_code == 200
    stored_set = response.json()["exercises"][0]["sets"][0]
    assert (stored_set["reps"], stored_set["weight_kg"], stored_set["done"]) == (None, None, False)


# --- atomicity, capture, and retryable failures -------------------------------------


def test_response_graph_is_captured_before_commit(
    api_client: TestClient, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    real_connect = workouts.connect

    def replace_after_commit(statement: str) -> None:
        if statement != "COMMIT":
            return
        # A second writer lands between the save's commit and its response.
        with real_connect(migrated_db) as second, write_transaction(second):
            second.execute(
                "UPDATE workouts SET name = 'replaced-after-commit' WHERE id = :id",
                {"id": workout_id},
            )

    @contextmanager
    def hooked_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, **kwargs) as conn:
            yield HookedConnection(conn, after=replace_after_commit)  # type: ignore[misc]

    monkeypatch.setattr(workouts, "connect", hooked_connect)
    response = put_save(
        api_client, workout_id, save_body(revision=0, save_id=SAVE_1, name="captured")
    )
    assert response.status_code == 200
    # The response keeps the graph captured on the write connection...
    assert response.json()["name"] == "captured"
    assert response.json()["revision"] == 1

    # ...while the later writer's replacement is the new committed state.
    current = get_detail(api_client, workout_id)
    assert current["name"] == "replaced-after-commit"
    assert current["revision"] == 1


def test_busy_database_maps_to_retryable_503(
    api_client: TestClient, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    body = save_body(revision=0, save_id=SAVE_1, name="blocked")
    real_connect = workouts.connect

    @contextmanager
    def impatient_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, busy_timeout_ms=50, **kwargs) as conn:
            yield conn

    with connect(migrated_db) as holder:
        # Hold the write lock outside any helper transaction until the save
        # attempt has provably failed; no timing-only sleeps are involved.
        holder.execute("BEGIN IMMEDIATE")
        try:
            monkeypatch.setattr(workouts, "connect", impatient_connect)
            response = put_save(api_client, workout_id, body)
        finally:
            holder.execute("ROLLBACK")

    assert response.status_code == 503
    problem_body = problem(response)
    assert problem_body["code"] == "retryable"
    assert response.headers["Retry-After"] == "1"
    # The blocked save changed nothing; the retry after release succeeds.
    assert get_detail(api_client, workout_id)["revision"] == 0
    monkeypatch.setattr(workouts, "connect", real_connect)
    retry = put_save(api_client, workout_id, body)
    assert retry.status_code == 200
    assert retry.json()["revision"] == 1
    assert retry.json()["name"] == "blocked"
