import { expect, test, type Page } from '@playwright/test';
import { gotoSignedIn } from './helpers';

async function startFreestyle(page: Page): Promise<string> {
  await page.getByRole('link', { name: 'Start workout session' }).click();
  await page.getByRole('button', { name: 'Freestyle session' }).click();
  await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+$/);
  const url = new URL(page.url());
  return url.hash.replace('#/workouts/', '');
}

async function addExercise(page: Page, name: string): Promise<void> {
  await page.locator('#workout-exercise-add-button').click();
  await page.getByLabel('Search').fill(name);
  await page
    .getByLabel('Exercise picker')
    .getByRole('button', { name: new RegExp(`^${name}`) })
    .first()
    .click();
  await expect(page.getByLabel(`${name} editor`)).toBeVisible();
}

/** Seed `count` finished bench-press workouts, one per day, via the API hook. */
async function seedFinishedBenchWorkouts(
  page: Page,
  count: number,
): Promise<void> {
  await page.evaluate(async (n) => {
    const api = (
      window as unknown as {
        __basefitApi: {
          createWorkout: (input: object) => Promise<{ revision: number }>;
          saveWorkout: (id: string, input: object) => Promise<unknown>;
        };
      }
    ).__basefitApi;
    for (let i = 0; i < n; i += 1) {
      const day = String(i + 1).padStart(2, '0');
      const started = `2026-01-${day}T10:00:00Z`;
      const ended = `2026-01-${day}T11:00:00Z`;
      const id = crypto.randomUUID();
      const created = await api.createWorkout({
        id,
        started_at: started,
        session_type: 'freestyle',
      });
      await api.saveWorkout(id, {
        revision: created.revision,
        save_id: crypto.randomUUID(),
        name: `Bench ${i + 1}`,
        notes: null,
        bodyweight_kg: null,
        ended_at: ended,
        exercises: [
          {
            id: crypto.randomUUID(),
            catalog_id: 'bench-press',
            notes: null,
            sets: [
              {
                id: crypto.randomUUID(),
                reps: 5,
                weight_kg: 40 + i,
                bw_percent_override: null,
                rpe: null,
                side: 'bilateral',
                done: true,
              },
            ],
          },
        ],
      });
    }
  }, count);
}

test.describe('exercise information screen', () => {
  test('info link is a read-only detour that preserves active-workout input', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await startFreestyle(page);
    await addExercise(page, 'Pull-up');

    const editor = page.getByLabel('Pull-up editor');
    const infoLink = editor.getByRole('link', { name: 'About Pull-up' });
    await expect(infoLink).toHaveAttribute('href', '#/exercises/pull-up');

    // Enter a local value; it stays unsynced ("Not synced yet").
    await editor.getByLabel('Set 1 reps').fill('7');
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Not synced yet',
    );

    // Track any workout write during the detour.
    const writes: string[] = [];
    page.on('request', (request) => {
      const url = request.url();
      if (
        /\/api\/v1\/workouts/.test(url) &&
        ['PUT', 'POST', 'DELETE'].includes(request.method())
      ) {
        writes.push(`${request.method()} ${url}`);
      }
    });

    await infoLink.click();
    await expect(page).toHaveURL(/#\/exercises\/pull-up$/);
    await expect(
      page.getByRole('heading', { level: 1, name: 'Pull-up' }),
    ).toBeVisible();

    // Return with browser Back; the local value and unsynced state survive.
    await page.goBack();
    await expect(page).toHaveURL(/#\/workouts\/[0-9a-f-]+$/);
    const returned = page.getByLabel('Pull-up editor');
    await returned.locator('button[id^="workout-exercise-toggle-"]').click();
    await expect(returned.getByLabel('Set 1 reps')).toHaveValue('7');
    await expect(page.locator('#workout-sync-status')).toHaveAttribute(
      'aria-label',
      'Not synced yet',
    );
    // No workout lifecycle or graph write was introduced by the detour.
    expect(writes).toEqual([]);
  });

  test('default detail renders guidance, sources, and animation', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await page.goto('/#/exercises/bench-press');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Bench Press' }),
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'How to perform' }),
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Form cues' }),
    ).toBeVisible();
    const source = page.getByRole('link', {
      name: /Squat, bench press, and deadlift mechanics/i,
    });
    await expect(source).toHaveAttribute(
      'href',
      'https://pmc.ncbi.nlm.nih.gov/articles/PMC12521083/',
    );
    // Two locally bundled frames, no third-party image request.
    const images = page.locator('.exercise-detail__animation img');
    await expect(images).toHaveCount(2);
    for (let i = 0; i < 2; i += 1) {
      const src = await images.nth(i).getAttribute('src');
      expect(src ?? '').toMatch(/^data:image\/svg/);
    }
    await expect(
      page.getByRole('button', { name: /movement animation/i }),
    ).toBeVisible();
  });

  test('bodyweight exercise never fabricates an estimated 1RM', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await page.goto('/#/exercises/pull-up');
    await expect(page.getByText('Your statistics')).toBeVisible();
    await expect(page.getByText('Unavailable for this exercise')).toBeVisible();
  });

  test('custom exercise shows its description and no media', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    const id = await page.evaluate(async () => {
      const api = (
        window as unknown as {
          __basefitApi: {
            createExercise: (input: object) => Promise<{ id: string }>;
          };
        }
      ).__basefitApi;
      const created = await api.createExercise({
        name: `E2E Detail Custom ${Date.now()}`,
        muscle_group: 'arms',
        load_type: 'single_weight',
        side_count: 1,
        description: 'Personal notes for my variation.',
      });
      return created.id;
    });
    await page.goto(`/#/exercises/${id}`);
    await expect(
      page.getByText('Personal notes for my variation.'),
    ).toBeVisible();
    await expect(page.locator('.exercise-detail__animation')).toHaveCount(0);
    await expect(page.locator('img')).toHaveCount(0);
    await expect(
      page.getByRole('heading', { name: 'How to perform' }),
    ).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Sources' })).toHaveCount(0);
  });

  test('chart shows exactly the latest twelve sessions oldest-to-newest', async ({
    page,
  }) => {
    await gotoSignedIn(page);
    await seedFinishedBenchWorkouts(page, 14);
    await page.goto('/#/exercises/bench-press');
    await expect(page.getByText('Your statistics')).toBeVisible();
    const chart = page.locator('.exercise-volume-chart');
    await expect(chart.locator('.exercise-volume-chart__bar')).toHaveCount(12);
    await expect(
      chart.getByText('Latest 12 finished sessions, oldest to newest'),
    ).toBeVisible();
    // Oldest emitted session is day 3 (days 1-2 are the two dropped); the
    // fixed-UTC value list exposes exact dates without hover.
    await expect(
      chart.getByRole('link', { name: '2026-01-03' }).first(),
    ).toBeVisible();
    await expect(
      chart.getByRole('link', { name: '2026-01-14' }).first(),
    ).toBeVisible();
  });
});
