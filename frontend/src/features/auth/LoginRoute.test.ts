import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { loginMock } = vi.hoisted(() => ({ loginMock: vi.fn() }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return { ...actual, login: loginMock };
});

import { ApiNetworkError, ApiRequestError, type PublicUser } from '../../api';
import LoginRoute from './LoginRoute.svelte';
import {
  primeLoginAfterRegistration,
  rememberIntendedRoute,
  session,
  takeIntendedRoute,
} from './session.svelte';

function makeUser(overrides: Partial<PublicUser> = {}): PublicUser {
  return {
    id: 'u-1',
    email: 'user@example.test',
    display_name: null,
    bodyweight_default_kg: null,
    utc_offset_minutes: 0,
    ...overrides,
  };
}

function requestError(
  status: number,
  detail: string,
  retryAfterSeconds: number | null = null,
) {
  return new ApiRequestError({
    status,
    code: 'error',
    title: 'Error',
    detail,
    requestId: null,
    retryAfterSeconds,
    validationErrors: [],
    currentRevision: null,
  });
}

function form(): HTMLFormElement {
  const element = document.querySelector('form');
  if (element === null) {
    throw new Error('form not rendered');
  }
  return element;
}

async function fillAndSubmit(email: string, password: string): Promise<void> {
  await fireEvent.input(screen.getByLabelText('Email'), {
    target: { value: email },
  });
  await fireEvent.input(screen.getByLabelText('Password'), {
    target: { value: password },
  });
  await fireEvent.submit(form());
}

beforeEach(() => {
  loginMock.mockReset();
  window.location.hash = '';
  window.dispatchEvent(new Event('hashchange'));
  session.noteUnauthorized();
  takeIntendedRoute();
  cleanup();
});

describe('LoginRoute', () => {
  it('renders real labels and autocomplete attributes', () => {
    render(LoginRoute);
    const email = screen.getByLabelText('Email');
    const password = screen.getByLabelText('Password');
    expect(email.getAttribute('autocomplete')).toBe('username');
    expect(email.getAttribute('type')).toBe('email');
    expect(password.getAttribute('autocomplete')).toBe('current-password');
    expect(password.getAttribute('type')).toBe('password');
    expect(screen.getByRole('button', { name: 'Log in' })).toBeDefined();
  });

  it('blocks clearly invalid input without a request', async () => {
    render(LoginRoute);
    await fillAndSubmit('not-an-email', '123');
    expect(loginMock).not.toHaveBeenCalled();
    expect(screen.getByText('Enter a valid email address')).toBeDefined();
    expect(
      screen.getByText('Password must be at least 8 characters'),
    ).toBeDefined();
  });

  it('normalizes the email, adopts the session, and navigates home', async () => {
    loginMock.mockResolvedValue(makeUser());
    render(LoginRoute);
    await fillAndSubmit('  User@Example.TEST ', 'password123');
    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith(
        {
          email: 'user@example.test',
          password: 'password123',
        },
        expect.any(AbortSignal),
      ),
    );
    await waitFor(() => expect(window.location.hash).toBe('#/'));
    expect(session.status).toBe('authenticated');
    expect(session.user?.email).toBe('user@example.test');
    // The password never reaches frontend persistence.
    expect(session.user?.display_name).toBeNull();
  });

  it('returns to the intended route preserved for this page load', async () => {
    loginMock.mockResolvedValue(makeUser());
    rememberIntendedRoute('/catalog?muscle_group=legs');
    render(LoginRoute);
    await fillAndSubmit('user@example.test', 'password123');
    await waitFor(() =>
      expect(window.location.hash).toBe('#/catalog?muscle_group=legs'),
    );
    expect(takeIntendedRoute()).toBeNull();
  });

  it('shows the generic invalid-credential message from the API', async () => {
    loginMock.mockRejectedValue(requestError(401, 'Invalid email or password'));
    render(LoginRoute);
    await fillAndSubmit('user@example.test', 'wrong-password');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Invalid email or password');
    expect(session.status).toBe('anonymous');
  });

  it('formats throttling with the retry delay and network failures distinctly', async () => {
    loginMock.mockRejectedValue(requestError(429, 'Too Many Requests', 30));
    const { unmount } = render(LoginRoute);
    await fillAndSubmit('user@example.test', 'password123');
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Too many attempts. Try again in 30 seconds.',
    );
    unmount();
    cleanup();

    loginMock.mockRejectedValue(new ApiNetworkError('down'));
    render(LoginRoute);
    await fillAndSubmit('user@example.test', 'password123');
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Cannot reach the server',
    );
  });

  it('disables only the submitted action while the request is active', async () => {
    let resolveLogin!: (user: PublicUser) => void;
    loginMock.mockReturnValue(
      new Promise<PublicUser>((resolve) => {
        resolveLogin = resolve;
      }),
    );
    render(LoginRoute);
    await fillAndSubmit('user@example.test', 'password123');
    const button = screen.getByRole('button', {
      name: 'Logging in…',
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    // A second submit is prevented.
    await fireEvent.submit(form());
    expect(loginMock).toHaveBeenCalledTimes(1);
    resolveLogin(makeUser());
    await waitFor(() => expect(window.location.hash).toBe('#/'));
  });

  it('prefills the normalized email after registration', () => {
    primeLoginAfterRegistration('new@example.test');
    render(LoginRoute);
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe(
      'new@example.test',
    );
    expect(screen.getByRole('status').textContent).toContain(
      'Account created. Log in to continue.',
    );
  });
});
