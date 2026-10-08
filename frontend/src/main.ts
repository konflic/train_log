import App from './App.svelte';
import './app.css';
import { mount } from 'svelte';

// Test-only browser flow for E2E proof of the real API helpers. Built with
// `vite build --mode e2e` only; production builds statically drop this
// branch, so the hook and its dynamic import never ship.
if (import.meta.env.MODE === 'e2e') {
  void import('./api').then((api) => {
    const target = window as unknown as { __basefitApi?: typeof api };
    target.__basefitApi = api;
  });
}

const target = document.getElementById('app');
if (!target) {
  throw new Error('Missing #app mount target');
}

async function start(mountTarget: HTMLElement): Promise<void> {
  if (
    import.meta.env.MODE === 'e2e' &&
    new URLSearchParams(window.location.search).has('draftHarness') &&
    window.location.hash === '#/draft-harness'
  ) {
    // The recovery harness is dynamically imported only by the explicit E2E
    // build, so production bundles expose neither its route nor failure hook.
    const { default: DraftHarnessRoute } =
      await import('./features/drafts/DraftHarnessRoute.svelte');
    mount(App, {
      target: mountTarget,
      props: { draftHarness: DraftHarnessRoute },
    });
    return;
  }
  mount(App, { target: mountTarget });
}

void start(target);
