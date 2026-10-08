# Stage 12a - Locally persistent editor

Status: implemented on `stage-12a-locally-persistent-editor`; Gate G12a passed
locally on 2026-10-08.

Working estimate: part of Stage 12's 4 person-day budget.

This file is the detailed implementation contract for Stage 12a. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Deliver a usable mobile workout editor whose every acknowledged edit is backed
by Stage 11 persistence. This increment proves creation, recovery, graph editing,
focus stability, validation, and provisional calculations before enabling
server save or finish controls.

References:

- `PLAN.md` sections 3, 4, 6, 7, and 8.
- `IMPLEMENTATION.md` Gate G12a and acceptance checks 1 and 7.
- Stage 11's durable create and local-draft contracts.

## Scope and boundaries

- Add `features/workout` editor, exercise block, set row, catalog picker,
  recovery selection, local status, and route integration.
- Enable Home quick start and active-workout resume/navigation.
- Quick start uses Stage 11b's durable online create path; offline creation
  remains unsupported and visibly disabled/failed without generating repeated
  IDs.
- Online resume fetches authoritative detail and resolves existing local drafts
  through Stage 11a's explicit selection rules. Offline available-shell recovery
  opens an existing draft with its stored snapshots/raw input in local-only mode;
  it must not depend on a successful detail or `/auth/me` request.
- Keep network save, reconnect automation, reauthentication, finish,
  and conflict recovery controls for Stages 12b-12c.
- No new dependency is expected.

## Draft construction

- A first acknowledged empty workout becomes a draft at revision 0 with the
  server-recorded bodyweight and immutable `started_at`. A recovered create may
  already have a newer revision/graph; honor Stage 11b's returned lifecycle/base.
- Loading an existing active workout copies writable fields and ordered graph
  inputs into a new draft while retaining its authoritative revision and
  recorded exercise snapshots for provisional validation/calculation.
- Existing draft IDs, exercise IDs, and set IDs remain stable. New graph rows use
  `crypto.randomUUID()` once and persist that ID with the edit.
- Never assign one existing exercise ID to another catalog entry or move a set
  ID between exercise parents. Copying creates new IDs.
- Finished workouts are not editable; route them to the read-only Stage 13
  detail placeholder until that stage lands.

## Editor behavior

- Edit nullable workout name, notes, and recorded bodyweight; show immutable
  start time and current base revision without presenting technical receipt
  fields as ordinary form controls.
- Add exercises through the visible catalog picker. New instances retain the
  selected catalog values locally as provisional snapshots until a server save
  acknowledges the authoritative snapshot.
- Add/remove/reorder exercise blocks and sets. Array order is the future PUT
  order; never expose or submit editable order indexes.
- Support reps, whole-kilogram weight, bodyweight percentage override, integer
  RPE, side, done flag, and exercise notes according to the selected/recorded
  load rules. Hide or disable impossible side/load inputs rather than silently
  coercing values.
- Completed-set validation matches the backend: positive reps; required
  nonnegative weight for weighted loads; null weight for bodyweight; allowed
  override only when a bodyweight contribution exists; RPE 1-10 and percentage
  1-100.
- Keep raw input text while editing so an empty field or temporarily invalid
  integer does not become zero/NaN. Convert only strict decimal integer text
  within the shared safe range; no fractional, exponential, boolean, or
  whitespace-coerced values. Also enforce the backend's field-specific and graph
  bounds. Persist raw text locally even when invalid, and block server payload
  construction until the visible fields are valid.

## Persistence and focus

- Every edit creates a complete draft update through Stage 11a. The UI may show
  the keystroke immediately but displays `locally saved` only for the matching
  committed change number.
- Serialize rapid edits without dropping intermediate intent; the final durable
  record must equal the visible editor state.
- Use keyed Svelte lists with stable exercise/set IDs. Reorder and unrelated
  persistence/status updates must not replace focused inputs or move the caret.
- A storage failure keeps the in-memory edit visible, changes status to a clear
  failure with retry, and prevents navigation from implying the edit is safe.
- Recovery lists identify drafts without exposing another account's records and
  never silently pick a two-tab winner.

## Provisional calculations

- Calculate effective load and volume with Stage 9 BigInt helpers from the
  workout's recorded bodyweight, the existing recorded snapshot or new selected
  catalog values, and a set override.
- Label totals as provisional and include only `done=true` sets. Preserve unknown
  load as unknown; if known and unknown completed sets are mixed, show the known
  partial sum and the unknown count without calling it complete.
- Do not calculate or invent server previous-performance pairings in the editor.
  Existing detail data may be shown as read-only "last time" context, but Stage
  13 owns full comparison presentation.

## Mobile and accessibility rules

- Prioritize one-handed single-column logging, sticky primary/local-status
  regions that do not cover content, and at least 44 CSS pixel controls.
- Every input has a visible label including fixed metric unit where applicable.
  Numeric fields use numeric input mode and integer steps where supported.
- Reorder controls are keyboard operable and announced by label; drag-and-drop
  is not required.
- Errors are associated with their row/field and use text as well as color.

## Verification

Component tests cover draft construction, strict numeric editing, the load/side
matrix, graph limits, add/remove/reorder, stable keys/focus, provisional known/
unknown totals, persistence statuses, and storage-error retry.

Playwright against the real backend covers quick start, catalog selection,
large integer entry, graph editing/reordering, local acknowledgement, reload,
explicit recovery, focus preservation through neighboring edits, two-tab draft
selection, and visible storage failure. Assert that new workouts remain at
revision 0 and resumed workouts retain their existing revision: no graph save
occurs because synchronization belongs to 12b. Recover while auth/detail requests
fail, including an invalid intermediate input value.

Run the complete frontend gate:

```bash
cd frontend
npm run check
npm run lint
npm run test:unit
npm run build
npm run test:e2e
```

## Non-goals

- Server PUT/autosave, finish, reconnect, or synchronization-state controls.
- Polished conflict/deletion recovery.
- Drag-and-drop, templates, timers, fractional units, or advanced charts.
- Editing finished workouts.

## Gate G12a

G12a passes when a user can durably quick-start or resume an active workout,
explicitly select/recover the correct local draft, edit and reorder the complete
graph with strict integer/load validation, retain focus through keyed updates,
see honest provisional totals and storage status, and recover every locally
acknowledged edit after reload without a server save.

Completion evidence and the Stage 12b marker must be recorded in
`IMPLEMENTATION.md` in the Stage 12a branch before merge.

## Completion evidence

Implemented on `stage-12a-locally-persistent-editor`.

- The authenticated production shell provides `#/workouts/new` durable quick
  start and `#/workouts/:id` resume routes. A create request and empty draft are
  persisted before POST; the acknowledged draft remains at revision 0. Existing
  local drafts require explicit selection, while a network-unavailable shell
  exposes only the last confirmed account's local drafts and pauses all network
  work.
- The editor keeps stable client row IDs, supports catalog selection plus
  add/remove/reorder exercises and sets, records exercise snapshots locally,
  preserves invalid raw integer text, validates load/side/completed-set rules,
  and labels completed-set volume as provisional with unknown-load counts.
  Storage acknowledgement is visibly distinct from server synchronization; this
  stage sends no graph PUT or finish request.
- Verification: `npm run check`, `npm run lint`, `npm run test:unit` (182
  tests), `npm run build`, and `npm run test:e2e` (26 Chromium tests) pass
  locally. The added browser case quick-starts, edits a catalog graph, reloads
  its selected durable draft, and asserts no PUT request occurred.
- Gate G12a covers the local-persistence half of acceptance check 1 and the UI
  half of check 7. Stage 12b is the next marker and owns all synchronization,
  reauthentication, and finish behavior.
