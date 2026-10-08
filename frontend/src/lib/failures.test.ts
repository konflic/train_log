// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  ApiNetworkError,
  ApiRequestError,
  MALFORMED_RESPONSE_CODE,
  type ApiProblem,
} from '../api';
import {
  describeFailure,
  isAbortError,
  isUnauthorizedError,
  mapFailureToForm,
} from './failures';

function makeProblem(overrides: Partial<ApiProblem> = {}): ApiProblem {
  return {
    status: 500,
    code: 'error',
    title: 'Internal Server Error',
    detail: 'Something failed',
    requestId: null,
    retryAfterSeconds: null,
    validationErrors: [],
    currentRevision: null,
    ...overrides,
  };
}

describe('classification helpers', () => {
  it('recognizes aborts without wrapping them', () => {
    expect(isAbortError(new DOMException('aborted', 'AbortError'))).toBe(true);
    expect(isAbortError(new ApiNetworkError('down'))).toBe(false);
    expect(isAbortError('AbortError')).toBe(false);
  });

  it('recognizes 401 problems', () => {
    expect(
      isUnauthorizedError(new ApiRequestError(makeProblem({ status: 401 }))),
    ).toBe(true);
    expect(
      isUnauthorizedError(new ApiRequestError(makeProblem({ status: 403 }))),
    ).toBe(false);
    expect(isUnauthorizedError(new ApiNetworkError('down'))).toBe(false);
  });
});

describe('describeFailure', () => {
  it('prefers the safe server detail', () => {
    expect(
      describeFailure(
        new ApiRequestError(makeProblem({ detail: 'Not found' })),
      ),
    ).toBe('Not found');
    expect(
      describeFailure(
        new ApiRequestError(makeProblem({ detail: '', title: 'Conflict' })),
      ),
    ).toBe('Conflict');
  });

  it('uses a connection message for network failures', () => {
    expect(describeFailure(new ApiNetworkError('x'))).toContain(
      'Cannot reach the server',
    );
  });

  it('falls back to a generic message for anything else', () => {
    expect(describeFailure(new Error('boom'))).toBe(
      'Something went wrong. Please try again.',
    );
  });
});

describe('mapFailureToForm', () => {
  it('maps 422 validation entries by field path without the body prefix', () => {
    const failure = mapFailureToForm(
      new ApiRequestError(
        makeProblem({
          status: 422,
          validationErrors: [
            { field: 'body.email', message: 'email is malformed' },
            { field: 'body.password', message: 'too short' },
          ],
        }),
      ),
    );
    expect(failure.fields).toEqual({
      email: 'email is malformed',
      password: 'too short',
    });
    expect(failure.form).toBeNull();
  });

  it('keeps the first message per field', () => {
    const failure = mapFailureToForm(
      new ApiRequestError(
        makeProblem({
          status: 422,
          validationErrors: [
            { field: 'body.name', message: 'first' },
            { field: 'body.name', message: 'second' },
          ],
        }),
      ),
    );
    expect(failure.fields.name).toBe('first');
  });

  it('surfaces unmappable model-level entries at form level', () => {
    const failure = mapFailureToForm(
      new ApiRequestError(
        makeProblem({
          status: 422,
          validationErrors: [
            {
              field: 'body',
              message: 'bodyweight exercises require a percentage',
            },
          ],
        }),
      ),
    );
    expect(failure.fields).toEqual({});
    expect(failure.form).toBe('bodyweight exercises require a percentage');
  });

  it('formats throttling with the preserved Retry-After', () => {
    const failure = mapFailureToForm(
      new ApiRequestError(makeProblem({ status: 429, retryAfterSeconds: 30 })),
    );
    expect(failure.form).toBe('Too many attempts. Try again in 30 seconds.');
    const withoutHeader = mapFailureToForm(
      new ApiRequestError(makeProblem({ status: 429 })),
    );
    expect(withoutHeader.form).toBe('Too many attempts. Try again later.');
  });

  it('keeps conflicts, network, and malformed failures at form level', () => {
    expect(
      mapFailureToForm(
        new ApiRequestError(
          makeProblem({
            status: 409,
            code: 'email_taken',
            detail: 'Already exists',
          }),
        ),
      ).form,
    ).toBe('Already exists');
    expect(mapFailureToForm(new ApiNetworkError('x')).form).toContain(
      'Cannot reach the server',
    );
    expect(
      mapFailureToForm(
        new ApiRequestError(
          makeProblem({
            status: 502,
            code: MALFORMED_RESPONSE_CODE,
            detail: 'Unreadable',
          }),
        ),
      ).form,
    ).toBe('Unreadable');
  });
});
