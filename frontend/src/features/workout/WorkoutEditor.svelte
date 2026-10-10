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
  import { formatRelativeTime } from '../../lib/relativeTime';
  import ExercisePicker from './ExercisePicker.svelte';
  import {
    MAX_EXERCISES,
    MAX_SETS,
    MAX_SETS_PER_EXERCISE,
    catalogIssue,
    catalogIssueKey,
    completionProgress,
    emptySet,
    exerciseProgress,
    fieldKey,
    finishBlocker,
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
  let draggingExerciseId = $state<string | null>(null);
  let dropTargetExerciseId = $state<string | null>(null);
  let dropPosition = $state<'before' | 'after'>('before');

  const content = $derived(editor.current!.content);
  const completion = $derived(completionProgress(content));
  const locked = $derived(sync?.locked ?? false);
  const blocker = $derived(finishBlocker(content));

  function confirmCancel(): void {
    if (!sync || sync.discarding) return;
    if (
      !window.confirm(
        'Discard this workout? Every logged set is deleted and this cannot be undone',
      )
    )
      return;
    void sync.discard();
  }

  function confirmFinish(): void {
    if (!sync?.canFinish) return;
    if (
      !window.confirm('Finish this workout? It is saved and becomes read-only')
    )
      return;
    void sync.finish();
  }

  function saveLocally(next: EditableWorkoutContent): void {
    if (sync) void sync.saveLocally(next);
    else void editor.edit(next);
  }

  function syncChanges(next: EditableWorkoutContent): void {
    if (sync) void sync.commit(next);
    else void editor.edit(next);
  }

  function updateSet(
    exerciseId: string,
    setId: string,
    patch: Partial<SaveSetInput>,
    synchronize = false,
  ): void {
    clearCompletionError(setId);
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    const set = exercise?.sets.find((item) => item.id === setId);
    if (!set) return;
    Object.assign(set, patch);
    if (synchronize) syncChanges(next);
    else saveLocally(next);
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
    saveLocally(updateInteger(content, setId, field, raw));
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
    syncChanges(next);
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
    syncChanges(next);
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
    syncChanges(next);
    onClosePicker();
  }

  function removeExercise(exerciseId: string): void {
    const next = structuredClone(content);
    next.exercises = next.exercises.filter((item) => item.id !== exerciseId);
    delete next.recorded_load_snapshots[exerciseId];
    delete next.provisional_load_snapshots[exerciseId];
    delete next.raw_fields[catalogIssueKey(exerciseId)];
    syncChanges(next);
  }

  function confirmRemoveExercise(exercise: SaveExerciseInput): void {
    if (!window.confirm(`Remove ${exerciseName(exercise)} from this workout?`))
      return;
    removeExercise(exercise.id);
  }

  function startExerciseDrag(event: DragEvent, exerciseId: string): void {
    if (locked) return;
    draggingExerciseId = exerciseId;
    event.dataTransfer?.setData('text/plain', exerciseId);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      const card = event.currentTarget as HTMLElement;
      event.dataTransfer.setDragImage(card, card.clientWidth / 2, 24);
    }
  }

  function allowExerciseDrop(event: DragEvent, exerciseId: string): void {
    if (!draggingExerciseId || draggingExerciseId === exerciseId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    dropTargetExerciseId = exerciseId;
    const target = event.currentTarget as HTMLElement;
    dropPosition =
      event.clientY <
      target.getBoundingClientRect().top + target.clientHeight / 2
        ? 'before'
        : 'after';
  }

  function dropExercise(event: DragEvent, targetId: string): void {
    event.preventDefault();
    const sourceId =
      draggingExerciseId ?? event.dataTransfer?.getData('text/plain');
    draggingExerciseId = null;
    dropTargetExerciseId = null;
    if (!sourceId || sourceId === targetId) return;

    const next = structuredClone(content);
    const sourceIndex = next.exercises.findIndex(
      (exercise) => exercise.id === sourceId,
    );
    const targetIndex = next.exercises.findIndex(
      (exercise) => exercise.id === targetId,
    );
    if (sourceIndex < 0 || targetIndex < 0) return;
    const [exercise] = next.exercises.splice(sourceIndex, 1);
    const adjustedTargetIndex =
      targetIndex - (sourceIndex < targetIndex ? 1 : 0);
    next.exercises.splice(
      adjustedTargetIndex + (dropPosition === 'after' ? 1 : 0),
      0,
      exercise,
    );
    syncChanges(next);
  }

  function endExerciseDrag(): void {
    draggingExerciseId = null;
    dropTargetExerciseId = null;
    dropPosition = 'before';
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
    syncChanges(next);
  }

  function removeSet(exerciseId: string, setId: string): void {
    const next = structuredClone(content);
    const exercise = next.exercises.find((item) => item.id === exerciseId);
    if (
      !exercise ||
      exercise.sets.at(-1)?.id !== setId ||
      exercise.sets.some((item) => item.id === setId && item.done)
    )
      return;
    exercise.sets = exercise.sets.filter((item) => item.id !== setId);
    for (const field of ['reps', 'weight_kg', 'bw_percent_override', 'rpe'])
      delete next.raw_fields[fieldKey(setId, field)];
    syncChanges(next);
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
        return 'Storage error, the latest visible edit is not safely stored';
      return `Locally saved change ${editor.savedChange}, offline recovery mode`;
    }
    if (sync.status === 'saving_local') return 'Saving locally…';
    if (sync.status === 'locally_saved') return 'Not synced yet';
    if (sync.status === 'syncing') return 'Syncing durable changes…';
    if (sync.status === 'synced') return 'Synced';
    if (sync.status === 'offline') return 'Offline, changes remain local';
    if (sync.status === 'authentication_required')
      return sync.finishPending
        ? 'Authentication required, finish remains pending'
        : 'Authentication required, upload is paused';
    if (sync.status === 'conflict')
      return 'Conflict, automatic saving is paused with this draft retained';
    if (sync.status === 'finish_pending')
      return 'Finish pending, the final graph is stored and will retry exactly';
    if (sync.status === 'storage_error')
      return 'Storage error, the latest visible edit is not safely stored';
    if (sync.status === 'correction_required')
      return 'Correction required before this workout can sync';
    return 'Synchronization paused';
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
  id="workout-editor"
  aria-label="Workout editor"
  class:hidden={pickerTarget !== undefined}
  class="flex flex-col gap-4"
>
  <div
    class="sticky top-0 z-10 rounded-lg border border-edge bg-surface p-3 shadow-sm"
  >
    {#if sync?.message}<p class="mt-1 text-sm text-muted">
        {sync.message}
      </p>{/if}
    <div class="flex flex-wrap gap-2">
      {#if sync?.status === 'storage_error' || sync?.status === 'offline' || sync?.status === 'finish_pending' || sync?.status === 'error' || (!sync && editor.status === 'failed')}
        <button
          id="workout-sync-retry-button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3"
          type="button"
          aria-label={retryLabel()}
          title={retryLabel()}
          onclick={() => void (sync ? sync.retry() : editor.retry())}
          ><ActionIcon name="refresh" /></button
        >
      {/if}
      <span
        id="workout-sync-status"
        role="status"
        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md"
        class:text-sync-error={sync?.status === 'storage_error' ||
          sync?.status === 'conflict' ||
          sync?.status === 'correction_required' ||
          sync?.status === 'error'}
        class:text-sync-ok={sync?.status === 'synced'}
        class:text-sync-pending={sync?.status === 'saving_local' ||
          sync?.status === 'syncing' ||
          sync?.status === 'finish_pending'}
        class:text-muted={sync?.status === 'locally_saved' ||
          sync?.status === 'offline' ||
          sync?.status === 'authentication_required' ||
          !sync}
        aria-label={statusText()}
        title={statusText()}
      >
        {#if sync?.status === 'synced'}
          <ActionIcon name="finish" />
        {:else if sync?.status === 'saving_local' || sync?.status === 'syncing'}
          <ActionIcon name="refresh" />
        {:else}
          <ActionIcon name="save" />
        {/if}
      </span>
      <button
        id="workout-finish-button"
        class="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
        type="button"
        disabled={!sync?.canFinish}
        onclick={confirmFinish}>Finish workout</button
      >
      <button
        id="workout-cancel-button"
        class="inline-flex min-h-11 items-center justify-center rounded-md border border-danger px-4 font-medium text-danger disabled:opacity-40"
        type="button"
        disabled={sync === undefined || locked || sync.discarding}
        onclick={confirmCancel}
        >{sync?.discarding ? 'Discarding…' : 'Cancel'}</button
      >
    </div>
    {#if blocker}
      <p id="workout-finish-blocker" class="mt-2 text-sm text-muted">
        {blocker}
      </p>
    {/if}
  </div>

  <div class="grid gap-3 rounded-lg border border-edge bg-surface p-4">
    <p id="workout-started-at" class="text-sm text-muted">
      Started {formatRelativeTime(editor.current!.started_at) ??
        editor.current!.started_at}
    </p>
    <p class="font-semibold">{content.name ?? 'Workout'}</p>
    <p aria-label="Workout completion">
      {completion.percent}% completed ({completion.completedSets} of
      {completion.totalSets}
      {completion.totalSets === 1 ? 'set' : 'sets'})
    </p>
  </div>

  {#each content.exercises as exercise (exercise.id)}
    {@const progress = exerciseProgress(exercise)}
    {@const snapshot = snapshotOf(exercise.id)}
    <section
      id={`workout-exercise-${exercise.id}`}
      class="rounded-lg border border-edge bg-surface p-4 transition-opacity"
      class:border-primary={dropTargetExerciseId === exercise.id}
      class:ring-2={dropTargetExerciseId === exercise.id}
      class:opacity-50={draggingExerciseId === exercise.id}
      aria-label={`${exerciseName(exercise)} editor`}
      aria-roledescription={expandedExerciseId === exercise.id
        ? undefined
        : 'Draggable exercise card'}
      draggable={!locked && expandedExerciseId !== exercise.id}
      title={expandedExerciseId === exercise.id ? undefined : 'Drag to reorder'}
      ondragstart={(event) => startExerciseDrag(event, exercise.id)}
      ondragend={endExerciseDrag}
      ondragover={(event) => allowExerciseDrop(event, exercise.id)}
      ondrop={(event) => dropExercise(event, exercise.id)}
    >
      <div class="flex items-start justify-between gap-2">
        <button
          id={`workout-exercise-toggle-${exercise.id}`}
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
            {progress.completedSets} / {progress.totalSets}{progress.complete
              ? ' · Completed'
              : ''}
          </p>
        </button>
        {#if expandedExerciseId === exercise.id}<div
            class="flex shrink-0 gap-2"
          >
            <button
              id={`workout-exercise-remove-${exercise.id}`}
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
        {@const lastSet = exercise.sets.at(-1)}
        {#if catalogIssue(content, exercise.id)}
          <p role="alert" class="mt-2 text-sm text-danger">
            {catalogIssue(content, exercise.id)}
          </p>
          <button
            id={`workout-exercise-replace-${exercise.id}`}
            type="button"
            class="mt-2 min-h-11 rounded-md border border-edge px-3"
            disabled={locked}
            onclick={() => choosePicker(exercise.id)}>Replace exercise</button
          >
        {/if}
        <div class="mt-4 divide-y divide-edge border-y border-edge">
          {#each exercise.sets as set, setIndex (set.id)}
            {@const error = setError(content, exercise, set)}
            {@const validationError = error ?? completionErrors[set.id]}
            <fieldset
              id={`workout-set-${set.id}`}
              class="py-2"
              aria-describedby={validationError
                ? `set-error-${set.id}`
                : undefined}
            >
              <legend class="sr-only">Set {setIndex + 1}</legend>
              <div
                class="grid gap-2 {snapshot?.load_type === 'bodyweight'
                  ? 'grid-cols-[2rem_minmax(0,1fr)_2.75rem]'
                  : 'grid-cols-[2rem_minmax(0,1fr)_minmax(0,1fr)_2.75rem]'}"
              >
                <span
                  class="flex min-h-10 items-center justify-center text-sm font-medium"
                  >{setIndex + 1}</span
                >
                <label class="sr-only" for={`workout-set-${set.id}-reps`}
                  >Set {setIndex + 1} reps</label
                >
                <input
                  id={`workout-set-${set.id}-reps`}
                  placeholder="Reps"
                  inputmode="numeric"
                  step="1"
                  disabled={locked || set.done}
                  class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                  value={rawValue(content, set, 'reps')}
                  oninput={(event) =>
                    updateIntegerField(
                      set.id,
                      'reps',
                      event.currentTarget.value,
                    )}
                />
                {#if snapshot?.load_type !== 'bodyweight'}
                  <label class="sr-only" for={`workout-set-${set.id}-weight`}
                    >Set {setIndex + 1} weight in kilograms</label
                  >
                  <input
                    id={`workout-set-${set.id}-weight`}
                    placeholder="kg"
                    inputmode="numeric"
                    step="1"
                    disabled={locked || set.done}
                    class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
                    value={rawValue(content, set, 'weight_kg')}
                    oninput={(event) =>
                      updateIntegerField(
                        set.id,
                        'weight_kg',
                        event.currentTarget.value,
                      )}
                  />
                {/if}
                <div class="flex gap-1">
                  {#if set.done}
                    <button
                      id={`workout-set-edit-${set.id}`}
                      type="button"
                      class="inline-flex min-h-10 min-w-10 items-center justify-center rounded-md border border-edge"
                      aria-label={`Edit set ${setIndex + 1}`}
                      title={`Edit set ${setIndex + 1}`}
                      disabled={locked}
                      onclick={() =>
                        updateSet(exercise.id, set.id, { done: false }, true)}
                      ><ActionIcon name="edit" /></button
                    >
                  {:else}
                    <button
                      id={`workout-set-complete-${set.id}`}
                      type="button"
                      aria-label={`Mark set ${setIndex + 1} completed`}
                      title={`Mark set ${setIndex + 1} completed`}
                      class="inline-flex min-h-10 min-w-10 items-center justify-center rounded-md border border-edge"
                      disabled={locked}
                      onclick={() => completeSet(exercise.id, set.id)}
                      ><ActionIcon name="finish" /></button
                    >
                  {/if}
                </div>
              </div>
              <div class="ml-10 mt-2 grid grid-cols-2 gap-2">
                {#if snapshot?.load_type !== 'bodyweight' && snapshot?.bodyweight_percent !== null}<label
                    class="text-sm font-medium"
                    for={`workout-set-${set.id}-bodyweight-override`}
                    >Bodyweight % override<input
                      id={`workout-set-${set.id}-bodyweight-override`}
                      inputmode="numeric"
                      step="1"
                      disabled={locked || set.done}
                      class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
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
                    for={`workout-set-${set.id}-side`}
                    >Side<select
                      id={`workout-set-${set.id}-side`}
                      class="min-h-10 w-full rounded-md border border-edge bg-surface px-2"
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
                  class="ml-10 mt-2 text-sm text-danger"
                >
                  {validationError}
                </p>{/if}
            </fieldset>
          {/each}
        </div>
        <div class="mt-3 flex gap-2">
          <button
            id={`workout-set-add-${exercise.id}`}
            type="button"
            class="min-h-11 rounded-md border border-edge px-3 disabled:opacity-40"
            aria-label={`Add set to ${exerciseName(exercise)}`}
            title={`Add set to ${exerciseName(exercise)}`}
            disabled={locked || exercise.sets.length >= MAX_SETS_PER_EXERCISE}
            onclick={() => addSet(exercise)}><ActionIcon name="add" /></button
          >
          {#if lastSet}
            <button
              id={`workout-set-remove-${lastSet.id}`}
              type="button"
              class="min-h-11 rounded-md border border-danger px-3 text-danger disabled:opacity-40"
              aria-label={`Remove set ${exercise.sets.length}`}
              title={`Remove set ${exercise.sets.length}`}
              disabled={locked || lastSet.done}
              onclick={() => removeSet(exercise.id, lastSet.id)}
              ><ActionIcon name="remove" /></button
            >
          {/if}
        </div>
      {/if}
    </section>
  {/each}
  <button
    id="workout-exercise-add-button"
    type="button"
    class="min-h-11 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-40"
    disabled={locked || content.exercises.length >= MAX_EXERCISES}
    onclick={() => choosePicker()}>Add exercise</button
  >
</section>
