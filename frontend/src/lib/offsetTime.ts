/**
 * Fixed-offset calendar and time helpers (PLAN.md §4, §7; Stage 10).
 *
 * All operations are date-only integer/calendar math on UTC epoch values and
 * the profile's fixed `utc_offset_minutes`; nothing depends on the browser's
 * local timezone. Civil-date conversions use the proleptic Gregorian
 * days-from-civil algorithm (Howard Hinnant), which is exact for the whole
 * supported range with plain integer arithmetic.
 */

export interface CivilDate {
  year: number;
  month: number;
  day: number;
}

export const MINUTES_PER_DAY = 1440;

function mod(a: number, b: number): number {
  return ((a % b) + b) % b;
}

function pad(value: number, width: number): string {
  return String(Math.abs(value)).padStart(width, '0');
}

/** Days since 1970-01-01 for a proleptic Gregorian civil date. */
export function daysFromCivil(
  year: number,
  month: number,
  day: number,
): number {
  const y = year - (month <= 2 ? 1 : 0);
  const era = Math.floor(y / 400);
  const yearOfEra = y - era * 400;
  const dayOfYear =
    Math.floor((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5) + day - 1;
  const dayOfEra =
    yearOfEra * 365 +
    Math.floor(yearOfEra / 4) -
    Math.floor(yearOfEra / 100) +
    dayOfYear;
  return era * 146097 + dayOfEra - 719468;
}

/** Inverse of `daysFromCivil`. */
export function civilFromDays(days: number): CivilDate {
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const dayOfEra = z - era * 146097;
  const yearOfEra = Math.floor(
    (dayOfEra -
      Math.floor(dayOfEra / 1460) +
      Math.floor(dayOfEra / 36524) -
      Math.floor(dayOfEra / 146096)) /
      365,
  );
  const y = yearOfEra + era * 400;
  const dayOfYear =
    dayOfEra -
    (365 * yearOfEra + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100));
  const shiftedMonth = Math.floor((5 * dayOfYear + 2) / 153);
  const day = dayOfYear - Math.floor((153 * shiftedMonth + 2) / 5) + 1;
  const month = shiftedMonth + (shiftedMonth < 10 ? 3 : -9);
  return { year: y + (month <= 2 ? 1 : 0), month, day };
}

/** The caller's local calendar date for an instant at a fixed UTC offset. */
export function localDateAt(
  epochMs: number,
  utcOffsetMinutes: number,
): CivilDate {
  const totalMinutes = Math.floor(epochMs / 60_000) + utcOffsetMinutes;
  return civilFromDays(Math.floor(totalMinutes / MINUTES_PER_DAY));
}

/** Canonical `YYYY-MM-DD` text for a civil date. */
export function isoDate(date: CivilDate): string {
  return `${pad(date.year, 4)}-${pad(date.month, 2)}-${pad(date.day, 2)}`;
}

export interface WeekBounds {
  /** Inclusive Monday of the local week, `YYYY-MM-DD`. */
  monday: string;
  /** Inclusive Sunday of the local week, `YYYY-MM-DD`. */
  sunday: string;
}

/**
 * The caller's current local Monday-through-Sunday week for an instant. The
 * API treats both bounds as inclusive local dates.
 */
export function weekBounds(
  epochMs: number,
  utcOffsetMinutes: number,
): WeekBounds {
  const today = localDateAt(epochMs, utcOffsetMinutes);
  const days = daysFromCivil(today.year, today.month, today.day);
  // 1970-01-01 (day 0) was a Thursday; ISO weekdays run Monday=1..Sunday=7.
  const isoWeekday = mod(days + 3, 7) + 1;
  const monday = days - (isoWeekday - 1);
  return {
    monday: isoDate(civilFromDays(monday)),
    sunday: isoDate(civilFromDays(monday + 6)),
  };
}

const TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

/**
 * Render a canonical backend UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) at the
 * profile's fixed offset as `YYYY-MM-DD HH:MM`. Returns `null` for input the
 * backend contract does not produce rather than guessing a local format.
 */
export function formatTimestampAtOffset(
  timestamp: string,
  utcOffsetMinutes: number,
): string | null {
  const match = TIMESTAMP_PATTERN.exec(timestamp);
  if (match === null) {
    return null;
  }
  const [, year, month, day, hour, minute, second] = match;
  const totalMinutes =
    daysFromCivil(Number(year), Number(month), Number(day)) * MINUTES_PER_DAY +
    Number(hour) * 60 +
    Number(minute) +
    utcOffsetMinutes;
  const seconds = Number(second);
  const date = civilFromDays(Math.floor(totalMinutes / MINUTES_PER_DAY));
  const minuteOfDay = mod(totalMinutes, MINUTES_PER_DAY);
  return `${isoDate(date)} ${pad(Math.floor(minuteOfDay / 60), 2)}:${pad(minuteOfDay % 60, 2)}:${pad(seconds, 2)}`;
}

/** Human `UTC±H:MM` label for a fixed offset. */
export function formatUtcOffset(utcOffsetMinutes: number): string {
  const sign = utcOffsetMinutes < 0 ? '-' : '+';
  const absolute = Math.abs(utcOffsetMinutes);
  const hours = Math.floor(absolute / 60);
  const minutes = absolute % 60;
  return minutes === 0
    ? `UTC${sign}${hours}`
    : `UTC${sign}${hours}:${pad(minutes, 2)}`;
}
