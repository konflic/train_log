import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { sendSaveMock, resumeMock } = vi.hoisted(() => ({
  sendSaveMock: vi.fn(async () => {}),
  resumeMock: vi.fn(async () => {}),
}));

vi.mock('../drafts/sync', () => ({
  DraftSyncCoordinator: class {
    recovery = null;
    resume = resumeMock;
    sendSave = sendSaveMock;
    async prepareSave(draft: { content: unknown }) {
      // The durable pending record's payload mirrors the workout content,
      // including its `ended_at` lifecycle marker.
      return { payload: draft.content };
    }
    fetchServerCopy = vi.fn();
    useServer = vi.fn();
    prepareReplacement = vi.fn();
  },
}));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    fetchCurrentUser: vi.fn(async () => ({ id: 'account-1' })),
    createWorkout: vi.fn(),
    getWorkout: vi.fn(),
    saveWorkout: vi.fn(),
    deleteWorkout: vi.fn(),
  };
});

import {
  DraftRepository,
  type EditableWorkoutContent,
  PendingDraftRepository,
  type WorkoutDraft,
} from '../../db';
import { LocalDraftEditor } from '../drafts/editor.svelte';
import { WorkoutSyncController } from './sync.svelte';
import WorkoutEditor from './WorkoutEditor.svelte';

function makeDraft(): WorkoutDraft {
  const timestamp = '2026-10-08T10:00:00Z';
  return {
    account_id: 'account-1',
    workout_id: 'workout-1',
    draft_id: 'draft-1',
    base_detail_id: 'workout-1',
    base_revision: 0,
    started_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
    change_number: 0,
    acknowledged_change_number: 0,
    content: {
      name: null,
      notes: null,
      ended_at: null,
      bodyweight_kg: null,
      exercises: [
        {
          id: 'exercise-1',
          catalog_id: 'bench-press',
          notes: null,
          sets: [
            {
              id: 'set-1',
              reps: null,
              weight_kg: null,
              bw_percent_override: null,
              rpe: null,
              side: 'bilateral',
              done: false,
            },
          ],
        },
      ],
      raw_fields: {},
      recorded_load_snapshots: {
        'exercise-1': {
          load_type: 'single_weight',
          bodyweight_percent: null,
          side_count: 1,
        },
      },
      provisional_load_snapshots: {},
    },
  };
}

interface Harness {
  editor: LocalDraftEditor;
  sync: WorkoutSyncController;
  onFinished: ReturnType<typeof vi.fn>;
  finishButton: HTMLButtonElement;
}

async function renderEditor(): Promise<Harness> {
  const draft = makeDraft();
  const editor = new LocalDraftEditor(
    new DraftRepository({
      put: vi.fn(async () => {}),
      get: vi.fn(async () => draft),
      listByAccount: vi.fn(async () => ({ values: [], next_key: null })),
    } as never),
    draft,
  );
  const operations = {
    getSave: vi.fn(async () => null),
    replaceSave: vi.fn(async () => {}),
    prepareSave: vi.fn(async () => {}),
    discardPending: vi.fn(async () => {}),
    drafts: {
      // Acknowledge whatever the editor currently holds so the synchronization
      // loop settles into `synced` after one save round.
      get: vi.fn(async () => ({
        ...structuredClone(editor.current!),
        acknowledged_change_number: editor.current!.change_number,
      })),
      delete: vi.fn(async () => {}),
    },
  } as unknown as PendingDraftRepository;
  const onFinished = vi.fn();
  const sync = new WorkoutSyncController({
    accountId: 'account-1',
    editor,
    operations,
    authenticatedAccountId: () => 'account-1',
    onFinished,
    onDiscarded: vi.fn(),
    currentUser: async () => ({ id: 'account-1' }) as never,
  });
  render(WorkoutEditor, {
    props: {
      editor,
      sync,
      catalog: [],
      onOpenPicker: vi.fn(),
      onClosePicker: vi.fn(),
    },
  });
  const finishButton = screen.getByRole('button', {
    name: 'Finish workout',
  }) as HTMLButtonElement;
  return { editor, sync, onFinished, finishButton };
}

/** Mark the only set done and drive one full local save + synchronization. */
async function completeSetAndSynchronize(harness: Harness): Promise<void> {
  const content: EditableWorkoutContent = structuredClone(
    harness.editor.current!.content,
  );
  content.exercises[0].sets[0] = {
    ...content.exercises[0].sets[0],
    reps: 5,
    weight_kg: 100,
    done: true,
  };
  await harness.sync.commit(content);
  await harness.sync.saveNow();
}

describe('WorkoutSyncController finish availability', () => {
  let confirmMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    confirmMock = vi.fn(() => false);
    vi.stubGlobal('confirm', confirmMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('re-enables Finish workout when the synchronization settles', async () => {
    const harness = await renderEditor();
    // Blocked while a set is incomplete.
    expect(harness.finishButton.disabled).toBe(true);

    await completeSetAndSynchronize(harness);
    expect(harness.sync.status).toBe('synced');

    // Regression: the button used to stay disabled here because clearing the
    // in-flight synchronization was not reactive; only a remount recovered.
    await waitFor(() => expect(harness.finishButton.disabled).toBe(false));
  });

  it('finishes only after an explicit confirmation', async () => {
    const harness = await renderEditor();
    await completeSetAndSynchronize(harness);
    await waitFor(() => expect(harness.finishButton.disabled).toBe(false));

    confirmMock.mockReturnValue(false);
    await fireEvent.click(harness.finishButton);
    expect(confirmMock).toHaveBeenCalledOnce();
    expect(harness.onFinished).not.toHaveBeenCalled();
    expect(harness.sync.status).toBe('synced');

    confirmMock.mockReturnValue(true);
    await fireEvent.click(harness.finishButton);
    await waitFor(() => expect(harness.onFinished).toHaveBeenCalledOnce());
  });
});
