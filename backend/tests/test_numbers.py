"""Stage 2 integer arithmetic and input-validation contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.numbers import (
    MAX_SAFE_INTEGER,
    NumericRangeError,
    bodyweight_load,
    calculate_set_load,
    external_load,
    floor_divide,
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
