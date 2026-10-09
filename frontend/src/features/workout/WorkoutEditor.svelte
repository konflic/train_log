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
  import ExercisePicker from './ExercisePicker.svelte';
  import {
    MAX_EXERCISES,
    MAX_SETS,
    MAX_SETS_PER_EXERCISE,
    catalogIssue,
    catalogIssueKey,
    emptySet,
    exerciseProgress,
    fieldKey,
    provisionalTotal,
    rawValue,
    setError,
    snapshotFor,
    updateInteger,
  } from './model';

  let {
    editor,
    sync,
    catalog = [],
    onOpenPicker,
    onClosePicker,
    pickerTarget = undefined,
  }: {
    editor: LocalDraftEditor;
    sync?: WorkoutSyncController;
    catalog?: Exercise[];
    onOpenPicker: (exerciseId?: string) => void;
    onClosePicker: () => void;
    pickerTarget?: string | null;
  } = $props();
  let completionErrors = $state<Record<string, string>>({});
  let expandedExerciseId = $state<string | null>(null);
  let selectedNames = $state<Record<string, string>>({});

  const content = $derived(editor.current!.content);
  const total = $derived(provisionalTotal(content));
  const locked = $derived(sync?.locked ?? false);
  const inProgressExercises = $derived(
    content.exercises.filter(
      (exercise) => !exerciseProgress(exercise).complete,
    ),
  );
  const completedExercises = $derived(
    content.exercises.filter((exercise) => exerciseProgress(exercise).complete),
  );

  function edit(next: EditableWorkoutContent): void {
    if (sync) void sync.commit(next);
    else void editor.edit(next);
  }

  function updateSet(
    exerciseId: string,
    setId: string,
    patch: Partial<SaveSetInput>,
  ): void {
    clearCompletionError(setId);
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    const set = exercise?.sets.find((item) => item.id === setId);
    if (!set) return;
    Object.assign(set, patch);
    edit(next);
  }

  function clearCompletionError(setId: string): void {
    if (!(setId in completionErrors)) return;
    const next = { ...completionErrors };
    delete next[setId];
    completionErrors = next;
  }

  function updateIntegerField(
    setId: string,
    field: 'reps' | 'weight_kg' | 'bw_percent_override' | 'rpe',
    raw: string,
  ): void {
    clearCompletionError(setId);
    edit(updateInteger(content, setId, field, raw));
  }

  function completeSet(exerciseId: string, setId: string): void {
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    const set = exercise?.sets.find((item) => item.id === setId);
    if (!exercise || !set) return;
    set.done = true;
    const error = setError(next, exercise, set);
    if (error) {
      completionErrors = { ...completionErrors, [setId]: error };
      return;
    }
    clearCompletionError(setId);
    edit(next);
  }

  function addExercise(entry: Exercise): void {
    if (locked || content.exercises.length >= MAX_EXERCISES) return;
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
    selectedNames = { ...selectedNames, [entry.id]: entry.name };
    expandedExerciseId = id;
    edit(next);
    onClosePicker();
  }

  function replaceExercise(exerciseId: string, entry: Exercise): void {
    if (locked) return;
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
    selectedNames = { ...selectedNames, [entry.id]: entry.name };
    expandedExerciseId = id;
    edit(next);
    onClosePicker();
  }

  function removeExercise(exerciseId: string): void {
    const next = structuredClone(content);
    next.exercises = next.exercises.filter((item) => item.id !== exerciseId);
    delete next.recorded_load_snapshots[exerciseId];
    delete next.provisional_load_snapshots[exerciseId];
    delete next.raw_fields[catalogIssueKey(exerciseId)];
    edit(next);
  }

  function confirmRemoveExercise(exercise: SaveExerciseInput): void {
    if (!window.confirm(`Remove ${exerciseName(exercise)} from this workout?`))
      return;
    removeExercise(exercise.id);
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
    if (
      !exercise ||
      exercise.sets.some((item) => item.id === setId && item.done)
    )
      return;
    exercise.sets = exercise.sets.filter((item) => item.id !== setId);
    for (const field of ['reps', 'weight_kg', 'bw_percent_override', 'rpe'])
      delete next.raw_fields[fieldKey(setId, field)];
    edit(next);
  }

  function moveSet(exerciseId: string, index: number, direction: -1 | 1): void {
    const next = structuredClone(content);
    const sets = next.exercises.find((item) => item.id === exerciseId)?.sets;
    const target = index + direction;
    if (
      !sets ||
      target < 0 ||
      target >= sets.length ||
      sets[index].done ||
      sets[target].done
    )
      return;
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
      selectedNames[exercise.catalog_id] ??
      'Exercise'
    );
  }

  function choosePicker(exerciseId: string | null = null): void {
    if (locked) return;
    onOpenPicker(exerciseId ?? undefined);
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

{#if pickerTarget !== undefined}
  <ExercisePicker
    replacement={pickerTarget !== null}
    disabled={locked}
    onSelect={(entry) =>
      pickerTarget === null
        ? addExercise(entry)
        : replaceExercise(pickerTarget, entry)}
    onBack={onClosePicker}
  />
{/if}
<section
  aria-label="Workout editor"
  class:hidden={pickerTarget !== undefined}
  class="flex flex-col gap-4"
>
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
        oninput={(event) =>
          edit({
            ...structuredClone(content),
            name: event.currentTarget.value || null,
          })}
      />
    </div>
    <p class="text-sm text-muted">
      Bodyweight snapshot:
      {content.bodyweight_kg === null
        ? 'not set'
        : `${content.bodyweight_kg} kg`}. Change bodyweight in Settings for
      future sessions.
    </p>
    <section aria-labelledby="provisional-total">
      <h2 id="provisional-total" class="font-semibold">
        Provisional completed-set total
      </h2>
      <p class="mt-1">
        {total.knownVolume === null
          ? 'Unknown'
          : `${total.knownVolume} kg·reps`} from
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
  </div>

  {#each [...inProgressExercises, ...completedExercises] as exercise, groupedIndex (exercise.id)}
    {@const exerciseIndex = content.exercises.indexOf(exercise)}
    {@const progress = exerciseProgress(exercise)}
    {#if groupedIndex === 0 || groupedIndex === inProgressExercises.length}
      <h2
        id={progress.complete ? 'completed-exercises' : 'in-progress-exercises'}
        class="font-semibold"
      >
        {progress.complete ? 'Completed' : 'In progress'}
        <span class="text-sm font-normal text-muted">
          ({progress.complete
            ? completedExercises.length
            : inProgressExercises.length})
        </span>
      </h2>
    {/if}
    {@const snapshot = snapshotOf(exercise.id)}
    <section
      class="rounded-lg border border-edge bg-surface p-4"
      aria-label={`${exerciseName(exercise)} editor`}
    >
      <div class="flex items-start justify-between gap-2">
        <button
          type="button"
          class="min-h-11 min-w-0 flex-1 text-left"
          aria-expanded={expandedExerciseId === exercise.id}
          onclick={() => {
            expandedExerciseId =
              expandedExerciseId === exercise.id ? null : exercise.id;
          }}
        >
          <h3 class="font-semibold">{exerciseName(exercise)}</h3>
          <p class="text-sm text-muted">
            {progress.completedSets} of {progress.totalSets} sets completed ·
            {snapshot?.load_type === 'bodyweight'
              ? 'Bodyweight'
              : 'Whole kilograms'}
          </p>
        </button>
        {#if expandedExerciseId === exercise.id}<div
            class="flex shrink-0 gap-2"
          >
            <button
              type="button"
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge disabled:opacity-40"
              disabled={locked || exerciseIndex === 0}
              aria-label={`Move ${exerciseName(exercise)} up`}
              title={`Move ${exerciseName(exercise)} up`}
              onclick={() => moveExercise(exerciseIndex, -1)}
              ><ActionIcon name="up" /></button
            >
            <button
              type="button"
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge disabled:opacity-40"
              disabled={locked ||
                exerciseIndex === content.exercises.length - 1}
              aria-label={`Move ${exerciseName(exercise)} down`}
              title={`Move ${exerciseName(exercise)} down`}
              onclick={() => moveExercise(exerciseIndex, 1)}
              ><ActionIcon name="down" /></button
            >
            <button
              type="button"
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-danger text-danger disabled:opacity-40"
              aria-label={`Remove ${exerciseName(exercise)}`}
              title={`Remove ${exerciseName(exercise)}`}
              disabled={locked}
              onclick={() => confirmRemoveExercise(exercise)}
              ><ActionIcon name="remove" /></button
            >
          </div>{/if}
      </div>
      {#if expandedExerciseId === exercise.id}
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
        <div class="mt-4 flex flex-col gap-3">
          {#each exercise.sets as set, setIndex (set.id)}
            {@const error = setError(content, exercise, set)}
            {@const validationError = error ?? completionErrors[set.id]}
            <fieldset
              class="rounded-md border border-edge p-3"
              aria-describedby={validationError
                ? `set-error-${set.id}`
                : undefined}
            >
              <legend class="px-1 font-medium">Set {setIndex + 1}</legend>
              <div class="grid grid-cols-2 gap-3">
                <label class="text-sm font-medium"
                  >Reps<input
                    inputmode="numeric"
                    step="1"
                    disabled={locked || set.done}
                    class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                    value={rawValue(content, set, 'reps')}
                    oninput={(event) =>
                      updateIntegerField(
                        set.id,
                        'reps',
                        event.currentTarget.value,
                      )}
                  /></label
                >
                {#if snapshot?.load_type !== 'bodyweight'}<label
                    class="text-sm font-medium"
                    >Weight (kg)<input
                      inputmode="numeric"
                      step="1"
                      disabled={locked || set.done}
                      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                      value={rawValue(content, set, 'weight_kg')}
                      oninput={(event) =>
                        updateIntegerField(
                          set.id,
                          'weight_kg',
                          event.currentTarget.value,
                        )}
                    /></label
                  >{/if}
                {#if snapshot?.load_type !== 'bodyweight' && snapshot?.bodyweight_percent !== null}<label
                    class="text-sm font-medium"
                    >Bodyweight % override<input
                      inputmode="numeric"
                      step="1"
                      disabled={locked || set.done}
                      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                      value={rawValue(content, set, 'bw_percent_override')}
                      oninput={(event) =>
                        updateIntegerField(
                          set.id,
                          'bw_percent_override',
                          event.currentTarget.value,
                        )}
                    /></label
                  >{/if}
                {#if snapshot?.load_type === 'split_weight' && snapshot.side_count === 1}<label
                    class="text-sm font-medium"
                    >Side<select
                      class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3"
                      value={set.side}
                      disabled={locked || set.done}
                      onchange={(event) =>
                        updateSet(exercise.id, set.id, {
                          side: event.currentTarget
                            .value as SaveSetInput['side'],
                        })}
                      ><option value="left">Left</option><option value="right"
                        >Right</option
                      ></select
                    ></label
                  >{/if}
              </div>
              {#if validationError}<p
                  id={`set-error-${set.id}`}
                  role="alert"
                  class="mt-2 text-sm text-danger"
                >
                  {validationError}
                </p>{/if}
              <div class="mt-3 flex flex-wrap gap-2">
                {#if set.done}<button
                    type="button"
                    class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge"
                    aria-label={`Edit set ${setIndex + 1}`}
                    title={`Edit set ${setIndex + 1}`}
                    disabled={locked}
                    onclick={() =>
                      updateSet(exercise.id, set.id, { done: false })}
                    ><ActionIcon name="edit" /></button
                  >{:else}<button
                    type="button"
                    aria-label={`Mark set ${setIndex + 1} completed`}
                    title={`Mark set ${setIndex + 1} completed`}
                    class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge"
                    disabled={locked}
                    onclick={() => completeSet(exercise.id, set.id)}
                    ><ActionIcon name="finish" /></button
                  >{/if}
                <button
                  type="button"
                  class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                  disabled={locked ||
                    set.done ||
                    setIndex === 0 ||
                    exercise.sets[setIndex - 1].done}
                  aria-label={`Move set ${setIndex + 1} up`}
                  title={`Move set ${setIndex + 1} up`}
                  onclick={() => moveSet(exercise.id, setIndex, -1)}
                  ><ActionIcon name="up" /></button
                ><button
                  type="button"
                  class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
                  disabled={locked ||
                    set.done ||
                    setIndex === exercise.sets.length - 1 ||
                    exercise.sets[setIndex + 1].done}
                  aria-label={`Move set ${setIndex + 1} down`}
                  title={`Move set ${setIndex + 1} down`}
                  onclick={() => moveSet(exercise.id, setIndex, 1)}
                  ><ActionIcon name="down" /></button
                ><button
                  type="button"
                  class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-danger text-danger disabled:opacity-40"
                  aria-label={`Remove set ${setIndex + 1}`}
                  title={`Remove set ${setIndex + 1}`}
                  disabled={locked || set.done}
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
      {/if}
    </section>
  {/each}
  <button
    type="button"
    class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
    disabled={locked || content.exercises.length >= MAX_EXERCISES}
    onclick={() => choosePicker()}
    ><ActionIcon name="add" /> Add exercise</button
  >
</section>
