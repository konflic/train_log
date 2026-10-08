# Stage 8c - Saved-data export

Status: draft; implementation is blocked on the content decisions in Open
questions.

Working estimate: 0.5 person-day within Stage 8's 2.5-day post-Stage-6 budget.

This file is the detailed implementation contract for Stage 8c. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Provide a versioned, owner-scoped JSON export of server-saved training data and
the recorded inputs needed to interpret it, without exposing credentials,
sessions, or another user's data.

References:

- `PLAN.md` sections 6 and 10 for the Phase 1 export requirement.
- `PLAN.md` section 4 for recorded historical inputs.
- `IMPLEMENTATION.md` Gate G8 and acceptance check 12.

This is the server-saved-data export. The offline local-draft export is a
separate Stage 11/13 client feature.

## Fixed product rules

- Endpoint: authenticated `GET /api/v1/export`.
- Return versioned JSON owned by the authenticated caller.
- Include recorded workout bodyweight, exercise load snapshots, set values, and
  referenced catalog information so historical data remains interpretable.
- Exclude password hashes, session rows/tokens, and authentication secrets.
- Do not include role or administrative audit data when those arrive in Stage
  14.
- Export is not import, database backup, or an operational recovery procedure.
- Use one consistent database snapshot so parent and child rows cannot describe
  different committed states.

## Proposed export envelope

```json
{
  "format_version": 1,
  "exported_at": "2026-01-01T00:00:00Z",
  "profile": {},
  "catalog": [],
  "workouts": []
}
```

Proposed profile fields:

- Account ID.
- Email and display name.
- Current bodyweight default.
- Fixed UTC offset.
- Account creation/update timestamps.

Proposed catalog content:

- Every custom catalog entry owned by the caller, including unreferenced ones.
- Every default catalog entry referenced by an exported workout.
- Public catalog fields only; no `created_by` value.

Proposed workout content:

- Active and finished workouts.
- Public metadata, revision, created/updated timestamps, and ordered graph.
- Exercise catalog reference, order, notes, and recorded load snapshot.
- Every set's recorded fields and order, including draft/incomplete saved sets.
- `last_save_id` only if preserving the public workout-detail shape is valuable;
  the current recommendation is to omit receipt state from the export.

Always exclude:

- Password hashes or any password-related material.
- Session rows, token hashes, or raw tokens.
- `create_request_hash` and `last_save_hash`.
- Login throttle state or request logs.
- Other users' profile, custom catalog, workout, or set data.
- Future role, account status, admin audit, and admin-only data.

The exact envelope and content are not final until the open questions are
resolved.

## Service design

Add a focused export service, likely `app/services/export.py`, to keep route
serialization thin. In one deferred read transaction:

1. Read the caller's approved profile fields.
2. Read all caller-owned workouts in a stable order.
3. Read all descendant exercises and sets with fixed query counts and stable
   `(workout, order_index, set_index)` ordering.
4. Read caller-owned custom catalog entries and/or referenced default entries
   according to the finalized content decision.
5. Build the explicit export response only from whitelisted fields.

The MVP may build the caller's export in memory. Do not add streaming,
background jobs, archive formats, object storage, or a dependency without a
measured export-size requirement.

## API work

- Add explicit export schemas, either in `app/schemas/export.py` or in the API
  module if they remain small and isolated.
- Add and register `app/api/export.py`.
- Set `application/json` and, if approved, a deterministic safe attachment
  filename through `Content-Disposition`.
- Use `ensure_ascii=False` behavior from normal JSON serialization so Unicode
  user content round-trips correctly.
- Do not expose internal row dictionaries or generic writable schemas.

## Verification

Tests must cover:

- Authentication is required.
- Only the authenticated caller's rows are present when multiple users have
  profiles, customs, workouts, exercises, sets, and sessions.
- Active and finished workouts and saved draft/completed sets follow the final
  content decision.
- Recorded bodyweight, exercise snapshots, overrides, side, completion, order,
  and null values round-trip in JSON.
- Referenced default/custom catalog data and unreferenced customs follow the
  final catalog decision.
- UTF-8 names and notes are emitted without data loss.
- Passwords, password hashes, session/token data, request fingerprints, and
  future admin fields are absent by field name and value.
- Stable ordering produces deterministic data arrays for unchanged storage.
- A concurrent commit cannot mix parent/child revisions within one export.
- `format_version` and timestamp use their finalized types and canonical format.
- Response media type and attachment header follow the finalized contract.
- Empty-account export remains valid versioned JSON.

## Open questions

1. Which profile fields are included? Proposed default: ID, email, display name,
   bodyweight default, UTC offset, and account timestamps.
2. Should catalog data include all caller-owned customs plus referenced defaults,
   as proposed, or referenced entries only?
3. Confirm that both active and finished workouts and all persisted draft sets
   are exported.
4. Confirm inclusion of revision and server timestamps but exclusion of
   `last_save_id` and all request hashes.
5. Confirm integer `format_version: 1` and top-level canonical `exported_at`.
6. Should the API set `Content-Disposition: attachment` with a timestamped
   filename, or leave download naming entirely to the frontend? Proposed
   default: set the header.

## Gate G8c / G8

G8c passes when the finalized versioned export is complete for the caller's
approved saved-data scope, is consistent and deterministically ordered, excludes
all secrets and foreign data, and the complete backend suite is green locally
and in CI.

Completion evidence, the Milestone B exit, and the Stage 9 marker must be
recorded in `IMPLEMENTATION.md` in the Stage 8c branch before merge.
