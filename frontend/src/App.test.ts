import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  fetchCurrentUserMock,
  logoutMock,
  deleteAccountMock,
  listWorkoutsMock,
  fetchStatsSummaryMock,
  listExercisesMock,
} = vi.hoisted(() => ({
  fetchCurrentUserMock: vi.fn(),
  logoutMock: vi.fn(),
  deleteAccountMock: vi.fn(),
  listWorkoutsMock: vi.fn(),
  fetchStatsSummaryMock: vi.fn(),
  listExercisesMock: vi.fn(),
}));

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    fetchCurrentUser: fetchCurrentUserMock,
    logout: logoutMock,
    listWorkouts: listWorkoutsMock,
    fetchStatsSummary: fetchStatsSummaryMock,
    listExercises: listExercisesMock,
  };
});

vi.mock('./db', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./db')>();
  return {
    ...actual,
    openDraftStorage: vi.fn(async () => ({ deleteAccount: deleteAccountMock })),
  };
});

import { ApiNetworkError, ApiRequestError, type PublicUser } from './api';
import App from './App.svelte';
import { session, takeIntendedRoute } from './features/auth/session.svelte';

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

function requestError(status: number, detail = 'failed'): ApiRequestError {
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

function navigateTo(hash: string): void {
  window.location.hash = hash;
  window.dispatchEvent(new Event('hashchange'));
}

/** Render the app with an already-authenticated session by default. */
async function renderAuthenticated(): Promise<void> {
  fetchCurrentUserMock.mockResolvedValue(makeUser());
  render(App);
  await waitFor(() => expect(session.status).toBe('authenticated'));
}

beforeEach(() => {
  fetchCurrentUserMock.mockReset();
  logoutMock.mockReset();
  deleteAccountMock.mockReset();
  // Home/Catalog panels must not reach the network in shell tests.
  listWorkoutsMock.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 5,
  });
  listExercisesMock.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 10,
  });
  fetchStatsSummaryMock.mockResolvedValue({
    workout_count: 0,
    completed_set_count: 0,
    training_day_count: 0,
    total_volume_kg_reps: 0,
    unknown_load_set_count: 0,
    volume_complete: true,
    muscle_group_frequency: [],
    current_week_streak: 0,
  });
  // Reset the shared singleton and route state between tests.
  session.status = 'loading';
  session.user = null;
  session.logoutRequested = false;
  navigateTo('#/');
  takeIntendedRoute();
  cleanup();
});

describe('startup session states', () => {
  it('shows a checking state while GET /auth/me is in flight', () => {
    fetchCurrentUserMock.mockReturnValue(new Promise<PublicUser>(() => {}));
    render(App);
    expect(screen.getByRole('status').textContent).toContain(
      'Checking your session',
    );
  });

  it('renders a retry state for network failures instead of logging out', async () => {
    fetchCurrentUserMock.mockRejectedValueOnce(new ApiNetworkError('down'));
    render(App);
    await waitFor(() =>
      expect(
        screen.getByRole('heading', {
          level: 1,
          name: 'Cannot reach the server',
        }),
      ).toBeDefined(),
    );
    expect(session.status).toBe('error');

    fetchCurrentUserMock.mockResolvedValue(makeUser());
    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(session.status).toBe('authenticated'));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Home' }),
      ).toBeDefined(),
    );
  });
});

describe('route guarding', () => {
  it('leads anonymous feature routes to login, preserving the requested route', async () => {
    fetchCurrentUserMock.mockRejectedValue(requestError(401));
    navigateTo('#/catalog?muscle_group=legs');
    render(App);
    await waitFor(() => expect(window.location.hash).toBe('#/login'));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Log in' }),
      ).toBeDefined(),
    );
    expect(takeIntendedRoute()).toBe('/catalog?muscle_group=legs');
    // The shell navigation is hidden on auth routes.
    expect(screen.queryByRole('navigation', { name: 'Primary' })).toBeNull();
  });

  it('does not offer feature routes while anonymous', async () => {
    fetchCurrentUserMock.mockRejectedValue(requestError(401));
    render(App);
    await waitFor(() => expect(window.location.hash).toBe('#/login'));
    expect(
      screen.queryByRole('heading', { level: 1, name: 'Home' }),
    ).toBeNull();
    expect(
      screen.queryByRole('heading', { level: 1, name: 'Catalog' }),
    ).toBeNull();
  });
});

describe('authenticated application shell', () => {
  it('renders icon-only bottom navigation with named anchors', async () => {
    await renderAuthenticated();
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    const links = nav.querySelectorAll('a');
    expect(
      Array.from(links).map((link) => link.getAttribute('aria-label')),
    ).toEqual(['Home', 'Catalog', 'Current workout', 'History', 'Settings']);
    expect(nav.querySelectorAll('svg')).toHaveLength(5);
    expect(
      screen
        .getByRole('link', { name: 'Current workout' })
        .getAttribute('href'),
    ).toBe('#/workouts/current');
    // Keyboard-visible navigation: real anchors with hash targets.
    for (const link of links) {
      expect(link.getAttribute('href')).toMatch(/^#\//);
    }
  });

  it('renders Home by default and marks it as the current page', async () => {
    await renderAuthenticated();
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Home' }),
    ).toBeDefined();
    expect(
      screen.getByRole('link', { name: 'Home' }).getAttribute('aria-current'),
    ).toBe('page');
    expect(
      screen
        .getByRole('link', { name: 'Catalog' })
        .hasAttribute('aria-current'),
    ).toBe(false);
  });

  it('routes to the catalog and moves the current-page marker', async () => {
    await renderAuthenticated();
    navigateTo('#/catalog');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Catalog' }),
      ).toBeDefined(),
    );
    expect(
      screen
        .getByRole('link', { name: 'Catalog' })
        .getAttribute('aria-current'),
    ).toBe('page');
    expect(
      screen.getByRole('link', { name: 'Home' }).hasAttribute('aria-current'),
    ).toBe(false);
  });

  it('routes to history and settings placeholders', async () => {
    await renderAuthenticated();
    navigateTo('#/history');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'History' }),
      ).toBeDefined(),
    );
    navigateTo('#/settings');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Settings' }),
      ).toBeDefined(),
    );
  });

  it('logs out from Settings and displays the app version', async () => {
    logoutMock.mockResolvedValueOnce(undefined);
    await renderAuthenticated();
    navigateTo('#/settings');
    await screen.findByRole('heading', { level: 1, name: 'Settings' });

    expect(screen.getByText('Version 0.1.0')).toBeDefined();
    await fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

    await waitFor(() => expect(window.location.hash).toBe('#/login'));
    expect(logoutMock).toHaveBeenCalledOnce();
    expect(deleteAccountMock).toHaveBeenCalledWith('u-1');
    expect(takeIntendedRoute()).toBeNull();
  });

  it('renders the not-found route for unknown hashes', async () => {
    await renderAuthenticated();
    navigateTo('#/definitely-not-a-route');
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 1, name: 'Page not found' }),
      ).toBeDefined(),
    );
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(nav.querySelector('[aria-current="page"]')).toBeNull();
  });

  it('applies a theme class to the document root on mount', async () => {
    localStorage.clear();
    await renderAuthenticated();
    const classes = document.documentElement.classList;
    expect(classes.contains('light') || classes.contains('dark')).toBe(true);
    expect(classes.contains('light') && classes.contains('dark')).toBe(false);
  });
});
