import type { LoadType } from '../../api';

/**
 * Handwritten catalog form checks for immediate required/range/cross-field
 * feedback (PLAN.md §2: no validation library). The backend remains
 * authoritative for duplicate names, bodyweight percentage rules, and
 * split-weight side counts.
 */

export interface ExerciseDraft {
  name: string;
  loadType: LoadType;
  /** Raw percent input text; stays text so fractions are rejected, not coerced. */
  percentText: string;
  sideCount: number;
  maxNameLength: number;
}

const PERCENT_PATTERN = /^\d+$/;

export function validateExerciseDraft(
  draft: ExerciseDraft,
): Record<string, string> {
  const errors: Record<string, string> = {};

  const trimmedName = draft.name.trim();
  if (trimmedName === '') {
    errors.name = 'Name is required';
  } else if ([...trimmedName].length > draft.maxNameLength) {
    errors.name = `Name must be at most ${draft.maxNameLength} characters`;
  }

  const trimmedPercent = draft.percentText.trim();
  if (trimmedPercent !== '') {
    if (!PERCENT_PATTERN.test(trimmedPercent)) {
      errors.bodyweight_percent =
        'Percentage must be a whole number from 1 to 100';
    } else {
      const percent = Number.parseInt(trimmedPercent, 10);
      if (!Number.isSafeInteger(percent) || percent < 1 || percent > 100) {
        errors.bodyweight_percent = 'Percentage must be between 1 and 100';
      }
    }
  } else if (draft.loadType === 'bodyweight') {
    errors.bodyweight_percent = 'Bodyweight exercises require a percentage';
  }

  if (
    !Number.isSafeInteger(draft.sideCount) ||
    draft.sideCount < 1 ||
    draft.sideCount > 2
  ) {
    errors.side_count = 'Sides must be 1 or 2';
  } else if (draft.loadType !== 'split_weight' && draft.sideCount !== 1) {
    errors.side_count = 'Only split-weight exercises can have two sides';
  }

  return errors;
}
