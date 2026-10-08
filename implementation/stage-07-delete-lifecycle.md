# Stage 7 - Delete and lifecycle

Status: planned and implementation-ready.

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

The `revision` query parameter is required and bounded to the shared
nonnegative JSON-safe integer range.

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

Completion evidence and the next-stage marker must be recorded in
`IMPLEMENTATION.md` in the Stage 7 branch before merge.
