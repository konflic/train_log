"""Stage 7 delete-lifecycle service tests (Gate G7).

Direct-SQLite coverage of `delete_workout`: exact-revision hard deletion of
active and finished workouts with `ON DELETE CASCADE` removal of descendant
exercises and sets; catalog-reference release so a guarded custom entry becomes
deletable after the workout is gone; stale and future revisions raising
`RevisionConflictError` without any mutation, including after a save incremented
the stored revision; missing, foreign, and already-deleted ids being
indistinguishable `WorkoutNotFoundError`s; and the held-lock busy timeout
leaving the database unchanged before a successful retry.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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

from app.db import DatabaseBusyError, connect, write_transaction
from app.schemas.workouts import SaveWorkoutRequest
from app.services import catalog, workouts
from app.services.workouts import RevisionConflictError, WorkoutNotFoundError

TS = "2026-01-01T00:00:00Z"
OWNER = "user-1"
WORKOUT = "workout-1"
FOREIGN_WORKOUT = "workout-foreign"
CUSTOM_ENTRY = "cat-custom"


@pytest.fixture()
def delete_db(migrated_db: Path) -> Path:
    """The migrated database with the owner and one foreign user."""
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, OWNER, bodyweight_default_kg=80)
        insert_user(conn, "user-2")
    return migrated_db


def seed_workout(
    db: Path,
    workout_id: str = WORKOUT,
    *,
    user_id: str = OWNER,
    revision: int = 0,
    ended_at: str | None = None,
    catalog_id: str = "dumbbell-curl",
    with_graph: bool = True,
) -> None:
    """One workout plus two exercises (three sets) referencing `catalog_id`."""
    with connect(db) as conn, write_transaction(conn):
        insert_workout(
            conn,
            workout_id,
            user_id=user_id,
            started_at=TS,
            ended_at=ended_at,
            revision=revision,
        )
        if not with_graph:
            return
        insert_exercise(
            conn,
            "exercise-a",
            workout_id=workout_id,
            catalog_id=catalog_id,
            order_index=0,
            load_type="split_weight",
            side_count=2,
        )
        insert_set(conn, "set-a-0", exercise_id="exercise-a", set_index=0)
        insert_set(conn, "set-a-1", exercise_id="exercise-a", set_index=1, reps=10, rpe=8)
        insert_exercise(
            conn,
            "exercise-b",
            workout_id=workout_id,
            catalog_id="pull-up",
            order_index=1,
            load_type="bodyweight",
            bodyweight_percent=100,
            side_count=1,
        )
        insert_set(conn, "set-b-0", exercise_id="exercise-b", set_index=0, reps=6, weight_kg=None)


def delete(db: Path, *, owner_id: str = OWNER, workout_id: str = WORKOUT, revision: int) -> None:
    workouts.delete_workout(db, owner_id=owner_id, workout_id=workout_id, revision=revision)


def row_counts(db: Path) -> dict[str, int]:
    with connect(db) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("workouts", "exercises", "sets")
        }


def database_state(db: Path) -> tuple[tuple[object, ...], ...]:
    with connect(db) as conn:
        rows: list[tuple[object, ...]] = []
        for table in ("workouts", "exercise_catalog", "exercises", "sets"):
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall():
                rows.append((table, *tuple(row)))
    return tuple(rows)


# --- accepted deletions ---------------------------------------------------------


def test_delete_active_workout_cascades_the_full_graph(delete_db: Path) -> None:
    seed_workout(delete_db)
    seed_workout(delete_db, FOREIGN_WORKOUT, user_id="user-2", with_graph=False)
    delete(delete_db, revision=0)
    assert workouts.get_workout_graph(delete_db, WORKOUT, user_id=OWNER) is None
    # The cascade removed every descendant; the foreign row is untouched.
    assert row_counts(delete_db) == {"workouts": 1, "exercises": 0, "sets": 0}
    with connect(delete_db) as conn:
        remaining = conn.execute("SELECT id FROM workouts").fetchall()
    assert [str(row["id"]) for row in remaining] == [FOREIGN_WORKOUT]


def test_delete_finished_workout(delete_db: Path) -> None:
    seed_workout(delete_db, revision=2, ended_at="2026-01-01T09:30:00Z")
    delete(delete_db, revision=2)
    assert workouts.get_workout_graph(delete_db, WORKOUT, user_id=OWNER) is None
    assert row_counts(delete_db) == {"workouts": 0, "exercises": 0, "sets": 0}


def test_delete_releases_the_catalog_reference(delete_db: Path) -> None:
    with connect(delete_db) as conn, write_transaction(conn):
        insert_catalog_entry(conn, CUSTOM_ENTRY, created_by=OWNER)
    seed_workout(delete_db, catalog_id=CUSTOM_ENTRY)
    # The entry is guarded while workout history references it...
    with pytest.raises(catalog.EntryInUseError):
        catalog.delete_custom_entry(delete_db, CUSTOM_ENTRY, owner_id=OWNER)
    delete(delete_db, revision=0)
    # ...and deletable once the referencing workout is gone.
    assert catalog.delete_custom_entry(delete_db, CUSTOM_ENTRY, owner_id=OWNER) is True


# --- revision conflicts -----------------------------------------------------------


def test_stale_revision_conflicts_without_mutation(delete_db: Path) -> None:
    seed_workout(delete_db, revision=2)
    before = database_state(delete_db)
    with pytest.raises(RevisionConflictError) as excinfo:
        delete(delete_db, revision=1)
    assert excinfo.value.current_revision == 2
    assert database_state(delete_db) == before


def test_future_revision_conflicts_without_mutation(delete_db: Path) -> None:
    seed_workout(delete_db, revision=2)
    before = database_state(delete_db)
    with pytest.raises(RevisionConflictError) as excinfo:
        delete(delete_db, revision=3)
    assert excinfo.value.current_revision == 2
    assert database_state(delete_db) == before


def test_save_increment_requires_the_new_revision(delete_db: Path) -> None:
    seed_workout(delete_db)
    payload = SaveWorkoutRequest.model_validate(
        {
            "revision": 0,
            "save_id": str(uuid.uuid4()),
            "name": "saved",
            "notes": None,
            "bodyweight_kg": None,
            "ended_at": None,
            "exercises": [],
        }
    )
    graph = workouts.save_workout(delete_db, owner_id=OWNER, workout_id=WORKOUT, payload=payload)
    assert graph.workout.revision == 1
    with connect(delete_db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM workout_save_previous_performance").fetchone()[0]
            == 1
        )
    # The delete at the superseded base revision fails atomically...
    before = database_state(delete_db)
    with pytest.raises(RevisionConflictError) as excinfo:
        delete(delete_db, revision=0)
    assert excinfo.value.current_revision == 1
    assert database_state(delete_db) == before
    # ...and the incremented revision deletes.
    delete(delete_db, revision=1)
    assert workouts.get_workout_graph(delete_db, WORKOUT, user_id=OWNER) is None
    with connect(delete_db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM workout_save_previous_performance").fetchone()[0]
            == 0
        )


# --- not-found outcomes ------------------------------------------------------------


def test_missing_foreign_and_deleted_ids_are_not_found(delete_db: Path) -> None:
    seed_workout(delete_db)
    seed_workout(delete_db, FOREIGN_WORKOUT, user_id="user-2", with_graph=False)
    with pytest.raises(WorkoutNotFoundError):
        delete(delete_db, workout_id="no-such-workout", revision=0)
    # A foreign row is indistinguishable even at its exact stored revision...
    with pytest.raises(WorkoutNotFoundError):
        delete(delete_db, workout_id=FOREIGN_WORKOUT, revision=0)
    # ...and stays untouched.
    assert workouts.get_workout_graph(delete_db, FOREIGN_WORKOUT, user_id="user-2") is not None
    # A retry after a successful but unobserved deletion is an ordinary 404
    # path: there is no tombstone or receipt.
    delete(delete_db, revision=0)
    with pytest.raises(WorkoutNotFoundError):
        delete(delete_db, revision=0)


# --- retryable busy timeout ----------------------------------------------------------


def test_held_write_lock_times_out_retryably_and_retry_succeeds(
    delete_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_workout(delete_db)
    before = database_state(delete_db)
    real_connect = workouts.connect

    @contextmanager
    def impatient_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, busy_timeout_ms=50, **kwargs) as conn:
            yield conn

    with connect(delete_db) as holder:
        # Hold the write lock outside any helper transaction until the delete
        # attempt has provably failed; no timing-only sleeps are involved.
        holder.execute("BEGIN IMMEDIATE")
        try:
            monkeypatch.setattr(workouts, "connect", impatient_connect)
            with pytest.raises(DatabaseBusyError):
                delete(delete_db, revision=0)
        finally:
            holder.execute("ROLLBACK")

    # The timeout left no partial mutation.
    assert database_state(delete_db) == before

    # After release, the identical delete succeeds with the production timeout.
    monkeypatch.setattr(workouts, "connect", real_connect)
    delete(delete_db, revision=0)
    assert workouts.get_workout_graph(delete_db, WORKOUT, user_id=OWNER) is None
