# Stage 12c - Repeat-last and conflict recovery

Status: planned. Start after Gate G12b is merged.

Working estimate: part of Stage 12's 4 person-day budget.

This file is the detailed implementation contract for Stage 12c. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Complete the core logging experience with repeat-last and explicit recovery from
concurrent edits or deletion, while preserving source drafts until the selected
action has durably succeeded.

References:

- `PLAN.md` sections 6 and 8, Creation/repeat and conflict handling.
- `IMPLEMENTATION.md` Gate G12c/G12 and acceptance checks 1-5, 8, and 11.
- Stage 11c recovery commands and the Stage 12a-12b production editor.

## Scope

- Enable Home repeat-last and complete quick-start/resume action presentation.
- Implement source selection, current-catalog compatibility checks, graph copy,
  and durable create/save through existing paths.
- Add production UI for use-server, copy-local-to-new, explicit replacement, and
  deleted/finished variants.
- Prove the complete core app in real browser/two-tab flows.
- No new dependency is expected.

## Repeat-last source and creation

1. Request the newest finished workout from history's stable newest-first order.
   If none exists, show an explicit empty state and do not create anything.
2. Fetch its full detail and resolve every unique catalog ID against the current
   visible catalog before creating the copied graph.
3. Allocate the new workout ID and immutable create request without sending POST.
4. Build that prepared graph with new UUIDs for every exercise and set. Preserve
   exercise order and copy only completed source sets.
5. Copy reps, weight, side, and percentage override; set `done=false` and
   `rpe=null`. For a source exercise with no completed sets, add one blank draft
   set using a side valid for the current catalog entry.
6. Commit that prepared graph and create request together before POST through
   Stage 11b's durable online create path. Reload must never leave an acknowledged
   empty workout without the intended graph/IDs. On create acknowledgement,
   retain the prepared graph and install the returned
   base/bodyweight. The server-recorded bodyweight and each later server snapshot
   use current profile/catalog defaults, never historical snapshots. Save valid
   copied content through the ordinary immutable PUT path; keep incompatible
   content local for correction. There is no clone endpoint or special protocol.

Do not count copied draft sets in history/statistics; they remain unfinished
until the user marks and finishes them normally.

## Catalog compatibility

- A catalog entry that is no longer visible/unavailable blocks that copied
  exercise from save. Keep it visible in the source preview and require the user
  to remove it or choose a replacement; never silently drop history content.
- Validate copied side, weight, and percentage override against the current
  catalog load type/bodyweight contribution/side count. Mark incompatible fields
  and require correction; do not coerce a weighted set to bodyweight, cross
  left/right into bilateral, or retain a disallowed override silently.
- A replacement catalog selection creates a new exercise identity and rechecks
  every copied set. Historical source/detail remains unchanged.
- Failure during create, local persistence, or initial save keeps the new draft
  and exact pending request recoverable. It never mutates the source workout.

## Conflict recovery UI

Display a concise comparison of local status and the freshly fetched server
workout, then expose only lifecycle-valid actions:

- **Use server version:** confirm local-discard intent, durably replace the
  selected draft from the server detail, then retire superseded pending state.
- **Copy local work to new workout:** create a distinct workout and graph IDs
  through the durable create path, validating current catalog compatibility as
  for repeat-last. Unlike repeat, retain all local sets, completion flags, RPE,
  notes, and entered values rather than applying repeat's done/RPE reset or
  completed-set filter. Use a new start and `ended_at=null`, current catalog
  snapshots, and expose any load incompatibility for explicit correction. Preserve
  an explicitly recorded local bodyweight through normal PUT, showing how it
  differs from the new profile default. Keep the source conflict draft until the
  full copied graph is durable and its initial PUT is durably acknowledged.
- **Replace server version:** active workouts only. Show the fresh server
  revision, require explicit confirmation, and submit the retained local graph
  as one new immutable PUT at that revision/save ID. A new conflict returns to
  the choice screen; no retry loop or merge.
- **Missing/deleted server workout:** offer copy-to-new or confirmed local
  discard. Do not turn PUT into POST with the deleted ID.
- **Server-finished workout:** replacement is unavailable; offer use-server or
  copy-to-new because Phase 1 cannot edit/reopen finished workouts.
- **Revision exhausted:** offer use-server or copy-to-new even if active; a fresh
  GET cannot make another same-workout save possible.

Replacement must reconcile read-only snapshots with the fresh server graph by
ID. A locally retained instance that the server has removed is new to the server
and will receive current catalog defaults; preview/revalidate it as provisional
instead of promising preservation of an old snapshot the API cannot accept.

Cancel, failed storage, failed create/save, reauthentication, and route changes
preserve the source draft and fetched server state. No action clears another
tab's draft.

## User experience rules

- Explain that no automatic merge occurs and identify which version each action
  keeps without technical jargon such as receipt hash.
- Destructive discard/replacement requires an explicit confirmation and returns
  focus predictably.
- Keep controls usable at phone width with visible status and 44 CSS pixel
  targets. Recovery must be keyboard operable and not color-only.
- Return Home/editor lists to current server state after successful recovery
  without retaining stale action buttons.

## Verification

Component tests cover repeat transformation, new-ID guarantees, completed-set
filtering, blank fallback set, RPE/done resets, each current-catalog
incompatibility, and lifecycle-specific recovery actions.

Playwright against the real backend covers:

- Repeat a finished workout, verify independent IDs/current defaults and
  unfinished copied sets, save/finish it normally, and prove the source detail
  and pre-copy statistics did not change from draft creation.
- No-history empty state and failure/reload during durable repeat creation.
- Reload after POST commits but before copied-graph PUT preserves every prepared
  ID/value. Copy-to-new recovery preserves incomplete sets, done flags, RPE, and
  notes; it never applies repeat-last's destructive reset transformation.
- Unavailable and changed catalog entries remain visible and block invalid save
  until corrected.
- Two tabs save from one base revision; both drafts survive, and use-server,
  copy-to-new, and explicit replacement each work in isolated scenarios.
- Cancellation/failure preserves the source draft; a second replacement conflict
  pauses again.
- Deletion and server-finished conflicts expose only valid choices and never
  recreate/reopen silently.

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

- Automatic merging, per-field/set winner selection, or editing finished
  workouts.
- Dedicated repeat/clone API, templates, or offline workout creation.
- History/detail and Settings/logout screens, which arrive in Stage 13.

## Gate G12c / G12

G12c and parent Gate G12 pass when repeat-last creates a separately identified,
unfinished, current-default draft through normal durable create/save paths;
catalog incompatibilities are explicit; all lifecycle-valid conflict choices
work without premature source deletion; and the complete create/edit/save/
finish/recover core flow passes component and real-browser/two-tab tests.

Completion evidence, the Milestone C remote-QA checkpoint, and the Stage 13
marker must be recorded in `IMPLEMENTATION.md` in the Stage 12c branch before
merge.

## Completion evidence

Not yet implemented. Record the branch, repeat/recovery behavior, commands/test
counts, two-tab/catalog/lifecycle observations, remote-QA readiness, and Gate G12
acceptance mapping here before merge.
