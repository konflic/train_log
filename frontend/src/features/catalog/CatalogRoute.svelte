<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { SvelteURLSearchParams } from 'svelte/reactivity';
  import { push, router } from 'svelte-spa-router';
  import {
    listExercises,
    type Equipment,
    type Exercise,
    type MuscleGroup,
  } from '../../api';
  import ActionIcon from '../../components/ActionIcon.svelte';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import { isUnauthorizedError, session } from '../auth/session.svelte';
  import ExerciseForm from './ExerciseForm.svelte';
  import {
    equipmentLabels,
    equipmentValues,
    isEquipment,
    isMuscleGroup,
    loadTypeLabels,
    muscleGroupLabels,
    muscleGroupValues,
  } from './labels';

  const PAGE_SIZE = 10;
  const SEARCH_DEBOUNCE_MS = 300;

  interface Filters {
    search: string;
    muscleGroup: MuscleGroup | null;
    equipment: Equipment | null;
    page: number;
  }

  function filtersFromQuery(querystring: string | undefined): Filters {
    const params = new URLSearchParams(querystring ?? '');
    const rawPage = Number.parseInt(params.get('page') ?? '1', 10);
    const muscleGroup = params.get('muscle_group');
    const equipment = params.get('equipment');
    return {
      search: params.get('search') ?? '',
      muscleGroup:
        muscleGroup !== null && isMuscleGroup(muscleGroup) ? muscleGroup : null,
      equipment:
        equipment !== null && isEquipment(equipment) ? equipment : null,
      page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    };
  }

  // Filters live in the route query/hash state; no second state layer.
  const filters = $derived(filtersFromQuery(router.querystring));

  let phase = $state<'loading' | 'error' | 'ready'>('loading');
  let items = $state<Exercise[]>([]);
  let total = $state(0);
  let message = $state<string | null>(null);

  let requestId = 0;
  let controller: AbortController | null = null;

  async function load(target: Filters): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    phase = 'loading';
    try {
      const result = await listExercises(
        {
          page: target.page,
          pageSize: PAGE_SIZE,
          search: target.search === '' ? undefined : target.search,
          muscle_group: target.muscleGroup ?? undefined,
          equipment: target.equipment ?? undefined,
        },
        controller.signal,
      );
      // Stale responses are ignored by request identity.
      if (id !== requestId) {
        return;
      }
      items = result.items;
      total = result.total;
      message = null;
      phase = 'ready';
    } catch (error) {
      if (id !== requestId || isAbortError(error)) {
        return;
      }
      if (isUnauthorizedError(error)) {
        session.noteUnauthorized();
        return;
      }
      message = describeFailure(error);
      phase = 'error';
    }
  }

  $effect(() => {
    void load(filters);
  });

  // Controlled search input: debounced toward the route query, superseded
  // reads are aborted in load(). Route changes from elsewhere (back button)
  // sync back into the input while no keystroke is pending.
  let searchInput = $state('');
  let pendingSearch = false;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    const routeSearch = filters.search;
    if (pendingSearch) {
      return;
    }
    untrack(() => {
      if (routeSearch !== searchInput) {
        searchInput = routeSearch;
      }
    });
  });

  function handleSearchInput(): void {
    pendingSearch = true;
    if (searchTimer !== null) {
      clearTimeout(searchTimer);
    }
    const value = searchInput;
    searchTimer = setTimeout(() => {
      searchTimer = null;
      pendingSearch = false;
      setQuery({ search: value, page: undefined });
    }, SEARCH_DEBOUNCE_MS);
  }

  onDestroy(() => {
    requestId += 1;
    controller?.abort();
    if (searchTimer !== null) {
      clearTimeout(searchTimer);
    }
  });

  function setQuery(patch: {
    search?: string;
    muscle_group?: string;
    equipment?: string;
    page?: number;
  }): void {
    const next = new SvelteURLSearchParams(router.querystring ?? '');
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === '') {
        next.delete(key);
      } else {
        next.set(key, String(value));
      }
    }
    const querystring = next.toString();
    void push(querystring === '' ? '/catalog' : `/catalog?${querystring}`);
  }

  function selectValue(event: Event): string {
    return (event.currentTarget as HTMLSelectElement).value;
  }

  // Form visibility: creating or editing one custom entry at a time.
  let creating = $state(false);
  let editing = $state<Exercise | null>(null);

  function handleFormClose(saved: boolean): void {
    creating = false;
    editing = null;
    if (saved) {
      // Refetch the affected visible page; server ordering stays authoritative.
      void load(filters);
    }
  }

  const pageCount = $derived(Math.max(1, Math.ceil(total / PAGE_SIZE)));

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
</script>

<svelte:head>
  <title>Catalog · BaseFit</title>
</svelte:head>

<h1 tabindex="-1">Catalog</h1>

<div class="mt-4 flex flex-col gap-3">
  <div>
    <label for="catalog-search" class="block text-sm font-medium">Search</label>
    <input
      id="catalog-search"
      name="search"
      type="search"
      autocomplete="off"
      placeholder="Filter by name"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
      bind:value={searchInput}
      oninput={handleSearchInput}
    />
  </div>

  <div class="flex flex-col gap-3 sm:flex-row">
    <div class="flex-1">
      <label for="filter-muscle-group" class="block text-sm font-medium"
        >Muscle group</label
      >
      <select
        id="filter-muscle-group"
        name="muscle_group"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
        value={filters.muscleGroup ?? ''}
        onchange={(event) =>
          setQuery({ muscle_group: selectValue(event), page: undefined })}
      >
        <option value="">All</option>
        {#each muscleGroupValues as value (value)}
          <option {value}>{muscleGroupLabels[value]}</option>
        {/each}
      </select>
    </div>
    <div class="flex-1">
      <label for="filter-equipment" class="block text-sm font-medium"
        >Equipment</label
      >
      <select
        id="filter-equipment"
        name="equipment"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
        value={filters.equipment ?? ''}
        onchange={(event) =>
          setQuery({ equipment: selectValue(event), page: undefined })}
      >
        <option value="">All</option>
        {#each equipmentValues as value (value)}
          <option {value}>{equipmentLabels[value]}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if !creating && editing === null}
    <button
      type="button"
      class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
      onclick={() => {
        creating = true;
      }}
    >
      New custom exercise
    </button>
  {/if}

  {#if creating}
    <ExerciseForm exercise={null} onclose={handleFormClose} />
  {:else if editing !== null}
    <!-- Remount per target so editing always starts from current values. -->
    {#key editing.id}
      <ExerciseForm exercise={editing} onclose={handleFormClose} />
    {/key}
  {/if}

  {#if phase === 'loading'}
    <p role="status" class="text-sm text-muted">Loading catalog…</p>
  {:else if phase === 'error'}
    <p role="alert" class="text-sm text-danger">{message}</p>
    <button
      type="button"
      class="min-h-11 w-fit rounded-md border border-edge px-4 text-sm font-medium"
      onclick={() => void load(filters)}>Retry</button
    >
  {:else if items.length === 0}
    <p class="text-sm text-muted">
      No exercises match the current search or filters.
    </p>
  {:else}
    <ul class="flex flex-col gap-2">
      {#each items as entry (entry.id)}
        <li class="rounded-md border border-edge bg-surface px-3 py-2">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="font-medium">
                {entry.name}
                <span
                  class="ml-2 rounded-full border border-edge px-2 py-0.5 text-xs font-normal text-muted"
                >
                  {entry.is_default ? 'Default' : 'Custom'}
                </span>
              </p>
              <p class="text-sm text-muted">
                {muscleGroupLabels[entry.muscle_group]} · {equipmentLabels[
                  entry.equipment
                ]} ·
                {describeLoad(entry)}
              </p>
            </div>
            {#if !entry.is_default}
              <button
                type="button"
                class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md border border-edge px-3"
                aria-label={`Edit ${entry.name}`}
                title={`Edit ${entry.name}`}
                onclick={() => {
                  editing = entry;
                }}
              >
                <ActionIcon name="edit" />
              </button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>

    <nav
      aria-label="Catalog pages"
      class="flex items-center justify-between gap-2"
    >
      <p class="text-sm text-muted">
        {total}
        {total === 1 ? 'exercise' : 'exercises'} · page {filters.page} of {pageCount}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 text-sm font-medium disabled:opacity-40"
          disabled={filters.page <= 1}
          onclick={() => setQuery({ page: filters.page - 1 })}
        >
          Previous
        </button>
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 text-sm font-medium disabled:opacity-40"
          disabled={filters.page >= pageCount}
          onclick={() => setQuery({ page: filters.page + 1 })}
        >
          Next
        </button>
      </div>
    </nav>
  {/if}
</div>
