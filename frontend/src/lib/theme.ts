/**
 * Theme resolution and explicit preference writes (PLAN.md §2, Stage 9).
 *
 * The only themes are `light` and `dark`, applied as one class on the
 * document root. localStorage stores only an explicit user choice; the first
 * visit falls back to the system dark preference, then to light. The inline
 * bootstrap in index.html applies the choice before first paint and must keep
 * its storage key and values synchronized with this module.
 */

export type Theme = 'light' | 'dark';

/** Storage key shared with the pre-paint bootstrap in index.html. */
export const THEME_STORAGE_KEY = 'basefit.theme';

export function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark';
}

export interface ThemeResolution {
  /** The theme to show for this page. */
  theme: Theme;
  /** True when the theme came from a saved explicit user choice. */
  explicit: boolean;
  /** False when localStorage could not be read (blocked/private mode). */
  storageReadable: boolean;
}

function readStoredTheme(): { theme: Theme | null; storageReadable: boolean } {
  try {
    const saved: unknown = localStorage.getItem(THEME_STORAGE_KEY);
    // Any invalid stored value is ignored, never migrated or rewritten here.
    return { theme: isTheme(saved) ? saved : null, storageReadable: true };
  } catch {
    return { theme: null, storageReadable: false };
  }
}

function systemPrefersDark(): boolean {
  try {
    if (typeof globalThis.matchMedia !== 'function') {
      return false;
    }
    return (
      globalThis.matchMedia('(prefers-color-scheme: dark)').matches === true
    );
  } catch {
    return false;
  }
}

/** Resolve the theme for this page: explicit choice, then system, then light. */
export function resolveTheme(): ThemeResolution {
  const stored = readStoredTheme();
  if (stored.theme !== null) {
    return {
      theme: stored.theme,
      explicit: true,
      storageReadable: stored.storageReadable,
    };
  }
  return {
    theme: systemPrefersDark() ? 'dark' : 'light',
    explicit: false,
    storageReadable: stored.storageReadable,
  };
}

/** Replace the root theme class and update `color-scheme` immediately. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.remove(theme === 'dark' ? 'light' : 'dark');
  root.classList.add(theme);
  root.style.colorScheme = theme;
}

/** Resolve and apply the theme; safe to call after the inline bootstrap. */
export function initializeTheme(): ThemeResolution {
  const resolution = resolveTheme();
  applyTheme(resolution.theme);
  return resolution;
}

export interface ThemePreferenceUpdate {
  theme: Theme;
  /** False when the choice could not be persisted (blocked storage). */
  persisted: boolean;
}

/**
 * Apply an explicit user choice and persist it. A blocked preference store
 * never throws: the choice applies for this page and `persisted` reports the
 * failed persistence so callers can surface it.
 */
export function setPreferredTheme(theme: Theme): ThemePreferenceUpdate {
  applyTheme(theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    return { theme, persisted: true };
  } catch {
    return { theme, persisted: false };
  }
}
