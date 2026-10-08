"""Stage 8a inline previous-performance service tests (Gate G8a).

Direct-SQLite coverage of bounded candidate selection (finished, strictly
earlier, owner-scoped, requiring a completed set for the catalog id, ordered by
the `(started_at DESC, id DESC)` total order), positional occurrence pairing,
side-aware per-side ordinal set pairing, recorded-snapshot compatibility,
historical stability against profile and catalog edits, unknown-versus-zero
propagation, estimated 1RM eligibility, and the fixed query bound.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from helpers import insert_exercise, insert_set, insert_user, insert_workout

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.services import workouts
from app.services.workouts import ExercisePreviousPerformance, PreviousSetPair, WorkoutGraph

VIEWED = "w-view"
VIEWED_START = "2026-02-01T08:00:00Z"
PREVIOUS_START = "2026-01-20T08:00:00Z"
ENDED = "2026-02-01T09:00:00Z"


@dataclass(frozen=True)
class SetSpec:
    """One set row; the defaults describe a completed bilateral weighted set."""

    reps: int | None = 8
    weight_kg: int | None = 100
    side: str = "bilateral"
    done: bool = True
    bw_percent_override: int | None = None


@dataclass(frozen=True)
class ExerciseSpec:
    """One exercise occurrence; the defaults describe a barbell bench snapshot."""

    catalog_id: str = "bench-press"
    load_type: str = "single_weight"
    side_count: int = 1
    bodyweight_percent: int | None = None
    sets: tuple[SetSpec, ...] = ()


# Three catalog snapshots covering every load type, reused by the graph-size
# bound test so each occurrence exercises a different calculation path.
BARBELL = ExerciseSpec()
BODYWEIGHT = ExerciseSpec(catalog_id="pull-up", load_type="bodyweight", bodyweight_percent=100)
DUMBBELL = ExerciseSpec(catalog_id="dumbbell-curl", load_type="split_weight", side_count=2)


def barbell(*sets: SetSpec) -> ExerciseSpec:
    return replace(BARBELL, sets=sets)


def bodyweight(*sets: SetSpec) -> ExerciseSpec:
    return replace(BODYWEIGHT, sets=sets)


def dumbbell(*sets: SetSpec) -> ExerciseSpec:
    return replace(DUMBBELL, sets=sets)


def completed(reps: int, weight_kg: int | None, side: str = "bilateral") -> SetSpec:
    return SetSpec(reps=reps, weight_kg=weight_kg, side=side)


def draft(side: str = "bilateral") -> SetSpec:
    return SetSpec(reps=None, weight_kg=None, side=side, done=False)


def bench_session(reps: int, weight_kg: int | None = 100) -> tuple[ExerciseSpec, ...]:
    """One barbell bench occurrence holding a single completed set."""
    return (barbell(completed(reps, weight_kg)),)


@pytest.fixture()
def db(migrated_db: Path) -> Path:
    """The migrated database with two owners; `user-1` defaults to 80 kg."""
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, "user-1", bodyweight_default_kg=80)
        insert_user(conn, "user-2", bodyweight_default_kg=90)
    return migrated_db


def seed_workout(
    conn: sqlite3.Connection,
    workout_id: str,
    *,
    started_at: str,
    ended_at: str | None = ENDED,
    bodyweight_kg: int | None = None,
    user_id: str = "user-1",
    exercises: Sequence[ExerciseSpec] = (),
) -> None:
    """Insert one workout plus its graph with deterministic nested ids.

    Exercise `i` of `workout_id` is `"{workout_id}-e{i}"` and its set `j` is
    `"{workout_id}-e{i}-s{j}"`, so assertions can name paired rows exactly.
    """
    insert_workout(
        conn,
        workout_id,
        user_id=user_id,
        started_at=started_at,
        ended_at=ended_at,
        bodyweight_kg=bodyweight_kg,
    )
    for index, exercise in enumerate(exercises):
        exercise_id = f"{workout_id}-e{index}"
        insert_exercise(
            conn,
            exercise_id,
            workout_id=workout_id,
            catalog_id=exercise.catalog_id,
            order_index=index,
            load_type=exercise.load_type,
            bodyweight_percent=exercise.bodyweight_percent,
            side_count=exercise.side_count,
        )
        for position, spec in enumerate(exercise.sets):
            insert_set(
                conn,
                f"{exercise_id}-s{position}",
                exercise_id=exercise_id,
                set_index=position,
                reps=spec.reps,
                weight_kg=spec.weight_kg,
                bw_percent_override=spec.bw_percent_override,
                side=spec.side,
                done=int(spec.done),
            )


def read_graph(database_path: Path, workout_id: str, *, user_id: str = "user-1") -> WorkoutGraph:
    graph = workouts.get_workout_graph(database_path, workout_id, user_id=user_id)
    assert graph is not None
    return graph


def previous_of(
    database_path: Path, workout_id: str, position: int, *, user_id: str = "user-1"
) -> ExercisePreviousPerformance | None:
    return read_graph(database_path, workout_id, user_id=user_id).previous_performance[position]


def pair_ids(pair: PreviousSetPair) -> tuple[str, str]:
    return pair.current_set_id, pair.previous_set_id


@contextmanager
def counting_queries(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Capture every statement the service issues for one graph read."""
    statements: list[str] = []
    real_connect = workouts.connect

    @contextmanager
    def counting_connect(path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(path, **kwargs) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(workouts, "connect", counting_connect)
    yield statements


def selects(statements: Sequence[str]) -> list[str]:
    return [item for item in statements if item.lstrip().upper().startswith("SELECT")]


# --- candidate selection ------------------------------------------------------


def test_no_eligible_previous_session_reports_no_performance(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(8, 100)),))
    assert read_graph(db, VIEWED).previous_performance == (None,)


def test_only_finished_strictly_earlier_sessions_are_candidates(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # An earlier session that never finished earns no history...
        seed_workout(
            conn,
            "w-active-earlier",
            started_at="2026-01-05T08:00:00Z",
            ended_at=None,
            exercises=(barbell(completed(20, 140)),),
        )
        # ...and neither does a finished session that started later.
        seed_workout(
            conn,
            "w-later",
            started_at="2026-03-01T08:00:00Z",
            ended_at="2026-03-01T09:00:00Z",
            exercises=(barbell(completed(20, 140)),),
        )
        seed_workout(conn, "w-previous", started_at=PREVIOUS_START, exercises=bench_session(8))
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(8))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-previous"
    assert previous.started_at == PREVIOUS_START
    assert previous.exercise_id == "w-previous-e0"


def test_viewed_workout_and_equal_started_at_are_excluded(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-same-instant", started_at=VIEWED_START, exercises=bench_session(20, 140)
        )
        # The viewed workout is itself finished with completed sets; it must
        # never become its own candidate.
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(8, 100)),))
    assert previous_of(db, VIEWED, 0) is None


def test_candidate_ties_are_broken_by_descending_id(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-a", started_at=PREVIOUS_START, exercises=bench_session(8))
        seed_workout(conn, "w-b", started_at=PREVIOUS_START, exercises=bench_session(8, 105))
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(8, 110))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-b"


def test_most_recent_started_at_wins_over_the_id_tie_breaker(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-zzz", started_at="2026-01-10T08:00:00Z", exercises=bench_session(8))
        seed_workout(conn, "w-aaa", started_at=PREVIOUS_START, exercises=bench_session(8, 105))
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(8, 110))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-aaa"


def test_candidate_without_completed_sets_for_that_catalog_id_is_skipped(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-older", started_at="2026-01-10T08:00:00Z", exercises=bench_session(8))
        # Most recent, but only a draft bench set: not a candidate.
        seed_workout(
            conn, "w-recent", started_at="2026-01-25T08:00:00Z", exercises=(barbell(draft()),)
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(8, 110))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-older"


def test_completed_sets_for_another_catalog_id_do_not_select_a_session(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-older", started_at="2026-01-10T08:00:00Z", exercises=bench_session(8))
        seed_workout(
            conn,
            "w-recent",
            started_at="2026-01-25T08:00:00Z",
            exercises=(bodyweight(completed(10, None)),),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(8, 110))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-older"


def test_each_catalog_id_selects_its_own_previous_session(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-bench", started_at="2026-01-10T08:00:00Z", exercises=bench_session(8))
        seed_workout(
            conn, "w-pull", started_at=PREVIOUS_START, exercises=(bodyweight(completed(6, None)),)
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            bodyweight_kg=82,
            exercises=(barbell(completed(8, 105)), bodyweight(completed(7, None))),
        )
    bench_previous, pull_previous = read_graph(db, VIEWED).previous_performance
    assert bench_previous is not None and bench_previous.workout_id == "w-bench"
    assert pull_previous is not None and pull_previous.workout_id == "w-pull"
    # The pure-bodyweight comparison uses each session's own recorded
    # bodyweight: 82 kg now, unknown back then.
    assert pull_previous.bodyweight_kg is None
    assert pull_previous.sets[0].values.effective_load_kg is None
    assert pull_previous.pairs[0].current.effective_load_kg == 82
    assert pull_previous.pairs[0].delta.effective_load_kg is None


def test_foreign_workouts_never_enter_candidate_selection(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-foreign",
            user_id="user-2",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(20, 200)),),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(8, 100)),))
    assert previous_of(db, VIEWED, 0) is None
    assert previous_of(db, "w-foreign", 0, user_id="user-2") is None


# --- occurrence and set pairing -----------------------------------------------


def test_occurrences_pair_in_workout_order_with_extras_unmatched(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(8, 100)), barbell(completed(6, 90))),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            exercises=(
                barbell(completed(8, 105)),
                barbell(completed(6, 95)),
                barbell(completed(4, 80)),
            ),
        )
    first, second, third = read_graph(db, VIEWED).previous_performance
    assert first is not None and first.exercise_id == "w-previous-e0"
    assert first.order_index == 0
    assert second is not None and second.exercise_id == "w-previous-e1"
    assert second.order_index == 1
    # The current graph has a third occurrence; the previous session has none.
    assert third is None


def test_extra_previous_occurrences_are_not_paired(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(
                barbell(completed(8, 100)),
                barbell(completed(6, 90)),
                barbell(completed(4, 80)),
            ),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(5, 85)),))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.exercise_id == "w-previous-e0"
    assert [item.id for item in previous.sets] == ["w-previous-e0-s0"]


def test_completed_sets_pair_by_side_and_ordinal_without_crossing(db: Path) -> None:
    per_side = replace(DUMBBELL, side_count=1)
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(
                replace(
                    per_side,
                    sets=(
                        completed(8, 10, side="left"),
                        completed(8, 10, side="right"),
                        completed(6, 10, side="left"),
                    ),
                ),
            ),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            exercises=(
                replace(
                    per_side,
                    sets=(
                        completed(10, 12, side="left"),
                        completed(5, 12, side="left"),
                        completed(7, 12, side="right"),
                        completed(9, 12, side="right"),
                    ),
                ),
            ),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    # Left ordinals pair with left ordinals and right with right; the second
    # current right set has no counterpart.
    assert [pair_ids(pair) for pair in previous.pairs] == [
        (f"{VIEWED}-e0-s0", "w-previous-e0-s0"),
        (f"{VIEWED}-e0-s1", "w-previous-e0-s2"),
        (f"{VIEWED}-e0-s2", "w-previous-e0-s1"),
    ]
    assert all(pair.load_compatible for pair in previous.pairs)
    # A per-side snapshot records one dumbbell, so the multiplier stays 1.
    assert previous.pairs[0].previous.external_load_kg == 10
    assert previous.pairs[0].current.external_load_kg == 12
    assert previous.pairs[0].delta.external_load_kg == 2


def test_bilateral_sets_never_pair_with_left_or_right(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(dumbbell(completed(8, 12)),),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            exercises=(
                replace(
                    DUMBBELL,
                    side_count=1,
                    sets=(completed(8, 12, side="left"), completed(8, 12, side="right")),
                ),
            ),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    # The previous bilateral set is still reported as "last time"...
    assert [item.id for item in previous.sets] == ["w-previous-e0-s0"]
    # ...but no cross-side comparison is fabricated.
    assert previous.pairs == ()


def test_draft_sets_neither_contribute_history_nor_consume_ordinals(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(barbell(draft(), completed(8, 100), draft()),),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            exercises=(barbell(draft(), completed(10, 105), draft()),),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    # Only the completed historical set is exposed, in stored set order.
    assert [item.id for item in previous.sets] == ["w-previous-e0-s1"]
    assert [pair_ids(pair) for pair in previous.pairs] == [(f"{VIEWED}-e0-s1", "w-previous-e0-s1")]


def test_previous_sets_are_ordered_by_set_index(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(8, 100), completed(6, 100), completed(4, 100)),),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(),))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert [item.set_index for item in previous.sets] == [0, 1, 2]
    assert [item.values.reps for item in previous.sets] == [8, 6, 4]


def test_an_active_view_exposes_the_complete_previous_set_list(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(8, 100), completed(6, 95)),),
        )
        # The viewed workout is active with prefilled drafts only.
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            ended_at=None,
            exercises=(barbell(draft(), draft()),),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert [item.id for item in previous.sets] == ["w-previous-e0-s0", "w-previous-e0-s1"]
    assert previous.pairs == ()


# --- comparison values --------------------------------------------------------


def test_compatible_pairs_report_values_and_absolute_deltas(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-previous", started_at=PREVIOUS_START, exercises=bench_session(8))
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(10, 105))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    pair = previous.pairs[0]
    assert pair.load_compatible is True
    assert pair.previous.reps == 8
    assert pair.previous.external_load_kg == 100
    assert pair.previous.effective_load_kg == 100
    assert pair.previous.volume_kg_reps == 800
    # 100 * (30 + 8) // 30 = 126
    assert pair.previous.estimated_1rm_kg == 126
    assert pair.current.reps == 10
    assert pair.current.effective_load_kg == 105
    assert pair.current.volume_kg_reps == 1050
    # 105 * (30 + 10) // 30 = 140
    assert pair.current.estimated_1rm_kg == 140
    assert pair.delta.reps == 2
    assert pair.delta.external_load_kg == 5
    assert pair.delta.effective_load_kg == 5
    assert pair.delta.volume_kg_reps == 250
    assert pair.delta.estimated_1rm_kg == 14


def test_negative_deltas_are_exact_integers(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-previous", started_at=PREVIOUS_START, exercises=(barbell(completed(10, 105)),)
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(8, 100)),))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    pair = previous.pairs[0]
    assert pair.delta.reps == -2
    assert pair.delta.external_load_kg == -5
    assert pair.delta.effective_load_kg == -5
    assert pair.delta.volume_kg_reps == 800 - 1050
    assert pair.delta.estimated_1rm_kg == 126 - 140


@pytest.mark.parametrize(
    ("previous_exercise", "current_exercise"),
    [
        # A later catalog edit copied into a new instance changes load_type.
        (
            barbell(completed(8, 100)),
            replace(BARBELL, load_type="split_weight", side_count=2, sets=(completed(8, 50),)),
        ),
        # Same load type, different side count.
        (dumbbell(completed(8, 12)), replace(DUMBBELL, side_count=1, sets=(completed(8, 12),))),
        # Same snapshot shape, different recorded bodyweight percentage.
        (
            replace(BARBELL, bodyweight_percent=50, sets=(completed(8, 20),)),
            replace(BARBELL, bodyweight_percent=65, sets=(completed(8, 20),)),
        ),
        # Same snapshot, but only the current set overrides its percentage.
        (
            replace(BARBELL, bodyweight_percent=50, sets=(completed(8, 20),)),
            replace(
                BARBELL,
                bodyweight_percent=50,
                sets=(SetSpec(reps=8, weight_kg=20, bw_percent_override=65),),
            ),
        ),
    ],
    ids=["load-type", "side-count", "snapshot-percent", "set-override"],
)
def test_incompatible_recorded_settings_never_fabricate_progression(
    db: Path, previous_exercise: ExerciseSpec, current_exercise: ExerciseSpec
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            bodyweight_kg=80,
            exercises=(previous_exercise,),
        )
        seed_workout(
            conn, VIEWED, started_at=VIEWED_START, bodyweight_kg=80, exercises=(current_exercise,)
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert len(previous.pairs) == 1
    pair = previous.pairs[0]
    assert pair.load_compatible is False
    # A reps comparison survives; every load-based comparison is unknown.
    assert pair.current.reps == 8
    assert pair.previous.reps == 8
    assert pair.delta.reps == 0
    for values in (pair.current, pair.previous, pair.delta):
        assert values.external_load_kg is None
        assert values.effective_load_kg is None
        assert values.volume_kg_reps is None
        assert values.estimated_1rm_kg is None
    # The previous occurrence's own recorded values stay fully reported.
    assert previous.sets[0].values.effective_load_kg is not None


def test_compatible_settings_compare_loads_across_different_bodyweights(db: Path) -> None:
    weighted = replace(BARBELL, bodyweight_percent=50)
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            bodyweight_kg=75,
            exercises=(replace(weighted, sets=(completed(8, 20),)),),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            bodyweight_kg=81,
            exercises=(replace(weighted, sets=(completed(8, 20),)),),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    pair = previous.pairs[0]
    assert pair.load_compatible is True
    # 20 + 75 * 50 // 100 = 57, and 20 + 81 * 50 // 100 = 60.
    assert pair.previous.effective_load_kg == 57
    assert pair.current.effective_load_kg == 60
    assert pair.delta.effective_load_kg == 3
    # A bodyweight contribution makes the 1RM estimate inapplicable.
    assert pair.previous.estimated_1rm_kg is None
    assert pair.current.estimated_1rm_kg is None


def test_unknown_bodyweight_stays_unknown_and_zero_stays_zero(db: Path) -> None:
    weighted = replace(BARBELL, bodyweight_percent=50)
    with connect(db) as conn, write_transaction(conn):
        for workout_id in ("w-previous", VIEWED):
            started = PREVIOUS_START if workout_id == "w-previous" else VIEWED_START
            seed_workout(
                conn,
                workout_id,
                started_at=started,
                bodyweight_kg=None,
                exercises=(
                    replace(weighted, sets=(completed(8, 20),)),
                    barbell(completed(8, 0)),
                ),
            )
    weighted_previous, barbell_previous = read_graph(db, VIEWED).previous_performance
    assert weighted_previous is not None and barbell_previous is not None
    unknown = weighted_previous.sets[0].values
    assert unknown.external_load_kg == 20
    assert unknown.effective_load_kg is None
    assert unknown.volume_kg_reps is None
    assert unknown.estimated_1rm_kg is None
    assert weighted_previous.pairs[0].delta.effective_load_kg is None
    assert weighted_previous.pairs[0].delta.reps == 0
    # A known zero external load is a value, not an unknown.
    zero = barbell_previous.sets[0].values
    assert zero.external_load_kg == 0
    assert zero.effective_load_kg == 0
    assert zero.volume_kg_reps == 0
    assert zero.estimated_1rm_kg == 0
    assert barbell_previous.pairs[0].delta.volume_kg_reps == 0


def test_legacy_unsafe_derivations_do_not_break_detail_reads(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Stage 7 accepted each operand independently before read-time derived
        # values existed. Keep such persisted rows readable after upgrading.
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(2, MAX_SAFE_INTEGER)),),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(2, 100))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    values = previous.sets[0].values
    assert values.reps == 2
    assert values.external_load_kg is None
    assert values.effective_load_kg is None
    assert values.volume_kg_reps is None
    assert values.estimated_1rm_kg is None
    pair = previous.pairs[0]
    assert pair.previous == values
    assert pair.delta.reps == 0
    assert pair.delta.volume_kg_reps is None


@pytest.mark.parametrize(
    ("reps", "expected"), [(1, 100), (2, 106), (3, 110), (10, 133), (11, None), (25, None)]
)
def test_estimated_one_rep_max_uses_the_documented_rep_boundaries(
    db: Path, reps: int, expected: int | None
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-previous", started_at=PREVIOUS_START, exercises=bench_session(reps))
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(),))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    # The external load itself at one rep, 100 * (30 + reps) // 30 for 2..10.
    assert previous.sets[0].values.estimated_1rm_kg == expected


def test_pure_bodyweight_sets_have_no_estimated_one_rep_max(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            bodyweight_kg=80,
            exercises=(bodyweight(completed(3, None)),),
        )
        seed_workout(
            conn,
            VIEWED,
            started_at=VIEWED_START,
            bodyweight_kg=80,
            exercises=(bodyweight(completed(5, None)),),
        )
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    pair = previous.pairs[0]
    assert pair.load_compatible is True
    assert pair.previous.external_load_kg == 0
    assert pair.previous.effective_load_kg == 80
    assert pair.previous.volume_kg_reps == 240
    assert pair.previous.estimated_1rm_kg is None
    assert pair.current.estimated_1rm_kg is None
    assert pair.delta.estimated_1rm_kg is None
    assert pair.delta.volume_kg_reps == 160


# --- historical stability -----------------------------------------------------


def test_profile_and_catalog_edits_do_not_rewrite_history(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            bodyweight_kg=75,
            exercises=bench_session(8),
        )
        seed_workout(
            conn, VIEWED, started_at=VIEWED_START, bodyweight_kg=75, exercises=bench_session(8)
        )
    before = previous_of(db, VIEWED, 0)
    assert before is not None

    with connect(db) as conn, write_transaction(conn):
        conn.execute("UPDATE users SET bodyweight_default_kg = 120 WHERE id = 'user-1'")
        conn.execute(
            "UPDATE exercise_catalog SET load_type = 'split_weight', side_count = 2 "
            "WHERE id = 'bench-press'"
        )

    after = previous_of(db, VIEWED, 0)
    assert after == before
    assert after is not None
    assert after.load_type == "single_weight"
    assert after.side_count == 1
    assert after.pairs[0].current.effective_load_kg == 100
    assert after.pairs[0].delta.effective_load_kg == 0


def test_recorded_bodyweight_of_the_previous_session_drives_its_values(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_START,
            bodyweight_kg=70,
            exercises=bench_session(8),
        )
        seed_workout(
            conn, VIEWED, started_at=VIEWED_START, bodyweight_kg=90, exercises=bench_session(8)
        )
        # The profile default is irrelevant to both recorded sessions.
        conn.execute("UPDATE users SET bodyweight_default_kg = 120 WHERE id = 'user-1'")
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.bodyweight_kg == 70
    assert read_graph(db, VIEWED).workout.bodyweight_kg == 90
    assert previous.pairs[0].previous.effective_load_kg == 100
    assert previous.pairs[0].current.effective_load_kg == 100
    assert previous.pairs[0].delta.effective_load_kg == 0


# --- repeat-last --------------------------------------------------------------


def test_a_repeat_with_draft_sets_does_not_become_history(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-original",
            started_at="2026-01-10T08:00:00Z",
            exercises=(barbell(completed(8, 100)),),
        )
        # A repeat-last copy: same values, new ids, every set back to draft.
        seed_workout(
            conn, "w-repeat", started_at=PREVIOUS_START, exercises=(barbell(draft(), draft()),)
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(10, 105))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-original"
    assert [pair_ids(pair) for pair in previous.pairs] == [(f"{VIEWED}-e0-s0", "w-original-e0-s0")]
    # Viewing the repeat itself still shows the original as "last time", with
    # no comparison because none of its sets are completed.
    repeated = previous_of(db, "w-repeat", 0)
    assert repeated is not None
    assert repeated.workout_id == "w-original"
    assert repeated.pairs == ()
    assert [item.id for item in repeated.sets] == ["w-original-e0-s0"]


def test_a_finished_repeat_with_completed_sets_becomes_the_next_history(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-original",
            started_at="2026-01-10T08:00:00Z",
            exercises=(barbell(completed(8, 100)),),
        )
        seed_workout(
            conn,
            "w-repeat",
            started_at=PREVIOUS_START,
            exercises=(barbell(completed(8, 100), completed(6, 95)),),
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=bench_session(10, 105))
    previous = previous_of(db, VIEWED, 0)
    assert previous is not None
    assert previous.workout_id == "w-repeat"
    assert [item.id for item in previous.sets] == ["w-repeat-e0-s0", "w-repeat-e0-s1"]
    assert [pair_ids(pair) for pair in previous.pairs] == [(f"{VIEWED}-e0-s0", "w-repeat-e0-s0")]


# --- query bound --------------------------------------------------------------


def test_an_empty_graph_issues_only_the_three_base_queries(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, VIEWED, started_at=VIEWED_START)
    with counting_queries(db, monkeypatch) as statements:
        assert read_graph(db, VIEWED).previous_performance == ()
    assert len(selects(statements)) == 3


def test_no_eligible_session_stops_after_the_selection_query(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, VIEWED, started_at=VIEWED_START, exercises=(barbell(completed(8, 100)),))
    with counting_queries(db, monkeypatch) as statements:
        assert read_graph(db, VIEWED).previous_performance == (None,)
    assert len(selects(statements)) == 4


@pytest.mark.parametrize("exercise_count", [1, 6, 12])
def test_the_query_bound_is_independent_of_graph_size(
    db: Path, monkeypatch: pytest.MonkeyPatch, exercise_count: int
) -> None:
    templates = (BARBELL, BODYWEIGHT, DUMBBELL)
    weights = {"bench-press": 100, "pull-up": None, "dumbbell-curl": 12}
    historical: list[ExerciseSpec] = []
    current: list[ExerciseSpec] = []
    for index in range(exercise_count):
        template = templates[index % len(templates)]
        weight = weights[template.catalog_id]
        historical.append(replace(template, sets=(completed(6, weight),)))
        current.append(replace(template, sets=(completed(8, weight),)))

    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-previous", started_at=PREVIOUS_START, bodyweight_kg=80, exercises=historical
        )
        seed_workout(conn, VIEWED, started_at=VIEWED_START, bodyweight_kg=80, exercises=current)

    with counting_queries(db, monkeypatch) as statements:
        graph = read_graph(db, VIEWED)
    assert len(graph.exercises) == exercise_count
    assert all(item is not None for item in graph.previous_performance)
    # Three graph queries plus three previous-performance queries, however
    # large the graph or the training history.
    assert len(selects(statements)) == 6
