<script lang="ts">
  import { push } from 'svelte-spa-router';
  import ExerciseForm from './ExerciseForm.svelte';

  let closed = $state(false);

  function close(): void {
    closed = true;
    void push('/catalog');
  }
</script>

<svelte:head><title>New custom exercise · BaseFit</title></svelte:head>

{#if !closed}
  <a
    href="#/catalog"
    class="inline-flex min-h-11 items-center text-sm font-medium text-primary"
    >Back to catalog</a
  >
  <h1 tabindex="-1" class="mt-2">New custom exercise</h1>
  <div class="mt-4">
    <ExerciseForm exercise={null} onclose={close} />
  </div>
{/if}
