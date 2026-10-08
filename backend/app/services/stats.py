"""Bounded Phase 1 statistics summary (PLAN.md §7).

One owner-scoped read transaction with exactly two data queries, independent
of history size: the selected range's completed sets joined to their recorded
workout/exercise/catalog inputs, and the start instants of every eligible
finished workout for the full-history weekly streak. Load arithmetic is reused
from `app.numbers` in Python rather than duplicated in SQL, so the summary
follows the same recorded-input, missing-data, and safe-range rules as the
workout detail read.

Eligibility is fixed: finished workouts with at least one `done=1` set. A
completed set whose volume is unknown (missing bodyweight for an applied
percentage, or a pre-Stage-8 row whose derived value exceeds the shared safe
range) keeps the workout eligible and counts toward `unknown_load_set_count`.
Calendar grouping applies the caller's current fixed UTC offset with
Monday-start, half-open weeks; `local_date_bounds` converts inclusive local
date filters to the canonical-UTC range query.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast, get_args

from app.db import connect
from app.numbers import NumericRangeError, calculate_set_load, require_safe_integer
from app.schemas.common import LoadType
from app.schemas.exercises import MuscleGroup
from app.services.workouts import local_date_bounds
from app.timestamps import parse_timestamp

# Canonical emission order for `muscle_group_frequency`, taken from the shared
# Literal so the service, the response schema, and the catalog CHECK cannot
# drift apart. Every group is always emitted, with a zero count when unused.
MUSCLE_GROUP_ORDER: tuple[str, ...] = get_args(MuscleGroup)

# Completed sets of eligible finished workouts in the selected range, with
# every recorded input needed to derive volume in Python and the catalog's
# current muscle group (exercise snapshots do not store it).
RANGED_COMPLETED_SETS_SQL = """
SELECT w.id AS workout_id,
       w.started_at AS started_at,
       w.bodyweight_kg AS bodyweight_kg,
       c.muscle_group AS muscle_group,
       e.load_type AS load_type,
       e.bodyweight_percent AS bodyweight_percent,
       e.side_count AS side_count,
       s.reps AS reps,
       s.weight_kg AS weight_kg,
       s.bw_percent_override AS bw_percent_override
FROM workouts AS w
JOIN exercises AS e ON e.workout_id = w.id
JOIN sets AS s ON s.exercise_id = e.id
JOIN exercise_catalog AS c ON c.id = e.catalog_id
WHERE w.user_id = :user_id
  AND w.ended_at IS NOT NULL
  AND s.done = 1
"""

# Start instants of every eligible finished workout, unfiltered by date: the
# streak always covers full history (resolved decision 5).
ELIGIBLE_STARTED_AT_SQL = """
SELECT w.started_at AS started_at
FROM workouts AS w
WHERE w.user_id = :user_id
  AND w.ended_at IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM exercises AS e
      JOIN sets AS s ON s.exercise_id = e.id
      WHERE e.workout_id = w.id
        AND s.done = 1
  )
"""


@dataclass(frozen=True, slots=True)
class MuscleGroupFrequency:
    """One muscle group's eligible-workout count in the selected range."""

    muscle_group: str
    workout_count: int


@dataclass(frozen=True, slots=True)
class StatsSummary:
    """The complete summary; `None` volume means every eligible load is unknown."""

    workout_count: int
    completed_set_count: int
    training_day_count: int
    total_volume_kg_reps: int | None
    unknown_load_set_count: int
    volume_complete: bool
    muscle_group_frequency: tuple[MuscleGroupFrequency, ...]
    current_week_streak: int


def _local_date(moment: datetime, utc_offset_minutes: int) -> date:
    """The caller's local calendar date for one aware instant.

    Instants within one extreme offset (up to +14 h / -12 h) of the datetime
    bounds clamp to the representable calendar edge instead of failing the
    read; stored timestamps may legally span the full canonical range.
    """
    if moment.tzinfo is None:
        raise ValueError("naive datetimes are not canonical UTC timestamps")
    try:
        return (moment + timedelta(minutes=utc_offset_minutes)).date()
    except OverflowError:
        return date.max if utc_offset_minutes > 0 else date.min


def _monday(day: date) -> date:
    """The Monday starting `day`'s local week (weeks are Monday-start)."""
    return day - timedelta(days=day.weekday())


def _set_volume(row: sqlite3.Row) -> int | None:
    """One completed set's volume from recorded inputs only (PLAN.md §3).

    The set's effective bodyweight percentage is its override when one is
    recorded, otherwise the exercise snapshot's. `NumericRangeError` marks a
    pre-Stage-8 row whose individually valid inputs derive an unsafe value;
    like the detail read, it degrades to unknown volume without losing
    eligibility.
    """
    percent = row["bw_percent_override"]
    if percent is None:
        percent = row["bodyweight_percent"]
    try:
        loads = calculate_set_load(
            reps=row["reps"],
            weight_kg=row["weight_kg"],
            load_type=cast(LoadType, row["load_type"]),
            side_count=int(row["side_count"]),
            bodyweight_kg=row["bodyweight_kg"],
            bodyweight_percent=percent,
        )
    except NumericRangeError:
        return None
    return loads.volume_kg_reps


def _current_week_streak(
    started_ats: Iterable[str], *, utc_offset_minutes: int, now: datetime
) -> int:
    """Consecutive eligible Monday-start weeks, allowing an ongoing week.

    The walk starts at the current local week when eligible and otherwise at
    the immediately previous week, which may still be in progress; zero when
    neither is eligible.
    """
    eligible_weeks = {
        _monday(_local_date(parse_timestamp(text), utc_offset_minutes)) for text in started_ats
    }
    week = _monday(_local_date(now, utc_offset_minutes))
    if week not in eligible_weeks:
        week -= timedelta(days=7)
        if week not in eligible_weeks:
            return 0
    streak = 0
    while week in eligible_weeks:
        streak += 1
        week -= timedelta(days=7)
    return streak


def _summarize(
    set_rows: Sequence[sqlite3.Row],
    started_ats: Sequence[str],
    *,
    utc_offset_minutes: int,
    now: datetime,
) -> StatsSummary:
    known_volume = 0
    unknown_sets = 0
    workout_days: dict[str, date] = {}
    group_workouts: dict[str, set[str]] = {}
    for row in set_rows:
        workout_id = str(row["workout_id"])
        if workout_id not in workout_days:
            workout_days[workout_id] = _local_date(
                parse_timestamp(str(row["started_at"])), utc_offset_minutes
            )
        group_workouts.setdefault(str(row["muscle_group"]), set()).add(workout_id)
        volume = _set_volume(row)
        if volume is None:
            unknown_sets += 1
        else:
            known_volume += volume

    completed_sets = len(set_rows)
    total: int | None
    if completed_sets == 0:
        # No eligible sets is a known zero, never an unknown total.
        total = 0
    elif unknown_sets == completed_sets:
        total = None
    else:
        # Exact Python integers throughout; the emitted aggregate must fit the
        # shared JSON-safe range. Overflow raises NumericRangeError, which the
        # API reports as an explicit 500 rather than an imprecise number or a
        # fabricated missing-data state.
        total = require_safe_integer(known_volume, name="total_volume_kg_reps")

    return StatsSummary(
        workout_count=len(workout_days),
        completed_set_count=completed_sets,
        training_day_count=len(set(workout_days.values())),
        total_volume_kg_reps=total,
        unknown_load_set_count=unknown_sets,
        volume_complete=unknown_sets == 0,
        muscle_group_frequency=tuple(
            MuscleGroupFrequency(
                muscle_group=group,
                workout_count=len(group_workouts.get(group, ())),
            )
            for group in MUSCLE_GROUP_ORDER
        ),
        current_week_streak=_current_week_streak(
            started_ats, utc_offset_minutes=utc_offset_minutes, now=now
        ),
    )


def get_stats_summary(
    database_path: str | Path,
    *,
    user_id: str,
    utc_offset_minutes: int,
    date_from: date | None = None,
    date_to: date | None = None,
    now: datetime | None = None,
) -> StatsSummary:
    """The caller's statistics summary on one consistent read snapshot.

    `date_from`/`date_to` are inclusive local calendar dates filtering every
    member except `current_week_streak`; a reversed pair is a valid empty
    selection, matching workout history. `now` is sampled once per request and
    is injectable for deterministic streak boundary tests.
    """
    moment = datetime.now(UTC) if now is None else now
    started_from, started_to = local_date_bounds(
        date_from=date_from, date_to=date_to, utc_offset_minutes=utc_offset_minutes
    )
    params: dict[str, Any] = {"user_id": user_id}
    set_query = RANGED_COMPLETED_SETS_SQL
    if started_from is not None:
        # Canonical UTC text has one fixed width, so text order is time order.
        set_query += "  AND w.started_at >= :started_from\n"
        params["started_from"] = started_from
    if started_to is not None:
        set_query += "  AND w.started_at < :started_to\n"
        params["started_to"] = started_to

    with connect(database_path) as conn, conn:
        # Both queries share one snapshot while concurrent saves commit (WAL).
        conn.execute("BEGIN")
        set_rows = conn.execute(set_query, params).fetchall()
        start_rows = conn.execute(ELIGIBLE_STARTED_AT_SQL, {"user_id": user_id}).fetchall()

    return _summarize(
        set_rows,
        [str(row["started_at"]) for row in start_rows],
        utc_offset_minutes=utc_offset_minutes,
        now=moment,
    )
