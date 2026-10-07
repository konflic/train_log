"""Exercise catalog storage: visible listing, lookup, and custom CRUD.

Visibility (PLAN.md §4): global defaults (`is_default=1`, no owner) are
readable by every authenticated user but never writable through the API;
custom entries are private to their owner, so a foreign custom is
indistinguishable from an unknown id. Name uniqueness within the default scope
and within each owner's custom scope is enforced by the partial unique indexes
(authoritative, race-free); entries referenced by workout history cannot be
deleted (FK `ON DELETE RESTRICT`).

Listing search and order are Unicode-correct through the connection-registered
`casefold` SQL function (SQLite's own `LIKE`/`NOCASE` fold ASCII only):
search is a case-insensitive substring match with escaped wildcards, and the
order is `casefold(name)` with an `id` tie-break, which is a total order and
therefore stable across pages. All values are bound parameters; the only
string-built SQL parts are code-controlled column/where fragments.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db import connect, write_transaction
from app.numbers import MAX_SAFE_INTEGER
from app.schemas.exercises import CreateExerciseRequest

CATALOG_COLUMNS = (
    "id",
    "name",
    "muscle_group",
    "equipment",
    "load_type",
    "bodyweight_percent",
    "side_count",
    "is_default",
    "created_by",
)

# Content columns writable through PATCH; id/is_default/created_by are
# server-controlled and rejected here as well as by the schemas.
WRITABLE_COLUMNS = frozenset(
    {"name", "muscle_group", "equipment", "load_type", "bodyweight_percent", "side_count"}
)

_LIKE_ESCAPE = "\\"
_VISIBILITY_WHERE = "(is_default = 1 OR created_by = :viewer_id)"
_ORDER_BY = "ORDER BY casefold(name), id"


class DuplicateNameError(Exception):
    """The owner's custom scope already contains this exact name."""


class EntryInUseError(Exception):
    """The entry is referenced by workout history and cannot be deleted."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One `exercise_catalog` row. Never serialized directly; APIs use schemas."""

    id: str
    name: str
    muscle_group: str
    equipment: str
    load_type: str
    bodyweight_percent: int | None
    side_count: int
    is_default: bool
    created_by: str | None


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One listing page plus the total number of matching visible entries."""

    items: list[CatalogEntry]
    total: int


def row_to_entry(row: sqlite3.Row) -> CatalogEntry:
    return CatalogEntry(
        id=str(row["id"]),
        name=str(row["name"]),
        muscle_group=str(row["muscle_group"]),
        equipment=str(row["equipment"]),
        load_type=str(row["load_type"]),
        bodyweight_percent=row["bodyweight_percent"],
        side_count=int(row["side_count"]),
        is_default=bool(row["is_default"]),
        created_by=row["created_by"],
    )


def like_pattern(search: str) -> str:
    """Build a substring LIKE pattern; user wildcards stay literal text."""
    escaped = search
    for character in (_LIKE_ESCAPE, "%", "_"):
        escaped = escaped.replace(character, _LIKE_ESCAPE + character)
    return f"%{escaped}%"


def _filter_clause(
    *, search: str | None, muscle_group: str | None, equipment: str | None
) -> tuple[str, dict[str, Any]]:
    """Optional list-filter SQL fragment plus its bound parameters."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if search is not None and search.strip():
        clauses.append(f"casefold(name) LIKE casefold(:search) ESCAPE '{_LIKE_ESCAPE}'")
        params["search"] = like_pattern(search.strip())
    if muscle_group is not None:
        clauses.append("muscle_group = :muscle_group")
        params["muscle_group"] = muscle_group
    if equipment is not None:
        clauses.append("equipment = :equipment")
        params["equipment"] = equipment
    fragment = "".join(f" AND {clause}" for clause in clauses)
    return fragment, params


def list_entries(
    database_path: str | Path,
    *,
    viewer_id: str,
    limit: int,
    offset: int,
    search: str | None = None,
    muscle_group: str | None = None,
    equipment: str | None = None,
) -> CatalogPage:
    """One stable-ordered page of the entries visible to the viewer."""
    if limit < 1:
        raise ValueError(f"limit must be positive; got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be nonnegative; got {offset}")
    if offset > MAX_SAFE_INTEGER:
        raise ValueError(f"offset must not exceed {MAX_SAFE_INTEGER}; got {offset}")
    where, params = _filter_clause(search=search, muscle_group=muscle_group, equipment=equipment)
    params["viewer_id"] = viewer_id
    columns = ", ".join(CATALOG_COLUMNS)
    with connect(database_path) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM exercise_catalog WHERE {_VISIBILITY_WHERE}{where}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"SELECT {columns} FROM exercise_catalog "
            f"WHERE {_VISIBILITY_WHERE}{where} {_ORDER_BY} LIMIT :limit OFFSET :offset",
            dict(params, limit=limit, offset=offset),
        ).fetchall()
    return CatalogPage(items=[row_to_entry(row) for row in rows], total=int(total_row["total"]))


def get_visible_entry(
    database_path: str | Path, entry_id: str, *, viewer_id: str
) -> CatalogEntry | None:
    """Fetch one entry when visible to the viewer; foreign customs are `None`."""
    columns = ", ".join(CATALOG_COLUMNS)
    with connect(database_path) as conn:
        row = conn.execute(
            f"SELECT {columns} FROM exercise_catalog WHERE id = :id AND {_VISIBILITY_WHERE}",
            {"id": entry_id, "viewer_id": viewer_id},
        ).fetchone()
    return row_to_entry(row) if row is not None else None


def create_custom_entry(
    database_path: str | Path,
    *,
    owner_id: str,
    name: str,
    muscle_group: str,
    equipment: str,
    load_type: str,
    bodyweight_percent: int | None,
    side_count: int,
) -> CatalogEntry:
    """Insert an owner-private custom entry with a server-generated UUID id.

    Defaults keep stable slug ids and customs use UUIDs, so the id scopes
    cannot collide. The owner-name unique index is the authoritative
    duplicate check and surfaces as `DuplicateNameError`.
    """
    entry_id = str(uuid.uuid4())
    try:
        with connect(database_path) as conn, write_transaction(conn):
            conn.execute(
                "INSERT INTO exercise_catalog (id, name, muscle_group, equipment, "
                "load_type, bodyweight_percent, side_count, is_default, created_by) "
                "VALUES (:id, :name, :muscle_group, :equipment, :load_type, "
                ":bodyweight_percent, :side_count, 0, :created_by)",
                {
                    "id": entry_id,
                    "name": name,
                    "muscle_group": muscle_group,
                    "equipment": equipment,
                    "load_type": load_type,
                    "bodyweight_percent": bodyweight_percent,
                    "side_count": side_count,
                    "created_by": owner_id,
                },
            )
    except sqlite3.IntegrityError as exc:
        if "exercise_catalog.name" in str(exc):
            raise DuplicateNameError(name) from exc
        raise
    return CatalogEntry(
        id=entry_id,
        name=name,
        muscle_group=muscle_group,
        equipment=equipment,
        load_type=load_type,
        bodyweight_percent=bodyweight_percent,
        side_count=side_count,
        is_default=False,
        created_by=owner_id,
    )


def update_custom_entry(
    database_path: str | Path,
    entry_id: str,
    *,
    owner_id: str,
    updates: Mapping[str, Any],
) -> CatalogEntry | None:
    """Apply whitelisted content updates to the owner's custom entry.

    Returns `None` when the entry is not the caller's custom (unknown id, a
    default, or another user's entry); defaults are never matched by the
    `WHERE` clause, so they are immutable at the storage layer too. Editing an
    entry applies to future workout instances only: exercise rows snapshot
    their load settings and are untouched here (PLAN.md §4).
    """
    if not updates:
        raise ValueError("update_custom_entry requires at least one field")
    unknown = set(updates) - WRITABLE_COLUMNS
    if unknown:
        raise ValueError(f"unknown catalog fields: {sorted(unknown)}")

    columns = ", ".join(CATALOG_COLUMNS)
    try:
        with connect(database_path) as conn, write_transaction(conn):
            row = conn.execute(
                f"SELECT {columns} FROM exercise_catalog "
                "WHERE id = :id AND is_default = 0 AND created_by = :owner_id",
                {"id": entry_id, "owner_id": owner_id},
            ).fetchone()
            if row is None:
                return None

            current = row_to_entry(row)
            merged: dict[str, Any] = {
                "name": current.name,
                "muscle_group": current.muscle_group,
                "equipment": current.equipment,
                "load_type": current.load_type,
                "bodyweight_percent": current.bodyweight_percent,
                "side_count": current.side_count,
            }
            merged.update(updates)
            validated = CreateExerciseRequest.model_validate(merged)
            normalized_updates = {name: getattr(validated, name) for name in updates}
            assignments = ", ".join(f"{name} = :{name}" for name in sorted(normalized_updates))
            params: dict[str, Any] = dict(normalized_updates)
            params["id"] = entry_id
            params["owner_id"] = owner_id
            conn.execute(
                f"UPDATE exercise_catalog SET {assignments} "
                "WHERE id = :id AND is_default = 0 AND created_by = :owner_id",
                params,
            )
            row = conn.execute(
                f"SELECT {columns} FROM exercise_catalog WHERE id = :id",
                {"id": entry_id},
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        if "exercise_catalog.name" in str(exc):
            raise DuplicateNameError(entry_id) from exc
        raise
    return row_to_entry(row) if row is not None else None


def delete_custom_entry(database_path: str | Path, entry_id: str, *, owner_id: str) -> bool:
    """Delete the owner's custom entry; `False` when there was nothing to delete.

    Referenced entries raise `EntryInUseError`: the `ON DELETE RESTRICT`
    foreign key from `exercises.catalog_id` aborts the statement and the
    transaction rolls back, so history always keeps its catalog reference.
    """
    try:
        with connect(database_path) as conn, write_transaction(conn):
            cursor = conn.execute(
                "DELETE FROM exercise_catalog "
                "WHERE id = :id AND is_default = 0 AND created_by = :owner_id",
                {"id": entry_id, "owner_id": owner_id},
            )
    except sqlite3.IntegrityError as exc:
        # The only integrity failure a DELETE can hit here is the RESTRICT FK.
        raise EntryInUseError(entry_id) from exc
    return cursor.rowcount > 0
