/**
 * Exact integer arithmetic mirroring backend/app/numbers.py (PLAN.md §3).
 *
 * All domain arithmetic runs on `bigint` without floating-point
 * intermediates. BigInt division truncates toward zero, so floor division
 * applies a remainder-sign correction. Every operand is validated with
 * `Number.isSafeInteger` before conversion, every intermediate (including
 * products before division) stays inside the shared safe range, and every
 * conversion back to `number` is range-checked rather than rounded.
 * `null` means unknown; `0` means a known zero.
 */

export type LoadType = 'single_weight' | 'split_weight' | 'bodyweight';

export const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
export const MIN_SAFE_INTEGER = Number.MIN_SAFE_INTEGER;

const MAX_SAFE_BIG = BigInt(MAX_SAFE_INTEGER);
const MIN_SAFE_BIG = BigInt(MIN_SAFE_INTEGER);

/** Above this rep count an external-load 1RM estimate is not meaningful. */
export const MAX_ESTIMATED_ONE_REP_REPS = 10;

export class NumericRangeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NumericRangeError';
  }
}

function rangeMessage(name: string): string {
  return `${name} must be an integer between ${MIN_SAFE_INTEGER} and ${MAX_SAFE_INTEGER}`;
}

/** Validate a numeric operand and convert it to BigInt exactly. */
function requireSafeInteger(value: number, name = 'value'): bigint {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new NumericRangeError(rangeMessage(name));
  }
  return BigInt(value);
}

/** Bound an arithmetic intermediate (BigInt precision does not waive it). */
function requireSafeBig(value: bigint, name: string): bigint {
  if (value < MIN_SAFE_BIG || value > MAX_SAFE_BIG) {
    throw new NumericRangeError(rangeMessage(name));
  }
  return value;
}

/** Reject unsafe results rather than rounding them back to `number`. */
function checkedResult(value: bigint): number {
  requireSafeBig(value, 'calculation result');
  return Number(value);
}

/** Floor division on validated BigInts; callers guarantee a nonzero divisor. */
function floorBig(numerator: bigint, denominator: bigint): bigint {
  requireSafeBig(numerator, 'numerator');
  requireSafeBig(denominator, 'denominator');
  let quotient = numerator / denominator;
  const remainder = numerator % denominator;
  // BigInt division truncates toward zero; correct when the remainder's sign
  // differs from the denominator's (e.g. -100n / 3n must floor to -34n).
  if (remainder !== 0n && remainder < 0n !== denominator < 0n) {
    quotient -= 1n;
  }
  return quotient;
}

/** Floor-divide exact integers; a zero denominator is the unknown result. */
export function floorDivide(
  numerator: number,
  denominator: number,
): number | null {
  const dividend = requireSafeInteger(numerator, 'numerator');
  const divisor = requireSafeInteger(denominator, 'denominator');
  if (divisor === 0n) {
    return null;
  }
  return checkedResult(floorBig(dividend, divisor));
}

/** The floored bodyweight contribution for a set. */
export function bodyweightLoad(
  bodyweightKg: number,
  bodyweightPercent: number,
): number {
  const bodyweight = requireSafeInteger(bodyweightKg, 'bodyweight_kg');
  const percent = requireSafeInteger(bodyweightPercent, 'bodyweight_percent');
  // The product is bounded before division even when the quotient would fit.
  return checkedResult(floorBig(bodyweight * percent, 100n));
}

/** External load for a single or split-weight exercise. */
export function externalLoad(weightKg: number, multiplier: number): number {
  const weight = requireSafeInteger(weightKg, 'weight_kg');
  const factor = requireSafeInteger(multiplier, 'multiplier');
  return checkedResult(weight * factor);
}

export interface RecordedLoadInput {
  weightKg: number | null;
  loadType: LoadType;
  sideCount: number;
}

/**
 * The external load implied by one set's recorded inputs. A pure-bodyweight
 * set contributes zero (its null weight is never multiplied); a weighted set
 * with an unrecorded weight stays unknown rather than becoming zero.
 */
export function recordedExternalLoad(input: RecordedLoadInput): number | null {
  const { weightKg, loadType, sideCount } = input;
  const sides = requireSafeInteger(sideCount, 'side_count');
  const weight =
    weightKg === null ? null : requireSafeInteger(weightKg, 'weight_kg');

  if (loadType === 'bodyweight') {
    return 0;
  }
  if (weight === null) {
    return null;
  }
  if (loadType === 'single_weight') {
    return checkedResult(weight);
  }
  if (loadType === 'split_weight') {
    return checkedResult(weight * sides);
  }
  throw new NumericRangeError(`unsupported load_type: ${String(loadType)}`);
}

export interface EffectiveLoadInput extends RecordedLoadInput {
  bodyweightKg: number | null;
  bodyweightPercent: number | null;
}

/**
 * Effective load from the recorded exercise and workout inputs. When a
 * percentage applies but bodyweight is unknown, the result stays unknown even
 * though the external load may be known.
 */
export function effectiveLoad(input: EffectiveLoadInput): number | null {
  const external = recordedExternalLoad(input);
  const { bodyweightKg, bodyweightPercent } = input;
  if (external === null) {
    return null;
  }
  if (bodyweightPercent === null) {
    return external;
  }
  if (bodyweightKg === null) {
    return null;
  }
  const contribution = bodyweightLoad(bodyweightKg, bodyweightPercent);
  return checkedResult(BigInt(external) + BigInt(contribution));
}

/** Set volume, preserving an unknown input as an unknown result. */
export function setVolume(
  reps: number | null,
  effectiveLoadKg: number | null,
): number | null {
  if (reps === null || effectiveLoadKg === null) {
    return null;
  }
  const repCount = requireSafeInteger(reps, 'reps');
  const load = requireSafeInteger(effectiveLoadKg, 'effective_load_kg');
  return checkedResult(repCount * load);
}

export interface OneRepMaxInput {
  externalLoadKg: number | null;
  reps: number | null;
  loadType: LoadType;
  bodyweightPercent: number | null;
}

/**
 * The floored 1RM estimate for an external-load-only set: one rep is the
 * external load itself, 2..10 reps use `external_load * (30 + reps) // 30`,
 * and anything else is unknown. Pure-bodyweight and weighted-bodyweight sets
 * are always unknown because the bodyweight share is an estimate.
 */
export function estimatedOneRepMax(input: OneRepMaxInput): number | null {
  const { externalLoadKg, reps, loadType, bodyweightPercent } = input;
  if (loadType === 'bodyweight' || bodyweightPercent !== null) {
    return null;
  }
  if (externalLoadKg === null || reps === null) {
    return null;
  }
  const load = requireSafeInteger(externalLoadKg, 'external_load_kg');
  const repCount = requireSafeInteger(reps, 'reps');
  if (repCount < 1n) {
    return null;
  }
  if (repCount === 1n) {
    return checkedResult(load);
  }
  if (repCount > BigInt(MAX_ESTIMATED_ONE_REP_REPS)) {
    return null;
  }
  return checkedResult(floorBig(load * (30n + repCount), 30n));
}

/** `current - previous`, keeping an unknown operand unknown. */
export function integerDelta(
  current: number | null,
  previous: number | null,
): number | null {
  if (current === null || previous === null) {
    return null;
  }
  const currentValue = requireSafeInteger(current, 'current');
  const previousValue = requireSafeInteger(previous, 'previous');
  return checkedResult(currentValue - previousValue);
}

export interface SetLoad {
  external_load_kg: number | null;
  effective_load_kg: number | null;
  volume_kg_reps: number | null;
  estimated_1rm_kg: number | null;
}

export interface SetLoadInput extends EffectiveLoadInput {
  reps: number | null;
}

/**
 * The derived values for one set, resolving the complete documented
 * calculation order in one call. `bodyweightPercent` is the set's effective
 * percentage (its override when recorded, otherwise the exercise snapshot).
 */
export function calculateSetLoad(input: SetLoadInput): SetLoad {
  const { reps, loadType, bodyweightPercent } = input;
  const external = recordedExternalLoad(input);
  const effective = effectiveLoad(input);
  return {
    external_load_kg: external,
    effective_load_kg: effective,
    volume_kg_reps: setVolume(reps, effective),
    estimated_1rm_kg: estimatedOneRepMax({
      externalLoadKg: external,
      reps,
      loadType,
      bodyweightPercent,
    }),
  };
}
