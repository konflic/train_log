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

export const MAX_EXERCISES = 25;
export const MAX_SETS_PER_EXERCISE = 20;
export const MAX_SETS = 250;
const CATALOG_ISSUE_PREFIX = 'catalog-issue.';

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

export function catalogIssueKey(exerciseId: string): string {
  return `${CATALOG_ISSUE_PREFIX}${exerciseId}`;
}

export function catalogIssue(
  content: EditableWorkoutContent,
  exerciseId: string,
): string | null {
  return content.raw_fields[catalogIssueKey(exerciseId)] ?? null;
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

export function copyDraftToNewWorkout(
  source: WorkoutDraft,
  catalog: ReadonlyMap<string, Exercise | null>,
  startedAt: string,
): WorkoutDraft {
  const detail: WorkoutDetail = {
    id: source.workout_id,
    name: source.content.name,
    started_at: source.started_at,
    ended_at: source.content.ended_at,
    notes: source.content.notes,
    bodyweight_kg: source.content.bodyweight_kg,
    revision: source.base_revision,
    last_save_id: null,
    exercises: source.content.exercises.map((exercise, orderIndex) => {
      const snapshot =
        source.content.recorded_load_snapshots[exercise.id] ??
        source.content.provisional_load_snapshots[exercise.id];
      if (!snapshot) throw new Error('Exercise load settings are unavailable.');
      return {
        ...exercise,
        order_index: orderIndex,
        ...snapshot,
        sets: exercise.sets.map((set, setIndex) => ({
          ...set,
          set_index: setIndex,
        })),
        previous_performance: null,
      };
    }),
  };
  const draft = copiedDraft(source.account_id, detail, catalog, startedAt);
  draft.content.bodyweight_kg = source.content.bodyweight_kg;
  const bodyweightRaw = source.content.raw_fields['workout.bodyweight_kg'];
  if (bodyweightRaw !== undefined)
    draft.content.raw_fields['workout.bodyweight_kg'] = bodyweightRaw;
  for (const [
    exerciseIndex,
    sourceExercise,
  ] of source.content.exercises.entries()) {
    const copiedExercise = draft.content.exercises[exerciseIndex];
    for (const [setIndex, sourceSet] of sourceExercise.sets.entries()) {
      const copiedSet = copiedExercise.sets[setIndex];
      for (const field of ['reps', 'weight_kg', 'bw_percent_override', 'rpe']) {
        const raw = source.content.raw_fields[fieldKey(sourceSet.id, field)];
        if (raw !== undefined)
          draft.content.raw_fields[fieldKey(copiedSet.id, field)] = raw;
      }
    }
  }
  return draft;
}

function copiedDraft(
  accountId: string,
  source: WorkoutDetail,
  catalog: ReadonlyMap<string, Exercise | null>,
  startedAt: string,
): WorkoutDraft {
  const workoutId = createDraftId();
  const draftId = createDraftId();
  const provisional: Record<string, LoadSnapshot> = {};
  const rawFields: Record<string, string> = {};
  const exercises = source.exercises.map((sourceExercise) => {
    const id = createDraftId();
    const current = catalog.get(sourceExercise.catalog_id) ?? null;
    const snapshot = current
      ? snapshotFor(current)
      : {
          load_type: sourceExercise.load_type,
          bodyweight_percent: sourceExercise.bodyweight_percent,
          side_count: sourceExercise.side_count,
        };
    provisional[id] = snapshot;
    if (!current) {
      rawFields[catalogIssueKey(id)] =
        'This exercise is no longer available. Remove or replace it.';
    }
    const sets = sourceExercise.sets.map((set) => ({
      id: createDraftId(),
      reps: set.reps,
      weight_kg: set.weight_kg,
      bw_percent_override: set.bw_percent_override,
      rpe: set.rpe,
      side: set.side,
      done: set.done,
    }));
    return {
      id,
      catalog_id: sourceExercise.catalog_id,
      notes: sourceExercise.notes,
      sets: sets.length > 0 ? sets : [emptySet(snapshot)],
    };
  });
  return {
    account_id: accountId,
    workout_id: workoutId,
    draft_id: draftId,
    base_detail_id: workoutId,
    base_revision: 0,
    started_at: startedAt,
    content: {
      name: source.name,
      notes: source.notes,
      bodyweight_kg: source.bodyweight_kg,
      ended_at: null,
      exercises,
      raw_fields: rawFields,
      recorded_load_snapshots: {},
      provisional_load_snapshots: provisional,
    },
    change_number: 1,
    acknowledged_change_number: 0,
    created_at: startedAt,
    updated_at: startedAt,
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

export interface ExerciseProgress {
  completedSets: number;
  totalSets: number;
  complete: boolean;
}

export interface CompletionProgress {
  completedSets: number;
  totalSets: number;
  percent: number;
}

export function exerciseProgress(
  exercise: SaveExerciseInput,
): ExerciseProgress {
  const completedSets = exercise.sets.filter((set) => set.done).length;
  return {
    completedSets,
    totalSets: exercise.sets.length,
    complete:
      exercise.sets.length > 0 && completedSets === exercise.sets.length,
  };
}

export function completionProgress(
  content: EditableWorkoutContent,
): CompletionProgress {
  const totalSets = content.exercises.reduce(
    (total, exercise) => total + exercise.sets.length,
    0,
  );
  const completedSets = content.exercises.reduce(
    (total, exercise) => total + exercise.sets.filter((set) => set.done).length,
    0,
  );
  return {
    completedSets,
    totalSets,
    percent:
      totalSets === 0 ? 0 : Math.round((completedSets / totalSets) * 100),
  };
}

/**
 * Why this content may not be finished yet, or `null` when it may. Finishing is
 * an explicit user decision, so an empty workout and any set the user neither
 * completed nor removed both block it while remaining valid to save.
 */
export function finishBlocker(content: EditableWorkoutContent): string | null {
  if (content.exercises.length === 0)
    return 'Add at least one exercise to finish this workout.';
  if (content.exercises.some((exercise) => exercise.sets.length === 0))
    return 'Every exercise needs at least one set. Add a set or remove the exercise.';
  const completion = completionProgress(content);
  const remaining = completion.totalSets - completion.completedSets;
  if (remaining > 0)
    return `Finish or remove the ${remaining} incomplete ${remaining === 1 ? 'set' : 'sets'} before finishing this workout.`;
  return null;
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
  const catalogIssueEntry = Object.entries(content.raw_fields).find(([key]) =>
    key.startsWith(CATALOG_ISSUE_PREFIX),
  );
  if (catalogIssueEntry) return catalogIssueEntry[1];
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
