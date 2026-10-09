import type {
  Exercise,
  ExerciseNode,
  StoredSet,
  WorkoutDetail,
} from '../../api';
import { calculateSetLoad, floorDivide, type SetLoad } from '../../lib/numbers';

export interface DetailTotal {
  completedSetCount: number;
  knownVolume: number | null;
  unknownLoadSetCount: number;
  complete: boolean;
}

export function durationSeconds(detail: WorkoutDetail): number | null {
  if (detail.ended_at === null) return null;
  const started = Date.parse(detail.started_at);
  const ended = Date.parse(detail.ended_at);
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) {
    return null;
  }
  return Math.floor((ended - started) / 1000);
}

export function exerciseLabel(
  exercise: ExerciseNode,
  catalog: Map<string, Exercise>,
): string {
  return (
    catalog.get(exercise.catalog_id)?.name ?? `Exercise ${exercise.catalog_id}`
  );
}

export function setLoad(
  detail: WorkoutDetail,
  exercise: ExerciseNode,
  set: StoredSet,
): SetLoad {
  return calculateSetLoad({
    reps: set.reps,
    weightKg: set.weight_kg,
    loadType: exercise.load_type,
    sideCount: exercise.side_count,
    bodyweightKg: detail.bodyweight_kg,
    bodyweightPercent: set.bw_percent_override ?? exercise.bodyweight_percent,
  });
}

export function detailTotal(detail: WorkoutDetail): DetailTotal {
  let completedSetCount = 0;
  let unknownLoadSetCount = 0;
  let knownVolume = 0;
  for (const exercise of detail.exercises) {
    for (const set of exercise.sets) {
      if (!set.done) continue;
      completedSetCount += 1;
      const volume = setLoad(detail, exercise, set).volume_kg_reps;
      if (volume === null) unknownLoadSetCount += 1;
      else knownVolume += volume;
    }
  }
  return {
    completedSetCount,
    knownVolume: completedSetCount === unknownLoadSetCount ? null : knownVolume,
    unknownLoadSetCount,
    complete: unknownLoadSetCount === 0,
  };
}

export function percentageDelta(
  current: number | null,
  previous: number | null,
): number | null {
  if (current === null || previous === null || previous === 0) return null;
  return floorDivide((current - previous) * 100, previous);
}
