<script lang="ts">
  import { onMount } from 'svelte';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { push, replace, router } from 'svelte-spa-router';
  import {
    getWorkout,
    listExercises,
    listWorkouts,
    type Exercise,
  } from '../../api';
  import {
    DraftRepository,
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
  import WorkoutEditor from './WorkoutEditor.svelte';
  import { draftFromDetail } from './model';
  import { WorkoutSyncController } from './sync.svelte';
  import { activeSession } from './activeSession.svelte';

  let { params = {} }: { params?: { id?: string } } = $props();
  const workoutId = $derived(params.id ?? 'current');
  const pickerTarget = $derived.by(() => {
    const query = new SvelteURLSearchParams(router.querystring ?? '');
    if (query.get('picker') !== 'exercise') return undefined;
    return query.get('replace');
  });
  const accountId = $derived(session.user?.id ?? null);
  let repository = $state<DraftRepository | null>(null);
  let editor = $state<LocalDraftEditor | null>(null);
  let sync = $state<WorkoutSyncController | null>(null);
  let phase = $state<'loading' | 'editing' | 'finished' | 'error'>('loading');
  let message = $state('');
  let catalog = $state<Exercise[]>([]);
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
      if (workoutId === 'current') await openCurrent();
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
    await replace(current ? `/workouts/${current.id}` : '/workouts/start');
  }

  async function useEditor(draft: WorkoutDraft): Promise<void> {
    if (!repository || !accountId) return;
    const key = editorKey(accountId, draft.workout_id);
    const previous = localEditors.get(key);
    if (previous?.current) {
      editorAssociations.release(key, previous.current.draft_id);
    }
    editorAssociations.associate(key, draft.draft_id);
    const active = new LocalDraftEditor(repository, draft);
    localEditors.set(key, active);
    editor = active;
    const operations = new PendingDraftRepository(
      repository,
      await openDurableDraftStorage(),
    );
    // Both terminal outcomes retire this draft's editor and active-session mark
    // before leaving the route.
    const release = (): void => {
      editorAssociations.release(key, draft.draft_id);
      localEditors.delete(key);
      activeSession.clear(draft.workout_id);
    };
    sync = new WorkoutSyncController({
      accountId,
      editor: active,
      operations,
      authenticatedAccountId: () => session.user?.id ?? null,
      onFinished: () => {
        release();
        phase = 'finished';
        void replace(`/workouts/${draft.workout_id}`);
      },
      onDiscarded: () => {
        release();
        void replace('/');
      },
    });
    // Catalog labels are presentation data only; recorded snapshots remain the
    // local source for validation and provisional calculations.
    void loadCatalog();
    await sync.initialize();
    // Do not expose a writable editor until its server state is checked.
    phase = 'editing';
    activeSession.setActive(draft.workout_id);
  }

  async function resume(id: string): Promise<void> {
    if (!repository || !accountId) return;
    const existing = await repository.listByAccountWorkout(accountId, id);
    const detail = await getWorkout(id);
    await discardStoredWorkout(existing.drafts);
    if (detail.ended_at !== null) {
      phase = 'finished';
      return;
    }
    const draft = draftFromDetail(accountId, detail);
    await repository.put(accountId, draft);
    await useEditor(draft);
  }

  async function discardStoredWorkout(drafts: WorkoutDraft[]): Promise<void> {
    if (!repository || !accountId) return;
    const draftRepository = repository;
    const operations = new PendingDraftRepository(
      draftRepository,
      await openDurableDraftStorage(),
    );
    await Promise.all(
      drafts.map(async (draft) => {
        await operations.discardPending(accountId, draft.draft_id);
        await draftRepository.delete(
          accountId,
          draft.workout_id,
          draft.draft_id,
        );
      }),
    );
  }

  async function loadCatalog(): Promise<void> {
    if (catalog.length > 0) return;
    try {
      catalog = (await listExercises({ page: 1, pageSize: 100 })).items;
    } catch {
      // The picker loads its own paginated catalog; labels fall back safely here.
      return;
    }
  }

  function workoutPath(includePicker = false, replacementId?: string): string {
    const query = new SvelteURLSearchParams(router.querystring ?? '');
    query.delete('picker');
    query.delete('replace');
    if (includePicker) {
      query.set('picker', 'exercise');
      if (replacementId) query.set('replace', replacementId);
    }
    const querystring = query.toString();
    return `/workouts/${workoutId}${querystring === '' ? '' : `?${querystring}`}`;
  }

  function openPicker(replacementId?: string): void {
    void push(workoutPath(true, replacementId));
  }

  function closePicker(): void {
    void replace(workoutPath());
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
          'This account does not own the workout. Sign in as the original account.';
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
    };
  });
</script>

<svelte:window
  ononline={() => sync?.setOnline(true)}
  onoffline={() => sync?.setOnline(false)}
/>

{#if phase === 'loading'}
  <h1 id="workout-loading-heading" tabindex="-1">Loading active workout</h1>
  <p role="status" class="mt-2 text-muted">Getting the latest workout data…</p>
{:else if phase === 'editing' && editor !== null && sync !== null}
  <h1 id="active-workout-heading" tabindex="-1">
    {pickerTarget === undefined
      ? 'Active workout'
      : pickerTarget === null
        ? 'Choose an exercise'
        : 'Choose a replacement'}
  </h1>
  <WorkoutEditor
    {editor}
    {sync}
    {catalog}
    {pickerTarget}
    onOpenPicker={openPicker}
    onClosePicker={closePicker}
  />
  {#if sync.status === 'conflict'}
    <section
      id="workout-sync-conflict"
      class="mt-4 rounded-lg border border-edge bg-surface p-4"
      aria-labelledby="workout-conflict-heading"
    >
      <h2 id="workout-conflict-heading" class="font-semibold">
        Workout changed elsewhere
      </h2>
      <p class="mt-1 text-sm text-muted">
        Reload to use the latest saved workout data. Unsynced changes in this
        tab will be discarded.
      </p>
      <button
        id="workout-reload-server-button"
        type="button"
        class="mt-3 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
        onclick={() => window.location.reload()}>Reload workout</button
      >
    </section>
  {/if}
  {#if sync.status === 'authentication_required'}
    <section class="mt-4 rounded-lg border border-edge bg-surface p-4">
      <h2 class="font-semibold">Authentication required</h2>
      <p class="mt-1 text-sm text-muted">
        Your latest workout changes will resume after you sign in.
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
  <a
    class="mt-4 inline-flex min-h-11 items-center rounded-md border border-edge px-4"
    href="#/">Back home</a
  >
{/if}
