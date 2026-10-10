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
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Synced',
    );
    await expect(page.locator('#workout-editor')).not.toContainText(
      /revision/i,
    );
  });

  test('keeps set actions inline and last-set removal beside add set', async ({
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
    await expect(
      exercise.getByRole('button', { name: 'Remove set 1' }),
    ).toBeVisible();

    await exercise
      .getByRole('button', { name: 'Add set to Bench Press' })
      .click();
    const secondSet = exercise.getByRole('group', { name: 'Set 2' });
    await expect(secondSet).toBeVisible();
    await expect(
      firstSet.getByRole('button', { name: 'Edit set 1' }),
    ).toBeVisible();
    await expect(
      exercise.getByRole('button', { name: 'Remove set 2' }),
    ).toBeVisible();
    await expect(
      exercise.getByRole('button', { name: /Move set/ }),
    ).toHaveCount(0);

    await exercise.getByRole('button', { name: 'Remove set 2' }).click();
    await expect(exercise.getByRole('group', { name: 'Set 2' })).toHaveCount(0);
    await expect(
      exercise.getByRole('button', { name: 'Remove set 1' }),
    ).toBeVisible();
  });

  test('keeps field edits local until a set is completed', async ({ page }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    const exercise = await addExercise(page, 'Bench Press');
    const firstSet = exercise.getByRole('group', { name: 'Set 1' });

    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Synced',
    );
    await firstSet.getByLabel('Set 1 reps').fill('8');
    await firstSet.getByLabel('Set 1 weight in kilograms').fill('50');
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Not synced yet',
    );
    await page.waitForTimeout(400);
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Not synced yet',
    );

    await firstSet
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Synced',
    );
  });

  test('blocks finishing until every added set is completed', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    const finish = page.locator('#workout-finish-button');
    const blocker = page.locator('#workout-finish-blocker');

    // The label is text only; no icon is rendered inside the button.
    await expect(finish.locator('svg')).toHaveCount(0);
    await expect(finish).toBeDisabled();
    await expect(blocker).toContainText('Add at least one exercise');

    const exercise = await addExercise(page, 'Bench Press');
    await expect(finish).toBeDisabled();
    await expect(blocker).toContainText(
      'Finish or remove the 1 incomplete set',
    );

    const firstSet = exercise.getByRole('group', { name: 'Set 1' });
    await firstSet.getByLabel('Set 1 reps').fill('8');
    await firstSet.getByLabel('Set 1 weight in kilograms').fill('50');
    await expect(finish).toBeDisabled();
    await firstSet
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();
    await expect(blocker).toHaveCount(0);
    await expect(finish).toBeEnabled();
  });

  test('cancelling discards the session only after confirmation', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await addExercise(page, 'Bench Press');
    const editing = page.url();

    page.once('dialog', (dialog) => void dialog.dismiss());
    await page.locator('#workout-cancel-button').click();
    await expect(page).toHaveURL(editing);
    await expect(page.getByLabel('Bench Press editor')).toBeVisible();

    page.once('dialog', (dialog) => void dialog.accept());
    await page.locator('#workout-cancel-button').click();
    await expect(page).toHaveURL(/#\/$/);

    // A new session starts immediately, which the one-active-session rule
    // allows only because the discarded workout was deleted on the server.
    await page.getByRole('link', { name: 'Start workout session' }).click();
    await page.getByRole('button', { name: 'Freestyle session' }).click();
    await expect(
      page.getByRole('heading', { name: 'Active workout' }),
    ).toBeVisible();
    await expect(page.locator('#workout-editor')).not.toContainText(
      'Bench Press',
    );
  });

  test('reorders compact exercise cards by dragging the card itself', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    const benchPress = await addExercise(page, 'Bench Press');
    await benchPress.locator('[id^="workout-exercise-toggle-"]').click();
    const backSquat = await addExercise(page, 'Back Squat');
    await backSquat.locator('[id^="workout-exercise-toggle-"]').click();

    await benchPress.dragTo(page.getByLabel('Back Squat editor'));

    await expect(
      page.locator('#workout-editor > section').first(),
    ).toHaveAttribute('aria-label', 'Back Squat editor');
  });
});
