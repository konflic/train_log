<script lang="ts">
  import { onMount } from 'svelte';
  import { replace, router } from 'svelte-spa-router';
  import {
    ApiRequestError,
    createWorkout,
    getExercise,
    getWorkout,
    listExercises,
    listWorkouts,
    saveWorkout,
    type Exercise,
  } from '../../api';
  import {
    DraftRepository,
    createDraftId,
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
  import { copyDraftToNewWorkout, draftFromDetail } from './model';
  import { WorkoutSyncController } from './sync.svelte';

  let { params = {} }: { params?: { id?: string } } = $props();
  const workoutId = $derived(
    params.id ?? (router.location === '/workouts/current' ? 'current' : 'new'),
  );
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
  let recoveryBusy = $state(false);
  let recoveryMessage = $state<string | null>(null);
  let alive = true;

  async function setup(): Promise<void> {
    if (!accountId) return;
    phase = 'loading';
    message = '';
    try {
      repository = new DraftRepository(await openDraftStorage());
      if (workoutId === 'current') await openCurrent();
      else if (workoutId === 'new') await quickStart();
      else await resume(workoutId);
    } catch (error) {
      if (!alive) return;
      message = describeFailure(error);
      phase = 'error';
    }
  }

  async function openCurrent(): Promise<void> {
    const active = await listWorkouts({
      status: 'active',
      page: 1,
      pageSize: 1,
    });
    const current = active.items[0];
    await replace(current ? `/workouts/${current.id}` : '/workouts/new');
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
    // Catalog labels are presentation data only; recorded snapshots remain the
    // local source for validation and provisional calculations.
    void loadCatalog();
    await sync.initialize();
    // Do not expose a writable editor while its initial authoritative recovery
    // check is still in flight; otherwise a concurrent deletion can race the
    // first load and lock input before the user can make a local edit.
    phase = 'editing';
  }

  async function quickStart(): Promise<void> {
    if (!repository || !accountId) return;
    const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    const draft: WorkoutDraft = {
      account_id: accountId,
      workout_id: createDraftId(),
      draft_id: createDraftId(),
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

  async function currentCatalogFor(
    source: WorkoutDraft,
  ): Promise<Map<string, Exercise | null>> {
    const ids = [
      ...new Set(source.content.exercises.map((item) => item.catalog_id)),
    ];
    const entries = await Promise.all(
      ids.map(async (id): Promise<[string, Exercise | null]> => {
        try {
          return [id, await getExercise(id)];
        } catch (error) {
          if (error instanceof ApiRequestError && error.problem.status === 404)
            return [id, null];
          throw error;
        }
      }),
    );
    return new Map(entries);
  }

  function releaseCurrentEditor(): void {
    sync?.destroy();
    if (!editor?.current) return;
    const current = editor.current;
    const key = editorKey(current.account_id, current.workout_id);
    editorAssociations.release(key, current.draft_id);
    localEditors.delete(key);
  }

  async function copyConflictToNew(): Promise<void> {
    if (!repository || !accountId || !editor?.current || recoveryBusy) return;
    recoveryBusy = true;
    recoveryMessage = null;
    try {
      const source = $state.snapshot(editor.current);
      const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
      const draft = copyDraftToNewWorkout(
        source,
        await currentCatalogFor(source),
        now,
      );
      const operations = new PendingDraftRepository(
        repository,
        await openDurableDraftStorage(),
      );
      const coordinator = new DraftSyncCoordinator(
        accountId,
        draft.draft_id,
        operations,
        { create: createWorkout, get: getWorkout, save: saveWorkout },
        () => session.user?.id ?? null,
      );
      await coordinator.prepareCreate(draft);
      await coordinator.sendCreate();
      const acknowledged = await repository.get(
        accountId,
        draft.workout_id,
        draft.draft_id,
      );
      if (!acknowledged)
        throw new Error('The copied local workout is unavailable.');
      releaseCurrentEditor();
      await useEditor(acknowledged);
      void replace(
        `/workouts/${acknowledged.workout_id}?draft=${acknowledged.draft_id}`,
      );
    } catch (error) {
      recoveryMessage = describeFailure(error);
    } finally {
      recoveryBusy = false;
    }
  }

  async function useServerVersion(): Promise<void> {
    if (
      !sync ||
      !window.confirm('Discard local changes and use the server version?')
    )
      return;
    recoveryBusy = true;
    await sync.useServerVersion();
    recoveryBusy = false;
  }

  async function replaceServerVersion(): Promise<void> {
    if (
      !sync ||
      !window.confirm(
        'Replace the current server version with this entire local workout?',
      )
    )
      return;
    recoveryBusy = true;
    await sync.replaceServerVersion();
    recoveryBusy = false;
  }

  async function discardDeletedWorkout(): Promise<void> {
    if (
      !sync ||
      !window.confirm(
        'Discard this local copy? The server workout was deleted.',
      )
    )
      return;
    recoveryBusy = true;
    try {
      await sync.discardDeletedWorkout();
      releaseCurrentEditor();
      await replace('/');
    } catch (error) {
      recoveryMessage = describeFailure(error);
    } finally {
      recoveryBusy = false;
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

  $effect(() => {
    if (sync?.status === 'conflict' && sync.recoveryStatus === 'idle') {
      void sync.loadRecovery();
    }
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
  {#if sync.status === 'conflict'}
    <section
      class="mt-4 rounded-lg border border-edge bg-surface p-4"
      aria-labelledby="recovery-heading"
    >
      <h2 id="recovery-heading" class="font-semibold">Choose what to keep</h2>
      <p class="mt-1 text-sm text-muted">
        Changes are not merged automatically. Your local copy stays stored until
        the selected action succeeds.
      </p>
      <p class="mt-2 text-sm">
        Local copy: change {editor.current!.change_number}, based on revision
        {editor.current!.base_revision}.
      </p>
      {#if sync.recoveryStatus === 'loading'}
        <p role="status" class="mt-2 text-sm text-muted">
          Loading server version…
        </p>
      {:else if sync.recoveryStatus === 'ready' && sync.serverCopy}
        <p class="mt-2 text-sm">
          Server copy: revision {sync.serverCopy.revision},
          {sync.serverCopy.ended_at === null ? 'active' : 'finished'}.
        </p>
      {:else if sync.recoveryStatus === 'deleted'}
        <p class="mt-2 text-sm">The server workout was deleted.</p>
      {:else if sync.recoveryStatus === 'error'}
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md border border-edge px-3"
          onclick={() => void sync?.loadRecovery()}>Retry server check</button
        >
      {/if}
      {#if recoveryMessage}<p role="alert" class="mt-2 text-sm text-danger">
          {recoveryMessage}
        </p>{/if}
      {#if sync.recoveryStatus === 'ready' || sync.recoveryStatus === 'deleted'}
        <div class="mt-3 flex flex-wrap gap-2">
          {#if sync.recoveryStatus === 'ready'}
            <button
              type="button"
              disabled={recoveryBusy}
              class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
              onclick={() => void useServerVersion()}>Use server version</button
            >
          {/if}
          <button
            type="button"
            disabled={recoveryBusy}
            class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
            onclick={() => void copyConflictToNew()}
            >Copy local work to new workout</button
          >
          {#if sync.canReplaceServer}
            <button
              type="button"
              disabled={recoveryBusy}
              class="min-h-11 rounded-md bg-primary px-3 font-medium text-primary-content disabled:opacity-40"
              onclick={() => void replaceServerVersion()}
              >Replace server version</button
            >
          {/if}
          {#if sync.recoveryStatus === 'deleted'}
            <button
              type="button"
              disabled={recoveryBusy}
              class="min-h-11 rounded-md border border-danger px-3 text-danger disabled:opacity-40"
              onclick={() => void discardDeletedWorkout()}
              >Discard local copy</button
            >
          {/if}
        </div>
      {/if}
    </section>
  {/if}
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
