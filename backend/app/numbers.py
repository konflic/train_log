"""Integer-only arithmetic used for recorded workout load calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# JavaScript cannot safely represent larger JSON integers, so this lower bound
# also keeps every value emitted by the API inside SQLite's INTEGER range.
MAX_SAFE_INTEGER = (1 << 53) - 1
MIN_SAFE_INTEGER = -MAX_SAFE_INTEGER

# Above this rep count an external-load 1RM estimate is not meaningful
# (PLAN.md §7 Metrics); the value is reported as unknown instead.
MAX_ESTIMATED_ONE_REP_REPS = 10

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


def recorded_external_load(
    *,
    weight_kg: int | None,
    load_type: LoadType,
    side_count: int,
) -> int | None:
    """Return the external load implied by one set's recorded inputs.

    A pure-bodyweight set has no external weight and contributes zero; the
    `weight_kg` field is not multiplied (PLAN.md §4). A weighted set whose
    weight was never recorded stays unknown rather than becoming zero.
    """
    if weight_kg is not None:
        weight_kg = require_safe_integer(weight_kg, name="weight_kg")
    side_count = require_safe_integer(side_count, name="side_count")

    if load_type == "bodyweight":
        return 0
    if weight_kg is None:
        return None
    if load_type == "single_weight":
        return external_load(weight_kg, 1)
    if load_type == "split_weight":
        return external_load(weight_kg, side_count)
    raise ValueError(f"unsupported load_type: {load_type!r}")


def effective_load(
    *,
    weight_kg: int | None,
    load_type: LoadType,
    side_count: int,
    bodyweight_kg: int | None,
    bodyweight_percent: int | None,
) -> int | None:
    """Calculate effective load from the recorded exercise and workout inputs."""
    external = recorded_external_load(
        weight_kg=weight_kg, load_type=load_type, side_count=side_count
    )
    if bodyweight_kg is not None:
        bodyweight_kg = require_safe_integer(bodyweight_kg, name="bodyweight_kg")
    if bodyweight_percent is not None:
        bodyweight_percent = require_safe_integer(bodyweight_percent, name="bodyweight_percent")

    if external is None:
        return None
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


def estimated_one_rep_max(
    *,
    external_load_kg: int | None,
    reps: int | None,
    load_type: LoadType,
    bodyweight_percent: int | None,
) -> int | None:
    """Return the floored 1RM estimate for an external-load-only set.

    Only weighted exercises without a bodyweight contribution have an estimate:
    one rep is the external load itself, 2 through
    `MAX_ESTIMATED_ONE_REP_REPS` reps use `external_load * (30 + reps) // 30`,
    and higher rep counts are unknown. Pure-bodyweight and weighted-bodyweight
    sets are always unknown, because the bodyweight share is an estimate rather
    than a measured external load (PLAN.md §7).
    """
    if load_type == "bodyweight" or bodyweight_percent is not None:
        return None
    if external_load_kg is None or reps is None:
        return None
    external_load_kg = require_safe_integer(external_load_kg, name="external_load_kg")
    reps = require_safe_integer(reps, name="reps")
    if reps < 1:
        return None
    if reps == 1:
        return external_load_kg
    if reps > MAX_ESTIMATED_ONE_REP_REPS:
        return None
    return floor_divide(external_load_kg * (30 + reps), 30)


def integer_delta(current: int | None, previous: int | None) -> int | None:
    """Return `current - previous`, keeping an unknown operand unknown."""
    if current is None or previous is None:
        return None
    current = require_safe_integer(current, name="current")
    previous = require_safe_integer(previous, name="previous")
    return _checked_result(current - previous)


@dataclass(frozen=True, slots=True)
class SetLoad:
    """The derived values for one set, with ``None`` representing unknown."""

    external_load_kg: int | None
    effective_load_kg: int | None
    volume_kg_reps: int | None
    estimated_1rm_kg: int | None


def calculate_set_load(
    *,
    reps: int | None,
    weight_kg: int | None,
    load_type: LoadType,
    side_count: int,
    bodyweight_kg: int | None,
    bodyweight_percent: int | None,
) -> SetLoad:
    """Calculate external load, effective load, volume, and 1RM estimate.

    `bodyweight_percent` is the set's effective percentage (its override when
    one is recorded, otherwise the exercise snapshot), so one call resolves the
    complete documented calculation order for one set.
    """
    external = recorded_external_load(
        weight_kg=weight_kg, load_type=load_type, side_count=side_count
    )
    result_load = effective_load(
        weight_kg=weight_kg,
        load_type=load_type,
        side_count=side_count,
        bodyweight_kg=bodyweight_kg,
        bodyweight_percent=bodyweight_percent,
    )
    return SetLoad(
        external_load_kg=external,
        effective_load_kg=result_load,
        volume_kg_reps=set_volume(reps, result_load),
        estimated_1rm_kg=estimated_one_rep_max(
            external_load_kg=external,
            reps=reps,
            load_type=load_type,
            bodyweight_percent=bodyweight_percent,
        ),
    )
