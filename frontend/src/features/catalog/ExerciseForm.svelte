<script lang="ts">
  import { onMount } from 'svelte';
  import {
    createExercise,
    updateExercise,
    type Exercise,
    type ExerciseUpdateInput,
    type LoadType,
    type MuscleGroup,
  } from '../../api';
  import { mapFailureToForm, type FormFailure } from '../../lib/failures';
  import {
    loadTypeLabels,
    loadTypeValues,
    muscleGroupLabels,
    muscleGroupValues,
  } from './labels';
  import { validateExerciseDraft, type ExerciseDraft } from './validation';

  let {
    exercise,
    onclose,
  }: {
    /** The custom entry being edited, or `null` to create a new one. */
    exercise: Exercise | null;
    /** Called after close; `saved` tells whether the list should refresh. */
    onclose: (saved: boolean) => void;
  } = $props();

  const noErrors: FormFailure = { form: null, fields: {} };
  const MAX_NAME_LENGTH = 100;

  // The form is remounted per target (keyed by the caller), so capturing the
  // initial prop values into editable local state is exactly the intent:
  // editing starts from the entry's current complete values.
  /* svelte-ignore state_referenced_locally */
  let name = $state(exercise?.name ?? '');
  /* svelte-ignore state_referenced_locally */
  let muscleGroup = $state<MuscleGroup>(exercise?.muscle_group ?? 'chest');
  /* svelte-ignore state_referenced_locally */
  let loadType = $state<LoadType>(exercise?.load_type ?? 'single_weight');
  // Percent stays text until submit so fractional input is rejected, never
  // silently coerced (PLAN.md §3).
  /* svelte-ignore state_referenced_locally */
  let percentText = $state(
    exercise?.bodyweight_percent != null
      ? String(exercise.bodyweight_percent)
      : '',
  );
  /* svelte-ignore state_referenced_locally */
  let sideCount = $state<number>(exercise?.side_count ?? 1);

  let submitting = $state(false);
  let errors = $state<FormFailure>(noErrors);
  let alertRef = $state<HTMLElement | undefined>();
  let nameRef = $state<HTMLInputElement | undefined>();

  onMount(() => {
    nameRef?.focus();
  });

  function handleLoadTypeChange(): void {
    if (loadType !== 'split_weight') {
      // Only split-weight entries may cover two sides; the API enforces it.
      sideCount = 1;
    }
  }

  function draft(): ExerciseDraft {
    return {
      name,
      loadType,
      percentText,
      sideCount,
      maxNameLength: MAX_NAME_LENGTH,
    };
  }

  function parsedPercent(): number | null {
    const trimmed = percentText.trim();
    return trimmed === '' ? null : Number.parseInt(trimmed, 10);
  }

  /** PATCH carries only fields whose normalized value actually changed. */
  function buildPatch(): ExerciseUpdateInput {
    if (exercise === null) {
      return {};
    }
    const patch: ExerciseUpdateInput = {};
    const trimmedName = name.trim();
    if (trimmedName !== exercise.name) {
      patch.name = trimmedName;
    }
    if (muscleGroup !== exercise.muscle_group) {
      patch.muscle_group = muscleGroup;
    }
    if (loadType !== exercise.load_type) {
      patch.load_type = loadType;
    }
    const percent = parsedPercent();
    if (percent !== exercise.bodyweight_percent) {
      patch.bodyweight_percent = percent;
    }
    if (sideCount !== exercise.side_count) {
      patch.side_count = sideCount;
    }
    return patch;
  }

  async function handleSubmit(): Promise<void> {
    if (submitting) {
      return;
    }
    const fieldErrors = validateExerciseDraft(draft());
    errors = { form: null, fields: fieldErrors };
    if (Object.keys(fieldErrors).length > 0) {
      return;
    }
    submitting = true;
    try {
      if (exercise === null) {
        await createExercise({
          name: name.trim(),
          muscle_group: muscleGroup,
          load_type: loadType,
          bodyweight_percent: parsedPercent(),
          side_count: sideCount,
        });
      } else {
        const patch = buildPatch();
        if (Object.keys(patch).length > 0) {
          await updateExercise(exercise.id, patch);
        }
      }
      onclose(true);
    } catch (error) {
      // The backend remains authoritative (duplicate names, cross-field rules).
      errors = mapFailureToForm(error);
      alertRef?.focus();
    } finally {
      submitting = false;
    }
  }
</script>

<section
  aria-labelledby="exercise-form-heading"
  class="rounded-lg border border-edge bg-surface p-4"
>
  <h2 id="exercise-form-heading" tabindex="-1" class="text-lg font-semibold">
    {exercise === null ? 'New custom exercise' : `Edit ${exercise.name}`}
  </h2>

  {#if errors.form !== null}
    <p
      role="alert"
      tabindex="-1"
      bind:this={alertRef}
      class="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
    >
      {errors.form}
    </p>
  {/if}

  <form
    class="mt-3 flex flex-col gap-4"
    novalidate
    onsubmit={(event) => {
      event.preventDefault();
      void handleSubmit();
    }}
  >
    <div>
      <label for="exercise-name" class="block text-sm font-medium">Name</label>
      <input
        id="exercise-name"
        name="name"
        type="text"
        autocomplete="off"
        maxlength={MAX_NAME_LENGTH}
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
        bind:value={name}
        bind:this={nameRef}
        aria-invalid={errors.fields.name !== undefined}
        aria-describedby={errors.fields.name !== undefined
          ? 'exercise-name-error'
          : undefined}
      />
      {#if errors.fields.name !== undefined}
        <p id="exercise-name-error" class="mt-1 text-sm text-danger">
          {errors.fields.name}
        </p>
      {/if}
    </div>

    <div>
      <label for="exercise-muscle-group" class="block text-sm font-medium"
        >Muscle group</label
      >
      <select
        id="exercise-muscle-group"
        name="muscle_group"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
        bind:value={muscleGroup}
      >
        {#each muscleGroupValues as value (value)}
          <option {value}>{muscleGroupLabels[value]}</option>
        {/each}
      </select>
    </div>

    <div>
      <label for="exercise-load-type" class="block text-sm font-medium"
        >Load type</label
      >
      <select
        id="exercise-load-type"
        name="load_type"
        class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
        bind:value={loadType}
        onchange={handleLoadTypeChange}
      >
        {#each loadTypeValues as value (value)}
          <option {value}>{loadTypeLabels[value]}</option>
        {/each}
      </select>
    </div>

    <div class="flex flex-col gap-4 sm:flex-row">
      <div class="flex-1">
        <label for="exercise-percent" class="block text-sm font-medium">
          Bodyweight percentage
          <span class="font-normal text-muted">
            ({loadType === 'bodyweight' ? 'required' : 'optional'}, whole 1–100)
          </span>
        </label>
        <input
          id="exercise-percent"
          name="bodyweight_percent"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2"
          bind:value={percentText}
          aria-invalid={errors.fields.bodyweight_percent !== undefined}
          aria-describedby={errors.fields.bodyweight_percent !== undefined
            ? 'exercise-percent-error'
            : undefined}
        />
        {#if errors.fields.bodyweight_percent !== undefined}
          <p id="exercise-percent-error" class="mt-1 text-sm text-danger">
            {errors.fields.bodyweight_percent}
          </p>
        {/if}
      </div>
      <div class="flex-1">
        <label for="exercise-side-count" class="block text-sm font-medium"
          >Sides</label
        >
        <select
          id="exercise-side-count"
          name="side_count"
          class="mt-1 min-h-11 w-full rounded-md border border-edge bg-surface px-3 py-2 disabled:opacity-60"
          bind:value={sideCount}
          disabled={loadType !== 'split_weight'}
        >
          <option value={1}>1 (one side per set)</option>
          <option value={2}>2 (both sides per set)</option>
        </select>
        {#if errors.fields.side_count !== undefined}
          <p class="mt-1 text-sm text-danger">{errors.fields.side_count}</p>
        {/if}
      </div>
    </div>

    <div class="flex gap-2">
      <button
        type="submit"
        disabled={submitting}
        class="min-h-11 flex-1 rounded-md bg-primary px-4 font-medium text-primary-content disabled:opacity-60"
      >
        {submitting
          ? 'Saving…'
          : exercise === null
            ? 'Create exercise'
            : 'Save changes'}
      </button>
      <button
        type="button"
        class="min-h-11 rounded-md border border-edge px-4 font-medium"
        onclick={() => onclose(false)}
      >
        Cancel
      </button>
    </div>
  </form>
</section>
