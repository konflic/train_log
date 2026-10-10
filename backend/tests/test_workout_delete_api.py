"""Stage 7 delete-lifecycle API tests (Gate G7).

`DELETE /workouts/{id}?revision=N` end-to-end coverage: authentication and the
Origin/JSON mutating-request conventions; the empty 204 exact-revision delete
of an active workout with its cascaded graph; finished-workout deletion with
the exact finish retry served before deletion and 404 after it; stale and
future revisions returning the stable 409 `revision_conflict` shape without
mutation; missing, already-deleted, and foreign ids sharing one 404; required,
bounded revision-query validation; GET/PUT/DELETE after deletion never
recreating the workout; catalog-reference release for a guarded custom entry;
and the retryable held-writer 503.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import connect
from app.numbers import MAX_SAFE_INTEGER
from app.services import workouts

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
WORKOUTS_URL = "/api/v1/workouts"
EXERCISES_URL = "/api/v1/exercises"
JSON_TYPE = {"Content-Type": "application/json"}

STARTED_AT = "2026-01-01T08:00:00Z"
CATALOG = "bench-press"

PROBLEM_FIELDS = {"type", "title", "status", "detail", "code", "request_id"}


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


EXERCISE_A = uid(1)
SET_A1 = uid(11)
SAVE_1 = uid(101)
SAVE_2 = uid(102)


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
    sets: list[dict[str, Any]] | None = None,
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


def delete_workout(client: TestClient, workout_id: str, revision: int | str):
    return client.delete(
        f"{WORKOUTS_URL}/{workout_id}", params={"revision": revision}, headers=JSON_TYPE
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


# --- authentication and conventions --------------------------------------------


def test_delete_requires_authentication(api_client: TestClient) -> None:
    response = delete_workout(api_client, str(uuid.uuid4()), 0)
    assert response.status_code == 401
    assert problem(response)["code"] == "unauthorized"


def test_delete_follows_csrf_and_json_conventions(make_app) -> None:
    app = make_app()
    with TestClient(app) as client:  # no Origin header at all
        missing_origin = delete_workout(client, str(uuid.uuid4()), 0)
        assert missing_origin.status_code == 403
        assert problem(missing_origin)["code"] == "origin_not_allowed"
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        register_and_login(client)
        workout_id = create(client)
        # The empty body still requires the JSON content type on DELETE.
        response = client.delete(f"{WORKOUTS_URL}/{workout_id}", params={"revision": 0})
        assert response.status_code == 415
        assert problem(response)["code"] == "json_required"
        assert get_detail(client, workout_id)["revision"] == 0


# --- accepted deletions ----------------------------------------------------------


def test_delete_returns_empty_204_and_removes_the_graph(
    api_client: TestClient, migrated_db: Path
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    body = save_body(
        revision=0,
        save_id=SAVE_1,
        name="Push day",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
    )
    assert put_save(api_client, workout_id, body).status_code == 200

    response = delete_workout(api_client, workout_id, 1)
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["X-Request-ID"]

    # The delete cascaded through the public route and left nothing behind.
    assert api_client.get(f"{WORKOUTS_URL}/{workout_id}").status_code == 404
    assert api_client.get(WORKOUTS_URL).json()["total"] == 0
    with connect(migrated_db) as conn:
        for table in ("workouts", "exercises", "sets"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_finished_workout_deletes_and_finish_retry_window_closes(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    finish = save_body(
        revision=0,
        save_id=SAVE_1,
        name="done",
        ended_at="2026-01-01T09:30:00Z",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
    )
    first = put_save(api_client, workout_id, finish)
    assert first.status_code == 200
    assert first.json()["revision"] == 1

    # Before deletion, the exact accepted finish retry is still served.
    retry = put_save(api_client, workout_id, finish)
    assert retry.status_code == 200
    assert retry.json() == first.json()

    # A finished workout is deletable at its exact revision...
    assert delete_workout(api_client, workout_id, 1).status_code == 204

    # ...after which even the exact receipt retry is a plain 404: no tombstone.
    after = put_save(api_client, workout_id, finish)
    assert after.status_code == 404
    assert set(problem(after)) == PROBLEM_FIELDS
    assert api_client.get(WORKOUTS_URL, params={"status": "finished"}).json()["total"] == 0


# --- stable failures ---------------------------------------------------------------


def test_stale_and_future_revisions_conflict_without_mutation(
    api_client: TestClient,
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    assert (
        put_save(
            api_client, workout_id, save_body(revision=0, save_id=SAVE_1, name="v1")
        ).status_code
        == 200
    )
    for revision in (0, 2, MAX_SAFE_INTEGER):
        response = delete_workout(api_client, workout_id, revision)
        assert response.status_code == 409, revision
        body = problem(response)
        assert body["code"] == "revision_conflict"
        assert body["current_revision"] == 1
        # The PUT conflict shape, reused exactly; never a resource body.
        assert set(body) == PROBLEM_FIELDS | {"current_revision"}
    current = get_detail(api_client, workout_id)
    assert current["revision"] == 1
    assert current["name"] == "v1"


def test_missing_foreign_and_repeated_deletes_404(make_app, migrated_db: Path) -> None:
    with two_users(make_app) as (alice, bob, _alice_id, _bob_id):
        workout_id = create(alice)
        missing = delete_workout(alice, str(uuid.uuid4()), 0)
        assert missing.status_code == 404
        assert set(problem(missing)) == PROBLEM_FIELDS

        # Bob's delete at the exact stored revision is indistinguishable...
        foreign = delete_workout(bob, workout_id, 0)
        assert foreign.status_code == 404
        assert set(problem(foreign)) == PROBLEM_FIELDS
        # ...and leaves Alice's workout untouched.
        assert get_detail(alice, workout_id)["revision"] == 0

        assert delete_workout(alice, workout_id, 0).status_code == 204
        # A retry after a successful but unobserved deletion resolves to the
        # same 404 as an unknown id; the client's GET sees 404 too.
        repeated = delete_workout(alice, workout_id, 0)
        assert repeated.status_code == 404
        assert set(problem(repeated)) == PROBLEM_FIELDS


def test_revision_query_is_required_and_bounded(api_client: TestClient) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    missing = api_client.delete(f"{WORKOUTS_URL}/{workout_id}", headers=JSON_TYPE)
    assert missing.status_code == 422
    assert problem(missing)["code"] == "validation_error"
    for value in (
        "-1",
        str(MAX_SAFE_INTEGER + 1),
        "abc",
        "1.0",
        "1.5",
        "+1",
        " 1 ",
        "",
        "0x1",
    ):
        response = delete_workout(api_client, workout_id, value)
        assert response.status_code == 422, value
        body = problem(response)
        assert body["code"] == "validation_error"
        # Field paths and messages only; never the rejected value.
        if value:
            assert value not in json.dumps(body["errors"])
    assert get_detail(api_client, workout_id)["revision"] == 0


# --- post-delete lifecycle -----------------------------------------------------------


def test_lifecycle_after_delete_never_recreates(api_client: TestClient, migrated_db: Path) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    queued = save_body(
        revision=0,
        save_id=SAVE_1,
        name="queued",
        exercises=[exercise_body(EXERCISE_A, sets=[set_body(SET_A1)])],
    )
    assert put_save(api_client, workout_id, queued).status_code == 200
    assert delete_workout(api_client, workout_id, 1).status_code == 204

    # A queued/stale PUT — even the exact retry of the last accepted save —
    # returns 404 and never resurrects the workout.
    stale = put_save(api_client, workout_id, queued)
    assert stale.status_code == 404
    assert problem(stale)["code"] == "not_found"
    fresh = put_save(api_client, workout_id, save_body(revision=1, save_id=SAVE_2, name="fresh"))
    assert fresh.status_code == 404
    assert api_client.get(f"{WORKOUTS_URL}/{workout_id}").status_code == 404
    assert delete_workout(api_client, workout_id, 1).status_code == 404

    with connect(migrated_db) as conn:
        for table in ("workouts", "exercises", "sets"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_delete_releases_a_guarded_catalog_reference(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = api_client.post(
        EXERCISES_URL,
        json={
            "name": "Custom Curl",
            "muscle_group": "arms",
            "load_type": "split_weight",
            "side_count": 2,
        },
    )
    assert entry.status_code == 201
    entry_id = str(entry.json()["id"])
    workout_id = create(api_client)
    body = save_body(
        revision=0,
        save_id=SAVE_1,
        exercises=[exercise_body(EXERCISE_A, catalog_id=entry_id, sets=[set_body(SET_A1)])],
    )
    assert put_save(api_client, workout_id, body).status_code == 200

    # While history references the entry, its delete stays guarded...
    in_use = api_client.delete(f"{EXERCISES_URL}/{entry_id}", headers=JSON_TYPE)
    assert in_use.status_code == 409
    assert problem(in_use)["code"] == "entry_in_use"

    # ...and the workout deletion releases the reference.
    assert delete_workout(api_client, workout_id, 1).status_code == 204
    freed = api_client.delete(f"{EXERCISES_URL}/{entry_id}", headers=JSON_TYPE)
    assert freed.status_code == 204


# --- retryable failure ----------------------------------------------------------------


def test_busy_database_maps_to_retryable_503(
    api_client: TestClient, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_and_login(api_client)
    workout_id = create(api_client)
    real_connect = workouts.connect

    @contextmanager
    def impatient_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, busy_timeout_ms=50, **kwargs) as conn:
            yield conn

    with connect(migrated_db) as holder:
        # Hold the write lock outside any helper transaction until the delete
        # attempt has provably failed; no timing-only sleeps are involved.
        holder.execute("BEGIN IMMEDIATE")
        try:
            monkeypatch.setattr(workouts, "connect", impatient_connect)
            response = delete_workout(api_client, workout_id, 0)
        finally:
            holder.execute("ROLLBACK")

    assert response.status_code == 503
    problem_body = problem(response)
    assert problem_body["code"] == "retryable"
    assert response.headers["Retry-After"] == "1"
    # The blocked delete changed nothing; the retry after release succeeds.
    assert get_detail(api_client, workout_id)["revision"] == 0
    monkeypatch.setattr(workouts, "connect", real_connect)
    assert delete_workout(api_client, workout_id, 0).status_code == 204
    assert api_client.get(f"{WORKOUTS_URL}/{workout_id}").status_code == 404
