# Stage 12c - Conflict recovery

Status: implemented directly on `master` at the user's request. Gate G12c/G12
passed locally on 2026-10-08.

Working estimate: part of Stage 12's 4 person-day budget.

This file is the detailed implementation contract for Stage 12c. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record. Repeat-last is deferred beyond the MVP.

## Purpose

Complete the core logging experience with explicit recovery from concurrent
edits or deletion while preserving source drafts until the selected action has
durably succeeded.

References:

- `PLAN.md` sections 6 and 8, creation and conflict handling.
- `IMPLEMENTATION.md` Gate G12c/G12 and acceptance checks 1-5, 8, and 11.
- Stage 11c recovery commands and the Stage 12a-12b production editor.

## Scope

- Complete quick-start/resume action presentation, including a centered current
  workout navigation action.
- Add production UI for use-server, copy-local-to-new, explicit replacement, and
  deleted/finished conflict variants.
- Validate copy-to-new graphs against the current catalog and preserve local
  completion flags, RPE data, notes, bodyweight, raw entered values, and IDs only
  where identity preservation is valid.
- Prove the complete core app in real browser and two-tab flows.
- Remove RPE from the set form while retaining persisted RPE data, and present
  set completion as an action button beside the other set actions.
- No new dependency is expected.

## Catalog compatibility

- An unavailable catalog entry blocks a copied exercise from save. Keep it
  visible and require the user to remove it or choose a replacement.
- Validate side, weight, and percentage override against the current catalog
  load type, bodyweight contribution, and side count. Never silently coerce an
  incompatible value.
- A replacement catalog selection creates a new exercise identity, remaps set
  identities/raw values, and rechecks every copied set.
- Create, local-persistence, and initial-save failures retain the new draft and
  exact pending request without mutating the source workout.

## Conflict recovery UI

Display a concise comparison of local status and the freshly fetched server
workout, then expose only lifecycle-valid actions:

- **Use server version:** confirm local-discard intent, durably replace the
  selected draft from server detail, then retire superseded pending state.
- **Copy local work to new workout:** create distinct workout, exercise, and set
  IDs through the durable create path. Retain all local sets, completion flags,
  RPE data, notes, entered values, and explicitly recorded bodyweight. Use a new
  start and `ended_at=null`, current catalog snapshots, and expose incompatible
  values for correction. Keep the source conflict draft.
- **Replace server version:** active workouts only. Show the fresh server
  revision, require confirmation, and submit the retained local graph as one new
  immutable PUT at that revision/save ID. A new conflict returns to the choices.
- **Missing/deleted server workout:** offer copy-to-new or confirmed discard. PUT
  never becomes POST with the deleted ID.
- **Server-finished workout:** offer use-server or copy-to-new; replacement is
  unavailable because the MVP cannot edit or reopen finished workouts.
- **Revision exhausted:** offer use-server or copy-to-new without replacement.

Cancel, failed storage, failed create/save, reauthentication, and route changes
preserve the source draft. No action clears another tab's draft.

## User experience rules

- Explain that no automatic merge occurs and identify which version each action
  keeps without protocol jargon.
- Destructive discard/replacement requires confirmation.
- Keep controls keyboard-operable with visible status and 44 CSS pixel targets.
- Return Home/editor lists to current server state after successful recovery.

## Verification

Component tests cover copy-to-new identity/value preservation, unavailable
catalog blocking, current-catalog incompatibility, and lifecycle actions.

Playwright against the real backend covers:

- Two tabs save from one base revision; both drafts survive, and use-server,
  copy-to-new, and explicit replacement work in isolated scenarios.
- Copy-to-new preserves incomplete sets, completion flags, RPE data, notes, and
  entered values across reload and durable create/save.
- Unavailable and changed catalog entries remain visible and block invalid save
  until corrected.
- Cancellation/failure preserves the source draft; a second replacement conflict
  pauses again.
- Deletion and server-finished conflicts expose only valid choices and never
  recreate or reopen silently.

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

- Repeat-last, automatic merging, per-field/set winner selection, or editing
  finished workouts.
- Dedicated clone API, templates, or offline workout creation.
- History/detail and remaining Stage 13 work.

## Gate G12c / G12

G12c and parent Gate G12 pass when catalog incompatibilities are explicit; all
lifecycle-valid conflict choices work without premature source deletion; and the
complete create/edit/save/finish/recover core flow passes component and
real-browser/two-tab tests.

Completion evidence, the Milestone C remote-QA checkpoint, and the Stage 13
marker must be recorded in `IMPLEMENTATION.md` before delivery.

## Completion evidence

Implemented directly on `master` at the user's request on 2026-10-08.

- The five-item bottom navigation now has a centered current-workout action. Its
  resolver opens the newest active workout or redirects to durable quick start
  when none exists, without initializing duplicate sync controllers.
- Conflict UI fetches and compares fresh server lifecycle/revision state. Confirmed
  use-server, copy-local-to-new, and active replacement are explicit; deleted
  workouts expose copy/discard only, while server-finished workouts expose
  use-server/copy only. No automatic merge occurs.
- Copy-to-new allocates independent workout, draft, exercise, and set IDs;
  preserves local completion flags, RPE data, notes, bodyweight, and raw entered
  values; uses current catalog snapshots; and blocks unavailable or incompatible
  entries until removal, replacement, or correction.
- The set form no longer renders RPE. Completion is a keyboard-operable pressed
  action beside move/remove controls; persisted RPE remains intact for API and
  conflict-copy compatibility.
- `npm run check`, `npm run lint`, `npm run test:unit`, `npm run build`, and
  `npm run test:e2e` pass: 192 unit tests and 38 Chromium tests. Real-backend
  browser evidence covers current-session routing, use-server, copy-to-new,
  replacement, second-tab draft retention, deleted discard, and finished-server
  action restrictions.
- Backend regression validation passes: Ruff lint/format, mypy, 643 pytest tests,
  and `pip check`.
- Milestone C is ready for the isolated remote QA deployment checkpoint. Phase 1
  acceptance checks 1-5, 8, and the editor portions of 11 remain green.
