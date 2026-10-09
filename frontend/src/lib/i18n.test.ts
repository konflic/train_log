import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  initializeLocale,
  isLocale,
  locale,
  setPreferredLocale,
  t,
} from './i18n';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  initializeLocale();
});

describe('localization foundation', () => {
  it('uses English by default and substitutes named values', () => {
    expect(initializeLocale()).toBe(DEFAULT_LOCALE);
    expect(t('relative.hour', { count: 1 })).toBe('1 hr ago');
  });

  it('persists a selected locale and applies it to the document', () => {
    expect(setPreferredLocale('en')).toBe(true);
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(locale()).toBe('en');
  });

  it('accepts only configured locales', () => {
    expect(isLocale('en')).toBe(true);
    expect(isLocale('ru')).toBe(false);
  });
});
