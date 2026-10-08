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
  import { WorkoutSyncController } from './sync.svelte';

  let { params = {} }: { params?: { id?: string } } = $props();
  const workoutId = $derived(params.id ?? 'new');
  const preferredDraftId = $derived(
    new URLSearchParams(router.querystring ?? '').get('draft'),
  );
  const accountId = $derived(session.user?.id ?? null);
  let repository = $state<DraftRepository | null>(null);
  let editor = $state<LocalDraftEditor | null>(null);
  let sync = $state<WorkoutSyncController | null>(null);
  let choices = $state<WorkoutDraft[]>([]);
  let phase = $state<'loading' | 'choosing' | 'editing' | 'finished' | 'error'>(
    'loading',
  );
  let message = $state('');
  let catalog = $state<Exercise[]>([]);
  let catalogMessage = $state<string | null>(null);
  let createCoordinator = $state<DraftSyncCoordinator | null>(null);
  let pendingCreateDraftId = $state<string | null>(null);
  let reauthOpen = $state(false);
  let reauthEmail = $state('');
  let reauthPassword = $state('');
  let reauthBusy = $state(false);
  let reauthMessage = $state<string | null>(null);
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

  async function useEditor(draft: WorkoutDraft): Promise<void> {
    if (!repository || !accountId) return;
    const key = editorKey(accountId, draft.workout_id);
    editorAssociations.associate(key, draft.draft_id);
    const active = new LocalDraftEditor(repository, draft);
    localEditors.set(key, active);
    editor = active;
    const operations = new PendingDraftRepository(
      repository,
      await openDurableDraftStorage(),
    );
    sync = new WorkoutSyncController({
      accountId,
      editor: active,
      operations,
      authenticatedAccountId: () => session.user?.id ?? null,
      onFinished: () => {
        editorAssociations.release(key, draft.draft_id);
        localEditors.delete(key);
        phase = 'finished';
        void replace(`/workouts/${draft.workout_id}`);
      },
    });
    phase = 'editing';
    // Catalog labels are presentation data only; recorded snapshots remain the
    // local source for validation and provisional calculations.
    void loadCatalog();
    await sync.initialize();
  }

  async function quickStart(): Promise<void> {
    if (!repository || !accountId) return;
    const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
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
      acknowledged_change_number: 0,
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
    await useEditor(acknowledged);
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
      await useEditor(acknowledged);
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
    const existing = await repository.listByAccountWorkout(accountId, id);
    const preferred = existing.drafts.find(
      (draft) => draft.draft_id === preferredDraftId,
    );
    if (preferred) {
      await useEditor(preferred);
      return;
    }
    if (existing.drafts.length > 0) {
      choices = existing.drafts;
      phase = 'choosing';
      return;
    }
    const detail = await getWorkout(id);
    if (detail.ended_at !== null) {
      phase = 'finished';
      return;
    }
    const draft = draftFromDetail(accountId, detail);
    await repository.put(accountId, draft);
    await useEditor(draft);
  }

  async function recover(source: WorkoutDraft): Promise<void> {
    if (!repository || !accountId) return;
    try {
      const draft = createRecoveryDraft($state.snapshot(source));
      await repository.put(accountId, draft);
      await useEditor(draft);
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

  async function reauthenticate(): Promise<void> {
    if (!sync || reauthBusy) return;
    reauthBusy = true;
    reauthMessage = null;
    try {
      await session.authenticate({
        email: reauthEmail.trim().toLowerCase(),
        password: reauthPassword,
      });
      reauthPassword = '';
      await sync.resume();
      if (sync.status !== 'authentication_required') reauthOpen = false;
      else
        reauthMessage =
          'This account does not own the draft. Sign in as the original account.';
    } catch (error) {
      reauthMessage = describeFailure(error);
    } finally {
      reauthBusy = false;
    }
  }

  onMount(() => {
    void setup();
    return () => {
      alive = false;
      sync?.destroy();
      if (editor?.current) {
        editorAssociations.release(
          editorKey(editor.current.account_id, editor.current.workout_id),
          editor.current.draft_id,
        );
      }
    };
  });
</script>

<svelte:window
  ononline={() => sync?.setOnline(true)}
  onoffline={() => sync?.setOnline(false)}
/>

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
{:else if phase === 'editing' && editor !== null && sync !== null}
  <h1 tabindex="-1">Active workout</h1>
  <WorkoutEditor
    {editor}
    {sync}
    {catalog}
    {catalogMessage}
    onOpenPicker={() => void loadCatalog()}
  />
  {#if sync.status === 'authentication_required'}
    <section class="mt-4 rounded-lg border border-edge bg-surface p-4">
      <h2 class="font-semibold">Authentication required</h2>
      <p class="mt-1 text-sm text-muted">
        Your local draft and any exact pending request are retained.
      </p>
      {#if !reauthOpen}
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
          onclick={() => {
            reauthEmail = session.user?.email ?? '';
            reauthOpen = true;
          }}>Sign in again</button
        >
      {:else}
        <form
          class="mt-3 flex flex-col gap-3"
          onsubmit={(event) => {
            event.preventDefault();
            void reauthenticate();
          }}
        >
          <label class="text-sm font-medium" for="reauth-email"
            >Email<input
              id="reauth-email"
              type="email"
              autocomplete="username"
              class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
              bind:value={reauthEmail}
            /></label
          >
          <label class="text-sm font-medium" for="reauth-password"
            >Password<input
              id="reauth-password"
              type="password"
              autocomplete="current-password"
              class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
              bind:value={reauthPassword}
            /></label
          >
          {#if reauthMessage}<p role="alert" class="text-sm text-danger">
              {reauthMessage}
            </p>{/if}
          <div class="flex gap-2">
            <button
              type="submit"
              disabled={reauthBusy}
              class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
              >{reauthBusy ? 'Signing in…' : 'Sign in and resume'}</button
            >
            <button
              type="button"
              class="min-h-11 rounded-md border border-edge px-4"
              onclick={() => (reauthOpen = false)}>Cancel</button
            >
          </div>
        </form>
      {/if}
    </section>
  {/if}
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
