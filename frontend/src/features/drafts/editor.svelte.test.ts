// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import {
  DraftRepository,
  type DraftStorage,
  type WorkoutDraft,
} from '../../db';
import { LocalDraftEditor } from './editor.svelte';

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function draft(): WorkoutDraft {
  return {
    account_id: 'a',
    workout_id: 'w',
    draft_id: 'd',
    base_detail_id: 'w',
    base_revision: 0,
    started_at: '2026-10-08T10:00:00Z',
    created_at: '2026-10-08T10:00:00Z',
    updated_at: '2026-10-08T10:00:00Z',
    change_number: 0,
    acknowledged_change_number: 0,
    content: {
      name: null,
      notes: null,
      ended_at: null,
      bodyweight_kg: null,
      exercises: [],
      raw_fields: {},
      recorded_load_snapshots: {},
      provisional_load_snapshots: {},
    },
  };
}

describe('LocalDraftEditor', () => {
  it('does not reuse change numbers, replace newer input, or acknowledge a queued edit early', async () => {
    const first = deferred();
    const second = deferred();
    const put = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const editor = new LocalDraftEditor(
      new DraftRepository({ put } as unknown as DraftStorage),
      draft(),
    );
    const one = editor.edit({ ...editor.current!.content, name: 'First' });
    const two = editor.edit({ ...editor.current!.content, notes: 'Newer' });
    await Promise.resolve();
    expect(editor.current?.change_number).toBe(2);
    expect(editor.savedChange).toBe(0);
    first.resolve();
    await one;
    expect(editor.status).toBe('saving');
    expect(editor.current?.content).toMatchObject({
      name: 'First',
      notes: 'Newer',
    });
    second.resolve();
    await two;
    expect(editor.status).toBe('saved');
    expect(editor.savedChange).toBe(2);
  });

  it('retains the newest failed full value and retries it without reverting to an older failure', async () => {
    const first = deferred();
    const put = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockRejectedValueOnce(new Error('quota'))
      .mockResolvedValue(undefined);
    const editor = new LocalDraftEditor(
      new DraftRepository({ put } as unknown as DraftStorage),
      draft(),
    );
    const one = editor.edit({ ...editor.current!.content, name: 'First' });
    const two = editor.edit({
      ...editor.current!.content,
      raw_fields: { reps: '12.5' },
    });
    first.reject(new Error('abort'));
    await Promise.all([one, two]);
    expect(editor.status).toBe('failed');
    expect(editor.savedChange).toBe(0);
    await editor.retry();
    expect(editor.savedChange).toBe(2);
    expect(put.mock.calls[2][0].content).toMatchObject({
      name: 'First',
      raw_fields: { reps: '12.5' },
    });
  });

  it('applies an acknowledged base without replacing newer visible content', async () => {
    const put = vi.fn().mockResolvedValue(undefined);
    const editor = new LocalDraftEditor(
      new DraftRepository({ put } as unknown as DraftStorage),
      draft(),
    );
    await editor.edit({ ...editor.current!.content, name: 'Newer input' });
    const acknowledged = draft();
    acknowledged.base_revision = 1;
    acknowledged.acknowledged_change_number = 0;

    await editor.rebase(acknowledged);

    expect(editor.current).toMatchObject({
      base_revision: 1,
      change_number: 1,
      acknowledged_change_number: 0,
      content: { name: 'Newer input' },
    });
    expect(put).toHaveBeenLastCalledWith(
      expect.objectContaining({
        base_revision: 1,
        content: expect.objectContaining({ name: 'Newer input' }),
      }),
    );
  });
});
