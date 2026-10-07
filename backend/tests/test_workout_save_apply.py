"""Stage 6b atomic graph-replacement tests (Gate G6b).

Each test opens a real write transaction, runs the Stage 6a validation, calls
the internal Stage 6b ``apply_validated_graph``, commits, and reads the
authoritative state back. Coverage: empty replacement; add/remove/swap/reverse
ordering of exercises and sets; moving both levels plus add/remove in one save;
adding in the middle; retained snapshot/catalog-identity preservation; new
snapshot copying; metadata/bodyweight persistence and clearing; untouched
lifecycle/receipt fields; cross-parent and global-id rejection before mutation;
and a deterministic mid-mutation rollback injected with a test-local SQLite
``TEMP TRIGGER``. The public PUT route and receipt/revision/finish behavior
arrive only in Stage 6c, so none is exercised here.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from helpers import insert_exercise, insert_set, insert_user, insert_workout

from app.db import connect, write_transaction
from app.schemas.workouts import SaveWorkoutRequest
from app.services.workouts import (
    GraphConflictError,
    ValidatedSaveGraph,
    WorkoutGraph,
    apply_validated_graph,
    get_workout_graph,
    validate_save_graph,
)

WORKOUT = "workout-1"
OWNER = "user-1"
CATALOG = "bench-press"


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


EXERCISE_A = uid(1)
EXERCISE_B = uid(2)
EXERCISE_C = uid(3)
SET_A1 = uid(11)
SET_A2 = uid(12)
SET_A3 = uid(13)
SET_B1 = uid(21)
SET_C1 = uid(31)
SET_NEW = uid(41)


def set_req(set_id: str, **overrides: Any) -> dict[str, Any]:
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


def exercise_req(
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


def save_req(exercises: list[dict[str, Any]], **overrides: Any) -> SaveWorkoutRequest:
    payload: dict[str, Any] = {
        "revision": 0,
        "save_id": uid(9999),
        "name": None,
        "notes": None,
        "bodyweight_kg": None,
        "ended_at": None,
        "exercises": exercises,
    }
    payload.update(overrides)
    return SaveWorkoutRequest.model_validate(payload)


@pytest.fixture()
def apply_db(migrated_db: Path) -> Path:
    """A migrated db with an owned workout carrying receipt/lifecycle state.

    The workout starts with a non-zero revision and a prior save receipt so the
    tests can prove Stage 6b leaves those protocol fields untouched.
    """
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, OWNER)
        insert_user(conn, "user-2")
        insert_workout(
            conn,
            WORKOUT,
            user_id=OWNER,
            revision=5,
            bodyweight_kg=70,
            last_save_id="prev-save-id",
            last_save_hash="prev-save-hash",
        )
        insert_workout(conn, "workout-foreign", user_id="user-2")
    return migrated_db


def seed_exercise(
    conn: sqlite3.Connection,
    exercise_id: str,
    *,
    order_index: int,
    catalog_id: str = CATALOG,
    load_type: str = "single_weight",
    bodyweight_percent: int | None = None,
    side_count: int = 1,
    set_ids: tuple[str, ...] = (),
) -> None:
    insert_exercise(
        conn,
        exercise_id,
        workout_id=WORKOUT,
        catalog_id=catalog_id,
        order_index=order_index,
        load_type=load_type,
        bodyweight_percent=bodyweight_percent,
        side_count=side_count,
    )
    for index, set_id in enumerate(set_ids):
        insert_set(conn, set_id, exercise_id=exercise_id, set_index=index)


def apply_save(db: Path, payload: SaveWorkoutRequest, *, workout_id: str = WORKOUT) -> None:
    """Validate then apply inside one write transaction, then commit."""
    with connect(db) as conn, write_transaction(conn):
        graph = validate_save_graph(conn, owner_id=OWNER, workout_id=workout_id, payload=payload)
        apply_validated_graph(conn, workout_id=workout_id, graph=graph)


def read_graph(db: Path, *, workout_id: str = WORKOUT) -> WorkoutGraph:
    graph = get_workout_graph(db, workout_id, user_id=OWNER)
    assert graph is not None
    return graph


def exercise_order(graph: WorkoutGraph) -> list[tuple[str, int]]:
    return [(exercise.id, exercise.order_index) for exercise in graph.exercises]


def set_order(graph: WorkoutGraph, exercise_id: str) -> list[tuple[str, int]]:
    for exercise in graph.exercises:
        if exercise.id == exercise_id:
            return [(item.id, item.set_index) for item in exercise.sets]
    raise AssertionError(f"exercise {exercise_id} not in graph")


def workout_row(db: Path, *, workout_id: str = WORKOUT) -> sqlite3.Row:
    with connect(db) as conn:
        row = conn.execute(
            "SELECT name, notes, bodyweight_kg, ended_at, revision, last_save_id, "
            "last_save_hash, started_at, created_at, updated_at FROM workouts WHERE id = :id",
            {"id": workout_id},
        ).fetchone()
    assert row is not None
    return cast(sqlite3.Row, row)


def database_state(db: Path) -> tuple[tuple[object, ...], ...]:
    with connect(db) as conn:
        rows: list[tuple[object, ...]] = []
        for table in ("workouts", "exercise_catalog", "exercises", "sets"):
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall():
                rows.append((table, *tuple(row)))
    return tuple(rows)


def test_apply_requires_an_active_transaction(apply_db: Path) -> None:
    empty_graph = ValidatedSaveGraph(
        revision=0,
        save_id=uid(9999),
        name=None,
        notes=None,
        bodyweight_kg=None,
        ended_at=None,
        exercises=(),
    )
    with connect(apply_db) as conn, pytest.raises(RuntimeError, match="active transaction"):
        apply_validated_graph(conn, workout_id=WORKOUT, graph=empty_graph)


def test_empty_replacement_clears_graph_and_keeps_protocol_fields(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))

    apply_save(apply_db, save_req([], name="Emptied", notes="cleared", bodyweight_kg=88))

    graph = read_graph(apply_db)
    assert graph.exercises == ()
    row = workout_row(apply_db)
    assert (row["name"], row["notes"], row["bodyweight_kg"]) == ("Emptied", "cleared", 88)
    # Stage 6c-owned protocol fields stay exactly as seeded.
    assert (row["revision"], row["last_save_id"], row["last_save_hash"]) == (
        5,
        "prev-save-id",
        "prev-save-hash",
    )
    assert row["ended_at"] is None
    assert row["updated_at"] == row["started_at"]


def test_add_new_exercise_with_new_sets(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1,))

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(EXERCISE_A, sets=[set_req(SET_A1)]),
                exercise_req(EXERCISE_B, sets=[set_req(SET_B1), set_req(SET_C1)]),
            ]
        ),
    )

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_A, 0), (EXERCISE_B, 1)]
    assert set_order(graph, EXERCISE_A) == [(SET_A1, 0)]
    assert set_order(graph, EXERCISE_B) == [(SET_B1, 0), (SET_C1, 1)]
    # A new bench-press instance copies the catalog snapshot.
    new_exercise = graph.exercises[1]
    assert (new_exercise.load_type, new_exercise.bodyweight_percent, new_exercise.side_count) == (
        "single_weight",
        None,
        1,
    )


def test_add_new_exercise_in_the_middle_reindexes_dense(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0)
        seed_exercise(conn, EXERCISE_B, order_index=1)

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(EXERCISE_A),
                exercise_req(EXERCISE_C),
                exercise_req(EXERCISE_B),
            ]
        ),
    )

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_A, 0), (EXERCISE_C, 1), (EXERCISE_B, 2)]


def test_remove_exercise_and_its_sets_cascade(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))

    # Keep only A; B (and its sets) are omitted and must disappear.
    apply_save(apply_db, save_req([exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])]))

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_A, 0)]
    # SET_A2 was omitted from the retained exercise and is deleted too.
    assert set_order(graph, EXERCISE_A) == [(SET_A1, 0)]


def test_remove_sets_from_retained_exercise(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2, SET_A3))

    apply_save(
        apply_db,
        save_req([exercise_req(EXERCISE_A, sets=[set_req(SET_A3), set_req(SET_A1)])]),
    )

    graph = read_graph(apply_db)
    # Retained sets reindex dense in submitted order; SET_A2 is gone.
    assert set_order(graph, EXERCISE_A) == [(SET_A3, 0), (SET_A1, 1)]


def test_swap_exercise_order(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1,))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(EXERCISE_B, sets=[set_req(SET_B1)]),
                exercise_req(EXERCISE_A, sets=[set_req(SET_A1)]),
            ]
        ),
    )

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_B, 0), (EXERCISE_A, 1)]
    assert set_order(graph, EXERCISE_A) == [(SET_A1, 0)]
    assert set_order(graph, EXERCISE_B) == [(SET_B1, 0)]


def test_reverse_exercise_order(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0)
        seed_exercise(conn, EXERCISE_B, order_index=1)
        seed_exercise(conn, EXERCISE_C, order_index=2)

    apply_save(
        apply_db,
        save_req([exercise_req(EXERCISE_C), exercise_req(EXERCISE_B), exercise_req(EXERCISE_A)]),
    )

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_C, 0), (EXERCISE_B, 1), (EXERCISE_A, 2)]


def test_swap_and_reverse_set_order_within_exercise(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2, SET_A3))

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(
                    EXERCISE_A,
                    sets=[set_req(SET_A3), set_req(SET_A2), set_req(SET_A1)],
                )
            ]
        ),
    )

    graph = read_graph(apply_db)
    assert set_order(graph, EXERCISE_A) == [(SET_A3, 0), (SET_A2, 1), (SET_A1, 2)]


def test_move_both_levels_with_add_and_remove_in_one_save(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))

    # Reverse exercises, drop SET_A1, add a new set to A, and add a new exercise.
    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(EXERCISE_C, sets=[set_req(SET_C1)]),
                exercise_req(EXERCISE_B, sets=[set_req(SET_B1)]),
                exercise_req(EXERCISE_A, sets=[set_req(SET_A2), set_req(SET_NEW)]),
            ]
        ),
    )

    graph = read_graph(apply_db)
    assert exercise_order(graph) == [(EXERCISE_C, 0), (EXERCISE_B, 1), (EXERCISE_A, 2)]
    assert set_order(graph, EXERCISE_A) == [(SET_A2, 0), (SET_NEW, 1)]
    assert set_order(graph, EXERCISE_B) == [(SET_B1, 0)]
    assert set_order(graph, EXERCISE_C) == [(SET_C1, 0)]


def test_retained_exercise_snapshot_and_catalog_identity_are_preserved(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        # Stored snapshot deliberately differs from the bench-press catalog
        # default (single_weight/NULL/1) and must remain authoritative.
        seed_exercise(
            conn,
            EXERCISE_A,
            order_index=0,
            catalog_id=CATALOG,
            load_type="split_weight",
            bodyweight_percent=40,
            side_count=1,
        )
        insert_set(
            conn,
            SET_A1,
            exercise_id=EXERCISE_A,
            set_index=0,
            reps=6,
            weight_kg=10,
            bw_percent_override=50,
            side="left",
        )

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(
                    EXERCISE_A,
                    notes="kept",
                    sets=[
                        set_req(SET_A1, reps=6, weight_kg=10, bw_percent_override=50, side="left")
                    ],
                )
            ]
        ),
    )

    graph = read_graph(apply_db)
    retained = graph.exercises[0]
    assert retained.notes == "kept"
    assert (retained.load_type, retained.bodyweight_percent, retained.side_count) == (
        "split_weight",
        40,
        1,
    )
    assert retained.catalog_id == CATALOG
    assert set_order(graph, EXERCISE_A) == [(SET_A1, 0)]


def test_retained_set_values_are_updated_in_place(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1,))

    apply_save(
        apply_db,
        save_req(
            [
                exercise_req(
                    EXERCISE_A,
                    sets=[set_req(SET_A1, reps=12, weight_kg=60, rpe=9, done=True)],
                )
            ]
        ),
    )

    stored_set = read_graph(apply_db).exercises[0].sets[0]
    assert (stored_set.reps, stored_set.weight_kg, stored_set.rpe, stored_set.done) == (
        12,
        60,
        9,
        True,
    )
    assert stored_set.exercise_id == EXERCISE_A


def test_metadata_and_bodyweight_persist_and_can_clear(apply_db: Path) -> None:
    apply_save(apply_db, save_req([], name="Push day", notes="felt strong", bodyweight_kg=82))
    row = workout_row(apply_db)
    assert (row["name"], row["notes"], row["bodyweight_kg"]) == ("Push day", "felt strong", 82)

    # A later save may clear bodyweight and notes explicitly.
    apply_save(apply_db, save_req([], name="Push day", notes=None, bodyweight_kg=None))
    row = workout_row(apply_db)
    assert (row["name"], row["notes"], row["bodyweight_kg"]) == ("Push day", None, None)


def test_lifecycle_and_receipt_fields_are_never_written(apply_db: Path) -> None:
    before = workout_row(apply_db)
    apply_save(
        apply_db,
        save_req([exercise_req(EXERCISE_A)], name="x", notes="y", bodyweight_kg=75),
    )
    after = workout_row(apply_db)
    assert after["revision"] == before["revision"] == 5
    assert after["last_save_id"] == before["last_save_id"] == "prev-save-id"
    assert after["last_save_hash"] == before["last_save_hash"] == "prev-save-hash"
    assert after["ended_at"] == before["ended_at"] is None
    assert after["started_at"] == before["started_at"]
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] == before["updated_at"]


@pytest.mark.parametrize(
    "overflow_sql",
    [
        f"UPDATE exercises SET order_index = 9223372036854775807 WHERE id = '{EXERCISE_A}'",
        f"UPDATE sets SET set_index = 9223372036854775807 WHERE id = '{SET_A1}'",
    ],
    ids=["exercise", "set"],
)
def test_temporary_index_overflow_is_rejected_before_mutation(
    apply_db: Path, overflow_sql: str
) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1,))
        conn.execute(overflow_sql)

    payload = save_req(
        [exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
        name="must not stick",
    )
    with connect(apply_db) as conn, write_transaction(conn):
        graph = validate_save_graph(conn, owner_id=OWNER, workout_id=WORKOUT, payload=payload)
        changes_before = conn.total_changes
        with pytest.raises(OverflowError, match="SQLite INTEGER range"):
            apply_validated_graph(conn, workout_id=WORKOUT, graph=graph)
        assert conn.total_changes == changes_before

    assert workout_row(apply_db)["name"] is None


def test_cross_parent_set_id_is_rejected_before_mutation(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1,))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))
    before = database_state(apply_db)

    # Try to move SET_A1 (stored under A) onto B: a cross-parent id.
    with pytest.raises(GraphConflictError):
        apply_save(
            apply_db,
            save_req(
                [
                    exercise_req(EXERCISE_A, sets=[]),
                    exercise_req(EXERCISE_B, sets=[set_req(SET_A1)]),
                ]
            ),
        )
    assert database_state(apply_db) == before


def test_global_exercise_id_collision_is_rejected_before_mutation(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0)
        # A foreign workout already owns EXERCISE_B.
        insert_exercise(conn, EXERCISE_B, workout_id="workout-foreign", order_index=0)
    before = database_state(apply_db)

    with pytest.raises(GraphConflictError):
        apply_save(apply_db, save_req([exercise_req(EXERCISE_A), exercise_req(EXERCISE_B)]))
    assert database_state(apply_db) == before


def test_mid_mutation_failure_rolls_back_the_entire_save(apply_db: Path) -> None:
    with connect(apply_db) as conn, write_transaction(conn):
        seed_exercise(conn, EXERCISE_A, order_index=0, set_ids=(SET_A1, SET_A2))
        seed_exercise(conn, EXERCISE_B, order_index=1, set_ids=(SET_B1,))
    before = database_state(apply_db)

    # Reorder exercises, omit SET_A2, retain A and B, and add a new exercise C
    # with a new set. The trigger fires on the final new-set insert, after the
    # deletes, temporary moves, retained updates, and new-exercise insert.
    payload = save_req(
        [
            exercise_req(EXERCISE_B, sets=[set_req(SET_B1)]),
            exercise_req(EXERCISE_A, sets=[set_req(SET_A1)]),
            exercise_req(EXERCISE_C, sets=[set_req(SET_C1)]),
        ],
        name="should not stick",
        bodyweight_kg=90,
    )

    with connect(apply_db) as conn:
        conn.execute(
            "CREATE TEMP TRIGGER fail_new_set BEFORE INSERT ON sets "
            "BEGIN SELECT RAISE(ABORT, 'injected mid-mutation failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected"), write_transaction(conn):
            graph = validate_save_graph(conn, owner_id=OWNER, workout_id=WORKOUT, payload=payload)
            apply_validated_graph(conn, workout_id=WORKOUT, graph=graph)

    assert database_state(apply_db) == before
