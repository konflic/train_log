import { defineConfig, devices } from '@playwright/test';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const configDir = fileURLToPath(new URL('.', import.meta.url));
const backendDir = resolve(configDir, '..', 'backend');

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8123);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 4173);
const BACKEND_ORIGIN = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_ORIGIN = `http://127.0.0.1:${FRONTEND_PORT}`;

// Isolated per-run data directory; each E2E run starts with a clean database
// location and Playwright tears both servers down afterwards.
const dataDir = mkdtempSync(join(tmpdir(), 'basefit-e2e-'));

function processEnv(): Record<string, string> {
  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

// Prefer an explicit override, then the local backend venv, then system python.
function findBackendPython(): string {
  if (process.env.BACKEND_PYTHON) {
    return process.env.BACKEND_PYTHON;
  }
  const venvPython = join(backendDir, '.venv', 'bin', 'python');
  return existsSync(venvPython) ? venvPython : 'python3';
}

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list']],
  use: {
    baseURL: FRONTEND_ORIGIN,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${findBackendPython()} -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: backendDir,
      env: {
        ...processEnv(),
        DATABASE_PATH: join(dataDir, 'e2e.db'),
        APP_ENV: 'test',
        PYTHONUNBUFFERED: '1',
      },
      url: `${BACKEND_ORIGIN}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npm run build && npm run preview -- --port ${FRONTEND_PORT} --strictPort`,
      cwd: configDir,
      env: {
        ...processEnv(),
        BACKEND_ORIGIN,
      },
      url: `${FRONTEND_ORIGIN}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
