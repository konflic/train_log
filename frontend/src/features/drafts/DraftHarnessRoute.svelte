<script lang="ts">
  import { onMount } from 'svelte';
  import {
    DraftRepository,
    createDraftId,
    createRecoveryDraft,
    openDurableDraftStorage,
    openDraftStorage,
    PendingDraftRepository,
    type DraftKey,
    type DraftPageOptions,
    type DraftStorage,
    type WorkoutDraft,
  } from '../../db';
  import {
    createWorkout,
    getWorkout,
    listExercises,
    saveWorkout,
  } from '../../api';
  import {
    LocalDraftEditor,
    editorAssociations,
    editorKey,
    localEditors,
  } from './editor.svelte';
  import { DraftSyncCoordinator } from './sync';

  let { accountId, localOnly }: { accountId: string; localOnly: boolean } =
    $props();
  const workoutId = 'draft-harness-workout';
  const documentEditorId = createDraftId();

  // Failure/delay controls are only in this E2E component. The abort exercises
  // a real readwrite transaction; request success is not a committed edit.
  class ControlledStorage implements DraftStorage {
    failNextWrite = false;
    holdNextWrite = false;
    release: (() => void) | null = null;
    delegate: DraftStorage;

    constructor(delegate: DraftStorage) {
      this.delegate = delegate;
    }

    async put(draft: WorkoutDraft): Promise<void> {
      if (this.holdNextWrite) {
        this.holdNextWrite = false;
        await new Promise<void>((resolve) => {
          this.release = resolve;
        });
        this.release = null;
      }
      if (this.failNextWrite) {
        this.failNextWrite = false;
        await new Promise<void>((resolve, reject) => {
          const request = indexedDB.open('basefit-drafts');
          request.onerror = () => reject(request.error);
          request.onsuccess = () => {
            const database = request.result;
            const transaction = database.transaction('drafts', 'readwrite');
            transaction.onabort = () => {
              database.close();
              reject(
                new DOMException('Injected transaction abort', 'AbortError'),
              );
            };
            transaction.oncomplete = () => {
              database.close();
              resolve();
            };
            transaction.objectStore('drafts').put(draft).onsuccess = () =>
              transaction.abort();
          };
        });
        return;
      }
      await this.delegate.put(draft);
    }

    get = (key: DraftKey) => this.delegate.get(key);
    listByAccount = (id: string, options?: DraftPageOptions) =>
      this.delegate.listByAccount(id, options);
    listByAccountWorkout = (
      id: string,
      workout: string,
      options?: DraftPageOptions,
    ) => this.delegate.listByAccountWorkout(id, workout, options);
    delete = (key: DraftKey) => this.delegate.delete(key);
    deleteAccount = (id: string) => this.delegate.deleteAccount(id);
    close = () => this.delegate.close();
  }

  let repository = $state<DraftRepository | null>(null);
  let controlledStorage = $state<ControlledStorage | null>(null);
  let drafts = $state.raw<WorkoutDraft[]>([]);
  let nextKey = $state.raw<DraftKey | null>(null);
  let unavailableCount = $state(0);
  let editor = $state<LocalDraftEditor | null>(null);
  let coordinator = $state<DraftSyncCoordinator | null>(null);
  let status = $state('Loading local recovery choices…');
  let error = $state('');
  let selecting = $state(false);
  let available = $state(true);

  async function refreshChoices(after?: DraftKey): Promise<void> {
    if (!repository) return;
    const result = await repository.listByAccountWorkout(accountId, workoutId, {
      after,
    });
    if (!available) return;
    drafts = result.drafts;
    nextKey = result.next_key;
    unavailableCount = result.unavailable_count;
  }

  function sampleDraft(): WorkoutDraft {
    const now = new Date().toISOString();
    return {
      account_id: accountId,
      workout_id: workoutId,
      draft_id: createDraftId(),
      base_detail_id: workoutId,
      base_revision: 4,
      started_at: '2026-10-08T10:00:00Z',
      change_number: 0,
      created_at: now,
      updated_at: now,
      content: {
        name: 'Local recovery sample',
        notes: 'Complete fixture graph',
        bodyweight_kg: 81,
        ended_at: null,
        exercises: [
          {
            id: 'sample-exercise',
            catalog_id: 'sample-catalog',
            notes: null,
            sets: [
              {
                id: 'sample-set',
                reps: 8,
                weight_kg: 12,
                bw_percent_override: null,
                rpe: null,
                side: 'bilateral',
                done: false,
              },
            ],
          },
          {
            id: 'provisional-exercise',
            catalog_id: 'new-catalog',
            notes: null,
            sets: [
              {
                id: 'new-set',
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
        raw_fields: { 'sample-set.weight_kg': '12' },
        recorded_load_snapshots: {
          'sample-exercise': {
            load_type: 'split_weight',
            bodyweight_percent: null,
            side_count: 2,
          },
        },
        provisional_load_snapshots: {
          'provisional-exercise': {
            load_type: 'bodyweight',
            bodyweight_percent: 65,
            side_count: 1,
          },
        },
      },
    };
  }

  async function createSource(): Promise<void> {
    if (!repository || localOnly) return;
    status = 'Saving local draft…';
    error = '';
    try {
      await repository.put(accountId, sampleDraft());
      await refreshChoices();
      status = 'Draft saved. Select a recovery choice to edit it.';
    } catch {
      error = 'Storage failed. Retry creating the draft.';
    }
  }

  async function recover(source: WorkoutDraft): Promise<void> {
    if (!repository || selecting) return;
    const key = editorKey(accountId, workoutId);
    let recoveredId: string | null = null;
    selecting = true;
    error = '';
    try {
      const selected = await repository.get(
        accountId,
        workoutId,
        source.draft_id,
      );
      if (!selected)
        throw new Error('The selected draft is no longer available.');
      const recovered = createRecoveryDraft(selected);
      recoveredId = recovered.draft_id;
      editorAssociations.associate(key, recoveredId);
      await repository.put(accountId, recovered);
      const active = new LocalDraftEditor(repository, recovered);
      localEditors.set(key, active);
      editor = active;
      coordinator = null;
      status = `Editing local draft ${recoveredId}.`;
    } catch (cause) {
      if (recoveredId) editorAssociations.release(key, recoveredId);
      error = cause instanceof Error ? cause.message : 'Storage failed.';
    } finally {
      selecting = false;
    }
  }

  async function startDurableCreate(): Promise<void> {
    if (!repository || localOnly || selecting) return;
    selecting = true;
    error = '';
    status = 'Persisting create request…';
    try {
      const workoutId = createDraftId();
      const prepared = sampleDraft();
      prepared.workout_id = workoutId;
      prepared.base_detail_id = workoutId;
      prepared.draft_id = createDraftId();
      prepared.base_revision = 0;
      prepared.started_at = new Date().toISOString();
      const exerciseId = createDraftId();
      const setId = createDraftId();
      prepared.content.exercises[0].id = exerciseId;
      prepared.content.exercises[0].sets[0].id = setId;
      prepared.content.raw_fields = { [`${setId}.weight_kg`]: '12' };
      const catalog = await listExercises({ pageSize: 100 });
      const exercise = catalog.items.find(
        (item) => item.load_type === 'single_weight',
      );
      if (!exercise) throw new Error('No compatible exercise is available.');
      prepared.content.exercises = [prepared.content.exercises[0]];
      prepared.content.exercises[0].catalog_id = exercise.id;
      prepared.content.recorded_load_snapshots = {};
      prepared.content.provisional_load_snapshots = {
        [exerciseId]: {
          load_type: exercise.load_type,
          bodyweight_percent: exercise.bodyweight_percent,
          side_count: exercise.side_count,
        },
      };
      const operations = new PendingDraftRepository(
        repository,
        await openDurableDraftStorage(),
      );
      const next = new DraftSyncCoordinator(
        accountId,
        prepared.draft_id,
        operations,
        { create: createWorkout, get: getWorkout, save: saveWorkout },
        () => accountId,
      );
      await next.prepareCreate(prepared);
      status = 'Create request stored. Sending…';
      await next.sendCreate();
      const acknowledged = await repository.get(
        accountId,
        workoutId,
        prepared.draft_id,
      );
      if (!acknowledged) throw new Error('Created draft is unavailable.');
      editor = new LocalDraftEditor(repository, acknowledged);
      coordinator = next;
      status = `Created workout ${workoutId}. Save the prepared graph when ready.`;
    } catch (cause) {
      error =
        cause instanceof Error
          ? cause.message
          : 'Create request could not be sent.';
    } finally {
      selecting = false;
    }
  }

  async function sendDurableSave(finish: boolean): Promise<void> {
    if (!editor?.current || !coordinator || selecting) return;
    selecting = true;
    error = '';
    try {
      if (finish) {
        const content = structuredClone(editor.current.content);
        content.ended_at = new Date().toISOString();
        await editor.edit(content);
      }
      if (editor.status !== 'saved') {
        throw new Error(
          'The latest edit must be stored locally before saving.',
        );
      }
      status = 'Persisting immutable save request…';
      await coordinator.prepareSave(editor.current);
      status = 'Sending exact save request…';
      await coordinator.sendSave();
      const acknowledged = await repository!.get(
        accountId,
        editor.current.workout_id,
        editor.current.draft_id,
      );
      if (!acknowledged) throw new Error('Saved draft is unavailable.');
      editor = new LocalDraftEditor(repository!, acknowledged);
      status = finish
        ? 'Finish-shaped save acknowledged.'
        : 'Save acknowledged.';
    } catch (cause) {
      error =
        cause instanceof Error
          ? cause.message
          : 'Save request could not be sent.';
    } finally {
      selecting = false;
    }
  }

  function updateRawText(event: Event): void {
    if (!editor?.current) return;
    const value = (event.currentTarget as HTMLInputElement).value;
    const content = structuredClone(editor.current.content);
    content.raw_fields['sample-set.weight_kg'] = value;
    // Unparsed raw text is authoritative local input. No server payload is
    // available in this stage and no previous numeric value is substituted.
    void editor.edit(content);
  }

  async function initializeStorage(): Promise<void> {
    error = '';
    status = 'Loading local recovery choices…';
    try {
      const storage = new ControlledStorage(await openDraftStorage());
      controlledStorage = storage;
      repository = new DraftRepository(storage);
      await refreshChoices();
      status = 'Select a saved draft or create a recovery source.';
    } catch (cause) {
      repository = null;
      error =
        cause instanceof Error
          ? cause.message
          : 'Local storage could not be opened. Retry when available.';
    }
  }

  onMount(() => {
    void initializeStorage();
    return () => {
      available = false;
    };
  });
</script>

<h1>Draft recovery harness</h1>
<p class="mt-2 text-muted" data-testid="document-editor-id">
  Document editor identity: {documentEditorId}
</p>
<p class="mt-2 text-muted">
  Only committed data still present in IndexedDB can be recovered. Browser
  storage can be evicted.
</p>
{#if localOnly}
  <p>
    Local-only recovery. Server authentication is required before network work.
  </p>
{/if}
{#if error}<p role="alert">{error}</p>{/if}
<p class="mt-2" role="status">
  {#if editor?.status === 'saving'}Saving locally…
  {:else if editor?.status === 'failed'}Storage failed. Retry the latest local
    edit.
  {:else if editor?.current}Locally saved change {editor.savedChange}.
  {:else}{status}{/if}
</p>
{#if repository}
  {#if !localOnly}
    <button
      type="button"
      class="mt-4 min-h-11 rounded-md border border-edge px-4"
      onclick={() => void createSource()}>Create recovery source</button
    >
    <button
      type="button"
      class="mt-4 min-h-11 rounded-md border border-edge px-4"
      disabled={selecting}
      onclick={() => void startDurableCreate()}>Start durable create</button
    >
  {/if}
  <button
    type="button"
    class="mt-4 min-h-11 rounded-md border border-edge px-4"
    onclick={() => {
      if (controlledStorage) controlledStorage.failNextWrite = true;
    }}>Fail next local write</button
  >
  <button
    type="button"
    class="mt-4 min-h-11 rounded-md border border-edge px-4"
    onclick={() => {
      if (controlledStorage) controlledStorage.holdNextWrite = true;
    }}>Hold next local write</button
  >
  <button
    type="button"
    class="mt-4 min-h-11 rounded-md border border-edge px-4"
    onclick={() => controlledStorage?.release?.()}>Release local write</button
  >
  {#if unavailableCount > 0}<p role="alert">
      {unavailableCount} malformed saved draft cannot be recovered.
    </p>{/if}
  {#if !editor && localEditors.has(editorKey(accountId, workoutId))}
    <button
      type="button"
      class="mt-4 min-h-11 rounded-md border border-edge px-4"
      onclick={() => {
        editor = localEditors.get(editorKey(accountId, workoutId)) ?? null;
      }}>Continue this tab's draft</button
    >
  {/if}
  <section class="mt-4" aria-label="Recovery choices">
    <h2>Recovery choices</h2>
    {#if drafts.length === 0}<p>No drafts for this account and workout.</p>{/if}
    <ul class="mt-2 flex flex-col gap-2">
      {#each drafts as draft (draft.draft_id)}
        <li
          class="rounded-md border border-edge p-3"
          data-testid="draft-{draft.draft_id}"
        >
          <p>Draft {draft.draft_id}</p>
          <p>
            Updated {draft.updated_at} · change {draft.change_number} · base revision
            {draft.base_revision}
          </p>
          <button
            type="button"
            disabled={selecting || editor !== null}
            class="mt-2 min-h-11 rounded-md border border-edge px-3"
            onclick={() => void recover(draft)}
            >Recover draft {draft.draft_id}</button
          >
        </li>
      {/each}
    </ul>
    {#if nextKey}
      <button
        type="button"
        class="min-h-11 border border-edge px-4"
        onclick={() =>
          void refreshChoices(nextKey ?? undefined).catch(() => {
            error = 'Could not read recovery choices.';
          })}>Next recovery page</button
      >
    {/if}
  </section>
  {#if editor?.current}
    <section class="mt-6" aria-label="Local draft editor">
      <h2>Local draft editor</h2>
      <p data-testid="editing-draft-id">
        Editing draft {editor.current.draft_id}
      </p>
      <p>Raw fields are local-only. No server payload is available.</p>
      {#if coordinator}
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md border border-edge px-4"
          disabled={selecting || editor.status !== 'saved'}
          onclick={() => void sendDurableSave(false)}>Send durable save</button
        >
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md border border-edge px-4"
          disabled={selecting || editor.status !== 'saved'}
          onclick={() => void sendDurableSave(true)}>Send durable finish</button
        >
      {/if}
      <pre data-testid="editor-value">{JSON.stringify(editor.current)}</pre>
      <label class="mt-4 block" for="raw-weight">Raw weight text</label>
      <input
        id="raw-weight"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
        value={editor.current.content.raw_fields['sample-set.weight_kg']}
        oninput={updateRawText}
      />
      {#if editor.status === 'failed'}
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md border border-edge px-4"
          onclick={() => void editor?.retry()}>Retry local edit</button
        >
      {/if}
    </section>
  {/if}
{:else}
  <button
    type="button"
    class="mt-4 min-h-11 rounded-md border border-edge px-4"
    onclick={() => void initializeStorage()}>Retry local storage</button
  >
{/if}
