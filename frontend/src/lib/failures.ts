/**
 * Shared failure helpers: abort/unauthorized recognition, safe user-facing
 * messages, and problem-to-form mapping (Stage 10). Messages never echo
 * submitted credentials or payload contents.
 */

import { ApiNetworkError, ApiRequestError } from '../api';

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.problem.status === 401;
}

/** A safe one-line message for read failures (panels, lists). */
export function describeFailure(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const { problem } = error;
    return problem.detail !== '' ? problem.detail : problem.title;
  }
  if (error instanceof ApiNetworkError) {
    return 'Cannot reach the server. Check your connection and try again.';
  }
  return 'Something went wrong. Please try again.';
}

export interface FormFailure {
  /** Form-level message, announced with role="alert". */
  form: string | null;
  /** Field messages keyed by input name (problem field paths without `body.`). */
  fields: Record<string, string>;
}

/**
 * Map a mutation failure onto a form: 422 validation entries by field path
 * where possible, a form-level fallback for conflicts, throttling (with the
 * preserved Retry-After), network, and server failures.
 */
export function mapFailureToForm(error: unknown): FormFailure {
  if (error instanceof ApiRequestError) {
    const { problem } = error;
    if (problem.status === 422 && problem.validationErrors.length > 0) {
      const fields: Record<string, string> = {};
      const unmapped: string[] = [];
      for (const entry of problem.validationErrors) {
        const name = entry.field.replace(/^body\./, '');
        if (name !== entry.field && name !== '') {
          fields[name] ??= entry.message;
        } else {
          // Cross-field/model-level entries carry no usable input name.
          unmapped.push(entry.message);
        }
      }
      return { form: unmapped.length > 0 ? unmapped.join(' ') : null, fields };
    }
    if (problem.status === 429) {
      const suffix =
        problem.retryAfterSeconds !== null
          ? ` Try again in ${problem.retryAfterSeconds} seconds.`
          : ' Try again later.';
      return { form: `Too many attempts.${suffix}`, fields: {} };
    }
  }
  return { form: describeFailure(error), fields: {} };
}
