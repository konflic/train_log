"""Owner-scoped per-exercise statistics (exercise information screen).

One read query over the caller's eligible history for a single catalog entry:
finished workouts with `done=1` sets referencing that catalog id. Load and
volume derive from each workout's recorded bodyweight and the exercise's
stored load-snapshot inputs (with per-set overrides), never from the current
profile or catalog settings, so later edits cannot rewrite history. The
arithmetic reuses `app.numbers.calculate_set_load`, keeping the shared
floor-division, unknown-input, and estimated-1RM contracts.

Aggregation rules mirror the Stage 8b summary at both lifetime and session
level: no eligible sets is a known zero total, all-unknown loads is a `None`
total, a partial sum keeps `volume_complete=False` with the positive unknown
count, and an aggregate beyond the shared JSON-safe integer range raises
`NumericRangeError` (the API fails explicitly rather than emitting an
imprecise number). Repeated occurrences of the catalog exercise inside one
workout aggregate into a single session point. The series selects the latest
12 eligible workouts under `(started_at DESC, id DESC)` and emits them
oldest-to-newest.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.db import connect
from app.numbers import NumericRangeError, calculate_set_load, require_safe_integer
from app.schemas.common import LoadType
from app.schemas.stats import MAX_EXERCISE_STATS_SESSIONS

# Completed sets of the requested catalog exercise in the caller's finished
# workouts, with every recorded input needed to derive volume and 1RM in
# Python. Canonical UTC text order is time order for the session selection.
ELIGIBLE_SETS_SQL = """
SELECT w.id AS workout_id,
       w.started_at AS started_at,
       w.bodyweight_kg AS bodyweight_kg,
       e.load_type AS load_type,
       e.bodyweight_percent AS bodyweight_percent,
       e.side_count AS side_count,
       s.reps AS reps,
       s.weight_kg AS weight_kg,
       s.bw_percent_override AS bw_percent_override
FROM workouts AS w
JOIN exercises AS e ON e.workout_id = w.id
JOIN sets AS s ON s.exercise_id = e.id
WHERE w.user_id = :user_id
  AND w.ended_at IS NOT NULL
  AND s.done = 1
  AND e.catalog_id = :catalog_id
"""


@dataclass(frozen=True, slots=True)
class ExerciseStatsSession:
    """One eligible workout's aggregate for the requested exercise."""

    workout_id: str
    started_at: str
    completed_set_count: int
    volume_kg_reps: int | None
    unknown_load_set_count: int
    volume_complete: bool


@dataclass(frozen=True, slots=True)
class ExerciseStats:
    """Lifetime totals plus the latest-12 session series, oldest first."""

    training_count: int
    completed_set_count: int
    total_volume_kg_reps: int | None
    unknown_load_set_count: int
    volume_complete: bool
    best_estimated_1rm_kg: int | None
    sessions: tuple[ExerciseStatsSession, ...]


@dataclass(slots=True)
class _WorkoutAggregate:
    started_at: str
    set_count: int = 0
    known_volume: int = 0
    unknown_sets: int = 0


def _set_values(row: sqlite3.Row) -> tuple[int | None, int | None]:
    """One completed set's (volume, estimated 1RM) from recorded inputs only.

    The effective bodyweight percentage is the set override when recorded,
    otherwise the exercise snapshot's. A per-set value beyond the shared safe
    range (a legacy row of individually valid inputs) degrades to unknown,
    matching the summary and detail reads; only aggregate sums fail loudly.
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
        return None, None
    return loads.volume_kg_reps, loads.estimated_1rm_kg


def _session_volume(aggregate: _WorkoutAggregate) -> tuple[int | None, bool]:
    """Session volume with the shared completeness semantics."""
    if aggregate.set_count == 0:
        # Cannot occur for emitted sessions (eligibility requires a completed
        # set), but keep the known-zero rule explicit rather than unreachable.
        return 0, True
    if aggregate.unknown_sets == aggregate.set_count:
        return None, False
    volume = require_safe_integer(aggregate.known_volume, name="volume_kg_reps")
    return volume, aggregate.unknown_sets == 0


def get_exercise_stats(
    database_path: str | Path,
    *,
    user_id: str,
    catalog_id: str,
) -> ExerciseStats:
    """Lifetime totals and the latest-12 volume series for one catalog entry.

    Visibility (default or the caller's own custom) is checked by the API
    layer before this read; the query itself is strictly owner-scoped, so a
    foreign custom id simply yields empty statistics like an unknown id.
    """
    with connect(database_path) as conn:
        rows = conn.execute(
            ELIGIBLE_SETS_SQL, {"user_id": user_id, "catalog_id": catalog_id}
        ).fetchall()

    aggregates: dict[str, _WorkoutAggregate] = {}
    total_sets = 0
    total_known_volume = 0
    total_unknown_sets = 0
    best_1rm: int | None = None
    for row in rows:
        workout_id = str(row["workout_id"])
        aggregate = aggregates.get(workout_id)
        if aggregate is None:
            aggregate = _WorkoutAggregate(started_at=str(row["started_at"]))
            aggregates[workout_id] = aggregate
        volume, one_rm = _set_values(row)
        aggregate.set_count += 1
        total_sets += 1
        if volume is None:
            aggregate.unknown_sets += 1
            total_unknown_sets += 1
        else:
            aggregate.known_volume += volume
            total_known_volume += volume
        if one_rm is not None and (best_1rm is None or one_rm > best_1rm):
            best_1rm = one_rm

    # Latest 12 eligible workouts under (started_at DESC, id DESC), emitted
    # oldest-to-newest for the chart.
    latest = sorted(aggregates.items(), key=lambda item: (item[1].started_at, item[0]))
    latest.reverse()
    sessions: list[ExerciseStatsSession] = []
    for workout_id, aggregate in latest[:MAX_EXERCISE_STATS_SESSIONS]:
        volume, complete = _session_volume(aggregate)
        sessions.append(
            ExerciseStatsSession(
                workout_id=workout_id,
                started_at=aggregate.started_at,
                completed_set_count=aggregate.set_count,
                volume_kg_reps=volume,
                unknown_load_set_count=aggregate.unknown_sets,
                volume_complete=complete,
            )
        )
    sessions.reverse()

    if total_sets == 0:
        # No eligible history: zero counts, a known zero total, null best 1RM.
        total_volume: int | None = 0
        total_complete = True
    elif total_unknown_sets == total_sets:
        total_volume = None
        total_complete = False
    else:
        total_volume = require_safe_integer(total_known_volume, name="total_volume_kg_reps")
        total_complete = total_unknown_sets == 0

    return ExerciseStats(
        training_count=len(aggregates),
        completed_set_count=total_sets,
        total_volume_kg_reps=total_volume,
        unknown_load_set_count=total_unknown_sets,
        volume_complete=total_complete,
        best_estimated_1rm_kg=best_1rm,
        sessions=tuple(sessions),
    )
