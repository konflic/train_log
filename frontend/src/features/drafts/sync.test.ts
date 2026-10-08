// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  ApiRequestError,
  type ApiProblem,
  type WorkoutDetail,
} from '../../api';
import {
  DraftRepository,
  type DraftKey,
  type DraftStorage,
  type DurableDraftStorage,
  type PendingCreate,
  type PendingSave,
  PendingDraftRepository,
  type StoredDraftPage,
  type WorkoutDraft,
} from '../../db';
import { DraftSyncCoordinator, type WorkoutSyncApi } from './sync';

function draft(overrides: Partial<WorkoutDraft> = {}): WorkoutDraft {
  return {
    account_id: 'account-a',
    workout_id: 'workout-1',
    draft_id: 'draft-1',
    base_detail_id: 'workout-1',
    base_revision: 0,
    started_at: '2026-10-08T10:00:00Z',
    change_number: 0,
    created_at: '2026-10-08T10:00:00.000Z',
    updated_at: '2026-10-08T10:00:00.000Z',
    content: {
      name: 'Workout',
      notes: null,
      bodyweight_kg: null,
      ended_at: null,
      exercises: [
        {
          id: 'exercise-1',
          catalog_id: 'catalog-1',
          notes: null,
          sets: [
            {
              id: 'set-1',
              reps: 8,
              weight_kg: 12,
              bw_percent_override: null,
              rpe: null,
              side: 'bilateral',
              done: false,
            },
          ],
        },
      ],
      raw_fields: {},
      recorded_load_snapshots: {},
      provisional_load_snapshots: {
        'exercise-1': {
          load_type: 'single_weight',
          bodyweight_percent: null,
          side_count: 1,
        },
      },
    },
    ...overrides,
  };
}

function detail(revision: number, saveId: string | null): WorkoutDetail {
  return {
    id: 'workout-1',
    name: 'Workout',
    started_at: '2026-10-08T10:00:00Z',
    ended_at: null,
    notes: null,
    bodyweight_kg: null,
    revision,
    last_save_id: saveId,
    exercises: [
      {
        id: 'exercise-1',
        catalog_id: 'catalog-1',
        order_index: 0,
        notes: null,
        load_type: 'single_weight',
        bodyweight_percent: null,
        side_count: 1,
        sets: [
          {
            id: 'set-1',
            set_index: 0,
            reps: 8,
            weight_kg: 12,
            bw_percent_override: null,
            rpe: null,
            side: 'bilateral',
            done: false,
          },
        ],
        previous_performance: null,
      },
    ],
  };
}

class MemoryStorage implements DraftStorage, DurableDraftStorage {
  readonly drafts = new Map<string, WorkoutDraft>();
  readonly creates = new Map<string, PendingCreate>();
  readonly saves = new Map<string, PendingSave>();
  failAcknowledgement = false;

  private key(...parts: string[]): string {
    return parts.join('\u0000');
  }

  async put(value: WorkoutDraft): Promise<void> {
    this.drafts.set(
      this.key(value.account_id, value.workout_id, value.draft_id),
      structuredClone(value),
    );
  }

  async get(key: DraftKey): Promise<WorkoutDraft | undefined> {
    return this.drafts.get(this.key(...key));
  }

  async listByAccount(): Promise<StoredDraftPage> {
    return { values: [], next_key: null };
  }

  async listByAccountWorkout(): Promise<StoredDraftPage> {
    return { values: [], next_key: null };
  }

  async delete(): Promise<void> {}
  async deleteAccount(): Promise<void> {}
  close(): void {}

  async putCreate(value: WorkoutDraft, pending: PendingCreate): Promise<void> {
    await this.put(value);
    this.creates.set(
      this.key(pending.account_id, pending.draft_id),
      structuredClone(pending),
    );
  }

  async putSave(pending: PendingSave): Promise<void> {
    const key = this.key(pending.account_id, pending.draft_id);
    if (this.saves.has(key)) throw new Error('already pending');
    this.saves.set(key, structuredClone(pending));
  }

  async getCreate(
    accountId: string,
    draftId: string,
  ): Promise<PendingCreate | undefined> {
    return this.creates.get(this.key(accountId, draftId));
  }

  async getSave(
    accountId: string,
    draftId: string,
  ): Promise<PendingSave | undefined> {
    return this.saves.get(this.key(accountId, draftId));
  }

  async acknowledgeCreate(
    value: WorkoutDraft,
    pending: PendingCreate,
  ): Promise<void> {
    if (this.failAcknowledgement) throw new Error('disk full');
    await this.put(value);
    this.creates.delete(this.key(pending.account_id, pending.draft_id));
  }

  async acknowledgeSave(
    value: WorkoutDraft,
    pending: PendingSave,
  ): Promise<void> {
    if (this.failAcknowledgement) throw new Error('disk full');
    await this.put(value);
    this.saves.delete(this.key(pending.account_id, pending.draft_id));
  }

  async adoptServer(value: WorkoutDraft): Promise<void> {
    await this.put(value);
    this.creates.delete(this.key(value.account_id, value.draft_id));
    this.saves.delete(this.key(value.account_id, value.draft_id));
  }

  async replaceSave(value: WorkoutDraft, pending: PendingSave): Promise<void> {
    await this.put(value);
    this.creates.delete(this.key(value.account_id, value.draft_id));
    this.saves.set(
      this.key(pending.account_id, pending.draft_id),
      structuredClone(pending),
    );
  }

  async discardPending(accountId: string, draftId: string): Promise<void> {
    this.creates.delete(this.key(accountId, draftId));
    this.saves.delete(this.key(accountId, draftId));
  }
}

function setup(api: WorkoutSyncApi): {
  storage: MemoryStorage;
  drafts: DraftRepository;
  operations: PendingDraftRepository;
  coordinator: DraftSyncCoordinator;
} {
  const storage = new MemoryStorage();
  const drafts = new DraftRepository(storage);
  const operations = new PendingDraftRepository(drafts, storage);
  return {
    storage,
    drafts,
    operations,
    coordinator: new DraftSyncCoordinator(
      'account-a',
      'draft-1',
      operations,
      api,
    ),
  };
}

describe('DraftSyncCoordinator', () => {
  it('persists an exact save before transport and retires it with its receipt', async () => {
    let sent: PendingSave['payload'] | null = null;
    const { storage, drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async (_workoutId, payload) => {
        sent = structuredClone(payload);
        expect(storage.saves.size).toBe(1);
        return detail(1, payload.save_id);
      },
    });
    const value = draft();
    await drafts.put('account-a', value);
    const pending = await coordinator.prepareSave(value);

    await coordinator.sendSave();

    expect(sent).toEqual(pending.payload);
    expect(storage.saves.size).toBe(0);
    expect(coordinator.state).toBe('acknowledged');
  });

  it('keeps a later edit while acknowledging an earlier immutable save', async () => {
    let release!: () => void;
    const response = new Promise<WorkoutDetail>((resolve) => {
      release = () => resolve(detail(1, pending!.payload.save_id));
    });
    let pending: PendingSave | null = null;
    const { drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async () => response,
    });
    const value = draft();
    await drafts.put('account-a', value);
    pending = await coordinator.prepareSave(value);
    const sending = coordinator.sendSave();
    const newer = draft({ change_number: 1 });
    newer.content.raw_fields['set-1.weight_kg'] = '13';
    await drafts.put('account-a', newer);
    release();
    await sending;

    await expect(
      drafts.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({
      base_revision: 1,
      change_number: 1,
      content: { raw_fields: { 'set-1.weight_kg': '13' } },
    });
    expect(coordinator.state).toBe('dirty');
  });

  it('reuses the persisted payload after a lost save response and coordinator reload', async () => {
    const sent: PendingSave['payload'][] = [];
    const { drafts, operations, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async (_workoutId, payload) => {
        sent.push(structuredClone(payload));
        throw new Error('connection lost after commit');
      },
    });
    const value = draft();
    await drafts.put('account-a', value);
    const pending = await coordinator.prepareSave(value);
    await expect(coordinator.sendSave()).rejects.toThrow('connection lost');

    const reloaded = new DraftSyncCoordinator(
      'account-a',
      'draft-1',
      operations,
      {
        create: async () => detail(0, null),
        get: async () => detail(0, null),
        save: async (_workoutId, payload) => {
          sent.push(structuredClone(payload));
          return detail(1, payload.save_id);
        },
      },
    );
    await reloaded.sendSave();

    expect(sent).toEqual([pending.payload, pending.payload]);
    expect(reloaded.state).toBe('acknowledged');
  });

  it('keeps an acknowledged server save pending when its local acknowledgement fails', async () => {
    const { storage, drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await drafts.put('account-a', draft());
    await coordinator.prepareSave(draft());
    storage.failAcknowledgement = true;

    await expect(coordinator.sendSave()).rejects.toThrow('acknowledge');

    expect(storage.saves.size).toBe(1);
    await expect(
      drafts.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({
      base_revision: 0,
    });
    expect(coordinator.state).toBe('paused');
  });

  it('preserves a prepared graph when a create acknowledgement is empty', async () => {
    const { drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await coordinator.prepareCreate(draft());
    await coordinator.sendCreate();

    await expect(
      drafts.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({
      base_revision: 0,
      content: { exercises: [{ id: 'exercise-1' }] },
    });
  });

  it('resolves a durable create before reading the current workout', async () => {
    const calls: string[] = [];
    const { drafts, operations } = setup({
      create: async () => detail(0, null),
      get: async () => {
        calls.push('get');
        return detail(0, null);
      },
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await drafts.put('account-a', draft());
    const original = new DraftSyncCoordinator(
      'account-a',
      'draft-1',
      operations,
      {
        create: async () => detail(0, null),
        get: async () => detail(0, null),
        save: async (_workoutId, payload) => detail(1, payload.save_id),
      },
    );
    await original.prepareCreate(draft());
    const reloaded = new DraftSyncCoordinator(
      'account-a',
      'draft-1',
      operations,
      {
        create: async () => detail(0, null),
        get: async () => {
          calls.push('get');
          return detail(0, null);
        },
        save: async (_workoutId, payload) => detail(1, payload.save_id),
      },
    );

    await reloaded.resume('account-a');

    expect(calls).toEqual(['get']);
    expect(reloaded.state).toBe('acknowledged');
  });

  it('pauses without a request when another account is authenticated', async () => {
    let requested = false;
    const { drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => {
        requested = true;
        return detail(0, null);
      },
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await drafts.put('account-a', draft());

    await coordinator.resume('account-b');

    expect(requested).toBe(false);
    expect(coordinator.recovery).toBe('authentication_required');
    expect(coordinator.state).toBe('paused');
  });

  it('keeps local work and classifies a stale save as a conflict', async () => {
    const conflict = new ApiRequestError(problem(409, 'revision_conflict'));
    const { drafts, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(0, null),
      save: async () => {
        throw conflict;
      },
    });
    await drafts.put('account-a', draft());
    await coordinator.prepareSave(draft());

    await expect(coordinator.sendSave()).rejects.toBe(conflict);

    expect(coordinator.recovery).toBe('conflict');
    await expect(
      drafts.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({ change_number: 0 });
  });

  it('ignores a delayed save response after an account switch', async () => {
    let resolve!: (value: WorkoutDetail) => void;
    let authenticated = 'account-a';
    const delayed = new Promise<WorkoutDetail>((done) => {
      resolve = done;
    });
    const storage = new MemoryStorage();
    const drafts = new DraftRepository(storage);
    const operations = new PendingDraftRepository(drafts, storage);
    const coordinator = new DraftSyncCoordinator(
      'account-a',
      'draft-1',
      operations,
      {
        create: async () => detail(0, null),
        get: async () => detail(0, null),
        save: async () => delayed,
      },
      () => authenticated,
    );
    await drafts.put('account-a', draft());
    const pending = await coordinator.prepareSave(draft());
    const saving = coordinator.sendSave();
    authenticated = 'account-b';
    resolve(detail(1, pending.payload.save_id));

    await expect(saving).rejects.toThrow('authenticated account changed');

    expect(coordinator.recovery).toBe('authentication_required');
    expect(await operations.getSave('account-a', 'draft-1')).toEqual(pending);
  });

  it('uses the server only through an explicit durable recovery command', async () => {
    const { drafts, operations, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(3, 'server-save'),
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await drafts.put('account-a', draft({ base_revision: 0 }));
    await coordinator.prepareSave(draft({ base_revision: 0 }));

    await coordinator.useServer();

    expect(await operations.getSave('account-a', 'draft-1')).toBeNull();
    await expect(
      drafts.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({ base_revision: 3 });
  });

  it('atomically replaces a rejected save with a new revision and save ID', async () => {
    const { drafts, operations, coordinator } = setup({
      create: async () => detail(0, null),
      get: async () => detail(3, 'server-save'),
      save: async (_workoutId, payload) => detail(1, payload.save_id),
    });
    await drafts.put('account-a', draft({ base_revision: 0 }));
    const rejected = await coordinator.prepareSave(draft({ base_revision: 0 }));

    const replacement = await coordinator.prepareReplacement();

    expect(replacement.payload.revision).toBe(3);
    expect(replacement.payload.save_id).not.toBe(rejected.payload.save_id);
    expect(await operations.getSave('account-a', 'draft-1')).toEqual(
      replacement,
    );
  });
});

function problem(status: number, code: string): ApiProblem {
  return {
    status,
    code,
    title: 'Request failed',
    detail: 'Request failed',
    requestId: null,
    retryAfterSeconds: null,
    validationErrors: [],
    currentRevision: null,
  };
}
