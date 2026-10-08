// @vitest-environment node
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  MAX_ESTIMATED_ONE_REP_REPS,
  MAX_SAFE_INTEGER,
  MIN_SAFE_INTEGER,
  NumericRangeError,
  bodyweightLoad,
  calculateSetLoad,
  effectiveLoad,
  estimatedOneRepMax,
  externalLoad,
  floorDivide,
  integerDelta,
  recordedExternalLoad,
  setVolume,
  type LoadType,
} from './numbers';

interface FixtureExample {
  name: string;
  input: {
    reps: number | null;
    weight_kg: number | null;
    load_type: LoadType;
    side_count: number;
    bodyweight_kg: number | null;
    bodyweight_percent: number | null;
  };
  expected: {
    effective_load_kg: number | null;
    volume_kg_reps: number | null;
  };
}

interface FixtureFloorDivision {
  numerator: number;
  denominator: number;
  expected: number | null;
}

interface FixtureFile {
  safe_integer_max: number;
  examples: FixtureExample[];
  floor_division: FixtureFloorDivision[];
}

// The shared fixtures are read directly from the repository root; values are
// never copied into this file (IMPLEMENTATION.md ground rules).
const fixtures = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL('../../../tests/fixtures/numeric_examples.json', import.meta.url),
    ),
    'utf8',
  ),
) as FixtureFile;

describe('shared numeric fixtures', () => {
  it('agrees on the safe integer bound', () => {
    expect(fixtures.safe_integer_max).toBe(MAX_SAFE_INTEGER);
    expect(MAX_SAFE_INTEGER).toBe(2 ** 53 - 1);
    expect(MIN_SAFE_INTEGER).toBe(-MAX_SAFE_INTEGER);
  });

  it.each(fixtures.examples)(
    'calculates "$name" exactly like the backend',
    (example) => {
      const load = calculateSetLoad({
        reps: example.input.reps,
        weightKg: example.input.weight_kg,
        loadType: example.input.load_type,
        sideCount: example.input.side_count,
        bodyweightKg: example.input.bodyweight_kg,
        bodyweightPercent: example.input.bodyweight_percent,
      });
      expect(load.effective_load_kg).toBe(example.expected.effective_load_kg);
      expect(load.volume_kg_reps).toBe(example.expected.volume_kg_reps);
    },
  );

  it.each(fixtures.floor_division)(
    'floors $numerator / $denominator to $expected',
    (entry) => {
      expect(floorDivide(entry.numerator, entry.denominator)).toBe(
        entry.expected,
      );
    },
  );
});

describe('floorDivide', () => {
  it('floors toward negative infinity for mixed signs', () => {
    expect(floorDivide(-100, 3)).toBe(-34);
    expect(floorDivide(100, -3)).toBe(-34);
    expect(floorDivide(-100, -3)).toBe(33);
    expect(floorDivide(7, 2)).toBe(3);
    expect(floorDivide(-7, 2)).toBe(-4);
  });

  it('needs no correction for exact division', () => {
    expect(floorDivide(-6, 3)).toBe(-2);
    expect(floorDivide(0, 5)).toBe(0);
    expect(floorDivide(0, -5)).toBe(0);
  });

  it('treats a zero denominator as the unknown result', () => {
    expect(floorDivide(1, 0)).toBeNull();
    expect(floorDivide(-1, 0)).toBeNull();
    expect(floorDivide(0, 0)).toBeNull();
  });

  it('accepts safe-range edges', () => {
    expect(floorDivide(MAX_SAFE_INTEGER, 1)).toBe(MAX_SAFE_INTEGER);
    expect(floorDivide(MIN_SAFE_INTEGER, 1)).toBe(MIN_SAFE_INTEGER);
    expect(floorDivide(MAX_SAFE_INTEGER, MAX_SAFE_INTEGER)).toBe(1);
  });

  it('rejects unsafe and non-integer operands', () => {
    // MAX_SAFE_INTEGER + 1 is exactly representable but no longer safe.
    expect(() => floorDivide(MAX_SAFE_INTEGER + 1, 1)).toThrow(
      NumericRangeError,
    );
    expect(() => floorDivide(MIN_SAFE_INTEGER - 1, 1)).toThrow(
      NumericRangeError,
    );
    expect(() => floorDivide(1.5, 1)).toThrow(NumericRangeError);
    expect(() => floorDivide(1, 0.5)).toThrow(NumericRangeError);
    expect(() => floorDivide(Number.NaN, 1)).toThrow(NumericRangeError);
    expect(() => floorDivide(Number.POSITIVE_INFINITY, 1)).toThrow(
      NumericRangeError,
    );
  });
});

describe('load calculations', () => {
  it('computes the floored bodyweight contribution', () => {
    expect(bodyweightLoad(81, 65)).toBe(52);
    expect(bodyweightLoad(80, 100)).toBe(80);
    expect(bodyweightLoad(1, 1)).toBe(0);
  });

  it('bounds the product before division even when the quotient would fit', () => {
    // 900719925474099 * 100 exceeds the safe range; the quotient does not.
    expect(() => bodyweightLoad(900719925474099, 100)).toThrow(
      NumericRangeError,
    );
  });

  it('multiplies split weights by the side count', () => {
    expect(externalLoad(12, 2)).toBe(24);
    expect(externalLoad(0, 2)).toBe(0);
    expect(() => externalLoad(MAX_SAFE_INTEGER, 2)).toThrow(NumericRangeError);
  });

  it('contributes zero external load for bodyweight and never multiplies null', () => {
    expect(
      recordedExternalLoad({
        weightKg: null,
        loadType: 'bodyweight',
        sideCount: 1,
      }),
    ).toBe(0);
    expect(
      recordedExternalLoad({
        weightKg: null,
        loadType: 'single_weight',
        sideCount: 1,
      }),
    ).toBeNull();
    expect(
      recordedExternalLoad({
        weightKg: 20,
        loadType: 'split_weight',
        sideCount: 2,
      }),
    ).toBe(40);
  });

  it('keeps effective load unknown when a percentage applies without bodyweight', () => {
    expect(
      effectiveLoad({
        weightKg: 20,
        loadType: 'single_weight',
        sideCount: 1,
        bodyweightKg: null,
        bodyweightPercent: 50,
      }),
    ).toBeNull();
    expect(
      effectiveLoad({
        weightKg: 20,
        loadType: 'single_weight',
        sideCount: 1,
        bodyweightKg: 80,
        bodyweightPercent: null,
      }),
    ).toBe(20);
    expect(
      effectiveLoad({
        weightKg: 0,
        loadType: 'single_weight',
        sideCount: 1,
        bodyweightKg: 81,
        bodyweightPercent: 65,
      }),
    ).toBe(52);
  });

  it('distinguishes a known zero volume from an unknown one', () => {
    expect(setVolume(10, 0)).toBe(0);
    expect(setVolume(10, null)).toBeNull();
    expect(setVolume(null, 10)).toBeNull();
    expect(setVolume(10, 52)).toBe(520);
  });
});

describe('estimatedOneRepMax', () => {
  it('returns the load itself for one rep', () => {
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: 1,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toBe(100);
  });

  it('floors the 2..10 rep estimate', () => {
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: 5,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toBe(116); // 100 * 35 // 30 = 116.67 floored
    expect(
      estimatedOneRepMax({
        externalLoadKg: 12,
        reps: MAX_ESTIMATED_ONE_REP_REPS,
        loadType: 'split_weight',
        bodyweightPercent: null,
      }),
    ).toBe(16); // 12 * 40 // 30
  });

  it('is unknown for bodyweight contributions, zero/high reps, and null inputs', () => {
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: 5,
        loadType: 'bodyweight',
        bodyweightPercent: null,
      }),
    ).toBeNull();
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: 5,
        loadType: 'single_weight',
        bodyweightPercent: 30,
      }),
    ).toBeNull();
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: 0,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toBeNull();
    expect(
      estimatedOneRepMax({
        externalLoadKg: 100,
        reps: MAX_ESTIMATED_ONE_REP_REPS + 1,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toBeNull();
    expect(
      estimatedOneRepMax({
        externalLoadKg: null,
        reps: 5,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toBeNull();
  });

  it('bounds the estimate intermediate', () => {
    expect(() =>
      estimatedOneRepMax({
        externalLoadKg: MAX_SAFE_INTEGER,
        reps: 10,
        loadType: 'single_weight',
        bodyweightPercent: null,
      }),
    ).toThrow(NumericRangeError);
  });
});

describe('integerDelta', () => {
  it('computes signed deltas', () => {
    expect(integerDelta(52, 50)).toBe(2);
    expect(integerDelta(50, 52)).toBe(-2);
    expect(integerDelta(0, 0)).toBe(0);
  });

  it('keeps an unknown operand unknown', () => {
    expect(integerDelta(null, 5)).toBeNull();
    expect(integerDelta(5, null)).toBeNull();
    expect(integerDelta(null, null)).toBeNull();
  });

  it('rejects a delta leaving the safe range', () => {
    expect(() => integerDelta(MAX_SAFE_INTEGER, MIN_SAFE_INTEGER)).toThrow(
      NumericRangeError,
    );
  });
});
