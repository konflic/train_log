<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { listWorkouts, type WorkoutSummary } from '../../api';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import { formatTimestampAtOffset } from '../../lib/offsetTime';
  import { isUnauthorizedError, session } from '../auth/session.svelte';

  let { utcOffsetMinutes }: { utcOffsetMinutes: number } = $props();

  const PAGE_SIZE = 5;

  let phase = $state<'loading' | 'error' | 'ready'>('loading');
  let items = $state<WorkoutSummary[]>([]);
  let total = $state(0);
  let message = $state<string | null>(null);

  let requestId = 0;
  let controller: AbortController | null = null;

  async function load(): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    phase = 'loading';
    try {
      const page = await listWorkouts(
        { status: 'active', page: 1, pageSize: PAGE_SIZE },
        controller.signal,
      );
      if (id !== requestId) {
        return;
      }
      items = page.items;
      total = page.total;
      message = null;
      phase = 'ready';
    } catch (error) {
      if (id !== requestId || isAbortError(error)) {
        return;
      }
      if (isUnauthorizedError(error)) {
        // Session expired while this read was in flight; pause everything.
        session.noteUnauthorized();
        return;
      }
      message = describeFailure(error);
      phase = 'error';
    }
  }

  function startedAt(workout: WorkoutSummary): string {
    return (
      formatTimestampAtOffset(workout.started_at, utcOffsetMinutes) ??
      workout.started_at
    );
  }

  onMount(() => {
    void load();
  });

  onDestroy(() => {
    requestId += 1;
    controller?.abort();
  });
</script>

<section
  aria-labelledby="active-workouts-heading"
  class="rounded-lg border border-edge bg-surface p-4"
>
  <h2 id="active-workouts-heading" class="text-lg font-semibold">
    Active workouts
  </h2>
  {#if phase === 'loading'}
    <p role="status" class="mt-2 text-sm text-muted">
      Loading active workouts…
    </p>
  {:else if phase === 'error'}
    <p role="alert" class="mt-2 text-sm text-danger">{message}</p>
    <button
      type="button"
      class="mt-2 min-h-11 rounded-md border border-edge px-4 text-sm font-medium"
      onclick={() => void load()}>Retry</button
    >
  {:else if items.length === 0}
    <p class="mt-2 text-sm text-muted">
      No active workouts. Quick start arrives with the workout editor.
    </p>
  {:else}
    <ul class="mt-2 flex flex-col gap-2">
      {#each items as workout (workout.id)}
        <li class="rounded-md border border-edge px-3 py-2">
          <p class="font-medium">{workout.name ?? 'Unnamed workout'}</p>
          <p class="text-sm text-muted">Started {startedAt(workout)}</p>
        </li>
      {/each}
    </ul>
    {#if total > items.length}
      <p class="mt-2 text-sm text-muted">{total} active in total.</p>
    {/if}
  {/if}
</section>
