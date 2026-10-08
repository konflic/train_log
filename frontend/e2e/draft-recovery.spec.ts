import { expect, test, type Page } from '@playwright/test';
import { gotoApp, signInThroughApi } from './helpers';
import type { WorkoutDraft } from '../src/db';

async function editorValue(page: Page): Promise<WorkoutDraft> {
  return JSON.parse(
    (await page.getByTestId('editor-value').textContent())!,
  ) as WorkoutDraft;
}

async function gotoHarness(page: Page): Promise<void> {
  // The query string forces a document navigation from the normal app, while
  // the hash remains the explicit test-only harness route.
  await page.goto('/?draftHarness=1#/draft-harness');
  await expect(
    page.getByRole('heading', { level: 1, name: 'Draft recovery harness' }),
  ).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Select a saved draft');
}

async function signedInHarness(page: Page): Promise<void> {
  await gotoApp(page);
  await signInThroughApi(page);
  await gotoHarness(page);
}

async function createSource(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Create recovery source' }).click();
  await expect(page.getByRole('status')).toContainText('Draft saved');
  const source = page.locator('[data-testid^="draft-"]').first();
  await expect(source).toBeVisible();
  return (await source.getAttribute('data-testid'))!.replace('draft-', '');
}

async function recover(page: Page, draftId: string): Promise<string> {
  await page.getByRole('button', { name: `Recover draft ${draftId}` }).click();
  const editor = page.getByTestId('editing-draft-id');
  await expect(editor).toBeVisible();
  return (await editor.textContent())!.replace('Editing draft ', '');
}

test.describe('IndexedDB draft recovery harness', () => {
  test('persists raw invalid form text and snapshots through a reload and explicit recovery', async ({
    page,
  }) => {
    await signedInHarness(page);
    const sourceId = await createSource(page);
    const editorId = await recover(page, sourceId);

    await page.getByLabel('Raw weight text').fill('12.5');
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 1',
    );
    const savedValue = await editorValue(page);
    expect(
      savedValue.content.recorded_load_snapshots['sample-exercise'].side_count,
    ).toBe(2);

    await page.reload();
    await expect(page.getByRole('status')).toContainText(
      'Select a saved draft',
    );
    await expect(page.getByTestId(`draft-${editorId}`)).toBeVisible();
    // Recovery always makes a new editable record, preserving its source.
    const reloadedEditorId = await recover(page, editorId);
    expect(reloadedEditorId).not.toBe(editorId);
    await expect(page.getByLabel('Raw weight text')).toHaveValue('12.5');
    expect((await editorValue(page)).content).toEqual(savedValue.content);
    expect((await editorValue(page)).base_revision).toBe(
      savedValue.base_revision,
    );
    await expect(page.getByTestId(`draft-${sourceId}`)).toBeVisible();
  });

  test('keeps two tab drafts distinct when both explicitly recover the same source', async ({
    page,
  }) => {
    await signedInHarness(page);
    const sourceId = await createSource(page);
    const initialDocumentId = await page
      .getByTestId('document-editor-id')
      .textContent();

    const popupPromise = page.waitForEvent('popup');
    await page.evaluate(() =>
      sessionStorage.setItem('duplicate-marker', 'cloned-context'),
    );
    await page.evaluate(() => window.open('/?draftHarness=1#/draft-harness'));
    const secondTab = await popupPromise;
    expect(
      await secondTab.evaluate(() =>
        sessionStorage.getItem('duplicate-marker'),
      ),
    ).toBe('cloned-context');
    await expect(
      secondTab.getByRole('heading', {
        level: 1,
        name: 'Draft recovery harness',
      }),
    ).toBeVisible();
    await expect(secondTab.getByRole('status')).toContainText(
      'Select a saved draft',
    );
    expect(
      await secondTab.getByTestId('document-editor-id').textContent(),
    ).not.toBe(initialDocumentId);

    const firstEditorId = await recover(page, sourceId);
    const secondEditorId = await recover(secondTab, sourceId);
    expect(firstEditorId).not.toBe(secondEditorId);
    await page.getByLabel('Raw weight text').fill('10');
    await secondTab.getByLabel('Raw weight text').fill('20');
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 1',
    );
    await expect(secondTab.getByRole('status')).toContainText(
      'Locally saved change 1',
    );

    await page.reload();
    await expect(page.getByTestId(`draft-${sourceId}`)).toBeVisible();
    await expect(page.getByTestId(`draft-${firstEditorId}`)).toBeVisible();
    await expect(page.getByTestId(`draft-${secondEditorId}`)).toBeVisible();
    await recover(page, firstEditorId);
    await expect(page.getByLabel('Raw weight text')).toHaveValue('10');
    await secondTab.reload();
    await recover(secondTab, secondEditorId);
    await expect(secondTab.getByLabel('Raw weight text')).toHaveValue('20');
  });

  test('does not acknowledge an aborted local write and hides another account records', async ({
    page,
  }) => {
    await signedInHarness(page);
    const sourceId = await createSource(page);
    await recover(page, sourceId);
    await page.getByRole('button', { name: 'Fail next local write' }).click();
    await page.getByLabel('Raw weight text').fill('77');
    await expect(page.getByRole('status')).toContainText('Storage failed');
    await expect(page.getByRole('status')).not.toContainText('Locally saved');
    await page.getByRole('button', { name: 'Retry local edit' }).click();
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 1',
    );

    await gotoApp(page);
    await signInThroughApi(page);
    await gotoHarness(page);
    await expect(
      page.getByText('No drafts for this account and workout.'),
    ).toBeVisible();
  });

  test('recovers an available shell offline without authorizing network work', async ({
    page,
  }) => {
    await signedInHarness(page);
    const source = await createSource(page);
    const edited = await recover(page, source);
    await page.getByLabel('Raw weight text').fill('');
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 1',
    );
    const saved = await editorValue(page);
    let apiRequests = 0;
    await page.route('**/api/**', (route) => {
      apiRequests += 1;
      return route.abort();
    });
    await page.reload();
    await expect(
      page.getByRole('heading', { name: 'Cannot reach the server' }),
    ).toBeVisible();
    await expect(page.getByTestId(`draft-${edited}`)).toHaveCount(0);
    await page
      .getByRole('button', { name: 'Recover local drafts only' })
      .click();
    await recover(page, edited);
    await expect(page.getByLabel('Raw weight text')).toHaveValue('');
    expect((await editorValue(page)).content).toEqual(saved.content);
    await expect(
      page.getByRole('button', { name: 'Create recovery source' }),
    ).toHaveCount(0);
    expect(apiRequests).toBe(1);
  });

  test('keeps newer input unsaved until its own transaction commits', async ({
    page,
  }) => {
    await signedInHarness(page);
    const source = await createSource(page);
    const edited = await recover(page, source);
    await page.getByRole('button', { name: 'Hold next local write' }).click();
    await page.getByLabel('Raw weight text').fill('1');
    await page.getByLabel('Raw weight text').fill('123');
    await expect(page.getByRole('status')).toHaveText('Saving locally…');
    expect((await editorValue(page)).change_number).toBe(2);
    await page.getByRole('button', { name: 'Release local write' }).click();
    await expect(page.getByRole('status')).toContainText(
      'Locally saved change 2',
    );
    await page.reload();
    await recover(page, edited);
    await expect(page.getByLabel('Raw weight text')).toHaveValue('123');
  });

  test('durably creates, saves, and finishes the prepared graph', async ({
    page,
  }) => {
    await signedInHarness(page);
    await page.getByRole('button', { name: 'Start durable create' }).click();
    await expect(page.getByTestId('editing-draft-id')).toBeVisible();
    const created = await editorValue(page);
    expect(created.base_revision).toBe(0);

    await page.getByRole('button', { name: 'Send durable save' }).click();
    await expect
      .poll(async () => (await editorValue(page)).base_revision)
      .toBe(1);
    await page.getByRole('button', { name: 'Send durable finish' }).click();
    await expect
      .poll(async () => (await editorValue(page)).base_revision)
      .toBe(2);

    const server = await page.evaluate(async (workoutId) => {
      const response = await fetch(`/api/v1/workouts/${workoutId}`);
      return response.json() as Promise<{
        revision: number;
        ended_at: string | null;
        exercises: Array<{ sets: unknown[] }>;
      }>;
    }, created.workout_id);
    expect(server).toMatchObject({ revision: 2, ended_at: expect.any(String) });
    expect(server.exercises[0].sets).toHaveLength(1);
  });

  test('a different confirmed account in another tab revokes offline recovery', async ({
    page,
  }) => {
    await signedInHarness(page);
    const source = await createSource(page);
    await page.route('**/api/**', (route) => route.abort());
    await page.reload();
    await page
      .getByRole('button', { name: 'Recover local drafts only' })
      .click();
    await expect(page.getByTestId(`draft-${source}`)).toBeVisible();
    const other = await page.context().newPage();
    await gotoApp(other);
    await signInThroughApi(other);
    await other.reload();
    await expect(
      other.getByRole('heading', { name: 'Home', exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId(`draft-${source}`)).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Recover local drafts only' }),
    ).toHaveCount(0);
    await page.reload();
    await expect(
      page.getByRole('heading', { name: 'Cannot reach the server' }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Recover local drafts only' }),
    ).toHaveCount(0);
  });

  test('bounds recovery pages and exposes malformed nested graphs', async ({
    page,
  }) => {
    await signedInHarness(page);
    await createSource(page);
    await page.evaluate(async () => {
      await new Promise<void>((resolve, reject) => {
        const opening = indexedDB.open('basefit-drafts');
        opening.onerror = () => reject(opening.error);
        opening.onsuccess = () => {
          const db = opening.result;
          const tx = db.transaction('drafts', 'readwrite');
          tx.oncomplete = () => {
            db.close();
            resolve();
          };
          tx.onabort = () => {
            db.close();
            reject(tx.error);
          };
          const store = tx.objectStore('drafts');
          store.getAll().onsuccess = (event) => {
            const sample = (event.target as IDBRequest<WorkoutDraft[]>)
              .result[0];
            for (let index = 0; index < 120; index += 1) {
              store.put({
                ...sample,
                draft_id: `page-${String(index).padStart(3, '0')}`,
              });
            }
            store.put({
              ...sample,
              draft_id: '000-malformed',
              content: { ...sample.content, exercises: [{ id: 'bad' }] },
            });
          };
        };
      });
    });
    await page.reload();
    await expect(page.getByRole('alert')).toContainText(
      '1 malformed saved draft',
    );
    await expect(page.locator('[data-testid^="draft-"]')).toHaveCount(99);
    await page.getByRole('button', { name: 'Next recovery page' }).click();
    await expect(page.locator('[data-testid^="draft-"]')).toHaveCount(22);
    await expect(
      page.getByRole('button', { name: 'Next recovery page' }),
    ).toHaveCount(0);
  });

  test('shows an open failure and can retry without losing persisted data', async ({
    page,
  }) => {
    await signedInHarness(page);
    const source = await createSource(page);
    await page.addInitScript(() => {
      const original = IDBFactory.prototype.open;
      IDBFactory.prototype.open = function (...args) {
        IDBFactory.prototype.open = original;
        throw new DOMException(
          `Injected open failure for ${args[0]}`,
          'UnknownError',
        );
      };
    });
    await page.reload();
    await expect(page.getByRole('alert')).toContainText(
      'Injected open failure',
    );
    await page.getByRole('button', { name: 'Retry local storage' }).click();
    await expect(page.getByTestId(`draft-${source}`)).toBeVisible();
  });
});
