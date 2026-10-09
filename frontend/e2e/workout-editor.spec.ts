import { expect, test } from '@playwright/test';
import { gotoApp, gotoSignedIn } from './helpers';

async function startFreestyle(
  page: import('@playwright/test').Page,
): Promise<void> {
  await page.getByRole('link', { name: 'Start workout session' }).click();
  await page.getByRole('button', { name: 'Freestyle session' }).click();
  await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+$/);
  await expect(
    page.getByRole('heading', { name: 'Active workout' }),
  ).toBeVisible();
}

async function addExercise(
  page: import('@playwright/test').Page,
  name: string,
): Promise<import('@playwright/test').Locator> {
  await page.locator('#workout-exercise-add-button').click();
  await page.getByLabel('Search').fill(name);
  await page
    .getByLabel('Exercise picker')
    .getByRole('button', { name: new RegExp(`^${name}`) })
    .click();
  const exercise = page.getByLabel(`${name} editor`);
  await expect(exercise).toBeVisible();
  return exercise;
}

test.describe('workout editor', () => {
  test('centers the named login controls and logo placeholder', async ({
    page,
  }) => {
    await gotoApp(page);
    await expect(page.locator('#login-screen')).toBeVisible();
    await expect(page.locator('#login-logo-placeholder')).toBeVisible();
    await expect(page.locator('#login-form')).toBeVisible();
    await expect(page.locator('#login-submit-button')).toBeVisible();
  });

  test('opens the authoritative workout without a draft URL or revision display', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page.locator('#workout-sync-status')).toHaveText('Synced.');
    await expect(page.locator('#workout-editor')).not.toContainText(
      /revision/i,
    );
  });

  test('swaps completed-set edit and last-set remove actions inline', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    const exercise = await addExercise(page, 'Bench Press');
    const firstSet = exercise.getByRole('group', { name: 'Set 1' });
    await firstSet.getByLabel('Set 1 reps').fill('8');
    await firstSet.getByLabel('Set 1 weight in kilograms').fill('50');
    await firstSet
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();
    await expect(firstSet.locator('[id^="workout-set-remove-"]')).toBeVisible();

    await exercise
      .getByRole('button', { name: 'Add set to Bench Press' })
      .click();
    const secondSet = exercise.getByRole('group', { name: 'Set 2' });
    await expect(secondSet).toBeVisible();
    await expect(
      firstSet.getByRole('button', { name: 'Edit set 1' }),
    ).toBeVisible();
    await expect(
      secondSet.getByRole('button', { name: 'Remove set 2' }),
    ).toBeVisible();
    await expect(
      exercise.getByRole('button', { name: /Move set/ }),
    ).toHaveCount(0);

    await secondSet.getByRole('button', { name: 'Remove set 2' }).click();
    await expect(exercise.getByRole('group', { name: 'Set 2' })).toHaveCount(0);
    await expect(
      firstSet.getByRole('button', { name: 'Remove set 1' }),
    ).toBeVisible();
  });
});
