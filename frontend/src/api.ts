/**
 * Local API types and focused fetch helpers over browser `fetch`
 * (PLAN.md §2, §6; Stage 9 contract).
 *
 * Requests use relative `/api/v1` URLs and same-origin credentials; the
 * session cookie stays HttpOnly and is never read by frontend code. Every
 * mutating request sets `Content-Type: application/json`, including bodyless
 * logout and DELETE, because the backend checks the header on all mutating
 * verbs. Non-success responses parse into one typed problem shape; malformed
 * gateway responses fall back to a safe problem without echoing payloads.
 * This layer distinguishes HTTP failures from network/abort failures and
 * implements no retry, caching, redirect-on-401, or synchronization policy.
 */

export type MuscleGroup =
  | 'chest'
  | 'back'
  | 'legs'
  | 'shoulders'
  | 'arms'
  | 'core'
  | 'full_body'
  | 'other';

export type Equipment =
  | 'barbell'
  | 'dumbbell'
  | 'kettlebell'
  | 'machine'
  | 'cable'
  | 'bodyweight'
  | 'band'
  | 'other';

export type LoadType = 'single_weight' | 'split_weight' | 'bodyweight';
export type WorkoutStatus = 'active' | 'finished';
export type SetSide = 'left' | 'right' | 'bilateral';

/** The only public user shape (auth endpoints). */
export interface PublicUser {
  id: string;
  email: string;
  display_name: string | null;
  bodyweight_default_kg: number | null;
  utc_offset_minutes: number;
}

export interface RegisterInput {
  email: string;
  password: string;
  display_name?: string | null;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface Exercise {
  id: string;
  name: string;
  muscle_group: MuscleGroup;
  equipment: Equipment;
  load_type: LoadType;
  bodyweight_percent: number | null;
  side_count: number;
  is_default: boolean;
}

export interface ExercisePage {
  items: Exercise[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExerciseListQuery {
  page?: number;
  pageSize?: number;
  search?: string;
  muscle_group?: MuscleGroup;
  equipment?: Equipment;
}

export interface ExerciseCreateInput {
  name: string;
  muscle_group: MuscleGroup;
  equipment: Equipment;
  load_type: LoadType;
  bodyweight_percent?: number | null;
  side_count?: number;
}

/** Partial PATCH input; an explicit `null` clears `bodyweight_percent`. */
export interface ExerciseUpdateInput {
  name?: string;
  muscle_group?: MuscleGroup;
  equipment?: Equipment;
  load_type?: LoadType;
  bodyweight_percent?: number | null;
  side_count?: number;
}

export interface WorkoutSummary {
  id: string;
  name: string | null;
  started_at: string;
  ended_at: string | null;
  bodyweight_kg: number | null;
  revision: number;
}

export interface WorkoutPage {
  items: WorkoutSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface WorkoutListQuery {
  page?: number;
  pageSize?: number;
  status?: WorkoutStatus;
  date_from?: string;
  date_to?: string;
}

/** Reported integer values for one compared set; `null` means unknown. */
export interface SetValues {
  reps: number | null;
  external_load_kg: number | null;
  effective_load_kg: number | null;
  volume_kg_reps: number | null;
  estimated_1rm_kg: number | null;
}

export interface StoredSet {
  id: string;
  set_index: number;
  reps: number | null;
  weight_kg: number | null;
  bw_percent_override: number | null;
  rpe: number | null;
  side: SetSide;
  done: boolean;
}

export interface PreviousSet {
  id: string;
  set_index: number;
  side: SetSide;
  reps: number | null;
  weight_kg: number | null;
  bw_percent_override: number | null;
  values: SetValues;
}

export interface PreviousSetPair {
  current_set_id: string;
  previous_set_id: string;
  load_compatible: boolean;
  current: SetValues;
  previous: SetValues;
  delta: SetValues;
}

export interface PreviousPerformance {
  workout_id: string;
  started_at: string;
  bodyweight_kg: number | null;
  exercise_id: string;
  order_index: number;
  load_type: LoadType;
  bodyweight_percent: number | null;
  side_count: number;
  sets: PreviousSet[];
  pairs: PreviousSetPair[];
}

export interface ExerciseNode {
  id: string;
  catalog_id: string;
  order_index: number;
  notes: string | null;
  load_type: LoadType;
  bodyweight_percent: number | null;
  side_count: number;
  sets: StoredSet[];
  previous_performance: PreviousPerformance | null;
}

export interface WorkoutDetail {
  id: string;
  name: string | null;
  started_at: string;
  ended_at: string | null;
  notes: string | null;
  bodyweight_kg: number | null;
  revision: number;
  last_save_id: string | null;
  exercises: ExerciseNode[];
}

export interface MuscleGroupFrequency {
  muscle_group: MuscleGroup;
  workout_count: number;
}

export interface StatsSummary {
  workout_count: number;
  completed_set_count: number;
  training_day_count: number;
  total_volume_kg_reps: number | null;
  unknown_load_set_count: number;
  volume_complete: boolean;
  muscle_group_frequency: MuscleGroupFrequency[];
  current_week_streak: number;
}

export interface StatsSummaryQuery {
  date_from?: string;
  date_to?: string;
}

/** One validation entry of a problem document (field path + safe message). */
export interface ValidationProblemEntry {
  field: string;
  message: string;
}

/** Typed shape of every non-success response. */
export interface ApiProblem {
  status: number;
  code: string;
  title: string;
  detail: string;
  requestId: string | null;
  /** Parsed `Retry-After` header in seconds, preserved for callers. */
  retryAfterSeconds: number | null;
  validationErrors: ValidationProblemEntry[];
  /** Conflict member of the save/delete protocol, when present. */
  currentRevision: number | null;
}

/** Fallback code for malformed/non-JSON responses (e.g. gateway errors). */
export const MALFORMED_RESPONSE_CODE = 'malformed_response';

/** An HTTP failure carrying the parsed (or fallback) problem document. */
export class ApiRequestError extends Error {
  readonly problem: ApiProblem;

  constructor(problem: ApiProblem) {
    super(problem.detail || problem.title);
    this.name = 'ApiRequestError';
    this.problem = problem;
  }
}

/** A transport failure: the request never produced an HTTP response. */
export class ApiNetworkError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = 'ApiNetworkError';
  }
}

const API_BASE = '/api/v1';
type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

interface EndpointOptions {
  query?: URLSearchParams;
  /** JSON-serializable body; `undefined` sends no body. */
  body?: unknown;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: URLSearchParams): string {
  const url = `${API_BASE}${path}`;
  if (query === undefined || query.size === 0) {
    return url;
  }
  return `${url}?${query.toString()}`;
}

function retryAfterSecondsOf(response: Response): number | null {
  const raw = response.headers.get('Retry-After');
  if (raw === null) {
    return null;
  }
  const seconds = Number.parseInt(raw, 10);
  return Number.isSafeInteger(seconds) && seconds >= 0 ? seconds : null;
}

function fallbackProblem(
  status: number,
  retryAfterSeconds: number | null,
): ApiProblem {
  // Explicit fallback for malformed/non-JSON gateway responses. It never
  // embeds the raw body, submitted credentials, or payloads.
  return {
    status,
    code: MALFORMED_RESPONSE_CODE,
    title: 'Request failed',
    detail: 'The server response could not be read',
    requestId: null,
    retryAfterSeconds,
    validationErrors: [],
    currentRevision: null,
  };
}

function stringMember(
  record: Record<string, unknown>,
  key: string,
): string | null {
  const value = record[key];
  return typeof value === 'string' ? value : null;
}

function parseValidationErrors(value: unknown): ValidationProblemEntry[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const entries: ValidationProblemEntry[] = [];
  for (const item of value) {
    if (typeof item !== 'object' || item === null) {
      continue;
    }
    const record = item as Record<string, unknown>;
    const field = stringMember(record, 'field');
    const message = stringMember(record, 'message');
    if (field !== null && message !== null) {
      entries.push({ field, message });
    }
  }
  return entries;
}

function parseProblemBody(
  body: unknown,
  status: number,
  retryAfterSeconds: number | null,
): ApiProblem {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return fallbackProblem(status, retryAfterSeconds);
  }
  const record = body as Record<string, unknown>;
  const currentRevision = record['current_revision'];
  return {
    status,
    code: stringMember(record, 'code') ?? 'error',
    title: stringMember(record, 'title') ?? 'Request failed',
    detail: stringMember(record, 'detail') ?? '',
    requestId: stringMember(record, 'request_id'),
    retryAfterSeconds,
    validationErrors: parseValidationErrors(record['errors']),
    currentRevision:
      typeof currentRevision === 'number' &&
      Number.isSafeInteger(currentRevision)
        ? currentRevision
        : null,
  };
}

async function toProblem(response: Response): Promise<ApiProblem> {
  const retryAfterSeconds = retryAfterSecondsOf(response);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return fallbackProblem(response.status, retryAfterSeconds);
  }
  return parseProblemBody(body, response.status, retryAfterSeconds);
}

async function performFetch(
  method: HttpMethod,
  url: string,
  body: unknown,
  signal: AbortSignal | undefined,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    // The backend checks Content-Type on every mutating verb, including
    // bodyless logout and DELETE.
    headers['Content-Type'] = 'application/json';
  }
  try {
    return await fetch(url, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      // Callers that pass a signal recognize their own aborts; rethrow as-is.
      throw error;
    }
    throw new ApiNetworkError('The request could not be completed', {
      cause: error,
    });
  }
}

async function sendJson<T>(
  method: HttpMethod,
  path: string,
  options: EndpointOptions = {},
): Promise<T> {
  const response = await performFetch(
    method,
    buildUrl(path, options.query),
    options.body,
    options.signal,
  );
  if (!response.ok) {
    throw new ApiRequestError(await toProblem(response));
  }
  if (response.status === 204) {
    // Bodyless success; never JSON-parsed.
    return undefined as T;
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiRequestError(
      fallbackProblem(response.status, retryAfterSecondsOf(response)),
    );
  }
}

async function sendNoContent(
  method: HttpMethod,
  path: string,
  options: EndpointOptions = {},
): Promise<void> {
  const response = await performFetch(
    method,
    buildUrl(path, options.query),
    options.body,
    options.signal,
  );
  if (!response.ok) {
    throw new ApiRequestError(await toProblem(response));
  }
}

function listQuery(
  params: Array<[string, string | number | undefined]>,
): URLSearchParams {
  const query = new URLSearchParams();
  for (const [name, value] of params) {
    if (value !== undefined && value !== '') {
      query.set(name, String(value));
    }
  }
  return query;
}

// --- Auth -----------------------------------------------------------------

/** POST /auth/register: create an account (never logs the user in). */
export function registerUser(
  input: RegisterInput,
  signal?: AbortSignal,
): Promise<PublicUser> {
  return sendJson<PublicUser>('POST', '/auth/register', {
    body: input,
    signal,
  });
}

/** POST /auth/login: verify credentials; the server sets the HttpOnly cookie. */
export function login(
  input: LoginInput,
  signal?: AbortSignal,
): Promise<PublicUser> {
  return sendJson<PublicUser>('POST', '/auth/login', { body: input, signal });
}

/** POST /auth/logout: bodyless mutation answered with an empty 204. */
export function logout(signal?: AbortSignal): Promise<void> {
  return sendNoContent('POST', '/auth/logout', { signal });
}

/** GET /auth/me: the current session's public user, or a 401 problem. */
export function fetchCurrentUser(signal?: AbortSignal): Promise<PublicUser> {
  return sendJson<PublicUser>('GET', '/auth/me', { signal });
}

// --- Exercise catalog ------------------------------------------------------

/** GET /exercises: one bounded page of defaults plus the caller's customs. */
export function listExercises(
  query: ExerciseListQuery = {},
  signal?: AbortSignal,
): Promise<ExercisePage> {
  const params = listQuery([
    ['page', query.page],
    // The query name is `pageSize` while the response member is `page_size`.
    ['pageSize', query.pageSize],
    ['search', query.search],
    ['muscle_group', query.muscle_group],
    ['equipment', query.equipment],
  ]);
  return sendJson<ExercisePage>('GET', '/exercises', { query: params, signal });
}

/** POST /exercises: create an owner-private custom entry. */
export function createExercise(
  input: ExerciseCreateInput,
  signal?: AbortSignal,
): Promise<Exercise> {
  return sendJson<Exercise>('POST', '/exercises', { body: input, signal });
}

/** PATCH /exercises/{id}: partial update of the caller's custom entry. */
export function updateExercise(
  exerciseId: string,
  patch: ExerciseUpdateInput,
  signal?: AbortSignal,
): Promise<Exercise> {
  return sendJson<Exercise>(
    'PATCH',
    `/exercises/${encodeURIComponent(exerciseId)}`,
    {
      body: patch,
      signal,
    },
  );
}

/** DELETE /exercises/{id}: bodyless mutation answered with an empty 204. */
export function deleteExercise(
  exerciseId: string,
  signal?: AbortSignal,
): Promise<void> {
  return sendNoContent(
    'DELETE',
    `/exercises/${encodeURIComponent(exerciseId)}`,
    { signal },
  );
}

// --- Workouts and statistics ------------------------------------------------

/** GET /workouts: the caller's history page, newest first. */
export function listWorkouts(
  query: WorkoutListQuery = {},
  signal?: AbortSignal,
): Promise<WorkoutPage> {
  const params = listQuery([
    ['page', query.page],
    ['pageSize', query.pageSize],
    ['status', query.status],
    ['date_from', query.date_from],
    ['date_to', query.date_to],
  ]);
  return sendJson<WorkoutPage>('GET', '/workouts', { query: params, signal });
}

/** GET /stats/summary: bounded statistics for inclusive local-date bounds. */
export function fetchStatsSummary(
  query: StatsSummaryQuery = {},
  signal?: AbortSignal,
): Promise<StatsSummary> {
  const params = listQuery([
    ['date_from', query.date_from],
    ['date_to', query.date_to],
  ]);
  return sendJson<StatsSummary>('GET', '/stats/summary', {
    query: params,
    signal,
  });
}
