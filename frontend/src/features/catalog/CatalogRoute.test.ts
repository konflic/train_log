import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { listExercisesMock, createExerciseMock, updateExerciseMock } =
  vi.hoisted(() => ({
    listExercisesMock: vi.fn(),
    createExerciseMock: vi.fn(),
    updateExerciseMock: vi.fn(),
  }));

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    listExercises: listExercisesMock,
    createExercise: createExerciseMock,
    updateExercise: updateExerciseMock,
  };
});

import { ApiRequestError, type Exercise, type ExercisePage } from '../../api';
import { session } from '../auth/session.svelte';
import CatalogRoute from './CatalogRoute.svelte';

function entry(overrides: Partial<Exercise> = {}): Exercise {
  return {
    id: 'x-1',
    name: 'Sample',
    muscle_group: 'chest',
    load_type: 'single_weight',
    bodyweight_percent: null,
    side_count: 1,
    is_default: true,
    ...overrides,
  };
}

const benchPress = entry({ id: 'bench-press', name: 'Bench Press' });
const pullUp = entry({
  id: 'pull-up',
  name: 'Pull-up',
  muscle_group: 'back',
  load_type: 'bodyweight',
  bodyweight_percent: 100,
});
const fullRow = entry({
  id: 'full-row',
  name: 'Full Body Row',
  muscle_group: 'full_body',
  load_type: 'split_weight',
  side_count: 2,
  is_default: true,
});
const customCurl = entry({
  id: 'custom-1',
  name: 'Custom Curl',
  muscle_group: 'arms',
  load_type: 'split_weight',
  side_count: 2,
  is_default: false,
});
const weightedDip = entry({
  id: 'custom-2',
  name: 'Weighted Dip',
  load_type: 'single_weight',
  bodyweight_percent: 30,
  is_default: false,
});

const defaultItems = [benchPress, pullUp, fullRow, customCurl, weightedDip];

function pageWith(items: Exercise[], total = 25, page = 1): ExercisePage {
  return { items, total, page, page_size: 10 };
}

function requestError(
  status: number,
  detail: string,
  validationErrors: Array<{ field: string; message: string }> = [],
) {
  return new ApiRequestError({
    status,
    code: 'error',
    title: 'Error',
    detail,
    requestId: null,
    retryAfterSeconds: null,
    validationErrors,
    currentRevision: null,
  });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function navigate(hash: string): void {
  window.location.hash = hash;
  window.dispatchEvent(new Event('hashchange'));
}

function renderAt(hash = '#/catalog') {
  navigate(hash);
  return render(CatalogRoute);
}

async function openCreateForm() {
  await fireEvent.click(
    screen.getByRole('button', { name: 'New custom exercise' }),
  );
  return screen.getByRole('region', { name: 'New custom exercise' });
}

beforeEach(() => {
  listExercisesMock.mockReset();
  createExerciseMock.mockReset();
  updateExerciseMock.mockReset();
  listExercisesMock.mockResolvedValue(pageWith(defaultItems));
  createExerciseMock.mockResolvedValue(customCurl);
  updateExerciseMock.mockResolvedValue(customCurl);
  session.status = 'authenticated';
  session.user = {
    id: 'u-1',
    email: 'user@example.test',
    display_name: null,
    bodyweight_default_kg: null,
    sex: null,
    age: null,
    utc_offset_minutes: 0,
  };
  cleanup();
  navigate('#/catalog');
});

describe('CatalogRoute listing', () => {
  it('builds the initial query with the exact backend names', async () => {
    renderAt();
    await waitFor(() => expect(screen.getByText('Bench Press')).toBeDefined());
    expect(listExercisesMock).toHaveBeenCalledWith(
      {
        page: 1,
        pageSize: 10,
        search: undefined,
        muscle_group: undefined,
      },
      expect.any(AbortSignal),
    );
  });

  it('renders enum labels and default/custom markers', async () => {
    renderAt();
    await waitFor(() => expect(screen.getByText('Bench Press')).toBeDefined());
    // Enum literals render through the local human-readable labels.
    expect(
      screen.getByText(
        /Full body · Split weight \(per side\) · both sides per set/,
      ),
    ).toBeDefined();
    expect(
      screen.getByText(/Arms · Split weight \(per side\) · both sides per set/),
    ).toBeDefined();
    expect(
      screen.getByText(/Back · Bodyweight · 100% bodyweight/),
    ).toBeDefined();
    expect(screen.getAllByText('Default').length).toBe(3);
    expect(screen.getAllByText('Custom').length).toBe(2);
  });

  it('offers edit only for custom entries', async () => {
    renderAt();
    await waitFor(() => expect(screen.getByText('Bench Press')).toBeDefined());
    expect(
      screen.getByRole('button', { name: 'Edit Custom Curl' }),
    ).toBeDefined();
    expect(
      screen.getByRole('button', { name: 'Edit Weighted Dip' }),
    ).toBeDefined();
    expect(
      screen.queryByRole('button', { name: 'Edit Bench Press' }),
    ).toBeNull();
  });

  it('shows a retryable error without erasing the filters', async () => {
    listExercisesMock.mockRejectedValueOnce(
      requestError(500, 'Catalog exploded'),
    );
    renderAt('#/catalog?search=bench');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Catalog exploded');
    expect(window.location.hash).toBe('#/catalog?search=bench');

    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByText('Bench Press')).toBeDefined());
    expect(listExercisesMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: 'bench' }),
      expect.any(AbortSignal),
    );
  });

  it('invalidates the session on a 401 read', async () => {
    listExercisesMock.mockRejectedValue(
      requestError(401, 'Authentication required'),
    );
    renderAt();
    await waitFor(() => expect(session.status).toBe('anonymous'));
  });

  it('ignores a stale response that resolves after a newer one', async () => {
    const first = deferred<ExercisePage>();
    listExercisesMock.mockReturnValueOnce(first.promise);
    listExercisesMock.mockResolvedValueOnce(
      pageWith([entry({ id: 'newer', name: 'Newer Entry' })]),
    );
    renderAt();
    await waitFor(() => expect(listExercisesMock).toHaveBeenCalledTimes(1));

    // A filter change supersedes the first read.
    navigate('#/catalog?search=new');
    await waitFor(() => expect(screen.getByText('Newer Entry')).toBeDefined());

    first.resolve(pageWith([entry({ id: 'stale', name: 'Stale Entry' })]));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText('Stale Entry')).toBeNull();
    expect(screen.getByText('Newer Entry')).toBeDefined();
  });
});

describe('CatalogRoute filters, search, and paging', () => {
  it('debounces search into the route query', async () => {
    renderAt();
    await waitFor(() => expect(listExercisesMock).toHaveBeenCalledTimes(1));

    await fireEvent.input(screen.getByLabelText('Search'), {
      target: { value: 'curl' },
    });
    // Not sent on every keystroke.
    expect(listExercisesMock).toHaveBeenCalledTimes(1);

    await waitFor(
      () =>
        expect(listExercisesMock).toHaveBeenLastCalledWith(
          expect.objectContaining({ search: 'curl' }),
          expect.any(AbortSignal),
        ),
      { timeout: 2000 },
    );
    await waitFor(() =>
      expect(window.location.hash).toBe('#/catalog?search=curl'),
    );
  });

  it('resets paging when a filter changes and keeps query names exact', async () => {
    renderAt('#/catalog?page=2');
    await waitFor(() =>
      expect(listExercisesMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
        expect.any(AbortSignal),
      ),
    );

    await fireEvent.change(screen.getByLabelText('Muscle group'), {
      target: { value: 'legs' },
    });
    await waitFor(() =>
      expect(listExercisesMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 1, muscle_group: 'legs' }),
        expect.any(AbortSignal),
      ),
    );
    await waitFor(() =>
      expect(window.location.hash).toBe('#/catalog?muscle_group=legs'),
    );
  });

  it('pages through the stable server ordering', async () => {
    renderAt();
    await waitFor(() =>
      expect(screen.getByText('25 exercises · page 1 of 3')).toBeDefined(),
    );
    const previous = screen.getByRole('button', {
      name: 'Previous',
    }) as HTMLButtonElement;
    expect(previous.disabled).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(window.location.hash).toBe('#/catalog?page=2'));
    await waitFor(() =>
      expect(listExercisesMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
        expect.any(AbortSignal),
      ),
    );
  });
});

describe('ExerciseForm through the catalog screen', () => {
  it('gives immediate required/range/cross-field feedback without a request', async () => {
    renderAt();
    const formRegion = await openCreateForm();

    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Create exercise' }),
    );
    expect(within(formRegion).getByText('Name is required')).toBeDefined();
    expect(createExerciseMock).not.toHaveBeenCalled();

    await fireEvent.input(within(formRegion).getByLabelText('Name'), {
      target: { value: 'Z Custom' },
    });
    await fireEvent.change(within(formRegion).getByLabelText('Load type'), {
      target: { value: 'bodyweight' },
    });
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Create exercise' }),
    );
    expect(
      within(formRegion).getByText('Bodyweight exercises require a percentage'),
    ).toBeDefined();

    await fireEvent.input(
      within(formRegion).getByLabelText(/Bodyweight percentage/),
      {
        target: { value: '12.5' },
      },
    );
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Create exercise' }),
    );
    expect(
      within(formRegion).getByText(
        'Percentage must be a whole number from 1 to 100',
      ),
    ).toBeDefined();
    expect(createExerciseMock).not.toHaveBeenCalled();
  });

  it('creates a custom entry and refreshes the visible page', async () => {
    renderAt();
    const formRegion = await openCreateForm();

    await fireEvent.input(within(formRegion).getByLabelText('Name'), {
      target: { value: ' Z Custom ' },
    });
    await fireEvent.change(within(formRegion).getByLabelText('Load type'), {
      target: { value: 'bodyweight' },
    });
    await fireEvent.input(
      within(formRegion).getByLabelText(/Bodyweight percentage/),
      {
        target: { value: '65' },
      },
    );
    // Switching away from split-weight forces the single-side value.
    expect(
      (within(formRegion).getByLabelText('Sides') as HTMLSelectElement)
        .disabled,
    ).toBe(true);

    const listCalls = listExercisesMock.mock.calls.length;
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Create exercise' }),
    );

    await waitFor(() =>
      expect(createExerciseMock).toHaveBeenCalledWith({
        name: 'Z Custom',
        muscle_group: 'chest',
        load_type: 'bodyweight',
        bodyweight_percent: 65,
        side_count: 1,
      }),
    );
    // The form closes and the affected page refetches from the server.
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'New custom exercise' }),
      ).toBeNull(),
    );
    expect(listExercisesMock.mock.calls.length).toBeGreaterThan(listCalls);
  });

  it('sends a PATCH with only changed fields, including an explicit percent clear', async () => {
    renderAt();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Edit Weighted Dip' }),
      ).toBeDefined(),
    );

    await fireEvent.click(
      screen.getByRole('button', { name: 'Edit Weighted Dip' }),
    );
    const formRegion = screen.getByRole('region', {
      name: 'Edit Weighted Dip',
    });
    // Editing starts from the entry's current complete values.
    expect(
      (within(formRegion).getByLabelText('Name') as HTMLInputElement).value,
    ).toBe('Weighted Dip');
    expect(
      (
        within(formRegion).getByLabelText(
          /Bodyweight percentage/,
        ) as HTMLInputElement
      ).value,
    ).toBe('30');

    await fireEvent.input(within(formRegion).getByLabelText('Name'), {
      target: { value: 'Renamed Dip' },
    });
    await fireEvent.input(
      within(formRegion).getByLabelText(/Bodyweight percentage/),
      {
        target: { value: '' },
      },
    );
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Save changes' }),
    );

    await waitFor(() =>
      expect(updateExerciseMock).toHaveBeenCalledWith('custom-2', {
        name: 'Renamed Dip',
        bodyweight_percent: null,
      }),
    );
  });

  it('closes an unchanged edit without a request', async () => {
    renderAt();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Edit Custom Curl' }),
      ).toBeDefined(),
    );
    await fireEvent.click(
      screen.getByRole('button', { name: 'Edit Custom Curl' }),
    );
    const formRegion = screen.getByRole('region', { name: 'Edit Custom Curl' });
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Save changes' }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'Edit Custom Curl' }),
      ).toBeNull(),
    );
    expect(updateExerciseMock).not.toHaveBeenCalled();
  });

  it('cancels without a request', async () => {
    renderAt();
    const formRegion = await openCreateForm();
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Cancel' }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'New custom exercise' }),
      ).toBeNull(),
    );
    expect(createExerciseMock).not.toHaveBeenCalled();
  });

  it('displays backend problems: duplicate names and mapped field errors', async () => {
    createExerciseMock.mockRejectedValue(
      requestError(409, 'A custom exercise with this name already exists'),
    );
    renderAt();
    let formRegion = await openCreateForm();
    await fireEvent.input(within(formRegion).getByLabelText('Name'), {
      target: { value: 'Bench Press' },
    });
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Create exercise' }),
    );
    const alert = await within(formRegion).findByRole('alert');
    expect(alert.textContent).toContain(
      'A custom exercise with this name already exists',
    );
    // The form stays open for correction once the action re-enables.
    expect(
      await within(formRegion).findByRole('button', {
        name: 'Create exercise',
      }),
    ).toBeDefined();
    cleanup();

    updateExerciseMock.mockRejectedValue(
      requestError(422, 'Request validation failed', [
        { field: 'body.name', message: 'name is taken' },
      ]),
    );
    session.status = 'authenticated';
    renderAt();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Edit Custom Curl' }),
      ).toBeDefined(),
    );
    await fireEvent.click(
      screen.getByRole('button', { name: 'Edit Custom Curl' }),
    );
    formRegion = screen.getByRole('region', { name: 'Edit Custom Curl' });
    await fireEvent.input(within(formRegion).getByLabelText('Name'), {
      target: { value: 'Bench Press' },
    });
    await fireEvent.click(
      within(formRegion).getByRole('button', { name: 'Save changes' }),
    );
    expect(await within(formRegion).findByText('name is taken')).toBeDefined();
  });
});
