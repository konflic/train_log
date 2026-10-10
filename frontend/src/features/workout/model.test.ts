import { describe, expect, it } from 'vitest';
import type {
  EditableWorkoutContent,
  LoadSnapshot,
  WorkoutDraft,
} from '../../db';
import {
  catalogIssue,
  completionProgress,
  copyDraftToNewWorkout,
  fieldKey,
  contentError,
  exerciseProgress,
  finishBlocker,
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

  it('retains invalid raw text and reports its completion progress', () => {
    const next = updateInteger(content(), 'set', 'weight_kg', '12.5');
    expect(next.raw_fields['set.weight_kg']).toBe('12.5');
    expect(next.exercises[0].sets[0].weight_kg).toBeNull();
    expect(setError(next, next.exercises[0], next.exercises[0].sets[0])).toBe(
      'Use whole numbers only.',
    );
    expect(completionProgress(next)).toEqual({
      completedSets: 1,
      totalSets: 1,
      percent: 100,
    });
  });

  it('calculates completion percentage from completed and planned sets', () => {
    const partial = content();
    partial.exercises[0].sets.push({
      ...partial.exercises[0].sets[0],
      id: 'next',
      done: false,
    });
    expect(completionProgress(partial)).toEqual({
      completedSets: 1,
      totalSets: 2,
      percent: 50,
    });
    const invalid = content();
    invalid.exercises[0].sets[0].reps = null;
    expect(
      setError(invalid, invalid.exercises[0], invalid.exercises[0].sets[0]),
    ).toBe('A completed set needs at least one rep.');
  });

  it('separates exercises with all completed sets from in-progress exercises', () => {
    expect(exerciseProgress(content().exercises[0])).toEqual({
      completedSets: 1,
      totalSets: 1,
      complete: true,
    });
    const inProgress = content().exercises[0];
    inProgress.sets.push({ ...inProgress.sets[0], id: 'next', done: false });
    expect(exerciseProgress(inProgress)).toMatchObject({
      completedSets: 1,
      totalSets: 2,
      complete: false,
    });
  });

  it('blocks finishing without exercises or with an incomplete set', () => {
    expect(finishBlocker(content())).toBeNull();

    const empty = content();
    empty.exercises = [];
    expect(finishBlocker(empty)).toBe(
      'Add at least one exercise to finish this workout.',
    );

    const withoutSets = content();
    withoutSets.exercises[0].sets = [];
    expect(finishBlocker(withoutSets)).toBe(
      'Every exercise needs at least one set. Add a set or remove the exercise.',
    );

    const incomplete = content();
    incomplete.exercises[0].sets.push({
      ...incomplete.exercises[0].sets[0],
      id: 'next',
      done: false,
    });
    expect(finishBlocker(incomplete)).toBe(
      'Finish or remove the 1 incomplete set before finishing this workout.',
    );
    incomplete.exercises[0].sets.push({
      ...incomplete.exercises[0].sets[0],
      id: 'later',
      done: false,
    });
    expect(finishBlocker(incomplete)).toBe(
      'Finish or remove the 2 incomplete sets before finishing this workout.',
    );
  });

  it('blocks invalid visible integers from server payloads', () => {
    const invalid = content();
    invalid.raw_fields['workout.bodyweight_kg'] = '80.5';
    invalid.bodyweight_kg = null;
    expect(contentError(invalid)).toBe(
      'Recorded bodyweight must be a whole number.',
    );
    invalid.raw_fields['workout.bodyweight_kg'] = '80';
    invalid.bodyweight_kg = 80;
    expect(contentError(invalid)).toBeNull();
  });

  it('copies conflict work to independent IDs without resetting local values', () => {
    const source: WorkoutDraft = {
      account_id: 'account',
      workout_id: 'old-workout',
      draft_id: 'old-draft',
      base_detail_id: 'old-workout',
      base_revision: 2,
      started_at: '2026-10-08T10:00:00Z',
      content: content(),
      change_number: 3,
      acknowledged_change_number: 1,
      created_at: '2026-10-08T10:00:00Z',
      updated_at: '2026-10-08T10:10:00Z',
    };
    source.content.name = 'Local copy';
    source.content.notes = 'Keep this';
    source.content.exercises[0].notes = 'Exercise note';
    source.content.exercises[0].sets[0].rpe = 9;
    source.content.raw_fields['set.weight_kg'] = '50';

    const copied = copyDraftToNewWorkout(
      source,
      new Map([
        [
          'catalog',
          {
            id: 'catalog',
            name: 'Current exercise',
            muscle_group: 'chest',
            equipment: 'barbell',
            load_type: 'single_weight',
            bodyweight_percent: null,
            side_count: 1,
            is_default: true,
          } as const,
        ],
      ]),
      '2026-10-08T11:00:00Z',
    );

    expect(copied.workout_id).not.toBe(source.workout_id);
    expect(copied.draft_id).not.toBe(source.draft_id);
    expect(copied.content.exercises[0].id).not.toBe(
      source.content.exercises[0].id,
    );
    expect(copied.content.exercises[0].sets[0]).toMatchObject({
      reps: 8,
      weight_kg: 50,
      rpe: 9,
      done: true,
    });
    expect(copied.content.exercises[0].sets[0].id).not.toBe(
      source.content.exercises[0].sets[0].id,
    );
    expect(
      copied.content.raw_fields[
        fieldKey(copied.content.exercises[0].sets[0].id, 'weight_kg')
      ],
    ).toBe('50');
    expect(copied.content).toMatchObject({
      name: 'Local copy',
      notes: 'Keep this',
      bodyweight_kg: 80,
      ended_at: null,
    });
  });

  it('keeps an unavailable copied exercise visible and blocks its save', () => {
    const source: WorkoutDraft = {
      account_id: 'account',
      workout_id: 'old-workout',
      draft_id: 'old-draft',
      base_detail_id: 'old-workout',
      base_revision: 2,
      started_at: '2026-10-08T10:00:00Z',
      content: content(),
      change_number: 3,
      acknowledged_change_number: 1,
      created_at: '2026-10-08T10:00:00Z',
      updated_at: '2026-10-08T10:10:00Z',
    };
    const copied = copyDraftToNewWorkout(
      source,
      new Map([['catalog', null]]),
      '2026-10-08T11:00:00Z',
    );

    expect(copied.content.exercises).toHaveLength(1);
    expect(
      catalogIssue(copied.content, copied.content.exercises[0].id),
    ).toMatch(/no longer available/);
    expect(contentError(copied.content)).toMatch(/no longer available/);
  });

  it('revalidates copied values against current catalog load settings', () => {
    const source: WorkoutDraft = {
      account_id: 'account',
      workout_id: 'old-workout',
      draft_id: 'old-draft',
      base_detail_id: 'old-workout',
      base_revision: 2,
      started_at: '2026-10-08T10:00:00Z',
      content: content(),
      change_number: 3,
      acknowledged_change_number: 1,
      created_at: '2026-10-08T10:00:00Z',
      updated_at: '2026-10-08T10:10:00Z',
    };
    const copied = copyDraftToNewWorkout(
      source,
      new Map([
        [
          'catalog',
          {
            id: 'catalog',
            name: 'Changed exercise',
            muscle_group: 'chest',
            equipment: 'bodyweight',
            load_type: 'bodyweight',
            bodyweight_percent: 100,
            side_count: 1,
            is_default: false,
          } as const,
        ],
      ]),
      '2026-10-08T11:00:00Z',
    );

    expect(contentError(copied.content)).toBe(
      'Bodyweight exercises do not use an external weight.',
    );
  });
});
