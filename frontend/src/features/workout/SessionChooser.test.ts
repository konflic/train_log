import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { startSessionMock, pushMock } = vi.hoisted(() => ({
  startSessionMock: vi.fn(),
  pushMock: vi.fn(),
}));

vi.mock('./startSession', () => ({ startSession: startSessionMock }));
vi.mock('svelte-spa-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('svelte-spa-router')>();
  return { ...actual, push: pushMock };
});

import { session } from '../auth/session.svelte';
import SessionChooser from './SessionChooser.svelte';
import { activeSession } from './activeSession.svelte';

beforeEach(() => {
  cleanup();
  startSessionMock.mockReset();
  pushMock.mockReset().mockResolvedValue(undefined);
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
});

describe('SessionChooser', () => {
  it('does not create a workout merely by opening the chooser', () => {
    render(SessionChooser);
    expect(
      screen.getByRole('heading', { name: 'Choose session type' }),
    ).toBeDefined();
    expect(startSessionMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole('link', { name: 'Plan session' }).getAttribute('href'),
    ).toBe('#/training-plans');
  });

  it('starts freestyle only after the explicit action and resumes that identity', async () => {
    startSessionMock.mockResolvedValue({
      workout_id: 'workout-1',
      draft_id: 'draft-1',
    });
    render(SessionChooser);

    await fireEvent.click(
      screen.getByRole('button', { name: 'Freestyle session' }),
    );

    await waitFor(() => expect(startSessionMock).toHaveBeenCalledOnce());
    expect(startSessionMock).toHaveBeenCalledWith('account-1');
    expect(activeSession.workoutId).toBe('workout-1');
    expect(pushMock).toHaveBeenCalledWith('/workouts/workout-1');
  });

  it('shows the active session instead of another start action', () => {
    activeSession.setActive('workout-1');
    render(SessionChooser);

    expect(
      screen
        .getByRole('link', { name: 'Resume active session' })
        .getAttribute('href'),
    ).toBe('#/workouts/workout-1');
    expect(
      screen.queryByRole('button', { name: 'Freestyle session' }),
    ).toBeNull();
  });
});
