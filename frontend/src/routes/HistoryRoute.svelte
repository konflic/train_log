<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { listWorkouts, type WorkoutSummary } from '../api';
  import {
    session,
    isUnauthorizedError,
  } from '../features/auth/session.svelte';
  import { describeFailure, isAbortError } from '../lib/failures';
  import { formatTimestampAtOffset } from '../lib/offsetTime';

  const PAGE_SIZE = 20;
  let page = $state(1);
  let items = $state<WorkoutSummary[]>([]);
  let total = $state(0);
  let phase = $state<'loading' | 'ready' | 'error'>('loading');
  let message = $state<string | null>(null);
  let dateFrom = $state('');
  let dateTo = $state('');
  let controller: AbortController | null = null;
  let requestId = 0;
  const offset = $derived(session.user?.utc_offset_minutes ?? 0);

  function localTime(workout: WorkoutSummary): string {
    return (
      formatTimestampAtOffset(workout.started_at, offset) ?? workout.started_at
    );
  }

  async function load(nextPage = page): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    phase = 'loading';
    try {
      const result = await listWorkouts(
        {
          status: 'finished',
          page: nextPage,
          pageSize: PAGE_SIZE,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
        controller.signal,
      );
      if (id !== requestId) return;
      page = result.page;
      items = result.items;
      total = result.total;
      message = null;
      phase = 'ready';
    } catch (error) {
      if (id !== requestId || isAbortError(error)) return;
      if (isUnauthorizedError(error)) {
        session.noteUnauthorized();
        return;
      }
      message = describeFailure(error);
      phase = 'error';
    }
  }

  onMount(() => void load(1));
  onDestroy(() => {
    requestId += 1;
    controller?.abort();
  });
</script>

<svelte:head><title>History · BaseFit</title></svelte:head>
<h1 tabindex="-1">History</h1>
<form
  class="mt-4 grid gap-3 rounded-lg border border-edge bg-surface p-4 sm:grid-cols-2"
  onsubmit={(event) => {
    event.preventDefault();
    void load(1);
  }}
>
  <label class="text-sm font-medium"
    >From<input
      bind:value={dateFrom}
      type="date"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
    /></label
  >
  <label class="text-sm font-medium"
    >To<input
      bind:value={dateTo}
      type="date"
      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
    /></label
  >
  <button
    type="submit"
    class="min-h-11 rounded-md border border-edge px-4 font-medium"
    >Apply dates</button
  >
</form>
{#if phase === 'loading'}
  <p role="status" class="mt-4 text-muted">Loading finished workouts…</p>
{:else if phase === 'error'}
  <p role="alert" class="mt-4 text-danger">{message}</p>
  <button
    type="button"
    class="mt-3 min-h-11 rounded-md border border-edge px-4"
    onclick={() => void load()}>Retry</button
  >
{:else if items.length === 0}
  <p class="mt-4 text-muted">No finished workouts match these dates.</p>
{:else}
  <ul class="mt-4 flex flex-col gap-2">
    {#each items as workout (workout.id)}
      <li>
        <a
          href={`#/history/${workout.id}`}
          class="block min-h-11 rounded-lg border border-edge bg-surface p-4"
          ><p class="font-medium">{workout.name ?? 'Unnamed workout'}</p>
          <p class="text-sm text-muted">Started {localTime(workout)}</p></a
        >
      </li>
    {/each}
  </ul>
  <nav
    aria-label="History pages"
    class="mt-4 flex items-center justify-between"
  >
    <button
      type="button"
      disabled={page === 1}
      class="min-h-11 rounded-md border border-edge px-4 disabled:opacity-40"
      onclick={() => void load(page - 1)}>Previous</button
    >
    <p class="text-sm text-muted">
      Page {page} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
    </p>
    <button
      type="button"
      disabled={page * PAGE_SIZE >= total}
      class="min-h-11 rounded-md border border-edge px-4 disabled:opacity-40"
      onclick={() => void load(page + 1)}>Next</button
    >
  </nav>
{/if}
