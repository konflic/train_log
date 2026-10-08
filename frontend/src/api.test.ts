// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiNetworkError,
  ApiRequestError,
  MALFORMED_RESPONSE_CODE,
  createExercise,
  createWorkout,
  deleteExercise,
  deleteWorkout,
  fetchCurrentUser,
  fetchStatsSummary,
  listExercises,
  listWorkouts,
  login,
  logout,
  registerUser,
  saveWorkout,
  updateCurrentUser,
  updateExercise,
} from './api';

const fetchMock = vi.fn();

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function emptyResponse(
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(null, { status, headers });
}

/** Resolve every fetch with a fresh Response (bodies are single-use). */
function respondWith(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): void {
  fetchMock.mockImplementation(async () => jsonResponse(status, body, headers));
}

interface FetchCall {
  url: string;
  init: RequestInit & { headers: Record<string, string> };
}

function lastCall(): FetchCall {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) {
    throw new Error('fetch was not called');
  }
  return {
    url: call[0] as string,
    init: call[1] as RequestInit & { headers: Record<string, string> },
  };
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('request construction', () => {
  it('builds exercise list URLs with the exact backend query names', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { items: [], total: 0, page: 2, page_size: 10 }),
    );
    await listExercises({
      page: 2,
      pageSize: 10,
      search: 'squat',
      muscle_group: 'legs',
      equipment: 'barbell',
    });
    const { url, init } = lastCall();
    expect(url).toBe(
      '/api/v1/exercises?page=2&pageSize=10&search=squat&muscle_group=legs&equipment=barbell',
    );
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('same-origin');
    expect(init.headers).toEqual({ Accept: 'application/json' });
  });

  it('omits empty search and absent parameters', async () => {
    respondWith(200, { items: [], total: 0, page: 1, page_size: 50 });
    await listExercises({ search: '', page: 1 });
    expect(lastCall().url).toBe('/api/v1/exercises?page=1');
    await listExercises();
    expect(lastCall().url).toBe('/api/v1/exercises');
  });

  it('builds workout list URLs with status and inclusive local-date bounds', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { items: [], total: 0, page: 1, page_size: 5 }),
    );
    await listWorkouts({
      status: 'finished',
      pageSize: 5,
      date_from: '2026-09-28',
      date_to: '2026-10-04',
    });
    expect(lastCall().url).toBe(
      '/api/v1/workouts?pageSize=5&status=finished&date_from=2026-09-28&date_to=2026-10-04',
    );
  });

  it('builds stats summary URLs with date_from/date_to only', async () => {
    respondWith(200, {});
    await fetchStatsSummary({ date_from: '2026-10-05', date_to: '2026-10-11' });
    expect(lastCall().url).toBe(
      '/api/v1/stats/summary?date_from=2026-10-05&date_to=2026-10-11',
    );
    await fetchStatsSummary();
    expect(lastCall().url).toBe('/api/v1/stats/summary');
  });

  it('encodes ids in paths', async () => {
    fetchMock.mockResolvedValue(emptyResponse(204));
    await deleteExercise('a/b c');
    expect(lastCall().url).toBe('/api/v1/exercises/a%2Fb%20c');
  });

  it('passes the caller abort signal through to fetch', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    const controller = new AbortController();
    await fetchCurrentUser(controller.signal);
    expect(lastCall().init.signal).toBe(controller.signal);
  });
});

describe('mutating request headers', () => {
  it('sends JSON content-type and body on login', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        id: 'u1',
        email: 'a@b.test',
        display_name: null,
        bodyweight_default_kg: null,
        utc_offset_minutes: 0,
      }),
    );
    const user = await login({ email: 'a@b.test', password: 'secret123' });
    const { url, init } = lastCall();
    expect(url).toBe('/api/v1/auth/login');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({
      Accept: 'application/json',
      'Content-Type': 'application/json',
    });
    expect(init.body).toBe(
      JSON.stringify({ email: 'a@b.test', password: 'secret123' }),
    );
    expect(user.email).toBe('a@b.test');
  });

  it('drops undefined optional members but keeps explicit nulls', async () => {
    respondWith(201, {});
    await registerUser({ email: 'a@b.test', password: 'secret123' });
    expect(lastCall().init.body).toBe(
      JSON.stringify({ email: 'a@b.test', password: 'secret123' }),
    );
    await registerUser({
      email: 'a@b.test',
      password: 'secret123',
      display_name: null,
    });
    expect(JSON.parse(lastCall().init.body as string)).toEqual({
      email: 'a@b.test',
      password: 'secret123',
      display_name: null,
    });
  });

  it('sets JSON content-type on the bodyless logout and parses no JSON from 204', async () => {
    let jsonCalls = 0;
    const response = emptyResponse(204);
    const originalJson = response.json.bind(response);
    response.json = async () => {
      jsonCalls += 1;
      return originalJson();
    };
    fetchMock.mockResolvedValue(response);
    await expect(logout()).resolves.toBeUndefined();
    const { url, init } = lastCall();
    expect(url).toBe('/api/v1/auth/logout');
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.body).toBeUndefined();
    expect(jsonCalls).toBe(0);
  });

  it('sets JSON content-type on the bodyless DELETE', async () => {
    fetchMock.mockResolvedValue(emptyResponse(204));
    await expect(deleteExercise('push-up')).resolves.toBeUndefined();
    const { init } = lastCall();
    expect(init.method).toBe('DELETE');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.body).toBeUndefined();
  });

  it('sends only changed PATCH fields as the body', async () => {
    respondWith(200, {});
    await updateExercise('id-1', { name: 'Renamed', bodyweight_percent: null });
    const { url, init } = lastCall();
    expect(url).toBe('/api/v1/exercises/id-1');
    expect(init.method).toBe('PATCH');
    expect(init.body).toBe(
      JSON.stringify({ name: 'Renamed', bodyweight_percent: null }),
    );
    await createExercise({
      name: 'New',
      muscle_group: 'core',
      equipment: 'band',
      load_type: 'single_weight',
    });
    expect(lastCall().url).toBe('/api/v1/exercises');
  });

  it('constructs profile and complete workout mutation requests', async () => {
    respondWith(200, {});
    await updateCurrentUser({ display_name: null, utc_offset_minutes: 180 });
    expect(lastCall()).toMatchObject({
      url: '/api/v1/auth/me',
      init: { method: 'PATCH' },
    });

    await createWorkout({
      id: '00000000-0000-4000-8000-000000000001',
      started_at: '2026-10-08T10:00:00Z',
    });
    expect(lastCall()).toMatchObject({
      url: '/api/v1/workouts',
      init: { method: 'POST' },
    });

    await saveWorkout('workout/id', {
      revision: 0,
      save_id: '00000000-0000-4000-8000-000000000002',
      name: null,
      notes: null,
      bodyweight_kg: null,
      ended_at: null,
      exercises: [],
    });
    expect(lastCall()).toMatchObject({
      url: '/api/v1/workouts/workout%2Fid',
      init: { method: 'PUT' },
    });

    fetchMock.mockResolvedValue(emptyResponse(204));
    await deleteWorkout('workout/id', 7);
    expect(lastCall()).toMatchObject({
      url: '/api/v1/workouts/workout%2Fid?revision=7',
      init: { method: 'DELETE' },
    });
  });
});

describe('problem+json failures', () => {
  it('parses status, code, detail, request id, and validation errors', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        422,
        {
          type: 'about:blank',
          title: 'Validation Error',
          status: 422,
          detail: 'Request validation failed',
          code: 'validation_error',
          request_id: 'req-42',
          errors: [
            {
              field: 'body.email',
              message: 'email is malformed',
              type: 'value_error',
            },
            { field: 'body.password', message: 'too short' },
            'junk',
          ],
        },
        { 'Content-Type': 'application/problem+json' },
      ),
    );
    const error = await registerUser({ email: 'x', password: 'y' }).then(
      () => null,
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ApiRequestError);
    const problem = (error as ApiRequestError).problem;
    expect(problem.status).toBe(422);
    expect(problem.code).toBe('validation_error');
    expect(problem.title).toBe('Validation Error');
    expect(problem.detail).toBe('Request validation failed');
    expect(problem.requestId).toBe('req-42');
    expect(problem.validationErrors).toEqual([
      { field: 'body.email', message: 'email is malformed' },
      { field: 'body.password', message: 'too short' },
    ]);
    expect(problem.currentRevision).toBeNull();
  });

  it('preserves current_revision and Retry-After for callers', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        409,
        {
          title: 'Conflict',
          detail: 'moved past',
          code: 'revision_conflict',
          current_revision: 7,
        },
        { 'Content-Type': 'application/problem+json' },
      ),
    );
    await expect(listExercises()).rejects.toMatchObject({
      name: 'ApiRequestError',
      problem: { status: 409, code: 'revision_conflict', currentRevision: 7 },
    });

    fetchMock.mockResolvedValue(
      jsonResponse(
        429,
        { title: 'Too Many Requests', detail: 'slow down', code: 'throttled' },
        { 'Retry-After': '2' },
      ),
    );
    await expect(
      login({ email: 'a@b.test', password: 'secret123' }),
    ).rejects.toMatchObject({
      problem: { status: 429, code: 'throttled', retryAfterSeconds: 2 },
    });
  });

  it('falls back safely for malformed non-JSON gateway responses', async () => {
    fetchMock.mockResolvedValue(
      new Response('<html>502 Bad Gateway secret-payload</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    );
    const error = await fetchCurrentUser().then(
      () => null,
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ApiRequestError);
    const problem = (error as ApiRequestError).problem;
    expect(problem.code).toBe(MALFORMED_RESPONSE_CODE);
    expect(problem.status).toBe(502);
    // The raw body (and any submitted payload) is never echoed.
    expect(problem.detail).not.toContain('html');
    expect(problem.detail).not.toContain('secret-payload');
    expect(problem.title).not.toContain('secret-payload');
  });

  it('falls back safely for JSON error bodies that are not objects', async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, ['unexpected']));
    await expect(fetchCurrentUser()).rejects.toMatchObject({
      problem: { status: 500, code: MALFORMED_RESPONSE_CODE },
    });
  });

  it('falls back safely for malformed JSON success bodies', async () => {
    fetchMock.mockResolvedValue(new Response('not json', { status: 200 }));
    await expect(listExercises()).rejects.toMatchObject({
      name: 'ApiRequestError',
      problem: { status: 200, code: MALFORMED_RESPONSE_CODE },
    });
  });

  it('defaults missing problem members', async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, {}));
    await expect(fetchCurrentUser()).rejects.toMatchObject({
      problem: {
        status: 401,
        code: 'error',
        requestId: null,
        retryAfterSeconds: null,
        validationErrors: [],
        currentRevision: null,
      },
    });
  });
});

describe('transport failures', () => {
  it('wraps network failures distinctly from HTTP failures', async () => {
    const cause = new TypeError('fetch failed');
    fetchMock.mockRejectedValue(cause);
    const error = await listExercises().then(
      () => null,
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ApiNetworkError);
    expect(error).not.toBeInstanceOf(ApiRequestError);
    expect((error as ApiNetworkError).cause).toBe(cause);
  });

  it('rethrows aborts unwrapped so callers recognize their own signals', async () => {
    const abort = new DOMException('This operation was aborted.', 'AbortError');
    fetchMock.mockRejectedValue(abort);
    const controller = new AbortController();
    const error = await listExercises({}, controller.signal).then(
      () => null,
      (caught: unknown) => caught,
    );
    expect(error).toBe(abort);
    expect(error).not.toBeInstanceOf(ApiNetworkError);
  });
});
