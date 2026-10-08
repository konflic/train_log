import { expect, test } from '@playwright/test';
import { gotoSignedIn } from './helpers';

test.describe('locally persistent workout editor', () => {
  test('quick-starts, edits a graph, and recovers its locally saved draft without a PUT', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    let putCount = 0;
    await page.route('**/api/v1/workouts/**', async (route) => {
      if (route.request().method() === 'PUT') putCount += 1;
      await route.continue();
    });

    await page.getByRole('link', { name: 'Quick start workout' }).click();
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Active workout' }),
    ).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 0',
    );

    await page.getByRole('button', { name: 'Add exercise' }).click();
    await page.getByRole('button', { name: 'Bench Press' }).click();
    const exercise = page.getByLabel('Bench Press editor');
    await exercise.getByLabel('Reps').fill('8');
    await exercise.getByLabel('Weight (kg)').fill('50');
    await exercise.getByLabel('Completed').check();
    await expect(
      page.getByText('400 kg·reps from 1 completed set.'),
    ).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 4',
    );

    await exercise.getByRole('button', { name: 'Add set' }).click();
    await expect(exercise.getByRole('group', { name: 'Set 2' })).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Active workout' }),
    ).toBeVisible();
    await expect(
      page.getByRole('group', { name: 'Set 1' }).getByLabel('Weight (kg)'),
    ).toHaveValue('50');
    expect(putCount).toBe(0);
  });
});
