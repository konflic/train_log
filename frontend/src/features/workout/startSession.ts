import {
  ApiRequestError,
  createWorkout,
  getWorkout,
  type WorkoutCreateInput,
} from '../../api';
import {
  createDraftId,
  DraftRepository,
  openDraftStorage,
  openDurableDraftStorage,
  PendingDraftRepository,
  type WorkoutDraft,
} from '../../db';
import { DraftSyncCoordinator } from '../drafts/sync';

export async function startSession(
  accountId: string,
  source?: { planId: string; revision: number },
): Promise<WorkoutDraft> {
  const repository = new DraftRepository(await openDraftStorage());
  const operations = new PendingDraftRepository(
    repository,
    await openDurableDraftStorage(),
  );
  const existing = await pendingDraft(accountId, repository, operations);
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const draft = existing ?? newDraft(accountId, now);
  const coordinator = new DraftSyncCoordinator(
    accountId,
    draft.draft_id,
    operations,
    {
      create: createWorkout,
      get: getWorkout,
      save: async () => getWorkout(draft.workout_id),
    },
    () => accountId,
  );
  const request: WorkoutCreateInput = source
    ? {
        id: draft.workout_id,
        started_at: now,
        session_type: 'from_plan',
        source_plan_id: source.planId,
        source_plan_revision: source.revision,
      }
    : {
        id: draft.workout_id,
        started_at: now,
        session_type: 'freestyle',
      };
  if (existing === null)
    await operations.prepareCreate(accountId, draft, request);
  try {
    await coordinator.sendCreate();
  } catch (error) {
    if (
      error instanceof ApiRequestError &&
      [
        'active_session_exists',
        'create_conflict',
        'plan_revision_conflict',
        'plan_unavailable',
      ].includes(error.problem.code)
    ) {
      try {
        await operations.discardPending(accountId, draft.draft_id);
        await repository.delete(accountId, draft.workout_id, draft.draft_id);
      } catch {
        // Keep the server's classified rejection visible; recovery storage is
        // still retained if its cleanup could not be confirmed.
      }
    }
    throw error;
  }
  const acknowledged = await repository.get(
    accountId,
    draft.workout_id,
    draft.draft_id,
  );
  if (acknowledged === null)
    throw new Error('The started session is unavailable.');
  return acknowledged;
}

function newDraft(accountId: string, now: string): WorkoutDraft {
  const workoutId = createDraftId();
  return {
    account_id: accountId,
    workout_id: workoutId,
    draft_id: createDraftId(),
    base_detail_id: workoutId,
    base_revision: 0,
    started_at: now,
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
    created_at: now,
    updated_at: now,
  };
}

async function pendingDraft(
  accountId: string,
  repository: DraftRepository,
  operations: PendingDraftRepository,
): Promise<WorkoutDraft | null> {
  const pendingCreates = await operations.listCreates(accountId);
  for (const pending of pendingCreates.sort((left, right) =>
    left.created_at.localeCompare(right.created_at),
  )) {
    const draft = await repository.get(
      accountId,
      pending.workout_id,
      pending.draft_id,
    );
    if (draft !== null) return draft;
  }
  return null;
}
