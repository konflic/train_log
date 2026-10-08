// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DraftRepository,
  DraftStorageError,
  EditorAssociations,
  MalformedDraftError,
  createDraftId,
  createRecoveryDraft,
  type DraftKey,
  type DraftPageOptions,
  type StoredDraftPage,
  type DraftStorage,
  type WorkoutDraft,
} from './db';

afterEach(() => {
  vi.unstubAllGlobals();
});

function draft(overrides: Partial<WorkoutDraft> = {}): WorkoutDraft {
  return {
    account_id: 'account-a',
    workout_id: 'workout-1',
    draft_id: 'draft-1',
    base_detail_id: 'workout-1',
    base_revision: 2,
    started_at: '2026-10-08T10:00:00Z',
    change_number: 0,
    acknowledged_change_number: 0,
    created_at: '2026-10-08T10:00:00.000Z',
    updated_at: '2026-10-08T10:00:00.000Z',
    content: {
      name: null,
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
      raw_fields: { 'set-1.reps': '' },
      recorded_load_snapshots: {},
      provisional_load_snapshots: {
        'exercise-1': {
          load_type: 'split_weight',
          bodyweight_percent: null,
          side_count: 2,
        },
      },
    },
    ...overrides,
  };
}

function keyOf(key: DraftKey): string {
  return key.join('\u0000');
}

describe('createDraftId', () => {
  it('falls back to a version 4 UUID when randomUUID needs a secure context', () => {
    vi.stubGlobal('crypto', {
      getRandomValues(bytes: Uint8Array): Uint8Array {
        bytes.fill(0);
        return bytes;
      },
    });

    expect(createDraftId()).toBe('00000000-0000-4000-8000-000000000000');
  });
});

class MemoryDraftStorage implements DraftStorage {
  readonly records = new Map<string, unknown>();

  async put(value: WorkoutDraft): Promise<void> {
    this.records.set(
      keyOf([value.account_id, value.workout_id, value.draft_id]),
      structuredClone(value),
    );
  }

  async get(key: DraftKey): Promise<unknown | undefined> {
    return this.records.get(keyOf(key));
  }

  async listByAccount(
    accountId: string,
    options?: DraftPageOptions,
  ): Promise<StoredDraftPage> {
    const values = Array.from(this.records.values()).filter(
      (value) =>
        typeof value === 'object' &&
        value !== null &&
        (value as { account_id?: unknown }).account_id === accountId,
    );
    return this.page(values, options);
  }

  async listByAccountWorkout(
    accountId: string,
    workoutId: string,
    options?: DraftPageOptions,
  ): Promise<StoredDraftPage> {
    const values = Array.from(this.records.values()).filter(
      (value) =>
        typeof value === 'object' &&
        value !== null &&
        (value as { account_id?: unknown }).account_id === accountId &&
        (value as { workout_id?: unknown }).workout_id === workoutId,
    );
    return this.page(values, options);
  }

  private page(
    values: unknown[],
    options: DraftPageOptions = {},
  ): StoredDraftPage {
    const key = (value: unknown): DraftKey => {
      const record = value as WorkoutDraft;
      return [record.account_id, record.workout_id, record.draft_id];
    };
    const ordered = values
      .sort((a, b) => keyOf(key(a)).localeCompare(keyOf(key(b))))
      .filter(
        (value) => !options.after || keyOf(key(value)) > keyOf(options.after),
      );
    const limit = options.limit ?? 100;
    return {
      values: ordered.slice(0, limit),
      next_key: ordered.length > limit ? key(ordered[limit - 1]) : null,
    };
  }

  async delete(key: DraftKey): Promise<void> {
    this.records.delete(keyOf(key));
  }

  async deleteAccount(accountId: string): Promise<void> {
    for (const [key, value] of this.records) {
      if ((value as { account_id?: unknown }).account_id === accountId) {
        this.records.delete(key);
      }
    }
  }

  close(): void {}
}

function deferred(): {
  promise: Promise<void>;
  resolve: () => void;
} {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('DraftRepository', () => {
  it('scopes recovery lists and deletion to the requested account', async () => {
    const storage = new MemoryDraftStorage();
    const repository = new DraftRepository(storage);
    await repository.put('account-a', draft());
    await repository.put(
      'account-b',
      draft({ account_id: 'account-b', draft_id: 'draft-b' }),
    );

    await expect(repository.listByAccount('account-a')).resolves.toMatchObject({
      drafts: [{ draft_id: 'draft-1' }],
      unavailable_count: 0,
    });
    await repository.deleteAccount('account-a');
    await expect(repository.listByAccount('account-a')).resolves.toMatchObject({
      drafts: [],
    });
    await expect(repository.listByAccount('account-b')).resolves.toMatchObject({
      drafts: [{ draft_id: 'draft-b' }],
    });
  });

  it('orders recovery choices deterministically and keeps malformed values unavailable', async () => {
    const storage = new MemoryDraftStorage();
    const repository = new DraftRepository(storage);
    await repository.put(
      'account-a',
      draft({ draft_id: 'later', updated_at: '2026-10-08T11:00:00.000Z' }),
    );
    await repository.put(
      'account-a',
      draft({ draft_id: 'earlier', updated_at: '2026-10-08T10:00:00.000Z' }),
    );
    storage.records.set(keyOf(['account-a', 'workout-1', 'bad']), {
      account_id: 'account-a',
      workout_id: 'workout-1',
      draft_id: 'bad',
    });

    await expect(
      repository.listByAccountWorkout('account-a', 'workout-1'),
    ).resolves.toEqual({
      drafts: [
        expect.objectContaining({ draft_id: 'later' }),
        expect.objectContaining({ draft_id: 'earlier' }),
      ],
      unavailable_count: 1,
      next_key: null,
    });
    await expect(
      repository.get('account-a', 'workout-1', 'bad'),
    ).rejects.toBeInstanceOf(MalformedDraftError);
  });

  it('serializes writes so an older delayed operation cannot become final', async () => {
    const gate = deferred();
    const storage = new MemoryDraftStorage();
    let firstWrite = true;
    const delayedStorage: DraftStorage = {
      get: (key) => storage.get(key),
      listByAccount: (accountId) => storage.listByAccount(accountId),
      listByAccountWorkout: (accountId, workoutId) =>
        storage.listByAccountWorkout(accountId, workoutId),
      delete: (key) => storage.delete(key),
      deleteAccount: (accountId) => storage.deleteAccount(accountId),
      close: () => storage.close(),
      put: async (value) => {
        if (firstWrite) {
          firstWrite = false;
          await gate.promise;
        }
        await storage.put(value);
      },
    };
    const repository = new DraftRepository(delayedStorage);
    const first = repository.put('account-a', draft({ change_number: 1 }));
    const second = repository.put('account-a', draft({ change_number: 2 }));

    gate.resolve();
    await Promise.all([first, second]);
    await expect(
      repository.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toMatchObject({
      change_number: 2,
    });
  });

  it('does not acknowledge a draft when storage rejects and permits an explicit retry', async () => {
    const storage = new MemoryDraftStorage();
    let rejectOnce = true;
    const failingStorage: DraftStorage = {
      get: (key) => storage.get(key),
      listByAccount: (accountId) => storage.listByAccount(accountId),
      listByAccountWorkout: (accountId, workoutId) =>
        storage.listByAccountWorkout(accountId, workoutId),
      delete: (key) => storage.delete(key),
      deleteAccount: (accountId) => storage.deleteAccount(accountId),
      close: () => storage.close(),
      put: async (value) => {
        if (rejectOnce) {
          rejectOnce = false;
          throw new Error('quota exceeded');
        }
        await storage.put(value);
      },
    };
    const repository = new DraftRepository(failingStorage);

    await expect(repository.put('account-a', draft())).rejects.toBeInstanceOf(
      DraftStorageError,
    );
    await expect(
      repository.get('account-a', 'workout-1', 'draft-1'),
    ).resolves.toBeNull();
    await expect(repository.put('account-a', draft())).resolves.toMatchObject({
      draft_id: 'draft-1',
    });
  });

  it('copies recovery source data into a fresh independent editor draft', () => {
    const source = draft({
      change_number: 4,
      acknowledged_change_number: 2,
    });
    const recovery = createRecoveryDraft(source);
    recovery.content.raw_fields['set-1.reps'] = '12.5';

    expect(recovery.draft_id).not.toBe(source.draft_id);
    expect(recovery.base_revision).toBe(source.base_revision);
    expect(recovery.change_number).toBe(4);
    expect(recovery.acknowledged_change_number).toBe(2);
    expect(source.content.raw_fields['set-1.reps']).toBe('');
    expect(recovery.content.provisional_load_snapshots['exercise-1']).toEqual(
      source.content.provisional_load_snapshots['exercise-1'],
    );
  });

  it('rejects cross-account writes and mismatched records from storage', async () => {
    const storage = new MemoryDraftStorage();
    const repository = new DraftRepository(storage);
    await expect(repository.put('account-b', draft())).rejects.toBeInstanceOf(
      MalformedDraftError,
    );
    storage.records.set(keyOf(['account-b', 'workout-1', 'draft-1']), draft());
    await expect(
      repository.get('account-b', 'workout-1', 'draft-1'),
    ).rejects.toBeInstanceOf(MalformedDraftError);
  });

  it.each([
    (value: WorkoutDraft) => {
      value.content.exercises[0].sets[0].done = 'yes' as unknown as boolean;
    },
    (value: WorkoutDraft) => {
      value.content.exercises[0].sets.push(value.content.exercises[0].sets[0]);
    },
    (value: WorkoutDraft) => {
      value.content.exercises[0].sets[0].reps = 1.5;
    },
    (value: WorkoutDraft) => {
      Object.assign(value, { password: 'not-allowed' });
    },
    (value: WorkoutDraft) => {
      value.content.provisional_load_snapshots['exercise-1'].side_count = 3;
    },
    (value: WorkoutDraft) => {
      value.updated_at = 'not-a-date';
    },
  ])(
    'makes malformed nested records unavailable rather than copying them',
    async (damage) => {
      const value = draft();
      damage(value);
      const storage = new MemoryDraftStorage();
      storage.records.set(keyOf(['account-a', 'workout-1', 'draft-1']), value);
      const repository = new DraftRepository(storage);
      await expect(repository.put('account-a', value)).rejects.toBeInstanceOf(
        MalformedDraftError,
      );
      await expect(repository.listByAccount('account-a')).resolves.toEqual({
        drafts: [],
        unavailable_count: 1,
        next_key: null,
      });
    },
  );

  it('does not acknowledge before commit and owns a full graph snapshot while waiting', async () => {
    const storage = new MemoryDraftStorage();
    const gate = deferred();
    const originalPut = storage.put.bind(storage);
    storage.put = async (value) => {
      await gate.promise;
      await originalPut(value);
    };
    const repository = new DraftRepository(storage);
    const value = draft();
    let acknowledged = false;
    const saving = repository.put('account-a', value).then(() => {
      acknowledged = true;
    });
    value.content.exercises[0].sets[0].weight_kg = 99;
    await Promise.resolve();
    expect(acknowledged).toBe(false);
    gate.resolve();
    await saving;
    const saved = await repository.get('account-a', 'workout-1', 'draft-1');
    expect(saved?.content.exercises[0].sets[0].weight_kg).toBe(12);
    saved!.content.exercises[0].sets[0].weight_kg = 50;
    expect(
      (await repository.get('account-a', 'workout-1', 'draft-1'))?.content
        .exercises[0].sets[0].weight_kg,
    ).toBe(12);
  });
});

describe('EditorAssociations', () => {
  it('permits only one active editor per workout in one tab', () => {
    const associations = new EditorAssociations();
    associations.associate('workout-1', 'draft-1');
    associations.associate('workout-1', 'draft-1');
    expect(() => associations.associate('workout-1', 'draft-2')).toThrow(
      'already has an editor',
    );
    associations.release('workout-1', 'draft-1');
    associations.associate('workout-1', 'draft-2');
    expect(associations.activeDraftId('workout-1')).toBe('draft-2');
  });
});
