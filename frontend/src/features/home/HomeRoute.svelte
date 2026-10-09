<script lang="ts">
  import { session } from '../auth/session.svelte';
  import RecentHistoryPanel from './RecentHistoryPanel.svelte';
  import WeeklySummaryPanel from './WeeklySummaryPanel.svelte';

  const user = $derived(session.user);
  const utcOffsetMinutes = $derived(user?.utc_offset_minutes ?? 0);
</script>

<svelte:head>
  <title>Home · BaseFit</title>
</svelte:head>

<h1 tabindex="-1">Home</h1>
{#if user !== null}
  <p class="mt-1 text-sm text-muted">
    Signed in as {user.display_name ?? user.email}
  </p>
{/if}

<div class="mt-4 flex flex-col gap-4">
  <section
    class="rounded-lg border border-edge bg-surface p-4"
    aria-labelledby="training-plans-heading"
  >
    <h2 id="training-plans-heading" class="text-lg font-semibold">
      Training plans
    </h2>
    <p class="mt-1 text-sm text-muted">
      Build reusable routines for your workouts.
    </p>
    <a
      href="#/training-plans"
      class="mt-3 inline-flex min-h-11 items-center rounded-md border border-edge px-4"
      >Manage training plans</a
    >
  </section>
  <RecentHistoryPanel />
  <WeeklySummaryPanel {utcOffsetMinutes} />
</div>
