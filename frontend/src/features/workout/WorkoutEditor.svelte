<script lang="ts">
  import type { Exercise, SaveExerciseInput, SaveSetInput } from '../../api';
  import type { EditableWorkoutContent, LoadSnapshot } from '../../db';
  import type { LocalDraftEditor } from '../drafts/editor.svelte';
  import {
    MAX_EXERCISES,
    MAX_SETS,
    MAX_SETS_PER_EXERCISE,
    emptySet,
    fieldKey,
    provisionalTotal,
    rawValue,
    setError,
    snapshotFor,
    strictInteger,
    updateInteger,
  } from './model';

  let {
    editor,
    catalog = [],
    catalogMessage = null,
    onOpenPicker,
  }: {
    editor: LocalDraftEditor;
    catalog?: Exercise[];
    catalogMessage?: string | null;
    onOpenPicker: () => void;
  } = $props();
  let pickerOpen = $state(false);

  const content = $derived(editor.current!.content);
  const total = $derived(provisionalTotal(content));

  function edit(next: EditableWorkoutContent): void {
    void editor.edit(next);
  }

  function updateText(field: 'name' | 'notes', value: string): void {
    edit({ ...structuredClone(content), [field]: value === '' ? null : value });
  }

  function updateBodyweight(raw: string): void {
    const next = structuredClone(content);
    next.raw_fields['workout.bodyweight_kg'] = raw;
    next.bodyweight_kg = raw === '' ? null : strictInteger(raw);
    edit(next);
  }

  function updateSet(
    exerciseId: string,
    setId: string,
    patch: Partial<SaveSetInput>,
  ): void {
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    const set = exercise?.sets.find((item) => item.id === setId);
    if (!set) return;
    Object.assign(set, patch);
    edit(next);
  }

  function updateExercise(exerciseId: string, notes: string): void {
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    if (!exercise) return;
    exercise.notes = notes === '' ? null : notes;
    edit(next);
  }

  function addExercise(entry: Exercise): void {
    if (content.exercises.length >= MAX_EXERCISES) return;
    const next = structuredClone(content);
    const id = crypto.randomUUID();
    const snapshot = snapshotFor(entry);
    next.exercises.push({
      id,
      catalog_id: entry.id,
      notes: null,
      sets: [emptySet(snapshot)],
    });
    next.provisional_load_snapshots[id] = snapshot;
    pickerOpen = false;
    edit(next);
  }

  function removeExercise(exerciseId: string): void {
    const next = structuredClone(content);
    next.exercises = next.exercises.filter((item) => item.id !== exerciseId);
    delete next.recorded_load_snapshots[exerciseId];
    delete next.provisional_load_snapshots[exerciseId];
    edit(next);
  }

  function moveExercise(index: number, direction: -1 | 1): void {
    const next = structuredClone(content);
    const target = index + direction;
    if (target < 0 || target >= next.exercises.length) return;
    [next.exercises[index], next.exercises[target]] = [
      next.exercises[target],
      next.exercises[index],
    ];
    edit(next);
  }

  function addSet(exercise: SaveExerciseInput): void {
    const snapshot = snapshotOf(exercise.id);
    if (!snapshot || exercise.sets.length >= MAX_SETS_PER_EXERCISE) return;
    if (
      content.exercises.reduce((count, item) => count + item.sets.length, 0) >=
      MAX_SETS
    )
      return;
    const next = structuredClone(content);
    next.exercises
      .find((item) => item.id === exercise.id)
      ?.sets.push(emptySet(snapshot));
    edit(next);
  }

  function removeSet(exerciseId: string, setId: string): void {
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    if (!exercise) return;
    exercise.sets = exercise.sets.filter((item) => item.id !== setId);
    for (const field of ['reps', 'weight_kg', 'bw_percent_override', 'rpe'])
      delete next.raw_fields[fieldKey(setId, field)];
    edit(next);
  }

  function moveSet(exerciseId: string, index: number, direction: -1 | 1): void {
    const next = structuredClone(content);
    const sets = next.exercises.find((item) => item.id === exerciseId)?.sets;
    const target = index + direction;
    if (!sets || target < 0 || target >= sets.length) return;
    [sets[index], sets[target]] = [sets[target], sets[index]];
    edit(next);
  }

  function snapshotOf(exerciseId: string): LoadSnapshot | null {
    return (
      content.recorded_load_snapshots[exerciseId] ??
      content.provisional_load_snapshots[exerciseId] ??
      null
    );
  }

  function exerciseName(exercise: SaveExerciseInput): string {
    return (
      catalog.find((entry) => entry.id === exercise.catalog_id)?.name ??
      'Exercise'
    );
  }

  function choosePicker(): void {
    pickerOpen = true;
    onOpenPicker();
  }
</script>

<section aria-label="Workout editor" class="flex flex-col gap-4">
  <div
    class="sticky top-0 z-10 rounded-lg border border-edge bg-surface p-3 shadow-sm"
  >
    <p role="status" class:text-sync-error={editor.status === 'failed'}>
      {#if editor.status === 'saving'}Saving locally…
      {:else if editor.status === 'failed'}Storage failed. Your visible edit is
        not locally saved.
      {:else}Locally saved change {editor.savedChange}. No server save has been
        sent.{/if}
    </p>
    {#if editor.status === 'failed'}
      <button
        class="mt-2 min-h-11 rounded-md border border-edge px-3"
        type="button"
        onclick={() => void editor.retry()}>Retry local save</button
      >
    {/if}
  </div>

  <div class="grid gap-3 rounded-lg border border-edge bg-surface p-4">
    <p class="text-sm text-muted">
      Started {editor.current!.started_at} · base revision {editor.current!
        .base_revision}
    </p>
    <div>
      <label class="block text-sm font-medium" for="workout-name"
        >Workout name</label
      >
      <input
        id="workout-name"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
        maxlength="100"
        value={content.name ?? ''}
        oninput={(event) => updateText('name', event.currentTarget.value)}
      />
    </div>
    <div>
      <label class="block text-sm font-medium" for="workout-bodyweight"
        >Recorded bodyweight (kg)</label
      >
      <input
        id="workout-bodyweight"
        inputmode="numeric"
        step="1"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
        value={content.raw_fields['workout.bodyweight_kg'] ??
          String(content.bodyweight_kg ?? '')}
        oninput={(event) => updateBodyweight(event.currentTarget.value)}
      />
    </div>
    <div>
      <label class="block text-sm font-medium" for="workout-notes">Notes</label>
      <textarea
        id="workout-notes"
        class="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2"
        maxlength="2000"
        value={content.notes ?? ''}
        oninput={(event) => updateText('notes', event.currentTarget.value)}
      ></textarea>
    </div>
  </div>

  <section
    class="rounded-lg border border-edge bg-surface p-4"
    aria-labelledby="provisional-total"
  >
    <h2 id="provisional-total" class="font-semibold">
      Provisional completed-set total
    </h2>
    <p class="mt-1">
      {total.knownVolume === null ? 'Unknown' : `${total.knownVolume} kg·reps`} from
      {total.completedSetCount} completed {total.completedSetCount === 1
        ? 'set'
        : 'sets'}.
    </p>
    {#if total.unknownSetCount > 0}<p class="text-sm text-muted">
        {total.unknownSetCount} completed {total.unknownSetCount === 1
          ? 'set has'
          : 'sets have'} an unknown load.
      </p>{/if}
  </section>

  <button
    type="button"
    class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
    disabled={content.exercises.length >= MAX_EXERCISES}
    onclick={choosePicker}>Add exercise</button
  >
  {#if pickerOpen}
    <section
      class="rounded-lg border border-edge bg-surface p-4"
      aria-label="Exercise picker"
    >
      <h2 class="font-semibold">Choose an exercise</h2>
      {#if catalogMessage}<p role="alert" class="mt-2 text-danger">
          {catalogMessage}
        </p>{/if}
      {#if catalog.length === 0}<p class="mt-2 text-muted">
          Load the catalog while online to add an exercise.
        </p>{:else}
        <ul class="mt-2 flex flex-col gap-2">
          {#each catalog as entry (entry.id)}
            <li>
              <button
                type="button"
                class="min-h-11 w-full rounded-md border border-edge px-3 text-left"
                onclick={() => addExercise(entry)}>{entry.name}</button
              >
            </li>
          {/each}
        </ul>
      {/if}
      <button
        type="button"
        class="mt-3 min-h-11 rounded-md border border-edge px-3"
        onclick={() => (pickerOpen = false)}>Close picker</button
      >
    </section>
  {/if}

  {#each content.exercises as exercise, exerciseIndex (exercise.id)}
    {@const snapshot = snapshotOf(exercise.id)}
    <section
      class="rounded-lg border border-edge bg-surface p-4"
      aria-label={`${exerciseName(exercise)} editor`}
    >
      <div class="flex items-start justify-between gap-2">
        <div>
          <h2 class="font-semibold">{exerciseName(exercise)}</h2>
          <p class="text-sm text-muted">
            {snapshot?.load_type === 'bodyweight'
              ? 'Bodyweight'
              : 'Whole kilograms'}
          </p>
        </div>
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3"
          onclick={() => removeExercise(exercise.id)}>Remove</button
        >
      </div>
      <div class="mt-2 flex gap-2">
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
          disabled={exerciseIndex === 0}
          aria-label={`Move ${exerciseName(exercise)} up`}
          onclick={() => moveExercise(exerciseIndex, -1)}>Up</button
        >
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
          disabled={exerciseIndex === content.exercises.length - 1}
          aria-label={`Move ${exerciseName(exercise)} down`}
          onclick={() => moveExercise(exerciseIndex, 1)}>Down</button
        >
      </div>
      <label
        class="mt-3 block text-sm font-medium"
        for={`exercise-notes-${exercise.id}`}>Exercise notes</label
      >
      <textarea
        id={`exercise-notes-${exercise.id}`}
        class="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2"
        maxlength="300"
        value={exercise.notes ?? ''}
        oninput={(event) =>
          updateExercise(exercise.id, event.currentTarget.value)}></textarea>
      <div class="mt-4 flex flex-col gap-3">
        {#each exercise.sets as set, setIndex (set.id)}
          {@const error = setError(content, exercise, set)}
          <fieldset
            class="rounded-md border border-edge p-3"
            aria-describedby={error ? `set-error-${set.id}` : undefined}
          >
            <legend class="px-1 font-medium">Set {setIndex + 1}</legend>
            <div class="grid grid-cols-2 gap-3">
              <label class="text-sm font-medium"
                >Reps<input
                  inputmode="numeric"
                  step="1"
                  class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                  value={rawValue(content, set, 'reps')}
                  oninput={(event) =>
                    edit(
                      updateInteger(
                        content,
                        set.id,
                        'reps',
                        event.currentTarget.value,
                      ),
                    )}
                /></label
              >
              {#if snapshot?.load_type !== 'bodyweight'}<label
                  class="text-sm font-medium"
                  >Weight (kg)<input
                    inputmode="numeric"
                    step="1"
                    class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                    value={rawValue(content, set, 'weight_kg')}
                    oninput={(event) =>
                      edit(
                        updateInteger(
                          content,
                          set.id,
                          'weight_kg',
                          event.currentTarget.value,
                        ),
                      )}
                  /></label
                >{/if}
              {#if snapshot?.bodyweight_percent !== null}<label
                  class="text-sm font-medium"
                  >Bodyweight % override<input
                    inputmode="numeric"
                    step="1"
                    class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                    value={rawValue(content, set, 'bw_percent_override')}
                    oninput={(event) =>
                      edit(
                        updateInteger(
                          content,
                          set.id,
                          'bw_percent_override',
                          event.currentTarget.value,
                        ),
                      )}
                  /></label
                >{/if}
              <label class="text-sm font-medium"
                >RPE<input
                  inputmode="numeric"
                  step="1"
                  class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                  value={rawValue(content, set, 'rpe')}
                  oninput={(event) =>
                    edit(
                      updateInteger(
                        content,
                        set.id,
                        'rpe',
                        event.currentTarget.value,
                      ),
                    )}
                /></label
              >
              {#if snapshot?.load_type === 'split_weight' && snapshot.side_count === 1}<label
                  class="text-sm font-medium"
                  >Side<select
                    class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                    value={set.side}
                    onchange={(event) =>
                      updateSet(exercise.id, set.id, {
                        side: event.currentTarget.value as SaveSetInput['side'],
                      })}
                    ><option value="left">Left</option><option value="right"
                      >Right</option
                    ></select
                  ></label
                >{/if}
            </div>
            <label
              class="mt-3 flex min-h-11 items-center gap-2 text-sm font-medium"
              ><input
                type="checkbox"
                checked={set.done}
                onchange={(event) =>
                  updateSet(exercise.id, set.id, {
                    done: event.currentTarget.checked,
                  })}
              /> Completed</label
            >
            {#if error}<p
                id={`set-error-${set.id}`}
                role="alert"
                class="mt-2 text-sm text-danger"
              >
                {error}
              </p>{/if}
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                disabled={setIndex === 0}
                aria-label={`Move set ${setIndex + 1} up`}
                onclick={() => moveSet(exercise.id, setIndex, -1)}>Up</button
              ><button
                type="button"
                class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                disabled={setIndex === exercise.sets.length - 1}
                aria-label={`Move set ${setIndex + 1} down`}
                onclick={() => moveSet(exercise.id, setIndex, 1)}>Down</button
              ><button
                type="button"
                class="min-h-11 rounded-md border border-edge px-3"
                onclick={() => removeSet(exercise.id, set.id)}
                >Remove set</button
              >
            </div>
          </fieldset>
        {/each}
      </div>
      <button
        type="button"
        class="mt-3 min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
        disabled={exercise.sets.length >= MAX_SETS_PER_EXERCISE}
        onclick={() => addSet(exercise)}>Add set</button
      >
    </section>
  {/each}
</section>
