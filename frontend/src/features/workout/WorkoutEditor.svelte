<script lang="ts">
  import type { Exercise, SaveExerciseInput, SaveSetInput } from '../../api';
  import ActionIcon from '../../components/ActionIcon.svelte';
  import {
    createDraftId,
    type EditableWorkoutContent,
    type LoadSnapshot,
  } from '../../db';
  import type { LocalDraftEditor } from '../drafts/editor.svelte';
  import type { WorkoutSyncController } from './sync.svelte';
  import {
    MAX_EXERCISES,
    MAX_SETS,
    MAX_SETS_PER_EXERCISE,
    catalogIssue,
    catalogIssueKey,
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
    sync,
    catalog = [],
    catalogMessage = null,
    onOpenPicker,
  }: {
    editor: LocalDraftEditor;
    sync?: WorkoutSyncController;
    catalog?: Exercise[];
    catalogMessage?: string | null;
    onOpenPicker: () => void;
  } = $props();
  let pickerOpen = $state(false);
  let pickerTarget = $state<string | null>(null);

  const content = $derived(editor.current!.content);
  const total = $derived(provisionalTotal(content));
  const locked = $derived(sync?.locked ?? false);

  function edit(next: EditableWorkoutContent): void {
    if (sync) void sync.commit(next);
    else void editor.edit(next);
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
    const id = createDraftId();
    const snapshot = snapshotFor(entry);
    next.exercises.push({
      id,
      catalog_id: entry.id,
      notes: null,
      sets: [emptySet(snapshot)],
    });
    next.provisional_load_snapshots[id] = snapshot;
    pickerOpen = false;
    pickerTarget = null;
    edit(next);
  }

  function replaceExercise(exerciseId: string, entry: Exercise): void {
    const next = structuredClone(content);
    const index = next.exercises.findIndex((item) => item.id === exerciseId);
    if (index < 0) return;
    const previous = next.exercises[index];
    const id = createDraftId();
    const sets = previous.sets.map((set) => {
      const setId = createDraftId();
      for (const field of ['reps', 'weight_kg', 'bw_percent_override', 'rpe']) {
        const previousKey = fieldKey(set.id, field);
        const raw = next.raw_fields[previousKey];
        if (raw !== undefined) next.raw_fields[fieldKey(setId, field)] = raw;
        delete next.raw_fields[previousKey];
      }
      return { ...set, id: setId };
    });
    next.exercises[index] = {
      ...previous,
      id,
      catalog_id: entry.id,
      sets,
    };
    delete next.recorded_load_snapshots[exerciseId];
    delete next.provisional_load_snapshots[exerciseId];
    delete next.raw_fields[catalogIssueKey(exerciseId)];
    next.provisional_load_snapshots[id] = snapshotFor(entry);
    pickerOpen = false;
    pickerTarget = null;
    edit(next);
  }

  function removeExercise(exerciseId: string): void {
    const next = structuredClone(content);
    next.exercises = next.exercises.filter((item) => item.id !== exerciseId);
    delete next.recorded_load_snapshots[exerciseId];
    delete next.provisional_load_snapshots[exerciseId];
    delete next.raw_fields[catalogIssueKey(exerciseId)];
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

  function choosePicker(exerciseId: string | null = null): void {
    if (locked) return;
    pickerTarget = exerciseId;
    pickerOpen = true;
    onOpenPicker();
  }

  function statusText(): string {
    if (!sync) {
      if (editor.status === 'saving') return 'Saving locally…';
      if (editor.status === 'failed')
        return 'Storage error. The latest visible edit is not safely stored.';
      return `Locally saved change ${editor.savedChange}. Offline recovery mode.`;
    }
    if (sync.status === 'saving_local') return 'Saving locally…';
    if (sync.status === 'locally_saved')
      return `Locally saved change ${editor.savedChange}. Waiting to sync.`;
    if (sync.status === 'syncing') return 'Syncing durable changes…';
    if (sync.status === 'synced')
      return `Synced at revision ${editor.current!.base_revision}.`;
    if (sync.status === 'offline') return 'Offline. Changes remain local.';
    if (sync.status === 'authentication_required')
      return sync.finishPending
        ? 'Authentication required. Finish remains pending.'
        : 'Authentication required. Upload is paused.';
    if (sync.status === 'conflict')
      return 'Conflict. Automatic saving is paused with this draft retained.';
    if (sync.status === 'finish_pending')
      return 'Finish pending. The final graph is stored and will retry exactly.';
    if (sync.status === 'storage_error')
      return 'Storage error. The latest visible edit is not safely stored.';
    if (sync.status === 'correction_required')
      return 'Correction required before this workout can sync.';
    return 'Synchronization paused.';
  }

  function retryLabel(): string {
    return !sync || editor.status === 'failed'
      ? 'Retry local save'
      : 'Retry synchronization';
  }
</script>

<section aria-label="Workout editor" class="flex flex-col gap-4">
  <div
    class="sticky top-0 z-10 rounded-lg border border-edge bg-surface p-3 shadow-sm"
  >
    <p
      role="status"
      class:text-sync-error={sync?.status === 'storage_error' ||
        sync?.status === 'conflict' ||
        sync?.status === 'correction_required' ||
        sync?.status === 'error'}
      class:text-sync-ok={sync?.status === 'synced'}
      class:text-sync-pending={sync?.status === 'syncing' ||
        sync?.status === 'finish_pending'}
    >
      {statusText()}
    </p>
    {#if sync?.message}<p class="mt-1 text-sm text-muted">
        {sync.message}
      </p>{/if}
    <div class="mt-2 flex flex-wrap gap-2">
      {#if sync?.status === 'storage_error' || sync?.status === 'offline' || sync?.status === 'finish_pending' || sync?.status === 'error' || (!sync && editor.status === 'failed')}
        <button
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3"
          type="button"
          aria-label={retryLabel()}
          title={retryLabel()}
          onclick={() => void (sync ? sync.retry() : editor.retry())}
          ><ActionIcon name="refresh" /></button
        >
      {/if}
      <button
        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3 disabled:opacity-40"
        type="button"
        aria-label="Save now"
        title="Save now"
        disabled={!sync ||
          locked ||
          sync.status === 'syncing' ||
          sync.status === 'authentication_required' ||
          sync.status === 'correction_required'}
        onclick={() => void sync?.saveNow()}><ActionIcon name="save" /></button
      >
      <button
        class="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
        type="button"
        disabled={!sync?.canFinish}
        onclick={() => void sync?.finish()}
        ><ActionIcon name="finish" /> Finish workout</button
      >
    </div>
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
        disabled={locked}
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
        disabled={locked}
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
        disabled={locked}
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
    aria-label="Add exercise"
    title="Add exercise"
    disabled={locked || content.exercises.length >= MAX_EXERCISES}
    onclick={() => choosePicker()}><ActionIcon name="add" /></button
  >
  {#if pickerOpen}
    <section
      class="rounded-lg border border-edge bg-surface p-4"
      aria-label="Exercise picker"
    >
      <h2 class="font-semibold">
        {pickerTarget === null ? 'Choose an exercise' : 'Choose a replacement'}
      </h2>
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
                disabled={locked}
                onclick={() =>
                  pickerTarget === null
                    ? addExercise(entry)
                    : replaceExercise(pickerTarget, entry)}>{entry.name}</button
              >
            </li>
          {/each}
        </ul>
      {/if}
      <button
        type="button"
        class="mt-3 min-h-11 rounded-md border border-edge px-3"
        aria-label="Close exercise picker"
        title="Close exercise picker"
        onclick={() => {
          pickerOpen = false;
          pickerTarget = null;
        }}><ActionIcon name="close" /></button
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
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3"
          aria-label={`Remove ${exerciseName(exercise)}`}
          title={`Remove ${exerciseName(exercise)}`}
          disabled={locked}
          onclick={() => removeExercise(exercise.id)}
          ><ActionIcon name="remove" /></button
        >
      </div>
      <div class="mt-2 flex gap-2">
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
          disabled={locked || exerciseIndex === 0}
          aria-label={`Move ${exerciseName(exercise)} up`}
          title={`Move ${exerciseName(exercise)} up`}
          onclick={() => moveExercise(exerciseIndex, -1)}
          ><ActionIcon name="up" /></button
        >
        <button
          type="button"
          class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
          disabled={locked || exerciseIndex === content.exercises.length - 1}
          aria-label={`Move ${exerciseName(exercise)} down`}
          title={`Move ${exerciseName(exercise)} down`}
          onclick={() => moveExercise(exerciseIndex, 1)}
          ><ActionIcon name="down" /></button
        >
      </div>
      {#if catalogIssue(content, exercise.id)}
        <p role="alert" class="mt-2 text-sm text-danger">
          {catalogIssue(content, exercise.id)}
        </p>
        <button
          type="button"
          class="mt-2 min-h-11 rounded-md border border-edge px-3"
          disabled={locked}
          onclick={() => choosePicker(exercise.id)}>Replace exercise</button
        >
      {/if}
      <label
        class="mt-3 block text-sm font-medium"
        for={`exercise-notes-${exercise.id}`}>Exercise notes</label
      >
      <textarea
        id={`exercise-notes-${exercise.id}`}
        class="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2"
        maxlength="300"
        disabled={locked}
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
                  disabled={locked}
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
                    disabled={locked}
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
                    disabled={locked}
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
              {#if snapshot?.load_type === 'split_weight' && snapshot.side_count === 1}<label
                  class="text-sm font-medium"
                  >Side<select
                    class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                    value={set.side}
                    disabled={locked}
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
                aria-pressed={set.done}
                aria-label={set.done
                  ? `Mark set ${setIndex + 1} incomplete`
                  : `Mark set ${setIndex + 1} completed`}
                class="min-h-11 rounded-md border px-3 font-medium {set.done
                  ? 'border-primary bg-primary text-primary-content'
                  : 'border-edge'}"
                disabled={locked}
                onclick={() =>
                  updateSet(exercise.id, set.id, { done: !set.done })}
                >{set.done ? 'Completed' : 'Mark completed'}</button
              >
              <button
                type="button"
                class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                disabled={locked || setIndex === 0}
                aria-label={`Move set ${setIndex + 1} up`}
                title={`Move set ${setIndex + 1} up`}
                onclick={() => moveSet(exercise.id, setIndex, -1)}
                ><ActionIcon name="up" /></button
              ><button
                type="button"
                class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                disabled={locked || setIndex === exercise.sets.length - 1}
                aria-label={`Move set ${setIndex + 1} down`}
                title={`Move set ${setIndex + 1} down`}
                onclick={() => moveSet(exercise.id, setIndex, 1)}
                ><ActionIcon name="down" /></button
              ><button
                type="button"
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3"
                aria-label={`Remove set ${setIndex + 1}`}
                title={`Remove set ${setIndex + 1}`}
                disabled={locked}
                onclick={() => removeSet(exercise.id, set.id)}
                ><ActionIcon name="remove" /></button
              >
            </div>
          </fieldset>
        {/each}
      </div>
      <button
        type="button"
        class="mt-3 min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
        aria-label={`Add set to ${exerciseName(exercise)}`}
        title={`Add set to ${exerciseName(exercise)}`}
        disabled={locked || exercise.sets.length >= MAX_SETS_PER_EXERCISE}
        onclick={() => addSet(exercise)}><ActionIcon name="add" /></button
      >
    </section>
  {/each}
</section>
