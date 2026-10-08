<script lang="ts">
  import { onMount } from 'svelte';
  import { replace, router } from 'svelte-spa-router';
  import {
    createWorkout,
    getWorkout,
    listExercises,
    type Exercise,
  } from '../../api';
  import {
    DraftRepository,
    createRecoveryDraft,
    openDraftStorage,
    openDurableDraftStorage,
    PendingDraftRepository,
    type WorkoutDraft,
  } from '../../db';
  import { describeFailure } from '../../lib/failures';
  import { session } from '../auth/session.svelte';
  import {
    LocalDraftEditor,
    editorAssociations,
    editorKey,
    localEditors,
  } from '../drafts/editor.svelte';
  import { DraftSyncCoordinator } from '../drafts/sync';
  import WorkoutEditor from './WorkoutEditor.svelte';
  import { draftFromDetail } from './model';

  let { params = {} }: { params?: { id?: string } } = $props();
  const workoutId = $derived(params.id ?? 'new');
  const preferredDraftId = $derived(
    new URLSearchParams(router.querystring ?? '').get('draft'),
  );
  const accountId = $derived(session.user?.id ?? null);
  let repository = $state<DraftRepository | null>(null);
  let editor = $state<LocalDraftEditor | null>(null);
  let choices = $state<WorkoutDraft[]>([]);
  let phase = $state<'loading' | 'choosing' | 'editing' | 'finished' | 'error'>(
    'loading',
  );
  let message = $state('');
  let catalog = $state<Exercise[]>([]);
  let catalogMessage = $state<string | null>(null);
  let createCoordinator = $state<DraftSyncCoordinator | null>(null);
  let pendingCreateDraftId = $state<string | null>(null);
  let alive = true;

  async function setup(): Promise<void> {
    if (!accountId) return;
    phase = 'loading';
    message = '';
    try {
      repository = new DraftRepository(await openDraftStorage());
      if (workoutId === 'new') await quickStart();
      else await resume(workoutId);
    } catch (error) {
      if (!alive) return;
      message = describeFailure(error);
      phase = 'error';
    }
  }

  function useEditor(draft: WorkoutDraft): void {
    if (!repository || !accountId) return;
    const key = editorKey(accountId, draft.workout_id);
    editorAssociations.associate(key, draft.draft_id);
    const active = new LocalDraftEditor(repository, draft);
    localEditors.set(key, active);
    editor = active;
    phase = 'editing';
    // Catalog labels are presentation data only; recorded snapshots remain the
    // local source for validation and provisional calculations.
    void loadCatalog();
  }

  async function quickStart(): Promise<void> {
    if (!repository || !accountId) return;
    const now = new Date().toISOString();
    const draft: WorkoutDraft = {
      account_id: accountId,
      workout_id: crypto.randomUUID(),
      draft_id: crypto.randomUUID(),
      base_detail_id: '',
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
      created_at: now,
      updated_at: now,
    };
    // A newly created workout must satisfy the persisted-draft invariant before
    // the POST is allowed to leave the browser.
    draft.base_detail_id = draft.workout_id;
    const operations = new PendingDraftRepository(
      repository,
      await openDurableDraftStorage(),
    );
    createCoordinator = new DraftSyncCoordinator(
      accountId,
      draft.draft_id,
      operations,
      {
        create: createWorkout,
        get: getWorkout,
        save: async () => getWorkout(draft.workout_id),
      },
      () => session.user?.id ?? null,
    );
    pendingCreateDraftId = draft.draft_id;
    await createCoordinator.prepareCreate(draft);
    try {
      await createCoordinator.sendCreate();
    } catch (error) {
      message =
        'Workout creation is pending. Retry uses the same saved workout ID.';
      phase = 'error';
      throw error;
    }
    const acknowledged = await repository.get(
      accountId,
      draft.workout_id,
      draft.draft_id,
    );
    if (!acknowledged)
      throw new Error('The created local workout is unavailable.');
    useEditor(acknowledged);
    void replace(`/workouts/${draft.workout_id}?draft=${draft.draft_id}`);
  }

  async function retryCreate(): Promise<void> {
    if (!createCoordinator) return;
    phase = 'loading';
    try {
      await createCoordinator.sendCreate();
      if (!repository || !accountId) return;
      const drafts = await repository.listByAccount(accountId);
      const acknowledged = drafts.drafts.find(
        (draft) => draft.draft_id === pendingCreateDraftId,
      );
      if (!acknowledged)
        throw new Error('The created local workout is unavailable.');
      useEditor(acknowledged);
      void replace(
        `/workouts/${acknowledged.workout_id}?draft=${acknowledged.draft_id}`,
      );
    } catch (error) {
      message = describeFailure(error);
      phase = 'error';
    }
  }

  async function resume(id: string): Promise<void> {
    if (!repository || !accountId) return;
    const detail = await getWorkout(id);
    if (detail.ended_at !== null) {
      phase = 'finished';
      return;
    }
    const existing = await repository.listByAccountWorkout(accountId, id);
    const preferred = existing.drafts.find(
      (draft) => draft.draft_id === preferredDraftId,
    );
    if (preferred) {
      useEditor(preferred);
      return;
    }
    if (existing.drafts.length > 0) {
      choices = existing.drafts;
      phase = 'choosing';
      return;
    }
    const draft = draftFromDetail(accountId, detail);
    await repository.put(accountId, draft);
    useEditor(draft);
  }

  async function recover(source: WorkoutDraft): Promise<void> {
    if (!repository || !accountId) return;
    try {
      const draft = createRecoveryDraft(source);
      await repository.put(accountId, draft);
      useEditor(draft);
    } catch (error) {
      message = describeFailure(error);
      phase = 'error';
    }
  }

  async function loadCatalog(): Promise<void> {
    if (catalog.length > 0) return;
    catalogMessage = null;
    try {
      catalog = (await listExercises({ page: 1, pageSize: 100 })).items;
    } catch (error) {
      catalogMessage = describeFailure(error);
    }
  }

  onMount(() => {
    void setup();
    return () => {
      alive = false;
      if (editor?.current && accountId) {
        editorAssociations.release(
          editorKey(accountId, editor.current.workout_id),
          editor.current.draft_id,
        );
      }
    };
  });
</script>

{#if phase === 'loading'}
  <h1 tabindex="-1">Preparing workout</h1>
  <p role="status" class="mt-2 text-muted">
    Creating or loading your locally persistent editor…
  </p>
{:else if phase === 'choosing'}
  <h1 tabindex="-1">Choose a local draft</h1>
  <p class="mt-2 text-muted">
    Each tab keeps a separate editable recovery copy.
  </p>
  <ul class="mt-4 flex flex-col gap-2">
    {#each choices as draft (draft.draft_id)}<li
        class="rounded-lg border border-edge bg-surface p-4"
      >
        <p>Draft updated {draft.updated_at}</p>
        <p class="text-sm text-muted">
          Change {draft.change_number} · base revision {draft.base_revision}
        </p>
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
          onclick={() => void recover(draft)}>Recover this draft</button
        >
      </li>{/each}
  </ul>
{:else if phase === 'editing' && editor !== null}
  <h1 tabindex="-1">Active workout</h1>
  <WorkoutEditor
    {editor}
    {catalog}
    {catalogMessage}
    onOpenPicker={() => void loadCatalog()}
  />
{:else if phase === 'finished'}
  <h1 tabindex="-1">Finished workout</h1>
  <p class="mt-2 text-muted">
    Finished workouts are read-only. Detailed history arrives in the next UI
    stage.
  </p>
{:else}
  <h1 tabindex="-1">Workout unavailable</h1>
  <p role="alert" class="mt-2 text-danger">{message}</p>
  {#if createCoordinator}<button
      type="button"
      class="mt-4 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
      onclick={() => void retryCreate()}>Retry workout creation</button
    >{:else}<a
      class="mt-4 inline-flex min-h-11 items-center rounded-md border border-edge px-4"
      href="#/">Back home</a
    >{/if}
{/if}
