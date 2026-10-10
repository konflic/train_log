"""Stage 4 catalog service tests (Gate G4).

Direct-SQLite coverage of visibility scoping, Unicode case-insensitive search
with escaped LIKE wildcards, filters, stable casefold ordering with id
tie-break, pagination, in-scope uniqueness, owner-scoped updates (including
snapshot preservation), and the referenced-entry delete guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from helpers import insert_exercise, insert_user, insert_workout

from app.db import connect, write_transaction
from app.services import catalog
from app.services.catalog import (
    CatalogEntry,
    DuplicateNameError,
    EntryInUseError,
    like_pattern,
)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

SEEDED_DEFAULT_COUNT = 42


@pytest.fixture()
def two_users(migrated_db: Path) -> Path:
    """The migrated database with `user-1` and `user-2` present."""
    with connect(migrated_db) as conn, write_transaction(conn):
        insert_user(conn, "user-1")
        insert_user(conn, "user-2")
    return migrated_db


def create_entry(
    database_path: Path,
    *,
    owner_id: str = "user-1",
    name: str = "Custom Curl",
    muscle_group: str = "arms",
    load_type: str = "split_weight",
    bodyweight_percent: int | None = None,
    side_count: int = 2,
) -> CatalogEntry:
    return catalog.create_custom_entry(
        database_path,
        owner_id=owner_id,
        name=name,
        muscle_group=muscle_group,
        load_type=load_type,
        bodyweight_percent=bodyweight_percent,
        side_count=side_count,
    )


def visible_names(page: catalog.CatalogPage) -> list[str]:
    return [entry.name for entry in page.items]


# --- create ------------------------------------------------------------------


def test_create_custom_entry_stores_owner_scoped_row(two_users: Path) -> None:
    entry = create_entry(two_users, name="  Custom Curl  ".strip())
    assert UUID_RE.fullmatch(entry.id)
    assert entry.is_default is False
    assert entry.created_by == "user-1"
    with connect(two_users) as conn:
        row = conn.execute(
            "SELECT id, name, is_default, created_by, side_count, bodyweight_percent "
            "FROM exercise_catalog WHERE id = :id",
            {"id": entry.id},
        ).fetchone()
    assert row["name"] == "Custom Curl"
    assert row["is_default"] == 0
    assert row["created_by"] == "user-1"
    assert row["side_count"] == 2
    assert row["bodyweight_percent"] is None


def test_create_rejects_duplicate_name_within_owner_scope(two_users: Path) -> None:
    create_entry(two_users, name="My Row")
    with pytest.raises(DuplicateNameError):
        create_entry(two_users, name="My Row")
    # Exact-match uniqueness: a case variant is a different name.
    other_case = create_entry(two_users, name="my row")
    assert other_case.name == "my row"


def test_create_allows_same_name_across_scopes(two_users: Path) -> None:
    # Another owner's custom scope is independent.
    create_entry(two_users, owner_id="user-1", name="My Row")
    create_entry(two_users, owner_id="user-2", name="My Row")
    # A custom may reuse a default name (PLAN.md §4).
    pull_up = create_entry(
        two_users,
        name="Pull-up",
        load_type="bodyweight",
        muscle_group="back",
        bodyweight_percent=100,
        side_count=1,
    )
    assert pull_up.name == "Pull-up"


def test_create_preserves_utf8_names(two_users: Path) -> None:
    entry = create_entry(two_users, name="💪 Бицепс-молот")
    fetched = catalog.get_visible_entry(two_users, entry.id, viewer_id="user-1")
    assert fetched is not None
    assert fetched.name == "💪 Бицепс-молот"


# --- visibility ----------------------------------------------------------------


def test_get_visible_entry_scoping(two_users: Path) -> None:
    mine = create_entry(two_users, owner_id="user-1")
    theirs = create_entry(two_users, owner_id="user-2", name="Their Row")
    assert catalog.get_visible_entry(two_users, mine.id, viewer_id="user-1") is not None
    # Another user's custom is indistinguishable from an unknown id.
    assert catalog.get_visible_entry(two_users, theirs.id, viewer_id="user-1") is None
    assert catalog.get_visible_entry(two_users, theirs.id, viewer_id="user-2") is not None
    assert catalog.get_visible_entry(two_users, "does-not-exist", viewer_id="user-1") is None
    # Defaults are visible to everyone.
    default = catalog.get_visible_entry(two_users, "bench-press", viewer_id="user-2")
    assert default is not None
    assert default.is_default is True
    assert default.created_by is None


def test_list_entries_returns_defaults_plus_own_customs_only(two_users: Path) -> None:
    mine = create_entry(two_users, owner_id="user-1")
    theirs = create_entry(two_users, owner_id="user-2", name="Their Row")
    page = catalog.list_entries(two_users, viewer_id="user-1", limit=100, offset=0)
    ids = {entry.id for entry in page.items}
    assert page.total == SEEDED_DEFAULT_COUNT + 1
    assert mine.id in ids
    assert theirs.id not in ids
    other = catalog.list_entries(two_users, viewer_id="user-2", limit=100, offset=0)
    assert other.total == SEEDED_DEFAULT_COUNT + 1
    assert {entry.id for entry in other.items} - ids == {theirs.id}


# --- search and filters ----------------------------------------------------------


def test_search_is_unicode_case_insensitive(two_users: Path) -> None:
    create_entry(
        two_users,
        name="Жим Лёжа",
        muscle_group="chest",
        load_type="single_weight",
        side_count=1,
    )
    create_entry(
        two_users,
        name="Übung",
        muscle_group="abs",
        load_type="single_weight",
        side_count=1,
    )
    for query in ("жим", "ЖИМ", "лёжа"):
        page = catalog.list_entries(two_users, viewer_id="user-1", limit=10, offset=0, search=query)
        assert visible_names(page) == ["Жим Лёжа"], query
    page = catalog.list_entries(two_users, viewer_id="user-1", limit=10, offset=0, search="ÜBUNG")
    assert visible_names(page) == ["Übung"]
    # Blank search is ignored rather than filtering everything out.
    page = catalog.list_entries(two_users, viewer_id="user-1", limit=100, offset=0, search="   ")
    assert page.total == SEEDED_DEFAULT_COUNT + 2


def test_search_never_matches_invisible_entries(two_users: Path) -> None:
    create_entry(two_users, owner_id="user-2", name="Secret Row")
    page = catalog.list_entries(two_users, viewer_id="user-1", limit=10, offset=0, search="secret")
    assert page.total == 0
    assert page.items == []


def test_search_escapes_like_wildcards(two_users: Path) -> None:
    create_entry(two_users, name="100% Row", load_type="single_weight", side_count=1)
    create_entry(two_users, name="100x Row", load_type="single_weight", side_count=1)
    create_entry(two_users, name="A_B", load_type="single_weight", side_count=1)
    create_entry(two_users, name="AXB", load_type="single_weight", side_count=1)

    def search(query: str) -> list[str]:
        page = catalog.list_entries(two_users, viewer_id="user-1", limit=10, offset=0, search=query)
        return visible_names(page)

    assert search("100%") == ["100% Row"]
    assert search("%") == ["100% Row"]
    assert search("A_B") == ["A_B"]
    assert search("_B") == ["A_B"]
    assert sorted(search("100")) == ["100% Row", "100x Row"]


def test_like_pattern_escapes_escape_char_first() -> None:
    assert like_pattern(r"a\b%c_d") == r"%a\\b\%c\_d%"


def test_muscle_group_filter(two_users: Path) -> None:
    page = catalog.list_entries(
        two_users, viewer_id="user-1", limit=100, offset=0, muscle_group="back"
    )
    assert {entry.id for entry in page.items} == {
        "barbell-row",
        "deadlift",
        "lat-pulldown",
        "pull-up",
        "back-extension",
        "good-morning",
        "one-arm-dumbbell-row",
        "chin-up",
    }
    assert page.total == 8
    page = catalog.list_entries(
        two_users, viewer_id="user-1", limit=100, offset=0, muscle_group="abs"
    )
    assert {entry.id for entry in page.items} == {
        "crunch",
        "sit-up",
        "hanging-leg-raise",
        "lying-leg-raise",
        "russian-twist",
        "ab-wheel-rollout",
    }
    # The filter combines with search.
    page = catalog.list_entries(
        two_users,
        viewer_id="user-1",
        limit=100,
        offset=0,
        muscle_group="back",
        search="row",
    )
    assert visible_names(page) == ["Barbell Row", "One-arm Dumbbell Row"]
    assert page.total == 2


# --- ordering and pagination ------------------------------------------------------


def test_order_is_casefolded_name_with_id_tiebreak(two_users: Path) -> None:
    custom = create_entry(
        two_users,
        name="pull-up",
        muscle_group="back",
        load_type="bodyweight",
        bodyweight_percent=100,
        side_count=1,
    )
    page = catalog.list_entries(two_users, viewer_id="user-1", limit=100, offset=0)
    names_and_ids = [(entry.name, entry.id) for entry in page.items]
    assert names_and_ids == sorted(names_and_ids, key=lambda pair: (pair[0].casefold(), pair[1]))
    # The default "Pull-up" and the custom "pull-up" are adjacent, id breaks tie.
    tie = [pair for pair in names_and_ids if pair[0].casefold() == "pull-up"]
    assert tie == sorted([("Pull-up", "pull-up"), ("pull-up", custom.id)], key=lambda pair: pair[1])


def test_pagination_is_stable_and_disjoint(two_users: Path) -> None:
    full = catalog.list_entries(two_users, viewer_id="user-1", limit=100, offset=0)
    assert full.total == SEEDED_DEFAULT_COUNT
    paged_ids: list[str] = []
    for offset in range(0, SEEDED_DEFAULT_COUNT, 5):
        page = catalog.list_entries(two_users, viewer_id="user-1", limit=5, offset=offset)
        assert page.total == SEEDED_DEFAULT_COUNT
        paged_ids.extend(entry.id for entry in page.items)
    assert paged_ids == [entry.id for entry in full.items]
    beyond = catalog.list_entries(two_users, viewer_id="user-1", limit=5, offset=100)
    assert beyond.items == []
    assert beyond.total == SEEDED_DEFAULT_COUNT


def test_total_reflects_filters(two_users: Path) -> None:
    page = catalog.list_entries(
        two_users, viewer_id="user-1", limit=3, offset=0, muscle_group="legs"
    )
    assert page.total == 11
    assert len(page.items) == 3


def test_invalid_paging_is_rejected(two_users: Path) -> None:
    with pytest.raises(ValueError):
        catalog.list_entries(two_users, viewer_id="user-1", limit=0, offset=0)
    with pytest.raises(ValueError):
        catalog.list_entries(two_users, viewer_id="user-1", limit=5, offset=-1)
    with pytest.raises(ValueError):
        catalog.list_entries(
            two_users,
            viewer_id="user-1",
            limit=5,
            offset=2**53,
        )


# --- update -----------------------------------------------------------------------


def test_update_custom_entry_applies_whitelisted_fields(two_users: Path) -> None:
    entry = create_entry(two_users)
    updated = catalog.update_custom_entry(
        two_users,
        entry.id,
        owner_id="user-1",
        updates={"name": "Renamed Row", "bodyweight_percent": 30},
    )
    assert updated is not None
    assert updated.name == "Renamed Row"
    assert updated.bodyweight_percent == 30
    # Untouched fields keep their stored values.
    assert updated.load_type == "split_weight"
    assert updated.side_count == 2


def test_update_rejects_unknown_fields_and_empty_updates(two_users: Path) -> None:
    entry = create_entry(two_users)
    with pytest.raises(ValueError):
        catalog.update_custom_entry(two_users, entry.id, owner_id="user-1", updates={})
    with pytest.raises(ValueError):
        catalog.update_custom_entry(
            two_users,
            entry.id,
            owner_id="user-1",
            updates={"name": "x", "is_default": 1},
        )
    with pytest.raises(ValueError):
        catalog.update_custom_entry(
            two_users, entry.id, owner_id="user-1", updates={"created_by": "user-2"}
        )


def test_update_is_scoped_to_owner_customs(two_users: Path) -> None:
    theirs = create_entry(two_users, owner_id="user-2", name="Their Row")
    assert (
        catalog.update_custom_entry(
            two_users, theirs.id, owner_id="user-1", updates={"name": "Stolen"}
        )
        is None
    )
    # Defaults are never matched by the owner-scoped WHERE clause.
    assert (
        catalog.update_custom_entry(
            two_users, "bench-press", owner_id="user-1", updates={"name": "Stolen"}
        )
        is None
    )
    assert (
        catalog.update_custom_entry(
            two_users, "does-not-exist", owner_id="user-1", updates={"name": "x"}
        )
        is None
    )
    unchanged = catalog.get_visible_entry(two_users, theirs.id, viewer_id="user-2")
    assert unchanged is not None
    assert unchanged.name == "Their Row"


def test_update_duplicate_rename_raises(two_users: Path) -> None:
    create_entry(two_users, name="First Row")
    second = create_entry(two_users, name="Second Row")
    with pytest.raises(DuplicateNameError):
        catalog.update_custom_entry(
            two_users, second.id, owner_id="user-1", updates={"name": "First Row"}
        )


def test_update_preserves_recorded_exercise_snapshots(two_users: Path) -> None:
    """Catalog edits apply to future instances, never to recorded history."""
    entry = create_entry(two_users)
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "workout-1", user_id="user-1")
        insert_exercise(conn, "exercise-1", workout_id="workout-1", catalog_id=entry.id)
    catalog.update_custom_entry(
        two_users,
        entry.id,
        owner_id="user-1",
        updates={"load_type": "single_weight", "side_count": 1, "bodyweight_percent": 40},
    )
    with connect(two_users) as conn:
        row = conn.execute(
            "SELECT load_type, side_count, bodyweight_percent FROM exercises "
            "WHERE id = 'exercise-1'"
        ).fetchone()
    assert (row["load_type"], row["side_count"], row["bodyweight_percent"]) == (
        "split_weight",
        2,
        None,
    )


# --- delete -------------------------------------------------------------------------


def test_delete_unreferenced_custom_entry(two_users: Path) -> None:
    entry = create_entry(two_users)
    assert catalog.delete_custom_entry(two_users, entry.id, owner_id="user-1") is True
    assert catalog.get_visible_entry(two_users, entry.id, viewer_id="user-1") is None
    # Deleting again finds nothing; the freed name is reusable.
    assert catalog.delete_custom_entry(two_users, entry.id, owner_id="user-1") is False
    create_entry(two_users, name=entry.name)


def test_delete_is_scoped_to_owner_customs(two_users: Path) -> None:
    theirs = create_entry(two_users, owner_id="user-2", name="Their Row")
    assert catalog.delete_custom_entry(two_users, theirs.id, owner_id="user-1") is False
    assert catalog.get_visible_entry(two_users, theirs.id, viewer_id="user-2") is not None
    # Defaults are never matched by the owner-scoped WHERE clause.
    assert catalog.delete_custom_entry(two_users, "bench-press", owner_id="user-1") is False
    assert catalog.delete_custom_entry(two_users, "does-not-exist", owner_id="user-1") is False


def test_delete_referenced_entry_raises_and_keeps_row(two_users: Path) -> None:
    entry = create_entry(two_users)
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "workout-1", user_id="user-1")
        insert_exercise(conn, "exercise-1", workout_id="workout-1", catalog_id=entry.id)
    with pytest.raises(EntryInUseError):
        catalog.delete_custom_entry(two_users, entry.id, owner_id="user-1")
    assert catalog.get_visible_entry(two_users, entry.id, viewer_id="user-1") is not None


def test_deleting_workout_history_frees_the_entry(two_users: Path) -> None:
    entry = create_entry(two_users)
    with connect(two_users) as conn, write_transaction(conn):
        insert_workout(conn, "workout-1", user_id="user-1")
        insert_exercise(conn, "exercise-1", workout_id="workout-1", catalog_id=entry.id)
    with connect(two_users) as conn, write_transaction(conn):
        conn.execute("DELETE FROM workouts WHERE id = 'workout-1'")
    assert catalog.delete_custom_entry(two_users, entry.id, owner_id="user-1") is True
