<script lang="ts">
  import { push } from 'svelte-spa-router';
  import { describeFailure } from '../../lib/failures';
  import { session } from '../auth/session.svelte';
  import { activeSession } from './activeSession.svelte';
  import { startSession } from './startSession';

  let busy = $state(false);
  let message = $state<string | null>(null);

  async function startFreestyle(): Promise<void> {
    if (busy || session.user === null) return;
    busy = true;
    message = null;
    try {
      const draft = await startSession(session.user.id);
      activeSession.setActive(draft.workout_id);
      await push(`/workouts/${draft.workout_id}`);
    } catch (error) {
      message = describeFailure(error);
      await activeSession.refresh(session.user.id);
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>Start session · BaseFit</title></svelte:head>
<h1 tabindex="-1">Choose session type</h1>
{#if message}<p role="alert" class="mt-3 text-danger">{message}</p>{/if}
{#if activeSession.workoutId !== null}
  <p class="mt-4">
    An active session is ready to resume.
    <a
      class="font-medium text-primary underline"
      href={`#/workouts/${activeSession.workoutId}`}>Resume active session</a
    >
  </p>
{:else}
  <div class="mt-5 grid gap-4">
    <button
      type="button"
      id="start-freestyle-session-button"
      class="min-h-32 rounded-lg bg-primary p-5 text-left text-primary-content disabled:opacity-40"
      disabled={busy}
      aria-label="Freestyle session"
      aria-describedby="freestyle-session-description"
      onclick={() => void startFreestyle()}
    >
      <span class="block text-lg font-semibold">Freestyle session</span>
      <span id="freestyle-session-description" class="mt-2 block text-sm"
        >Build a workout exercise by exercise as you go.</span
      >
    </button>
    <a
      id="start-plan-session-link"
      href="#/training-plans"
      class="min-h-32 rounded-lg border border-edge p-5"
      aria-label="Plan session"
      aria-describedby="plan-session-description"
    >
      <span class="block text-lg font-semibold">Plan session</span>
      <span id="plan-session-description" class="mt-2 block text-sm text-muted"
        >Start from a saved plan with its exercises and set targets.</span
      >
    </a>
  </div>
{/if}
