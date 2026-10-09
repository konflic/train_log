/**
 * Handwritten auth form checks for immediate feedback (PLAN.md §2: no form
 * framework). The backend stays authoritative; these only mirror the obvious
 * client-side constraints so a request is not sent for clearly invalid input.
 */

export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 256;
export const MAX_EMAIL_LENGTH = 254;
export const MAX_DISPLAY_NAME_LENGTH = 100;
export const MAX_AGE = 120;

export function normalizeEmailInput(value: string): string {
  return value.trim().toLowerCase();
}

/** Conservative shape check mirroring the backend normalization. */
export function validateEmail(value: string): string | null {
  const normalized = normalizeEmailInput(value);
  if (normalized === '') {
    return 'Email is required';
  }
  if (normalized.length > MAX_EMAIL_LENGTH) {
    return `Email must be at most ${MAX_EMAIL_LENGTH} characters`;
  }
  if (/\s/.test(normalized)) {
    return 'Email must not contain spaces';
  }
  const at = normalized.indexOf('@');
  const local = normalized.slice(0, at);
  const domain = at === -1 ? '' : normalized.slice(at + 1);
  if (at === -1 || local === '' || domain === '') {
    return 'Enter a valid email address';
  }
  if (domain.includes('@') || normalized.includes('..')) {
    return 'Enter a valid email address';
  }
  if (!domain.includes('.') || domain.startsWith('.') || domain.endsWith('.')) {
    return 'Enter a valid email address';
  }
  return null;
}

export function validatePassword(value: string): string | null {
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`;
  }
  if (value.length > MAX_PASSWORD_LENGTH) {
    return `Password must be at most ${MAX_PASSWORD_LENGTH} characters`;
  }
  return null;
}

/** Optional field: blank means "not provided"; non-blank must have content. */
export function validateDisplayName(value: string): string | null {
  if (value.trim() === '') {
    return null;
  }
  if ([...value.trim()].length > MAX_DISPLAY_NAME_LENGTH) {
    return `Display name must be at most ${MAX_DISPLAY_NAME_LENGTH} characters`;
  }
  return null;
}

function validateRequiredWholeNumber(
  value: string,
  label: string,
  maximum = Number.MAX_SAFE_INTEGER,
): string | null {
  if (value === '') return `${label} is required`;
  if (!/^[1-9]\d*$/.test(value))
    return `${label} must be a whole positive number`;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed > maximum)
    return `${label} must be at most ${maximum}`;
  return null;
}

export function validateInitialWeight(value: string): string | null {
  return validateRequiredWholeNumber(value, 'Initial weight');
}

export function validateAge(value: string): string | null {
  return validateRequiredWholeNumber(value, 'Age', MAX_AGE);
}

export function validateSex(value: string): string | null {
  return value === 'male' || value === 'female' ? null : 'Sex is required';
}
