// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { validateExerciseDraft, type ExerciseDraft } from './validation';

function draft(overrides: Partial<ExerciseDraft> = {}): ExerciseDraft {
  return {
    name: 'Valid Name',
    loadType: 'single_weight',
    percentText: '',
    sideCount: 1,
    maxNameLength: 100,
    ...overrides,
  };
}

describe('validateExerciseDraft', () => {
  it('accepts a valid weighted draft', () => {
    expect(validateExerciseDraft(draft())).toEqual({});
    expect(
      validateExerciseDraft(draft({ loadType: 'split_weight', sideCount: 2 })),
    ).toEqual({});
    expect(validateExerciseDraft(draft({ percentText: '65' }))).toEqual({});
  });

  it('requires a non-blank name within the length bound', () => {
    expect(validateExerciseDraft(draft({ name: '   ' })).name).toMatch(
      /required/i,
    );
    expect(
      validateExerciseDraft(draft({ name: 'a'.repeat(101) })).name,
    ).toMatch(/at most/i);
    // Bounds count codepoints, not UTF-16 units.
    expect(
      validateExerciseDraft(draft({ name: '😀'.repeat(100) })).name,
    ).toBeUndefined();
  });

  it('requires a percentage for pure bodyweight entries', () => {
    expect(
      validateExerciseDraft(draft({ loadType: 'bodyweight', percentText: '' }))
        .bodyweight_percent,
    ).toMatch(/require a percentage/i);
    expect(
      validateExerciseDraft(
        draft({ loadType: 'bodyweight', percentText: '100' }),
      ),
    ).toEqual({});
  });

  it('rejects fractional or out-of-range percentages before any coercion', () => {
    const fractional = validateExerciseDraft(draft({ percentText: '12.5' }));
    expect(fractional.bodyweight_percent).toMatch(/whole number/i);
    expect(
      validateExerciseDraft(draft({ percentText: '1e2' })).bodyweight_percent,
    ).toMatch(/whole number/i);
    expect(
      validateExerciseDraft(draft({ percentText: '0' })).bodyweight_percent,
    ).toMatch(/between 1 and 100/i);
    expect(
      validateExerciseDraft(draft({ percentText: '101' })).bodyweight_percent,
    ).toMatch(/between 1 and 100/i);
    expect(
      validateExerciseDraft(draft({ percentText: '-5' })).bodyweight_percent,
    ).toMatch(/whole number/i);
  });

  it('enforces the split-weight side-count rule', () => {
    expect(
      validateExerciseDraft(draft({ loadType: 'single_weight', sideCount: 2 }))
        .side_count,
    ).toMatch(/split-weight/i);
    expect(validateExerciseDraft(draft({ sideCount: 3 })).side_count).toMatch(
      /1 or 2/i,
    );
  });
});
