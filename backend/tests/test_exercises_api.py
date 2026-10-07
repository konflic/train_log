"""Stage 4 exercise catalog API tests (Gate G4).

Covers authentication, visibility scoping (defaults + own customs, cross-user
404), search/filters/pagination with stable Unicode casefold ordering, in-scope
name uniqueness, default immutability, the referenced-entry delete guard,
strict rejection of fractional/string/boolean/out-of-range and unknown or
server-controlled fields, UTF-8 round-trips, and the shared problem+json,
request-id, and CSRF conventions established in Stage 3.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import insert_exercise, insert_workout

from app.db import connect, write_transaction

ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery"
EXERCISES_URL = "/api/v1/exercises"

# Mutating requests must send JSON content type (Stage 3 CSRF convention);
# DELETE carries no body, so the header is set explicitly.
JSON_TYPE = {"Content-Type": "application/json"}

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

SEEDED_DEFAULT_COUNT = 12
RESPONSE_FIELDS = {
    "id",
    "name",
    "muscle_group",
    "equipment",
    "load_type",
    "bodyweight_percent",
    "side_count",
    "is_default",
}


def register_and_login(client: TestClient, email: str = "user@example.com") -> str:
    """Register and log in; return the new account's id."""
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


def entry_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Custom Curl",
        "muscle_group": "arms",
        "equipment": "dumbbell",
        "load_type": "split_weight",
        "side_count": 2,
    }
    payload.update(overrides)
    return payload


def create_exercise(client: TestClient, **overrides: object):
    return client.post(EXERCISES_URL, json=entry_payload(**overrides))


def delete_exercise(client: TestClient, entry_id: str):
    return client.delete(f"{EXERCISES_URL}/{entry_id}", headers=JSON_TYPE)


def list_ids(body: dict) -> list[str]:
    return [item["id"] for item in body["items"]]


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


def reference_in_history(database_path: Path, *, user_id: str, catalog_id: str) -> None:
    """Insert a workout whose exercise references the catalog entry."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(conn, "workout-1", user_id=user_id)
        insert_exercise(
            conn,
            "exercise-1",
            workout_id="workout-1",
            catalog_id=catalog_id,
            load_type="split_weight",
            bodyweight_percent=None,
            side_count=2,
        )


# --- authentication -----------------------------------------------------------


def test_all_endpoints_require_authentication(api_client: TestClient) -> None:
    responses = [
        api_client.get(EXERCISES_URL),
        api_client.get(f"{EXERCISES_URL}/bench-press"),
        api_client.post(EXERCISES_URL, json=entry_payload()),
        api_client.patch(f"{EXERCISES_URL}/bench-press", json={"name": "x"}),
        delete_exercise(api_client, "bench-press"),
    ]
    for response in responses:
        assert response.status_code == 401
        assert problem(response)["code"] == "unauthorized"


# --- listing and visibility -----------------------------------------------------


def test_list_returns_seeded_defaults(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.get(EXERCISES_URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == SEEDED_DEFAULT_COUNT
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert len(body["items"]) == SEEDED_DEFAULT_COUNT
    for item in body["items"]:
        assert set(item) == RESPONSE_FIELDS
        assert item["is_default"] is True


def test_list_includes_own_customs_only(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        created = create_exercise(alice)
        assert created.status_code == 201
        custom_id = created.json()["id"]

        alice_list = alice.get(EXERCISES_URL).json()
        assert alice_list["total"] == SEEDED_DEFAULT_COUNT + 1
        assert custom_id in list_ids(alice_list)

        bob_list = bob.get(EXERCISES_URL).json()
        assert bob_list["total"] == SEEDED_DEFAULT_COUNT
        assert custom_id not in list_ids(bob_list)
        assert all(item["is_default"] for item in bob_list["items"])


def test_get_by_id_respects_visibility(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        custom_id = create_exercise(alice).json()["id"]
        # Own custom and any default are visible to the owner...
        assert alice.get(f"{EXERCISES_URL}/{custom_id}").status_code == 200
        assert bob.get(f"{EXERCISES_URL}/{custom_id}").status_code == 404
        assert alice.get(f"{EXERCISES_URL}/bench-press").status_code == 200
        assert bob.get(f"{EXERCISES_URL}/bench-press").status_code == 200
        # Unknown ids share the same 404 shape as foreign ones.
        unknown = alice.get(f"{EXERCISES_URL}/no-such-entry")
        assert unknown.status_code == 404
        assert problem(unknown)["code"] == "not_found"


# --- search and filters -----------------------------------------------------------


def test_search_is_case_insensitive(api_client: TestClient) -> None:
    register_and_login(api_client)
    for query in ("press", "PRESS", "Pre"):
        response = api_client.get(EXERCISES_URL, params={"search": query})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert {item["id"] for item in body["items"]} == {
            "bench-press",
            "overhead-press",
            "leg-press",
        }


def test_search_folds_unicode(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        assert (
            create_exercise(
                alice,
                name="Жим Лёжа",
                muscle_group="chest",
                equipment="barbell",
                load_type="single_weight",
                side_count=1,
            ).status_code
            == 201
        )
        for query in ("жим", "ЖИМ", "лёжа"):
            found = alice.get(EXERCISES_URL, params={"search": query}).json()
            assert [item["name"] for item in found["items"]] == ["Жим Лёжа"], query
        # Search never reaches another user's customs.
        assert bob.get(EXERCISES_URL, params={"search": "жим"}).json()["total"] == 0


def test_search_treats_wildcards_literally(api_client: TestClient) -> None:
    register_and_login(api_client)
    assert (
        create_exercise(
            api_client, name="100% Row", load_type="single_weight", side_count=1
        ).status_code
        == 201
    )
    assert (
        create_exercise(
            api_client, name="100x Row", load_type="single_weight", side_count=1
        ).status_code
        == 201
    )
    assert (
        create_exercise(api_client, name="A_B", load_type="single_weight", side_count=1).status_code
        == 201
    )
    assert (
        create_exercise(api_client, name="AXB", load_type="single_weight", side_count=1).status_code
        == 201
    )

    def search(query: str) -> list[str]:
        return [
            item["name"]
            for item in api_client.get(EXERCISES_URL, params={"search": query}).json()["items"]
        ]

    assert search("100%") == ["100% Row"]
    assert search("%") == ["100% Row"]
    assert search("A_B") == ["A_B"]
    assert sorted(search("100")) == ["100% Row", "100x Row"]


def test_search_length_is_bounded(api_client: TestClient) -> None:
    register_and_login(api_client)
    assert api_client.get(EXERCISES_URL, params={"search": "x" * 100}).status_code == 200
    too_long = api_client.get(EXERCISES_URL, params={"search": "x" * 101})
    assert too_long.status_code == 422
    assert problem(too_long)["code"] == "validation_error"


def test_muscle_group_and_equipment_filters(api_client: TestClient) -> None:
    register_and_login(api_client)
    back = api_client.get(EXERCISES_URL, params={"muscle_group": "back"}).json()
    assert back["total"] == 4
    assert {item["id"] for item in back["items"]} == {
        "barbell-row",
        "deadlift",
        "lat-pulldown",
        "pull-up",
    }
    bodyweight = api_client.get(EXERCISES_URL, params={"equipment": "bodyweight"}).json()
    assert {item["id"] for item in bodyweight["items"]} == {"pull-up", "push-up", "dip"}
    combined = api_client.get(
        EXERCISES_URL, params={"muscle_group": "chest", "search": "press"}
    ).json()
    assert [item["id"] for item in combined["items"]] == ["bench-press"]


@pytest.mark.parametrize(
    "params",
    [{"muscle_group": "neck"}, {"equipment": "robot"}, {"muscle_group": 5}],
)
def test_invalid_filter_values_are_rejected(api_client: TestClient, params: dict) -> None:
    register_and_login(api_client)
    response = api_client.get(EXERCISES_URL, params=params)
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"


# --- pagination and ordering --------------------------------------------------------


def test_pagination_is_bounded_stable_and_disjoint(api_client: TestClient) -> None:
    register_and_login(api_client)
    first = api_client.get(EXERCISES_URL, params={"page": 1, "pageSize": 5}).json()
    assert first["total"] == SEEDED_DEFAULT_COUNT
    assert first["page"] == 1
    assert first["page_size"] == 5
    assert len(first["items"]) == 5
    second = api_client.get(EXERCISES_URL, params={"page": 2, "pageSize": 5}).json()
    third = api_client.get(EXERCISES_URL, params={"page": 3, "pageSize": 5}).json()
    assert len(third["items"]) == 2
    paged = [item["id"] for page in (first, second, third) for item in page["items"]]
    full = api_client.get(EXERCISES_URL, params={"pageSize": 100}).json()
    assert paged == [item["id"] for item in full["items"]]
    assert len(set(paged)) == SEEDED_DEFAULT_COUNT
    beyond = api_client.get(EXERCISES_URL, params={"page": 99, "pageSize": 5}).json()
    assert beyond["items"] == []
    assert beyond["total"] == SEEDED_DEFAULT_COUNT


def test_pagination_parameter_names_and_bounds(api_client: TestClient) -> None:
    register_and_login(api_client)
    # PLAN.md §6 names the bound query parameter `pageSize`; `page_size` is not
    # a recognized parameter and the default page size applies instead.
    ignored = api_client.get(EXERCISES_URL, params={"page_size": 5}).json()
    assert ignored["page_size"] == 50
    assert len(ignored["items"]) == SEEDED_DEFAULT_COUNT
    for params in (
        {"page": 0},
        {"page": -1},
        {"pageSize": 0},
        {"pageSize": 101},
        {"pageSize": 2.5},
        {"pageSize": "many"},
        {"page": True},
    ):
        response = api_client.get(EXERCISES_URL, params=params)
        assert response.status_code == 422, params
        assert problem(response)["code"] == "validation_error"


def test_order_folds_case_and_breaks_ties_by_id(api_client: TestClient) -> None:
    register_and_login(api_client)
    custom = create_exercise(
        api_client,
        name="pull-up",
        muscle_group="back",
        equipment="bodyweight",
        load_type="bodyweight",
        bodyweight_percent=100,
        side_count=1,
    ).json()
    found = api_client.get(EXERCISES_URL, params={"search": "PULL-UP"}).json()
    pairs = [(item["name"], item["id"]) for item in found["items"]]
    assert found["total"] == 2
    assert pairs == sorted(pairs, key=lambda pair: (pair[0].casefold(), pair[1]))
    assert {pair[1] for pair in pairs} == {"pull-up", custom["id"]}


# --- create -----------------------------------------------------------------------------


def test_create_returns_explicit_public_shape(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = create_exercise(api_client, name="  Custom Curl  ")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert UUID_RE.fullmatch(body["id"])
    assert body["name"] == "Custom Curl"
    assert body["is_default"] is False
    assert body["bodyweight_percent"] is None
    assert body["side_count"] == 2
    assert "created_by" not in response.text
    # The stored entry round-trips identically.
    assert api_client.get(f"{EXERCISES_URL}/{body['id']}").json() == body


def test_create_omitted_optionals_use_safe_defaults(api_client: TestClient) -> None:
    register_and_login(api_client)
    payload = {
        "name": "Weighted Pull-up",
        "muscle_group": "back",
        "equipment": "bodyweight",
        "load_type": "single_weight",
        "bodyweight_percent": 100,
    }
    response = api_client.post(EXERCISES_URL, json=payload)
    assert response.status_code == 201
    assert response.json()["side_count"] == 1


@pytest.mark.parametrize("field", ["id", "is_default", "created_by", "created_at", "owner"])
def test_create_rejects_unknown_or_server_controlled_fields(
    api_client: TestClient, field: str
) -> None:
    register_and_login(api_client)
    response = create_exercise(api_client, **{field: "whatever"})
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        entry_payload(name=""),
        entry_payload(name="   "),
        entry_payload(name="x" * 101),
        entry_payload(name=12345),
        entry_payload(name=True),
        entry_payload(name=None),
        entry_payload(muscle_group="neck"),
        entry_payload(muscle_group=None),
        entry_payload(equipment="robot"),
        entry_payload(load_type="assisted"),
        entry_payload(side_count=0),
        entry_payload(side_count=3),
        entry_payload(side_count=1.5),
        entry_payload(side_count="2"),
        entry_payload(side_count=True),
        entry_payload(load_type="single_weight", side_count=2),
        entry_payload(bodyweight_percent=0),
        entry_payload(bodyweight_percent=101),
        entry_payload(bodyweight_percent=65.5),
        entry_payload(bodyweight_percent="65"),
        entry_payload(bodyweight_percent=True),
        entry_payload(load_type="bodyweight", equipment="bodyweight"),
        entry_payload(load_type="bodyweight", equipment="bodyweight", bodyweight_percent=None),
        entry_payload(
            load_type="bodyweight",
            equipment="bodyweight",
            bodyweight_percent=100,
            side_count=2,
        ),
    ],
)
def test_create_rejects_invalid_payloads(api_client: TestClient, payload: dict) -> None:
    register_and_login(api_client)
    response = api_client.post(EXERCISES_URL, json=payload)
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"


def test_create_duplicate_name_conflicts_within_scope(api_client: TestClient) -> None:
    register_and_login(api_client)
    assert create_exercise(api_client, name="My Row").status_code == 201
    duplicate = create_exercise(api_client, name="My Row")
    assert duplicate.status_code == 409
    assert problem(duplicate)["code"] == "name_taken"
    # Exact-match uniqueness: a case variant is a different name.
    assert create_exercise(api_client, name="my row").status_code == 201


def test_create_allows_names_from_other_scopes(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        # A custom may reuse a default name (PLAN.md §4).
        assert create_exercise(alice, name="Pull-up").status_code == 201
        # Other owners' scopes are independent.
        assert create_exercise(alice, name="My Row").status_code == 201
        assert create_exercise(bob, name="My Row").status_code == 201


# --- patch ------------------------------------------------------------------------------


def test_patch_updates_own_custom_entry(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_exercise(api_client).json()
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}",
        json={"name": "  Renamed Row  ", "muscle_group": "core"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Row"
    assert body["muscle_group"] == "core"
    # Absent fields stay untouched.
    assert body["equipment"] == "dumbbell"
    assert body["load_type"] == "split_weight"
    assert body["side_count"] == 2
    assert body["is_default"] is False
    assert api_client.get(f"{EXERCISES_URL}/{entry['id']}").json() == body


def test_patch_null_clears_bodyweight_percent_only(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_exercise(
        api_client, load_type="single_weight", bodyweight_percent=30, side_count=1
    ).json()
    response = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"bodyweight_percent": None})
    assert response.status_code == 200
    assert response.json()["bodyweight_percent"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": 5},
        {"muscle_group": None},
        {"equipment": None},
        {"load_type": None},
        {"side_count": None},
        {"side_count": 0},
        {"bodyweight_percent": 0},
        {"bodyweight_percent": 101},
        {"bodyweight_percent": "30"},
        {"id": "other-id"},
        {"is_default": True},
        {"created_by": "someone"},
    ],
)
def test_patch_rejects_invalid_updates(api_client: TestClient, payload: dict) -> None:
    register_and_login(api_client)
    entry = create_exercise(api_client).json()
    response = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json=payload)
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"


def test_patch_validates_merged_entry(api_client: TestClient) -> None:
    register_and_login(api_client)
    # Stored: single_weight, percent null, side 1.
    entry = create_exercise(api_client, load_type="single_weight", side_count=1).json()
    # bodyweight requires a percentage on the merged result.
    response = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"load_type": "bodyweight"})
    assert response.status_code == 422
    assert problem(response)["code"] == "validation_error"
    assert api_client.get(f"{EXERCISES_URL}/{entry['id']}").json() == entry
    # Providing the percentage together succeeds.
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}",
        json={"load_type": "bodyweight", "bodyweight_percent": 100},
    )
    assert response.status_code == 200
    # Clearing the percentage of a bodyweight entry is rejected...
    response = api_client.patch(f"{EXERCISES_URL}/{entry['id']}", json={"bodyweight_percent": None})
    assert response.status_code == 422
    # ...while moving to a weighted load type keeps the stored percentage.
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}", json={"load_type": "single_weight"}
    )
    assert response.status_code == 200
    assert response.json()["bodyweight_percent"] == 100


def test_patch_side_count_must_stay_valid_for_load_type(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_exercise(api_client).json()  # split_weight, side_count 2
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}", json={"load_type": "single_weight"}
    )
    assert response.status_code == 422
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}",
        json={"load_type": "single_weight", "side_count": 1},
    )
    assert response.status_code == 200
    assert response.json()["side_count"] == 1


def test_patch_defaults_are_immutable(api_client: TestClient) -> None:
    register_and_login(api_client)
    for default_id in ("bench-press", "pull-up"):
        response = api_client.patch(
            f"{EXERCISES_URL}/{default_id}",
            json={"name": "Mine", "bodyweight_percent": 50},
        )
        assert response.status_code == 403
        assert problem(response)["code"] == "default_immutable"
    assert api_client.get(f"{EXERCISES_URL}/bench-press").json()["name"] == "Bench Press"


def test_patch_foreign_or_unknown_entries_404(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        entry = create_exercise(alice).json()
        assert (
            bob.patch(f"{EXERCISES_URL}/{entry['id']}", json={"name": "Stolen"}).status_code == 404
        )
        assert alice.patch(f"{EXERCISES_URL}/does-not-exist", json={"name": "x"}).status_code == 404
        assert alice.get(f"{EXERCISES_URL}/{entry['id']}").json()["name"] == "Custom Curl"


def test_patch_rename_to_existing_name_conflicts(api_client: TestClient) -> None:
    register_and_login(api_client)
    create_exercise(api_client, name="First Row")
    second = create_exercise(api_client, name="Second Row").json()
    response = api_client.patch(f"{EXERCISES_URL}/{second['id']}", json={"name": "First Row"})
    assert response.status_code == 409
    assert problem(response)["code"] == "name_taken"


def test_patch_preserves_recorded_snapshots(api_client: TestClient, migrated_db: Path) -> None:
    user_id = register_and_login(api_client)
    entry = create_exercise(api_client).json()  # split_weight, percent null, side 2
    reference_in_history(migrated_db, user_id=user_id, catalog_id=entry["id"])
    response = api_client.patch(
        f"{EXERCISES_URL}/{entry['id']}",
        json={"load_type": "single_weight", "side_count": 1, "bodyweight_percent": 40},
    )
    assert response.status_code == 200
    with connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT load_type, side_count, bodyweight_percent FROM exercises "
            "WHERE id = 'exercise-1'"
        ).fetchone()
    assert (row["load_type"], row["side_count"], row["bodyweight_percent"]) == (
        "split_weight",
        2,
        None,
    )


# --- delete -----------------------------------------------------------------------------


def test_delete_own_unreferenced_entry(api_client: TestClient) -> None:
    register_and_login(api_client)
    entry = create_exercise(api_client).json()
    response = delete_exercise(api_client, entry["id"])
    assert response.status_code == 204
    assert response.content == b""
    assert api_client.get(f"{EXERCISES_URL}/{entry['id']}").status_code == 404
    assert delete_exercise(api_client, entry["id"]).status_code == 404
    # The freed name is reusable.
    assert create_exercise(api_client, name=entry["name"]).status_code == 201


def test_delete_referenced_entry_conflicts(api_client: TestClient, migrated_db: Path) -> None:
    user_id = register_and_login(api_client)
    entry = create_exercise(api_client).json()
    reference_in_history(migrated_db, user_id=user_id, catalog_id=entry["id"])
    response = delete_exercise(api_client, entry["id"])
    assert response.status_code == 409
    assert problem(response)["code"] == "entry_in_use"
    # The guard left the entry usable.
    assert api_client.get(f"{EXERCISES_URL}/{entry['id']}").status_code == 200


def test_delete_defaults_are_immutable(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = delete_exercise(api_client, "bench-press")
    assert response.status_code == 403
    assert problem(response)["code"] == "default_immutable"
    assert api_client.get(f"{EXERCISES_URL}/bench-press").status_code == 200


def test_delete_foreign_or_unknown_entries_404(make_app) -> None:
    with two_users(make_app) as (alice, bob, _, _):
        entry = create_exercise(alice).json()
        assert delete_exercise(bob, entry["id"]).status_code == 404
        assert delete_exercise(alice, "does-not-exist").status_code == 404
        assert alice.get(f"{EXERCISES_URL}/{entry['id']}").status_code == 200


def test_delete_requires_json_content_type(make_app) -> None:
    app = make_app()
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        register_and_login(client)
        entry = create_exercise(client).json()
        response = client.delete(f"{EXERCISES_URL}/{entry['id']}")
        assert response.status_code == 415
        assert problem(response)["code"] == "json_required"
        assert client.get(f"{EXERCISES_URL}/{entry['id']}").status_code == 200


def test_mutating_exercise_requests_follow_csrf_conventions(make_app) -> None:
    app = make_app()
    with TestClient(app) as client:  # no Origin header at all
        missing_origin = client.post(EXERCISES_URL, json=entry_payload())
        assert missing_origin.status_code == 403
        assert problem(missing_origin)["code"] == "origin_not_allowed"
        response = client.post(
            EXERCISES_URL,
            content=b"{}",
            headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
        )
        assert response.status_code == 415
        assert problem(response)["code"] == "json_required"


# --- UTF-8 and shared conventions ---------------------------------------------------------


def test_utf8_names_roundtrip_unescaped(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = create_exercise(api_client, name="💪 Бицепс-молот")
    assert response.status_code == 201
    # Responses are UTF-8, not \\u-escaped ASCII.
    assert "💪 Бицепс-молот" in response.text
    entry_id = response.json()["id"]
    fetched = api_client.get(f"{EXERCISES_URL}/{entry_id}")
    assert fetched.json()["name"] == "💪 Бицепс-молот"
    found = api_client.get(EXERCISES_URL, params={"search": "бицепс"}).json()
    assert [item["id"] for item in found["items"]] == [entry_id]


def test_problem_documents_follow_conventions(api_client: TestClient) -> None:
    register_and_login(api_client)
    response = api_client.get(f"{EXERCISES_URL}/does-not-exist")
    body = problem(response)
    assert response.status_code == 404
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
