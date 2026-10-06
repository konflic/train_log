"""Integer-only arithmetic used for recorded workout load calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# JavaScript cannot safely represent larger JSON integers, so this lower bound
# also keeps every value emitted by the API inside SQLite's INTEGER range.
MAX_SAFE_INTEGER = (1 << 53) - 1
MIN_SAFE_INTEGER = -MAX_SAFE_INTEGER

LoadType = Literal["single_weight", "split_weight", "bodyweight"]


class NumericRangeError(ValueError):
    """An operand or calculated value cannot safely be represented in JSON."""


def require_safe_integer(value: int, *, name: str = "value") -> int:
    """Return an exact integer that fits the shared JSON safe range."""
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
        raise NumericRangeError(f"{name} must be between {MIN_SAFE_INTEGER} and {MAX_SAFE_INTEGER}")
    return value


def _checked_result(value: int) -> int:
    return require_safe_integer(value, name="calculation result")


def floor_divide(numerator: int, denominator: int) -> int | None:
    """Floor-divide exact integers, treating a zero denominator as unknown."""
    numerator = require_safe_integer(numerator, name="numerator")
    denominator = require_safe_integer(denominator, name="denominator")
    if denominator == 0:
        return None
    return _checked_result(numerator // denominator)


def bodyweight_load(bodyweight_kg: int, bodyweight_percent: int) -> int:
    """Return the floored bodyweight contribution for a set."""
    bodyweight_kg = require_safe_integer(bodyweight_kg, name="bodyweight_kg")
    bodyweight_percent = require_safe_integer(bodyweight_percent, name="bodyweight_percent")
    result = floor_divide(bodyweight_kg * bodyweight_percent, 100)
    assert result is not None
    return result


def external_load(weight_kg: int, multiplier: int) -> int:
    """Return external load for a single or split-weight exercise."""
    weight_kg = require_safe_integer(weight_kg, name="weight_kg")
    multiplier = require_safe_integer(multiplier, name="multiplier")
    return _checked_result(weight_kg * multiplier)


def effective_load(
    *,
    weight_kg: int | None,
    load_type: LoadType,
    side_count: int,
    bodyweight_kg: int | None,
    bodyweight_percent: int | None,
) -> int | None:
    """Calculate effective load from the recorded exercise and workout inputs."""
    if weight_kg is not None:
        weight_kg = require_safe_integer(weight_kg, name="weight_kg")
    side_count = require_safe_integer(side_count, name="side_count")
    if bodyweight_kg is not None:
        bodyweight_kg = require_safe_integer(bodyweight_kg, name="bodyweight_kg")
    if bodyweight_percent is not None:
        bodyweight_percent = require_safe_integer(bodyweight_percent, name="bodyweight_percent")

    if load_type == "bodyweight":
        external = 0
    elif weight_kg is None:
        return None
    elif load_type == "single_weight":
        external = external_load(weight_kg, 1)
    elif load_type == "split_weight":
        external = external_load(weight_kg, side_count)
    else:
        raise ValueError(f"unsupported load_type: {load_type!r}")

    if bodyweight_percent is None:
        return external
    if bodyweight_kg is None:
        return None
    return _checked_result(external + bodyweight_load(bodyweight_kg, bodyweight_percent))


def set_volume(reps: int | None, effective_load_kg: int | None) -> int | None:
    """Return set volume, preserving an unknown input as an unknown result."""
    if reps is None or effective_load_kg is None:
        return None
    reps = require_safe_integer(reps, name="reps")
    effective_load_kg = require_safe_integer(effective_load_kg, name="effective_load_kg")
    return _checked_result(reps * effective_load_kg)


@dataclass(frozen=True, slots=True)
class SetLoad:
    """The derived loads for one set, with ``None`` representing unknown."""

    effective_load_kg: int | None
    volume_kg_reps: int | None


def calculate_set_load(
    *,
    reps: int | None,
    weight_kg: int | None,
    load_type: LoadType,
    side_count: int,
    bodyweight_kg: int | None,
    bodyweight_percent: int | None,
) -> SetLoad:
    """Calculate effective load then volume in the documented order."""
    result_load = effective_load(
        weight_kg=weight_kg,
        load_type=load_type,
        side_count=side_count,
        bodyweight_kg=bodyweight_kg,
        bodyweight_percent=bodyweight_percent,
    )
    return SetLoad(result_load, set_volume(reps, result_load))
