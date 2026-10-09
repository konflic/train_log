// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { formatRelativeTime } from './relativeTime';

describe('formatRelativeTime', () => {
  const now = Date.UTC(2026, 9, 9, 12, 0, 0);

  it('uses compact minute, hour, day, month, and year labels', () => {
    expect(formatRelativeTime('2026-10-09T11:50:00Z', now)).toBe('10 min ago');
    expect(formatRelativeTime('2026-10-09T07:00:00Z', now)).toBe('5 hrs ago');
    expect(formatRelativeTime('2026-10-08T12:00:00Z', now)).toBe('1 day ago');
    expect(formatRelativeTime('2026-10-07T12:00:00Z', now)).toBe('2 days ago');
    expect(formatRelativeTime('2026-08-10T12:00:00Z', now)).toBe(
      '2 months ago',
    );
    expect(formatRelativeTime('2024-10-09T12:00:00Z', now)).toBe('2 yrs ago');
  });

  it('uses just now for recent and future timestamps', () => {
    expect(formatRelativeTime('2026-10-09T11:59:30Z', now)).toBe('just now');
    expect(formatRelativeTime('2026-10-09T12:05:00Z', now)).toBe('just now');
  });

  it('rejects malformed timestamps', () => {
    expect(formatRelativeTime('not-a-timestamp', now)).toBeNull();
  });
});
