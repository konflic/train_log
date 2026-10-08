import type { Equipment, LoadType, MuscleGroup } from '../../api';

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
  core: 'Core',
  full_body: 'Full body',
  other: 'Other',
};

export const equipmentLabels: Record<Equipment, string> = {
  barbell: 'Barbell',
  dumbbell: 'Dumbbell',
  kettlebell: 'Kettlebell',
  machine: 'Machine',
  cable: 'Cable',
  bodyweight: 'Bodyweight',
  band: 'Band',
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
export const equipmentValues = Object.keys(equipmentLabels) as Equipment[];
export const loadTypeValues = Object.keys(loadTypeLabels) as LoadType[];

export function isMuscleGroup(value: string): value is MuscleGroup {
  return Object.hasOwn(muscleGroupLabels, value);
}

export function isEquipment(value: string): value is Equipment {
  return Object.hasOwn(equipmentLabels, value);
}
