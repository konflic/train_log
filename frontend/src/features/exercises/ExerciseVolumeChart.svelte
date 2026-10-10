<script lang="ts">
  import type { ExerciseStatsSession } from '../../api';
  import { sessionDate, volumeLabel } from './statsFormat';

  let {
    sessions,
    utcOffsetMinutes,
  }: {
    sessions: ExerciseStatsSession[];
    utcOffsetMinutes: number;
  } = $props();

  const maxKnown = $derived(
    sessions.reduce(
      (max, session) =>
        session.volume_kg_reps !== null && session.volume_kg_reps > max
          ? session.volume_kg_reps
          : max,
      0,
    ),
  );

  /** Normalized bar height against the largest known session volume. */
  function barHeight(session: ExerciseStatsSession): string {
    const volume = session.volume_kg_reps;
    if (volume === null) return '34%';
    if (volume === 0 || maxKnown === 0) return '3px';
    return `${Math.max(4, Math.round((volume / maxKnown) * 100))}%`;
  }

  function barClass(session: ExerciseStatsSession): string {
    const parts = ['exercise-volume-chart__bar'];
    if (session.volume_kg_reps === null) parts.push('bar-unknown');
    else if (!session.volume_complete) parts.push('bar-partial');
    else if (session.volume_kg_reps === 0) parts.push('bar-zero');
    return parts.join(' ');
  }

  function shortDate(session: ExerciseStatsSession): string {
    const date = sessionDate(session, utcOffsetMinutes);
    // Columns keep the compact month-day; the value list keeps full dates.
    return date.length === 10 ? date.slice(5) : date;
  }
</script>

<section
  class="exercise-volume-chart mt-4 rounded-lg border border-edge bg-surface p-4"
  aria-labelledby="exercise-volume-chart-heading"
>
  <h2 id="exercise-volume-chart-heading" class="font-semibold">
    Volume by session
  </h2>
  {#if sessions.length === 0}
    <p class="mt-2 text-sm text-muted">
      No finished sessions with this exercise yet
    </p>
  {:else}
    <p class="mt-1 text-sm text-muted">
      Latest {sessions.length} finished
      {sessions.length === 1 ? 'session' : 'sessions'}, oldest to newest
    </p>
    <ol class="mt-3 flex items-end gap-1" style="height: 8rem">
      {#each sessions as session (session.workout_id)}
        <li class="flex h-full min-w-0 flex-1 flex-col justify-end">
          <a
            class="flex h-full flex-col justify-end"
            href="#/history/{session.workout_id}"
            aria-label="{sessionDate(session, utcOffsetMinutes)}: {volumeLabel(
              session.volume_kg_reps,
              session.volume_complete,
            )}, {session.completed_set_count} completed
            {session.completed_set_count === 1 ? 'set' : 'sets'}, open workout"
          >
            <span class={barClass(session)} style="height: {barHeight(session)}"
            ></span>
            <span class="mt-1 block truncate text-center text-xs text-muted"
              >{shortDate(session)}</span
            >
          </a>
        </li>
      {/each}
    </ol>
    <ul class="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
      {#each sessions as session (session.workout_id)}
        <li class="flex justify-between gap-2">
          <a class="text-primary" href="#/history/{session.workout_id}">
            {sessionDate(session, utcOffsetMinutes)}
          </a>
          <span
            class:text-sync-pending={session.volume_kg_reps !== null &&
              !session.volume_complete}
            class:text-muted={session.volume_kg_reps === null}
          >
            {volumeLabel(session.volume_kg_reps, session.volume_complete)}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .exercise-volume-chart__bar {
    display: block;
    width: 100%;
    border-radius: 3px 3px 0 0;
    background-color: var(--primary);
  }

  .bar-zero {
    /* A known zero stays a visible baseline sliver, distinct from missing. */
    background-color: var(--muted);
  }

  .bar-partial {
    background-image: repeating-linear-gradient(
      45deg,
      var(--primary) 0,
      var(--primary) 4px,
      var(--surface) 4px,
      var(--surface) 7px
    );
    outline: 1px solid var(--primary);
  }

  .bar-unknown {
    background: none;
    border: 1px dashed var(--muted);
    border-radius: 3px;
  }
</style>
