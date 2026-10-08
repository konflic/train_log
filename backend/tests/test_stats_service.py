"""Stage 8b statistics summary service tests (Gate G8b).

Direct-SQLite coverage of eligibility (finished workouts with completed sets
only), the missing-data volume contract, recorded-input stability against
profile and catalog edits, inclusive local-date ranges with half-open UTC
bounds at extreme offsets, Monday-start week boundaries, the ongoing-week
streak rule with an injected clock, muscle-group deduplication and canonical
ordering, owner isolation, safe-range degradation and aggregate overflow, the
two-query bound, and snapshot consistency during a concurrent WAL commit.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from helpers import insert_catalog_entry, insert_exercise, insert_set, insert_user, insert_workout

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER, NumericRangeError
from app.services import stats
from app.services.stats import MUSCLE_GROUP_ORDER, StatsSummary

# Wednesday noon UTC; at offset 0 the current local week started Monday
# 2026-03-02 and the previous week started Monday 2026-02-23.
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)

THIS_WEEK_MONDAY = "2026-03-02T09:00:00Z"
PREVIOUS_WEEK_WEDNESDAY = "2026-02-25T09:00:00Z"
TWO_WEEKS_AGO_WEDNESDAY = "2026-02-18T09:00:00Z"


@dataclass(frozen=True)
class SetRow:
    """One set row; the defaults describe a completed bilateral weighted set."""

    reps: int | None = 8
    weight_kg: int | None = 100
    side: str = "bilateral"
    done: bool = True
    bw_percent_override: int | None = None


@dataclass(frozen=True)
class ExerciseRow:
    """One exercise occurrence; defaults describe the seeded bench snapshot."""

    catalog_id: str = "bench-press"
    load_type: str = "single_weight"
    side_count: int = 1
    bodyweight_percent: int | None = None
    sets: tuple[SetRow, ...] = ()


BARBELL = ExerciseRow()
PUSHUP = ExerciseRow(catalog_id="push-up", load_type="bodyweight", bodyweight_percent=65)
PULLUP = ExerciseRow(catalog_id="pull-up", load_type="bodyweight", bodyweight_percent=100)
CURL = ExerciseRow(catalog_id="dumbbell-curl", load_type="split_weight", side_count=2)


def barbell(*sets: SetRow) -> ExerciseRow:
    return replace(BARBELL, sets=sets)


def pushup(*sets: SetRow) -> ExerciseRow:
    return replace(PUSHUP, sets=sets)


def pullup(*sets: SetRow) -> ExerciseRow:
    return replace(PULLUP, sets=sets)


def curl(*sets: SetRow) -> ExerciseRow:
    return replace(CURL, sets=sets)


def completed(reps: int = 8, weight_kg: int | None = 100, **overrides: Any) -> SetRow:
    return SetRow(reps=reps, weight_kg=weight_kg, **overrides)


def draft() -> SetRow:
    return SetRow(reps=None, weight_kg=None, done=False)


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
    ended_at: str | None = "2026-06-01T00:00:00Z",
    bodyweight_kg: int | None = None,
    user_id: str = "user-1",
    exercises: Sequence[ExerciseRow] = (),
) -> None:
    """Insert one workout plus its graph with deterministic nested ids."""
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


def summary(db: Path, **overrides: Any) -> StatsSummary:
    params: dict[str, Any] = {"user_id": "user-1", "utc_offset_minutes": 0, "now": NOW}
    params.update(overrides)
    return stats.get_stats_summary(db, **params)


def groups(result: StatsSummary) -> dict[str, int]:
    return {item.muscle_group: item.workout_count for item in result.muscle_group_frequency}


@contextmanager
def counting_queries(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Capture every statement the stats service issues for one summary."""
    statements: list[str] = []
    real_connect = stats.connect

    @contextmanager
    def counting_connect(path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        with real_connect(path, **kwargs) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(stats, "connect", counting_connect)
    yield statements


def selects(statements: Sequence[str]) -> list[str]:
    return [item for item in statements if item.lstrip().upper().startswith("SELECT")]


# --- eligibility ---------------------------------------------------------------


def test_empty_history_reports_known_zero_and_zero_streak(db: Path) -> None:
    result = summary(db)
    assert result.workout_count == 0
    assert result.completed_set_count == 0
    assert result.training_day_count == 0
    # No eligible sets is a known zero, never an unknown total.
    assert result.total_volume_kg_reps == 0
    assert result.unknown_load_set_count == 0
    assert result.volume_complete is True
    assert result.current_week_streak == 0
    assert [item.muscle_group for item in result.muscle_group_frequency] == list(MUSCLE_GROUP_ORDER)
    assert groups(result) == dict.fromkeys(MUSCLE_GROUP_ORDER, 0)


def test_active_workouts_and_draft_sets_never_contribute(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-active",
            started_at=THIS_WEEK_MONDAY,
            ended_at=None,
            exercises=(barbell(completed(8, 100)),),
        )
        seed_workout(
            conn,
            "w-drafts",
            started_at=PREVIOUS_WEEK_WEDNESDAY,
            exercises=(barbell(draft(), draft()),),
        )
    result = summary(db)
    assert result.workout_count == 0
    assert result.completed_set_count == 0
    assert result.total_volume_kg_reps == 0
    assert result.volume_complete is True
    assert result.current_week_streak == 0
    assert groups(result) == dict.fromkeys(MUSCLE_GROUP_ORDER, 0)


def test_finished_workout_without_exercises_is_ineligible(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(conn, "w-empty", started_at=THIS_WEEK_MONDAY)
    result = summary(db)
    assert result.workout_count == 0
    assert result.current_week_streak == 0


# --- counts and the missing-data volume contract --------------------------------


def test_counts_days_and_known_volume(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Monday: bench 8x100 = 800 plus split curls 2x12x8 = 192.
        seed_workout(
            conn,
            "w-monday",
            started_at=THIS_WEEK_MONDAY,
            exercises=(barbell(completed(8, 100)), curl(completed(8, 12))),
        )
        # Tuesday: bench 5x100 = 500.
        seed_workout(
            conn,
            "w-tuesday",
            started_at="2026-03-03T09:00:00Z",
            exercises=(barbell(completed(5, 100)),),
        )
    result = summary(db)
    assert result.workout_count == 2
    assert result.completed_set_count == 3
    assert result.training_day_count == 2
    assert result.total_volume_kg_reps == 1492
    assert result.unknown_load_set_count == 0
    assert result.volume_complete is True
    assert groups(result)["chest"] == 2
    assert groups(result)["arms"] == 1
    assert groups(result)["back"] == 0


def test_multiple_workouts_on_one_local_day_share_one_training_day(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-morning", started_at=THIS_WEEK_MONDAY, exercises=(barbell(completed()),)
        )
        seed_workout(
            conn,
            "w-evening",
            started_at="2026-03-02T18:00:00Z",
            exercises=(barbell(completed()),),
        )
    result = summary(db)
    assert result.workout_count == 2
    assert result.training_day_count == 1


def test_known_zero_load_contributes_known_zero_volume(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-zero", started_at=THIS_WEEK_MONDAY, exercises=(barbell(completed(5, 0)),)
        )
    result = summary(db)
    assert result.total_volume_kg_reps == 0
    assert result.unknown_load_set_count == 0
    assert result.volume_complete is True


def test_missing_bodyweight_makes_an_applied_percentage_unknown(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Pure-bodyweight set with no recorded workout bodyweight: eligible but
        # unknown volume (PLAN.md §3).
        seed_workout(
            conn,
            "w-unknown",
            started_at=THIS_WEEK_MONDAY,
            bodyweight_kg=None,
            exercises=(pushup(completed(10, None)),),
        )
    result = summary(db)
    assert result.workout_count == 1
    assert result.completed_set_count == 1
    assert result.training_day_count == 1
    assert result.total_volume_kg_reps is None
    assert result.unknown_load_set_count == 1
    assert result.volume_complete is False
    assert groups(result)["chest"] == 1
    assert result.current_week_streak == 1


def test_mixed_known_and_unknown_volumes_report_the_known_sum(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-mixed",
            started_at=THIS_WEEK_MONDAY,
            bodyweight_kg=None,
            exercises=(barbell(completed(8, 100)), pullup(completed(5, None))),
        )
    result = summary(db)
    assert result.completed_set_count == 2
    assert result.total_volume_kg_reps == 800
    assert result.unknown_load_set_count == 1
    assert result.volume_complete is False


def test_set_override_replaces_the_snapshot_percentage(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # 80 kg at an overridden 50% gives 40 kg; 10 reps give 400 kg-reps.
        seed_workout(
            conn,
            "w-override",
            started_at=THIS_WEEK_MONDAY,
            bodyweight_kg=80,
            exercises=(pushup(completed(10, None, bw_percent_override=50)),),
        )
    result = summary(db)
    assert result.total_volume_kg_reps == 400
    assert result.volume_complete is True


# --- recorded inputs survive later edits ------------------------------------------


def test_recorded_bodyweight_and_snapshots_survive_profile_and_catalog_edits(
    db: Path,
) -> None:
    with connect(db) as conn, write_transaction(conn):
        # 80 kg at the seeded 65% gives 52 kg; 10 reps give 520 kg-reps.
        seed_workout(
            conn,
            "w-history",
            started_at=THIS_WEEK_MONDAY,
            bodyweight_kg=80,
            exercises=(pushup(completed(10, None)),),
        )
        conn.execute("UPDATE users SET bodyweight_default_kg = 100 WHERE id = 'user-1'")
        conn.execute("UPDATE exercise_catalog SET bodyweight_percent = 90 WHERE id = 'push-up'")
    result = summary(db)
    assert result.total_volume_kg_reps == 520
    assert result.volume_complete is True


def test_muscle_group_frequency_follows_the_current_catalog_classification(
    db: Path,
) -> None:
    with connect(db) as conn, write_transaction(conn):
        insert_catalog_entry(
            conn,
            "cat-custom-1",
            name="Custom Press",
            muscle_group="arms",
            equipment="machine",
            load_type="single_weight",
            side_count=1,
        )
        exercise = ExerciseRow(catalog_id="cat-custom-1", sets=(completed(8, 100),))
        seed_workout(conn, "w-custom", started_at=THIS_WEEK_MONDAY, exercises=(exercise,))
    assert groups(summary(db))["arms"] == 1

    with connect(db) as conn, write_transaction(conn):
        # The schema does not snapshot muscle group, so an owner edit to a
        # custom entry reclassifies historical frequency (resolved decision 7).
        conn.execute("UPDATE exercise_catalog SET muscle_group = 'core' WHERE id = 'cat-custom-1'")
    result = groups(summary(db))
    assert result["arms"] == 0
    assert result["core"] == 1


def test_muscle_group_counts_deduplicate_workouts_within_a_group(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # One workout, two chest occurrences and one back exercise.
        seed_workout(
            conn,
            "w-dedup",
            started_at=THIS_WEEK_MONDAY,
            exercises=(
                barbell(completed(8, 100)),
                barbell(completed(5, 90)),
                pullup(completed(6, None)),
            ),
            bodyweight_kg=80,
        )
    result = summary(db)
    assert result.workout_count == 1
    assert result.completed_set_count == 3
    assert groups(result)["chest"] == 1
    assert groups(result)["back"] == 1


# --- local-date ranges ------------------------------------------------------------


def test_date_ranges_are_inclusive_local_dates_with_half_open_utc_bounds(
    db: Path,
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-late", started_at="2026-01-01T23:30:00Z", exercises=(barbell(completed()),)
        )
        seed_workout(
            conn,
            "w-midnight",
            started_at="2026-01-02T00:00:00Z",
            exercises=(barbell(completed()),),
        )
    day1 = date(2026, 1, 1)
    day2 = date(2026, 1, 2)

    # Offset 0: only `w-late` falls on January 1st; `date_to` is inclusive and
    # `w-midnight` sits exactly on the next day's half-open boundary.
    assert summary(db, date_from=day1, date_to=day1).workout_count == 1
    assert summary(db, date_from=day2, date_to=day2).workout_count == 1
    assert summary(db, date_from=day2).workout_count == 1
    assert summary(db, date_to=day1).workout_count == 1

    # Offset +2 h moves `w-late` to local January 2nd, joining `w-midnight`.
    assert summary(db, utc_offset_minutes=120, date_from=day2, date_to=day2).workout_count == 2
    assert summary(db, utc_offset_minutes=120, date_from=day1, date_to=day1).workout_count == 0


def test_extreme_offsets_shift_day_boundaries(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-early", started_at="2026-01-01T05:00:00Z", exercises=(barbell(completed()),)
        )
        seed_workout(
            conn, "w-noon", started_at="2026-01-01T13:00:00Z", exercises=(barbell(completed()),)
        )
    # UTC+14 (the supported maximum) moves the noon workout to January 2nd.
    plus = summary(db, utc_offset_minutes=840, date_from=date(2026, 1, 2))
    assert plus.workout_count == 1
    # UTC-12 (the supported minimum) moves the early workout to December 31st.
    minus = summary(db, utc_offset_minutes=-720, date_to=date(2025, 12, 31))
    assert minus.workout_count == 1
    assert summary(db, utc_offset_minutes=-720, date_from=date(2026, 1, 1)).workout_count == 1


def test_reversed_range_returns_empty_selection_but_keeps_the_streak(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn, "w-current", started_at=THIS_WEEK_MONDAY, exercises=(barbell(completed()),)
        )
    result = summary(db, date_from=date(2026, 1, 20), date_to=date(2026, 1, 10))
    assert result.workout_count == 0
    assert result.completed_set_count == 0
    assert result.total_volume_kg_reps == 0
    assert result.volume_complete is True
    assert groups(result) == dict.fromkeys(MUSCLE_GROUP_ORDER, 0)
    # The streak covers full history and ignores the (empty) selection.
    assert result.current_week_streak == 1


def test_instants_near_the_datetime_extremes_clamp_instead_of_failing(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-max",
            started_at="9999-12-31T23:59:59Z",
            ended_at="9999-12-31T23:59:59Z",
            exercises=(barbell(completed()),),
        )
        seed_workout(
            conn,
            "w-min",
            started_at="0001-01-01T00:00:00Z",
            ended_at="0001-01-01T00:00:00Z",
            exercises=(barbell(completed()),),
        )
    for offset in (840, -720):
        result = summary(db, utc_offset_minutes=offset)
        assert result.workout_count == 2
        assert result.training_day_count == 2


# --- weekly streaks ----------------------------------------------------------------


def seed_weeks(conn: sqlite3.Connection, *started_ats: str) -> None:
    for index, started_at in enumerate(started_ats):
        seed_workout(
            conn,
            f"w-week-{index}",
            started_at=started_at,
            exercises=(barbell(completed()),),
        )


def test_streak_counts_the_current_and_consecutive_previous_weeks(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_weeks(conn, THIS_WEEK_MONDAY, PREVIOUS_WEEK_WEDNESDAY, TWO_WEEKS_AGO_WEDNESDAY)
    assert summary(db).current_week_streak == 3


def test_streak_starts_from_the_previous_week_while_the_current_one_runs(
    db: Path,
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_weeks(conn, PREVIOUS_WEEK_WEDNESDAY, TWO_WEEKS_AGO_WEDNESDAY)
    assert summary(db).current_week_streak == 2


def test_streak_is_zero_when_current_and_previous_weeks_are_empty(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_weeks(conn, TWO_WEEKS_AGO_WEDNESDAY)
    assert summary(db).current_week_streak == 0


def test_a_gap_breaks_the_streak(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_weeks(conn, THIS_WEEK_MONDAY, TWO_WEEKS_AGO_WEDNESDAY)
    assert summary(db).current_week_streak == 1


def test_weeks_start_monday_in_local_time(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Sunday 23:30 UTC and the following Monday 00:30 UTC.
        seed_weeks(conn, "2026-03-01T23:30:00Z", "2026-03-02T00:30:00Z")
    assert summary(db).current_week_streak == 2
    # Offset +2 h moves the Sunday workout into the Monday's week, so both
    # share the current week and the older week is no longer consecutive.
    assert summary(db, utc_offset_minutes=120).current_week_streak == 1


def test_streak_weeks_use_the_offset_for_workouts_and_now_alike(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_weeks(conn, "2026-03-01T23:30:00Z", TWO_WEEKS_AGO_WEDNESDAY)
    monday_morning = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)
    # Offset 0: the Sunday workout anchors the previous week, which is
    # consecutive with the week of February 16th.
    assert summary(db, now=monday_morning).current_week_streak == 2
    # Offset +2 h: the Sunday workout moves into `now`'s current week, leaving
    # the previous week empty and breaking the chain.
    assert summary(db, utc_offset_minutes=120, now=monday_morning).current_week_streak == 1


def test_a_naive_now_is_rejected(db: Path) -> None:
    with pytest.raises(ValueError, match="naive"):
        summary(db, now=datetime(2026, 3, 4, 12, 0))


# --- owner isolation ---------------------------------------------------------------


def test_other_users_workouts_never_contribute(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-foreign",
            started_at=THIS_WEEK_MONDAY,
            user_id="user-2",
            bodyweight_kg=90,
            exercises=(barbell(completed(8, 100)),),
        )
    mine = summary(db)
    assert mine.workout_count == 0
    assert mine.total_volume_kg_reps == 0
    assert mine.current_week_streak == 0
    theirs = summary(db, user_id="user-2")
    assert theirs.workout_count == 1
    assert theirs.total_volume_kg_reps == 800
    assert theirs.current_week_streak == 1


# --- safe-range handling -------------------------------------------------------------


def test_legacy_unsafe_set_volume_counts_unknown_without_losing_eligibility(
    db: Path,
) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Individually safe inputs whose product exceeds the shared range:
        # eligible everywhere, unknown volume (Stage 8a compatibility rule).
        seed_workout(
            conn,
            "w-legacy",
            started_at=THIS_WEEK_MONDAY,
            exercises=(barbell(completed(2, MAX_SAFE_INTEGER)),),
        )
    result = summary(db)
    assert result.workout_count == 1
    assert result.completed_set_count == 1
    assert result.training_day_count == 1
    assert result.total_volume_kg_reps is None
    assert result.unknown_load_set_count == 1
    assert result.volume_complete is False
    assert groups(result)["chest"] == 1
    assert result.current_week_streak == 1


def test_an_unsafe_aggregate_raises_rather_than_overflowing(db: Path) -> None:
    with connect(db) as conn, write_transaction(conn):
        # Two sets whose individual volumes are exactly the safe maximum.
        seed_workout(
            conn,
            "w-huge",
            started_at=THIS_WEEK_MONDAY,
            exercises=(barbell(completed(1, MAX_SAFE_INTEGER), completed(1, MAX_SAFE_INTEGER)),),
        )
    with pytest.raises(NumericRangeError):
        summary(db)


# --- query bound and snapshot consistency ---------------------------------------------


def test_summary_uses_exactly_two_selects_regardless_of_history_size(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(db) as conn, write_transaction(conn):
        for started_at in (
            "2026-01-08T09:00:00Z",
            "2026-01-15T09:00:00Z",
            "2026-01-22T09:00:00Z",
            "2026-01-29T09:00:00Z",
            "2026-02-05T09:00:00Z",
        ):
            seed_workout(
                conn,
                f"w-{started_at}",
                started_at=started_at,
                bodyweight_kg=80,
                exercises=(
                    barbell(completed(8, 100), completed(5, 90), draft()),
                    curl(completed(8, 12)),
                    pushup(completed(10, None)),
                ),
            )
    with counting_queries(db, monkeypatch) as statements:
        result = summary(db)
    assert result.workout_count == 5
    assert result.completed_set_count == 20
    assert len(selects(statements)) == 2
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"


def test_summary_uses_one_snapshot_during_a_concurrent_commit(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(db) as conn, write_transaction(conn):
        seed_workout(
            conn,
            "w-previous",
            started_at=PREVIOUS_WEEK_WEDNESDAY,
            exercises=(barbell(completed()),),
        )
    real_connect = stats.connect
    inserted = False

    @contextmanager
    def racing_connect(database_path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
        nonlocal inserted
        with real_connect(database_path, **kwargs) as conn:
            select_count = 0

            def insert_before_streak(statement: str) -> None:
                nonlocal inserted, select_count
                if not statement.lstrip().upper().startswith("SELECT"):
                    return
                select_count += 1
                if select_count == 2:
                    with real_connect(database_path) as writer, write_transaction(writer):
                        seed_workout(
                            writer,
                            "w-concurrent",
                            started_at=THIS_WEEK_MONDAY,
                            exercises=(barbell(completed()),),
                        )
                    inserted = True

            conn.set_trace_callback(insert_before_streak)
            yield conn

    monkeypatch.setattr(stats, "connect", racing_connect)
    result = summary(db)
    assert inserted is True
    # The current-week workout committed mid-read stays invisible on the
    # snapshot: the streak still starts from the previous week alone.
    assert result.workout_count == 1
    assert result.current_week_streak == 1
