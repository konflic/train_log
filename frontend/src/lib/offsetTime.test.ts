// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  civilFromDays,
  daysFromCivil,
  formatTimestampAtOffset,
  formatUtcOffset,
  isoDate,
  localDateAt,
  monthBounds,
  weekBounds,
} from './offsetTime';

describe('civil date conversions', () => {
  it('anchors at the Unix epoch', () => {
    expect(daysFromCivil(1970, 1, 1)).toBe(0);
    expect(civilFromDays(0)).toEqual({ year: 1970, month: 1, day: 1 });
  });

  it('round-trips a range of dates including leap days and pre-epoch', () => {
    const samples: Array<[number, number, number]> = [
      [1970, 1, 1],
      [1969, 7, 20],
      [1969, 12, 31],
      [2000, 2, 29],
      [2026, 10, 8],
      [2026, 12, 31],
      [2027, 1, 1],
      [1900, 3, 1],
      [9998, 12, 31],
    ];
    for (const [year, month, day] of samples) {
      expect(civilFromDays(daysFromCivil(year, month, day))).toEqual({
        year,
        month,
        day,
      });
    }
  });

  it('formats canonical ISO text', () => {
    expect(isoDate({ year: 2026, month: 10, day: 8 })).toBe('2026-10-08');
    expect(isoDate({ year: 999, month: 1, day: 2 })).toBe('0999-01-02');
  });
});

describe('localDateAt', () => {
  it('uses only the fixed offset, never a browser timezone', () => {
    const instant = Date.UTC(2026, 9, 8, 23, 30);
    expect(localDateAt(instant, 0)).toEqual({ year: 2026, month: 10, day: 8 });
    expect(localDateAt(instant, 60)).toEqual({ year: 2026, month: 10, day: 9 });
    expect(localDateAt(instant, -1440)).toEqual({
      year: 2026,
      month: 10,
      day: 7,
    });
  });

  it('handles pre-epoch instants', () => {
    const instant = Date.UTC(1970, 0, 1, 0, 30);
    expect(localDateAt(instant, -60)).toEqual({
      year: 1969,
      month: 12,
      day: 31,
    });
  });
});

describe('weekBounds', () => {
  it('returns Monday through Sunday for a mid-week Thursday', () => {
    // 2026-10-08 is a Thursday.
    expect(weekBounds(Date.UTC(2026, 9, 8, 12, 0), 0)).toEqual({
      monday: '2026-10-05',
      sunday: '2026-10-11',
    });
  });

  it('handles Sunday and Monday edges', () => {
    // 2026-10-04 is a Sunday, 2026-10-05 a Monday.
    expect(weekBounds(Date.UTC(2026, 9, 4, 12, 0), 0)).toEqual({
      monday: '2026-09-28',
      sunday: '2026-10-04',
    });
    expect(weekBounds(Date.UTC(2026, 9, 5, 0, 0), 0)).toEqual({
      monday: '2026-10-05',
      sunday: '2026-10-11',
    });
  });

  it('shifts the week when the offset moves the local date across Sunday midnight', () => {
    // 2026-10-04T23:30Z is Sunday in UTC; at UTC+1 it is already Monday.
    const instant = Date.UTC(2026, 9, 4, 23, 30);
    expect(weekBounds(instant, 60)).toEqual({
      monday: '2026-10-05',
      sunday: '2026-10-11',
    });
    expect(weekBounds(instant, 0)).toEqual({
      monday: '2026-09-28',
      sunday: '2026-10-04',
    });
    // At UTC-10 the same instant is still Sunday afternoon.
    expect(weekBounds(instant, -600)).toEqual({
      monday: '2026-09-28',
      sunday: '2026-10-04',
    });
  });

  it('works across the epoch boundary', () => {
    // 1969-12-31 (Wednesday) at UTC-1 from 1970-01-01T00:30Z.
    expect(weekBounds(Date.UTC(1970, 0, 1, 0, 30), -60)).toEqual({
      monday: '1969-12-29',
      sunday: '1970-01-04',
    });
  });
});

describe('monthBounds', () => {
  it('returns the first and last local day of a mid-month instant', () => {
    expect(monthBounds(Date.UTC(2026, 9, 8, 12, 0), 0)).toEqual({
      first: '2026-10-01',
      last: '2026-10-31',
    });
  });

  it('derives short months and leap Februaries from the next month start', () => {
    expect(monthBounds(Date.UTC(2026, 1, 10, 12, 0), 0)).toEqual({
      first: '2026-02-01',
      last: '2026-02-28',
    });
    expect(monthBounds(Date.UTC(2028, 1, 10, 12, 0), 0)).toEqual({
      first: '2028-02-01',
      last: '2028-02-29',
    });
    expect(monthBounds(Date.UTC(2026, 3, 10, 12, 0), 0)).toEqual({
      first: '2026-04-01',
      last: '2026-04-30',
    });
  });

  it('wraps the year in December and January', () => {
    expect(monthBounds(Date.UTC(2026, 11, 31, 23, 0), 0)).toEqual({
      first: '2026-12-01',
      last: '2026-12-31',
    });
    expect(monthBounds(Date.UTC(2027, 0, 1, 0, 30), 0)).toEqual({
      first: '2027-01-01',
      last: '2027-01-31',
    });
  });

  it('shifts the month when the offset moves the local date across midnight', () => {
    // 2026-09-30T23:30Z is still September in UTC; at UTC+1 it is October.
    const instant = Date.UTC(2026, 8, 30, 23, 30);
    expect(monthBounds(instant, 60)).toEqual({
      first: '2026-10-01',
      last: '2026-10-31',
    });
    expect(monthBounds(instant, 0)).toEqual({
      first: '2026-09-01',
      last: '2026-09-30',
    });
  });
});

describe('formatTimestampAtOffset', () => {
  it('renders canonical UTC timestamps at the fixed offset', () => {
    expect(formatTimestampAtOffset('2026-10-08T23:30:00Z', 60)).toBe(
      '2026-10-09 00:30:00',
    );
    expect(formatTimestampAtOffset('2026-10-08T23:30:00Z', 0)).toBe(
      '2026-10-08 23:30:00',
    );
    expect(formatTimestampAtOffset('2026-10-08T23:30:00Z', -1440)).toBe(
      '2026-10-07 23:30:00',
    );
    expect(formatTimestampAtOffset('1970-01-01T00:30:00Z', -60)).toBe(
      '1969-12-31 23:30:00',
    );
  });

  it('returns null for input outside the backend contract', () => {
    expect(formatTimestampAtOffset('2026-10-08T23:30:00+02:00', 0)).toBeNull();
    expect(formatTimestampAtOffset('not-a-timestamp', 0)).toBeNull();
    expect(formatTimestampAtOffset('2026-10-08 23:30:00', 0)).toBeNull();
  });
});

describe('formatUtcOffset', () => {
  it('formats whole hours and half hours', () => {
    expect(formatUtcOffset(0)).toBe('UTC+0');
    expect(formatUtcOffset(180)).toBe('UTC+3');
    expect(formatUtcOffset(-720)).toBe('UTC-12');
    expect(formatUtcOffset(330)).toBe('UTC+5:30');
    expect(formatUtcOffset(-45)).toBe('UTC-0:45');
  });
});
