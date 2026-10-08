"""Stage 5 workout service tests (Gate G5).

Direct-SQLite coverage of idempotent creation (bodyweight snapshot, revision 0,
canonical fingerprint, retry vs. conflict vs. cross-user conflict), history
listing (owner scoping, status/local-date filters with UTC-offset resolution,
newest-first stable order with id tie-break, pagination bounds), and graph
reads (fixed query count, nested ordering, foreign/unknown are None).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from helpers import insert_exercise, insert_set, insert_user, insert_workout

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.services import workouts
from app.services.workouts import CreateConflictError

TS = "2026-01-01T00:00:00Z"
HEX64_RE = re.compile(r"[0-9a-f]{64}")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@pytest.fixture()
def two_users(migrated_db: Path) -> Path:
    """The migrated database with `user-1` (80 kg default) and `user-2`."""
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, "user-1", bodyweight_default_kg=80)
        insert_user(conn, "user-2")
    return migrated_db


def fingerprint(owner_id: str, workout_id: str, started_at: str) -> str:
    return workouts.create_request_hash(
        user_id=owner_id, workout_id=workout_id, started_at=started_at
    )


def create(
    database_path: Path,
    *,
    owner_id: str = "user-1",
    workout_id: str | None = None,
    started_at: str = TS,
    request_hash: str | None = None,
) -> tuple[workouts.WorkoutRecord, bool]:
    resolved_id = workout_id if workout_id is not None else str(uuid.uuid4())
    return workouts.create_workout(
        database_path,
        owner_id=owner_id,
        workout_id=resolved_id,
        started_at=started_at,
        request_hash=(
            fingerprint(owner_id, resolved_id, started_at) if request_hash is None else request_hash
        ),
    )


def stored_rows(database_path: Path) -> list[sqlite3.Row]:
    with connect(database_path) as conn:
        return list(conn.execute("SELECT * FROM workouts ORDER BY id").fetchall())


def seed_history(database_path: Path) -> None:
    """Three user-1 workouts plus one foreign row that must never surface."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(conn, "w-jan-01", user_id="user-1", started_at="2026-01-01T08:00:00Z")
        insert_workout(
            conn,
            "w-jan-02",
            user_id="user-1",
            started_at="2026-01-02T08:00:00Z",
            ended_at="2026-01-02T09:30:00Z",
        )
        insert_workout(conn, "w-jan-03", user_id="user-1", started_at="2026-01-03T22:00:00Z")
        insert_workout(conn, "w-foreign", user_id="user-2", started_at="2026-01-02T10:00:00Z")


# --- create fingerprint -------------------------------------------------------


def test_create_request_hash_is_canonical_and_owner_bound() -> None:
    first = fingerprint("user-1", "id-1", TS)
    assert HEX64_RE.fullmatch(first)
    # Deterministic for identical validated content...
    assert first == fingerprint("user-1", "id-1", TS)
    # ...and sensitive to every fingerprinted field, including the owner:
    # identical content from another user can never match a stored receipt.
    assert first != fingerprint("user-2", "id-1", TS)
    assert first != fingerprint("user-1", "id-2", TS)
    assert first != fingerprint("user-1", "id-1", "2026-01-01T00:00:01Z")


# --- create -------------------------------------------------------------------


def test_create_stores_revision_zero_with_profile_bodyweight(two_users: Path) -> None:
    workout_id = str(uuid.uuid4())
    record, created = create(two_users, workout_id=workout_id)
    assert created is True
    assert record.id == workout_id
    assert record.user_id == "user-1"
    assert record.revision == 0
    # The profile default is copied as a recorded input (PLAN.md §4)...
    assert record.bodyweight_kg == 80
    assert record.name is None
    assert record.notes is None
    assert record.ended_at is None
    assert record.last_save_id is None
    assert record.last_save_hash is None
    assert record.started_at == TS
    assert TIMESTAMP_RE.fullmatch(record.created_at)
    assert record.created_at == record.updated_at
    row = stored_rows(two_users)[0]
    assert row["create_request_hash"] == fingerprint("user-1", workout_id, TS)
    assert row["revision"] == 0


def test_create_without_profile_bodyweight_records_null(two_users: Path) -> None:
    record, created = create(two_users, owner_id="user-2")
    assert created is True
    assert record.bodyweight_kg is None


def test_create_unknown_owner_violates_the_user_fk(two_users: Path) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        create(two_users, owner_id="no-such-user")
    assert stored_rows(two_users) == []


def test_retry_with_same_fingerprint_returns_existing_row(two_users: Path) -> None:
    workout_id = str(uuid.uuid4())
    first, created = create(two_users, workout_id=workout_id)
    assert created is True
    retry, retried = create(two_users, workout_id=workout_id)
    assert retried is False
    assert retry.id == first.id
    assert retry.started_at == first.started_at
    assert retry.bodyweight_kg == first.bodyweight_kg
    assert retry.revision == 0
    # Exactly one row exists; the retry never duplicated or rewrote it.
    assert len(stored_rows(two_users)) == 1
    assert stored_rows(two_users)[0]["created_at"] == first.created_at


def test_same_id_with_different_content_conflicts(two_users: Path) -> None:
    workout_id = str(uuid.uuid4())
    create(two_users, workout_id=workout_id)
    with pytest.raises(CreateConflictError):
        create(two_users, workout_id=workout_id, started_at="2026-02-02T00:00:00Z")
    rows = stored_rows(two_users)
    assert len(rows) == 1
    assert rows[0]["started_at"] == TS


def test_same_id_from_other_user_conflicts_without_touching_the_row(
    two_users: Path,
) -> None:
    workout_id = str(uuid.uuid4())
    owner_row, _ = create(two_users, workout_id=workout_id)
    # Identical content, different owner: the owner-bound fingerprint differs,
    # so this is a conflict rather than a successful cross-user retry.
    with pytest.raises(CreateConflictError):
        create(two_users, owner_id="user-2", workout_id=workout_id)
    rows = stored_rows(two_users)
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user-1"
    assert rows[0]["create_request_hash"] == owner_row.create_request_hash


# --- history listing ------------------------------------------------------------


def test_list_is_owner_scoped_and_newest_first(two_users: Path) -> None:
    seed_history(two_users)
    page = workouts.list_workouts(two_users, user_id="user-1", limit=50, offset=0)
    assert page.total == 3
    assert [record.id for record in page.items] == ["w-jan-03", "w-jan-02", "w-jan-01"]
    foreign = workouts.list_workouts(two_users, user_id="user-2", limit=50, offset=0)
    assert [record.id for record in foreign.items] == ["w-foreign"]


def test_list_status_filter(two_users: Path) -> None:
    seed_history(two_users)
    active = workouts.list_workouts(
        two_users, user_id="user-1", limit=50, offset=0, status="active"
    )
    assert [record.id for record in active.items] == ["w-jan-03", "w-jan-01"]
    finished = workouts.list_workouts(
        two_users, user_id="user-1", limit=50, offset=0, status="finished"
    )
    assert [record.id for record in finished.items] == ["w-jan-02"]
    assert all(record.ended_at is not None for record in finished.items)


def test_list_date_filters_are_inclusive_utc_days(two_users: Path) -> None:
    seed_history(two_users)
    single_day = workouts.list_workouts(
        two_users,
        user_id="user-1",
        limit=50,
        offset=0,
        date_from=date(2026, 1, 2),
        date_to=date(2026, 1, 2),
    )
    assert [record.id for record in single_day.items] == ["w-jan-02"]
    open_ended = workouts.list_workouts(
        two_users, user_id="user-1", limit=50, offset=0, date_from=date(2026, 1, 2)
    )
    assert [record.id for record in open_ended.items] == ["w-jan-03", "w-jan-02"]


def test_local_date_bounds_resolve_through_the_utc_offset() -> None:
    # UTC+3: local midnight is 21:00Z of the previous day.
    start, end = workouts.local_date_bounds(
        date_from=date(2026, 1, 1), date_to=date(2026, 1, 1), utc_offset_minutes=180
    )
    assert start == "2025-12-31T21:00:00Z"
    assert end == "2026-01-01T21:00:00Z"
    # UTC-12 shifts the other way; absent dates stay unbounded.
    start, end = workouts.local_date_bounds(
        date_from=date(2026, 1, 1), date_to=None, utc_offset_minutes=-720
    )
    assert start == "2026-01-01T12:00:00Z"
    assert end is None


def test_list_date_filters_use_the_caller_offset(two_users: Path) -> None:
    seed_history(two_users)
    # w-jan-03 starts 2026-01-03T22:00Z, which is already 2026-01-04 01:00
    # local time at UTC+3.
    shifted = workouts.list_workouts(
        two_users,
        user_id="user-1",
        limit=50,
        offset=0,
        date_from=date(2026, 1, 4),
        utc_offset_minutes=180,
    )
    assert [record.id for record in shifted.items] == ["w-jan-03"]
    unshifted = workouts.list_workouts(
        two_users,
        user_id="user-1",
        limit=50,
        offset=0,
        date_from=date(2026, 1, 4),
        utc_offset_minutes=0,
    )
    assert unshifted.items == []
    assert unshifted.total == 0


def test_list_breaks_started_at_ties_by_id(two_users: Path) -> None:
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "w-b", user_id="user-1", started_at=TS)
        insert_workout(conn, "w-a", user_id="user-1", started_at=TS)
    page = workouts.list_workouts(two_users, user_id="user-1", limit=50, offset=0)
    # Total order: equal timestamps fall back to descending id.
    assert [record.id for record in page.items] == ["w-b", "w-a"]


def test_list_paginates_without_gaps_or_duplicates(two_users: Path) -> None:
    seed_history(two_users)
    first = workouts.list_workouts(two_users, user_id="user-1", limit=2, offset=0)
    second = workouts.list_workouts(two_users, user_id="user-1", limit=2, offset=2)
    assert first.total == second.total == 3
    assert [record.id for record in first.items] == ["w-jan-03", "w-jan-02"]
    assert [record.id for record in second.items] == ["w-jan-01"]


def test_list_uses_one_snapshot_during_concurrent_insert(
    two_users: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_history(two_users)
    real_connect = workouts.connect
    inserted = False

    @contextmanager
    def racing_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        nonlocal inserted
        with real_connect(database_path, **kwargs) as conn:
            select_count = 0

            def insert_before_page(statement: str) -> None:
                nonlocal inserted, select_count
                if not statement.lstrip().upper().startswith("SELECT"):
                    return
                select_count += 1
                if select_count == 2:
                    with real_connect(database_path) as writer, write_transaction(writer):
                        insert_workout(
                            writer,
                            "w-concurrent",
                            user_id="user-1",
                            started_at="2026-01-04T08:00:00Z",
                        )
                    inserted = True

            conn.set_trace_callback(insert_before_page)
            yield conn

    monkeypatch.setattr(workouts, "connect", racing_connect)
    page = workouts.list_workouts(two_users, user_id="user-1", limit=50, offset=0)
    assert inserted is True
    assert page.total == 3
    assert [record.id for record in page.items] == ["w-jan-03", "w-jan-02", "w-jan-01"]


def test_list_rejects_invalid_arguments(two_users: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        workouts.list_workouts(two_users, user_id="user-1", limit=0, offset=0)
    with pytest.raises(ValueError, match="offset"):
        workouts.list_workouts(two_users, user_id="user-1", limit=10, offset=-1)
    with pytest.raises(ValueError, match="offset"):
        workouts.list_workouts(two_users, user_id="user-1", limit=10, offset=MAX_SAFE_INTEGER + 1)
    with pytest.raises(ValueError, match="status"):
        workouts.list_workouts(
            two_users,
            user_id="user-1",
            limit=10,
            offset=0,
            status="bogus",  # type: ignore[arg-type]
        )


# --- graph reads --------------------------------------------------------------


def seed_graph(database_path: Path) -> None:
    """One workout, two exercises with out-of-order indexes, three sets."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(conn, "workout-1", user_id="user-1", bodyweight_kg=75)
        # Stored out of order; reads must restore the dense index order.
        insert_exercise(
            conn,
            "exercise-b",
            workout_id="workout-1",
            catalog_id="pull-up",
            order_index=1,
            load_type="bodyweight",
            bodyweight_percent=100,
            side_count=1,
        )
        insert_exercise(
            conn,
            "exercise-a",
            workout_id="workout-1",
            catalog_id="dumbbell-curl",
            order_index=0,
            load_type="split_weight",
            bodyweight_percent=None,
            side_count=2,
        )
        insert_set(
            conn,
            "set-a-1",
            exercise_id="exercise-a",
            set_index=1,
            reps=10,
            weight_kg=12,
            rpe=8,
            side="bilateral",
            done=1,
        )
        insert_set(
            conn,
            "set-a-0",
            exercise_id="exercise-a",
            set_index=0,
            reps=None,
            weight_kg=None,
            side="bilateral",
            done=0,
        )
        insert_set(
            conn,
            "set-b-0",
            exercise_id="exercise-b",
            set_index=0,
            reps=6,
            weight_kg=None,
            bw_percent_override=90,
            side="bilateral",
            done=1,
        )


def seed_previous_session(database_path: Path) -> None:
    """A finished, strictly earlier session with one completed dumbbell-curl set."""
    with connect(database_path) as conn, write_transaction(conn):
        insert_workout(
            conn,
            "workout-0",
            user_id="user-1",
            started_at="2025-12-30T00:00:00Z",
            ended_at="2025-12-30T01:00:00Z",
            bodyweight_kg=74,
        )
        insert_exercise(
            conn,
            "exercise-prev",
            workout_id="workout-0",
            catalog_id="dumbbell-curl",
            order_index=0,
            load_type="split_weight",
            side_count=2,
        )
        insert_set(
            conn,
            "set-prev",
            exercise_id="exercise-prev",
            set_index=0,
            reps=8,
            weight_kg=10,
            side="bilateral",
            done=1,
        )


def test_graph_read_returns_nested_ordered_records(two_users: Path) -> None:
    seed_graph(two_users)
    graph = workouts.get_workout_graph(two_users, "workout-1", user_id="user-1")
    assert graph is not None
    assert graph.workout.bodyweight_kg == 75
    assert graph.workout.revision == 0
    assert [exercise.id for exercise in graph.exercises] == ["exercise-a", "exercise-b"]
    first, second = graph.exercises
    assert (first.order_index, first.load_type, first.side_count) == (0, "split_weight", 2)
    assert first.bodyweight_percent is None
    assert (second.order_index, second.load_type, second.bodyweight_percent) == (
        1,
        "bodyweight",
        100,
    )
    assert [item.id for item in first.sets] == ["set-a-0", "set-a-1"]
    assert [item.set_index for item in first.sets] == [0, 1]
    assert first.sets[0].done is False
    assert first.sets[0].reps is None
    assert first.sets[1].done is True
    assert first.sets[1].rpe == 8
    assert second.sets[0].bw_percent_override == 90
    assert second.sets[0].weight_kg is None


def test_graph_read_scopes_to_the_owner(two_users: Path) -> None:
    seed_graph(two_users)
    assert workouts.get_workout_graph(two_users, "workout-1", user_id="user-2") is None
    assert workouts.get_workout_graph(two_users, "no-such-workout", user_id="user-1") is None


def test_graph_read_of_empty_workout_has_no_exercises(two_users: Path) -> None:
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "workout-empty", user_id="user-1")
    graph = workouts.get_workout_graph(two_users, "workout-empty", user_id="user-1")
    assert graph is not None
    assert graph.exercises == ()


def test_graph_read_uses_one_snapshot_during_concurrent_replacement(
    two_users: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "workout-race", user_id="user-1")
        insert_exercise(
            conn,
            "exercise-old",
            workout_id="workout-race",
            catalog_id="bench-press",
            load_type="single_weight",
            side_count=1,
        )
        insert_set(conn, "set-old", exercise_id="exercise-old")

    real_connect = workouts.connect
    replaced = False

    @contextmanager
    def racing_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        nonlocal replaced
        with real_connect(database_path, **kwargs) as conn:
            select_count = 0

            def replace_before_sets(statement: str) -> None:
                nonlocal replaced, select_count
                if not statement.lstrip().upper().startswith("SELECT"):
                    return
                select_count += 1
                if select_count == 3:
                    with real_connect(database_path) as writer, write_transaction(writer):
                        writer.execute("DELETE FROM exercises WHERE id = 'exercise-old'")
                        insert_exercise(
                            writer,
                            "exercise-new",
                            workout_id="workout-race",
                            catalog_id="bench-press",
                            load_type="single_weight",
                            side_count=1,
                        )
                        insert_set(writer, "set-new", exercise_id="exercise-new")
                    replaced = True

            conn.set_trace_callback(replace_before_sets)
            yield conn

    monkeypatch.setattr(workouts, "connect", racing_connect)
    graph = workouts.get_workout_graph(two_users, "workout-race", user_id="user-1")
    assert replaced is True
    assert graph is not None
    assert [exercise.id for exercise in graph.exercises] == ["exercise-old"]
    assert [item.id for item in graph.exercises[0].sets] == ["set-old"]


def test_graph_read_uses_a_fixed_number_of_queries(
    two_users: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_graph(two_users)
    seed_previous_session(two_users)
    statements: list[str] = []
    real_connect = workouts.connect

    @contextmanager
    def counting_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, **kwargs) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(workouts, "connect", counting_connect)
    graph = workouts.get_workout_graph(two_users, "workout-1", user_id="user-1")
    assert graph is not None
    assert len(graph.exercises) == 2
    assert graph.previous_performance[0] is not None
    # Workout + exercises + all sets, then the three bounded previous-performance
    # queries: never one query per set or per exercise (PLAN.md §5, §7).
    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 6
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
