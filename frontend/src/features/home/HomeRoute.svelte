<script lang="ts">
  import { session } from '../auth/session.svelte';
  import ActiveWorkoutsPanel from './ActiveWorkoutsPanel.svelte';
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

<a
  href="#/workouts/new"
  class="mt-4 inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-primary-content"
  >Quick start workout</a
>

<div class="mt-4 flex flex-col gap-4">
  <ActiveWorkoutsPanel {utcOffsetMinutes} />
  <RecentHistoryPanel {utcOffsetMinutes} />
  <WeeklySummaryPanel {utcOffsetMinutes} />
</div>
