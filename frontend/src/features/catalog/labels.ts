import type { LoadType, MuscleGroup } from '../../api';

/**
 * Human-readable labels for the server enum literals. The exact API literals
 * are preserved as keys; only display text is localized here.
 */

export const muscleGroupLabels: Record<MuscleGroup, string> = {
  chest: 'Chest',
  back: 'Back',
  legs: 'Legs',
  shoulders: 'Shoulders',
  arms: 'Arms',
  abs: 'Abs',
  full_body: 'Full body',
  other: 'Other',
};

export const loadTypeLabels: Record<LoadType, string> = {
  single_weight: 'Single weight',
  split_weight: 'Split weight (per side)',
  bodyweight: 'Bodyweight',
};

export const muscleGroupValues = Object.keys(
  muscleGroupLabels,
) as MuscleGroup[];
export const loadTypeValues = Object.keys(loadTypeLabels) as LoadType[];

export function isMuscleGroup(value: string): value is MuscleGroup {
  return Object.hasOwn(muscleGroupLabels, value);
}

/**
 * Coarse load label for compact exercise cards. The information screen keeps
 * the precise load semantics under "How weight is logged"; compact cards show
 * only the body part and this label. Cardio stays future work: it requires
 * the separately specified interval model, not a display-only literal.
 */
export function compactLoadLabel(loadType: LoadType): string {
  return loadType === 'bodyweight' ? 'Bodyweight' : 'Weighted';
}

/** Compact card summary, e.g. `Shoulders · Weighted`. */
export function compactExerciseSummary(entry: {
  muscle_group: MuscleGroup;
  load_type: LoadType;
}): string {
  return `${muscleGroupLabels[entry.muscle_group]} · ${compactLoadLabel(entry.load_type)}`;
}
