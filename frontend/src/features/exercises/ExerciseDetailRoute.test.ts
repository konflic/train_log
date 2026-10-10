import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getExerciseMock, fetchExerciseStatsMock } = vi.hoisted(() => ({
  getExerciseMock: vi.fn(),
  fetchExerciseStatsMock: vi.fn(),
}));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    getExercise: getExerciseMock,
    fetchExerciseStats: fetchExerciseStatsMock,
  };
});

import {
  ApiRequestError,
  type ExerciseDetail,
  type ExerciseStats,
} from '../../api';
import { session } from '../auth/session.svelte';
import ExerciseDetailRoute from './ExerciseDetailRoute.svelte';

const pullUp: ExerciseDetail = {
  id: 'pull-up',
  name: 'Pull-up',
  muscle_group: 'back',
  load_type: 'bodyweight',
  bodyweight_percent: 100,
  side_count: 1,
  is_default: true,
  description: 'A bodyweight pull to the bar.',
  guidance: {
    technique_steps: ['Grip the bar', 'Pull until the chin clears the bar'],
    form_tips: ['Avoid kipping'],
    animation_key: 'pull-up',
    sources: [
      {
        title: 'Pull-up and chin-up muscle activation study',
        url: 'https://pubmed.ncbi.nlm.nih.gov/21068680/',
      },
    ],
  },
};

const customEntry: ExerciseDetail = {
  id: 'custom-1',
  name: 'Custom Curl',
  muscle_group: 'arms',
  load_type: 'split_weight',
  bodyweight_percent: null,
  side_count: 2,
  is_default: false,
  description: 'My own arm work.',
  guidance: null,
};

const emptyStats: ExerciseStats = {
  training_count: 0,
  completed_set_count: 0,
  total_volume_kg_reps: 0,
  unknown_load_set_count: 0,
  volume_complete: true,
  best_estimated_1rm_kg: null,
  sessions: [],
};

const populatedStats: ExerciseStats = {
  training_count: 2,
  completed_set_count: 5,
  total_volume_kg_reps: 900,
  unknown_load_set_count: 1,
  volume_complete: false,
  best_estimated_1rm_kg: 112,
  sessions: [
    {
      workout_id: 'w-1',
      started_at: '2026-09-01T10:00:00Z',
      completed_set_count: 3,
      volume_kg_reps: 600,
      unknown_load_set_count: 0,
      volume_complete: true,
    },
    {
      workout_id: 'w-2',
      started_at: '2026-09-08T10:00:00Z',
      completed_set_count: 2,
      volume_kg_reps: 300,
      unknown_load_set_count: 1,
      volume_complete: false,
    },
  ],
};

function requestError(status: number, detail: string) {
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

function renderRoute(id = 'pull-up') {
  return render(ExerciseDetailRoute, { props: { params: { id } } });
}

beforeEach(() => {
  getExerciseMock.mockReset();
  fetchExerciseStatsMock.mockReset();
  getExerciseMock.mockResolvedValue(pullUp);
  fetchExerciseStatsMock.mockResolvedValue(emptyStats);
  session.status = 'authenticated';
  session.user = {
    id: 'u-1',
    email: 'user@example.test',
    display_name: null,
    bodyweight_default_kg: null,
    sex: null,
    age: null,
    utc_offset_minutes: 0,
  };
  cleanup();
});

describe('default exercise detail', () => {
  it('renders guidance, sources, badges, and the animation', async () => {
    renderRoute();
    await screen.findByRole('heading', { name: 'Pull-up' });
    expect(screen.getByText('A bodyweight pull to the bar.')).toBeDefined();
    expect(screen.getByText('Grip the bar')).toBeDefined();
    expect(screen.getByText('Avoid kipping')).toBeDefined();
    const source = screen.getByRole('link', {
      name: 'Pull-up and chin-up muscle activation study',
    }) as HTMLAnchorElement;
    expect(source.href).toBe('https://pubmed.ncbi.nlm.nih.gov/21068680/');
    expect(source.target).toBe('_blank');
    // Compact badges and semantic hooks (the back-nav link also reads "Back").
    expect(screen.getAllByText('Back').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Bodyweight')).toBeDefined();
    expect(document.querySelector('.exercise-detail')).not.toBeNull();
    expect(
      document.querySelector('.exercise-detail__technique'),
    ).not.toBeNull();
    expect(document.querySelector('.exercise-detail__advice')).not.toBeNull();
    expect(
      document.querySelector('.exercise-detail__animation'),
    ).not.toBeNull();
    const frames = document.querySelectorAll('.exercise-detail__animation img');
    expect(frames.length).toBe(2);
    expect(
      screen.getByRole('button', { name: /movement animation/i }),
    ).toBeDefined();
    // Weight semantics stay available off the compact cards.
    expect(screen.getByText('How weight is logged')).toBeDefined();
  });

  it('renders honest statistics and chart semantics', async () => {
    fetchExerciseStatsMock.mockResolvedValue(populatedStats);
    renderRoute();
    await screen.findByRole('heading', { name: 'Pull-up' });
    await waitFor(() =>
      expect(document.querySelector('.exercise-stats')).not.toBeNull(),
    );
    expect(screen.getByText('Trainings').nextElementSibling?.textContent).toBe(
      '2',
    );
    expect(
      screen.getByText('Lifetime volume').parentElement?.textContent,
    ).toContain('At least 900 kg');
    expect(
      screen.getByText('Best estimated 1RM').parentElement?.textContent,
    ).toContain('112 kg');
    const chart = document.querySelector('.exercise-volume-chart');
    expect(chart).not.toBeNull();
    const bars = chart!.querySelectorAll('.exercise-volume-chart__bar');
    expect(bars.length).toBe(2);
    expect(chart!.querySelector('.bar-partial')).not.toBeNull();
    // Exact values are available as visible text (no hover required), and each
    // session links to its finished-workout detail.
    const chartEl = chart as HTMLElement;
    expect(within(chartEl).getByText('600 kg')).toBeDefined();
    expect(within(chartEl).getByText('At least 300 kg')).toBeDefined();
    const workoutLink = within(chartEl)
      .getAllByRole('link')
      .find((link) => link.getAttribute('href') === '#/history/w-2');
    expect(workoutLink).toBeDefined();
  });

  it('renders empty statistics and an unavailable 1RM honestly', async () => {
    renderRoute();
    await screen.findByRole('heading', { name: 'Pull-up' });
    await waitFor(() =>
      expect(screen.getByText('Your statistics')).toBeDefined(),
    );
    expect(
      screen.getByText('Best estimated 1RM').parentElement?.textContent,
    ).toContain('N/A');
    expect(
      screen.getByText('No finished sessions with this exercise yet'),
    ).toBeDefined();
  });
});

describe('custom exercise detail', () => {
  it('renders the description without any media or fabricated guidance', async () => {
    getExerciseMock.mockResolvedValue(customEntry);
    renderRoute('custom-1');
    await screen.findByRole('heading', { name: 'Custom Curl' });
    expect(screen.getByText('My own arm work.')).toBeDefined();
    expect(screen.getByText('Custom')).toBeDefined();
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('.exercise-detail__animation')).toBeNull();
    expect(screen.queryByText('How to perform')).toBeNull();
    expect(screen.queryByText('Form cues')).toBeNull();
    expect(screen.queryByText('Sources')).toBeNull();
  });

  it('shows a neutral empty state without a description', async () => {
    getExerciseMock.mockResolvedValue({ ...customEntry, description: null });
    renderRoute('custom-1');
    await screen.findByRole('heading', { name: 'Custom Curl' });
    expect(screen.getByText('No description provided')).toBeDefined();
  });
});

describe('independent content and statistics states', () => {
  it('keeps guidance visible when statistics fail, with its own retry', async () => {
    fetchExerciseStatsMock.mockRejectedValue(requestError(500, 'Stats down'));
    renderRoute();
    await screen.findByRole('heading', { name: 'Pull-up' });
    expect(screen.getByText('Grip the bar')).toBeDefined();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Stats down');
    expect(screen.getByText('Retry statistics')).toBeDefined();
  });

  it('keeps the statistics retry separate from a content failure', async () => {
    getExerciseMock.mockRejectedValue(requestError(500, 'Content down'));
    renderRoute();
    await screen.findByRole('alert');
    expect(screen.getByText('Content down')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDefined();
    // Statistics still loaded independently.
    await waitFor(() =>
      expect(screen.getByText('Your statistics')).toBeDefined(),
    );
  });

  it('renders a not-found state for unknown or foreign ids', async () => {
    getExerciseMock.mockRejectedValue(requestError(404, 'Exercise not found'));
    fetchExerciseStatsMock.mockRejectedValue(
      requestError(404, 'Exercise not found'),
    );
    renderRoute('no-such');
    await screen.findByRole('heading', { name: 'Exercise not found' });
    expect(screen.getByRole('link', { name: 'Open catalog' })).toBeDefined();
  });
});
