<script lang="ts">
  import { onMount } from 'svelte';
  import { animationFrames } from './animations';

  let {
    animationKey,
    exerciseName,
  }: {
    animationKey: string;
    exerciseName: string;
  } = $props();

  const frames = $derived(animationFrames(animationKey));

  // The loop runs indefinitely, so it is pausable; reduced-motion users start
  // paused while the control stays usable.
  let playing = $state(true);

  onMount(() => {
    if (
      typeof globalThis.matchMedia === 'function' &&
      globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      playing = false;
    }
  });

  const label = $derived(
    playing ? 'Pause movement animation' : 'Play movement animation',
  );
</script>

{#if frames !== null}
  <figure class="exercise-detail__animation my-0">
    <div
      class="frames"
      class:playing
      role="img"
      aria-label={`Two-position movement animation of ${exerciseName}: start and finish`}
    >
      <img class="frame frame-start" src={frames.start} alt="" />
      <img class="frame frame-finish" src={frames.finish} alt="" />
    </div>
    <figcaption class="mt-2 flex items-center justify-between gap-2">
      <span class="text-sm text-muted"
        >Start and finish positions, one second each</span
      >
      <button
        id="exercise-animation-toggle"
        type="button"
        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-edge px-3 text-sm font-medium"
        aria-pressed={playing}
        onclick={() => {
          playing = !playing;
        }}>{label}</button
      >
    </figcaption>
  </figure>
{/if}

<style>
  .frames {
    position: relative;
    width: 100%;
    max-width: 15rem;
    aspect-ratio: 3 / 2;
  }

  .frame {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    /* Two-second loop, each frame held for one second; stepped, never
       interpolated, and paused unless explicitly playing. */
    animation-duration: 2s;
    animation-timing-function: steps(1, end);
    animation-iteration-count: infinite;
    animation-play-state: paused;
  }

  .frame-start {
    animation-name: frame-start;
    opacity: 1;
  }

  .frame-finish {
    animation-name: frame-finish;
    opacity: 0;
  }

  .playing .frame {
    animation-play-state: running;
  }

  @keyframes frame-start {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0;
    }
  }

  @keyframes frame-finish {
    0%,
    100% {
      opacity: 0;
    }
    50% {
      opacity: 1;
    }
  }
</style>
