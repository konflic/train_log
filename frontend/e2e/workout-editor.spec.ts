import { expect, test } from '@playwright/test';
import { E2E_PASSWORD, gotoApp, gotoSignedIn } from './helpers';

function workoutIdOf(url: string): string {
  return new URL(url).hash.split('/').at(-1)!.split('?')[0];
}

async function startFreestyle(
  page: import('@playwright/test').Page,
): Promise<void> {
  await page.getByRole('link', { name: 'Start workout session' }).click();
  await expect(
    page.getByRole('heading', { name: 'Choose session type' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Freestyle session' }).click();
  await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
}

async function addExercise(
  page: import('@playwright/test').Page,
  name: string,
): Promise<void> {
  await page.getByRole('button', { name: 'Add exercise' }).click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Choose an exercise' }),
  ).toBeVisible();
  await page.getByLabel('Search').fill(name);
  await page
    .getByLabel('Exercise picker')
    .getByRole('button', { name: new RegExp(`^${name}`) })
    .click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Active workout' }),
  ).toBeVisible();
}

async function expandExercise(
  page: import('@playwright/test').Page,
  name: string,
): Promise<void> {
  const summary = page
    .getByLabel(`${name} editor`)
    .getByRole('button', { name: new RegExp(`^${name}`) });
  if ((await summary.getAttribute('aria-expanded')) !== 'true') {
    await summary.click();
  }
}

async function workoutDetail(
  page: import('@playwright/test').Page,
  id: string,
) {
  return page.evaluate(async (workoutId) => {
    const hook = (
      window as unknown as {
        __basefitApi: {
          getWorkout(value: string): Promise<{
            name: string | null;
            ended_at: string | null;
            revision: number;
            exercises: Array<{
              sets: Array<{ reps: number | null; weight_kg: number | null }>;
            }>;
          }>;
        };
      }
    ).__basefitApi;
    return hook.getWorkout(workoutId);
  }, id);
}

async function deleteWorkout(
  page: import('@playwright/test').Page,
  id: string,
  revision: number,
): Promise<void> {
  await page.evaluate(
    async ({ workoutId, expectedRevision }) => {
      const hook = (
        window as unknown as {
          __basefitApi: {
            deleteWorkout(value: string, revision: number): Promise<void>;
          };
        }
      ).__basefitApi;
      await hook.deleteWorkout(workoutId, expectedRevision);
    },
    { workoutId: id, expectedRevision: revision },
  );
}

test.describe('synchronized workout editor', () => {
  test('opens the chooser without starting and then resumes the started session', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await page.getByRole('link', { name: 'Start workout session' }).click();
    await expect(
      page.getByRole('heading', { name: 'Choose session type' }),
    ).toBeVisible();
    const before = await page.evaluate(async () => {
      const response = await fetch('/api/v1/workouts?status=active');
      return (await response.json()).total;
    });
    expect(before).toBe(0);
    await page.getByRole('button', { name: 'Freestyle session' }).click();
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    const workoutId = workoutIdOf(page.url());

    await page.getByRole('link', { name: 'Home' }).click();
    await page.getByRole('link', { name: 'Resume active session' }).click();
    await expect(page).toHaveURL(new RegExp(`#/workouts/${workoutId}`));
  });

  test('keeps one session and removes the rejected start from local recovery', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    const second = await context.newPage();
    await gotoApp(second);
    await Promise.all(
      [page, second].map(async (current) => {
        await current
          .getByRole('link', { name: 'Start workout session' })
          .click();
        await expect(
          current.getByRole('heading', { name: 'Choose session type' }),
        ).toBeVisible();
      }),
    );

    await Promise.all(
      [page, second].map((current) =>
        current.getByRole('button', { name: 'Freestyle session' }).click(),
      ),
    );
    await expect
      .poll(
        () =>
          [page, second].filter((current) =>
            /#\/workouts\/[0-9a-f-]+\?draft=/.test(current.url()),
          ).length,
      )
      .toBe(1);
    const rejected = /\?draft=/.test(page.url()) ? second : page;
    await expect(rejected.getByRole('alert')).toContainText(
      'active workout session already exists',
    );

    const activeCount = await page.evaluate(async () => {
      const response = await fetch('/api/v1/workouts?status=active');
      return (await response.json()).total;
    });
    expect(activeCount).toBe(1);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            new Promise<{ drafts: number; creates: number }>(
              (resolve, reject) => {
                const request = indexedDB.open('basefit-drafts');
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                  const database = request.result;
                  const transaction = database.transaction(
                    ['drafts', 'pending_creates'],
                    'readonly',
                  );
                  const drafts = transaction.objectStore('drafts').count();
                  const creates = transaction
                    .objectStore('pending_creates')
                    .count();
                  transaction.oncomplete = () =>
                    resolve({ drafts: drafts.result, creates: creates.result });
                  transaction.onerror = () => reject(transaction.error);
                };
              },
            ),
        ),
      )
      .toEqual({ drafts: 1, creates: 0 });
  });

  test('creates a plan without starting and explicitly starts its copied graph', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await page.getByRole('link', { name: 'Start workout session' }).click();
    await page.getByRole('link', { name: 'Plan session' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Training plans' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Create plan' }).click();
    await page.getByLabel('Name').fill('Arms plan');
    await page.getByRole('button', { name: 'Add exercise' }).click();
    await page
      .getByLabel('Exercise 1')
      .selectOption({ label: 'Dumbbell Curl' });
    await page.getByLabel('Target reps').fill('8');
    await page.getByLabel('Target kg').fill('12');
    await page.getByRole('button', { name: 'Save plan' }).click();

    const beforeStart = await page.evaluate(async () => {
      const response = await fetch('/api/v1/workouts?status=active');
      return (await response.json()).total;
    });
    expect(beforeStart).toBe(0);

    const plan = page.getByRole('listitem').filter({ hasText: 'Arms plan' });
    await plan.getByRole('button', { name: 'Start session' }).click();
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    await expandExercise(page, 'Dumbbell Curl');
    const exercise = page.getByLabel('Dumbbell Curl editor');
    await expect(exercise.getByLabel('Reps')).toHaveValue('8');
    await expect(exercise.getByLabel('Weight (kg)')).toHaveValue('12');
    await expect(
      exercise.getByRole('button', { name: 'Mark set 1 completed' }),
    ).toBeVisible();
  });

  test('starts freestyle, autosaves a graph, and recovers its acknowledged draft', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    let putCount = 0;
    await page.route('**/api/v1/workouts/**', async (route) => {
      if (route.request().method() === 'PUT') putCount += 1;
      await route.continue();
    });

    await startFreestyle(page);
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Active workout' }),
    ).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 0',
    );

    await page.getByRole('button', { name: 'Add exercise' }).click();
    await expect(page).toHaveURL(/picker=exercise/);
    await page.goBack();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Active workout' }),
    ).toBeVisible();
    await addExercise(page, 'Bench Press');
    const exercise = page.getByLabel('Bench Press editor');
    await expect(exercise.getByLabel('RPE')).toHaveCount(0);
    page.once('dialog', (dialog) => dialog.dismiss());
    await exercise.getByRole('button', { name: 'Remove Bench Press' }).click();
    await expect(exercise).toBeVisible();
    await exercise.getByLabel('Reps').fill('8');
    await exercise
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();
    await expect(exercise.getByRole('alert')).toContainText(
      'A completed weighted set needs a weight.',
    );
    await expect(
      exercise.getByRole('button', { name: 'Mark set 1 completed' }),
    ).toBeVisible();
    await exercise.getByLabel('Weight (kg)').fill('50');
    await exercise
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();
    await expect(
      exercise.getByRole('button', { name: 'Edit set 1' }),
    ).toBeVisible();
    await expect(exercise.getByLabel('Reps')).toBeDisabled();
    await expect(
      page.getByText('400 kg·reps from 1 completed set.'),
    ).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 1',
    );

    await exercise.getByRole('button', { name: 'Add set' }).click();
    await expect(exercise.getByRole('group', { name: 'Set 2' })).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 2',
    );
    await page.reload();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Active workout' }),
    ).toBeVisible();
    await expandExercise(page, 'Bench Press');
    await expect(
      page.getByRole('group', { name: 'Set 1' }).getByLabel('Weight (kg)'),
    ).toHaveValue('50');
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 2',
    );
    expect(putCount).toBe(2);
    await exercise.getByRole('button', { name: 'Edit set 1' }).click();
    await expect(
      exercise.getByRole('group', { name: 'Set 1' }).getByLabel('Reps'),
    ).toBeEnabled();
  });

  test('finishes the latest locally saved graph in one final PUT', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await addExercise(page, 'Bench Press');
    const exercise = page.getByLabel('Bench Press editor');
    await exercise.getByLabel('Reps').fill('6');
    await exercise.getByLabel('Weight (kg)').fill('70');
    await exercise
      .getByRole('button', { name: 'Mark set 1 completed' })
      .click();

    const finish = page.getByRole('button', { name: 'Finish workout' });
    await expect(finish).toBeEnabled();
    await finish.click();

    await expect(
      page.getByRole('heading', { level: 1, name: 'Finished workout' }),
    ).toBeVisible();
    const workoutId = workoutIdOf(page.url());
    const detail = await workoutDetail(page, workoutId);
    expect(detail.ended_at).not.toBeNull();
    expect(detail.revision).toBe(1);
    expect(detail.exercises[0].sets[0]).toMatchObject({
      reps: 6,
      weight_kg: 70,
    });
  });

  test('does not let a delayed save overwrite a newer edit', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    let releaseFirstPut!: () => void;
    let markPutStarted!: () => void;
    const firstPutStarted = new Promise<void>((resolve) => {
      markPutStarted = resolve;
    });
    const firstPutGate = new Promise<void>((resolve) => {
      releaseFirstPut = resolve;
    });
    let putCount = 0;
    await page.route('**/api/v1/workouts/**', async (route) => {
      if (route.request().method() === 'PUT') {
        putCount += 1;
        if (putCount === 1) {
          markPutStarted();
          await firstPutGate;
        }
      }
      await route.continue();
    });

    await startFreestyle(page);
    await addExercise(page, 'Bench Press');
    const weight = page
      .getByLabel('Bench Press editor')
      .getByLabel('Weight (kg)');
    await weight.fill('40');
    await firstPutStarted;
    await expect(
      page.getByRole('button', { name: 'Finish workout' }),
    ).toBeDisabled();
    await weight.fill('45');
    releaseFirstPut();

    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 2',
    );
    await expect(weight).toHaveValue('45');
    const detail = await workoutDetail(page, workoutIdOf(page.url()));
    expect(detail.exercises[0].sets[0].weight_kg).toBe(45);
  });

  test('retries an exact save after losing its committed response', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    const saveIds: string[] = [];
    let loseFirstResponse = true;
    await page.route('**/api/v1/workouts/**', async (route) => {
      if (route.request().method() !== 'PUT') {
        await route.continue();
        return;
      }
      const payload = route.request().postDataJSON() as { save_id: string };
      saveIds.push(payload.save_id);
      if (loseFirstResponse) {
        loseFirstResponse = false;
        await route.fetch();
        await route.fulfill({
          status: 503,
          contentType: 'application/problem+json',
          body: JSON.stringify({
            type: 'about:blank',
            title: 'Service Unavailable',
            status: 503,
            detail: 'Response was lost after commit',
            code: 'retryable',
          }),
        });
      } else {
        await route.continue();
      }
    });

    await startFreestyle(page);
    await page.getByLabel('Workout name').fill('Exact retry');
    await expect(page.getByRole('status')).toContainText('Offline');
    await page.getByRole('button', { name: 'Save now' }).click();

    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 1',
    );
    expect(saveIds).toHaveLength(2);
    expect(saveIds[1]).toBe(saveIds[0]);
    expect((await workoutDetail(page, workoutIdOf(page.url()))).revision).toBe(
      1,
    );
  });

  test('keeps an exact finish pending after response loss until durable retry', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    const finishSaveIds: string[] = [];
    let loseFinishResponse = true;
    await page.route('**/api/v1/workouts/**', async (route) => {
      if (route.request().method() !== 'PUT') {
        await route.continue();
        return;
      }
      const payload = route.request().postDataJSON() as {
        save_id: string;
        ended_at: string | null;
      };
      if (payload.ended_at === null) {
        await route.continue();
        return;
      }
      finishSaveIds.push(payload.save_id);
      if (loseFinishResponse) {
        loseFinishResponse = false;
        await route.fetch();
        await route.abort('failed');
      } else {
        await route.continue();
      }
    });

    await startFreestyle(page);
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 0',
    );
    await page.getByLabel('Workout name').fill('Finish receipt');
    const finish = page.getByRole('button', { name: 'Finish workout' });
    await expect(finish).toBeEnabled();
    await finish.click();

    await expect(page.getByRole('status')).toContainText('Finish pending');
    await expect(page.getByLabel('Workout name')).toBeDisabled();
    await page.getByRole('button', { name: 'Retry synchronization' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'Finished workout' }),
    ).toBeVisible();
    expect(finishSaveIds).toHaveLength(2);
    expect(finishSaveIds[1]).toBe(finishSaveIds[0]);
    expect((await workoutDetail(page, workoutIdOf(page.url()))).revision).toBe(
      1,
    );
  });

  test('reauthenticates in place and resumes the retained pending save', async ({
    page,
    context,
  }) => {
    const email = await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 0',
    );
    await context.clearCookies();

    await page.getByLabel('Workout name').fill('Retained draft');
    await expect(
      page.getByRole('heading', { name: 'Authentication required', level: 2 }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Sign in again' }).click();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Sign in and resume' }).click();

    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 1',
    );
    await expect(page.getByLabel('Workout name')).toHaveValue('Retained draft');
  });

  test('recovers an offline edit after shell reload and reconnects pending work', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 0',
    );
    await page.route('**/api/v1/**', (route) => route.abort('failed'));

    await page.getByLabel('Workout name').fill('Offline edit');
    await expect(page.getByRole('status')).toContainText('Offline');
    await page.reload();
    await page
      .getByRole('button', { name: 'Recover local drafts only' })
      .click();
    await page
      .getByRole('button', { name: 'Recover this draft' })
      .first()
      .click();
    await expect(page.getByLabel('Workout name')).toHaveValue('Offline edit');

    await page.unroute('**/api/v1/**');
    await page.reload();
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 1',
    );
    await expect(page.getByLabel('Workout name')).toHaveValue('Offline edit');
  });

  test('pauses a stale second tab and retains both local drafts', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 0',
    );
    const workoutId = workoutIdOf(page.url());

    const second = await context.newPage();
    await gotoApp(second);
    await second.goto(`/#/workouts/${workoutId}`);
    await second.getByRole('button', { name: 'Recover this draft' }).click();
    await expect(second.getByRole('status')).toContainText(
      'Synced at revision 0',
    );

    await page.getByLabel('Workout name').fill('First tab');
    await expect(page.getByRole('status')).toContainText(
      'Synced at revision 1',
    );
    await second.getByLabel('Workout name').fill('Second tab retained');
    await expect(second.getByRole('status')).toContainText('Conflict');
    await expect(second.getByLabel('Workout name')).toHaveValue(
      'Second tab retained',
    );
    await expect(
      second.getByRole('heading', { name: 'Choose what to keep', level: 2 }),
    ).toBeVisible();
    await expect(second.getByLabel('Choose what to keep')).toContainText(
      'Server copy: revision 1, active.',
    );
    second.once('dialog', (dialog) => dialog.accept());
    await second.getByRole('button', { name: 'Use server version' }).click();
    await expect(second.getByRole('status')).toContainText(
      'Synced at revision 1',
    );
    await expect(second.getByLabel('Workout name')).toHaveValue('First tab');

    await second.reload();
    await expect(
      second.getByRole('heading', { name: 'Choose a local draft', level: 1 }),
    ).toBeVisible();
    await expect(
      second.getByRole('button', { name: 'Recover this draft' }),
    ).toHaveCount(2);
  });

  test('explicitly replaces the fresh server revision after a two-tab conflict', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    const workoutId = workoutIdOf(page.url());
    const second = await context.newPage();
    await gotoApp(second);
    await second.goto(`/#/workouts/${workoutId}`);
    await second.getByRole('button', { name: 'Recover this draft' }).click();

    await page.getByLabel('Workout name').fill('Server winner');
    await expect(page.getByRole('status')).toContainText('revision 1');
    await second.getByLabel('Workout name').fill('Local replacement');
    await expect(second.getByRole('status')).toContainText('Conflict');
    await expect(
      second.getByRole('button', { name: 'Replace server version' }),
    ).toBeVisible();
    second.once('dialog', (dialog) => dialog.accept());
    await second
      .getByRole('button', { name: 'Replace server version' })
      .click();

    await expect(second.getByRole('status')).toContainText('revision 2');
    expect((await workoutDetail(second, workoutId)).name).toBe(
      'Local replacement',
    );
  });

  test('does not copy conflict work while the account has an active session', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    const sourceId = workoutIdOf(page.url());
    const second = await context.newPage();
    await gotoApp(second);
    await second.goto(`/#/workouts/${sourceId}`);
    await second.getByRole('button', { name: 'Recover this draft' }).click();

    await page.getByLabel('Workout name').fill('Server version');
    await expect(page.getByRole('status')).toContainText('revision 1');
    await second.getByLabel('Workout name').fill('Preserved local version');
    await expect(second.getByRole('status')).toContainText('Conflict');
    await expect(
      second.getByRole('button', { name: 'Copy local work to new workout' }),
    ).toHaveCount(0);
    await expect(second.getByLabel('Choose what to keep')).toContainText(
      'Finish or discard the active server session',
    );
    await expect(second.getByLabel('Workout name')).toHaveValue(
      'Preserved local version',
    );
    expect((await workoutDetail(second, sourceId)).name).toBe('Server version');
    const activeCount = await second.evaluate(async () => {
      const response = await fetch('/api/v1/workouts?status=active');
      return (await response.json()).total;
    });
    expect(activeCount).toBe(1);
  });

  test('offers only copy or discard after the server workout is deleted', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    const workoutId = workoutIdOf(page.url());
    const second = await context.newPage();
    await gotoApp(second);
    await second.goto(`/#/workouts/${workoutId}`);
    await second.getByRole('button', { name: 'Recover this draft' }).click();
    await expect(second.getByLabel('Workout name')).toBeEnabled();

    await deleteWorkout(page, workoutId, 0);
    await second.getByLabel('Workout name').fill('Deleted server copy');
    await expect(second.getByRole('status')).toContainText('Conflict');
    await expect(second.getByLabel('Choose what to keep')).toContainText(
      'The server workout was deleted.',
    );
    await expect(
      second.getByRole('button', { name: 'Copy local work to new workout' }),
    ).toBeVisible();
    await expect(
      second.getByRole('button', { name: 'Discard local copy' }),
    ).toBeVisible();
    await expect(
      second.getByRole('button', { name: 'Use server version' }),
    ).toHaveCount(0);
    await expect(
      second.getByRole('button', { name: 'Replace server version' }),
    ).toHaveCount(0);

    second.once('dialog', (dialog) => dialog.accept());
    await second.getByRole('button', { name: 'Discard local copy' }).click();
    await expect(second).toHaveURL(/#\/$/);
  });

  test('does not offer replacement when another tab finished the workout', async ({
    page,
    context,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+\?draft=/);
    const workoutId = workoutIdOf(page.url());
    const second = await context.newPage();
    await gotoApp(second);
    await second.goto(`/#/workouts/${workoutId}`);
    await second.getByRole('button', { name: 'Recover this draft' }).click();

    await page.getByRole('button', { name: 'Finish workout' }).click();
    await expect(
      page.getByRole('heading', { name: 'Finished workout', level: 1 }),
    ).toBeVisible();
    await second.getByLabel('Workout name').fill('Retained after finish');
    await expect(second.getByRole('status')).toContainText('Conflict');
    await expect(second.getByLabel('Choose what to keep')).toContainText(
      'Server copy: revision 1, finished.',
    );
    await expect(
      second.getByRole('button', { name: 'Use server version' }),
    ).toBeVisible();
    await expect(
      second.getByRole('button', { name: 'Copy local work to new workout' }),
    ).toBeVisible();
    await expect(
      second.getByRole('button', { name: 'Replace server version' }),
    ).toHaveCount(0);
  });
});
