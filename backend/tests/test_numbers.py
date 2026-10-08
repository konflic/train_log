"""Stage 2 integer arithmetic and input-validation contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.numbers import (
    MAX_SAFE_INTEGER,
    NumericRangeError,
    SetLoad,
    bodyweight_load,
    calculate_set_load,
    estimated_one_rep_max,
    external_load,
    floor_divide,
    integer_delta,
    recorded_external_load,
    require_safe_integer,
    set_volume,
)
from app.schemas.common import BodyweightKg, Index, Percentage, Rpe, SetInput, SideCount

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests/fixtures/numeric_examples.json"


def load_examples() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_calculations_match_shared_numeric_examples() -> None:
    fixture = load_examples()
    assert fixture["safe_integer_max"] == MAX_SAFE_INTEGER
    for example in fixture["examples"]:  # type: ignore[union-attr]
        input_values = example["input"]  # type: ignore[index]
        expected = example["expected"]  # type: ignore[index]
        result = calculate_set_load(**input_values)  # type: ignore[arg-type]
        assert result.effective_load_kg == expected["effective_load_kg"]  # type: ignore[index]
        assert result.volume_kg_reps == expected["volume_kg_reps"]  # type: ignore[index]
    for example in fixture["floor_division"]:  # type: ignore[union-attr]
        assert floor_divide(example["numerator"], example["denominator"]) == example["expected"]  # type: ignore[index]


@pytest.mark.parametrize("value", [1.5, "1", True, MAX_SAFE_INTEGER + 1])
def test_safe_integer_rejects_non_integers_and_out_of_range(value: object) -> None:
    with pytest.raises((NumericRangeError, TypeError)):
        require_safe_integer(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("calculation", "args"),
    [
        (bodyweight_load, (MAX_SAFE_INTEGER, 100)),
        (external_load, (MAX_SAFE_INTEGER, 2)),
        (set_volume, (2, MAX_SAFE_INTEGER)),
    ],
)
def test_calculations_reject_unsafe_intermediate_or_output(
    calculation: object,
    args: tuple[int, int],
) -> None:
    with pytest.raises(NumericRangeError):
        calculation(*args)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("weight_kg", "load_type", "side_count", "expected"),
    [
        (100, "single_weight", 1, 100),
        (0, "single_weight", 1, 0),
        (12, "split_weight", 2, 24),
        (12, "split_weight", 1, 12),
        # A pure-bodyweight set has no external weight and contributes zero...
        (None, "bodyweight", 1, 0),
        # ...while a weighted set without a recorded weight stays unknown.
        (None, "single_weight", 1, None),
        (None, "split_weight", 2, None),
    ],
)
def test_recorded_external_load_keeps_zero_and_unknown_apart(
    weight_kg: int | None, load_type: str, side_count: int, expected: int | None
) -> None:
    result = recorded_external_load(
        weight_kg=weight_kg,
        load_type=load_type,  # type: ignore[arg-type]
        side_count=side_count,
    )
    assert result == expected


@pytest.mark.parametrize(
    ("reps", "expected"),
    [(None, None), (0, None), (1, 100), (2, 106), (5, 116), (10, 133), (11, None), (30, None)],
)
def test_estimated_one_rep_max_uses_floored_rep_boundaries(
    reps: int | None, expected: int | None
) -> None:
    assert (
        estimated_one_rep_max(
            external_load_kg=100, reps=reps, load_type="single_weight", bodyweight_percent=None
        )
        == expected
    )


@pytest.mark.parametrize("load_type", ["single_weight", "split_weight"])
def test_estimated_one_rep_max_requires_no_bodyweight_contribution(load_type: str) -> None:
    assert (
        estimated_one_rep_max(
            external_load_kg=100,
            reps=5,
            load_type=load_type,  # type: ignore[arg-type]
            bodyweight_percent=None,
        )
        == 116
    )
    # Any bodyweight share makes the estimate inapplicable, however small.
    assert (
        estimated_one_rep_max(
            external_load_kg=100,
            reps=5,
            load_type=load_type,  # type: ignore[arg-type]
            bodyweight_percent=1,
        )
        is None
    )


def test_estimated_one_rep_max_is_unknown_without_external_load() -> None:
    assert (
        estimated_one_rep_max(
            external_load_kg=0, reps=5, load_type="bodyweight", bodyweight_percent=100
        )
        is None
    )
    assert (
        estimated_one_rep_max(
            external_load_kg=None, reps=5, load_type="single_weight", bodyweight_percent=None
        )
        is None
    )


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (5, 3, 2),
        (3, 5, -2),
        (0, 0, 0),
        (-100, 3, -103),
        (None, 3, None),
        (3, None, None),
        (None, None, None),
    ],
)
def test_integer_delta_preserves_unknown_operands(
    current: int | None, previous: int | None, expected: int | None
) -> None:
    assert integer_delta(current, previous) == expected


def test_stage_eight_calculations_reject_unsafe_intermediate_or_output() -> None:
    with pytest.raises(NumericRangeError):
        recorded_external_load(weight_kg=MAX_SAFE_INTEGER, load_type="split_weight", side_count=2)
    with pytest.raises(NumericRangeError):
        estimated_one_rep_max(
            external_load_kg=MAX_SAFE_INTEGER,
            reps=10,
            load_type="single_weight",
            bodyweight_percent=None,
        )
    with pytest.raises(NumericRangeError):
        integer_delta(MAX_SAFE_INTEGER, -1)


def test_calculate_set_load_reports_every_derived_value() -> None:
    assert calculate_set_load(
        reps=8,
        weight_kg=100,
        load_type="single_weight",
        side_count=1,
        bodyweight_kg=None,
        bodyweight_percent=None,
    ) == SetLoad(
        external_load_kg=100,
        effective_load_kg=100,
        volume_kg_reps=800,
        # 100 * (30 + 8) // 30
        estimated_1rm_kg=126,
    )
    # A bodyweight contribution is part of the effective load but removes the
    # external-load-only 1RM estimate.
    assert calculate_set_load(
        reps=8,
        weight_kg=20,
        load_type="single_weight",
        side_count=1,
        bodyweight_kg=80,
        bodyweight_percent=50,
    ) == SetLoad(
        external_load_kg=20, effective_load_kg=60, volume_kg_reps=480, estimated_1rm_kg=None
    )


@pytest.mark.parametrize(
    ("field_type", "valid", "invalid"),
    [
        (BodyweightKg, 1, 0),
        (Index, 0, -1),
        (Percentage, 100, 0),
        (Rpe, 10, 0),
        (SideCount, 2, 3),
    ],
)
def test_common_integer_types_enforce_bounds_and_strictness(
    field_type: object,
    valid: int,
    invalid: int,
) -> None:
    from pydantic import TypeAdapter

    adapter = TypeAdapter(field_type)  # type: ignore[arg-type]
    assert adapter.validate_python(valid) == valid
    for value in (invalid, str(valid), float(valid), True):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


@pytest.mark.parametrize(
    "payload",
    [
        {"load_type": "single_weight", "done": True, "reps": 1.0, "weight_kg": 1},
        {"load_type": "single_weight", "done": True, "reps": "1", "weight_kg": 1},
        {"load_type": "single_weight", "done": True, "reps": True, "weight_kg": 1},
        {"load_type": "single_weight", "done": True, "reps": 1, "weight_kg": -1},
        {"load_type": "single_weight", "done": True, "reps": 1, "weight_kg": 1, "rpe": 11},
        {
            "load_type": "single_weight",
            "done": True,
            "reps": 1,
            "weight_kg": 1,
            "bw_percent_override": 101,
        },
        {"load_type": "single_weight", "done": True, "reps": 0, "weight_kg": 1},
        {"load_type": "single_weight", "done": True, "reps": 1, "weight_kg": None},
        {"load_type": "bodyweight", "done": True, "reps": 1, "weight_kg": 0},
        {"load_type": "bodyweight", "done": True, "reps": 1, "weight_kg": None, "extra": 1},
    ],
)
def test_set_input_rejects_invalid_integer_and_cross_field_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SetInput.model_validate(payload)


def test_set_input_allows_drafts_and_completed_weighted_or_bodyweight_sets() -> None:
    assert SetInput(load_type="single_weight", done=False).model_dump() == {
        "load_type": "single_weight",
        "reps": None,
        "weight_kg": None,
        "rpe": None,
        "bw_percent_override": None,
        "done": False,
    }
    assert SetInput(load_type="split_weight", done=True, reps=8, weight_kg=12).reps == 8
    assert SetInput(load_type="bodyweight", done=True, reps=10, weight_kg=None).weight_kg is None
