"""Stage 6c public save-protocol service tests (Gate G6c).

Direct-SQLite coverage of `save_workout`: fingerprint canonicality and
owner/workout binding; revision increment with the receipt recorded in the same
commit; exact `save_id` retries (including after input re-spelling and the
accepted finish) served without mutation; `save_id_conflict`,
`revision_conflict`, superseded receipts, the finished-workout guard, revision
exhaustion, and finish-time boundaries against a frozen transaction clock;
generic stored-state conflicts leaving the database unchanged; and the two
deterministic two-connection concurrency cases (same-base-revision race and
held-lock busy timeout) plus response-graph capture before commit.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from helpers import insert_exercise, insert_set, insert_user, insert_workout

from app.db import DatabaseBusyError, connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.workouts import SaveWorkoutRequest
from app.services import workouts
from app.services.workouts import (
    CatalogUnavailableError,
    GraphConflictError,
    GraphValidationError,
    RevisionConflictError,
    RevisionExhaustedError,
    SaveIdConflictError,
    WorkoutFinishedError,
    WorkoutGraph,
    WorkoutNotFoundError,
)

TS = "2026-01-01T00:00:00Z"
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
SET_B1 = uid(21)
SAVE_1 = uid(101)
SAVE_2 = uid(102)
SAVE_3 = uid(103)
SAVE_4 = uid(104)


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


def save_req(**overrides: Any) -> SaveWorkoutRequest:
    payload: dict[str, Any] = {
        "revision": 0,
        "save_id": SAVE_1,
        "name": None,
        "notes": None,
        "bodyweight_kg": None,
        "ended_at": None,
        "exercises": [],
    }
    payload.update(overrides)
    return SaveWorkoutRequest.model_validate(payload)


def hash_of(
    payload: SaveWorkoutRequest, *, owner_id: str = OWNER, workout_id: str = WORKOUT
) -> str:
    return workouts.save_request_hash(owner_id=owner_id, workout_id=workout_id, payload=payload)


@pytest.fixture()
def protocol_db(migrated_db: Path) -> Path:
    """Two users, an owned active workout at revision 0, and a foreign one."""
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, OWNER, bodyweight_default_kg=80)
        insert_user(conn, "user-2")
        insert_workout(conn, WORKOUT, user_id=OWNER, started_at=TS)
        insert_workout(conn, "workout-foreign", user_id="user-2", started_at=TS)
    return migrated_db


def save(
    db: Path,
    payload: SaveWorkoutRequest,
    *,
    owner_id: str = OWNER,
    workout_id: str = WORKOUT,
) -> WorkoutGraph:
    return workouts.save_workout(db, owner_id=owner_id, workout_id=workout_id, payload=payload)


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


def read_graph(db: Path, *, workout_id: str = WORKOUT) -> WorkoutGraph:
    graph = workouts.get_workout_graph(db, workout_id, user_id=OWNER)
    assert graph is not None
    return graph


def seed_exercise(db: Path, exercise_id: str, *, set_ids: tuple[str, ...] = ()) -> None:
    with connect(db) as conn, write_transaction(conn):
        insert_exercise(
            conn,
            exercise_id,
            workout_id=WORKOUT,
            catalog_id=CATALOG,
            order_index=0,
            load_type="single_weight",
            side_count=1,
        )
        for index, set_id in enumerate(set_ids):
            insert_set(conn, set_id, exercise_id=exercise_id, set_index=index)


class HookedConnection:
    """`sqlite3.Connection` proxy running test hooks around `execute` calls.

    Hooks receive each statement's SQL text; everything else (including
    `executemany`, `in_transaction`, and cursor results) passes through, so the
    service under test cannot tell the proxy from a real connection.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        before: Callable[[str], None] | None = None,
        after: Callable[[str], None] | None = None,
    ) -> None:
        self._conn = conn
        self._before = before
        self._after = after

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        if self._before is not None:
            self._before(statement)
        result = self._conn.execute(statement, *args, **kwargs)
        if self._after is not None:
            self._after(statement)
        return result

    def __enter__(self) -> Any:
        # `with conn:` transaction commits delegate to the real connection.
        return self._conn.__enter__()

    def __exit__(self, *exc_info: Any) -> Any:
        return self._conn.__exit__(*exc_info)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


# --- fingerprint --------------------------------------------------------------


def test_save_request_hash_is_canonical_and_bound() -> None:
    base = save_req()
    assert re.fullmatch(r"[0-9a-f]{64}", hash_of(base))
    assert hash_of(base) == hash_of(save_req())
    # Owner/workout-bound: identical content never matches another receipt.
    assert hash_of(base) != hash_of(base, owner_id="user-2")
    assert hash_of(base) != hash_of(base, workout_id="workout-foreign")
    # Sensitive to every fingerprinted top-level field...
    assert hash_of(base) != hash_of(save_req(revision=1))
    assert hash_of(base) != hash_of(save_req(save_id=SAVE_2))
    assert hash_of(base) != hash_of(save_req(name="x"))
    assert hash_of(base) != hash_of(save_req(notes="x"))
    assert hash_of(base) != hash_of(save_req(bodyweight_kg=80))
    assert hash_of(base) != hash_of(save_req(ended_at="2026-01-01T01:00:00Z"))
    # ...explicit nulls vs values, array order, and nested set values/order.
    two_sets = save_req(
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1), set_req(SET_A2)])]
    )
    swapped_sets = save_req(
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A2), set_req(SET_A1)])]
    )
    changed_set = save_req(
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1), set_req(SET_A2, reps=9)])]
    )
    assert hash_of(two_sets) != hash_of(swapped_sets)
    assert hash_of(two_sets) != hash_of(changed_set)
    assert hash_of(two_sets) != hash_of(
        save_req(exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])])
    )
    assert hash_of(
        save_req(exercises=[exercise_req(EXERCISE_A), exercise_req(EXERCISE_B)])
    ) != hash_of(save_req(exercises=[exercise_req(EXERCISE_B), exercise_req(EXERCISE_A)]))


def test_save_request_hash_ignores_input_spelling() -> None:
    canonical = save_req(
        ended_at="2026-01-01T03:00:00Z",
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
    )
    respelled = save_req(
        save_id=SAVE_1.upper(),
        ended_at="2026-01-01T06:00:00+03:00",
        exercises=[exercise_req(EXERCISE_A.upper(), sets=[set_req(SET_A1.upper())])],
    )
    assert hash_of(canonical) == hash_of(respelled)


# --- accepted saves and receipts ----------------------------------------------


def test_new_save_applies_graph_and_records_receipt(protocol_db: Path) -> None:
    payload = save_req(
        revision=0,
        save_id=SAVE_1,
        name="Push day",
        notes="felt strong",
        bodyweight_kg=82,
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1), set_req(SET_A2)])],
    )
    graph = save(protocol_db, payload)
    assert graph.workout.revision == 1
    assert graph.workout.last_save_id == SAVE_1
    assert graph.workout.name == "Push day"
    assert graph.workout.notes == "felt strong"
    assert graph.workout.bodyweight_kg == 82
    assert graph.workout.ended_at is None
    assert graph.workout.started_at == TS
    assert [(exercise.id, exercise.order_index) for exercise in graph.exercises] == [
        (EXERCISE_A, 0)
    ]
    assert [(item.id, item.set_index) for item in graph.exercises[0].sets] == [
        (SET_A1, 0),
        (SET_A2, 1),
    ]
    # A new instance copies the catalog snapshot.
    assert (graph.exercises[0].load_type, graph.exercises[0].side_count) == (
        "single_weight",
        1,
    )
    row = workout_row(protocol_db)
    assert row["revision"] == 1
    assert row["last_save_id"] == SAVE_1
    assert row["last_save_hash"] == hash_of(payload)
    assert row["updated_at"] != row["created_at"]


def test_exact_retry_returns_stored_graph_without_reapplying(
    protocol_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = save_req(
        revision=0,
        save_id=SAVE_1,
        name="Push day",
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1), set_req(SET_A2)])],
    )
    first = save(protocol_db, payload)
    row_after_first = tuple(workout_row(protocol_db))

    def unexpected_clock_read() -> str:
        raise AssertionError("exact retry must not sample the transaction clock")

    monkeypatch.setattr(workouts, "now_timestamp", unexpected_clock_read)
    retry = save(protocol_db, payload)
    assert retry == first
    # No revision increment, no updated_at change, no duplicated rows.
    assert tuple(workout_row(protocol_db)) == row_after_first
    with connect(protocol_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 2


def test_finish_retry_matches_after_input_normalization(protocol_db: Path) -> None:
    accepted = save_req(
        revision=0,
        save_id=SAVE_1,
        ended_at="2026-01-01T03:00:00Z",
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
    )
    first = save(protocol_db, accepted)
    assert first.workout.ended_at == "2026-01-01T03:00:00Z"
    row_after_first = tuple(workout_row(protocol_db))
    # A retry spelled differently normalizes to the same fingerprint, so the
    # accepted finish is served exactly once (no double increment).
    respelled = save_req(
        revision=0,
        save_id=SAVE_1.upper(),
        ended_at="2026-01-01T06:00:00+03:00",
        exercises=[exercise_req(EXERCISE_A.upper(), sets=[set_req(SET_A1.upper())])],
    )
    assert save(protocol_db, respelled) == first
    assert tuple(workout_row(protocol_db)) == row_after_first


def test_no_op_new_save_is_accepted_with_a_new_receipt(protocol_db: Path) -> None:
    save(protocol_db, save_req(revision=0, save_id=SAVE_1, name="same"))
    second = save_req(revision=1, save_id=SAVE_2, name="same")
    graph = save(protocol_db, second)
    # Identical user-visible content with a new save_id is a new accepted save.
    assert graph.workout.revision == 2
    assert graph.workout.last_save_id == SAVE_2
    assert workout_row(protocol_db)["last_save_hash"] == hash_of(second)


# --- stable conflicts ----------------------------------------------------------


def test_same_save_id_with_different_content_conflicts(protocol_db: Path) -> None:
    save(protocol_db, save_req(revision=0, save_id=SAVE_1, name="original"))
    before = database_state(protocol_db)
    # Even with a stale revision: receipt resolution precedes every other check.
    impostor = save_req(revision=0, save_id=SAVE_1, name="tampered")
    with pytest.raises(SaveIdConflictError) as excinfo:
        save(protocol_db, impostor)
    assert excinfo.value.current_revision == 1
    assert database_state(protocol_db) == before


def test_revision_mismatch_conflicts_with_current_revision(protocol_db: Path) -> None:
    save(protocol_db, save_req(revision=0, save_id=SAVE_1, name="v1"))
    before = database_state(protocol_db)
    with pytest.raises(RevisionConflictError) as excinfo:
        save(protocol_db, save_req(revision=0, save_id=SAVE_2, name="stale"))
    assert excinfo.value.current_revision == 1
    with pytest.raises(RevisionConflictError):
        save(protocol_db, save_req(revision=2, save_id=SAVE_3, name="future"))
    assert database_state(protocol_db) == before


def test_superseded_receipt_retry_is_a_revision_conflict(protocol_db: Path) -> None:
    first = save_req(revision=0, save_id=SAVE_1, name="v1")
    save(protocol_db, first)
    save(protocol_db, save_req(revision=1, save_id=SAVE_2, name="v2"))
    before = database_state(protocol_db)
    # Only the latest receipt is retained: the older exact payload is a normal
    # revision conflict, never a claimed success.
    with pytest.raises(RevisionConflictError) as excinfo:
        save(protocol_db, first)
    assert excinfo.value.current_revision == 2
    assert database_state(protocol_db) == before


def test_finished_workout_rejects_new_saves_but_serves_exact_retry(
    protocol_db: Path,
) -> None:
    finish = save_req(
        revision=0,
        save_id=SAVE_1,
        name="done",
        ended_at="2026-01-01T01:00:00Z",
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
    )
    saved = save(protocol_db, finish)
    assert saved.workout.ended_at == "2026-01-01T01:00:00Z"
    assert saved.workout.revision == 1
    before = database_state(protocol_db)

    # A new save_id with identical content is a new write, not a retry.
    same_content = save_req(
        revision=1,
        save_id=SAVE_2,
        name="done",
        ended_at="2026-01-01T01:00:00Z",
        exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
    )
    with pytest.raises(WorkoutFinishedError) as excinfo:
        save(protocol_db, same_content)
    assert excinfo.value.current_revision == 1

    # Reopening (clearing or changing the finish) is rejected the same way.
    with pytest.raises(WorkoutFinishedError):
        save(
            protocol_db,
            save_req(
                revision=1,
                save_id=SAVE_3,
                name="done",
                ended_at=None,
                exercises=[exercise_req(EXERCISE_A, sets=[set_req(SET_A1)])],
            ),
        )
    assert database_state(protocol_db) == before

    # The exact accepted finish retry remains the only served write.
    assert save(protocol_db, finish) == saved
    assert database_state(protocol_db) == before


def test_revision_exhaustion_rejects_new_saves_but_serves_exact_retry(
    migrated_db: Path,
) -> None:
    accepted = save_req(revision=MAX_SAFE_INTEGER - 1, save_id=SAVE_1, name="final")
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, OWNER)
        insert_workout(
            conn,
            WORKOUT,
            user_id=OWNER,
            started_at=TS,
            revision=MAX_SAFE_INTEGER,
            last_save_id=SAVE_1,
            last_save_hash=hash_of(accepted),
        )
    # The receipt that produced the exhausted revision still serves its retry.
    retry = save(migrated_db, accepted)
    assert retry.workout.revision == MAX_SAFE_INTEGER
    # A new save has no safe successor revision.
    with pytest.raises(RevisionExhaustedError) as excinfo:
        save(migrated_db, save_req(revision=MAX_SAFE_INTEGER, save_id=SAVE_2, name="one more"))
    assert excinfo.value.current_revision == MAX_SAFE_INTEGER
    assert workout_row(migrated_db)["revision"] == MAX_SAFE_INTEGER


def test_missing_and_foreign_workouts_are_not_found(protocol_db: Path) -> None:
    payload = save_req(revision=0, save_id=SAVE_1)
    with pytest.raises(WorkoutNotFoundError):
        save(protocol_db, payload, workout_id=str(uuid.uuid4()))
    with pytest.raises(WorkoutNotFoundError):
        save(protocol_db, payload, workout_id="workout-foreign")
    # PUT never creates: the unknown id still has no row.
    with connect(protocol_db) as conn:
        rows = conn.execute("SELECT id FROM workouts ORDER BY id").fetchall()
    assert [str(row["id"]) for row in rows] == [WORKOUT, "workout-foreign"]


def test_stored_state_conflicts_leave_the_database_unchanged(protocol_db: Path) -> None:
    seed_exercise(protocol_db, EXERCISE_A, set_ids=(SET_A1,))
    with connect(protocol_db) as conn, write_transaction(conn):
        # A foreign workout already owns EXERCISE_B.
        insert_exercise(
            conn,
            EXERCISE_B,
            workout_id="workout-foreign",
            catalog_id=CATALOG,
            order_index=0,
            load_type="single_weight",
            side_count=1,
        )
    before = database_state(protocol_db)

    # A stored id under another parent cannot be adopted.
    with pytest.raises(GraphConflictError):
        save(
            protocol_db,
            save_req(
                revision=0,
                save_id=SAVE_1,
                exercises=[
                    exercise_req(EXERCISE_A, sets=[set_req(SET_A1)]),
                    exercise_req(EXERCISE_B),
                ],
            ),
        )
    assert database_state(protocol_db) == before

    # Unknown and foreign catalog ids are indistinguishable.
    with pytest.raises(CatalogUnavailableError):
        save(
            protocol_db,
            save_req(
                revision=0,
                save_id=SAVE_2,
                exercises=[exercise_req(EXERCISE_C, catalog_id="no-such-entry")],
            ),
        )
    assert database_state(protocol_db) == before


# --- finish-time rules ----------------------------------------------------------


@pytest.mark.parametrize(
    ("ended_at", "accepted"),
    [
        (TS, True),  # equal to started_at
        ("2026-01-01T10:00:00Z", True),  # equal to the sampled transaction now
        ("2026-01-01T09:59:59Z", True),  # inside the window
        ("2025-12-31T23:59:59Z", False),  # before started_at
        ("2026-01-01T10:00:01Z", False),  # future vs the sampled now
    ],
    ids=["equal-start", "equal-now", "inside-window", "before-start", "future"],
)
def test_finish_time_boundaries_use_the_transaction_clock(
    protocol_db: Path, monkeypatch: pytest.MonkeyPatch, ended_at: str, accepted: bool
) -> None:
    frozen_now = "2026-01-01T10:00:00Z"
    monkeypatch.setattr(workouts, "now_timestamp", lambda: frozen_now)
    before = database_state(protocol_db)
    payload = save_req(revision=0, save_id=SAVE_1, ended_at=ended_at)
    if accepted:
        graph = save(protocol_db, payload)
        assert graph.workout.ended_at == ended_at
        assert graph.workout.revision == 1
        # The finish ceiling and updated_at are the same sampled instant.
        assert workout_row(protocol_db)["updated_at"] == frozen_now
    else:
        with pytest.raises(GraphValidationError) as excinfo:
            save(protocol_db, payload)
        assert excinfo.value.field == "ended_at"
        # Field-path failures never echo the rejected value.
        assert ended_at not in excinfo.value.message
        assert database_state(protocol_db) == before


# --- concurrency ----------------------------------------------------------------


def test_concurrent_saves_on_one_revision_yield_exactly_one_winner(
    protocol_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_exercise(protocol_db, EXERCISE_A)

    a_holds_lock = threading.Event()
    b_attempting = threading.Event()
    release_a = threading.Event()
    real_connect = workouts.connect
    results: dict[str, Any] = {}

    def hook_a(statement: str) -> None:
        # Writer A keeps the write lock after BEGIN IMMEDIATE until writer B
        # has demonstrably started its own lock acquisition.
        if statement != "BEGIN IMMEDIATE":
            return
        a_holds_lock.set()
        if not release_a.wait(timeout=30):
            raise RuntimeError("writer-a was never released")

    def hook_b(statement: str) -> None:
        if statement == "BEGIN IMMEDIATE":
            b_attempting.set()

    @contextmanager
    def instrumented_connect(
        database_path: str | Path, **kwargs: Any
    ) -> Iterator[sqlite3.Connection]:
        # Sufficient lock-wait time so the loser deterministically queues
        # instead of timing out; production keeps its five-second default.
        with real_connect(database_path, busy_timeout_ms=30_000, **kwargs) as conn:
            role = threading.current_thread().name
            if role == "writer-a":
                yield cast(sqlite3.Connection, HookedConnection(conn, after=hook_a))
            elif role == "writer-b":
                yield cast(sqlite3.Connection, HookedConnection(conn, before=hook_b))
            else:
                yield conn

    def run(role: str, payload: SaveWorkoutRequest) -> None:
        try:
            results[role] = workouts.save_workout(
                protocol_db, owner_id=OWNER, workout_id=WORKOUT, payload=payload
            )
        except Exception as exc:
            results[role] = exc

    monkeypatch.setattr(workouts, "connect", instrumented_connect)
    payload_a = save_req(
        revision=0, save_id=SAVE_1, name="winner-a", exercises=[exercise_req(EXERCISE_A, notes="a")]
    )
    payload_b = save_req(
        revision=0, save_id=SAVE_2, name="winner-b", exercises=[exercise_req(EXERCISE_A, notes="b")]
    )
    writer_a = threading.Thread(target=run, args=("a", payload_a), name="writer-a")
    writer_b = threading.Thread(target=run, args=("b", payload_b), name="writer-b")
    writer_a.start()
    assert a_holds_lock.wait(timeout=30)
    writer_b.start()
    assert b_attempting.wait(timeout=30)
    release_a.set()
    writer_a.join(timeout=30)
    writer_b.join(timeout=30)
    assert not writer_a.is_alive()
    assert not writer_b.is_alive()

    # A committed first (it held the lock while B queued): exactly one winner,
    # exactly one revision increment, and the loser is a plain revision conflict.
    winner = results["a"]
    loser = results["b"]
    assert isinstance(winner, WorkoutGraph)
    assert winner.workout.revision == 1
    assert winner.workout.name == "winner-a"
    assert isinstance(loser, RevisionConflictError)
    assert loser.current_revision == 1

    row = workout_row(protocol_db)
    assert row["revision"] == 1
    assert row["last_save_id"] == SAVE_1
    assert row["name"] == "winner-a"
    # Only the winner's content exists; the loser left nothing behind.
    assert read_graph(protocol_db).exercises[0].notes == "a"


def test_held_write_lock_times_out_retryably_and_retry_succeeds(
    protocol_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_exercise(protocol_db, EXERCISE_A)
    payload = save_req(
        revision=0, save_id=SAVE_1, name="blocked", exercises=[exercise_req(EXERCISE_A)]
    )
    before = database_state(protocol_db)
    real_connect = workouts.connect

    @contextmanager
    def impatient_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, busy_timeout_ms=50, **kwargs) as conn:
            yield conn

    with connect(protocol_db) as holder:
        # Hold the write lock outside any helper transaction until the save
        # attempt has provably failed; no timing-only sleeps are involved.
        holder.execute("BEGIN IMMEDIATE")
        try:
            monkeypatch.setattr(workouts, "connect", impatient_connect)
            with pytest.raises(DatabaseBusyError):
                workouts.save_workout(
                    protocol_db, owner_id=OWNER, workout_id=WORKOUT, payload=payload
                )
        finally:
            holder.execute("ROLLBACK")

    # The timeout left no partial mutation.
    assert database_state(protocol_db) == before

    # After release, the identical save succeeds with the production timeout.
    monkeypatch.setattr(workouts, "connect", real_connect)
    graph = workouts.save_workout(protocol_db, owner_id=OWNER, workout_id=WORKOUT, payload=payload)
    assert graph.workout.revision == 1
    assert graph.workout.name == "blocked"


def test_returned_graph_is_captured_before_commit(
    protocol_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = save_req(revision=0, save_id=SAVE_1, name="captured")
    real_connect = workouts.connect
    replaced = threading.Event()

    def replace_after_commit(statement: str) -> None:
        if statement != "COMMIT":
            return
        # A second writer lands between the save's commit and its response.
        with real_connect(protocol_db) as second, write_transaction(second):
            second.execute(
                "UPDATE workouts SET name = 'replaced-after-commit' WHERE id = :id",
                {"id": WORKOUT},
            )
        replaced.set()

    @contextmanager
    def racing_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(database_path, **kwargs) as conn:
            yield cast(sqlite3.Connection, HookedConnection(conn, after=replace_after_commit))

    monkeypatch.setattr(workouts, "connect", racing_connect)
    graph = workouts.save_workout(protocol_db, owner_id=OWNER, workout_id=WORKOUT, payload=payload)
    assert replaced.is_set()
    # The response keeps the state captured on the write connection...
    assert graph.workout.name == "captured"
    assert graph.workout.revision == 1
    assert graph.workout.last_save_id == SAVE_1
    # ...while the later writer's replacement is the new committed state.
    row = workout_row(protocol_db)
    assert row["name"] == "replaced-after-commit"
    assert row["revision"] == 1
