import { expect, test } from '@playwright/test';

test.describe('application shell', () => {
  test('renders the shell in a real browser', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('BaseFit');
    await expect(
      page.getByRole('heading', { level: 1, name: 'BaseFit' }),
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
