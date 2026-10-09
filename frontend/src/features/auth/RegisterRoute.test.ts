import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { registerUserMock } = vi.hoisted(() => ({ registerUserMock: vi.fn() }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, registerUser: registerUserMock };
});

import { ApiRequestError, type PublicUser } from '../../api';
import LoginRoute from './LoginRoute.svelte';
import RegisterRoute from './RegisterRoute.svelte';
import { session } from './session.svelte';

function makeUser(overrides: Partial<PublicUser> = {}): PublicUser {
  return {
    id: 'u-1',
    email: 'user@example.test',
    display_name: null,
    bodyweight_default_kg: null,
    sex: null,
    age: null,
    utc_offset_minutes: 0,
    ...overrides,
  };
}

function form(): HTMLFormElement {
  const element = document.querySelector('form');
  if (element === null) {
    throw new Error('form not rendered');
  }
  return element;
}

beforeEach(() => {
  registerUserMock.mockReset();
  window.location.hash = '';
  window.dispatchEvent(new Event('hashchange'));
  session.noteUnauthorized();
  cleanup();
});

describe('RegisterRoute', () => {
  it('registers without signing in and moves to login with the email ready', async () => {
    registerUserMock.mockResolvedValue(makeUser({ email: 'new@example.test' }));
    render(RegisterRoute);

    await fireEvent.input(screen.getByLabelText('Email'), {
      target: { value: '  New@Example.TEST ' },
    });
    await fireEvent.input(screen.getByLabelText('Password'), {
      target: { value: 'password123' },
    });
    await fireEvent.input(screen.getByLabelText(/Display name/), {
      target: { value: '  Ada  ' },
    });
    await fireEvent.input(screen.getByLabelText('Initial weight (kg)'), {
      target: { value: '75' },
    });
    await fireEvent.change(screen.getByLabelText('Sex'), {
      target: { value: 'female' },
    });
    await fireEvent.input(screen.getByLabelText('Age'), {
      target: { value: '31' },
    });
    await fireEvent.submit(form());

    await waitFor(() =>
      expect(registerUserMock).toHaveBeenCalledWith({
        email: 'new@example.test',
        password: 'password123',
        display_name: 'Ada',
        bodyweight_default_kg: 75,
        sex: 'female',
        age: 31,
      }),
    );
    // A successful registration does not imply a session.
    expect(session.status).toBe('anonymous');

    const status = await screen.findByRole('status');
    expect(status.textContent).toContain(
      'Account created for new@example.test',
    );
    expect(status.textContent).toContain('does not sign you in');

    await fireEvent.click(
      screen.getByRole('button', { name: 'Continue to log in' }),
    );
    await waitFor(() => expect(window.location.hash).toBe('#/login'));

    // The login form has the normalized email available for convenience.
    cleanup();
    render(LoginRoute);
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe(
      'new@example.test',
    );
  });

  it('omits display_name when left blank', async () => {
    registerUserMock.mockResolvedValue(makeUser());
    render(RegisterRoute);
    await fireEvent.input(screen.getByLabelText('Email'), {
      target: { value: 'new@example.test' },
    });
    await fireEvent.input(screen.getByLabelText('Password'), {
      target: { value: 'password123' },
    });
    await fireEvent.input(screen.getByLabelText(/Display name/), {
      target: { value: '   ' },
    });
    await fireEvent.input(screen.getByLabelText('Initial weight (kg)'), {
      target: { value: '75' },
    });
    await fireEvent.change(screen.getByLabelText('Sex'), {
      target: { value: 'male' },
    });
    await fireEvent.input(screen.getByLabelText('Age'), {
      target: { value: '31' },
    });
    await fireEvent.submit(form());
    await waitFor(() =>
      expect(registerUserMock).toHaveBeenCalledWith({
        email: 'new@example.test',
        password: 'password123',
        display_name: undefined,
        bodyweight_default_kg: 75,
        sex: 'male',
        age: 31,
      }),
    );
  });

  it('blocks clearly invalid input without a request', async () => {
    render(RegisterRoute);
    await fireEvent.input(screen.getByLabelText('Email'), {
      target: { value: 'nope' },
    });
    await fireEvent.input(screen.getByLabelText('Password'), {
      target: { value: 'short' },
    });
    await fireEvent.submit(form());
    expect(registerUserMock).not.toHaveBeenCalled();
    expect(screen.getByText('Enter a valid email address')).toBeDefined();
    expect(
      screen.getByText('Password must be at least 8 characters'),
    ).toBeDefined();
    expect(screen.getByText('Initial weight is required')).toBeDefined();
    expect(screen.getByText('Sex is required')).toBeDefined();
    expect(screen.getByText('Age is required')).toBeDefined();
  });

  it('shows the duplicate-account conflict at form level', async () => {
    registerUserMock.mockRejectedValue(
      new ApiRequestError({
        status: 409,
        code: 'email_taken',
        title: 'Conflict',
        detail: 'An account with this email already exists',
        requestId: null,
        retryAfterSeconds: null,
        validationErrors: [],
        currentRevision: null,
      }),
    );
    render(RegisterRoute);
    await fireEvent.input(screen.getByLabelText('Email'), {
      target: { value: 'taken@example.test' },
    });
    await fireEvent.input(screen.getByLabelText('Password'), {
      target: { value: 'password123' },
    });
    await fireEvent.input(screen.getByLabelText('Initial weight (kg)'), {
      target: { value: '75' },
    });
    await fireEvent.change(screen.getByLabelText('Sex'), {
      target: { value: 'female' },
    });
    await fireEvent.input(screen.getByLabelText('Age'), {
      target: { value: '31' },
    });
    await fireEvent.submit(form());
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(
      'An account with this email already exists',
    );
    // The form stays available for correction once the action re-enables.
    expect(
      await screen.findByRole('button', { name: 'Create account' }),
    ).toBeDefined();
  });
});
