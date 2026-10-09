import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  createTrainingPlanMock,
  getTrainingPlanMock,
  listExercisesMock,
  listTrainingPlansMock,
} = vi.hoisted(() => ({
  createTrainingPlanMock: vi.fn(),
  getTrainingPlanMock: vi.fn(),
  listExercisesMock: vi.fn(),
  listTrainingPlansMock: vi.fn(),
}));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    createTrainingPlan: createTrainingPlanMock,
    getTrainingPlan: getTrainingPlanMock,
    listExercises: listExercisesMock,
    listTrainingPlans: listTrainingPlansMock,
  };
});

import type { Exercise, TrainingPlan } from '../../api';
import { session } from '../auth/session.svelte';
import TrainingPlansRoute from './TrainingPlansRoute.svelte';
import { activeSession } from '../workout/activeSession.svelte';

const splitExercise: Exercise = {
  id: 'single-side-curl',
  name: 'Single-side curl',
  muscle_group: 'arms',
  equipment: 'dumbbell',
  load_type: 'split_weight',
  bodyweight_percent: 50,
  side_count: 1,
  is_default: false,
};

const plan: TrainingPlan = {
  id: 'plan-1',
  name: 'Curl plan',
  notes: null,
  revision: 0,
  exercises: [
    {
      id: 'plan-exercise-1',
      catalog_id: splitExercise.id,
      order_index: 0,
      notes: null,
      sets: [
        {
          id: 'plan-set-1',
          set_index: 0,
          target_reps: 8,
          target_weight_kg: 12,
          bw_percent_override: 75,
          side: 'right',
        },
      ],
    },
  ],
};

beforeEach(() => {
  cleanup();
  activeSession.reset();
  session.status = 'authenticated';
  session.user = {
    id: 'account-1',
    email: 'user@example.test',
    display_name: null,
    bodyweight_default_kg: null,
    sex: null,
    age: null,
    utc_offset_minutes: 0,
  };
  listExercisesMock.mockReset().mockResolvedValue({
    items: [splitExercise],
    total: 1,
    page: 1,
    page_size: 100,
  });
  listTrainingPlansMock.mockReset().mockResolvedValue({
    items: [
      {
        id: plan.id,
        name: plan.name,
        notes: plan.notes,
        revision: plan.revision,
      },
    ],
    total: 1,
    page: 1,
    page_size: 50,
  });
  getTrainingPlanMock.mockReset().mockResolvedValue(plan);
  createTrainingPlanMock.mockReset().mockResolvedValue(plan);
});

describe('TrainingPlansRoute', () => {
  it('previews targets and prevents a second active session start', async () => {
    activeSession.setActive('workout-1');
    render(TrainingPlansRoute);

    await waitFor(() =>
      expect(
        screen.getByText('8 reps, 12 kg, 75% bodyweight, right'),
      ).toBeDefined(),
    );
    expect(
      (
        screen.getByRole('button', {
          name: 'Start session',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      screen
        .getByRole('link', { name: 'Resume active session' })
        .getAttribute('href'),
    ).toBe('#/workouts/workout-1');
  });

  it('saves side and bodyweight-percent targets for a plan set', async () => {
    render(TrainingPlansRoute);
    await screen.findByRole('button', { name: 'Create plan' });

    await fireEvent.click(screen.getByRole('button', { name: 'Create plan' }));
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Right curl' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Add exercise' }));
    await fireEvent.input(screen.getByLabelText('Bodyweight % override'), {
      target: { value: '60' },
    });
    await fireEvent.change(screen.getByLabelText('Side'), {
      target: { value: 'right' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Save plan' }));

    await waitFor(() =>
      expect(createTrainingPlanMock).toHaveBeenCalledWith({
        name: 'Right curl',
        notes: null,
        exercises: [
          {
            catalog_id: splitExercise.id,
            notes: null,
            sets: [
              {
                target_reps: null,
                target_weight_kg: null,
                bw_percent_override: 60,
                side: 'right',
              },
            ],
          },
        ],
      }),
    );
  });

  it('keeps changed plan fields open when discard is cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(TrainingPlansRoute);
    await screen.findByRole('button', { name: 'Create plan' });

    await fireEvent.click(screen.getByRole('button', { name: 'Create plan' }));
    await fireEvent.input(screen.getByLabelText('Name'), {
      target: { value: 'Unfinished plan' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(confirm).toHaveBeenCalledWith('Discard unsaved plan changes?');
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe(
      'Unfinished plan',
    );
    confirm.mockRestore();
  });
});
