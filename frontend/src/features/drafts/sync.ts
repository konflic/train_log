import type {
  ExerciseNode,
  SaveExerciseInput,
  WorkoutDetail,
  WorkoutCreateInput,
} from '../../api';
import {
  PendingDraftRepository,
  type EditableWorkoutContent,
  type LoadSnapshot,
  type PendingCreate,
  type PendingSave,
  type WorkoutDraft,
} from '../../db';

export interface WorkoutSyncApi {
  create(input: WorkoutCreateInput): Promise<WorkoutDetail>;
  get(workoutId: string): Promise<WorkoutDetail>;
  save(
    workoutId: string,
    input: PendingSave['payload'],
  ): Promise<WorkoutDetail>;
}

export type SyncState =
  | 'idle'
  | 'persisting'
  | 'ready'
  | 'sending'
  | 'acknowledging'
  | 'acknowledged'
  | 'dirty'
  | 'paused';

/**
 * Coordinates one draft at a time. It deliberately has no retry timer: Stage
 * 11c owns reconnect ordering and user choices for paused requests.
 */
export class DraftSyncCoordinator {
  state: SyncState = 'idle';
  error: unknown = null;
  private running = false;
  private operation = 0;

  constructor(
    private readonly accountId: string,
    private readonly draftId: string,
    private readonly operations: PendingDraftRepository,
    private readonly api: WorkoutSyncApi,
  ) {}

  async prepareCreate(draft: WorkoutDraft): Promise<PendingCreate> {
    this.ensureDraft(draft);
    this.state = 'persisting';
    this.error = null;
    try {
      const pending = await this.operations.prepareCreate(
        this.accountId,
        draft,
      );
      this.state = 'ready';
      return pending;
    } catch (error) {
      this.pause(error);
      throw error;
    }
  }

  async prepareSave(draft: WorkoutDraft): Promise<PendingSave> {
    this.ensureDraft(draft);
    this.state = 'persisting';
    this.error = null;
    try {
      const pending = await this.operations.prepareSave(this.accountId, draft);
      this.state = 'ready';
      return pending;
    } catch (error) {
      this.pause(error);
      throw error;
    }
  }

  async sendCreate(): Promise<void> {
    const pending = await this.requireCreate();
    await this.run(async (operation) => {
      this.state = 'sending';
      const detail = await this.api.create(pending.request);
      this.ensureOperation(operation);
      await this.acknowledgeCreate(pending, detail, operation);
    });
  }

  /** Resolve an uncertain POST without regenerating or automatically replaying it. */
  async resolveCreate(): Promise<void> {
    const pending = await this.requireCreate();
    await this.run(async (operation) => {
      this.state = 'sending';
      const detail = await this.api.get(pending.workout_id);
      this.ensureOperation(operation);
      if (
        detail.id !== pending.workout_id ||
        detail.started_at !== pending.request.started_at
      ) {
        throw new Error(
          'The created workout does not match the pending request',
        );
      }
      await this.acknowledgeCreate(pending, detail, operation);
    });
  }

  async sendSave(): Promise<void> {
    const pending = await this.requireSave();
    await this.run(async (operation) => {
      this.state = 'sending';
      const detail = await this.api.save(pending.workout_id, pending.payload);
      this.ensureOperation(operation);
      await this.acknowledgeSave(pending, detail, operation);
    });
  }

  private async acknowledgeCreate(
    pending: PendingCreate,
    detail: WorkoutDetail,
    operation: number,
  ): Promise<void> {
    this.state = 'acknowledging';
    const draft = await this.loadDraft(pending.workout_id);
    this.ensureOperation(operation);
    const next = {
      ...draft,
      base_detail_id: detail.id,
      base_revision: detail.revision,
      started_at: detail.started_at,
      updated_at: new Date().toISOString(),
    };
    // A create response is empty by design. Keep the locally prepared graph and
    // IDs so a reload cannot replace repeat/recovery content with that response.
    await this.operations.acknowledgeCreate(next, pending);
    this.complete(next, pending.prepared_change_number);
  }

  private async acknowledgeSave(
    pending: PendingSave,
    detail: WorkoutDetail,
    operation: number,
  ): Promise<void> {
    if (
      detail.id !== pending.workout_id ||
      detail.last_save_id !== pending.payload.save_id
    ) {
      throw new Error(
        'The save acknowledgement does not match the pending request',
      );
    }
    this.state = 'acknowledging';
    const draft = await this.loadDraft(pending.workout_id);
    this.ensureOperation(operation);
    const newerEdits = draft.change_number > pending.change_number;
    const next: WorkoutDraft = {
      ...draft,
      base_detail_id: detail.id,
      base_revision: detail.revision,
      content: newerEdits
        ? mergeAcknowledgedSnapshots(draft.content, detail.exercises)
        : contentFromDetail(detail, draft.content.raw_fields),
      updated_at: new Date().toISOString(),
    };
    await this.operations.acknowledgeSave(next, pending);
    this.complete(next, pending.change_number);
  }

  private async requireCreate(): Promise<PendingCreate> {
    const pending = await this.operations.getCreate(
      this.accountId,
      this.draftId,
    );
    if (pending === null)
      throw new Error('No pending create exists for this draft');
    return pending;
  }

  private async requireSave(): Promise<PendingSave> {
    const pending = await this.operations.getSave(this.accountId, this.draftId);
    if (pending === null)
      throw new Error('No pending save exists for this draft');
    return pending;
  }

  private async loadDraft(workoutId: string): Promise<WorkoutDraft> {
    const draft = await this.operations.drafts.get(
      this.accountId,
      workoutId,
      this.draftId,
    );
    if (draft === null)
      throw new Error('The editable draft is no longer available');
    return draft;
  }

  private async run(
    action: (operation: number) => Promise<void>,
  ): Promise<void> {
    if (this.running)
      throw new Error('A request is already in flight for this draft');
    this.running = true;
    const operation = ++this.operation;
    this.error = null;
    try {
      await action(operation);
    } catch (error) {
      if (operation === this.operation) this.pause(error);
      throw error;
    } finally {
      if (operation === this.operation) this.running = false;
    }
  }

  private complete(draft: WorkoutDraft, acknowledgedChange: number): void {
    this.state =
      draft.change_number > acknowledgedChange ? 'dirty' : 'acknowledged';
    this.error = null;
  }

  private pause(error: unknown): void {
    this.state = 'paused';
    this.error = error;
  }

  private ensureOperation(operation: number): void {
    if (operation !== this.operation)
      throw new Error('A stale response was ignored');
  }

  private ensureDraft(draft: WorkoutDraft): void {
    if (
      draft.account_id !== this.accountId ||
      draft.draft_id !== this.draftId
    ) {
      throw new Error('The draft does not belong to this coordinator');
    }
  }
}

function contentFromDetail(
  detail: WorkoutDetail,
  rawFields: Record<string, string>,
): EditableWorkoutContent {
  const snapshots: Record<string, LoadSnapshot> = {};
  const exercises = detail.exercises.map((exercise) => {
    snapshots[exercise.id] = snapshotOf(exercise);
    return saveExerciseOf(exercise);
  });
  return {
    name: detail.name,
    notes: detail.notes,
    bodyweight_kg: detail.bodyweight_kg,
    ended_at: detail.ended_at,
    exercises,
    raw_fields: structuredClone(rawFields),
    recorded_load_snapshots: snapshots,
    provisional_load_snapshots: {},
  };
}

function mergeAcknowledgedSnapshots(
  content: EditableWorkoutContent,
  acknowledged: ExerciseNode[],
): EditableWorkoutContent {
  const visible = new Set(content.exercises.map((exercise) => exercise.id));
  const recorded = { ...content.recorded_load_snapshots };
  const provisional = { ...content.provisional_load_snapshots };
  for (const exercise of acknowledged) {
    if (!visible.has(exercise.id)) continue;
    recorded[exercise.id] = snapshotOf(exercise);
    delete provisional[exercise.id];
  }
  return {
    ...content,
    recorded_load_snapshots: recorded,
    provisional_load_snapshots: provisional,
  };
}

function snapshotOf(exercise: ExerciseNode): LoadSnapshot {
  return {
    load_type: exercise.load_type,
    bodyweight_percent: exercise.bodyweight_percent,
    side_count: exercise.side_count,
  };
}

function saveExerciseOf(exercise: ExerciseNode): SaveExerciseInput {
  return {
    id: exercise.id,
    catalog_id: exercise.catalog_id,
    notes: exercise.notes,
    sets: exercise.sets.map((set) => ({
      id: set.id,
      reps: set.reps,
      weight_kg: set.weight_kg,
      bw_percent_override: set.bw_percent_override,
      rpe: set.rpe,
      side: set.side,
      done: set.done,
    })),
  };
}
