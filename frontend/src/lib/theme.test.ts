import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  THEME_STORAGE_KEY,
  applyTheme,
  initializeTheme,
  isTheme,
  resolveTheme,
  setPreferredTheme,
} from './theme';

function stubMatchMedia(prefersDark: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: prefersDark })),
  );
}

function stubBrokenMatchMedia(): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => {
      throw new Error('media queries unavailable');
    }),
  );
}

function stubBlockedStorage(): void {
  vi.stubGlobal('localStorage', {
    getItem: () => {
      throw new Error('storage blocked');
    },
    setItem: () => {
      throw new Error('storage blocked');
    },
  });
}

const rootClasses = (): string[] =>
  Array.from(document.documentElement.classList).filter(
    (name) => name === 'light' || name === 'dark',
  );

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = '';
  document.documentElement.style.colorScheme = '';
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resolveTheme', () => {
  it('uses the saved explicit light choice even when the system prefers dark', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light');
    stubMatchMedia(true);
    expect(resolveTheme()).toEqual({
      theme: 'light',
      explicit: true,
      storageReadable: true,
    });
  });

  it('uses the saved explicit dark choice', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    stubMatchMedia(false);
    expect(resolveTheme()).toEqual({
      theme: 'dark',
      explicit: true,
      storageReadable: true,
    });
  });

  it('ignores invalid stored values and falls back to the system preference', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'neon');
    stubMatchMedia(true);
    expect(resolveTheme()).toEqual({
      theme: 'dark',
      explicit: false,
      storageReadable: true,
    });
  });

  it('falls back to light when the system does not prefer dark', () => {
    stubMatchMedia(false);
    expect(resolveTheme()).toEqual({
      theme: 'light',
      explicit: false,
      storageReadable: true,
    });
  });

  it('falls back to light when the media-query API is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(resolveTheme().theme).toBe('light');
    stubBrokenMatchMedia();
    expect(resolveTheme().theme).toBe('light');
  });

  it('survives blocked storage and reports it', () => {
    stubBlockedStorage();
    stubMatchMedia(true);
    expect(resolveTheme()).toEqual({
      theme: 'dark',
      explicit: false,
      storageReadable: false,
    });
  });
});

describe('applyTheme', () => {
  it('replaces the root class instead of accumulating and sets color-scheme', () => {
    applyTheme('light');
    expect(rootClasses()).toEqual(['light']);
    expect(document.documentElement.style.colorScheme).toBe('light');

    applyTheme('dark');
    expect(rootClasses()).toEqual(['dark']);
    expect(document.documentElement.style.colorScheme).toBe('dark');

    applyTheme('dark');
    expect(rootClasses()).toEqual(['dark']);
  });

  it('does not remove unrelated root classes', () => {
    document.documentElement.classList.add('debug');
    applyTheme('dark');
    expect(document.documentElement.classList.contains('debug')).toBe(true);
  });
});

describe('initializeTheme', () => {
  it('resolves and applies the theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    const resolution = initializeTheme();
    expect(resolution.theme).toBe('dark');
    expect(rootClasses()).toEqual(['dark']);
  });
});

describe('setPreferredTheme', () => {
  it('applies and persists the explicit choice', () => {
    const result = setPreferredTheme('dark');
    expect(result).toEqual({ theme: 'dark', persisted: true });
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(rootClasses()).toEqual(['dark']);
  });

  it('reports failed persistence without preventing the page theme', () => {
    stubBlockedStorage();
    const result = setPreferredTheme('dark');
    expect(result).toEqual({ theme: 'dark', persisted: false });
    expect(rootClasses()).toEqual(['dark']);
  });
});

describe('isTheme', () => {
  it('accepts only the two supported values', () => {
    expect(isTheme('light')).toBe(true);
    expect(isTheme('dark')).toBe(true);
    expect(isTheme('neon')).toBe(false);
    expect(isTheme(null)).toBe(false);
    expect(isTheme(undefined)).toBe(false);
  });
});
