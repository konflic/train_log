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
  import ActionIcon from '../../components/ActionIcon.svelte';
  import { describeFailure } from '../../lib/failures';
  import { session } from '../auth/session.svelte';
  import { activeSession } from '../workout/activeSession.svelte';
  import ExercisePicker from '../workout/ExercisePicker.svelte';
  import {
    MAX_EXERCISES,
    MAX_SETS,
    MAX_SETS_PER_EXERCISE,
  } from '../workout/model';
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
  // `add` opens the picker for a new exercise; an index replaces that exercise.
  let pickerTarget = $state<number | 'add' | null>(null);

  const pickerOpen = $derived(phase === 'editing' && pickerTarget !== null);
  const totalSets = $derived(
    form.exercises.reduce((count, item) => count + item.sets.length, 0),
  );

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
    pickerTarget = null;
    phase = 'editing';
  }

  function beginEdit(plan: TrainingPlan): void {
    selected = plan;
    form = inputFromPlan(plan);
    initialForm = $state.snapshot(form);
    pickerTarget = null;
    phase = 'editing';
  }

  function openPicker(target: number | 'add'): void {
    pickerTarget = target;
  }

  function closePicker(): void {
    pickerTarget = null;
  }

  function exerciseName(exercise: TrainingPlanExerciseInput): string {
    return (
      catalog.find((item) => item.id === exercise.catalog_id)?.name ??
      'Exercise'
    );
  }

  function chooseExercise(entry: Exercise): void {
    const target = pickerTarget;
    if (target === null) return;
    // Keep the picked entry available for names and load settings even when
    // the initially loaded catalog page does not include it.
    if (!catalog.some((item) => item.id === entry.id)) catalog.push(entry);
    if (target === 'add') {
      if (form.exercises.length >= MAX_EXERCISES) return;
      form.exercises.push({
        catalog_id: entry.id,
        notes: null,
        sets: [emptySet(entry)],
      });
    } else {
      const exercise = form.exercises[target];
      if (exercise) {
        exercise.catalog_id = entry.id;
        exercise.sets = exercise.sets.map(() => emptySet(entry));
      }
    }
    pickerTarget = null;
  }

  function removeExercise(index: number): void {
    const exercise = form.exercises[index];
    if (!exercise) return;
    if (!window.confirm(`Remove ${exerciseName(exercise)} from this plan?`))
      return;
    form.exercises.splice(index, 1);
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
      await push(`/workouts/${draft.workout_id}`);
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
<h1 tabindex="-1">
  {pickerOpen
    ? pickerTarget === 'add'
      ? 'Choose an exercise'
      : 'Choose a replacement'
    : 'Training plans'}
</h1>
{#if !pickerOpen}
  <p class="mt-2 text-muted">
    Saving or previewing a plan does not start a session
  </p>
{/if}
{#if message}<p role="alert" class="mt-3 text-danger">{message}</p>{/if}
{#if phase === 'loading'}
  <p role="status" class="mt-4">Loading plans…</p>
{:else if phase === 'editing'}
  {#if pickerTarget !== null}
    <ExercisePicker
      target="plan"
      replacement={pickerTarget !== 'add'}
      onSelect={chooseExercise}
      onBack={closePicker}
    />
  {:else}
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
        {@const name = exerciseName(exercise)}
        <section
          class="rounded-lg border border-edge bg-surface p-4"
          aria-label={`Exercise ${exerciseIndex + 1}: ${name}`}
        >
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <h2 class="font-semibold">{name}</h2>
              <p class="text-sm text-muted">Exercise {exerciseIndex + 1}</p>
            </div>
            <div class="flex shrink-0 gap-2">
              <button
                type="button"
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge"
                aria-label={`Replace ${name}`}
                title={`Replace ${name}`}
                onclick={() => openPicker(exerciseIndex)}
                ><ActionIcon name="edit" /></button
              >
              <button
                type="button"
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-danger text-danger"
                aria-label={`Remove ${name}`}
                title={`Remove ${name}`}
                onclick={() => removeExercise(exerciseIndex)}
                ><ActionIcon name="remove" /></button
              >
            </div>
          </div>
          {#if exercise.sets.length > 0}
            <div class="mt-4 divide-y divide-edge border-y border-edge">
              {#each exercise.sets as set, setIndex (setIndex)}
                <fieldset class="py-2">
                  <legend class="sr-only">Set {setIndex + 1}</legend>
                  <div
                    class="grid gap-2 {entry?.load_type === 'bodyweight'
                      ? 'grid-cols-[2rem_minmax(0,1fr)]'
                      : 'grid-cols-[2rem_minmax(0,1fr)_minmax(0,1fr)]'}"
                  >
                    <span
                      class="flex min-h-10 items-center justify-center text-sm font-medium"
                      >{setIndex + 1}</span
                    >
                    <label
                      class="sr-only"
                      for={`plan-set-${exerciseIndex}-${setIndex}-reps`}
                      >Set {setIndex + 1} target reps</label
                    >
                    <input
                      id={`plan-set-${exerciseIndex}-${setIndex}-reps`}
                      placeholder="Reps"
                      inputmode="numeric"
                      step="1"
                      class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                      value={set.target_reps ?? ''}
                      oninput={(event) =>
                        (set.target_reps = parseTarget(
                          event.currentTarget.value,
                        ))}
                    />
                    {#if entry?.load_type !== 'bodyweight'}
                      <label
                        class="sr-only"
                        for={`plan-set-${exerciseIndex}-${setIndex}-weight`}
                        >Set {setIndex + 1} target weight in kilograms</label
                      >
                      <input
                        id={`plan-set-${exerciseIndex}-${setIndex}-weight`}
                        placeholder="kg"
                        inputmode="numeric"
                        step="1"
                        class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                        value={set.target_weight_kg ?? ''}
                        oninput={(event) =>
                          (set.target_weight_kg = parseTarget(
                            event.currentTarget.value,
                          ))}
                      />
                    {/if}
                  </div>
                  <div class="ml-10 mt-2 grid grid-cols-2 gap-2">
                    {#if entry?.load_type !== 'bodyweight' && entry?.bodyweight_percent !== null && entry?.bodyweight_percent !== undefined}
                      <label
                        class="text-sm font-medium"
                        for={`plan-set-${exerciseIndex}-${setIndex}-bodyweight-override`}
                        >Bodyweight % override<input
                          id={`plan-set-${exerciseIndex}-${setIndex}-bodyweight-override`}
                          type="number"
                          min="1"
                          max="100"
                          inputmode="numeric"
                          class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                          value={set.bw_percent_override ?? ''}
                          oninput={(event) =>
                            (set.bw_percent_override = parseTarget(
                              event.currentTarget.value,
                            ))}
                        /></label
                      >
                    {/if}
                    {#if entry?.load_type === 'split_weight' && entry.side_count === 1}
                      <label
                        class="text-sm font-medium"
                        for={`plan-set-${exerciseIndex}-${setIndex}-side`}
                        >Side<select
                          id={`plan-set-${exerciseIndex}-${setIndex}-side`}
                          class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                          value={set.side}
                          onchange={(event) =>
                            setTargetSide(set, event.currentTarget.value)}
                          ><option value="left">Left</option><option
                            value="right">Right</option
                          ></select
                        ></label
                      >
                    {/if}
                  </div>
                </fieldset>
              {/each}
            </div>
          {/if}
          <div class="mt-3 flex gap-2">
            <button
              type="button"
              class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
              aria-label={`Add set to ${name}`}
              title={`Add set to ${name}`}
              disabled={!entry ||
                exercise.sets.length >= MAX_SETS_PER_EXERCISE ||
                totalSets >= MAX_SETS}
              onclick={() => entry && exercise.sets.push(emptySet(entry))}
              ><ActionIcon name="add" /></button
            >
            {#if exercise.sets.length > 0}
              <button
                type="button"
                class="min-h-11 rounded-md border border-danger px-3 text-danger"
                aria-label={`Remove set ${exercise.sets.length}`}
                title={`Remove set ${exercise.sets.length}`}
                onclick={() => exercise.sets.pop()}
                ><ActionIcon name="remove" /></button
              >
            {/if}
          </div>
        </section>
      {/each}
      <button
        type="button"
        class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
        disabled={form.exercises.length >= MAX_EXERCISES}
        onclick={() => openPicker('add')}
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
  {/if}
{:else}
  <button
    class="mt-4 min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content"
    onclick={beginCreate}
  >
    Create plan
  </button>
  {#if plans.length === 0}<p class="mt-4">No training plans yet</p>{/if}
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
