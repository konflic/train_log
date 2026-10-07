"""Stage 6a full-state bulk-save schema tests.

Direct model coverage of `SaveWorkoutRequest`: required-field completeness
(full state, never a patch), explicit nulls, UUID/timestamp normalization,
exact text preservation, graph/text limits, strict integer and literal
rejection, and payload-local duplicate detection without leaking rejected
values. Snapshot-dependent rules (side matrix, override permission,
completion) resolve against stored/catalog rows in the service and are not
covered here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.numbers import MAX_SAFE_INTEGER
from app.schemas.workouts import (
    MAX_CATALOG_ID_LENGTH,
    MAX_EXERCISE_NOTES_LENGTH,
    MAX_EXERCISES_PER_WORKOUT,
    MAX_SETS_PER_EXERCISE,
    MAX_SETS_PER_WORKOUT,
    MAX_WORKOUT_NAME_LENGTH,
    MAX_WORKOUT_NOTES_LENGTH,
    SaveWorkoutRequest,
)

TOP_LEVEL_FIELDS = (
    "revision",
    "save_id",
    "name",
    "notes",
    "bodyweight_kg",
    "ended_at",
    "exercises",
)
EXERCISE_FIELDS = ("id", "catalog_id", "notes", "sets")
SET_FIELDS = ("id", "reps", "weight_kg", "bw_percent_override", "rpe", "side", "done")


def make_set(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "reps": 8,
        "weight_kg": 12,
        "bw_percent_override": None,
        "rpe": None,
        "side": "bilateral",
        "done": True,
    }
    payload.update(overrides)
    return payload


def make_exercise(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "catalog_id": "dumbbell-curl",
        "notes": None,
        "sets": [make_set()],
    }
    payload.update(overrides)
    return payload


def make_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "revision": 0,
        "save_id": str(uuid.uuid4()),
        "name": None,
        "notes": None,
        "bodyweight_kg": 80,
        "ended_at": None,
        "exercises": [make_exercise()],
    }
    payload.update(overrides)
    return payload


def error_text(exc: ValidationError) -> str:
    return str(exc)


# --- valid payloads -----------------------------------------------------------


def test_minimal_valid_payload_with_empty_graph() -> None:
    request = SaveWorkoutRequest.model_validate(make_payload(exercises=[]))
    assert request.exercises == []
    assert request.name is None
    assert request.ended_at is None


def test_full_state_graph_is_preserved() -> None:
    submitted = make_set(
        reps=5, weight_kg=100, bw_percent_override=65, rpe=9, side="left", done=False
    )
    request = SaveWorkoutRequest.model_validate(
        make_payload(
            revision=7,
            name="Push day",
            notes="Felt strong",
            bodyweight_kg=82,
            ended_at="2026-01-01T10:00:00Z",
            exercises=[make_exercise(notes="slow tempo", sets=[submitted])],
        )
    )
    assert request.revision == 7
    assert request.bodyweight_kg == 82
    assert request.ended_at == "2026-01-01T10:00:00Z"
    exercise = request.exercises[0]
    assert exercise.notes == "slow tempo"
    stored = exercise.sets[0]
    assert (stored.reps, stored.weight_kg, stored.bw_percent_override) == (5, 100, 65)
    assert (stored.rpe, stored.side, stored.done) == (9, "left", False)


def test_explicit_nulls_are_accepted_everywhere() -> None:
    request = SaveWorkoutRequest.model_validate(
        make_payload(
            name=None,
            notes=None,
            bodyweight_kg=None,
            ended_at=None,
            exercises=[
                make_exercise(
                    notes=None,
                    sets=[
                        make_set(
                            reps=None,
                            weight_kg=None,
                            bw_percent_override=None,
                            rpe=None,
                            done=False,
                        )
                    ],
                )
            ],
        )
    )
    submitted = request.exercises[0].sets[0]
    assert submitted.reps is None
    assert submitted.weight_kg is None
    assert submitted.rpe is None


# --- required fields: omission is invalid, not "keep" --------------------------


def test_every_top_level_field_is_required() -> None:
    for field in TOP_LEVEL_FIELDS:
        payload = make_payload()
        del payload[field]
        with pytest.raises(ValidationError):
            SaveWorkoutRequest.model_validate(payload)


def test_every_exercise_field_is_required() -> None:
    for field in EXERCISE_FIELDS:
        exercise = make_exercise()
        del exercise[field]
        with pytest.raises(ValidationError):
            SaveWorkoutRequest.model_validate(make_payload(exercises=[exercise]))


def test_every_set_field_is_required() -> None:
    for field in SET_FIELDS:
        submitted = make_set()
        del submitted[field]
        with pytest.raises(ValidationError):
            SaveWorkoutRequest.model_validate(
                make_payload(exercises=[make_exercise(sets=[submitted])])
            )


# --- normalization ------------------------------------------------------------


def test_uuid_ids_are_normalized_before_validation_completes() -> None:
    raw = uuid.uuid4()
    request = SaveWorkoutRequest.model_validate(
        make_payload(
            save_id=str(raw).upper(),
            exercises=[
                make_exercise(
                    id=f"urn:uuid:{raw}",
                    sets=[make_set(id="{" + str(raw) + "}")],
                )
            ],
        )
    )
    canonical = str(raw)
    assert request.save_id == canonical
    assert request.exercises[0].id == canonical
    assert request.exercises[0].sets[0].id == canonical


def test_ended_at_is_normalized_to_canonical_utc() -> None:
    request = SaveWorkoutRequest.model_validate(make_payload(ended_at="2026-01-01T12:30:00+03:00"))
    assert request.ended_at == "2026-01-01T09:30:00Z"


@pytest.mark.parametrize("value", ["2026-01-01T09:30:00", "yesterday", "2026-01-01", 1234])
def test_ended_at_rejects_naive_or_malformed_values(value: object) -> None:
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(ended_at=value))


def test_invalid_uuids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(save_id="not-a-uuid"))
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(exercises=[make_exercise(id="exercise-1")]))
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(exercises=[make_exercise(sets=[make_set(id="set-1")])])
        )


# --- rejected unknown / server-controlled fields -------------------------------


@pytest.mark.parametrize("field", ["started_at", "id", "user_id", "last_save_id", "created_at"])
def test_top_level_unknown_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(**{field: "x"}))


@pytest.mark.parametrize(
    "field",
    ["order_index", "load_type", "bodyweight_percent", "side_count", "workout_id", "user_id"],
)
def test_exercise_unknown_fields_are_rejected(field: str) -> None:
    exercise = make_exercise()
    exercise[field] = 1
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(exercises=[exercise]))


@pytest.mark.parametrize("field", ["set_index", "exercise_id", "done_at"])
def test_set_unknown_fields_are_rejected(field: str) -> None:
    submitted = make_set()
    submitted[field] = 1
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(exercises=[make_exercise(sets=[submitted])]))


# --- text bounds and exact preservation ----------------------------------------


def test_text_length_bounds() -> None:
    SaveWorkoutRequest.model_validate(make_payload(name="n" * MAX_WORKOUT_NAME_LENGTH))
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(name="n" * (MAX_WORKOUT_NAME_LENGTH + 1)))
    SaveWorkoutRequest.model_validate(make_payload(notes="n" * MAX_WORKOUT_NOTES_LENGTH))
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(notes="n" * (MAX_WORKOUT_NOTES_LENGTH + 1)))
    ok_notes = "n" * MAX_EXERCISE_NOTES_LENGTH
    SaveWorkoutRequest.model_validate(make_payload(exercises=[make_exercise(notes=ok_notes)]))
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(exercises=[make_exercise(notes=ok_notes + "n")])
        )


def test_catalog_id_bounds() -> None:
    SaveWorkoutRequest.model_validate(
        make_payload(exercises=[make_exercise(catalog_id="c" * MAX_CATALOG_ID_LENGTH)])
    )
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(exercises=[make_exercise(catalog_id="c" * (MAX_CATALOG_ID_LENGTH + 1))])
        )
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(exercises=[make_exercise(catalog_id="")]))


def test_text_is_preserved_exactly_without_trim_or_null_conversion() -> None:
    request = SaveWorkoutRequest.model_validate(
        make_payload(
            name="  Morning Session  ",
            notes="",
            exercises=[make_exercise(catalog_id=" Custom Entry #1 ", notes="")],
        )
    )
    assert request.name == "  Morning Session  "
    assert request.notes == ""
    assert request.exercises[0].catalog_id == " Custom Entry #1 "
    assert request.exercises[0].notes == ""


# --- graph limits ----------------------------------------------------------------


def test_exercise_and_set_count_limits() -> None:
    SaveWorkoutRequest.model_validate(
        make_payload(exercises=[make_exercise(sets=[]) for _ in range(MAX_EXERCISES_PER_WORKOUT)])
    )
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(
                exercises=[make_exercise(sets=[]) for _ in range(MAX_EXERCISES_PER_WORKOUT + 1)]
            )
        )
    SaveWorkoutRequest.model_validate(
        make_payload(
            exercises=[make_exercise(sets=[make_set() for _ in range(MAX_SETS_PER_EXERCISE)])]
        )
    )
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(
                exercises=[
                    make_exercise(sets=[make_set() for _ in range(MAX_SETS_PER_EXERCISE + 1)])
                ]
            )
        )


def test_total_set_limit_across_the_graph() -> None:
    per_exercise = MAX_SETS_PER_WORKOUT // MAX_EXERCISES_PER_WORKOUT  # 10
    exercises = [
        make_exercise(sets=[make_set() for _ in range(per_exercise)])
        for _ in range(MAX_EXERCISES_PER_WORKOUT)
    ]
    SaveWorkoutRequest.model_validate(make_payload(exercises=exercises))
    # 12 * 20 + 11 = 251 total sets; every per-exercise limit still holds.
    over = [
        make_exercise(sets=[make_set() for _ in range(MAX_SETS_PER_EXERCISE)])
        for _ in range(MAX_SETS_PER_WORKOUT // MAX_SETS_PER_EXERCISE)
    ]
    over.append(make_exercise(sets=[make_set() for _ in range(11)]))
    with pytest.raises(ValidationError, match=str(MAX_SETS_PER_WORKOUT)):
        SaveWorkoutRequest.model_validate(make_payload(exercises=over))


# --- strict integers, literals -----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", 1.5),
        ("revision", "1"),
        ("revision", True),
        ("revision", -1),
        ("revision", MAX_SAFE_INTEGER + 1),
        ("bodyweight_kg", 80.5),
        ("bodyweight_kg", "80"),
        ("bodyweight_kg", 0),
        ("bodyweight_kg", -80),
    ],
)
def test_top_level_integer_strictness(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(make_payload(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reps", -1),
        ("reps", 8.0),
        ("reps", "8"),
        ("reps", True),
        ("weight_kg", -1),
        ("weight_kg", 12.5),
        ("weight_kg", "12"),
        ("rpe", 0),
        ("rpe", 11),
        ("rpe", 8.0),
        ("bw_percent_override", 0),
        ("bw_percent_override", 101),
        ("done", 1),
        ("done", 0),
        ("done", "true"),
        ("side", "both"),
        ("side", ""),
        ("side", None),
    ],
)
def test_set_value_strictness(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SaveWorkoutRequest.model_validate(
            make_payload(exercises=[make_exercise(sets=[make_set(**{field: value})])])
        )


def test_draft_bounds_stay_within_stage_two_ranges() -> None:
    # Draft values at the documented bounds are accepted (completion rules are
    # service-side against the resolved snapshot).
    request = SaveWorkoutRequest.model_validate(
        make_payload(
            revision=MAX_SAFE_INTEGER,
            exercises=[
                make_exercise(
                    sets=[make_set(reps=0, weight_kg=0, rpe=1, done=False)],
                )
            ],
        )
    )
    assert request.revision == MAX_SAFE_INTEGER


# --- payload-local duplicates ------------------------------------------------------


def test_duplicate_exercise_ids_are_rejected_after_normalization() -> None:
    raw = uuid.uuid4()
    exercises = [
        make_exercise(id=str(raw)),
        make_exercise(id=str(raw).upper()),
    ]
    with pytest.raises(ValidationError, match=r"duplicate exercise id at exercises\.1"):
        SaveWorkoutRequest.model_validate(make_payload(exercises=exercises))


def test_duplicate_set_ids_are_rejected_across_the_whole_graph() -> None:
    raw = uuid.uuid4()
    exercises = [
        make_exercise(sets=[make_set(id=str(raw))]),
        make_exercise(sets=[make_set(), make_set(id="urn:uuid:" + str(raw))]),
    ]
    with pytest.raises(ValidationError, match=r"duplicate set id at exercises\.1\.sets\.1"):
        SaveWorkoutRequest.model_validate(make_payload(exercises=exercises))


def test_duplicate_set_ids_within_one_exercise_are_rejected() -> None:
    raw = uuid.uuid4()
    exercise = make_exercise(sets=[make_set(id=str(raw)), make_set(id=str(raw))])
    with pytest.raises(ValidationError, match=r"duplicate set id at exercises\.0\.sets\.1"):
        SaveWorkoutRequest.model_validate(make_payload(exercises=[exercise]))


def test_duplicate_errors_report_positions_not_values() -> None:
    raw = uuid.uuid4()
    exercises = [make_exercise(id=str(raw)), make_exercise(id=str(raw))]
    with pytest.raises(ValidationError) as excinfo:
        SaveWorkoutRequest.model_validate(make_payload(exercises=exercises))
    message = error_text(excinfo.value)
    assert str(raw) not in message
    assert str(raw).upper() not in message
