import { describe, expect, it } from 'vitest';
import type { WorkoutDetail } from '../../api';
import { detailTotal, durationSeconds, percentageDelta } from './history';

const detail: WorkoutDetail = {
  id: 'workout-1',
  name: 'Recorded workout',
  started_at: '2026-10-09T10:00:00Z',
  ended_at: '2026-10-09T10:01:30Z',
  notes: null,
  bodyweight_kg: 81,
  revision: 2,
  last_save_id: 'save-1',
  exercises: [
    {
      id: 'exercise-1',
      catalog_id: 'catalog-1',
      order_index: 0,
      notes: null,
      load_type: 'bodyweight',
      bodyweight_percent: 65,
      side_count: 1,
      previous_performance: null,
      sets: [
        {
          id: 'set-known',
          set_index: 0,
          reps: 10,
          weight_kg: null,
          bw_percent_override: null,
          rpe: null,
          side: 'bilateral',
          done: true,
        },
        {
          id: 'set-unknown',
          set_index: 1,
          reps: 8,
          weight_kg: null,
          bw_percent_override: null,
          rpe: null,
          side: 'bilateral',
          done: false,
        },
      ],
    },
  ],
};

describe('history calculations', () => {
  it('uses recorded inputs and excludes incomplete sets from the total', () => {
    expect(detailTotal(detail)).toEqual({
      completedSetCount: 1,
      knownVolume: 520,
      unknownLoadSetCount: 0,
      complete: true,
    });
    expect(durationSeconds(detail)).toBe(90);
  });

  it('keeps zero and unknown comparisons distinct and floors negative percentages', () => {
    expect(percentageDelta(0, 10)).toBe(-100);
    expect(percentageDelta(10, 0)).toBeNull();
    expect(percentageDelta(null, 10)).toBeNull();
    expect(percentageDelta(2, 3)).toBe(-34);
  });
});
