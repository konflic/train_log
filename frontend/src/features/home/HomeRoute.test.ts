import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { listWorkoutsMock, fetchStatsSummaryMock } = vi.hoisted(() => ({
  listWorkoutsMock: vi.fn(),
  fetchStatsSummaryMock: vi.fn(),
}));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    listWorkouts: listWorkoutsMock,
    fetchStatsSummary: fetchStatsSummaryMock,
  };
});

import {
  ApiNetworkError,
  ApiRequestError,
  type StatsSummary,
  type WorkoutPage,
} from '../../api';
import { monthBounds, weekBounds } from '../../lib/offsetTime';
import { session } from '../auth/session.svelte';
import HomeRoute from './HomeRoute.svelte';

const OFFSET = 180; // UTC+3, fixed profile offset

function emptyPage(): WorkoutPage {
  return { items: [], total: 0, page: 1, page_size: 3 };
}

function zeroSummary(overrides: Partial<StatsSummary> = {}): StatsSummary {
  return {
    workout_count: 0,
    completed_set_count: 0,
    training_day_count: 0,
    total_volume_kg_reps: 0,
    unknown_load_set_count: 0,
    volume_complete: true,
    muscle_group_frequency: [],
    current_week_streak: 0,
    ...overrides,
  };
}

function requestError(status: number, detail: string): ApiRequestError {
  return new ApiRequestError({
    status,
    code: 'error',
    title: 'Error',
    detail,
    requestId: null,
    retryAfterSeconds: null,
    validationErrors: [],
    currentRevision: null,
  });
}

beforeEach(() => {
  listWorkoutsMock.mockReset();
  fetchStatsSummaryMock.mockReset();
  listWorkoutsMock.mockResolvedValue(emptyPage());
  fetchStatsSummaryMock.mockResolvedValue(zeroSummary());
  session.status = 'authenticated';
  session.user = {
    id: 'u-1',
    email: 'user@example.test',
    display_name: 'Ada',
    bodyweight_default_kg: null,
    sex: null,
    age: null,
    utc_offset_minutes: OFFSET,
  };
  cleanup();
});

describe('HomeRoute reads', () => {
  it('issues the two bounded reads with profile-offset week bounds', async () => {
    render(HomeRoute);
    await waitFor(() => expect(fetchStatsSummaryMock).toHaveBeenCalled());

    const calls = listWorkoutsMock.mock.calls.map((call) => call[0]);
    expect(calls).toContainEqual({ status: 'finished', page: 1, pageSize: 3 });

    // Every read is abortable.
    for (const call of listWorkoutsMock.mock.calls) {
      expect(call[1]).toBeInstanceOf(AbortSignal);
    }

    const expected = weekBounds(Date.now(), OFFSET);
    expect(fetchStatsSummaryMock).toHaveBeenCalledWith(
      { date_from: expected.monday, date_to: expected.sunday },
      expect.any(AbortSignal),
    );
  });

  it('renders loading, then populated panels with relative times', async () => {
    // Relative labels are elapsed-time based, so the fixture must stay anchored
    // to the current instant rather than a fixed date.
    const startedAt = new Date(Date.now() - 3 * 60 * 60 * 1000)
      .toISOString()
      .replace('.000Z', 'Z');
    listWorkoutsMock.mockResolvedValue({
      items: [
        {
          id: 'w-done',
          name: 'Leg day',
          started_at: startedAt,
          ended_at: startedAt,
          bodyweight_kg: null,
          revision: 0,
        },
      ],
      total: 1,
      page: 1,
      page_size: 3,
    });
    render(HomeRoute);
    expect((await screen.findAllByRole('status')).length).toBeGreaterThan(0);

    expect(await screen.findByText('Leg day')).toBeDefined();
    expect(screen.getAllByText(/^Started \d+ hrs ago$/).length).toBe(1);
    expect(screen.getByText('Signed in as Ada')).toBeDefined();
  });

  it('renders empty states without a start-workout action', async () => {
    render(HomeRoute);
    await waitFor(() =>
      expect(screen.getByText(/No finished workouts yet/)).toBeDefined(),
    );
    expect(screen.getByText(/No finished workouts yet/)).toBeDefined();
    expect(
      screen
        .getByRole('link', { name: 'Manage training plans' })
        .getAttribute('href'),
    ).toBe('#/training-plans');
    expect(screen.queryByRole('link', { name: /start.*workout/i })).toBeNull();
  });

  it('isolates a failed panel and retries it without touching the others', async () => {
    listWorkoutsMock.mockRejectedValue(requestError(500, 'Server exploded'));
    render(HomeRoute);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Server exploded');
    // The weekly summary remains available.
    expect(screen.getByText(/Workouts/)).toBeDefined();

    listWorkoutsMock.mockResolvedValue(emptyPage());
    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(screen.getByText(/No finished workouts yet/)).toBeDefined(),
    );
  });

  it('reports a network failure with a retry path', async () => {
    fetchStatsSummaryMock.mockRejectedValue(new ApiNetworkError('down'));
    render(HomeRoute);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Cannot reach the server');
  });

  it('invalidates the session when a protected read returns 401', async () => {
    listWorkoutsMock.mockRejectedValue(
      requestError(401, 'Authentication required'),
    );
    render(HomeRoute);
    await waitFor(() => expect(session.status).toBe('anonymous'));
  });
});

describe('SummaryPanel display', () => {
  it('reads each tab range: profile-offset week, month, then unbounded total', async () => {
    render(HomeRoute);
    const week = weekBounds(Date.now(), OFFSET);
    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Week', selected: true }),
      ).toBeDefined(),
    );
    expect(fetchStatsSummaryMock).toHaveBeenLastCalledWith(
      { date_from: week.monday, date_to: week.sunday },
      expect.any(AbortSignal),
    );

    const month = monthBounds(Date.now(), OFFSET);
    await fireEvent.click(screen.getByRole('tab', { name: 'Month' }));
    await waitFor(() =>
      expect(fetchStatsSummaryMock).toHaveBeenLastCalledWith(
        { date_from: month.first, date_to: month.last },
        expect.any(AbortSignal),
      ),
    );
    expect(
      screen.getByText(`${month.first} – ${month.last} (UTC+3)`),
    ).toBeDefined();

    await fireEvent.click(screen.getByRole('tab', { name: 'Total' }));
    await waitFor(() =>
      expect(fetchStatsSummaryMock).toHaveBeenLastCalledWith(
        {},
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByText('Full history')).toBeDefined();
    // Selecting the visible tab again issues no further read.
    const calls = fetchStatsSummaryMock.mock.calls.length;
    await fireEvent.click(screen.getByRole('tab', { name: 'Total' }));
    expect(fetchStatsSummaryMock.mock.calls.length).toBe(calls);
  });

  it('shows integer counts with fixed metric labels', async () => {
    fetchStatsSummaryMock.mockResolvedValue(
      zeroSummary({
        workout_count: 3,
        completed_set_count: 42,
        training_day_count: 2,
        total_volume_kg_reps: 12345,
        volume_complete: true,
        current_week_streak: 4,
      }),
    );
    render(HomeRoute);
    await waitFor(() => expect(screen.getByText('12345')).toBeDefined());
    expect(screen.getByText('kg')).toBeDefined();
    expect(screen.getByText('3')).toBeDefined();
    expect(screen.getByText('42')).toBeDefined();
    expect(screen.getByText('2')).toBeDefined();
    expect(screen.getByText('4')).toBeDefined();
    expect(screen.getByText('(full history)')).toBeDefined();
    expect(screen.queryByText(/\(partial\)/)).toBeNull();
  });

  it('labels an incomplete volume as partial and exposes the unknown count', async () => {
    fetchStatsSummaryMock.mockResolvedValue(
      zeroSummary({
        total_volume_kg_reps: 900,
        volume_complete: false,
        unknown_load_set_count: 2,
      }),
    );
    render(HomeRoute);
    await waitFor(() => expect(screen.getByText(/900/)).toBeDefined());
    expect(screen.getByText(/\(partial\)/)).toBeDefined();
    expect(
      screen.getByText(/2 completed sets without a recorded load/),
    ).toBeDefined();
    // The known partial sum is never labeled complete.
    expect(screen.queryByText(/volume is complete/i)).toBeNull();
  });

  it('shows Unknown when the volume total is null', async () => {
    fetchStatsSummaryMock.mockResolvedValue(
      zeroSummary({
        total_volume_kg_reps: null,
        volume_complete: false,
        unknown_load_set_count: 1,
      }),
    );
    render(HomeRoute);
    await waitFor(() => expect(screen.getByText('Unknown')).toBeDefined());
    expect(
      screen.getByText(/1 completed set without a recorded load/),
    ).toBeDefined();
  });

  it('shows the inclusive local week range with the offset label', async () => {
    render(HomeRoute);
    const expected = weekBounds(Date.now(), OFFSET);
    await waitFor(() =>
      expect(
        screen.getByText(`${expected.monday} – ${expected.sunday} (UTC+3)`),
      ).toBeDefined(),
    );
  });
});
