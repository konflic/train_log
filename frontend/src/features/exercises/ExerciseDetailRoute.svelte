<script lang="ts">
  import { onDestroy } from 'svelte';
  import {
    ApiRequestError,
    fetchExerciseStats,
    getExercise,
    type ExerciseDetail,
    type ExerciseStats,
  } from '../../api';
  import { describeFailure, isAbortError } from '../../lib/failures';
  import { backDestination } from '../../lib/backNavigation.svelte';
  import { isUnauthorizedError, session } from '../auth/session.svelte';
  import { compactLoadLabel, muscleGroupLabels } from '../catalog/labels';
  import ExerciseAnimation from './ExerciseAnimation.svelte';
  import ExerciseVolumeChart from './ExerciseVolumeChart.svelte';
  import { volumeLabel } from './statsFormat';

  let { params = {} }: { params?: { id?: string } } = $props();

  // Catalog detail and personal statistics load independently: a failed
  // statistics read must not hide available guidance, and failed guidance
  // must not imply absent history. Each read owns its retry state.
  let detail = $state<ExerciseDetail | null>(null);
  let contentPhase = $state<'loading' | 'ready' | 'error' | 'not_found'>(
    'loading',
  );
  let contentMessage = $state<string | null>(null);

  let stats = $state<ExerciseStats | null>(null);
  let statsPhase = $state<'loading' | 'ready' | 'error'>('loading');
  let statsMessage = $state<string | null>(null);

  let contentController: AbortController | null = null;
  let statsController: AbortController | null = null;
  let contentRequestId = 0;
  let statsRequestId = 0;

  function isNotFound(error: unknown): boolean {
    return error instanceof ApiRequestError && error.problem.status === 404;
  }

  async function loadContent(exerciseId: string): Promise<void> {
    const requestId = ++contentRequestId;
    contentController?.abort();
    contentController = new AbortController();
    contentPhase = 'loading';
    try {
      const value = await getExercise(exerciseId, contentController.signal);
      if (requestId !== contentRequestId) return;
      detail = value;
      contentMessage = null;
      contentPhase = 'ready';
    } catch (error) {
      if (requestId !== contentRequestId || isAbortError(error)) return;
      if (isUnauthorizedError(error)) {
        session.noteUnauthorized();
        return;
      }
      if (isNotFound(error)) {
        contentPhase = 'not_found';
        return;
      }
      contentMessage = describeFailure(error);
      contentPhase = 'error';
    }
  }

  async function loadStats(exerciseId: string): Promise<void> {
    const requestId = ++statsRequestId;
    statsController?.abort();
    statsController = new AbortController();
    statsPhase = 'loading';
    try {
      const value = await fetchExerciseStats(
        exerciseId,
        statsController.signal,
      );
      if (requestId !== statsRequestId) return;
      stats = value;
      statsMessage = null;
      statsPhase = 'ready';
    } catch (error) {
      if (requestId !== statsRequestId || isAbortError(error)) return;
      if (isUnauthorizedError(error)) {
        session.noteUnauthorized();
        return;
      }
      if (isNotFound(error)) {
        // The content read owns the not-found presentation for the route.
        return;
      }
      statsMessage = describeFailure(error);
      statsPhase = 'error';
    }
  }

  function loadAll(exerciseId: string): void {
    if (exerciseId === '') return;
    void loadContent(exerciseId);
    void loadStats(exerciseId);
  }

  // A direct route visit falls back to Catalog as its back destination.
  const backHref = $derived(backDestination('/catalog'));
  const utcOffsetMinutes = $derived(session.user?.utc_offset_minutes ?? 0);
  const guidance = $derived(
    detail !== null && detail.is_default ? detail.guidance : null,
  );

  /** Precise load semantics, kept off compact cards and available here. */
  function loadSemantics(entry: ExerciseDetail): string {
    const parts: string[] = [];
    if (entry.load_type === 'bodyweight') {
      parts.push(
        `Logged with reps only; every completed set counts an estimated ${entry.bodyweight_percent}% of the bodyweight recorded on that workout.`,
      );
    } else if (entry.load_type === 'single_weight') {
      parts.push('The recorded weight is the total external load.');
    } else if (entry.side_count === 2) {
      parts.push(
        'The recorded weight is per dumbbell and one set covers both sides, so the external load is the weight times two.',
      );
    } else {
      parts.push(
        'One set covers one side; the recorded weight is the load for that side.',
      );
    }
    if (entry.load_type !== 'bodyweight' && entry.bodyweight_percent !== null) {
      parts.push(
        `An estimated ${entry.bodyweight_percent}% of the recorded bodyweight is added to the load.`,
      );
    }
    if (entry.bodyweight_percent !== null) {
      parts.push(
        'Bodyweight percentages are labeled estimates, not physical constants.',
      );
    }
    return parts.join(' ');
  }

  $effect(() => {
    loadAll(params.id ?? '');
  });

  onDestroy(() => {
    contentRequestId += 1;
    statsRequestId += 1;
    contentController?.abort();
    statsController?.abort();
  });
</script>

<svelte:head>
  <title>{detail?.name ?? 'Exercise'} · BaseFit</title>
</svelte:head>

<a
  id="exercise-detail-back"
  href="#{backHref}"
  class="inline-flex min-h-11 items-center text-sm font-medium text-primary"
  >Back</a
>

{#if contentPhase === 'not_found'}
  <h1 tabindex="-1" class="mt-2">Exercise not found</h1>
  <p class="mt-2 text-muted">This exercise is not part of your catalog</p>
  <a
    href="#/catalog"
    class="mt-4 inline-flex min-h-11 items-center rounded-md border border-edge px-4"
    >Open catalog</a
  >
{:else}
  {#if contentPhase === 'loading'}
    <h1 tabindex="-1" class="mt-2">Exercise</h1>
    <p role="status" class="mt-2 text-muted">Loading exercise…</p>
  {:else if contentPhase === 'error'}
    <h1 tabindex="-1" class="mt-2">Exercise unavailable</h1>
    <p role="alert" class="mt-2 text-danger">{contentMessage}</p>
    <button
      id="exercise-content-retry"
      type="button"
      class="mt-3 min-h-11 rounded-md border border-edge px-4"
      onclick={() => loadAll(params.id ?? '')}>Retry</button
    >
  {:else if detail !== null}
    <div class="exercise-detail mt-2">
      <h1 id="exercise-detail-name" tabindex="-1">{detail.name}</h1>
      <p class="mt-2 flex flex-wrap gap-2 text-sm">
        <span class="rounded-full border border-edge px-2 py-0.5 text-muted">
          {muscleGroupLabels[detail.muscle_group]}
        </span>
        <span class="rounded-full border border-edge px-2 py-0.5 text-muted">
          {compactLoadLabel(detail.load_type)}
        </span>
        {#if !detail.is_default}
          <span class="rounded-full border border-edge px-2 py-0.5 text-muted">
            Custom
          </span>
        {/if}
      </p>

      {#if guidance !== null}
        <div class="mt-4">
          <ExerciseAnimation
            animationKey={guidance.animation_key}
            exerciseName={detail.name}
          />
        </div>
      {/if}

      <section class="mt-4" aria-labelledby="exercise-description-heading">
        <h2 id="exercise-description-heading" class="font-semibold">
          About this exercise
        </h2>
        {#if detail.description !== null}
          <p id="exercise-detail-description" class="mt-1">
            {detail.description}
          </p>
        {:else}
          <p id="exercise-detail-description" class="mt-1 text-sm text-muted">
            No description provided
          </p>
        {/if}
        <details class="mt-2">
          <summary
            class="min-h-11 cursor-pointer text-sm font-medium text-primary"
            >How weight is logged</summary
          >
          <p id="exercise-load-semantics" class="mt-1 text-sm text-muted">
            {loadSemantics(detail)}
          </p>
        </details>
      </section>

      {#if guidance !== null}
        <section
          class="exercise-detail__technique mt-4"
          aria-labelledby="exercise-technique-heading"
        >
          <h2 id="exercise-technique-heading" class="font-semibold">
            How to perform
          </h2>
          <ol class="mt-2 list-decimal space-y-1 pl-5">
            {#each guidance.technique_steps as step (step)}
              <li>{step}</li>
            {/each}
          </ol>
        </section>

        <section
          class="exercise-detail__advice mt-4"
          aria-labelledby="exercise-advice-heading"
        >
          <h2 id="exercise-advice-heading" class="font-semibold">Form cues</h2>
          <ul class="mt-2 list-disc space-y-1 pl-5">
            {#each guidance.form_tips as tip (tip)}
              <li>{tip}</li>
            {/each}
          </ul>
        </section>

        <section class="mt-4" aria-labelledby="exercise-sources-heading">
          <h2 id="exercise-sources-heading" class="font-semibold">Sources</h2>
          <ul class="mt-2 flex flex-col gap-1 text-sm">
            {#each guidance.sources as source (source.url)}
              <li>
                <a
                  class="text-primary underline"
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer">{source.title}</a
                >
              </li>
            {/each}
          </ul>
          <p class="mt-2 text-sm text-muted">
            Guidance is evidence-informed rather than scientifically proven, and
            it is not medical advice. Individual anatomy and training context
            vary.
          </p>
        </section>
      {/if}
    </div>
  {/if}

  {#if statsPhase === 'loading'}
    <p role="status" class="mt-4 text-muted">Loading your statistics…</p>
  {:else if statsPhase === 'error'}
    <section class="mt-4 rounded-lg border border-edge bg-surface p-4">
      <p role="alert" class="text-sm text-danger">{statsMessage}</p>
      <button
        id="exercise-stats-retry"
        type="button"
        class="mt-3 min-h-11 rounded-md border border-edge px-4"
        onclick={() => loadAll(params.id ?? '')}>Retry statistics</button
      >
    </section>
  {:else if stats !== null}
    <section
      class="exercise-stats mt-4 rounded-lg border border-edge bg-surface p-4"
      aria-labelledby="exercise-stats-heading"
    >
      <h2 id="exercise-stats-heading" class="font-semibold">Your statistics</h2>
      <dl class="mt-3 grid grid-cols-2 gap-3">
        <div class="exercise-stats__metric rounded-md border border-edge p-3">
          <dt class="text-sm text-muted">Trainings</dt>
          <dd id="exercise-stat-trainings" class="text-xl font-semibold">
            {stats.training_count}
          </dd>
        </div>
        <div class="exercise-stats__metric rounded-md border border-edge p-3">
          <dt class="text-sm text-muted">Completed sets</dt>
          <dd id="exercise-stat-sets" class="text-xl font-semibold">
            {stats.completed_set_count}
          </dd>
        </div>
        <div class="exercise-stats__metric rounded-md border border-edge p-3">
          <dt class="text-sm text-muted">Lifetime volume</dt>
          <dd
            id="exercise-stat-volume"
            class="text-xl font-semibold"
            class:text-sync-pending={stats.total_volume_kg_reps !== null &&
              !stats.volume_complete}
          >
            {volumeLabel(stats.total_volume_kg_reps, stats.volume_complete)}
          </dd>
        </div>
        <div class="exercise-stats__metric rounded-md border border-edge p-3">
          <dt class="text-sm text-muted">Best estimated 1RM</dt>
          <dd id="exercise-stat-1rm" class="text-xl font-semibold">
            {stats.best_estimated_1rm_kg === null
              ? 'Unavailable for this exercise'
              : `${stats.best_estimated_1rm_kg} kg`}
          </dd>
        </div>
      </dl>
    </section>
    <ExerciseVolumeChart sessions={stats.sessions} {utcOffsetMinutes} />
  {/if}
{/if}
