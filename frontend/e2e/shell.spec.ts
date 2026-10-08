import { expect, test } from '@playwright/test';
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

/** Wait until the e2e build has attached the real API helpers. */
async function gotoWithApi(
  page: import('@playwright/test').Page,
): Promise<void> {
  await page.goto('/');
  await page.waitForFunction(() => '__basefitApi' in window);
}

test.describe('application shell', () => {
  test('renders the shell in a real browser', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('BaseFit');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Home' }),
    ).toBeVisible();
    await expect(
      page.getByRole('navigation', { name: 'Primary' }),
    ).toBeVisible();
  });

  test('backend health is reachable through the /api proxy', async ({
    request,
  }) => {
    const response = await request.get('/api/v1/health');
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
  });
});

test.describe('pre-paint theme', () => {
  test('applies the saved theme to the document root without the app bundle', async ({
    page,
  }) => {
    // Abort every bundled script: only the inline bootstrap in index.html
    // may apply the theme, proving it runs before/independent of the app.
    await page.route('**/assets/**', (route) => route.abort());
    await page.addInitScript(() => {
      localStorage.setItem('basefit.theme', 'dark');
    });
    await page.goto('/');
    await expect(page.locator('html')).toHaveClass(/dark/);
    await expect(page.locator('html')).not.toHaveClass(/light/);
    const scheme = await page.evaluate(
      () => getComputedStyle(document.documentElement).colorScheme,
    );
    expect(scheme).toBe('dark');
  });

  test('falls back to the system preference and light on first visit', async ({
    page,
  }) => {
    await page.route('**/assets/**', (route) => route.abort());
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/');
    await expect(page.locator('html')).toHaveClass(/dark/);

    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/');
    await expect(page.locator('html')).toHaveClass(/light/);
  });

  test('ignores an invalid stored value', async ({ page }) => {
    await page.route('**/assets/**', (route) => route.abort());
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => {
      localStorage.setItem('basefit.theme', 'neon');
    });
    await page.goto('/');
    await expect(page.locator('html')).toHaveClass(/light/);
  });
});

test.describe('hash routing', () => {
  test('navigates between shell routes and renders not-found', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Home' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Catalog' }).click();
    await expect(page).toHaveURL(/#\/catalog/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Catalog' }),
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'Catalog' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    await page.getByRole('link', { name: 'History' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'History' }),
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'History' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    await page.goto('/#/no-such-route');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Page not found' }),
    ).toBeVisible();
  });

  test('navigation links are keyboard operable', async ({ page }) => {
    await page.goto('/');
    const catalog = page.getByRole('link', { name: 'Catalog' });
    await catalog.focus();
    await expect(catalog).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#\/catalog/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Catalog' }),
    ).toBeVisible();
  });
});

test.describe('api helpers against the live backend', () => {
  test('register, login, and an authenticated read through the proxy', async ({
    page,
  }) => {
    await gotoWithApi(page);
    const email = `e2e-${randomUUID()}@example.test`;
    const password = 'e2e-password-123';

    const anonymousStatus = await page.evaluate(async () => {
      const hook = (window as unknown as { __basefitApi: ApiHook })
        .__basefitApi;
      try {
        await hook.fetchCurrentUser();
        return null;
      } catch (error) {
        return (
          (error as { problem?: { status?: number } }).problem?.status ?? -1
        );
      }
    });
    expect(anonymousStatus).toBe(401);

    // Real browser mutations: the server sets the HttpOnly session cookie
    // on the page origin exactly like the real app flow.
    const user = await page.evaluate(
      async ({ email, password }) => {
        const hook = (window as unknown as { __basefitApi: ApiHook })
          .__basefitApi;
        const created = await hook.registerUser({ email, password });
        const session = await hook.login({ email, password });
        return {
          createdEmail: created.email,
          sessionEmail: session.email,
          id: session.id,
        };
      },
      { email, password },
    );
    expect(user.createdEmail).toBe(email);
    expect(user.sessionEmail).toBe(email);

    const read = await page.evaluate(async () => {
      const hook = (window as unknown as { __basefitApi: ApiHook })
        .__basefitApi;
      const me = await hook.fetchCurrentUser();
      const catalog = await hook.listExercises({ page: 1, pageSize: 5 });
      return {
        email: me.email,
        total: catalog.total,
        firstIsDefault: catalog.items[0]?.is_default ?? null,
      };
    });
    expect(read.email).toBe(email);
    expect(read.total).toBeGreaterThan(0);
    expect(read.firstIsDefault).toBe(true);
  });

  test('api failures surface as typed problems in the browser', async ({
    page,
  }) => {
    await gotoWithApi(page);
    const failure = await page.evaluate(async () => {
      const hook = (window as unknown as { __basefitApi: ApiHook })
        .__basefitApi;
      try {
        await hook.login({
          email: 'no-such@example.test',
          password: 'wrong-password',
        });
        return null;
      } catch (error) {
        const problem = (
          error as { problem?: { status?: number; code?: string } }
        ).problem;
        return { status: problem?.status ?? null, code: problem?.code ?? null };
      }
    });
    expect(failure).toEqual({ status: 401, code: 'unauthorized' });
  });
});
