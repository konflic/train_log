// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  MAX_DISPLAY_NAME_LENGTH,
  MAX_EMAIL_LENGTH,
  MIN_PASSWORD_LENGTH,
  normalizeEmailInput,
  validateDisplayName,
  validateEmail,
  validatePassword,
} from './validation';

describe('normalizeEmailInput', () => {
  it('trims and lowercases', () => {
    expect(normalizeEmailInput('  User@Example.TEST ')).toBe(
      'user@example.test',
    );
  });
});

describe('validateEmail', () => {
  it('accepts ordinary addresses', () => {
    expect(validateEmail('user@example.test')).toBeNull();
    expect(validateEmail('  USER@sub.example.co.uk  ')).toBeNull();
  });

  it('rejects blank, malformed, and oversized values', () => {
    expect(validateEmail('')).toMatch(/required/i);
    expect(validateEmail('no-at-sign')).toMatch(/valid email/i);
    expect(validateEmail('@example.test')).toMatch(/valid email/i);
    expect(validateEmail('user@')).toMatch(/valid email/i);
    expect(validateEmail('a@b@c.test')).toMatch(/valid email/i);
    expect(validateEmail('user@domain')).toMatch(/valid email/i);
    expect(validateEmail('user@a..b.test')).toMatch(/valid email/i);
    expect(validateEmail('user@.example.test')).toMatch(/valid email/i);
    expect(validateEmail('user@example.test.')).toMatch(/valid email/i);
    expect(validateEmail('us er@example.test')).toMatch(/spaces/i);
    expect(
      validateEmail(
        `${'a'.repeat(MAX_EMAIL_LENGTH - 10)}@example.test`.padEnd(
          MAX_EMAIL_LENGTH + 1,
          'z',
        ),
      ),
    ).toMatch(/at most/i);
  });
});

describe('validatePassword', () => {
  it('enforces the backend length bounds', () => {
    expect(validatePassword('12345678')).toBeNull();
    expect(validatePassword('1234567')).toBe(
      `Password must be at least ${MIN_PASSWORD_LENGTH} characters`,
    );
    expect(validatePassword('x'.repeat(257))).toMatch(/at most/i);
  });
});

describe('validateDisplayName', () => {
  it('treats blank as not provided', () => {
    expect(validateDisplayName('')).toBeNull();
    expect(validateDisplayName('   ')).toBeNull();
    expect(validateDisplayName('Ada')).toBeNull();
  });

  it('bounds the length in codepoints', () => {
    expect(validateDisplayName('a'.repeat(MAX_DISPLAY_NAME_LENGTH))).toBeNull();
    expect(
      validateDisplayName('a'.repeat(MAX_DISPLAY_NAME_LENGTH + 1)),
    ).toMatch(/at most/i);
  });
});
