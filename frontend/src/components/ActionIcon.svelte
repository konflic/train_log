<script lang="ts">
  let {
    name,
    size = 20,
  }: {
    name:
      | 'add'
      | 'catalog'
      | 'close'
      | 'edit'
      | 'down'
      | 'drag'
      | 'finish'
      | 'history'
      | 'home'
      | 'refresh'
      | 'remove'
      | 'save'
      | 'settings'
      | 'up'
      | 'workout';
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
  {:else if name === 'catalog'}
    <path d="M5 4h14v16H5zM8 4v16M11 8h5M11 12h5" />
  {:else if name === 'close'}
    <path d="m6 6 12 12M18 6 6 18" />
  {:else if name === 'edit'}
    <path d="m4 20 4-1 11-11-3-3L5 16zM14 6l3 3" />
  {:else if name === 'down'}
    <path d="m6 9 6 6 6-6" />
  {:else if name === 'drag'}
    <circle cx="8" cy="6" r="1" fill="currentColor" />
    <circle cx="16" cy="6" r="1" fill="currentColor" />
    <circle cx="8" cy="12" r="1" fill="currentColor" />
    <circle cx="16" cy="12" r="1" fill="currentColor" />
    <circle cx="8" cy="18" r="1" fill="currentColor" />
    <circle cx="16" cy="18" r="1" fill="currentColor" />
  {:else if name === 'finish'}
    <path d="M20 6 9 17l-5-5" />
  {:else if name === 'history'}
    <circle cx="12" cy="12" r="8" />
    <path d="M12 7v5l3 2" />
  {:else if name === 'home'}
    <path d="m4 11 8-7 8 7v9H4zM9 20v-6h6v6" />
  {:else if name === 'refresh'}
    <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
  {:else if name === 'remove'}
    <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
  {:else if name === 'save'}
    <path d="M5 4h12l2 2v14H5zM8 4v6h8V4M8 20v-6h8v6" />
  {:else if name === 'settings'}
    <circle cx="12" cy="12" r="3" />
    <path
      d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.5 4h-5l-.4 2.1a7 7 0 0 0-1.7 1l-2.3-1-2 3.4L5.1 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.4 2.1h5l.4-2.1a7 7 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z"
    />
  {:else if name === 'up'}
    <path d="m6 15 6-6 6 6" />
  {:else if name === 'workout'}
    <path d="M4 9v6M7 7v10M17 7v10M20 9v6M7 12h10" />
  {/if}
</svg>
