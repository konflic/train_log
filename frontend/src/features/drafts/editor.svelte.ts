import {
  DraftRepository,
  EditorAssociations,
  type EditableWorkoutContent,
  type WorkoutDraft,
} from '../../db';
import { SvelteDate, SvelteMap } from 'svelte/reactivity';

/** Immediate input and durable acknowledgement are separate clocks. */
export class LocalDraftEditor {
  current = $state.raw<WorkoutDraft>();
  savedChange = $state(0);
  status = $state<'saved' | 'saving' | 'failed'>('saved');
  private readonly repository: DraftRepository;

  constructor(repository: DraftRepository, draft: WorkoutDraft) {
    this.repository = repository;
    this.current = structuredClone(draft);
    this.savedChange = draft.change_number;
  }

  async edit(content: EditableWorkoutContent): Promise<void> {
    const current = this.current!;
    if (current.change_number === Number.MAX_SAFE_INTEGER) {
      this.status = 'failed';
      return;
    }
    // Advance before awaiting storage. A second keystroke must build on this
    // input, never on the last committed value or a slower acknowledgement.
    const next = {
      ...current,
      content,
      change_number: current.change_number + 1,
      updated_at: new SvelteDate().toISOString(),
    };
    try {
      this.current = structuredClone(next);
    } catch {
      // Keep the user's in-memory value even when it cannot be cloned. Only a
      // successful repository transaction may turn this into a saved value.
      this.current = next;
      this.status = 'failed';
      return;
    }
    await this.persist(this.current);
  }

  async retry(): Promise<void> {
    await this.persist(this.current!);
  }

  private async persist(value: WorkoutDraft): Promise<void> {
    this.status = 'saving';
    try {
      await this.repository.put(value.account_id, value);
      this.savedChange = Math.max(this.savedChange, value.change_number);
      if (this.current?.change_number === value.change_number) {
        this.status = 'saved';
      }
    } catch {
      if (this.current?.change_number === value.change_number) {
        this.status = 'failed';
      }
    }
  }
}

// The registry is document-local, never restored from cloned sessionStorage.
export const localEditors = new SvelteMap<string, LocalDraftEditor>();
export const editorAssociations = new EditorAssociations();

export function editorKey(accountId: string, workoutId: string): string {
  return JSON.stringify([accountId, workoutId]);
}
