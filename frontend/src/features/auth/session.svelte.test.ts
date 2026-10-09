// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchCurrentUserMock, loginMock, logoutMock, deleteAccountMock } =
  vi.hoisted(() => ({
    fetchCurrentUserMock: vi.fn(),
    loginMock: vi.fn(),
    logoutMock: vi.fn(),
    deleteAccountMock: vi.fn(),
  }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    fetchCurrentUser: fetchCurrentUserMock,
    login: loginMock,
    logout: logoutMock,
  };
});

vi.mock('../../db', () => ({
  openDraftStorage: vi.fn(async () => ({ deleteAccount: deleteAccountMock })),
}));

import { ApiNetworkError, ApiRequestError, type PublicUser } from '../../api';
import {
  SessionState,
  rememberIntendedRoute,
  takeIntendedRoute,
  takeLoginPrefillEmail,
  takeRegistrationNotice,
  primeLoginAfterRegistration,
} from './session.svelte';

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

function problem(status: number): ApiRequestError {
  return new ApiRequestError({
    status,
    code: 'error',
    title: 'Error',
    detail: 'failed',
    requestId: null,
    retryAfterSeconds: null,
    validationErrors: [],
    currentRevision: null,
  });
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  fetchCurrentUserMock.mockReset();
  loginMock.mockReset();
  logoutMock.mockReset();
  deleteAccountMock.mockReset();
});

describe('SessionState.initialize', () => {
  it('establishes the user on a 200', async () => {
    fetchCurrentUserMock.mockResolvedValue(makeUser({ email: 'a@b.test' }));
    const session = new SessionState();
    expect(session.status).toBe('loading');
    await session.initialize();
    expect(session.status).toBe('authenticated');
    expect(session.user?.email).toBe('a@b.test');
  });

  it('establishes an anonymous state on a 401', async () => {
    fetchCurrentUserMock.mockRejectedValue(problem(401));
    const session = new SessionState();
    await session.initialize();
    expect(session.status).toBe('anonymous');
    expect(session.user).toBeNull();
  });

  it('renders a retry state for network and server failures, not logout', async () => {
    fetchCurrentUserMock.mockRejectedValue(new ApiNetworkError('down'));
    const session = new SessionState();
    await session.initialize();
    expect(session.status).toBe('error');

    fetchCurrentUserMock.mockRejectedValue(problem(500));
    await session.initialize();
    expect(session.status).toBe('error');

    // A retry can recover into either real state.
    fetchCurrentUserMock.mockResolvedValue(makeUser());
    await session.initialize();
    expect(session.status).toBe('authenticated');
  });

  it('never lets a superseded request restore a stale user', async () => {
    const session = new SessionState();
    const first = deferred<PublicUser>();
    const second = deferred<PublicUser>();
    fetchCurrentUserMock.mockReturnValueOnce(first.promise);
    fetchCurrentUserMock.mockReturnValueOnce(second.promise);

    const firstRun = session.initialize();
    const secondRun = session.initialize();

    second.resolve(makeUser({ id: 'newer' }));
    await secondRun;
    expect(session.status).toBe('authenticated');
    expect(session.user?.id).toBe('newer');

    // The stale first response resolves afterwards and must be ignored.
    first.resolve(makeUser({ id: 'older' }));
    await firstRun;
    expect(session.user?.id).toBe('newer');
  });

  it('ignores a stale failure after a newer success', async () => {
    const session = new SessionState();
    const first = deferred<PublicUser>();
    fetchCurrentUserMock.mockReturnValueOnce(first.promise);
    fetchCurrentUserMock.mockResolvedValueOnce(makeUser({ id: 'fresh' }));

    const firstRun = session.initialize();
    await session.initialize();
    expect(session.status).toBe('authenticated');

    first.reject(problem(500));
    await firstRun;
    expect(session.status).toBe('authenticated');
    expect(session.user?.id).toBe('fresh');
  });
});

describe('SessionState.authenticate and noteUnauthorized', () => {
  it('adopts the user returned by the newest explicit login', async () => {
    const session = new SessionState();
    loginMock.mockResolvedValue(makeUser({ id: 'adopted' }));
    await expect(
      session.authenticate({ email: 'a@b.test', password: 'password' }),
    ).resolves.toBe(true);
    expect(session.status).toBe('authenticated');
    expect(session.user?.id).toBe('adopted');
  });

  it('ignores a login response after its route cancels the request', async () => {
    const session = new SessionState();
    const pending = deferred<PublicUser>();
    loginMock.mockReturnValueOnce(pending.promise);

    const run = session.authenticate({
      email: 'old@account.test',
      password: 'password',
    });
    session.cancelPendingAuthentication();
    pending.resolve(makeUser({ id: 'stale-login' }));

    await expect(run).resolves.toBe(false);
    expect(session.user).toBeNull();
    expect(session.status).toBe('loading');
  });

  it('invalidates the signed-in state on a protected-read 401', async () => {
    const session = new SessionState();
    loginMock.mockResolvedValueOnce(makeUser());
    await session.authenticate({ email: 'a@b.test', password: 'password' });
    session.noteUnauthorized();
    expect(session.status).toBe('anonymous');
    expect(session.user).toBeNull();

    // A late in-flight initialize for the old session cannot restore it.
    const pending = deferred<PublicUser>();
    fetchCurrentUserMock.mockReturnValueOnce(pending.promise);
    const run = session.initialize();
    session.noteUnauthorized();
    pending.resolve(makeUser({ id: 'stale' }));
    await run;
    expect(session.status).toBe('anonymous');
  });
});

describe('SessionState.signOut', () => {
  it('keeps the session on a failed revocation and clears it after success', async () => {
    const state = new SessionState();
    loginMock.mockResolvedValueOnce(makeUser());
    await state.authenticate({ email: 'a@b.test', password: 'password' });

    logoutMock.mockRejectedValueOnce(new ApiNetworkError('down'));
    await expect(state.signOut()).rejects.toThrow('down');
    expect(state.status).toBe('authenticated');
    expect(state.user?.id).toBe('u-1');

    logoutMock.mockResolvedValueOnce(undefined);
    await state.signOut();
    expect(deleteAccountMock).toHaveBeenCalledWith('u-1');
    expect(state.status).toBe('anonymous');
    expect(state.user).toBeNull();
    expect(state.logoutRequested).toBe(true);
  });
});

describe('in-memory navigation handoffs', () => {
  it('remembers the intended route once per page load', () => {
    expect(takeIntendedRoute()).toBeNull();
    rememberIntendedRoute('/catalog?muscle_group=legs');
    expect(takeIntendedRoute()).toBe('/catalog?muscle_group=legs');
    expect(takeIntendedRoute()).toBeNull();
  });

  it('hands the normalized email and notice from register to login', () => {
    expect(takeLoginPrefillEmail()).toBeNull();
    expect(takeRegistrationNotice()).toBe(false);
    primeLoginAfterRegistration('a@b.test');
    expect(takeLoginPrefillEmail()).toBe('a@b.test');
    expect(takeRegistrationNotice()).toBe(true);
    // Both are consumed exactly once.
    expect(takeLoginPrefillEmail()).toBeNull();
    expect(takeRegistrationNotice()).toBe(false);
  });
});
