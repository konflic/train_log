<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    fetchStatsSummary,
    type StatsSummary,
    type StatsSummaryQuery,
  } from '../../api';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import {
    formatUtcOffset,
    monthBounds,
    weekBounds,
  } from '../../lib/offsetTime';
  import { isUnauthorizedError, session } from '../auth/session.svelte';

  let { utcOffsetMinutes }: { utcOffsetMinutes: number } = $props();

  const TABS = [
    { id: 'week', label: 'Week' },
    { id: 'month', label: 'Month' },
    { id: 'total', label: 'Total' },
  ] as const;

  type SummaryTab = (typeof TABS)[number]['id'];

  /** Inclusive local bounds; both `null` means unbounded full history. */
  interface SummaryRange {
    from: string | null;
    to: string | null;
  }

  let tab = $state<SummaryTab>('week');
  let phase = $state<'loading' | 'error' | 'ready'>('loading');
  let summary = $state<StatsSummary | null>(null);
  let range = $state<SummaryRange | null>(null);
  let message = $state<string | null>(null);

  let requestId = 0;
  let controller: AbortController | null = null;

  // Every range is derived from the current instant plus the profile's fixed
  // offset with date-only integer math, never the browser timezone.
  function rangeFor(selected: SummaryTab): SummaryRange {
    if (selected === 'total') return { from: null, to: null };
    if (selected === 'month') {
      const month = monthBounds(Date.now(), utcOffsetMinutes);
      return { from: month.first, to: month.last };
    }
    const week = weekBounds(Date.now(), utcOffsetMinutes);
    return { from: week.monday, to: week.sunday };
  }

  async function load(): Promise<void> {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    const bounds = rangeFor(tab);
    range = bounds;
    phase = 'loading';
    const query: StatsSummaryQuery =
      bounds.from === null || bounds.to === null
        ? {}
        : { date_from: bounds.from, date_to: bounds.to };
    try {
      const result = await fetchStatsSummary(query, controller.signal);
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

  function select(selected: SummaryTab): void {
    if (selected === tab) return;
    tab = selected;
    void load();
  }

  // Refresh the selected range on foreground return across its boundary.
  function handleVisibilityChange(): void {
    if (document.visibilityState !== 'visible') {
      return;
    }
    if (range !== null && rangeFor(tab).from !== range.from) {
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
  aria-labelledby="summary-heading"
  class="rounded-lg border border-edge bg-surface p-4"
>
  <h2 id="summary-heading" class="text-lg font-semibold">Summary</h2>
  <div role="tablist" aria-label="Summary range" class="mt-2 flex gap-2">
    {#each TABS as item (item.id)}
      <button
        id={`summary-tab-${item.id}`}
        type="button"
        role="tab"
        aria-selected={tab === item.id}
        class="min-h-11 rounded-md border px-4 text-sm font-medium {tab ===
        item.id
          ? 'border-primary bg-primary text-primary-content'
          : 'border-edge'}"
        onclick={() => select(item.id)}>{item.label}</button
      >
    {/each}
  </div>
  <div role="tabpanel" aria-labelledby={`summary-tab-${tab}`}>
    {#if range !== null}
      <p class="mt-2 text-sm text-muted">
        {#if range.from === null || range.to === null}
          Full history
        {:else}
          {range.from} – {range.to} ({formatUtcOffset(utcOffsetMinutes)})
        {/if}
      </p>
    {/if}
    {#if phase === 'loading'}
      <p role="status" class="mt-2 text-sm text-muted">Loading summary…</p>
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
  </div>
</section>
