import { describe, expect, it, vi } from 'vitest';

const { getDraftMock, listCreatesMock, prepareCreateMock, sendCreateMock } =
  vi.hoisted(() => ({
    getDraftMock: vi.fn(),
    listCreatesMock: vi.fn(),
    prepareCreateMock: vi.fn(),
    sendCreateMock: vi.fn(),
  }));

vi.mock('../../db', () => ({
  createDraftId: vi.fn(() => 'new-id'),
  openDraftStorage: vi.fn(async () => ({})),
  openDurableDraftStorage: vi.fn(async () => ({})),
  DraftRepository: class {
    get = getDraftMock;
    delete = vi.fn();
  },
  PendingDraftRepository: class {
    listCreates = listCreatesMock;
    prepareCreate = prepareCreateMock;
    discardPending = vi.fn();
  },
}));

vi.mock('../drafts/sync', () => ({
  DraftSyncCoordinator: class {
    sendCreate = sendCreateMock;
  },
}));

import { startSession } from './startSession';

describe('startSession', () => {
  it('retries a durable unresolved start instead of creating another draft', async () => {
    const draft = {
      account_id: 'account-1',
      workout_id: 'workout-1',
      draft_id: 'draft-1',
      base_detail_id: 'workout-1',
      base_revision: 0,
      started_at: '2026-01-01T00:00:00Z',
      content: {
        name: null,
        notes: null,
        bodyweight_kg: null,
        ended_at: null,
        exercises: [],
        raw_fields: {},
        recorded_load_snapshots: {},
        provisional_load_snapshots: {},
      },
      change_number: 0,
      acknowledged_change_number: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    listCreatesMock.mockResolvedValue([
      {
        account_id: draft.account_id,
        draft_id: draft.draft_id,
        workout_id: draft.workout_id,
        request: {
          id: draft.workout_id,
          started_at: draft.started_at,
          session_type: 'freestyle',
        },
        prepared_change_number: 0,
        created_at: draft.created_at,
      },
    ]);
    getDraftMock.mockResolvedValue(draft);
    sendCreateMock.mockResolvedValue(undefined);

    await expect(startSession(draft.account_id)).resolves.toEqual(draft);

    expect(prepareCreateMock).not.toHaveBeenCalled();
    expect(sendCreateMock).toHaveBeenCalledOnce();
    expect(getDraftMock).toHaveBeenNthCalledWith(
      1,
      draft.account_id,
      draft.workout_id,
      draft.draft_id,
    );
  });
});
