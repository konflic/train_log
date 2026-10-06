import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

// Dev/preview servers proxy API calls to the backend. Override the target
// with BACKEND_ORIGIN when the backend listens on another port (the
// Playwright config does this for E2E).
const backendOrigin = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8000';

const apiProxy = {
  '/api': {
    target: backendOrigin,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [svelte(), svelteTesting()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
});
