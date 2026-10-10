<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { listWorkouts, type WorkoutSummary } from '../api';
  import {
    session,
    isUnauthorizedError,
  } from '../features/auth/session.svelte';
  import { describeFailure, isAbortError } from '../lib/failures';
  import { formatRelativeTime } from '../lib/relativeTime';

  const PAGE_SIZE = 20;
  let items = $state<WorkoutSummary[]>([]);
  let phase = $state<'loading' | 'ready' | 'error'>('loading');
  let message = $state<string | null>(null);
  let controller: AbortController | null = null;
  let requestId = 0;
  function finishedTime(workout: WorkoutSummary): string {
    if (workout.ended_at === null) return 'Not finished';
    return formatRelativeTime(workout.ended_at) ?? workout.ended_at;
  }

  function volume(workout: WorkoutSummary): string {
    if (workout.total_volume_kg_reps === null) return 'Unknown volume';
    return `${workout.total_volume_kg_reps} kg${workout.volume_complete ? '' : '+'}`;
  }

  async function load(): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    phase = 'loading';
    try {
      const result = await listWorkouts(
        {
          status: 'finished',
          page: 1,
          pageSize: PAGE_SIZE,
        },
        controller.signal,
      );
      if (id !== requestId) return;
      items = result.items;
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

  onMount(() => void load());
  onDestroy(() => {
    requestId += 1;
    controller?.abort();
  });
</script>

<svelte:head><title>History · BaseFit</title></svelte:head>
<h1 tabindex="-1">History</h1>
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
  <p class="mt-4 text-muted">No finished workouts yet</p>
{:else}
  <ul class="mt-4 flex flex-col gap-2">
    {#each items as workout (workout.id)}
      <li>
        <a
          href={`#/history/${workout.id}`}
          class="block min-h-11 rounded-lg border border-edge bg-surface p-3"
          ><p class="font-medium">{workout.name ?? 'Unnamed workout'}</p>
          <p class="text-sm text-muted">
            Finished {finishedTime(workout)} · {volume(workout)}
          </p></a
        >
      </li>
    {/each}
  </ul>
{/if}
