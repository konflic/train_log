import { createWorkout, getWorkout, saveWorkout } from '../../api';
import {
  DraftRepository,
  openDraftStorage,
  openDurableDraftStorage,
  PendingDraftRepository,
  type WorkoutDraft,
} from '../../db';
import { DraftSyncCoordinator } from '../drafts/sync';

export interface LocalWork {
  drafts: WorkoutDraft[];
  dirty: boolean;
}

export async function inspectLocalWork(accountId: string): Promise<LocalWork> {
  const repository = new DraftRepository(await openDraftStorage());
  const result = await repository.listByAccount(accountId);
  return {
    drafts: result.drafts,
    dirty: result.drafts.some(
      (draft) => draft.change_number > draft.acknowledged_change_number,
    ),
  };
}

/** Synchronize each stored draft through the same durable coordinator as the editor. */
export async function synchronizeLocalWork(accountId: string): Promise<void> {
  const repository = new DraftRepository(await openDraftStorage());
  const page = await repository.listByAccount(accountId);
  if (page.drafts.length === 0) return;
  const storage = await openDurableDraftStorage();
  for (const draft of page.drafts) {
    const operations = new PendingDraftRepository(repository, storage);
    const coordinator = new DraftSyncCoordinator(
      accountId,
      draft.draft_id,
      operations,
      { create: createWorkout, get: getWorkout, save: saveWorkout },
      () => accountId,
    );
    await coordinator.resume(accountId);
    const current = await repository.get(
      accountId,
      draft.workout_id,
      draft.draft_id,
    );
    if (
      current !== null &&
      current.change_number > current.acknowledged_change_number
    ) {
      await coordinator.prepareSave(current);
      await coordinator.sendSave();
    }
  }
}
