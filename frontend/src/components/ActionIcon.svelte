<script lang="ts">
  let {
    name,
    size = 20,
  }: {
    name:
      | 'add'
      | 'close'
      | 'down'
      | 'finish'
      | 'refresh'
      | 'remove'
      | 'save'
      | 'up';
    size?: number;
  } = $props();
</script>

<svg
  aria-hidden="true"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
>
  {#if name === 'add'}
    <path d="M12 5v14M5 12h14" />
  {:else if name === 'close'}
    <path d="m6 6 12 12M18 6 6 18" />
  {:else if name === 'down'}
    <path d="m6 9 6 6 6-6" />
  {:else if name === 'finish'}
    <path d="M20 6 9 17l-5-5" />
  {:else if name === 'refresh'}
    <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
  {:else if name === 'remove'}
    <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
  {:else if name === 'save'}
    <path d="M5 4h12l2 2v14H5zM8 4v6h8V4M8 20v-6h8v6" />
  {:else if name === 'up'}
    <path d="m6 15 6-6 6 6" />
  {/if}
</svg>
