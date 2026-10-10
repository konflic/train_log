/**
 * Display helpers for the per-exercise statistics (exercise information
 * screen). Volume completeness semantics mirror PLAN.md §7: a `null` volume
 * is missing data ("Unknown"), a partial sum is a known lower bound ("At
 * least N kg·reps"), and a known zero stays visibly zero. Dates use the
 * profile's fixed UTC offset, never the browser timezone.
 */

import type { ExerciseStatsSession } from '../../api';
import { isoDate, localDateAt } from '../../lib/offsetTime';

/** The session's calendar date at the user's fixed UTC offset. */
export function sessionDate(
  session: ExerciseStatsSession,
  utcOffsetMinutes: number,
): string {
  const milliseconds = Date.parse(session.started_at);
  if (!Number.isFinite(milliseconds)) return session.started_at;
  return isoDate(localDateAt(milliseconds, utcOffsetMinutes));
}

/** Honest volume text for one aggregate (lifetime or session level). */
export function volumeLabel(
  volume: number | null,
  volumeComplete: boolean,
): string {
  if (volume === null) return 'Unknown';
  if (!volumeComplete) return `At least ${volume} kg·reps`;
  return `${volume} kg·reps`;
}
