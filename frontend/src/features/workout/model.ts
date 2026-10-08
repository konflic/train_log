import type {
  Exercise,
  SaveExerciseInput,
  SaveSetInput,
  WorkoutDetail,
} from '../../api';
import {
  createDraftId,
  type EditableWorkoutContent,
  type LoadSnapshot,
  type WorkoutDraft,
} from '../../db';
import { calculateSetLoad } from '../../lib/numbers';

export const MAX_EXERCISES = 25;
export const MAX_SETS_PER_EXERCISE = 20;
export const MAX_SETS = 250;

export function strictInteger(raw: string): number | null {
  if (!/^-?(?:0|[1-9]\d*)$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) ? value : null;
}

export function snapshotFor(exercise: Exercise): LoadSnapshot {
  return {
    load_type: exercise.load_type,
    bodyweight_percent: exercise.bodyweight_percent,
    side_count: exercise.side_count,
  };
}

export function contentFromDetail(
  detail: WorkoutDetail,
): EditableWorkoutContent {
  const snapshots: Record<string, LoadSnapshot> = {};
  const exercises: SaveExerciseInput[] = detail.exercises.map((exercise) => {
    snapshots[exercise.id] = {
      load_type: exercise.load_type,
      bodyweight_percent: exercise.bodyweight_percent,
      side_count: exercise.side_count,
    };
    return {
      id: exercise.id,
      catalog_id: exercise.catalog_id,
      notes: exercise.notes,
      sets: exercise.sets.map((set) => ({
        id: set.id,
        reps: set.reps,
        weight_kg: set.weight_kg,
        bw_percent_override: set.bw_percent_override,
        rpe: set.rpe,
        side: set.side,
        done: set.done,
      })),
    };
  });
  return {
    name: detail.name,
    notes: detail.notes,
    bodyweight_kg: detail.bodyweight_kg,
    ended_at: detail.ended_at,
    exercises,
    raw_fields: {},
    recorded_load_snapshots: snapshots,
    provisional_load_snapshots: {},
  };
}

export function draftFromDetail(
  accountId: string,
  detail: WorkoutDetail,
): WorkoutDraft {
  const now = new Date().toISOString();
  return {
    account_id: accountId,
    workout_id: detail.id,
    draft_id: createDraftId(),
    base_detail_id: detail.id,
    base_revision: detail.revision,
    started_at: detail.started_at,
    content: contentFromDetail(detail),
    change_number: 0,
    acknowledged_change_number: 0,
    created_at: now,
    updated_at: now,
  };
}

export function emptySet(snapshot: LoadSnapshot): SaveSetInput {
  return {
    id: createDraftId(),
    reps: null,
    weight_kg: null,
    bw_percent_override: null,
    rpe: null,
    side:
      snapshot.load_type === 'split_weight' && snapshot.side_count === 1
        ? 'left'
        : 'bilateral',
    done: false,
  };
}

export function fieldKey(setId: string, field: string): string {
  return `${setId}.${field}`;
}

export function rawValue(
  content: EditableWorkoutContent,
  set: SaveSetInput,
  field: 'reps' | 'weight_kg' | 'bw_percent_override' | 'rpe',
): string {
  return (
    content.raw_fields[fieldKey(set.id, field)] ?? String(set[field] ?? '')
  );
}

export function updateInteger(
  content: EditableWorkoutContent,
  setId: string,
  field: 'reps' | 'weight_kg' | 'bw_percent_override' | 'rpe',
  raw: string,
): EditableWorkoutContent {
  const next = structuredClone(content);
  next.raw_fields[fieldKey(setId, field)] = raw;
  for (const exercise of next.exercises) {
    const set = exercise.sets.find((candidate) => candidate.id === setId);
    if (set) {
      set[field] = raw === '' ? null : strictInteger(raw);
      break;
    }
  }
  return next;
}

export interface ProvisionalTotal {
  knownVolume: number | null;
  unknownSetCount: number;
  completedSetCount: number;
}

export function provisionalTotal(
  content: EditableWorkoutContent,
): ProvisionalTotal {
  let known = 0;
  let knownCount = 0;
  let unknown = 0;
  let completed = 0;
  for (const exercise of content.exercises) {
    const snapshot =
      content.recorded_load_snapshots[exercise.id] ??
      content.provisional_load_snapshots[exercise.id];
    if (!snapshot) continue;
    for (const set of exercise.sets) {
      if (!set.done) continue;
      completed += 1;
      const percent = set.bw_percent_override ?? snapshot.bodyweight_percent;
      try {
        const values = calculateSetLoad({
          reps: set.reps,
          weightKg: set.weight_kg,
          loadType: snapshot.load_type,
          sideCount: snapshot.side_count,
          bodyweightKg: content.bodyweight_kg,
          bodyweightPercent: percent,
        });
        if (values.volume_kg_reps === null) unknown += 1;
        else {
          known += values.volume_kg_reps;
          knownCount += 1;
        }
      } catch {
        unknown += 1;
      }
    }
  }
  return {
    knownVolume: knownCount === 0 && unknown > 0 ? null : known,
    unknownSetCount: unknown,
    completedSetCount: completed,
  };
}

export function setError(
  content: EditableWorkoutContent,
  exercise: SaveExerciseInput,
  set: SaveSetInput,
): string | null {
  const snapshot =
    content.recorded_load_snapshots[exercise.id] ??
    content.provisional_load_snapshots[exercise.id];
  if (!snapshot) return 'Exercise load settings are unavailable.';
  const fields: Array<'reps' | 'weight_kg' | 'bw_percent_override' | 'rpe'> = [
    'reps',
    'weight_kg',
    'bw_percent_override',
    'rpe',
  ];
  if (
    fields.some((field) => {
      const raw = content.raw_fields[fieldKey(set.id, field)];
      return raw !== undefined && raw !== '' && strictInteger(raw) === null;
    })
  )
    return 'Use whole numbers only.';
  if (set.rpe !== null && (set.rpe < 1 || set.rpe > 10))
    return 'RPE must be from 1 to 10.';
  if (
    set.bw_percent_override !== null &&
    (snapshot.bodyweight_percent === null ||
      set.bw_percent_override < 1 ||
      set.bw_percent_override > 100)
  )
    return 'Bodyweight percentage must be from 1 to 100 for this exercise.';
  if (snapshot.load_type === 'bodyweight' && set.weight_kg !== null)
    return 'Bodyweight exercises do not use an external weight.';
  if (
    snapshot.load_type !== 'bodyweight' &&
    set.weight_kg !== null &&
    set.weight_kg < 0
  )
    return 'Weight must be zero or greater.';
  if (set.done && (set.reps === null || set.reps < 1))
    return 'A completed set needs at least one rep.';
  if (set.done && snapshot.load_type !== 'bodyweight' && set.weight_kg === null)
    return 'A completed weighted set needs a weight.';
  if (
    snapshot.load_type === 'split_weight' &&
    snapshot.side_count === 1 &&
    set.side === 'bilateral'
  )
    return 'Choose left or right for one-side sets.';
  if (
    (snapshot.load_type !== 'split_weight' || snapshot.side_count === 2) &&
    set.side !== 'bilateral'
  )
    return 'This set covers both sides.';
  return null;
}

export function contentError(content: EditableWorkoutContent): string | null {
  const bodyweightRaw = content.raw_fields['workout.bodyweight_kg'];
  if (
    bodyweightRaw !== undefined &&
    bodyweightRaw !== '' &&
    strictInteger(bodyweightRaw) === null
  )
    return 'Recorded bodyweight must be a whole number.';
  if (content.bodyweight_kg !== null && content.bodyweight_kg < 1)
    return 'Recorded bodyweight must be greater than zero.';
  if ((content.name?.length ?? 0) > 100 || (content.notes?.length ?? 0) > 2000)
    return 'Workout text is too long.';
  if (content.exercises.length > MAX_EXERCISES)
    return `A workout can contain at most ${MAX_EXERCISES} exercises.`;
  let setCount = 0;
  for (const exercise of content.exercises) {
    if (exercise.notes !== null && exercise.notes.length > 300)
      return 'Exercise notes are too long.';
    if (exercise.sets.length > MAX_SETS_PER_EXERCISE)
      return `An exercise can contain at most ${MAX_SETS_PER_EXERCISE} sets.`;
    setCount += exercise.sets.length;
    for (const set of exercise.sets) {
      const error = setError(content, exercise, set);
      if (error !== null) return error;
    }
  }
  return setCount > MAX_SETS
    ? `A workout can contain at most ${MAX_SETS} sets.`
    : null;
}
