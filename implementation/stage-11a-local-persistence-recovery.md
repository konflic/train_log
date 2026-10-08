# Stage 11a - Local persistence and recovery

Status: implemented and reviewed on `stage-11a-local-persistence`.
Post-review checks were not rerun at the user's explicit request. Gate G11a
and CI remain pending for the revised implementation.

Working estimate: part of Stage 11's 3 person-day budget.

This file is the detailed implementation contract for Stage 11a. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Establish the smallest durable IndexedDB draft layer and prove that locally
acknowledged edits survive reload without one tab or account overwriting
another. This stage deliberately stops before network create/save coordination.

References:

- `PLAN.md` section 6, Client persistence and conflict handling.
- `IMPLEMENTATION.md` Gate G11a and acceptance checks 1, 4, and 11.
- Stage 10's authenticated user identity and application shell.

## Dependencies and scope

- Add only `idb`, pinned exactly, and update/review the lockfile with `npm ls`
  and `npm audit`.
- Add `frontend/src/db.ts` for database opening, schema upgrade, bounded draft
  operations, and account-local cleanup primitives needed by later stages.
- Add a small draft repository/model module only if separating serializable
  types from IndexedDB transactions materially improves testing.
- Add a temporary authenticated browser harness route/component for exercising
  draft creation, editing, discovery, selection, failure, reload, and tabs
  without implementing the Stage 12 workout editor.
  Include it only in an explicit test build; normal production builds must not
  expose harness routes, failure injection, or storage/account inspection hooks.
- Do not add create requests, pending PUT payloads, network synchronization,
  conflict policy, or logout cleanup yet.

## Stored draft contract

Use one versioned database and one `drafts` store. A draft is identified by the
compound identity `(account_id, workout_id, draft_id)` and contains only
structured-clone-safe data:

- Account, workout, and draft IDs.
- The authoritative base revision/detail identity from which editing began.
- The latest editable workout content needed for a future full-state PUT,
  recorded/provisional load snapshots, and raw form text for incomplete/invalid
  fields. Raw text is local-only and survives reload; it blocks payload creation
  until valid rather than silently reverting to a prior numeric value.
- A monotonically increasing local change number and timestamps used only for
  recovery ordering/display.

Create indexes needed to list drafts by account and by account/workout. Do not
store passwords, cookies, session tokens, derived caches, DOM state, functions,
or arbitrary server responses. Keep API snake_case at the transport boundary;
the persisted draft shape may use the same field names when that avoids lossy
mapping.

IDs and all graph arrays are copied into each committed draft value. Callers do
not retain mutable object references and no partial graph write is exposed as a
successful edit.

## Tab and recovery semantics

- Generate a fresh editor identity per document lifetime. sessionStorage can be
  cloned by duplicate-tab/window-open, so a stored identity is only a recovery
  hint, never proof of exclusive ownership of an editable record.
- Enforce at most one active editor association for a workout in one tab. This
  is a UI/coordinator invariant, not a global cross-tab lock.
- Opening a workout never silently chooses among stored drafts. If a known
  current-tab draft exists, offer to continue it; if other recoverable drafts
  exist, list them with stable metadata and require an explicit selection or a
  deliberate new draft.
- On reload or selection, copy the selected recovery value into a fresh draft ID
  before editing, retaining its base revision and graph IDs. Preserve the source
  and alternatives; two tabs selecting the same source must still write different
  records. Stage 11b must carry any pending request unchanged and resolve it before
  further uploads, never regenerate its workout/save IDs during this handoff.
- Partition every read, write, list, and delete by the authenticated account ID
  supplied by the caller. Never discover another account's drafts in UI output.
- For an available-shell reload without connectivity, permit explicit local-only
  recovery for the previously established account using non-secret account context.
  This is not server authentication: no cross-account draft chooser or network
  work is allowed until `/auth/me` confirms the same account. A known different
  account blocks that recovery view. Integrate this exception with Stage 10's
  startup retry state so an offline `/auth/me` cannot hide all local drafts.

## Local acknowledgement semantics

- Each edit produces a complete next draft value and awaits the IndexedDB
  transaction before advancing the visible `locally saved` change number.
- Serialize writes for one draft so a slower older transaction cannot become
  the final value after a newer edit. Different drafts remain independent.
- The in-memory editor may display the user's immediate keystroke, but its
  persistence status remains saving/failed until the matching write commits.
- A failed open, quota/transaction error, blocked upgrade, or serialization
  failure is visible and retryable. Never report `locally saved`, discard the
  in-memory value, or substitute localStorage after a failed write.
- Browser eviction cannot be prevented; state clearly that only committed,
  still-present IndexedDB data is recoverable.

## Database lifecycle

- Open the database lazily in browser code and expose a close hook for tests and
  future blocked-upgrade handling.
- Keep upgrade logic explicit by version. Stage 11b may add stores through the
  next schema version; do not prebuild speculative operation logs.
- Treat an unexpectedly malformed persisted record as unavailable recovery data
  with a visible error. Do not upload or silently repair it.
- Provide bounded account/workout list operations and exact-key get/put/delete;
  avoid a generic repository/query abstraction.

## Verification

Unit tests with a controllable repository boundary cover:

- Compound-key/account scoping and deterministic recovery ordering.
- Serialized writes where the older operation completes last.
- Success acknowledgement only after commit and visible persistence failures.
- One-editor-per-workout-per-tab association and explicit selection among
  alternatives.
- No cross-account reads or deletes.

Playwright uses real browser IndexedDB to cover:

- Edit, await local acknowledgement, reload, and explicitly recover the exact
  graph/value.
- Two tabs editing the same workout into different draft IDs without overwrite;
  both remain selectable after reload. Include a duplicated tab with cloned
  sessionStorage and two tabs explicitly recovering the same source draft.
- Incomplete/invalid raw input survives reload without being reported as a valid
  server payload; stored recorded/provisional snapshots remain available offline.
- A failed/aborted IndexedDB write never displays locally saved.
- Account B cannot discover Account A's records through the harness.
- An available app-shell reload can recover data while network requests fail;
  cold offline startup remains out of scope without a service worker.

Run the complete frontend gate plus dependency checks:

```bash
cd frontend
npm run check
npm run lint
npm run test:unit
npm run build
npm run test:e2e
npm ls
npm audit
```

## Non-goals

- Offline workout creation or cold offline application startup.
- Pending POST/PUT/finish records, retries, server acknowledgements, or
  synchronization statuses.
- Cross-tab locking, automatic draft merging, newest-wins selection, or
  background sync.
- The production workout editor; Stage 12a consumes this layer.

## Gate G11a

G11a passes when every locally acknowledged draft edit is an atomic committed
IndexedDB value, survives an available-shell reload, remains isolated by account
and tab/editor identity, requires explicit recovery selection, and storage
failures remain visible in unit and real-browser tests.

Completion evidence and the Stage 11b marker must be recorded in
`IMPLEMENTATION.md` in the Stage 11a branch before merge.

## Completion evidence

Implemented and reviewed on `stage-11a-local-persistence` on 2026-10-08.

- Added the only Stage 11a dependency, `idb@8.0.3` (npm exact version), with
  a public-registry lockfile URL. The pre-review `npm ls` and `npm audit`
  reported no unmet dependencies and 0 vulnerabilities.
- `frontend/src/db.ts` opens `basefit-drafts` lazily at schema version 1. Its
  `drafts` store has compound key `(account_id, workout_id, draft_id)` and
  `by-account` plus `by-account-workout` indexes. Values retain the full graph,
  raw form text, separate recorded/provisional load snapshots, immutable start
  time, base detail/revision, local change number, and recovery timestamps.
  Structural validation rejects unknown fields, malformed nested graphs,
  duplicate IDs, invalid snapshots, unsafe integers, and oversized data.
- Reads are account-scoped keyset pages of at most 100 values, ordered by
  compound primary key across pages and by recovery timestamp/ID within each
  page. Malformed records consume a page slot and surface as unavailable;
  cursor continuation does not silently drop alternatives. Account deletion
  iterates a scoped cursor instead of allocating every key at once. Logout
  coordination remains Stage 11c/13 work.
- Writes copy the complete value and serialize per draft. `LocalDraftEditor`
  advances the editable change number immediately but advances the saved number
  only after commit; an earlier completion never replaces later input or clears
  its failure. The document-local registry allows an explicit continue action
  after a component remount; recovery creates a new draft without deleting its
  source. No editor identity is restored from sessionStorage.
- A non-secret confirmed-account hint enables explicit local-only recovery
  when startup `/auth/me` fails. A 401 clears eligibility; a different account
  confirmed in another tab invalidates the old hint. The E2E harness now uses
  the same guarded App/session retry state, with no API work or new-source
  creation during local-only recovery. Production editor UI remains Stage 12a.
- Failed opens can be retried. A blocked upgrade rejects visibly and closes any
  late connection; version changes release the cached handle. The test-only
  failure control aborts a real IndexedDB transaction after request success.
  The harness displays persisted graph/snapshot data rather than hard-coded
  snapshot labels.

### Verification provenance

The **pre-review** implementation passed these commands on 2026-10-08:

  ```bash
  cd frontend
  npm run check       # 0 errors, 0 warnings
  npm run lint        # clean
  npm run test:unit   # 14 files, 154 tests passed
  npm run build       # passed; no E2E harness/failure hook in dist
  npm run test:e2e    # 19 Chromium tests passed
  npm ls              # clean exact dependency tree
  npm audit           # 0 vulnerabilities
  ```

Those results did not cover the review findings and are not evidence that the
revised implementation passes. The prior Gate G11a completion claim is withdrawn
until the revised checks pass. The user explicitly requested no rerun of checks
during review; lint, typecheck, unit, browser, build, production-bundle exclusion,
dependency checks, and CI have not been reconfirmed for the revised code.

Added/strengthened regression cases (not executed after review):

- Rapid edits with delayed storage, unique change numbers, latest-value retry,
  acknowledgement only after commit, and graph/reference isolation.
- Exact account scope on writes/reads, malformed nested records, unknown fields,
  open failure retry, blocked-upgrade rejection, and late-handle closure.
- Real-browser graph/raw/snapshot recovery, cloned sessionStorage with distinct
  tab drafts, actual transaction abort, and bounded pagination with corrupt data.
- Available-shell offline recovery, no API requests after explicit local-only
  selection, and revocation when another tab confirms a different account.

Next stage: Stage 11b - durable create requests and immutable pending saves,
after Gate G11a validation and merge.
