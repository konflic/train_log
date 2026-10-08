<script lang="ts">
  import { onMount } from 'svelte';
  import {
    DraftRepository,
    createRecoveryDraft,
    openDraftStorage,
    type WorkoutDraft,
  } from '../../db';
  import { describeFailure } from '../../lib/failures';
  import {
    LocalDraftEditor,
    editorAssociations,
    editorKey,
    localEditors,
  } from '../drafts/editor.svelte';
  import WorkoutEditor from './WorkoutEditor.svelte';

  let { accountId }: { accountId: string } = $props();
  let repository = $state<DraftRepository | null>(null);
  let drafts = $state<WorkoutDraft[]>([]);
  let editor = $state<LocalDraftEditor | null>(null);
  let error = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      repository = new DraftRepository(await openDraftStorage());
      drafts = (await repository.listByAccount(accountId)).drafts;
    } catch (cause) {
      error = describeFailure(cause);
    }
  }

  async function recover(source: WorkoutDraft): Promise<void> {
    if (!repository) return;
    try {
      const draft = createRecoveryDraft(source);
      await repository.put(accountId, draft);
      const key = editorKey(accountId, draft.workout_id);
      editorAssociations.associate(key, draft.draft_id);
      const active = new LocalDraftEditor(repository, draft);
      localEditors.set(key, active);
      editor = active;
    } catch (cause) {
      error = describeFailure(cause);
    }
  }

  onMount(() => {
    void load();
  });
</script>

{#if editor}
  <h2 tabindex="-1">Local workout recovery</h2>
  <p class="mt-2 text-muted">
    Network saving is paused until you sign in again.
  </p>
  <WorkoutEditor
    {editor}
    onOpenPicker={() => (error = 'The catalog is unavailable while offline.')}
    catalogMessage={error}
  />
{:else}
  <h2 tabindex="-1">Choose a local draft</h2>
  <p class="mt-2 text-muted">
    Only drafts for the previously confirmed account are shown.
  </p>
  {#if error}<p role="alert" class="mt-2 text-danger">{error}</p>{/if}
  {#if repository && drafts.length === 0}<p class="mt-4">
      No local drafts are available.
    </p>{/if}
  <ul class="mt-4 flex flex-col gap-2">
    {#each drafts as draft (draft.draft_id)}
      <li class="rounded-lg border border-edge bg-surface p-4">
        <p>{draft.content.name ?? 'Unnamed workout'}</p>
        <p class="text-sm text-muted">Updated {draft.updated_at}</p>
        <button
          type="button"
          class="mt-3 min-h-11 rounded-md border border-edge px-3"
          onclick={() => void recover(draft)}>Recover this draft</button
        >
      </li>
    {/each}
  </ul>
{/if}
