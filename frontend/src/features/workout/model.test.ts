import { describe, expect, it } from 'vitest';
import type { EditableWorkoutContent, LoadSnapshot } from '../../db';
import {
  provisionalTotal,
  setError,
  strictInteger,
  updateInteger,
} from './model';

const weighted: LoadSnapshot = {
  load_type: 'single_weight',
  bodyweight_percent: null,
  side_count: 1,
};

function content(): EditableWorkoutContent {
  return {
    name: null,
    notes: null,
    bodyweight_kg: 80,
    ended_at: null,
    raw_fields: {},
    recorded_load_snapshots: { exercise: weighted },
    provisional_load_snapshots: {},
    exercises: [
      {
        id: 'exercise',
        catalog_id: 'catalog',
        notes: null,
        sets: [
          {
            id: 'set',
            reps: 8,
            weight_kg: 50,
            bw_percent_override: null,
            rpe: null,
            side: 'bilateral',
            done: true,
          },
        ],
      },
    ],
  };
}

describe('workout editor model', () => {
  it('accepts only strict safe decimal integers', () => {
    expect(strictInteger('12')).toBe(12);
    expect(strictInteger('-1')).toBe(-1);
    for (const value of [
      '',
      ' 12',
      '12 ',
      '12.0',
      '1e2',
      '+2',
      '9007199254740992',
    ])
      expect(strictInteger(value)).toBeNull();
  });

  it('retains invalid raw text and makes the corresponding set unknown', () => {
    const next = updateInteger(content(), 'set', 'weight_kg', '12.5');
    expect(next.raw_fields['set.weight_kg']).toBe('12.5');
    expect(next.exercises[0].sets[0].weight_kg).toBeNull();
    expect(setError(next, next.exercises[0], next.exercises[0].sets[0])).toBe(
      'Use whole numbers only.',
    );
    expect(provisionalTotal(next)).toEqual({
      knownVolume: null,
      unknownSetCount: 1,
      completedSetCount: 1,
    });
  });

  it('reports known volume and completed-set requirements honestly', () => {
    expect(provisionalTotal(content())).toEqual({
      knownVolume: 400,
      unknownSetCount: 0,
      completedSetCount: 1,
    });
    const invalid = content();
    invalid.exercises[0].sets[0].reps = null;
    expect(
      setError(invalid, invalid.exercises[0], invalid.exercises[0].sets[0]),
    ).toBe('A completed set needs at least one rep.');
  });
});
