"""Owner-scoped storage for reusable training plans."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.training_plans import TrainingPlanContent
from app.timestamps import now_timestamp


class TrainingPlanNotFoundError(Exception):
    """The plan is missing or belongs to another account."""


class TrainingPlanRevisionConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f"current revision is {current_revision}")
        self.current_revision = current_revision


class TrainingPlanCatalogError(Exception):
    """A plan references an unavailable catalog entry or invalid load target."""


class TrainingPlanInUseError(Exception):
    """A catalog relationship prevented deletion."""


@dataclass(frozen=True, slots=True)
class PlanSet:
    id: str
    set_index: int
    target_reps: int | None
    target_weight_kg: int | None
    side: str
    bw_percent_override: int | None


@dataclass(frozen=True, slots=True)
class PlanExercise:
    id: str
    catalog_id: str
    order_index: int
    notes: str | None
    sets: tuple[PlanSet, ...]


@dataclass(frozen=True, slots=True)
class TrainingPlan:
    id: str
    user_id: str
    name: str
    notes: str | None
    revision: int
    exercises: tuple[PlanExercise, ...]


@dataclass(frozen=True, slots=True)
class TrainingPlanSummary:
    id: str
    name: str
    notes: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class TrainingPlanPage:
    items: list[TrainingPlanSummary]
    total: int


def _read_plan(conn: sqlite3.Connection, plan_id: str, owner_id: str) -> TrainingPlan | None:
    row = conn.execute(
        "SELECT id, user_id, name, notes, revision FROM training_plans "
        "WHERE id = :id AND user_id = :owner_id",
        {"id": plan_id, "owner_id": owner_id},
    ).fetchone()
    if row is None:
        return None
    exercise_rows = conn.execute(
        "SELECT id, catalog_id, order_index, notes FROM training_plan_exercises "
        "WHERE plan_id = ? ORDER BY order_index",
        (plan_id,),
    ).fetchall()
    exercise_ids = [str(item["id"]) for item in exercise_rows]
    sets_by_exercise: dict[str, list[PlanSet]] = {item: [] for item in exercise_ids}
    if exercise_ids:
        placeholders = ", ".join("?" for _ in exercise_ids)
        for item in conn.execute(
            "SELECT id, plan_exercise_id, set_index, target_reps, target_weight_kg, "
            "side, bw_percent_override FROM training_plan_sets "
            f"WHERE plan_exercise_id IN ({placeholders}) "
            "ORDER BY plan_exercise_id, set_index",
            exercise_ids,
        ).fetchall():
            sets_by_exercise[str(item["plan_exercise_id"])].append(
                PlanSet(
                    id=str(item["id"]),
                    set_index=int(item["set_index"]),
                    target_reps=item["target_reps"],
                    target_weight_kg=item["target_weight_kg"],
                    side=str(item["side"]),
                    bw_percent_override=item["bw_percent_override"],
                )
            )
    return TrainingPlan(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        notes=row["notes"],
        revision=int(row["revision"]),
        exercises=tuple(
            PlanExercise(
                id=str(item["id"]),
                catalog_id=str(item["catalog_id"]),
                order_index=int(item["order_index"]),
                notes=item["notes"],
                sets=tuple(sets_by_exercise[str(item["id"])]),
            )
            for item in exercise_rows
        ),
    )


def _validated_catalog(
    conn: sqlite3.Connection, owner_id: str, content: TrainingPlanContent
) -> dict[str, sqlite3.Row]:
    catalog_ids = list(dict.fromkeys(item.catalog_id for item in content.exercises))
    if not catalog_ids:
        return {}
    placeholders = ", ".join("?" for _ in catalog_ids)
    rows = conn.execute(
        "SELECT id, load_type, bodyweight_percent, side_count FROM exercise_catalog "
        f"WHERE id IN ({placeholders}) AND (is_default = 1 OR created_by = ?)",
        [*catalog_ids, owner_id],
    ).fetchall()
    catalog = {str(row["id"]): row for row in rows}
    if len(catalog) != len(catalog_ids):
        raise TrainingPlanCatalogError("A catalog entry is unavailable")
    for exercise_index, exercise in enumerate(content.exercises):
        snapshot = catalog[exercise.catalog_id]
        split_single = snapshot["load_type"] == "split_weight" and snapshot["side_count"] == 1
        expected_sides = {"left", "right"} if split_single else {"bilateral"}
        for set_index, target in enumerate(exercise.sets):
            prefix = f"exercises.{exercise_index}.sets.{set_index}"
            if target.side not in expected_sides:
                raise TrainingPlanCatalogError(f"{prefix}.side is incompatible with the exercise")
            if snapshot["load_type"] == "bodyweight" and target.target_weight_kg is not None:
                raise TrainingPlanCatalogError(f"{prefix}.target_weight_kg must be null")
            if target.bw_percent_override is not None and snapshot["bodyweight_percent"] is None:
                raise TrainingPlanCatalogError(
                    f"{prefix}.bw_percent_override requires a bodyweight contribution"
                )
    return catalog


def _replace_graph(
    conn: sqlite3.Connection, plan_id: str, owner_id: str, content: TrainingPlanContent
) -> None:
    _validated_catalog(conn, owner_id, content)
    conn.execute("DELETE FROM training_plan_exercises WHERE plan_id = ?", (plan_id,))
    for order_index, exercise in enumerate(content.exercises):
        exercise_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO training_plan_exercises "
            "(id, plan_id, catalog_id, order_index, notes) VALUES (?, ?, ?, ?, ?)",
            (exercise_id, plan_id, exercise.catalog_id, order_index, exercise.notes),
        )
        conn.executemany(
            "INSERT INTO training_plan_sets (id, plan_exercise_id, set_index, target_reps, "
            "target_weight_kg, side, bw_percent_override) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(uuid.uuid4()),
                    exercise_id,
                    set_index,
                    target.target_reps,
                    target.target_weight_kg,
                    target.side,
                    target.bw_percent_override,
                )
                for set_index, target in enumerate(exercise.sets)
            ],
        )


def create_plan(
    database_path: str | Path, *, owner_id: str, content: TrainingPlanContent
) -> TrainingPlan:
    plan_id = str(uuid.uuid4())
    now = now_timestamp()
    with connect(database_path) as conn, write_transaction(conn):
        _validated_catalog(conn, owner_id, content)
        conn.execute(
            "INSERT INTO training_plans "
            "(id, user_id, name, notes, revision, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (plan_id, owner_id, content.name, content.notes, now, now),
        )
        _replace_graph(conn, plan_id, owner_id, content)
        result = _read_plan(conn, plan_id, owner_id)
    if result is None:
        raise RuntimeError("created training plan vanished")
    return result


def get_plan(database_path: str | Path, *, owner_id: str, plan_id: str) -> TrainingPlan | None:
    with connect(database_path) as conn:
        return _read_plan(conn, plan_id, owner_id)


def list_plans(
    database_path: str | Path, *, owner_id: str, limit: int, offset: int
) -> TrainingPlanPage:
    if limit < 1 or offset < 0 or offset > MAX_SAFE_INTEGER:
        raise ValueError("invalid training plan page")
    with connect(database_path) as conn:
        total = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM training_plans WHERE user_id = ?", (owner_id,)
            ).fetchone()["total"]
        )
        rows = conn.execute(
            "SELECT id, name, notes, revision FROM training_plans WHERE user_id = ? "
            "ORDER BY casefold(name), id LIMIT ? OFFSET ?",
            (owner_id, limit, offset),
        ).fetchall()
    return TrainingPlanPage(
        items=[
            TrainingPlanSummary(
                id=str(row["id"]),
                name=str(row["name"]),
                notes=row["notes"],
                revision=int(row["revision"]),
            )
            for row in rows
        ],
        total=total,
    )


def update_plan(
    database_path: str | Path,
    *,
    owner_id: str,
    plan_id: str,
    expected_revision: int,
    content: TrainingPlanContent,
) -> TrainingPlan:
    now = now_timestamp()
    with connect(database_path) as conn, write_transaction(conn):
        row = conn.execute(
            "SELECT revision FROM training_plans WHERE id = ? AND user_id = ?",
            (plan_id, owner_id),
        ).fetchone()
        if row is None:
            raise TrainingPlanNotFoundError
        revision = int(row["revision"])
        if revision != expected_revision:
            raise TrainingPlanRevisionConflictError(revision)
        if revision >= MAX_SAFE_INTEGER:
            raise TrainingPlanRevisionConflictError(revision)
        _replace_graph(conn, plan_id, owner_id, content)
        conn.execute(
            "UPDATE training_plans SET name = ?, notes = ?, revision = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (content.name, content.notes, revision + 1, now, plan_id, owner_id),
        )
        result = _read_plan(conn, plan_id, owner_id)
    if result is None:
        raise RuntimeError("updated training plan vanished")
    return result


def delete_plan(
    database_path: str | Path, *, owner_id: str, plan_id: str, expected_revision: int
) -> None:
    with connect(database_path) as conn, write_transaction(conn):
        row = conn.execute(
            "SELECT revision FROM training_plans WHERE id = ? AND user_id = ?",
            (plan_id, owner_id),
        ).fetchone()
        if row is None:
            raise TrainingPlanNotFoundError
        revision = int(row["revision"])
        if revision != expected_revision:
            raise TrainingPlanRevisionConflictError(revision)
        conn.execute("DELETE FROM training_plans WHERE id = ? AND user_id = ?", (plan_id, owner_id))
