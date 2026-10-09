/**
 * Small, dependency-free localization boundary. Add a locale by extending
 * `Locale`, adding its full catalog, and exposing it in future Settings UI.
 */
export type Locale = 'en';

export const DEFAULT_LOCALE: Locale = 'en';
export const LOCALE_STORAGE_KEY = 'basefit.locale';

const en = {
  'relative.justNow': 'just now',
  'relative.minute': '{{count}} min ago',
  'relative.hour': '{{count}} hr ago',
  'relative.hours': '{{count}} hrs ago',
  'relative.day': '{{count}} day ago',
  'relative.days': '{{count}} days ago',
  'relative.month': '{{count}} month ago',
  'relative.months': '{{count}} months ago',
  'relative.year': '{{count}} yr ago',
  'relative.years': '{{count}} yrs ago',
} as const;

export type TranslationKey = keyof typeof en;
export type TranslationValues = Record<string, string | number>;
export type LocaleCatalog = Record<TranslationKey, string>;

const catalogs: Record<Locale, LocaleCatalog> = { en };
let activeLocale: Locale = DEFAULT_LOCALE;

export function isLocale(value: unknown): value is Locale {
  return value === 'en';
}

export function locale(): Locale {
  return activeLocale;
}

export function setLocale(next: Locale): void {
  activeLocale = next;
  if (typeof document !== 'undefined') document.documentElement.lang = next;
}

export function initializeLocale(): Locale {
  try {
    const stored: unknown = localStorage.getItem(LOCALE_STORAGE_KEY);
    setLocale(isLocale(stored) ? stored : DEFAULT_LOCALE);
  } catch {
    setLocale(DEFAULT_LOCALE);
  }
  return activeLocale;
}

export function setPreferredLocale(next: Locale): boolean {
  setLocale(next);
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, next);
    return true;
  } catch {
    return false;
  }
}

export function t(key: TranslationKey, values: TranslationValues = {}): string {
  return catalogs[activeLocale][key].replace(/{{(\w+)}}/g, (_, name: string) =>
    String(values[name] ?? `{{${name}}}`),
  );
}
