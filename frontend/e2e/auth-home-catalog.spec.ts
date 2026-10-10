import { expect, test, type Page } from '@playwright/test';
import {
  E2E_PASSWORD,
  gotoApp,
  gotoSignedIn,
  registerThroughApi,
  uniqueEmail,
} from './helpers';

test.describe('authentication flow', () => {
  test('create-account form fits a mobile viewport without horizontal overflow', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await gotoApp(page);
    await page.getByRole('link', { name: 'Create one' }).click();

    const form = page.locator('#register-form');
    await expect(form).toBeVisible();
    const bounds = await form.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(375);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });

  test('anonymous catalog visit leads to login and returns after sign-in', async ({
    page,
  }) => {
    await page.goto('/#/catalog');
    await expect(page).toHaveURL(/#\/login/);

    // Register through the UI.
    await page.getByRole('link', { name: 'Create one' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Create account' }),
    ).toBeVisible();
    const email = uniqueEmail();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByLabel(/Display name/).fill('E2E Tester');
    await page.getByLabel('Initial weight (kg)').fill('75');
    await page.getByLabel('Sex').selectOption('male');
    await page.getByLabel('Age').fill('31');
    await page.getByRole('button', { name: 'Create account' }).click();

    // Registration does not imply a session.
    await expect(page.getByRole('status')).toContainText('Account created');
    await page.getByRole('button', { name: 'Continue to log in' }).click();
    await expect(page).toHaveURL(/#\/login/);
    await expect(page.getByLabel('Email')).toHaveValue(email);

    // Explicit login returns to the intended route.
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page).toHaveURL(/#\/catalog/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Catalog' }),
    ).toBeVisible();
    await expect(
      page.getByRole('navigation', { name: 'Primary' }),
    ).toBeVisible();
  });

  test('invalid credentials stay a generic form error, valid ones sign in', async ({
    page,
  }) => {
    await gotoApp(page);
    const email = await registerThroughApi(page);
    await page.reload();
    await expect(page).toHaveURL(/#\/login/);

    // Exactly one failed attempt: the shared-IP login throttle is bounded.
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill('definitely-wrong-password');
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('alert')).toContainText(
      'Invalid email or password',
    );
    await expect(page).toHaveURL(/#\/login/);

    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();
    await expect(page).toHaveURL(/#\/$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Home' }),
    ).toBeVisible();
    await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();
  });

  test('registering a duplicate email surfaces the conflict', async ({
    page,
  }) => {
    await gotoApp(page);
    const email = await registerThroughApi(page);
    await page.reload();
    await page.getByRole('link', { name: 'Create one' }).click();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByLabel('Initial weight (kg)').fill('75');
    await page.getByLabel('Sex').selectOption('female');
    await page.getByLabel('Age').fill('31');
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByRole('alert')).toContainText('already exists');
  });
});

test.describe('read-only home', () => {
  test('a new account sees empty panels and zeroed summary stats', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Home' }),
    ).toBeVisible();

    await expect(page.getByText(/No finished workouts yet/)).toBeVisible();

    const summary = page.getByRole('region', { name: 'Summary' });
    await expect(summary).toContainText('Workouts');
    await expect(summary).toContainText('Completed sets');
    await expect(summary).toContainText('Training days');
    await expect(summary).toContainText('kg·reps');
    await expect(summary).toContainText('Current streak:');
    await expect(summary).toContainText('(full history)');
    // Inclusive local Monday-Sunday range at the account's fixed offset (0).
    await expect(summary).toContainText(
      /\d{4}-\d{2}-\d{2} – \d{4}-\d{2}-\d{2} \(UTC\+0\)/,
    );

    await summary.getByRole('tab', { name: 'Month' }).click();
    await expect(summary).toContainText(
      /\d{4}-\d{2}-01 – \d{4}-\d{2}-\d{2} \(UTC\+0\)/,
    );
    await summary.getByRole('tab', { name: 'Total' }).click();
    await expect(summary).toContainText('Full history');
    await summary.getByRole('tab', { name: 'Week' }).click();
    await expect(summary).toContainText(
      /\d{4}-\d{2}-\d{2} – \d{4}-\d{2}-\d{2} \(UTC\+0\)/,
    );

    await expect(
      page.getByRole('link', { name: 'Start workout session' }),
    ).toBeVisible();
    await expect(page.getByRole('main')).not.toContainText(
      'Quick start workout',
    );
  });
});

test.describe('catalog management', () => {
  test('browse, search, filter, page, create, and edit custom entries', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await page.getByRole('link', { name: 'Catalog' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Catalog' }),
    ).toBeVisible();

    // Seeded defaults browse with stable paging (26 defaults, page size 10).
    await expect(page.getByText('26 exercises · page 1 of 3')).toBeVisible();
    await expect(page.getByText('Bench Press')).toBeVisible();
    await expect(page.getByText('Back Squat')).toBeVisible();
    const defaults = page.getByText('Default', { exact: true });
    await expect(defaults).toHaveCount(10);
    // Default entries have no edit action.
    await expect(page.getByRole('button', { name: /^Edit/ })).toHaveCount(0);

    // Enum values render through human-readable labels.
    await expect(page.getByText(/Single weight/).first()).toBeVisible();

    // Stable ordering: page 2 continues the casefolded name order.
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('26 exercises · page 2 of 3')).toBeVisible();
    await expect(page.getByText('Dumbbell Curl')).toBeVisible();
    await expect(page.getByText('Overhead Press')).toBeVisible();
    await page.getByRole('button', { name: 'Previous' }).click();
    await expect(page.getByText('26 exercises · page 1 of 3')).toBeVisible();

    // Search narrows to matching names (URL state, debounced).
    await page.getByLabel('Search').fill('dumb');
    await expect(page.getByText('Dumbbell Curl')).toBeVisible();
    await expect(page.getByText('Bench Press')).toHaveCount(0);
    await expect(page).toHaveURL(/search=dumb/);
    await page.getByLabel('Search').fill('');
    await expect(page.getByText('Bench Press')).toBeVisible();

    // Muscle-group filter keeps exact API literals behind readable labels.
    await page.getByLabel('Muscle group').selectOption('back');
    await expect(page.getByText('5 exercises · page 1 of 1')).toBeVisible();
    await expect(page.getByText('Barbell Row')).toBeVisible();
    await expect(page.getByText('Deadlift')).toBeVisible();
    await expect(page.getByText('Lat Pulldown')).toBeVisible();
    await expect(page.getByText('Pull-up')).toBeVisible();
    await expect(page.getByText('Back Extension')).toBeVisible();
    await expect(page).toHaveURL(/muscle_group=back/);
    await page.getByLabel('Muscle group').selectOption('');
    await expect(page.getByText('26 exercises · page 1 of 3')).toBeVisible();

    // Create a custom split-weight entry.
    const customName = `E2E Custom Curl ${Date.now()}`;
    await page.getByRole('button', { name: 'New custom exercise' }).click();
    const form = page.getByRole('region', { name: 'New custom exercise' });
    await form.getByLabel('Name').fill(customName);
    await form.getByLabel('Muscle group').selectOption('arms');
    await form.getByLabel('Load type').selectOption('split_weight');
    await form.getByLabel('Sides').selectOption('2');
    await form.getByRole('button', { name: 'Create exercise' }).click();

    await expect(form).toHaveCount(0);
    const customRow = page.locator('li', { hasText: customName });
    await expect(customRow).toBeVisible();
    await expect(customRow.getByText('Custom', { exact: true })).toBeVisible();
    await expect(
      customRow.getByText(/Split weight \(per side\) · both sides per set/),
    ).toBeVisible();

    // Client-side validation blocks an invalid create before any request.
    await page.getByRole('button', { name: 'New custom exercise' }).click();
    const invalidForm = page.getByRole('region', {
      name: 'New custom exercise',
    });
    await invalidForm.getByLabel('Name').fill('Bad Fraction');
    await invalidForm.getByLabel(/Bodyweight percentage/).fill('12.5');
    await invalidForm.getByRole('button', { name: 'Create exercise' }).click();
    await expect(
      invalidForm.getByText('Percentage must be a whole number from 1 to 100'),
    ).toBeVisible();
    await invalidForm.getByRole('button', { name: 'Cancel' }).click();

    // Editing a custom entry starts from its current values and saves.
    await page.getByRole('button', { name: `Edit ${customName}` }).click();
    const editForm = page.getByRole('region', { name: `Edit ${customName}` });
    await expect(editForm.getByLabel('Name')).toHaveValue(customName);
    await expect(editForm.getByLabel('Sides')).toHaveValue('2');
    const renamed = `${customName} v2`;
    await editForm.getByLabel('Name').fill(renamed);
    await editForm.getByRole('button', { name: 'Save changes' }).click();
    await expect(page.locator('li', { hasText: renamed })).toBeVisible();

    // The backend stays authoritative for duplicate names.
    await page.getByRole('button', { name: 'New custom exercise' }).click();
    const duplicateForm = page.getByRole('region', {
      name: 'New custom exercise',
    });
    await duplicateForm.getByLabel('Name').fill(renamed);
    await duplicateForm
      .getByRole('button', { name: 'Create exercise' })
      .click();
    await expect(duplicateForm.getByRole('alert')).toContainText(
      'already exists',
    );
  });

  test('search resets paging to the first page', async ({ page }) => {
    await gotoSignedIn(page);
    await page.getByRole('link', { name: 'Catalog' }).click();
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page).toHaveURL(/page=2/);
    await page.getByLabel('Search').fill('squat');
    await expect(page).not.toHaveURL(/page=/);
    await expect(page.getByText('Back Squat')).toBeVisible();
  });
});

/** Keep a stable authenticated Home for assertions shared across tests. */
async function expectHome(page: Page): Promise<void> {
  await expect(
    page.getByRole('heading', { level: 1, name: 'Home' }),
  ).toBeVisible();
}

test('authenticated navigation keeps the session across reloads', async ({
  page,
}) => {
  const email = await gotoSignedIn(page);
  await expectHome(page);
  await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();
  await page.reload();
  await expectHome(page);
  await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();
  // No test touched the database directly or used a reset endpoint; the
  // session lives only in the HttpOnly cookie.
  const cookies = await page.context().cookies();
  const sessionCookie = cookies.find(
    (cookie) => cookie.name === 'basefit_session',
  );
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe('Strict');
});
