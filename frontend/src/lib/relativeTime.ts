const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const MONTH_MS = 30 * DAY_MS;
const YEAR_MS = 365 * DAY_MS;

/** Render an ISO timestamp as a compact, user-facing elapsed time. */
export function formatRelativeTime(
  timestamp: string,
  now = Date.now(),
): string | null {
  const then = Date.parse(timestamp);
  if (!Number.isFinite(then) || !Number.isFinite(now)) return null;

  const elapsed = Math.max(0, now - then);
  if (elapsed < MINUTE_MS) return t('relative.justNow');

  if (elapsed < HOUR_MS)
    return t('relative.minute', { count: Math.floor(elapsed / MINUTE_MS) });
  if (elapsed < DAY_MS) {
    const hours = Math.floor(elapsed / HOUR_MS);
    return t(hours === 1 ? 'relative.hour' : 'relative.hours', {
      count: hours,
    });
  }
  if (elapsed < MONTH_MS) {
    const days = Math.floor(elapsed / DAY_MS);
    return t(days === 1 ? 'relative.day' : 'relative.days', { count: days });
  }
  if (elapsed < YEAR_MS) {
    const months = Math.floor(elapsed / MONTH_MS);
    return t(months === 1 ? 'relative.month' : 'relative.months', {
      count: months,
    });
  }
  const years = Math.floor(elapsed / YEAR_MS);
  return t(years === 1 ? 'relative.year' : 'relative.years', { count: years });
}
import { t } from './i18n';
