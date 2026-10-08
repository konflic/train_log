import type { Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

/**
 * The e2e-mode build exposes the real frontend API helpers on
 * `window.__basefitApi` (see src/main.ts); production builds never include
 * the hook. Calls run inside the page, so cookies, Origin, and the Vite
 * `/api` proxy behave exactly like the real app.
 */
interface ApiHook {
  fetchCurrentUser(): Promise<{ id: string; email: string }>;
  registerUser(input: {
    email: string;
    password: string;
  }): Promise<{ id: string; email: string }>;
  login(input: {
    email: string;
    password: string;
  }): Promise<{ id: string; email: string }>;
  listExercises(query?: { page?: number; pageSize?: number }): Promise<{
    items: Array<{ id: string; is_default: boolean }>;
    total: number;
  }>;
}

export type { ApiHook };

export const E2E_PASSWORD = 'e2e-password-123';

export function uniqueEmail(): string {
  return `e2e-${randomUUID()}@example.test`;
}

/** Load the app and wait for the e2e-only API hook to be attached. */
export async function gotoApp(page: Page): Promise<void> {
  await page.goto('/');
  await page.waitForFunction(() => '__basefitApi' in window);
}

/** Register an account through the real API helpers in the page. */
export async function registerThroughApi(
  page: Page,
  email = uniqueEmail(),
): Promise<string> {
  await page.evaluate(
    async ({ email, password }) => {
      const hook = (window as unknown as { __basefitApi: ApiHook })
        .__basefitApi;
      await hook.registerUser({ email, password });
    },
    { email, password: E2E_PASSWORD },
  );
  return email;
}

/** Register and log in through the real API helpers; cookie lands in browser. */
export async function signInThroughApi(
  page: Page,
  email = uniqueEmail(),
): Promise<string> {
  await page.evaluate(
    async ({ email, password }) => {
      const hook = (window as unknown as { __basefitApi: ApiHook })
        .__basefitApi;
      await hook.registerUser({ email, password });
      await hook.login({ email, password });
    },
    { email, password: E2E_PASSWORD },
  );
  return email;
}

/**
 * Start from a signed-in Home. The reload resolves GET /auth/me through the
 * real startup flow rather than trusting the hook's session.
 */
export async function gotoSignedIn(page: Page): Promise<string> {
  await gotoApp(page);
  const email = await signInThroughApi(page);
  await page.reload();
  await page.waitForFunction(() => '__basefitApi' in window);
  return email;
}
