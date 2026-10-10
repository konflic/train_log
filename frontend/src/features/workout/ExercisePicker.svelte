<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { Exercise, MuscleGroup } from '../../api';
  import { listExercises } from '../../api';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import {
    loadTypeLabels,
    muscleGroupLabels,
    muscleGroupValues,
  } from '../catalog/labels';

  const PAGE_SIZE = 10;
  const SEARCH_DEBOUNCE_MS = 300;

  let {
    replacement = false,
    disabled = false,
    target = 'workout',
    onSelect,
    onBack,
  }: {
    replacement?: boolean;
    disabled?: boolean;
    target?: 'workout' | 'plan';
    onSelect: (exercise: Exercise) => void;
    onBack: () => void;
  } = $props();

  let search = $state('');
  let muscleGroup = $state<MuscleGroup | ''>('');
  let page = $state(1);
  let phase = $state<'loading' | 'ready' | 'error'>('loading');
  let items = $state<Exercise[]>([]);
  let total = $state(0);
  let message = $state<string | null>(null);
  let requestId = 0;
  let controller: AbortController | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  const pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));

  async function load(): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    phase = 'loading';
    try {
      const result = await listExercises(
        {
          page,
          pageSize: PAGE_SIZE,
          search: search === '' ? undefined : search,
          muscle_group: muscleGroup || undefined,
        },
        controller.signal,
      );
      if (id !== requestId) return;
      items = result.items;
      total = result.total;
      message = null;
      phase = 'ready';
    } catch (error) {
      if (id !== requestId || isAbortError(error)) return;
      message = describeFailure(error);
      phase = 'error';
    }
  }

  function resetPageAndLoad(): void {
    page = 1;
    void load();
  }

  function handleSearch(): void {
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchTimer = null;
      resetPageAndLoad();
    }, SEARCH_DEBOUNCE_MS);
  }

  function describeLoad(entry: Exercise): string {
    const parts = [loadTypeLabels[entry.load_type]];
    if (entry.bodyweight_percent !== null) {
      parts.push(`${entry.bodyweight_percent}% bodyweight`);
    }
    if (entry.load_type === 'split_weight') {
      parts.push(
        entry.side_count === 1 ? 'one side per set' : 'both sides per set',
      );
    }
    return parts.join(' · ');
  }

  void load();

  onDestroy(() => {
    requestId += 1;
    controller?.abort();
    if (searchTimer !== null) clearTimeout(searchTimer);
  });
</script>

<section aria-label="Exercise picker" class="flex flex-col gap-3">
  <button
    type="button"
    class="inline-flex min-h-11 w-fit items-center text-sm font-medium text-primary"
    onclick={onBack}>Back to {target}</button
  >

  <p class="text-sm text-muted">
    {replacement
      ? 'Choose a replacement exercise'
      : `Choose an exercise to add to this ${target}`}
  </p>

  <div>
    <label for="workout-exercise-search" class="block text-sm font-medium"
      >Search</label
    >
    <input
      id="workout-exercise-search"
      type="search"
      autocomplete="off"
      placeholder="Filter by name"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
      bind:value={search}
      oninput={handleSearch}
    />
  </div>

  <div>
    <label for="workout-filter-muscle-group" class="block text-sm font-medium"
      >Muscle group</label
    >
    <select
      id="workout-filter-muscle-group"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
      bind:value={muscleGroup}
      onchange={resetPageAndLoad}
    >
      <option value="">All</option>
      {#each muscleGroupValues as value (value)}
        <option {value}>{muscleGroupLabels[value]}</option>
      {/each}
    </select>
  </div>

  {#if phase === 'loading'}
    <p role="status" class="text-sm text-muted">Loading exercises…</p>
  {:else if phase === 'error'}
    <p role="alert" class="text-sm text-danger">{message}</p>
    <button
      type="button"
      class="min-h-11 w-fit rounded-md border border-edge px-4 text-sm font-medium"
      onclick={() => void load()}>Retry</button
    >
  {:else if items.length === 0}
    <p class="text-sm text-muted">No exercises match the current filters</p>
  {:else}
    <ul class="flex flex-col gap-2">
      {#each items as entry (entry.id)}
        <li>
          <button
            type="button"
            class="min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-3 text-left"
            {disabled}
            onclick={() => onSelect(entry)}
          >
            <span class="block font-medium">{entry.name}</span>
            <span class="mt-1 block text-sm text-muted">
              {muscleGroupLabels[entry.muscle_group]} · {describeLoad(entry)}
            </span>
          </button>
        </li>
      {/each}
    </ul>

    <nav
      aria-label="Exercise picker pages"
      class="flex items-center justify-between gap-2"
    >
      <p class="text-sm text-muted">
        {total}
        {total === 1 ? 'exercise' : 'exercises'} · page {page} of {pageCount}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 text-sm font-medium disabled:opacity-40"
          disabled={page <= 1}
          onclick={() => {
            page -= 1;
            void load();
          }}>Previous</button
        >
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 text-sm font-medium disabled:opacity-40"
          disabled={page >= pageCount}
          onclick={() => {
            page += 1;
            void load();
          }}>Next</button
        >
      </div>
    </nav>
  {/if}
</section>
