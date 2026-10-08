<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { fetchStatsSummary, type StatsSummary } from '../../api';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import { formatUtcOffset, weekBounds } from '../../lib/offsetTime';
  import { isUnauthorizedError, session } from '../auth/session.svelte';

  let { utcOffsetMinutes }: { utcOffsetMinutes: number } = $props();

  let phase = $state<'loading' | 'error' | 'ready'>('loading');
  let summary = $state<StatsSummary | null>(null);
  let bounds = $state<{ monday: string; sunday: string } | null>(null);
  let message = $state<string | null>(null);

  let requestId = 0;
  let controller: AbortController | null = null;

  async function load(): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    // The week is derived from the current instant plus the profile's fixed
    // offset with date-only integer math, never the browser timezone. Both
    // API bounds are inclusive local dates.
    const week = weekBounds(Date.now(), utcOffsetMinutes);
    bounds = week;
    phase = 'loading';
    try {
      const result = await fetchStatsSummary(
        { date_from: week.monday, date_to: week.sunday },
        controller.signal,
      );
      if (id !== requestId) {
        return;
      }
      summary = result;
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

  // Refresh the weekly range on foreground return across a week boundary.
  function handleVisibilityChange(): void {
    if (document.visibilityState !== 'visible') {
      return;
    }
    const current = weekBounds(Date.now(), utcOffsetMinutes);
    if (bounds !== null && current.monday !== bounds.monday) {
      void load();
    }
  }

  onMount(() => {
    void load();
    document.addEventListener('visibilitychange', handleVisibilityChange);
  });

  onDestroy(() => {
    requestId += 1;
    controller?.abort();
    document.removeEventListener('visibilitychange', handleVisibilityChange);
  });
</script>

<section
  aria-labelledby="weekly-summary-heading"
  class="rounded-lg border border-edge bg-surface p-4"
>
  <h2 id="weekly-summary-heading" class="text-lg font-semibold">This week</h2>
  {#if bounds !== null}
    <p class="text-sm text-muted">
      {bounds.monday} – {bounds.sunday} ({formatUtcOffset(utcOffsetMinutes)})
    </p>
  {/if}
  {#if phase === 'loading'}
    <p role="status" class="mt-2 text-sm text-muted">Loading weekly summary…</p>
  {:else if phase === 'error'}
    <p role="alert" class="mt-2 text-sm text-danger">{message}</p>
    <button
      type="button"
      class="mt-2 min-h-11 rounded-md border border-edge px-4 text-sm font-medium"
      onclick={() => void load()}>Retry</button
    >
  {:else if summary !== null}
    <dl class="mt-2 grid grid-cols-2 gap-2">
      <div class="rounded-md border border-edge px-3 py-2">
        <dt class="text-sm text-muted">Workouts</dt>
        <dd class="text-xl font-semibold tabular-nums">
          {summary.workout_count}
        </dd>
      </div>
      <div class="rounded-md border border-edge px-3 py-2">
        <dt class="text-sm text-muted">Completed sets</dt>
        <dd class="text-xl font-semibold tabular-nums">
          {summary.completed_set_count}
        </dd>
      </div>
      <div class="rounded-md border border-edge px-3 py-2">
        <dt class="text-sm text-muted">Training days</dt>
        <dd class="text-xl font-semibold tabular-nums">
          {summary.training_day_count}
        </dd>
      </div>
      <div class="rounded-md border border-edge px-3 py-2">
        <dt class="text-sm text-muted">Volume</dt>
        <dd class="text-xl font-semibold tabular-nums">
          {#if summary.total_volume_kg_reps === null}
            Unknown
          {:else}
            {summary.total_volume_kg_reps}
            <span class="text-sm font-normal"
              >kg·reps{summary.volume_complete ? '' : ' (partial)'}</span
            >
          {/if}
        </dd>
      </div>
    </dl>
    {#if !summary.volume_complete}
      <p class="mt-2 text-sm text-muted">
        {summary.unknown_load_set_count}
        completed {summary.unknown_load_set_count === 1 ? 'set' : 'sets'} without
        a recorded load, so the known volume is partial, not complete.
      </p>
    {/if}
    <p class="mt-2 text-sm">
      Current streak: <span class="font-semibold tabular-nums"
        >{summary.current_week_streak}</span
      >
      {summary.current_week_streak === 1 ? 'week' : 'weeks'}
      <span class="text-muted">(full history)</span>
    </p>
  {/if}
</section>
