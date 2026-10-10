<script lang="ts">
  import { onMount } from 'svelte';
  import { replace } from 'svelte-spa-router';
  import {
    ApiRequestError,
    deleteWorkout,
    getExercise,
    getWorkout,
    type ExerciseDetail,
    type WorkoutDetail,
  } from '../api';
  import ActionIcon from '../components/ActionIcon.svelte';
  import {
    session,
    isUnauthorizedError,
  } from '../features/auth/session.svelte';
  import {
    detailTotal,
    durationSeconds,
    exerciseLabel,
    percentageDelta,
    setLoad,
  } from '../features/history/history';
  import { describeFailure } from '../lib/failures';
  import { formatRelativeTime } from '../lib/relativeTime';

  let { params = {} }: { params?: { id?: string } } = $props();
  const workoutId = $derived(params.id ?? '');
  let detail = $state<WorkoutDetail | null>(null);
  let catalog = $state(new Map<string, ExerciseDetail>());
  let phase = $state<'loading' | 'ready' | 'error'>('loading');
  let message = $state<string | null>(null);
  let deleting = $state(false);

  function display(timestamp: string | null): string {
    if (timestamp === null) return 'Not finished';
    return formatRelativeTime(timestamp) ?? timestamp;
  }

  async function load(): Promise<void> {
    phase = 'loading';
    try {
      const value = await getWorkout(workoutId);
      const entries = await Promise.all(
        [
          ...new Set(value.exercises.map((exercise) => exercise.catalog_id)),
        ].map(async (id): Promise<[string, ExerciseDetail | null]> => {
          try {
            return [id, await getExercise(id)];
          } catch (error) {
            if (
              error instanceof ApiRequestError &&
              error.problem.status === 404
            ) {
              return [id, null];
            }
            throw error;
          }
        }),
      );
      detail = value;
      catalog = new Map(
        entries.filter(
          (entry): entry is [string, ExerciseDetail] => entry[1] !== null,
        ),
      );
      message = null;
      phase = 'ready';
    } catch (error) {
      if (isUnauthorizedError(error)) {
        session.noteUnauthorized();
        return;
      }
      message = describeFailure(error);
      phase = 'error';
    }
  }

  async function remove(): Promise<void> {
    if (!detail || deleting) return;
    if (
      !window.confirm(
        `Delete ${detail.name ?? 'this workout'}? This cannot be undone`,
      )
    )
      return;
    deleting = true;
    message = null;
    try {
      await deleteWorkout(detail.id, detail.revision);
      await replace('/history');
    } catch (error) {
      if (error instanceof ApiRequestError && error.problem.status === 404) {
        // A lost DELETE response is successful once the authoritative GET is absent.
        await replace('/history');
        return;
      }
      if (isUnauthorizedError(error)) session.noteUnauthorized();
      else message = describeFailure(error);
    } finally {
      deleting = false;
    }
  }

  onMount(() => void load());
</script>

<svelte:head><title>Workout detail · BaseFit</title></svelte:head>
{#if phase === 'loading'}
  <h1 tabindex="-1">Workout</h1>
  <p role="status" class="mt-2 text-muted">Loading workout…</p>
{:else if phase === 'error'}
  <h1 tabindex="-1">Workout unavailable</h1>
  <p role="alert" class="mt-2 text-danger">{message}</p>
  <button
    type="button"
    class="mt-3 min-h-11 rounded-md border border-edge px-4"
    onclick={() => void load()}>Retry</button
  >
{:else if detail}
  {@const total = detailTotal(detail)}
  <a
    href="#/history"
    class="inline-flex min-h-11 items-center text-sm font-medium text-primary"
    >Back to history</a
  >
  <h1 tabindex="-1" class="mt-2">{detail.name ?? 'Unnamed workout'}</h1>
  <dl
    class="mt-4 grid gap-3 rounded-lg border border-edge bg-surface p-4 text-sm sm:grid-cols-2"
  >
    <div>
      <dt class="text-muted">Started</dt>
      <dd>{display(detail.started_at)}</dd>
    </div>
    <div>
      <dt class="text-muted">Finished</dt>
      <dd>{display(detail.ended_at)}</dd>
    </div>
    <div>
      <dt class="text-muted">Duration</dt>
      <dd>
        {durationSeconds(detail) === null
          ? 'Unavailable'
          : `${durationSeconds(detail)} seconds`}
      </dd>
    </div>
    <div>
      <dt class="text-muted">Recorded bodyweight</dt>
      <dd>
        {detail.bodyweight_kg === null
          ? 'Unknown'
          : `${detail.bodyweight_kg} kg`}
      </dd>
    </div>
  </dl>
  <section
    class="mt-4 rounded-lg border border-edge bg-surface p-4"
    aria-labelledby="workout-total"
  >
    <h2 id="workout-total" class="font-semibold">Completed-set total</h2>
    <p>
      {total.knownVolume === null ? 'Unknown' : `${total.knownVolume} kg`} from
      {total.completedSetCount} completed sets{total.complete
        ? '.'
        : `; ${total.unknownLoadSetCount} loads unknown`}
    </p>
  </section>
  {#if detail.notes}<section
      class="mt-4 rounded-lg border border-edge bg-surface p-4"
    >
      <h2 class="font-semibold">Notes</h2>
      <p class="mt-1 whitespace-pre-wrap">{detail.notes}</p>
    </section>{/if}
  <div class="mt-4 flex flex-col gap-4">
    {#each detail.exercises as exercise (exercise.id)}
      <section
        class="exercise-card rounded-lg border border-edge bg-surface p-4"
      >
        <div
          class="exercise-card__header flex items-start justify-between gap-2"
        >
          <h2 class="font-semibold">{exerciseLabel(exercise, catalog)}</h2>
          <a
            class="exercise-card__info-link inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md border border-edge"
            href="#/exercises/{exercise.catalog_id}"
            aria-label="About {exerciseLabel(exercise, catalog)}"
            title="About {exerciseLabel(exercise, catalog)}"
          >
            <ActionIcon name="info" />
          </a>
        </div>
        {#if exercise.notes}<p class="mt-1 text-sm text-muted">
            {exercise.notes}
          </p>{/if}
        <ul class="mt-3 flex flex-col gap-2">
          {#each exercise.sets as set (set.id)}
            {@const load = setLoad(detail, exercise, set)}
            <li class="rounded-md border border-edge p-3">
              <p class="font-medium">
                Set {set.set_index + 1}: {set.reps === null
                  ? '—'
                  : `${set.reps} reps`} · {set.weight_kg === null
                  ? exercise.load_type === 'bodyweight'
                    ? 'Bodyweight'
                    : 'Unknown weight'
                  : `${set.weight_kg} kg`} · {set.done
                  ? 'Completed'
                  : 'Not completed'}
              </p>
              {#if set.done}<p class="mt-1 text-sm text-muted">
                  Effective load {load.effective_load_kg === null
                    ? 'unknown'
                    : `${load.effective_load_kg} kg`} · Volume {load.volume_kg_reps ===
                  null
                    ? 'unknown'
                    : `${load.volume_kg_reps} kg`}
                </p>{/if}
              {#each exercise.previous_performance?.pairs.filter((pair) => pair.current_set_id === set.id) ?? [] as pair (pair.previous_set_id)}
                <p class="mt-2 text-sm">
                  Previous set: {pair.previous.reps ?? '—'} reps. {pair.load_compatible &&
                  pair.delta.external_load_kg !== null
                    ? `Load change ${pair.delta.external_load_kg >= 0 ? '+' : ''}${pair.delta.external_load_kg} kg${percentageDelta(pair.current.external_load_kg, pair.previous.external_load_kg) === null ? '' : ` (${percentageDelta(pair.current.external_load_kg, pair.previous.external_load_kg)}%)`}.`
                    : 'Load comparison unavailable'}
                </p>
              {/each}
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  </div>
  {#if message}<p role="alert" class="mt-4 text-danger">{message}</p>{/if}
  <button
    type="button"
    disabled={deleting}
    class="mt-6 min-h-11 rounded-md border border-danger px-4 font-medium text-danger disabled:opacity-40"
    onclick={() => void remove()}
    >{deleting ? 'Deleting…' : 'Delete workout'}</button
  >
{/if}
