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

function start(mountTarget: HTMLElement): void {
  mount(App, { target: mountTarget });
}

start(target);
