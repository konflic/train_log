<script lang="ts">
  import { onMount } from 'svelte';
  import { push } from 'svelte-spa-router';
  import {
    createTrainingPlan,
    deleteTrainingPlan,
    getTrainingPlan,
    listExercises,
    listTrainingPlans,
    updateTrainingPlan,
    type Exercise,
    type TrainingPlan,
    type TrainingPlanContent,
    type TrainingPlanExerciseInput,
    type TrainingPlanSetInput,
  } from '../../api';
  import { describeFailure } from '../../lib/failures';
  import { session } from '../auth/session.svelte';
  import { activeSession } from '../workout/activeSession.svelte';
  import { startSession } from '../workout/startSession';

  let plans = $state<TrainingPlan[]>([]);
  let catalog = $state<Exercise[]>([]);
  let selected = $state<TrainingPlan | null>(null);
  let form = $state<TrainingPlanContent>({
    name: '',
    notes: null,
    exercises: [],
  });
  let initialForm = $state<TrainingPlanContent | null>(null);
  let phase = $state<'loading' | 'list' | 'editing'>('loading');
  let busy = $state(false);
  let message = $state<string | null>(null);

  function emptySet(entry: Exercise) {
    return {
      target_reps: null,
      target_weight_kg: null,
      side:
        entry.load_type === 'split_weight' && entry.side_count === 1
          ? ('left' as const)
          : ('bilateral' as const),
      bw_percent_override: null,
    };
  }

  function inputFromPlan(plan: TrainingPlan): TrainingPlanContent {
    return {
      name: plan.name,
      notes: plan.notes,
      exercises: plan.exercises.map((exercise) => ({
        catalog_id: exercise.catalog_id,
        notes: exercise.notes,
        sets: exercise.sets.map((set) => ({
          target_reps: set.target_reps,
          target_weight_kg: set.target_weight_kg,
          side: set.side,
          bw_percent_override: set.bw_percent_override,
        })),
      })),
    };
  }

  async function load(): Promise<void> {
    message = null;
    try {
      const [page, exercisePage] = await Promise.all([
        listTrainingPlans(),
        listExercises({ page: 1, pageSize: 100 }),
      ]);
      catalog = exercisePage.items;
      plans = await Promise.all(
        page.items.map((item) => getTrainingPlan(item.id)),
      );
      phase = 'list';
    } catch (error) {
      message = describeFailure(error);
      phase = 'list';
    }
  }

  function beginCreate(): void {
    selected = null;
    form = { name: '', notes: null, exercises: [] };
    initialForm = $state.snapshot(form);
    phase = 'editing';
  }

  function beginEdit(plan: TrainingPlan): void {
    selected = plan;
    form = inputFromPlan(plan);
    initialForm = $state.snapshot(form);
    phase = 'editing';
  }

  function addExercise(): void {
    const entry = catalog[0];
    if (!entry || form.exercises.length >= 25) return;
    form.exercises.push({
      catalog_id: entry.id,
      notes: null,
      sets: [emptySet(entry)],
    });
  }

  function changeExercise(
    exercise: TrainingPlanExerciseInput,
    id: string,
  ): void {
    const entry = catalog.find((item) => item.id === id);
    if (!entry) return;
    exercise.catalog_id = id;
    exercise.sets = exercise.sets.map(() => emptySet(entry));
  }

  function parseTarget(raw: string): number | null {
    if (raw === '') return null;
    return /^\d+$/.test(raw) && Number.isSafeInteger(Number(raw))
      ? Number(raw)
      : null;
  }

  function setTargetSide(set: TrainingPlanSetInput, side: string): void {
    set.side = side as TrainingPlanSetInput['side'];
  }

  function setSummary(set: TrainingPlanSetInput): string {
    const targets = [
      set.target_reps === null ? 'no reps target' : `${set.target_reps} reps`,
      set.target_weight_kg === null ? null : `${set.target_weight_kg} kg`,
      set.bw_percent_override === null
        ? null
        : `${set.bw_percent_override}% bodyweight`,
      set.side === 'bilateral' ? null : set.side,
    ].filter((target): target is string => target !== null);
    return targets.join(', ');
  }

  async function save(): Promise<void> {
    if (busy || form.name.trim() === '') return;
    busy = true;
    message = null;
    try {
      const saved = selected
        ? await updateTrainingPlan(selected.id, {
            ...$state.snapshot(form),
            name: form.name.trim(),
            revision: selected.revision,
          })
        : await createTrainingPlan({
            ...$state.snapshot(form),
            name: form.name.trim(),
          });
      const index = plans.findIndex((plan) => plan.id === saved.id);
      if (index >= 0) plans[index] = saved;
      else plans.push(saved);
      selected = saved;
      form = inputFromPlan(saved);
      initialForm = null;
      phase = 'list';
    } catch (error) {
      message = describeFailure(error);
    } finally {
      busy = false;
    }
  }

  function cancelEditing(): void {
    if (
      initialForm !== null &&
      JSON.stringify($state.snapshot(form)) !== JSON.stringify(initialForm) &&
      !window.confirm('Discard unsaved plan changes?')
    )
      return;
    initialForm = null;
    phase = 'list';
  }

  async function remove(plan: TrainingPlan): Promise<void> {
    if (!window.confirm(`Delete training plan “${plan.name}”?`)) return;
    try {
      await deleteTrainingPlan(plan.id, plan.revision);
      plans = plans.filter((item) => item.id !== plan.id);
    } catch (error) {
      message = describeFailure(error);
    }
  }

  async function start(plan: TrainingPlan): Promise<void> {
    if (busy || session.user === null || activeSession.workoutId !== null)
      return;
    busy = true;
    message = null;
    try {
      const draft = await startSession(session.user.id, {
        planId: plan.id,
        revision: plan.revision,
      });
      activeSession.setActive(draft.workout_id);
      await push(
        `/workouts/${draft.workout_id}?draft=${encodeURIComponent(draft.draft_id)}`,
      );
    } catch (error) {
      message = describeFailure(error);
      await activeSession.refresh(session.user.id);
    } finally {
      busy = false;
    }
  }

  onMount(() => void load());
</script>

<svelte:head><title>Training plans · BaseFit</title></svelte:head>
<h1 tabindex="-1">Training plans</h1>
<p class="mt-2 text-muted">
  Saving or previewing a plan does not start a session.
</p>
{#if message}<p role="alert" class="mt-3 text-danger">{message}</p>{/if}
{#if phase === 'loading'}
  <p role="status" class="mt-4">Loading plans…</p>
{:else if phase === 'editing'}
  <form
    class="mt-4 grid gap-4"
    onsubmit={(event) => {
      event.preventDefault();
      void save();
    }}
  >
    <label class="text-sm font-medium"
      >Name<input
        bind:value={form.name}
        maxlength="100"
        required
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
      /></label
    >
    <label class="text-sm font-medium"
      >Notes<textarea
        value={form.notes ?? ''}
        maxlength="2000"
        class="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2"
        oninput={(event) => (form.notes = event.currentTarget.value || null)}
      ></textarea></label
    >
    {#each form.exercises as exercise, exerciseIndex (exerciseIndex)}
      {@const entry = catalog.find((item) => item.id === exercise.catalog_id)}
      <fieldset class="rounded-lg border border-edge p-3">
        <legend class="px-1 font-medium">Exercise {exerciseIndex + 1}</legend>
        <select
          aria-label={`Exercise ${exerciseIndex + 1}`}
          value={exercise.catalog_id}
          class="min-h-11 w-full rounded-md border border-edge bg-surface px-3"
          onchange={(event) =>
            changeExercise(exercise, event.currentTarget.value)}
        >
          {#each catalog as option (option.id)}<option value={option.id}
              >{option.name}</option
            >{/each}
        </select>
        {#each exercise.sets as set, setIndex (setIndex)}
          <div class="mt-3 grid grid-cols-2 gap-2">
            <label class="text-sm"
              >Target reps<input
                inputmode="numeric"
                value={set.target_reps ?? ''}
                class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                oninput={(event) =>
                  (set.target_reps = parseTarget(event.currentTarget.value))}
              /></label
            >
            {#if entry?.load_type !== 'bodyweight'}<label class="text-sm"
                >Target kg<input
                  inputmode="numeric"
                  value={set.target_weight_kg ?? ''}
                  class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                  oninput={(event) =>
                    (set.target_weight_kg = parseTarget(
                      event.currentTarget.value,
                    ))}
                /></label
              >{/if}
            {#if entry?.bodyweight_percent !== null && entry?.bodyweight_percent !== undefined}<label
                class="text-sm"
                >Bodyweight % override<input
                  type="number"
                  min="1"
                  max="100"
                  inputmode="numeric"
                  value={set.bw_percent_override ?? ''}
                  class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                  oninput={(event) =>
                    (set.bw_percent_override = parseTarget(
                      event.currentTarget.value,
                    ))}
                /></label
              >{/if}
            {#if entry?.load_type === 'split_weight' && entry.side_count === 1}<label
                class="text-sm"
                >Side<select
                  class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                  value={set.side}
                  onchange={(event) =>
                    setTargetSide(set, event.currentTarget.value)}
                  ><option value="left">Left</option><option value="right"
                    >Right</option
                  ></select
                ></label
              >{/if}
          </div>
          <button
            type="button"
            class="mt-2 min-h-11 rounded-md border border-edge px-3"
            onclick={() => exercise.sets.splice(setIndex, 1)}>Remove set</button
          >
        {/each}
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="min-h-11 rounded-md border border-edge px-3"
            onclick={() => entry && exercise.sets.push(emptySet(entry))}
            >Add set</button
          >
          <button
            type="button"
            class="min-h-11 rounded-md border border-danger px-3 text-danger"
            onclick={() => form.exercises.splice(exerciseIndex, 1)}
            >Remove exercise</button
          >
        </div>
      </fieldset>
    {/each}
    <button
      type="button"
      class="min-h-11 rounded-md border border-edge px-4"
      onclick={addExercise}
    >
      Add exercise
    </button>
    <div class="flex gap-2">
      <button
        disabled={busy}
        class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
      >
        {busy ? 'Saving…' : 'Save plan'}
      </button>
      <button
        type="button"
        class="min-h-11 rounded-md border border-edge px-4"
        onclick={cancelEditing}
      >
        Cancel
      </button>
    </div>
  </form>
{:else}
  <button
    class="mt-4 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
    onclick={beginCreate}
  >
    Create plan
  </button>
  {#if plans.length === 0}<p class="mt-4">No training plans yet.</p>{/if}
  {#if activeSession.workoutId !== null}<p class="mt-4">
      An active session is ready to resume.
      <a
        class="font-medium text-primary underline"
        href={`#/workouts/${activeSession.workoutId}`}>Resume active session</a
      >
    </p>{/if}
  <ul class="mt-4 grid gap-3">
    {#each plans as plan (plan.id)}
      <li class="rounded-lg border border-edge bg-surface p-4">
        <h2 class="font-semibold">{plan.name}</h2>
        {#if plan.notes}<p class="mt-1 text-sm text-muted">{plan.notes}</p>{/if}
        <p class="mt-2 text-sm">{plan.exercises.length} exercises</p>
        <details class="mt-2 text-sm">
          <summary class="cursor-pointer font-medium">Preview targets</summary>
          <ol class="mt-2 grid gap-2">
            {#each plan.exercises as exercise (exercise.id)}
              {@const entry = catalog.find(
                (item) => item.id === exercise.catalog_id,
              )}
              <li>
                <p>{entry?.name ?? 'Unavailable exercise'}</p>
                <ul class="ml-4 list-disc">
                  {#each exercise.sets as set (set.id)}
                    <li>{setSummary(set)}</li>
                  {/each}
                </ul>
              </li>
            {/each}
          </ol>
        </details>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            disabled={busy || activeSession.workoutId !== null}
            class="min-h-11 rounded-md bg-primary px-3 font-medium text-primary-content"
            onclick={() => void start(plan)}
          >
            Start session
          </button>
          <button
            class="min-h-11 rounded-md border border-edge px-3"
            onclick={() => beginEdit(plan)}>Edit</button
          >
          <button
            class="min-h-11 rounded-md border border-danger px-3 text-danger"
            onclick={() => void remove(plan)}>Delete</button
          >
        </div>
      </li>
    {/each}
  </ul>
{/if}
