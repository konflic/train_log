# Stage 7 - Delete and lifecycle

Status: implemented on branch `stage-7-delete-lifecycle` (PR pending). Gate G7
passed locally on 2026-10-08; see Completion evidence below.

Estimate: 0.5 person-day.

This file is the detailed implementation contract for Stage 7. `PLAN.md`
remains the product contract, and `IMPLEMENTATION.md` remains the roadmap and
status record.

## Purpose

Complete the workout lifecycle with revision-checked hard deletion while
preserving the Stage 6 save and finish guarantees.

References:

- `PLAN.md` section 6, especially Finishing and lifecycle.
- `IMPLEMENTATION.md` Gate G7 and acceptance checks 2 and 11.
- Stage 6c's existing save receipt, revision, and finished-workout behavior.

## Scope

- Add `DELETE /api/v1/workouts/{workout_id}?revision=N`.
- Delete active or finished workouts only at the exact stored revision.
- Keep missing and foreign workouts indistinguishable as 404 responses.
- Preserve hard-delete semantics: child exercises and sets are removed by the
  existing foreign-key cascades.
- Preserve the existing rule that PUT never recreates a missing workout.

No migration or dependency is required.

## Public contract

The `revision` query parameter is required, encoded as ASCII decimal digits,
and bounded to the shared nonnegative JSON-safe integer range. Fractional,
signed, whitespace-padded, and other malformed spellings are rejected.

| Outcome | Response |
|---------|----------|
| Owned workout and exact revision | Empty 204 |
| Missing, already deleted, or foreign workout | 404 `not_found` |
| Stored revision differs | 409 `revision_conflict` with `current_revision` |
| Missing or invalid revision query | 422 `validation_error` |
| SQLite writer timeout | 503 `retryable` with `Retry-After: 1` |

DELETE follows the existing mutating-request convention: exact allowed
`Origin` plus `Content-Type: application/json`, even though the request body is
empty. The response must not include a JSON body on success.

A retry after a successful but unobserved deletion returns 404. The client
resolves the uncertain result with an owner-scoped GET, which also returns 404;
there is no delete receipt or tombstone.

## Service design

Add a focused `delete_workout` function to `app/services/workouts.py`:

1. Open one configured connection and one `BEGIN IMMEDIATE` transaction.
2. Select the workout revision with both `id` and `user_id` in the predicate.
3. Raise `WorkoutNotFoundError` when no owned row exists.
4. Compare the submitted revision to the stored revision inside the
   transaction. Raise the existing `RevisionConflictError` on mismatch.
5. Delete the owner-scoped workout row. Existing foreign keys cascade to its
   exercises and sets.
6. Commit and return no resource representation.

The service does not inspect `ended_at`: both active and finished workouts are
deletable. It does not update timestamps, retain receipts, or create a generic
deletion abstraction.

## API work

- Add the DELETE route to `app/api/workouts.py`.
- Reuse the existing revision-conflict problem shape used by PUT.
- Map `WorkoutNotFoundError` to the existing generic workout 404.
- Return `Response(status_code=204)` directly.
- Keep all other shared middleware and error handling unchanged.

## Verification

Add focused service and API lifecycle tests covering:

- Exact-revision deletion of an active workout.
- Exact-revision deletion of a finished workout.
- Cascading removal of all descendant exercises and sets.
- Release of catalog references so an otherwise deletable custom entry can be
  removed after the workout is deleted.
- Stale and future revisions returning 409 with the stored revision and no
  mutation.
- Missing and foreign workouts returning indistinguishable 404 responses.
- Missing, negative, out-of-range, and malformed revision query values.
- Empty 204 success response.
- Origin and JSON-content-type checks on DELETE.
- GET, PUT, and repeated DELETE after deletion returning 404.
- A queued/stale PUT never recreating the deleted workout.
- An exact accepted finish retry succeeding before deletion and returning 404
  after deletion.
- A save that increments the revision causing a delete at the old revision to
  fail atomically.
- Writer-lock timeout mapping to the existing retryable 503 where focused
  coverage adds value beyond the Stage 6 concurrency tests.

Run the complete backend gate:

```bash
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app migrate.py
.venv/bin/pytest -q
.venv/bin/pip check
```

## Non-goals

- Soft delete, tombstones, restore, or a deletion receipt.
- Bulk deletion.
- Automatic client recovery or local-draft disposal; those belong to Stages
  11-13.
- Preventing a later explicit POST from creating a new workout with a UUID
  whose previous row has been deleted. The server has no tombstone; the client
  must require an explicit decision before starting anew.

## Gate G7

G7 passes when deletion is owner-scoped, revision-checked in the write
transaction, lifecycle reads and writes after deletion return 404 without
recreation, finished-workout behavior remains unchanged, and the full backend
suite is green locally and in CI.

Completion evidence is recorded below; the next-stage marker is recorded in
`IMPLEMENTATION.md`, both within branch `stage-7-delete-lifecycle` before
merge.

## Completion evidence

Recorded on branch `stage-7-delete-lifecycle` on 2026-10-08. Gate G7 passed
locally; CI re-runs the complete suite on the PR.

- `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
  `pytest -q` (510 tests, +18), and `pip check` all green, and the isolated
  migration + backup/verify check still passes. No dependency, migration,
  schema, or request-body change was added; the only new public surface is the
  `DELETE /workouts/{id}?revision=N` route and its empty 204 response. All
  Stage 6 save/finish/retry checks still pass unchanged.
- `app/services/workouts.py`: `delete_workout` hard-deletes one owned workout
  inside a single `BEGIN IMMEDIATE` transaction: owner-scoped revision select
  (missing, already-deleted, and foreign ids are indistinguishable
  `WorkoutNotFoundError`s), in-transaction comparison against the submitted
  revision (`RevisionConflictError` on mismatch, with no mutation), then
  delete of the workout row; existing `ON DELETE CASCADE` foreign keys remove
  its exercises and sets. Both active and finished workouts are deletable
  (`ended_at` is never inspected), and nothing is retained: no receipt,
  tombstone, or timestamp update.
- `app/api/workouts.py`: `DELETE /workouts/{id}?revision=N` with the required
  `revision` query parsed strictly as ASCII decimal digits and bounded to the
  shared nonnegative JSON-safe integer range.
  Exact-revision delete returns an empty 204 (no JSON body);
  missing/foreign/deleted return the generic 404 `not_found`; a revision
  mismatch reuses PUT's 409 `revision_conflict` carrying only
  `current_revision`; a missing or invalid revision query is 422
  `validation_error`; the writer timeout keeps the retryable 503 with
  `Retry-After: 1`. The mutating-request convention applies unchanged: exact
  allowed `Origin` plus JSON `Content-Type` despite the empty body. A retry
  after a successful but unobserved deletion returns 404; there is no delete
  receipt, and clients resolve uncertainty with an owner-scoped GET.
- Tests added (+18): `tests/test_workout_delete_service.py` (8 direct service
  cases) covers cascaded active/finished deletion, catalog-reference release
  (a guarded custom entry becomes deletable after the workout is gone),
  stale/future revision conflicts with byte-identical database state,
  delete-after-save-increment requiring the new revision,
  missing/foreign/repeated-delete not-found paths, and the held-lock busy
  timeout with a successful retry. `tests/test_workout_delete_api.py` (10 API
  cases) covers authentication, Origin/JSON conventions, the empty 204 with a
  fully cascaded graph, the finished-workout exact-retry window closing at
  deletion, the stable 409/404/422 shapes, GET/PUT/DELETE after deletion never
  recreating the workout (including a queued exact-retry PUT), the released
  catalog entry through the public routes, and the retryable 503.
- **Covers the deletion half of acceptance checks 2 and 11** (lost-retry and
  account/deletion recovery at the API layer); the client-side recovery
  behavior lands in Stages 11-13.
