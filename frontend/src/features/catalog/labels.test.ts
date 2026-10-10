import { describe, expect, it } from 'vitest';
import { compactExerciseSummary, compactLoadLabel } from './labels';
import { sessionDate, volumeLabel } from '../exercises/statsFormat';

describe('compact exercise labels', () => {
  it('maps load types to the coarse Bodyweight/Weighted labels', () => {
    expect(compactLoadLabel('bodyweight')).toBe('Bodyweight');
    expect(compactLoadLabel('single_weight')).toBe('Weighted');
    expect(compactLoadLabel('split_weight')).toBe('Weighted');
  });

  it('summarizes cards as body part and coarse type only', () => {
    expect(
      compactExerciseSummary({
        muscle_group: 'shoulders',
        load_type: 'split_weight',
      }),
    ).toBe('Shoulders · Weighted');
    expect(
      compactExerciseSummary({
        muscle_group: 'back',
        load_type: 'bodyweight',
      }),
    ).toBe('Back · Bodyweight');
  });
});

describe('volume labels', () => {
  it('keeps unknown, partial, and complete volumes distinct', () => {
    expect(volumeLabel(null, false)).toBe('Unknown');
    expect(volumeLabel(600, false)).toBe('At least 600 kg·reps');
    expect(volumeLabel(600, true)).toBe('600 kg·reps');
    expect(volumeLabel(0, true)).toBe('0 kg·reps');
  });

  it('formats session dates at the fixed UTC offset', () => {
    const session = {
      workout_id: 'w-1',
      started_at: '2026-09-01T22:30:00Z',
      completed_set_count: 4,
      volume_kg_reps: 2880,
      unknown_load_set_count: 0,
      volume_complete: true,
    };
    expect(sessionDate(session, 180)).toBe('2026-09-02');
    expect(sessionDate(session, 0)).toBe('2026-09-01');
    expect(sessionDate(session, -180)).toBe('2026-09-01');
  });
});
