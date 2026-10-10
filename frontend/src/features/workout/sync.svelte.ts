import {
  ApiNetworkError,
  ApiRequestError,
  createWorkout,
  deleteWorkout,
  fetchCurrentUser,
  getWorkout,
  saveWorkout,
  type PublicUser,
  type WorkoutDetail,
} from '../../api';
import {
  DraftStorageError,
  type EditableWorkoutContent,
  PendingDraftRepository,
} from '../../db';
import type { LocalDraftEditor } from '../drafts/editor.svelte';
import { DraftSyncCoordinator } from '../drafts/sync';
import { SvelteDate, SvelteSet } from 'svelte/reactivity';
import { contentError, finishBlocker } from './model';

export type EditorSyncStatus =
  | 'saving_local'
  | 'locally_saved'
  | 'syncing'
  | 'synced'
  | 'offline'
  | 'authentication_required'
  | 'conflict'
  | 'finish_pending'
  | 'storage_error'
  | 'correction_required'
  | 'error';

interface WorkoutSyncOptions {
  accountId: string;
  editor: LocalDraftEditor;
  operations: PendingDraftRepository;
  authenticatedAccountId: () => string | null;
  onFinished: () => void;
  onDiscarded: () => void;
  currentUser?: () => Promise<PublicUser>;
  now?: () => string;
}

export type RecoveryStatus = 'idle' | 'loading' | 'ready' | 'deleted' | 'error';

const AUTOSAVE_DELAY_MS = 300;

/** Foreground-only editor scheduling over the durable Stage 11 coordinator. */
export class WorkoutSyncController {
  status = $state<EditorSyncStatus>('locally_saved');
  message = $state<string | null>(null);
  locked = $state(false);
  finishPending = $state(false);
  discarding = $state(false);
  recoveryStatus = $state<RecoveryStatus>('idle');
  serverCopy = $state<WorkoutDetail | null>(null);
  recoveryReason = $state<string | null>(null);

  private readonly accountId: string;
  private readonly editor: LocalDraftEditor;
  private readonly operations: PendingDraftRepository;
  private readonly coordinator: DraftSyncCoordinator;
  private readonly onFinished: () => void;
  private readonly onDiscarded: () => void;
  private readonly currentUser: () => Promise<PublicUser>;
  private readonly now: () => string;
  private readonly writes = new SvelteSet<Promise<void>>();
  // Reactive: `canFinish` reads it, so clearing it when a synchronization
  // settles must re-evaluate dependent UI (the Finish button) immediately.
  private processing = $state.raw<Promise<void> | null>(null);
  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private online = typeof navigator === 'undefined' || navigator.onLine;

  constructor(options: WorkoutSyncOptions) {
    this.accountId = options.accountId;
    this.editor = options.editor;
    this.operations = options.operations;
    this.onFinished = options.onFinished;
    this.onDiscarded = options.onDiscarded;
    this.currentUser = options.currentUser ?? fetchCurrentUser;
    this.now = options.now ?? (() => new SvelteDate().toISOString());
    this.coordinator = new DraftSyncCoordinator(
      options.accountId,
      options.editor.current!.draft_id,
      options.operations,
      { create: createWorkout, get: getWorkout, save: saveWorkout },
      options.authenticatedAccountId,
    );
  }

  get canFinish(): boolean {
    return (
      !this.locked &&
      this.processing === null &&
      this.editor.status === 'saved' &&
      (this.status === 'synced' || this.status === 'locally_saved') &&
      finishBlocker(this.editor.current!.content) === null
    );
  }

  get canReplaceServer(): boolean {
    return (
      this.recoveryStatus === 'ready' &&
      this.serverCopy?.ended_at === null &&
      this.recoveryReason !== 'revision_exhausted'
    );
  }

  async initialize(): Promise<void> {
    const pending = await this.operations.getSave(
      this.accountId,
      this.editor.current!.draft_id,
    );
    if (pending !== null && pending.payload.ended_at !== null) {
      this.finishPending = true;
      this.locked = true;
      this.status = 'finish_pending';
    }
    await this.resume();
  }

  /**
   * Restore an idle status for a reused in-memory editor without any network
   * resume. Used when returning to the active workout from a read-only detour
   * (the exercise-information screen): the editor already holds the user's
   * locally stored input and its prior synchronization state, so re-fetching
   * or re-saving would risk discarding unsynced edits or introducing a write
   * the detour must not cause. A durable pending save is still adopted so a
   * lost response keeps its finish-pending treatment; the next committing
   * action resumes normal synchronization.
   */
  async adoptReusedEditor(): Promise<void> {
    const pending = await this.operations.getSave(
      this.accountId,
      this.editor.current!.draft_id,
    );
    if (pending !== null && pending.payload.ended_at !== null) {
      this.finishPending = true;
      this.locked = true;
      this.status = 'finish_pending';
      return;
    }
    if (!this.online) {
      this.status = 'offline';
      this.message = 'Your work is stored locally, reconnect to synchronize';
      return;
    }
    if (this.editor.status === 'failed') {
      this.status = 'storage_error';
      this.message = 'The latest visible edit is not safely stored yet';
      return;
    }
    this.status = this.hasUnsynchronizedChanges() ? 'locally_saved' : 'synced';
  }

  async commit(content: EditableWorkoutContent): Promise<void> {
    const previousStatus = await this.saveLocal(content);
    if (previousStatus === null) return;
    if (previousStatus === 'correction_required') {
      const validation = contentError(this.editor.current!.content);
      if (validation !== null) {
        this.status = 'correction_required';
        this.message = validation;
        return;
      }
      try {
        await this.operations.replaceSave(
          this.accountId,
          structuredClone(this.editor.current!),
        );
      } catch (error) {
        this.pause(error);
        return;
      }
      this.status = 'syncing';
      await this.synchronize();
      return;
    }
    if (previousStatus === 'authentication_required') {
      this.status = 'authentication_required';
      return;
    }
    this.status = 'locally_saved';
    this.scheduleAutosave();
  }

  async saveLocally(content: EditableWorkoutContent): Promise<void> {
    const previousStatus = await this.saveLocal(content);
    if (previousStatus === null) return;
    if (
      previousStatus === 'authentication_required' ||
      previousStatus === 'offline'
    ) {
      this.status = previousStatus;
      return;
    }
    this.status = 'locally_saved';
  }

  async retryLocalSave(): Promise<void> {
    this.status = 'saving_local';
    await this.editor.retry();
    if (this.editor.status === 'failed') {
      this.status = 'storage_error';
      return;
    }
    this.status = 'locally_saved';
    this.scheduleAutosave();
  }

  private async saveLocal(
    content: EditableWorkoutContent,
  ): Promise<EditorSyncStatus | null> {
    if (this.locked || this.destroyed) return null;
    const previousStatus = this.status;
    this.status = 'saving_local';
    this.message = null;
    const write = this.editor.edit(content);
    this.writes.add(write);
    try {
      await write;
    } finally {
      this.writes.delete(write);
    }
    if (this.editor.status === 'failed') {
      this.status = 'storage_error';
      this.message = 'The latest visible edit is not safely stored yet';
      return null;
    }
    return previousStatus;
  }

  async loadRecovery(): Promise<void> {
    if (this.recoveryStatus === 'loading') return;
    this.recoveryStatus = 'loading';
    try {
      this.serverCopy = await this.coordinator.fetchServerCopy();
      this.recoveryStatus = 'ready';
    } catch (error) {
      if (error instanceof ApiRequestError && error.problem.status === 404) {
        this.serverCopy = null;
        this.recoveryStatus = 'deleted';
        return;
      }
      this.message =
        error instanceof Error ? error.message : 'Could not load server copy';
      this.recoveryStatus = 'error';
    }
  }

  async useServerVersion(): Promise<void> {
    try {
      await this.coordinator.useServer();
      const current = this.editor.current!;
      const adopted = await this.operations.drafts.get(
        this.accountId,
        current.workout_id,
        current.draft_id,
      );
      if (!adopted) throw new Error('The server recovery copy is unavailable');
      await this.editor.rebase(adopted);
      this.serverCopy = null;
      this.recoveryStatus = 'idle';
      this.recoveryReason = null;
      if (adopted.content.ended_at !== null) {
        this.onFinished();
        return;
      }
      this.locked = false;
      this.status = 'synced';
      this.message = null;
    } catch (error) {
      this.pause(error);
    }
  }

  async replaceServerVersion(): Promise<void> {
    if (!this.canReplaceServer) return;
    try {
      await this.coordinator.prepareReplacement();
      await this.coordinator.sendSave();
      await this.adoptAcknowledgement();
      this.locked = false;
      this.status = 'synced';
      this.message = null;
      this.serverCopy = null;
      this.recoveryStatus = 'idle';
      this.recoveryReason = null;
    } catch (error) {
      this.pause(error);
      if (this.status === 'conflict') void this.loadRecovery();
    }
  }

  async discardDeletedWorkout(): Promise<void> {
    const draft = this.editor.current!;
    await this.operations.discardPending(this.accountId, draft.draft_id);
    await this.operations.drafts.delete(
      this.accountId,
      draft.workout_id,
      draft.draft_id,
    );
  }

  saveNow(): Promise<void> {
    this.clearAutosave();
    return this.synchronize();
  }

  retry(): Promise<void> {
    return this.editor.status === 'failed'
      ? this.retryLocalSave()
      : this.resume();
  }

  async resume(): Promise<void> {
    if (this.destroyed) return;
    if (!this.online) {
      this.status = this.finishPending ? 'finish_pending' : 'offline';
      this.message = 'Your work is stored locally, reconnect to synchronize';
      return;
    }
    try {
      const user = await this.currentUser();
      if (user.id !== this.accountId) {
        this.locked = true;
        this.status = 'authentication_required';
        this.message = 'Sign in as the owner of this draft to continue';
        return;
      }
      if (this.status === 'authentication_required' && !this.finishPending) {
        this.locked = false;
      }
      const pending = await this.operations.getSave(
        this.accountId,
        this.editor.current!.draft_id,
      );
      if (pending !== null && pending.payload.ended_at !== null) {
        this.finishPending = true;
        this.locked = true;
        this.status = 'finish_pending';
        await this.coordinator.sendSave(true);
        this.finishPending = false;
        this.onFinished();
        return;
      }
      this.status = 'syncing';
      await this.coordinator.resume(user.id);
      if (pending !== null) {
        await this.adoptAcknowledgement();
        // An exact retry is followed by the authoritative lifecycle/revision GET
        // before a newer local payload may be constructed.
        await this.coordinator.resume(user.id);
      }
      if (this.hasUnsynchronizedChanges()) {
        await this.synchronize();
      } else {
        this.status = 'synced';
        this.message = null;
      }
    } catch (error) {
      this.pause(error);
    }
  }

  async finish(): Promise<void> {
    if (!this.canFinish || this.destroyed) return;
    this.clearAutosave();
    this.locked = true;
    await this.flushWrites();
    const validation = contentError(this.editor.current!.content);
    if (validation !== null) {
      this.locked = false;
      this.status = 'correction_required';
      this.message = validation;
      return;
    }
    const content = structuredClone(this.editor.current!.content);
    content.ended_at = canonicalTimestamp(this.now());
    const write = this.editor.edit(content);
    this.writes.add(write);
    try {
      await write;
    } finally {
      this.writes.delete(write);
    }
    if (this.editor.status === 'failed') {
      this.locked = false;
      this.status = 'storage_error';
      this.message = 'The finish is not safe until local storage succeeds';
      return;
    }
    try {
      await this.operations.prepareSave(
        this.accountId,
        structuredClone(this.editor.current!),
      );
      this.finishPending = true;
      this.status = 'finish_pending';
      await this.coordinator.sendSave(true);
      this.finishPending = false;
      this.onFinished();
    } catch (error) {
      this.pause(error);
    }
  }

  /**
   * Cancel the session: delete the server workout at its authoritative
   * revision, then drop the local draft and every pending request. Deletion
   * keeps no receipt to replay, so it needs connectivity; any failure retains
   * the draft and reports through the usual status and message.
   */
  async discard(): Promise<void> {
    if (this.destroyed || this.discarding) return;
    this.clearAutosave();
    if (this.processing !== null) await this.processing;
    this.discarding = true;
    this.locked = true;
    await this.flushWrites();
    const draft = this.editor.current!;
    if (!this.online) {
      this.discarding = false;
      this.locked = false;
      this.status = 'offline';
      this.message =
        'Reconnect to discard this workout, until then it stays stored locally';
      return;
    }
    try {
      await this.deleteServerCopy();
      await this.operations.discardPending(this.accountId, draft.draft_id);
      await this.operations.drafts.delete(
        this.accountId,
        draft.workout_id,
        draft.draft_id,
      );
    } catch (error) {
      this.discarding = false;
      this.locked = false;
      this.pause(error);
      return;
    }
    this.onDiscarded();
  }

  private async deleteServerCopy(): Promise<void> {
    try {
      const detail = await this.coordinator.fetchServerCopy();
      await deleteWorkout(detail.id, detail.revision);
    } catch (error) {
      // An absent row is the intended end state: the workout was never created
      // online, or an earlier deletion succeeded without being observed.
      if (!isAbsentWorkout(error)) throw error;
    }
  }

  setOnline(online: boolean): void {
    this.online = online;
    if (!online) {
      this.status = this.finishPending ? 'finish_pending' : 'offline';
      this.message = 'Your work is stored locally, reconnect to synchronize';
    } else {
      void this.resume();
    }
  }

  destroy(): void {
    this.destroyed = true;
    this.clearAutosave();
  }

  private scheduleAutosave(): void {
    this.clearAutosave();
    this.autosaveTimer = setTimeout(() => {
      this.autosaveTimer = null;
      void this.synchronize();
    }, AUTOSAVE_DELAY_MS);
  }

  private clearAutosave(): void {
    if (this.autosaveTimer !== null) {
      clearTimeout(this.autosaveTimer);
      this.autosaveTimer = null;
    }
  }

  private synchronize(): Promise<void> {
    if (this.processing !== null) return this.processing;
    const processing = this.runSynchronization().finally(() => {
      if (this.processing === processing) this.processing = null;
    });
    this.processing = processing;
    return processing;
  }

  private async runSynchronization(): Promise<void> {
    if (this.destroyed || this.locked) return;
    await this.flushWrites();
    if (this.editor.status === 'failed') {
      this.status = 'storage_error';
      return;
    }
    if (!this.online) {
      this.status = 'offline';
      return;
    }
    const validation = contentError(this.editor.current!.content);
    if (validation !== null) {
      this.status = 'correction_required';
      this.message = validation;
      return;
    }
    try {
      while (this.hasUnsynchronizedChanges() && !this.locked) {
        let pending = await this.operations.getSave(
          this.accountId,
          this.editor.current!.draft_id,
        );
        if (pending === null) {
          pending = await this.coordinator.prepareSave(
            structuredClone(this.editor.current!),
          );
        }
        if (pending.payload.ended_at !== null) {
          this.finishPending = true;
          this.locked = true;
          this.status = 'finish_pending';
          await this.coordinator.sendSave(true);
          this.finishPending = false;
          this.onFinished();
          return;
        }
        this.status = 'syncing';
        this.message = null;
        await this.coordinator.sendSave();
        await this.adoptAcknowledgement();
      }
      this.status = 'synced';
      this.message = null;
    } catch (error) {
      this.pause(error);
    }
  }

  private async adoptAcknowledgement(): Promise<void> {
    const current = this.editor.current!;
    const acknowledged = await this.operations.drafts.get(
      this.accountId,
      current.workout_id,
      current.draft_id,
    );
    if (acknowledged === null) {
      throw new Error('The acknowledged local draft is unavailable');
    }
    await this.editor.rebase(acknowledged);
  }

  private hasUnsynchronizedChanges(): boolean {
    const draft = this.editor.current!;
    return draft.change_number > draft.acknowledged_change_number;
  }

  private async flushWrites(): Promise<void> {
    while (this.writes.size > 0) {
      await Promise.all([...this.writes]);
    }
  }

  private pause(error: unknown): void {
    this.message =
      error instanceof Error ? error.message : 'Synchronization paused';
    if (error instanceof ApiRequestError) {
      this.recoveryReason = error.problem.code;
    }
    if (this.coordinator.recovery === 'authentication_required') {
      this.status = 'authentication_required';
      return;
    }
    if (
      this.coordinator.recovery === 'conflict' ||
      this.coordinator.recovery === 'deleted'
    ) {
      this.locked = true;
      this.status = 'conflict';
      this.recoveryStatus = 'idle';
      return;
    }
    if (this.coordinator.recovery === 'correction_required') {
      this.locked = false;
      this.status = 'correction_required';
      return;
    }
    if (error instanceof ApiNetworkError) {
      this.status = this.finishPending ? 'finish_pending' : 'offline';
      return;
    }
    if (error instanceof ApiRequestError) {
      if (error.problem.status === 401) {
        this.status = 'authentication_required';
        return;
      }
      if (
        error.problem.status === 404 ||
        error.problem.code === 'revision_conflict' ||
        error.problem.code === 'save_id_conflict' ||
        error.problem.code === 'workout_finished' ||
        error.problem.code === 'revision_exhausted'
      ) {
        this.locked = true;
        this.status = 'conflict';
        this.recoveryStatus = 'idle';
        return;
      }
      if (
        error.problem.status === 422 ||
        error.problem.code === 'graph_conflict' ||
        error.problem.code === 'catalog_unavailable'
      ) {
        this.locked = false;
        this.status = 'correction_required';
        return;
      }
      if (error.problem.status === 429 || error.problem.status >= 500) {
        this.status = this.finishPending ? 'finish_pending' : 'offline';
        return;
      }
    }
    if (error instanceof DraftStorageError) {
      this.status = 'storage_error';
      return;
    }
    this.status = 'error';
  }
}

/** A 404 means the owned workout row is already gone. */
function isAbsentWorkout(error: unknown): boolean {
  return error instanceof ApiRequestError && error.problem.status === 404;
}

function canonicalTimestamp(value: string): string {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) throw new Error('Invalid finish time');
  return new Date(Math.floor(milliseconds / 1000) * 1000)
    .toISOString()
    .replace('.000Z', 'Z');
}
