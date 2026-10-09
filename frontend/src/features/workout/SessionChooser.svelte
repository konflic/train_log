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
<p class="mt-2 text-muted">Browsing this screen does not start a workout.</p>
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
  <div class="mt-5 grid gap-3">
    <button
      type="button"
      id="start-freestyle-session-button"
      class="min-h-11 rounded-lg bg-primary px-4 text-left font-medium text-primary-content disabled:opacity-40"
      disabled={busy}
      onclick={() => void startFreestyle()}
    >
      Freestyle session
    </button>
    <a
      id="start-plan-session-link"
      href="#/training-plans"
      class="flex min-h-11 items-center rounded-lg border border-edge px-4 font-medium"
      >Plan session</a
    >
  </div>
{/if}
