"""Stage 6a transaction-bound workout graph validation tests (Gate G6a).

Real-SQLite coverage verifies owner/parent classification, global nested-id
collision handling, catalog visibility, immutable snapshot selection, and all
set rules that depend on those snapshots. The helper is deliberately internal
and read-only; the public PUT route arrives only after Stage 6c.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    insert_catalog_entry,
    insert_exercise,
    insert_set,
    insert_user,
    insert_workout,
)

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.workouts import SaveWorkoutRequest
from app.services.workouts import (
    CatalogUnavailableError,
    GraphConflictError,
    GraphValidationError,
    ValidatedSaveGraph,
    WorkoutNotFoundError,
    validate_save_graph,
)


def uid(value: int) -> str:
    return str(uuid.UUID(int=value))


EXERCISE_1 = uid(1)
EXERCISE_2 = uid(2)
EXERCISE_3 = uid(3)
SET_1 = uid(101)
SET_2 = uid(102)
SET_3 = uid(103)


def set_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": SET_1,
        "reps": 8,
        "weight_kg": 12,
        "bw_percent_override": None,
        "rpe": None,
        "side": "bilateral",
        "done": True,
    }
    payload.update(overrides)
    return payload


def exercise_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": EXERCISE_1,
        "catalog_id": "bench-press",
        "notes": None,
        "sets": [],
    }
    payload.update(overrides)
    return payload


def save_payload(*, exercises: list[dict[str, Any]], **overrides: Any) -> SaveWorkoutRequest:
    payload: dict[str, Any] = {
        "revision": 0,
        "save_id": uid(1000),
        "name": None,
        "notes": None,
        "bodyweight_kg": None,
        "ended_at": None,
        "exercises": exercises,
    }
    payload.update(overrides)
    return SaveWorkoutRequest.model_validate(payload)


@pytest.fixture()
def save_db(migrated_db: Path) -> Path:
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, "user-1")
        insert_user(conn, "user-2")
        insert_workout(conn, "workout-1", user_id="user-1")
        insert_workout(conn, "workout-foreign", user_id="user-2")
    return migrated_db


def validate(
    database_path: Path,
    payload: SaveWorkoutRequest,
    *,
    owner_id: str = "user-1",
    workout_id: str = "workout-1",
) -> ValidatedSaveGraph:
    with connect(database_path) as conn, write_transaction(conn):
        return validate_save_graph(
            conn,
            owner_id=owner_id,
            workout_id=workout_id,
            payload=payload,
        )


def database_state(database_path: Path) -> tuple[tuple[object, ...], ...]:
    with connect(database_path) as conn:
        rows: list[tuple[object, ...]] = []
        for table in ("workouts", "exercise_catalog", "exercises", "sets"):
            table_rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            rows.extend((table, *tuple(row)) for row in table_rows)
    return tuple(rows)


def test_validation_requires_the_callers_transaction(save_db: Path) -> None:
    with connect(save_db) as conn, pytest.raises(RuntimeError, match="active transaction"):
        validate_save_graph(
            conn,
            owner_id="user-1",
            workout_id="workout-1",
            payload=save_payload(exercises=[]),
        )


def test_empty_graph_and_explicit_null_metadata_are_valid(save_db: Path) -> None:
    graph = validate(
        save_db,
        save_payload(
            exercises=[],
            name=None,
            notes=None,
            bodyweight_kg=None,
            ended_at=None,
        ),
    )
    assert graph.exercises == ()
    assert (graph.name, graph.notes, graph.bodyweight_kg, graph.ended_at) == (
        None,
        None,
        None,
        None,
    )


def test_resolves_retained_snapshots_and_new_catalog_defaults(save_db: Path) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        # The retained snapshot intentionally differs from the catalog's current
        # split_weight/NULL/2 default and must remain authoritative.
        insert_exercise(
            conn,
            EXERCISE_1,
            workout_id="workout-1",
            catalog_id="dumbbell-curl",
            load_type="split_weight",
            bodyweight_percent=40,
            side_count=1,
        )
        insert_set(
            conn,
            SET_1,
            exercise_id=EXERCISE_1,
            reps=6,
            weight_kg=10,
            bw_percent_override=50,
            side="left",
        )

    payload = save_payload(
        name="  Session  ",
        notes="",
        bodyweight_kg=82,
        exercises=[
            exercise_payload(
                id=EXERCISE_2,
                catalog_id="bench-press",
                notes="new",
                sets=[set_payload(id=SET_3, weight_kg=100)],
            ),
            exercise_payload(
                id=EXERCISE_1.upper(),
                catalog_id="dumbbell-curl",
                notes="retained",
                sets=[
                    set_payload(
                        id=SET_1.upper(),
                        reps=6,
                        weight_kg=10,
                        bw_percent_override=50,
                        side="left",
                    ),
                    set_payload(
                        id=SET_2,
                        reps=None,
                        weight_kg=None,
                        bw_percent_override=60,
                        side="right",
                        done=False,
                    ),
                ],
            ),
        ],
    )
    graph = validate(save_db, payload)

    new, retained = graph.exercises
    assert (new.order_index, new.load_type, new.bodyweight_percent, new.side_count) == (
        0,
        "single_weight",
        None,
        1,
    )
    assert new.is_new is True
    assert new.sets[0].is_new is True
    assert (retained.order_index, retained.load_type, retained.bodyweight_percent) == (
        1,
        "split_weight",
        40,
    )
    assert retained.side_count == 1
    assert retained.is_new is False
    assert [item.is_new for item in retained.sets] == [False, True]
    assert [item.set_index for item in retained.sets] == [0, 1]
    assert (graph.name, graph.notes, graph.bodyweight_kg) == ("  Session  ", "", 82)


def test_new_owned_custom_catalog_snapshot_is_valid(save_db: Path) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "my-split",
            created_by="user-1",
            load_type="split_weight",
            bodyweight_percent=25,
            side_count=1,
        )
    graph = validate(
        save_db,
        save_payload(
            exercises=[
                exercise_payload(
                    catalog_id="my-split",
                    sets=[set_payload(side="right", bw_percent_override=30)],
                )
            ]
        ),
    )
    exercise = graph.exercises[0]
    assert (exercise.load_type, exercise.bodyweight_percent, exercise.side_count) == (
        "split_weight",
        25,
        1,
    )


@pytest.mark.parametrize("workout_id", ["missing", "workout-foreign"])
def test_unknown_and_foreign_workouts_are_indistinguishable(save_db: Path, workout_id: str) -> None:
    before = database_state(save_db)
    with pytest.raises(WorkoutNotFoundError) as excinfo:
        validate(save_db, save_payload(exercises=[]), workout_id=workout_id)
    assert excinfo.value.args == ()
    assert database_state(save_db) == before


@pytest.mark.parametrize("foreign", [False, True])
def test_stored_exercise_id_collisions_are_generic(save_db: Path, foreign: bool) -> None:
    collision_workout = "workout-foreign" if foreign else "workout-other"
    with connect(save_db) as conn, write_transaction(conn):
        if not foreign:
            insert_workout(conn, collision_workout, user_id="user-1")
        insert_exercise(conn, EXERCISE_1, workout_id=collision_workout)
    before = database_state(save_db)
    with pytest.raises(GraphConflictError) as excinfo:
        validate(
            save_db,
            save_payload(exercises=[exercise_payload(sets=[set_payload()])]),
        )
    assert excinfo.value.args == ()
    assert database_state(save_db) == before


@pytest.mark.parametrize("foreign", [False, True])
def test_stored_set_id_collisions_are_generic(save_db: Path, foreign: bool) -> None:
    collision_workout = "workout-foreign" if foreign else "workout-other"
    collision_exercise = EXERCISE_2
    with connect(save_db) as conn, write_transaction(conn):
        if not foreign:
            insert_workout(conn, collision_workout, user_id="user-1")
        insert_exercise(conn, EXERCISE_1, workout_id="workout-1")
        insert_exercise(conn, collision_exercise, workout_id=collision_workout)
        insert_set(conn, SET_1, exercise_id=collision_exercise)
    before = database_state(save_db)
    with pytest.raises(GraphConflictError) as excinfo:
        validate(
            save_db,
            save_payload(exercises=[exercise_payload(sets=[set_payload()])]),
        )
    assert excinfo.value.args == ()
    assert database_state(save_db) == before


def test_retained_exercise_cannot_change_catalog_identity(save_db: Path) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_exercise(conn, EXERCISE_1, workout_id="workout-1", catalog_id="bench-press")
    before = database_state(save_db)
    with pytest.raises(GraphConflictError):
        validate(
            save_db,
            save_payload(exercises=[exercise_payload(catalog_id="overhead-press")]),
        )
    assert database_state(save_db) == before


@pytest.mark.parametrize("catalog_id", ["missing-catalog", "foreign-custom"])
def test_unknown_and_foreign_catalog_rows_are_indistinguishable(
    save_db: Path, catalog_id: str
) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "foreign-custom",
            name="Foreign custom",
            created_by="user-2",
            load_type="single_weight",
            side_count=1,
        )
    before = database_state(save_db)
    with pytest.raises(CatalogUnavailableError) as excinfo:
        validate(
            save_db,
            save_payload(exercises=[exercise_payload(catalog_id=catalog_id)]),
        )
    assert excinfo.value.args == ()
    assert database_state(save_db) == before


def test_full_allowed_side_matrix(save_db: Path) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "one-sided-split",
            load_type="split_weight",
            side_count=1,
            created_by="user-1",
        )
    graph = validate(
        save_db,
        save_payload(
            exercises=[
                exercise_payload(
                    id=EXERCISE_1,
                    catalog_id="one-sided-split",
                    sets=[set_payload(id=SET_1, side="left")],
                ),
                exercise_payload(
                    id=EXERCISE_2,
                    catalog_id="one-sided-split",
                    sets=[set_payload(id=SET_2, side="right")],
                ),
                exercise_payload(
                    id=EXERCISE_3,
                    catalog_id="dumbbell-curl",
                    sets=[set_payload(id=SET_3, side="bilateral")],
                ),
                exercise_payload(
                    id=uid(4),
                    catalog_id="bench-press",
                    sets=[set_payload(id=uid(104), side="bilateral")],
                ),
                exercise_payload(
                    id=uid(5),
                    catalog_id="pull-up",
                    sets=[set_payload(id=uid(105), side="bilateral", weight_kg=None)],
                ),
            ]
        ),
    )
    assert len(graph.exercises) == 5


@pytest.mark.parametrize(
    ("catalog_id", "side"),
    [
        ("one-sided-split", "bilateral"),
        ("dumbbell-curl", "left"),
        ("bench-press", "right"),
        ("pull-up", "left"),
    ],
)
def test_invalid_sides_report_only_the_field_path(
    save_db: Path, catalog_id: str, side: str
) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "one-sided-split",
            load_type="split_weight",
            side_count=1,
            created_by="user-1",
        )
    before = database_state(save_db)
    weight = None if catalog_id == "pull-up" else 12
    with pytest.raises(GraphValidationError) as excinfo:
        validate(
            save_db,
            save_payload(
                exercises=[
                    exercise_payload(
                        catalog_id=catalog_id,
                        sets=[set_payload(side=side, weight_kg=weight)],
                    )
                ]
            ),
        )
    assert excinfo.value.field == "exercises.0.sets.0.side"
    assert side not in str(excinfo.value)
    assert database_state(save_db) == before


def test_override_permission_uses_snapshot_not_draft_weight(save_db: Path) -> None:
    with connect(save_db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "weighted-bodyweight",
            load_type="single_weight",
            bodyweight_percent=30,
            side_count=1,
            created_by="user-1",
        )
    graph = validate(
        save_db,
        save_payload(
            exercises=[
                exercise_payload(
                    catalog_id="weighted-bodyweight",
                    sets=[
                        set_payload(
                            reps=None,
                            weight_kg=None,
                            bw_percent_override=50,
                            done=False,
                        )
                    ],
                ),
                exercise_payload(
                    id=EXERCISE_2,
                    catalog_id="pull-up",
                    sets=[
                        set_payload(
                            id=SET_2,
                            weight_kg=None,
                            bw_percent_override=75,
                        )
                    ],
                ),
            ]
        ),
    )
    assert [item.sets[0].bw_percent_override for item in graph.exercises] == [50, 75]


def test_override_without_snapshot_contribution_is_invalid(save_db: Path) -> None:
    with pytest.raises(GraphValidationError) as excinfo:
        validate(
            save_db,
            save_payload(
                exercises=[
                    exercise_payload(
                        catalog_id="bench-press",
                        sets=[set_payload(bw_percent_override=50)],
                    )
                ]
            ),
        )
    assert excinfo.value.field == "exercises.0.sets.0.bw_percent_override"


def test_bodyweight_sets_require_null_external_weight(save_db: Path) -> None:
    with pytest.raises(GraphValidationError) as excinfo:
        validate(
            save_db,
            save_payload(
                exercises=[
                    exercise_payload(
                        catalog_id="pull-up",
                        sets=[set_payload(weight_kg=1)],
                    )
                ]
            ),
        )
    assert excinfo.value.field == "exercises.0.sets.0.weight_kg"


@pytest.mark.parametrize(
    ("catalog_id", "overrides", "field"),
    [
        ("bench-press", {"reps": None}, "reps"),
        ("bench-press", {"reps": 0}, "reps"),
        ("bench-press", {"weight_kg": None}, "weight_kg"),
        ("pull-up", {"reps": None, "weight_kg": None}, "reps"),
        ("pull-up", {"reps": 0, "weight_kg": None}, "reps"),
    ],
)
def test_completed_sets_require_complete_load_inputs(
    save_db: Path,
    catalog_id: str,
    overrides: dict[str, Any],
    field: str,
) -> None:
    with pytest.raises(GraphValidationError) as excinfo:
        validate(
            save_db,
            save_payload(
                exercises=[
                    exercise_payload(
                        catalog_id=catalog_id,
                        sets=[set_payload(**overrides)],
                    )
                ]
            ),
        )
    assert excinfo.value.field == f"exercises.0.sets.0.{field}"


def test_set_derivations_must_stay_in_the_safe_integer_range(save_db: Path) -> None:
    with pytest.raises(GraphValidationError) as excinfo:
        validate(
            save_db,
            save_payload(
                exercises=[exercise_payload(sets=[set_payload(reps=2, weight_kg=MAX_SAFE_INTEGER)])]
            ),
        )
    assert excinfo.value.field == "exercises.0.sets.0"
    assert "safe integer range" in str(excinfo.value)


def test_drafts_and_completed_bodyweight_with_unknown_workout_weight_are_valid(
    save_db: Path,
) -> None:
    graph = validate(
        save_db,
        save_payload(
            bodyweight_kg=None,
            exercises=[
                exercise_payload(
                    catalog_id="bench-press",
                    sets=[
                        set_payload(
                            reps=None,
                            weight_kg=None,
                            done=False,
                        )
                    ],
                ),
                exercise_payload(
                    id=EXERCISE_2,
                    catalog_id="pull-up",
                    sets=[set_payload(id=SET_2, reps=5, weight_kg=None, done=True)],
                ),
            ],
        ),
    )
    assert graph.bodyweight_kg is None
    assert graph.exercises[0].sets[0].done is False
    assert graph.exercises[1].sets[0].done is True
