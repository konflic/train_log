/**
 * Versioned IndexedDB storage for local workout drafts. Network requests and
 * complete, account-scoped editable draft values and the one durable request
 * each draft may need while its server acknowledgement is uncertain.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type {
  LoadType,
  SaveExerciseInput,
  SaveWorkoutInput,
  WorkoutCreateInput,
} from './api';

const DATABASE_NAME = 'basefit-drafts';
const DATABASE_VERSION = 2;
const DRAFT_STORE = 'drafts';
const PENDING_CREATE_STORE = 'pending_creates';
const PENDING_SAVE_STORE = 'pending_saves';

export type DraftKey = [accountId: string, workoutId: string, draftId: string];

export interface LoadSnapshot {
  load_type: LoadType;
  bodyweight_percent: number | null;
  side_count: number;
}

/** The local-only data needed to build a later full-graph save request. */
export interface EditableWorkoutContent {
  name: string | null;
  notes: string | null;
  bodyweight_kg: number | null;
  ended_at: string | null;
  exercises: SaveExerciseInput[];
  raw_fields: Record<string, string>;
  recorded_load_snapshots: Record<string, LoadSnapshot>;
  provisional_load_snapshots: Record<string, LoadSnapshot>;
}

export interface WorkoutDraft {
  account_id: string;
  workout_id: string;
  draft_id: string;
  base_detail_id: string;
  base_revision: number;
  started_at: string;
  content: EditableWorkoutContent;
  change_number: number;
  acknowledged_change_number: number;
  created_at: string;
  updated_at: string;
}

/** Immutable POST content retained until the original create is acknowledged. */
export interface PendingCreate {
  account_id: string;
  draft_id: string;
  workout_id: string;
  request: WorkoutCreateInput;
  prepared_change_number: number;
  created_at: string;
}

/** Immutable PUT content retained until its exact save receipt is acknowledged. */
export interface PendingSave {
  account_id: string;
  draft_id: string;
  workout_id: string;
  change_number: number;
  payload: SaveWorkoutInput;
  created_at: string;
}

export interface DraftList {
  drafts: WorkoutDraft[];
  unavailable_count: number;
  next_key: DraftKey | null;
}

export interface DraftPageOptions {
  after?: DraftKey;
  limit?: number;
}

export interface StoredDraftPage {
  values: unknown[];
  next_key: DraftKey | null;
}

export class DraftStorageError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = 'DraftStorageError';
  }
}

export class MalformedDraftError extends Error {
  constructor() {
    super('A saved draft is malformed and cannot be recovered');
    this.name = 'MalformedDraftError';
  }
}

export interface DraftStorage {
  put(draft: WorkoutDraft): Promise<void>;
  get(key: DraftKey): Promise<unknown | undefined>;
  listByAccount(
    accountId: string,
    options?: DraftPageOptions,
  ): Promise<StoredDraftPage>;
  listByAccountWorkout(
    accountId: string,
    workoutId: string,
    options?: DraftPageOptions,
  ): Promise<StoredDraftPage>;
  delete(key: DraftKey): Promise<void>;
  deleteAccount(accountId: string): Promise<void>;
  close(): void;
}

interface DraftDatabaseSchema extends DBSchema {
  drafts: {
    key: DraftKey;
    value: WorkoutDraft;
    indexes: {
      'by-account': string;
      'by-account-workout': [string, string];
    };
  };
  pending_creates: {
    key: [accountId: string, draftId: string];
    value: PendingCreate;
    indexes: { 'by-account': string; 'by-account-draft': [string, string] };
  };
  pending_saves: {
    key: [accountId: string, draftId: string];
    value: PendingSave;
    indexes: { 'by-account': string; 'by-account-draft': [string, string] };
  };
}

export interface DurableDraftStorage {
  putCreate(draft: WorkoutDraft, pending: PendingCreate): Promise<void>;
  putSave(pending: PendingSave): Promise<void>;
  listCreates(accountId: string): Promise<PendingCreate[]>;
  getCreate(
    accountId: string,
    draftId: string,
  ): Promise<PendingCreate | undefined>;
  getSave(accountId: string, draftId: string): Promise<PendingSave | undefined>;
  acknowledgeCreate(draft: WorkoutDraft, pending: PendingCreate): Promise<void>;
  acknowledgeSave(draft: WorkoutDraft, pending: PendingSave): Promise<void>;
  acknowledgeFinish(pending: PendingSave): Promise<void>;
  adoptServer(draft: WorkoutDraft): Promise<void>;
  replaceSave(draft: WorkoutDraft, pending: PendingSave): Promise<void>;
  discardPending(accountId: string, draftId: string): Promise<void>;
}

class IndexedDbDraftStorage implements DraftStorage, DurableDraftStorage {
  constructor(private readonly database: IDBPDatabase<DraftDatabaseSchema>) {}

  async put(draft: WorkoutDraft): Promise<void> {
    await this.database.put(DRAFT_STORE, draft);
  }

  get(key: DraftKey): Promise<WorkoutDraft | undefined> {
    return this.database.get(DRAFT_STORE, key);
  }

  listByAccount(
    accountId: string,
    options: DraftPageOptions = {},
  ): Promise<StoredDraftPage> {
    return this.page(accountId, undefined, options);
  }

  listByAccountWorkout(
    accountId: string,
    workoutId: string,
    options: DraftPageOptions = {},
  ): Promise<StoredDraftPage> {
    return this.page(accountId, workoutId, options);
  }

  private async page(
    accountId: string,
    workoutId: string | undefined,
    options: DraftPageOptions,
  ): Promise<StoredDraftPage> {
    const limit = options.limit ?? 100;
    if (
      !isNonEmptyString(accountId) ||
      (workoutId !== undefined && !isNonEmptyString(workoutId)) ||
      !Number.isInteger(limit) ||
      limit < 1 ||
      limit > 100 ||
      (options.after &&
        (options.after.length !== 3 ||
          !options.after.every(isNonEmptyString) ||
          options.after[0] !== accountId ||
          (workoutId !== undefined && options.after[1] !== workoutId)))
    ) {
      throw new DraftStorageError('Invalid recovery page');
    }
    // Compound primary keys give bounded, stable pagination even if a record's
    // display timestamp changes. Never load every graph in an account at once.
    const prefix =
      workoutId === undefined ? [accountId] : [accountId, workoutId];
    const range = IDBKeyRange.bound(
      options.after ?? prefix,
      [...prefix, []],
      Boolean(options.after),
      true,
    );
    const transaction = this.database.transaction(DRAFT_STORE);
    const [values, keys] = await Promise.all([
      transaction.store.getAll(range, limit + 1),
      transaction.store.getAllKeys(range, limit + 1),
    ]);
    await transaction.done;
    return {
      values: values.slice(0, limit),
      next_key: values.length > limit ? keys[limit - 1] : null,
    };
  }

  async delete(key: DraftKey): Promise<void> {
    await this.database.delete(DRAFT_STORE, key);
  }

  async deleteAccount(accountId: string): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_CREATE_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    const storeNames: Array<
      | typeof DRAFT_STORE
      | typeof PENDING_CREATE_STORE
      | typeof PENDING_SAVE_STORE
    > = [DRAFT_STORE, PENDING_CREATE_STORE, PENDING_SAVE_STORE];
    for (const storeName of storeNames) {
      const store = transaction.objectStore(storeName);
      let cursor = await store.index('by-account').openCursor(accountId);
      while (cursor) {
        await cursor.delete();
        cursor = await cursor.continue();
      }
    }
    await transaction.done;
  }

  close(): void {
    this.database.close();
  }

  async putCreate(draft: WorkoutDraft, pending: PendingCreate): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_CREATE_STORE],
      'readwrite',
    );
    const pendingStore = transaction.objectStore(PENDING_CREATE_STORE);
    const key: [string, string] = [pending.account_id, pending.draft_id];
    if ((await pendingStore.get(key)) !== undefined) {
      transaction.abort();
      throw new DraftStorageError('A create is already pending for this draft');
    }
    await transaction.objectStore(DRAFT_STORE).put(draft);
    await pendingStore.put(pending);
    await transaction.done;
  }

  async putSave(pending: PendingSave): Promise<void> {
    const transaction = this.database.transaction(
      PENDING_SAVE_STORE,
      'readwrite',
    );
    const store = transaction.objectStore(PENDING_SAVE_STORE);
    const key: [string, string] = [pending.account_id, pending.draft_id];
    if ((await store.get(key)) !== undefined) {
      transaction.abort();
      throw new DraftStorageError('A save is already pending for this draft');
    }
    await store.put(pending);
    await transaction.done;
  }

  listCreates(accountId: string): Promise<PendingCreate[]> {
    return this.database.getAllFromIndex(
      PENDING_CREATE_STORE,
      'by-account',
      accountId,
    );
  }

  getCreate(
    accountId: string,
    draftId: string,
  ): Promise<PendingCreate | undefined> {
    return this.database.get(PENDING_CREATE_STORE, [accountId, draftId]);
  }

  getSave(
    accountId: string,
    draftId: string,
  ): Promise<PendingSave | undefined> {
    return this.database.get(PENDING_SAVE_STORE, [accountId, draftId]);
  }

  async acknowledgeCreate(
    draft: WorkoutDraft,
    pending: PendingCreate,
  ): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_CREATE_STORE],
      'readwrite',
    );
    const pendingStore = transaction.objectStore(PENDING_CREATE_STORE);
    const stored = await pendingStore.get([
      pending.account_id,
      pending.draft_id,
    ]);
    if (!samePendingCreate(stored, pending)) {
      transaction.abort();
      throw new DraftStorageError('The pending create no longer matches');
    }
    await transaction.objectStore(DRAFT_STORE).put(draft);
    await pendingStore.delete([pending.account_id, pending.draft_id]);
    await transaction.done;
  }

  async acknowledgeSave(
    draft: WorkoutDraft,
    pending: PendingSave,
  ): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    const pendingStore = transaction.objectStore(PENDING_SAVE_STORE);
    const stored = await pendingStore.get([
      pending.account_id,
      pending.draft_id,
    ]);
    if (!samePendingSave(stored, pending)) {
      transaction.abort();
      throw new DraftStorageError('The pending save no longer matches');
    }
    const draftStore = transaction.objectStore(DRAFT_STORE);
    const storedDraft = await draftStore.get([
      pending.account_id,
      pending.workout_id,
      pending.draft_id,
    ]);
    const acknowledged =
      isWorkoutDraft(storedDraft) &&
      storedDraft.change_number > draft.change_number
        ? mergeAcknowledgedDraft(copyDraft(storedDraft), draft)
        : draft;
    await draftStore.put(acknowledged);
    await pendingStore.delete([pending.account_id, pending.draft_id]);
    await transaction.done;
  }

  async acknowledgeFinish(pending: PendingSave): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    const pendingStore = transaction.objectStore(PENDING_SAVE_STORE);
    const stored = await pendingStore.get([
      pending.account_id,
      pending.draft_id,
    ]);
    if (!samePendingSave(stored, pending)) {
      transaction.abort();
      throw new DraftStorageError('The pending finish no longer matches');
    }
    await transaction
      .objectStore(DRAFT_STORE)
      .delete([pending.account_id, pending.workout_id, pending.draft_id]);
    await pendingStore.delete([pending.account_id, pending.draft_id]);
    await transaction.done;
  }

  async adoptServer(draft: WorkoutDraft): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_CREATE_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    await transaction.objectStore(DRAFT_STORE).put(draft);
    await transaction
      .objectStore(PENDING_CREATE_STORE)
      .delete([draft.account_id, draft.draft_id]);
    await transaction
      .objectStore(PENDING_SAVE_STORE)
      .delete([draft.account_id, draft.draft_id]);
    await transaction.done;
  }

  async replaceSave(draft: WorkoutDraft, pending: PendingSave): Promise<void> {
    const transaction = this.database.transaction(
      [DRAFT_STORE, PENDING_CREATE_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    await transaction.objectStore(DRAFT_STORE).put(draft);
    await transaction
      .objectStore(PENDING_CREATE_STORE)
      .delete([draft.account_id, draft.draft_id]);
    const saves = transaction.objectStore(PENDING_SAVE_STORE);
    await saves.delete([draft.account_id, draft.draft_id]);
    await saves.put(pending);
    await transaction.done;
  }

  async discardPending(accountId: string, draftId: string): Promise<void> {
    const transaction = this.database.transaction(
      [PENDING_CREATE_STORE, PENDING_SAVE_STORE],
      'readwrite',
    );
    await transaction
      .objectStore(PENDING_CREATE_STORE)
      .delete([accountId, draftId]);
    await transaction
      .objectStore(PENDING_SAVE_STORE)
      .delete([accountId, draftId]);
    await transaction.done;
  }
}

let openingStorage: Promise<IndexedDbDraftStorage> | null = null;

/** Open lazily so server-side imports and tests never touch browser storage. */
export function openDraftStorage(): Promise<DraftStorage> {
  if (openingStorage === null) {
    let cancelled = false;
    const opening: Promise<IndexedDbDraftStorage> =
      new Promise<IndexedDbDraftStorage>((resolve, reject) => {
        void openDB<DraftDatabaseSchema>(DATABASE_NAME, DATABASE_VERSION, {
          upgrade(database, oldVersion) {
            if (oldVersion < 1) {
              const store = database.createObjectStore(DRAFT_STORE, {
                keyPath: ['account_id', 'workout_id', 'draft_id'],
              });
              store.createIndex('by-account', 'account_id');
              store.createIndex('by-account-workout', [
                'account_id',
                'workout_id',
              ]);
            }
            if (oldVersion < 2) {
              const creates = database.createObjectStore(PENDING_CREATE_STORE, {
                keyPath: ['account_id', 'draft_id'],
              });
              creates.createIndex('by-account', 'account_id');
              creates.createIndex('by-account-draft', [
                'account_id',
                'draft_id',
              ]);
              const saves = database.createObjectStore(PENDING_SAVE_STORE, {
                keyPath: ['account_id', 'draft_id'],
              });
              saves.createIndex('by-account', 'account_id');
              saves.createIndex('by-account-draft', ['account_id', 'draft_id']);
            }
          },
          blocked() {
            cancelled = true;
            reject(
              new DraftStorageError(
                'Local storage upgrade is blocked. Close other BaseFit tabs and retry.',
              ),
            );
          },
          blocking() {
            void closeDraftStorage();
          },
          terminated() {
            if (openingStorage === opening) openingStorage = null;
          },
        }).then((database) => {
          if (cancelled) {
            database.close();
          } else {
            resolve(new IndexedDbDraftStorage(database));
          }
        }, reject);
      });
    openingStorage = opening;
    // A failed open must not leave a rejected singleton that makes a later
    // explicit retry impossible.
    void opening.catch(() => {
      if (openingStorage === opening) {
        openingStorage = null;
      }
    });
  }
  return openingStorage;
}

/** The durable-operation API is intentionally separate from ordinary draft reads. */
export async function openDurableDraftStorage(): Promise<DurableDraftStorage> {
  return (await openDraftStorage()) as unknown as DurableDraftStorage;
}

/** Tests and future upgrade handling may explicitly release the open handle. */
export async function closeDraftStorage(): Promise<void> {
  const storagePromise = openingStorage;
  if (storagePromise === null) {
    return;
  }
  openingStorage = null;
  const storage = await storagePromise;
  storage.close();
}

function draftKeyOf(draft: WorkoutDraft): DraftKey {
  return [draft.account_id, draft.workout_id, draft.draft_id];
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 100;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && value.length <= 2000);
}

function isNullableSafeInteger(value: unknown): value is number | null {
  return value === null || Number.isSafeInteger(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function fields(value: Record<string, unknown>, names: string): boolean {
  const expected = names.split(' ');
  return (
    Object.keys(value).length === expected.length &&
    expected.every((name) => Object.hasOwn(value, name))
  );
}

function timestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function validGraph(value: unknown): value is SaveExerciseInput[] {
  if (!Array.isArray(value) || value.length > 25) return false;
  const exerciseIds = new Set<string>();
  const setIds = new Set<string>();
  for (const exercise of value) {
    if (
      !isRecord(exercise) ||
      !fields(exercise, 'id catalog_id notes sets') ||
      !isNonEmptyString(exercise.id) ||
      exerciseIds.has(exercise.id) ||
      !isNonEmptyString(exercise.catalog_id) ||
      !isNullableString(exercise.notes) ||
      !Array.isArray(exercise.sets) ||
      exercise.sets.length > 20
    )
      return false;
    exerciseIds.add(exercise.id);
    for (const set of exercise.sets) {
      if (
        !isRecord(set) ||
        !fields(set, 'id reps weight_kg bw_percent_override rpe side done') ||
        !isNonEmptyString(set.id) ||
        setIds.has(set.id) ||
        ![set.reps, set.weight_kg, set.bw_percent_override, set.rpe].every(
          isNullableSafeInteger,
        ) ||
        (set.side !== 'left' &&
          set.side !== 'right' &&
          set.side !== 'bilateral') ||
        typeof set.done !== 'boolean'
      )
        return false;
      setIds.add(set.id);
    }
  }
  return setIds.size <= 250;
}

function hasStringValues(value: unknown): value is Record<string, string> {
  return (
    isRecord(value) &&
    Object.keys(value).length <= 1100 &&
    Object.entries(value).every(
      ([key, item]) =>
        key.length <= 150 && typeof item === 'string' && item.length <= 2000,
    )
  );
}

function hasLoadSnapshots(
  value: unknown,
): value is Record<string, LoadSnapshot> {
  if (!isRecord(value)) {
    return false;
  }
  return (
    Object.keys(value).length <= 25 &&
    Object.values(value).every(
      (item) =>
        isRecord(item) &&
        fields(item, 'load_type bodyweight_percent side_count') &&
        (item['load_type'] === 'single_weight' ||
          item['load_type'] === 'split_weight' ||
          item['load_type'] === 'bodyweight') &&
        (item.bodyweight_percent === null ||
          (typeof item.bodyweight_percent === 'number' &&
            Number.isInteger(item.bodyweight_percent) &&
            item.bodyweight_percent >= 1 &&
            item.bodyweight_percent <= 100)) &&
        (item.side_count === 1 ||
          (item.load_type === 'split_weight' && item.side_count === 2)) &&
        (item.load_type !== 'bodyweight' || item.bodyweight_percent !== null),
    )
  );
}

function snapshotsMatchGraph(
  exercises: SaveExerciseInput[],
  recorded: Record<string, LoadSnapshot>,
  provisional: Record<string, LoadSnapshot>,
): boolean {
  const ids = new Set(exercises.map((exercise) => exercise.id));
  return (
    [...Object.keys(recorded), ...Object.keys(provisional)].every((id) =>
      ids.has(id),
    ) &&
    exercises.every(
      ({ id }) =>
        Object.hasOwn(recorded, id) !== Object.hasOwn(provisional, id),
    )
  );
}

function isWorkoutDraft(value: unknown): value is WorkoutDraft {
  if (!isRecord(value) || !isRecord(value['content'])) {
    return false;
  }
  const content = value['content'];
  const baseRevision = value['base_revision'];
  const changeNumber = value['change_number'];
  const acknowledgedChangeNumber = value['acknowledged_change_number'] ?? 0;
  return (
    (fields(
      value,
      'account_id workout_id draft_id base_detail_id base_revision started_at content change_number acknowledged_change_number created_at updated_at',
    ) ||
      fields(
        value,
        'account_id workout_id draft_id base_detail_id base_revision started_at content change_number created_at updated_at',
      )) &&
    fields(
      content,
      'name notes bodyweight_kg ended_at exercises raw_fields recorded_load_snapshots provisional_load_snapshots',
    ) &&
    isNonEmptyString(value['account_id']) &&
    isNonEmptyString(value['workout_id']) &&
    isNonEmptyString(value['draft_id']) &&
    isNonEmptyString(value['base_detail_id']) &&
    value.base_detail_id === value.workout_id &&
    timestamp(value.started_at) &&
    typeof baseRevision === 'number' &&
    Number.isSafeInteger(baseRevision) &&
    baseRevision >= 0 &&
    typeof changeNumber === 'number' &&
    Number.isSafeInteger(changeNumber) &&
    changeNumber >= 0 &&
    typeof acknowledgedChangeNumber === 'number' &&
    Number.isSafeInteger(acknowledgedChangeNumber) &&
    acknowledgedChangeNumber >= 0 &&
    acknowledgedChangeNumber <= changeNumber &&
    timestamp(value['created_at']) &&
    timestamp(value['updated_at']) &&
    isNullableString(content['name']) &&
    isNullableString(content['notes']) &&
    isNullableSafeInteger(content['bodyweight_kg']) &&
    (content.ended_at === null || timestamp(content.ended_at)) &&
    validGraph(content['exercises']) &&
    hasStringValues(content['raw_fields']) &&
    hasLoadSnapshots(content['provisional_load_snapshots']) &&
    hasLoadSnapshots(content['recorded_load_snapshots']) &&
    snapshotsMatchGraph(
      content.exercises,
      content.recorded_load_snapshots,
      content.provisional_load_snapshots,
    )
  );
}

function copyDraft(draft: WorkoutDraft): WorkoutDraft {
  try {
    return structuredClone({
      ...draft,
      acknowledged_change_number: draft.acknowledged_change_number ?? 0,
    });
  } catch (error) {
    throw new DraftStorageError('Draft data could not be persisted', {
      cause: error,
    });
  }
}

function copyPending<T extends PendingCreate | PendingSave>(pending: T): T {
  try {
    return structuredClone(pending);
  } catch (error) {
    throw new DraftStorageError('Pending request data could not be persisted', {
      cause: error,
    });
  }
}

function mergeAcknowledgedDraft(
  current: WorkoutDraft,
  acknowledged: WorkoutDraft,
): WorkoutDraft {
  const visible = new Set(current.content.exercises.map(({ id }) => id));
  const recorded = { ...current.content.recorded_load_snapshots };
  const provisional = { ...current.content.provisional_load_snapshots };
  for (const [id, snapshot] of Object.entries(
    acknowledged.content.recorded_load_snapshots,
  )) {
    if (!visible.has(id)) continue;
    recorded[id] = snapshot;
    delete provisional[id];
  }
  return {
    ...current,
    base_detail_id: acknowledged.base_detail_id,
    base_revision: acknowledged.base_revision,
    acknowledged_change_number: acknowledged.acknowledged_change_number,
    content: {
      ...current.content,
      recorded_load_snapshots: recorded,
      provisional_load_snapshots: provisional,
    },
  };
}

function validSavePayload(value: unknown): value is SaveWorkoutInput {
  if (!isRecord(value)) return false;
  return (
    fields(
      value,
      'revision save_id name notes bodyweight_kg ended_at exercises',
    ) &&
    typeof value.revision === 'number' &&
    Number.isSafeInteger(value.revision) &&
    value.revision >= 0 &&
    isNonEmptyString(value.save_id) &&
    isNullableString(value.name) &&
    isNullableString(value.notes) &&
    isNullableSafeInteger(value.bodyweight_kg) &&
    (value.ended_at === null || timestamp(value.ended_at)) &&
    validGraph(value.exercises)
  );
}

function isPendingCreate(value: unknown): value is PendingCreate {
  return (
    isRecord(value) &&
    fields(
      value,
      'account_id draft_id workout_id request prepared_change_number created_at',
    ) &&
    isNonEmptyString(value.account_id) &&
    isNonEmptyString(value.draft_id) &&
    isNonEmptyString(value.workout_id) &&
    isRecord(value.request) &&
    (fields(value.request, 'id started_at') ||
      fields(value.request, 'id started_at session_type') ||
      fields(
        value.request,
        'id started_at session_type source_plan_id source_plan_revision',
      )) &&
    value.request.id === value.workout_id &&
    timestamp(value.request.started_at) &&
    (value.request.session_type === undefined ||
      value.request.session_type === 'freestyle' ||
      value.request.session_type === 'from_plan') &&
    typeof value.prepared_change_number === 'number' &&
    Number.isSafeInteger(value.prepared_change_number) &&
    value.prepared_change_number >= 0 &&
    timestamp(value.created_at)
  );
}

function isPendingSave(value: unknown): value is PendingSave {
  return (
    isRecord(value) &&
    fields(
      value,
      'account_id draft_id workout_id change_number payload created_at',
    ) &&
    isNonEmptyString(value.account_id) &&
    isNonEmptyString(value.draft_id) &&
    isNonEmptyString(value.workout_id) &&
    typeof value.change_number === 'number' &&
    Number.isSafeInteger(value.change_number) &&
    value.change_number >= 0 &&
    validSavePayload(value.payload) &&
    timestamp(value.created_at)
  );
}

function samePendingCreate(
  left: PendingCreate | undefined,
  right: PendingCreate,
): boolean {
  return (
    left !== undefined &&
    left.account_id === right.account_id &&
    left.draft_id === right.draft_id &&
    left.workout_id === right.workout_id &&
    sameWorkoutCreateInput(left.request, right.request) &&
    left.prepared_change_number === right.prepared_change_number &&
    left.created_at === right.created_at
  );
}

function sameWorkoutCreateInput(
  left: WorkoutCreateInput,
  right: WorkoutCreateInput,
): boolean {
  return (
    left.id === right.id &&
    left.started_at === right.started_at &&
    left.session_type === right.session_type &&
    left.source_plan_id === right.source_plan_id &&
    left.source_plan_revision === right.source_plan_revision
  );
}

function samePendingSave(
  left: PendingSave | undefined,
  right: PendingSave,
): boolean {
  return (
    left !== undefined &&
    left.account_id === right.account_id &&
    left.draft_id === right.draft_id &&
    left.workout_id === right.workout_id &&
    left.change_number === right.change_number &&
    left.created_at === right.created_at &&
    left.payload.save_id === right.payload.save_id
  );
}

function compareRecoveryDrafts(
  left: WorkoutDraft,
  right: WorkoutDraft,
): number {
  const updated = right.updated_at.localeCompare(left.updated_at);
  if (updated !== 0) {
    return updated;
  }
  return left.draft_id.localeCompare(right.draft_id);
}

/**
 * Scoped draft operations with per-draft write serialization. A failed write
 * does not poison the next explicit retry for that same draft.
 */
export class DraftRepository {
  private readonly writes = new Map<string, Promise<void>>();

  constructor(private readonly storage: DraftStorage) {}

  async put(accountId: string, draft: WorkoutDraft): Promise<WorkoutDraft> {
    if (!isWorkoutDraft(draft) || draft.account_id !== accountId) {
      throw new MalformedDraftError();
    }
    const committedValue = copyDraft(draft);
    const key = JSON.stringify(draftKeyOf(committedValue));
    const previous = this.writes.get(key) ?? Promise.resolve();
    const write = previous
      .catch(() => undefined)
      .then(async () => {
        try {
          await this.storage.put(committedValue);
        } catch (error) {
          throw new DraftStorageError('Draft storage write failed', {
            cause: error,
          });
        }
      });
    this.writes.set(key, write);
    try {
      await write;
      return copyDraft(committedValue);
    } finally {
      if (this.writes.get(key) === write) {
        this.writes.delete(key);
      }
    }
  }

  async get(
    accountId: string,
    workoutId: string,
    draftId: string,
  ): Promise<WorkoutDraft | null> {
    let value: unknown | undefined;
    try {
      value = await this.storage.get([accountId, workoutId, draftId]);
    } catch (error) {
      throw new DraftStorageError('Draft storage read failed', {
        cause: error,
      });
    }
    if (value === undefined) {
      return null;
    }
    if (
      !isWorkoutDraft(value) ||
      value.account_id !== accountId ||
      value.workout_id !== workoutId ||
      value.draft_id !== draftId
    ) {
      throw new MalformedDraftError();
    }
    return copyDraft(value);
  }

  async listByAccount(
    accountId: string,
    options?: DraftPageOptions,
  ): Promise<DraftList> {
    try {
      return this.validList(
        await this.storage.listByAccount(accountId, options),
        accountId,
      );
    } catch (error) {
      throw new DraftStorageError('Draft storage read failed', {
        cause: error,
      });
    }
  }

  async listByAccountWorkout(
    accountId: string,
    workoutId: string,
    options?: DraftPageOptions,
  ): Promise<DraftList> {
    try {
      return this.validList(
        await this.storage.listByAccountWorkout(accountId, workoutId, options),
        accountId,
        workoutId,
      );
    } catch (error) {
      throw new DraftStorageError('Draft storage read failed', {
        cause: error,
      });
    }
  }

  async delete(
    accountId: string,
    workoutId: string,
    draftId: string,
  ): Promise<void> {
    try {
      await this.storage.delete([accountId, workoutId, draftId]);
    } catch (error) {
      throw new DraftStorageError('Draft storage delete failed', {
        cause: error,
      });
    }
  }

  async deleteAccount(accountId: string): Promise<void> {
    try {
      await this.storage.deleteAccount(accountId);
    } catch (error) {
      throw new DraftStorageError('Draft storage delete failed', {
        cause: error,
      });
    }
  }

  private validList(
    page: StoredDraftPage,
    accountId: string,
    workoutId?: string,
  ): DraftList {
    const drafts: WorkoutDraft[] = [];
    let unavailableCount = 0;
    for (const value of page.values) {
      if (
        isRecord(value) &&
        (value.account_id !== accountId ||
          (workoutId !== undefined && value.workout_id !== workoutId))
      )
        continue;
      if (!isWorkoutDraft(value)) {
        unavailableCount += 1;
        continue;
      }
      drafts.push(copyDraft(value));
    }
    drafts.sort(compareRecoveryDrafts);
    return {
      drafts,
      unavailable_count: unavailableCount,
      next_key: page.next_key,
    };
  }
}

/**
 * Keeps the only create and save request for an editor durable. The coordinator
 * owns transport; this class only makes local state transitions atomic.
 */
export class PendingDraftRepository {
  constructor(
    readonly drafts: DraftRepository,
    private readonly storage: DurableDraftStorage,
  ) {}

  async prepareCreate(
    accountId: string,
    draft: WorkoutDraft,
    request: WorkoutCreateInput = {
      id: draft.workout_id,
      started_at: draft.started_at,
      session_type: 'freestyle',
    },
  ): Promise<PendingCreate> {
    if (!isWorkoutDraft(draft) || draft.account_id !== accountId) {
      throw new MalformedDraftError();
    }
    const pending: PendingCreate = {
      account_id: accountId,
      draft_id: draft.draft_id,
      workout_id: draft.workout_id,
      request,
      prepared_change_number: draft.change_number,
      created_at: new Date().toISOString(),
    };
    try {
      await this.storage.putCreate(copyDraft(draft), copyPending(pending));
      return copyPending(pending);
    } catch (error) {
      throw new DraftStorageError('Could not store the create request', {
        cause: error,
      });
    }
  }

  async prepareSave(
    accountId: string,
    draft: WorkoutDraft,
  ): Promise<PendingSave> {
    if (!isWorkoutDraft(draft) || draft.account_id !== accountId) {
      throw new MalformedDraftError();
    }
    const pending: PendingSave = {
      account_id: accountId,
      draft_id: draft.draft_id,
      workout_id: draft.workout_id,
      change_number: draft.change_number,
      payload: {
        revision: draft.base_revision,
        save_id: createDraftId(),
        name: draft.content.name,
        notes: draft.content.notes,
        bodyweight_kg: draft.content.bodyweight_kg,
        ended_at: draft.content.ended_at,
        exercises: draft.content.exercises,
      },
      created_at: new Date().toISOString(),
    };
    try {
      await this.storage.putSave(copyPending(pending));
      return copyPending(pending);
    } catch (error) {
      throw new DraftStorageError('Could not store the save request', {
        cause: error,
      });
    }
  }

  /** Atomically supersede explicitly rejected work with a fresh save attempt. */
  async replaceSave(
    accountId: string,
    draft: WorkoutDraft,
  ): Promise<PendingSave> {
    if (!isWorkoutDraft(draft) || draft.account_id !== accountId) {
      throw new MalformedDraftError();
    }
    const pending = pendingSaveFor(accountId, draft);
    try {
      await this.storage.replaceSave(copyDraft(draft), copyPending(pending));
      return copyPending(pending);
    } catch (error) {
      throw new DraftStorageError('Could not replace the save request', {
        cause: error,
      });
    }
  }

  async getCreate(
    accountId: string,
    draftId: string,
  ): Promise<PendingCreate | null> {
    try {
      const pending = await this.storage.getCreate(accountId, draftId);
      if (pending === undefined) return null;
      if (
        !isPendingCreate(pending) ||
        pending.account_id !== accountId ||
        pending.draft_id !== draftId
      ) {
        throw new MalformedDraftError();
      }
      return copyPending(pending);
    } catch (error) {
      if (error instanceof MalformedDraftError) throw error;
      throw new DraftStorageError('Could not read the create request', {
        cause: error,
      });
    }
  }

  async listCreates(accountId: string): Promise<PendingCreate[]> {
    try {
      const pendingCreates = await this.storage.listCreates(accountId);
      return pendingCreates.map((pending) => {
        if (!isPendingCreate(pending) || pending.account_id !== accountId) {
          throw new MalformedDraftError();
        }
        return copyPending(pending);
      });
    } catch (error) {
      if (error instanceof MalformedDraftError) throw error;
      throw new DraftStorageError('Could not read create requests', {
        cause: error,
      });
    }
  }

  async getSave(
    accountId: string,
    draftId: string,
  ): Promise<PendingSave | null> {
    try {
      const pending = await this.storage.getSave(accountId, draftId);
      if (pending === undefined) return null;
      if (
        !isPendingSave(pending) ||
        pending.account_id !== accountId ||
        pending.draft_id !== draftId
      ) {
        throw new MalformedDraftError();
      }
      return copyPending(pending);
    } catch (error) {
      if (error instanceof MalformedDraftError) throw error;
      throw new DraftStorageError('Could not read the save request', {
        cause: error,
      });
    }
  }

  async acknowledgeCreate(
    draft: WorkoutDraft,
    pending: PendingCreate,
  ): Promise<void> {
    if (
      !isWorkoutDraft(draft) ||
      !isPendingCreate(pending) ||
      draft.account_id !== pending.account_id ||
      draft.draft_id !== pending.draft_id ||
      draft.workout_id !== pending.workout_id
    ) {
      throw new MalformedDraftError();
    }
    try {
      await this.storage.acknowledgeCreate(
        copyDraft(draft),
        copyPending(pending),
      );
    } catch (error) {
      throw new DraftStorageError('Could not acknowledge the create request', {
        cause: error,
      });
    }
  }

  async acknowledgeSave(
    draft: WorkoutDraft,
    pending: PendingSave,
  ): Promise<void> {
    if (
      !isWorkoutDraft(draft) ||
      !isPendingSave(pending) ||
      draft.account_id !== pending.account_id ||
      draft.draft_id !== pending.draft_id ||
      draft.workout_id !== pending.workout_id
    ) {
      throw new MalformedDraftError();
    }
    try {
      await this.storage.acknowledgeSave(
        copyDraft(draft),
        copyPending(pending),
      );
    } catch (error) {
      throw new DraftStorageError('Could not acknowledge the save request', {
        cause: error,
      });
    }
  }

  async acknowledgeFinish(pending: PendingSave): Promise<void> {
    if (!isPendingSave(pending) || pending.payload.ended_at === null) {
      throw new MalformedDraftError();
    }
    try {
      await this.storage.acknowledgeFinish(copyPending(pending));
    } catch (error) {
      throw new DraftStorageError(
        'Could not acknowledge the finished workout',
        {
          cause: error,
        },
      );
    }
  }

  /** Replace local content with a fetched server copy and retire pending work. */
  async adoptServer(draft: WorkoutDraft): Promise<void> {
    if (!isWorkoutDraft(draft) || draft.account_id.length === 0) {
      throw new MalformedDraftError();
    }
    try {
      await this.storage.adoptServer(copyDraft(draft));
    } catch (error) {
      throw new DraftStorageError('Could not store the server recovery copy', {
        cause: error,
      });
    }
  }

  /** Only a confirmed recovery action may retire an immutable failed request. */
  async discardPending(accountId: string, draftId: string): Promise<void> {
    try {
      await this.storage.discardPending(accountId, draftId);
    } catch (error) {
      throw new DraftStorageError('Could not discard the pending request', {
        cause: error,
      });
    }
  }
}

function pendingSaveFor(accountId: string, draft: WorkoutDraft): PendingSave {
  return {
    account_id: accountId,
    draft_id: draft.draft_id,
    workout_id: draft.workout_id,
    change_number: draft.change_number,
    payload: {
      revision: draft.base_revision,
      save_id: createDraftId(),
      name: draft.content.name,
      notes: draft.content.notes,
      bodyweight_kg: draft.content.bodyweight_kg,
      ended_at: draft.content.ended_at,
      exercises: draft.content.exercises,
    },
    created_at: new Date().toISOString(),
  };
}

export class EditorAssociations {
  private readonly activeByWorkout = new Map<string, string>();

  associate(workoutId: string, draftId: string): void {
    const activeDraftId = this.activeByWorkout.get(workoutId);
    if (activeDraftId !== undefined && activeDraftId !== draftId) {
      throw new Error('This tab already has an editor for the workout');
    }
    this.activeByWorkout.set(workoutId, draftId);
  }

  release(workoutId: string, draftId: string): void {
    if (this.activeByWorkout.get(workoutId) === draftId) {
      this.activeByWorkout.delete(workoutId);
    }
  }

  activeDraftId(workoutId: string): string | null {
    return this.activeByWorkout.get(workoutId) ?? null;
  }
}

export function createDraftId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // `randomUUID` requires a secure context, while `getRandomValues` remains
  // available to generate collision-resistant client-side resource IDs on HTTP.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}

export function createRecoveryDraft(source: WorkoutDraft): WorkoutDraft {
  const now = new Date().toISOString();
  return {
    ...copyDraft(source),
    draft_id: createDraftId(),
    created_at: now,
    updated_at: now,
  };
}
