"""Database-level contract: STRICT typing, CHECKs, foreign keys, uniqueness.

Stage 1 covers what SQLite itself must enforce. Rejecting floats/strings/
bools at the API boundary is Stage 2 (Pydantic); SQLite losslessly coerces
some of these values, which is documented here rather than relied upon.
"""

import sqlite3
from pathlib import Path

import pytest
from helpers import (
    TS,
    insert_catalog_entry,
    insert_exercise,
    insert_graph,
    insert_session,
    insert_set,
    insert_user,
    insert_workout,
)

from app.db import connect, write_transaction


def test_integer_columns_reject_non_integral_values(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_graph(txn)
        for bad_value in (1.5, "abc", "1.5"):
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_set(txn, weight_kg=bad_value)
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_set(txn, reps=bad_value)
        # Nothing partial survived the rejected inserts.
        count = conn.execute("SELECT COUNT(*) FROM sets").fetchone()
        assert count is not None
        assert int(count[0]) == 0


def test_integer_columns_accept_null(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_graph(txn)
            # Draft set: reps/weight/rpe/override all unknown (null).
            insert_set(txn, reps=None, weight_kg=None, rpe=None, done=0)
        row = conn.execute("SELECT reps, weight_kg, rpe FROM sets").fetchone()
        assert row is not None
        assert row["reps"] is None
        assert row["weight_kg"] is None
        assert row["rpe"] is None


def test_sqlite_coerces_lossless_values_documenting_stage2_duty(
    migrated_db: Path,
) -> None:
    # SQLite STRICT losslessly coerces integral floats, numeric text, and
    # Python bools into INTEGER, and numbers into TEXT. The API must
    # therefore reject those input types itself (Pydantic, Stage 2); the
    # database is the second line.
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_graph(txn)
            insert_set(txn, set_id="s-text", set_index=0, weight_kg="12")
            insert_set(txn, set_id="s-float", set_index=1, weight_kg=14.0)
            insert_set(txn, set_id="s-bool", set_index=2, reps=True, weight_kg=None)
            insert_user(txn, "u-num", email=123)  # type: ignore[arg-type]
        rows = conn.execute(
            "SELECT id, typeof(reps) AS reps_type, typeof(weight_kg) AS w_type, "
            "reps, weight_kg FROM sets ORDER BY set_index"
        ).fetchall()
        assert [(r["w_type"], r["weight_kg"]) for r in rows[:2]] == [
            ("integer", 12),
            ("integer", 14),
        ]
        assert (rows[2]["reps_type"], rows[2]["reps"]) == ("integer", 1)
        user = conn.execute(
            "SELECT email, typeof(email) AS t FROM users WHERE id = 'u-num'"
        ).fetchone()
        assert user is not None
        assert (user["t"], user["email"]) == ("text", "123")


def test_text_columns_reject_blobs(migrated_db: Path) -> None:
    with (
        connect(migrated_db) as conn,
        pytest.raises(sqlite3.IntegrityError),
        write_transaction(conn) as txn,
    ):
        insert_user(txn, email=b"blob@example.com")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-01-01 00:00:00Z",
        "2026-01-01T00:00:00",
        "2026-01-01T00:00:00+00:00",
        "2026-99-99T99:99:99Z",
        "2026-02-30T00:00:00Z",
        "2025-02-29T00:00:00Z",
        "2026-01-01T24:00:00Z",
        "0000-01-01T00:00:00Z",
    ],
)
def test_timestamps_must_be_canonical_utc(migrated_db: Path, created_at: str) -> None:
    with (
        connect(migrated_db) as conn,
        pytest.raises(sqlite3.IntegrityError),
        write_transaction(conn) as txn,
    ):
        insert_user(txn, created_at=created_at)


def test_ended_at_must_not_precede_started_at(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_workout(
                txn,
                started_at="2026-01-02T00:00:00Z",
                ended_at="2026-01-01T00:00:00Z",
            )
        with write_transaction(conn) as txn:
            insert_workout(txn, started_at=TS, ended_at="2026-01-01T01:00:00Z")


def test_session_requires_future_expiry(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_session(txn, expires_at=TS)


def test_user_column_rules(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        for bad_offset in (-721, 841):
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_user(txn, f"u-off-{bad_offset}", utc_offset_minutes=bad_offset)
        for bad_bodyweight in (0, -5):
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_user(txn, f"u-bw-{bad_bodyweight}", bodyweight_default_kg=bad_bodyweight)
        with write_transaction(conn) as txn:
            insert_user(txn, "u-ok", utc_offset_minutes=-180, bodyweight_default_kg=81)
        row = conn.execute(
            "SELECT utc_offset_minutes, bodyweight_default_kg FROM users WHERE id = 'u-ok'"
        ).fetchone()
        assert row is not None
        assert int(row["utc_offset_minutes"]) == -180
        assert int(row["bodyweight_default_kg"]) == 81


def test_column_defaults(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            txn.execute(
                "INSERT INTO users (id, email, password_hash, created_at, updated_at) "
                "VALUES ('u-min', 'u-min@example.com', 'hash', :ts, :ts)",
                {"ts": TS},
            )
            txn.execute(
                "INSERT INTO workouts (id, user_id, started_at, create_request_hash, "
                "created_at, updated_at) "
                "VALUES ('w-min', 'u-min', :ts, 'hash', :ts, :ts)",
                {"ts": TS},
            )
            txn.execute(
                "INSERT INTO exercises (id, workout_id, catalog_id, order_index, "
                "load_type, bodyweight_percent, side_count) "
                "VALUES ('e-min', 'w-min', 'pull-up', 0, 'bodyweight', 100, 1)"
            )
            txn.execute(
                "INSERT INTO sets (id, exercise_id, set_index, side) "
                "VALUES ('s-min', 'e-min', 0, 'bilateral')"
            )
        user = conn.execute("SELECT utc_offset_minutes FROM users").fetchone()
        workout = conn.execute("SELECT revision, ended_at FROM workouts").fetchone()
        set_row = conn.execute("SELECT done FROM sets").fetchone()
        assert user is not None and int(user["utc_offset_minutes"]) == 0
        assert workout is not None
        assert int(workout["revision"]) == 0
        assert workout["ended_at"] is None
        assert set_row is not None and int(set_row["done"]) == 0


def test_workout_receipt_and_bodyweight_rules(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_workout(txn, "w-rev", revision=-1)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_workout(txn, "w-bw", bodyweight_kg=0)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_workout(txn, "w-receipt", last_save_id="save-1")
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_workout(txn, "w-receipt2", last_save_hash="hash-1")
        with write_transaction(conn) as txn:
            insert_workout(txn, "w-ok", last_save_id="save-1", last_save_hash="hash-1")


def test_catalog_rules(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn)
        # Pure-bodyweight load requires a percentage.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(
                txn,
                "c-bw",
                load_type="bodyweight",
                bodyweight_percent=None,
                side_count=1,
            )
        # side_count is 1 or 2, and only split_weight may use 2.
        for bad in (0, 3):
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_catalog_entry(txn, f"c-sc-{bad}", side_count=bad)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-single2", load_type="single_weight", side_count=2)
        # Percentage range.
        for bad in (0, 101):
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_catalog_entry(
                    txn,
                    f"c-pct-{bad}",
                    load_type="bodyweight",
                    bodyweight_percent=bad,
                    side_count=1,
                )
        # Enums.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-mg", muscle_group="neck")
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-lt", load_type="assisted")
        # Default entries have no owner; customs require one.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-def-owned", is_default=1, created_by="user-1")
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-custom-noowner", is_default=0, created_by=None)


def test_catalog_name_uniqueness_is_scoped(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn, "user-1")
            insert_user(txn, "user-2")
            # Same custom name for two different owners: allowed.
            insert_catalog_entry(txn, "c-u1", name="My Row", created_by="user-1")
            insert_catalog_entry(txn, "c-u2", name="My Row", created_by="user-2")
            # A custom may reuse a default's name: allowed.
            insert_catalog_entry(txn, "c-pull", name="Pull-up", created_by="user-1")
        # Duplicate name within one owner's custom scope: rejected.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-u1-dup", name="My Row", created_by="user-1")
        # Duplicate name within the default scope: rejected.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-def-dup", name="Pull-up", is_default=1, created_by=None)


def test_exercise_snapshot_rules(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_user(txn)
            insert_workout(txn)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_exercise(txn, order_index=-1)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_exercise(txn, load_type="bodyweight", bodyweight_percent=None)
        # Unknown catalog id: foreign key.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_exercise(txn, catalog_id="does-not-exist")
        # Unique (workout_id, order_index).
        with write_transaction(conn) as txn:
            insert_exercise(txn, "e-0", order_index=0)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_exercise(txn, "e-0-dup", order_index=0)


def test_set_rules(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_graph(txn)
        cases = {
            "rpe-0": {"rpe": 0},
            "rpe-11": {"rpe": 11},
            "pct-0": {"bw_percent_override": 0},
            "pct-101": {"bw_percent_override": 101},
            "reps-neg": {"reps": -1},
            "weight-neg": {"weight_kg": -1},
            "index-neg": {"set_index": -1},
            "side-both": {"side": "both"},
            "done-2": {"done": 2},
            "done-no-reps": {"reps": None, "done": 1},
            "done-zero-reps": {"reps": 0, "done": 1},
        }
        for set_id, bad in cases.items():
            with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
                insert_set(txn, set_id, **bad)  # type: ignore[arg-type]
        # Unique (exercise_id, set_index).
        with write_transaction(conn) as txn:
            insert_set(txn, "s-0", set_index=0)
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            insert_set(txn, "s-0-dup", set_index=0)
        # A draft set without reps is fine.
        with write_transaction(conn) as txn:
            insert_set(txn, "s-draft", set_index=1, reps=None, weight_kg=None, done=0)


def test_foreign_keys_restrict_and_cascade(migrated_db: Path) -> None:
    with connect(migrated_db) as conn:
        with write_transaction(conn) as txn:
            insert_graph(txn)
            insert_session(txn)
            insert_set(txn)

        # RESTRICT: a catalog entry referenced by history cannot be deleted.
        with pytest.raises(sqlite3.IntegrityError), write_transaction(conn) as txn:
            txn.execute("DELETE FROM exercise_catalog WHERE id = 'dumbbell-curl'")

        # Unreferenced entries delete fine.
        with write_transaction(conn) as txn:
            insert_catalog_entry(txn, "c-unused", name="Unused")
            txn.execute("DELETE FROM exercise_catalog WHERE id = 'c-unused'")

        # CASCADE: deleting the owner removes sessions and the whole graph.
        with write_transaction(conn) as txn:
            txn.execute("DELETE FROM users WHERE id = 'user-1'")
        for table in ("sessions", "workouts", "exercises", "sets"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert count is not None
            assert int(count[0]) == 0, table
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
