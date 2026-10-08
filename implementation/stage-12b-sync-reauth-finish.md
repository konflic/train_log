# Stage 12b - Synchronization, reauthentication, and finish

Status: planned. Start after Gate G12a is merged.

Working estimate: part of Stage 12's 4 person-day budget.

This file is the detailed implementation contract for Stage 12b. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Connect the real editor to Stage 11's coordinator so ordinary saves, offline
continuation, response loss, session expiry, and atomic finish are visible and
recoverable without stale responses replacing input or an unacknowledged finish
deleting a draft.

References:

- `PLAN.md` section 6, Bulk-save, finishing, and client persistence.
- `IMPLEMENTATION.md` Gate G12b and acceptance checks 1-5 and 11.
- Stage 6c's full-state PUT protocol and Stage 11b-11c coordinator contracts.

## Scope

- Connect editor changes and explicit save/finish controls to the existing
  coordinator.
- Add foreground reconnect handling, visible synchronization state, and
  same-account reauthentication that preserves the editor.
- Integrate conflict/deletion detection with a retained-draft paused screen;
  polished recovery choices arrive in Stage 12c.
- Update Home active-workout cards to resume through the editor/recovery flow.
- No new dependency is expected.

## Save construction and scheduling

- Build the complete PUT payload from one committed draft version: base
  revision, fresh save UUID, all nullable metadata, recorded bodyweight, null
  `ended_at`, and the full ordered graph. Never submit order/snapshot/server
  fields.
- Client checks prevent known-invalid sends, but backend validation remains
  authoritative and any rejection preserves the draft.
- Keep at most one immutable pending PUT per draft. Edits made while it is in
  flight remain newer local changes and are not folded into that payload or
  overwritten by its response.
- Foreground autosave may coalesce rapid edits after local persistence, and the
  user can request Save now. Both paths use the same coordinator; no parallel
  saves, interval daemon, unload beacon, or background sync.
- Browser `online`/`offline` events may trigger status and a foreground retry,
  but only an actual request result establishes connectivity. Retry uncertain
  work before constructing a newer payload.

## Visible status contract

Expose text plus non-color indication for:

- **Saving locally:** the latest visible edit is not yet committed to IndexedDB.
- **Locally saved:** committed locally but not yet acknowledged by the server.
- **Syncing:** the exact durable pending payload is in flight or its
  acknowledgement is being committed locally.
- **Synced:** the latest visible committed draft version is server acknowledged.
- **Offline:** network failure left durable local/pending work.
- **Authentication required:** upload is paused with all local work retained.
- **Conflict:** automatic saving stopped; local and fetched server state are
  retained for Stage 12c recovery.
- **Finish pending:** the final immutable graph/time is durable but not yet
  acknowledged and retired.
- **Storage error / correction required:** no claim of local/server safety.

Status is derived from durable/coordinator state, not a timer or optimistic
request start. `synced` requires the latest visible edit to be committed and
acknowledged; a newer in-memory edit or failed local write overrides an older
synced state.

## Reauthentication

- On 401, stop uploads and present login as an in-context dialog/page that does
  not destroy the editor route or draft.
- Submit credentials through the normal login endpoint. Resume only if
  `GET /auth/me`/login returns the same account ID as the draft.
- A different account result leaves the draft paused and returns to the account
  boundary flow; it never retags or uploads the draft.
- Cancel, invalid credentials, throttling, network failure, and repeated expiry
  preserve all local and pending state.
- After same-account success, follow Stage 11c ordering: uncertain pending work
  first, then authoritative GET, then any newer local save.

## Finish contract

- If an ordinary PUT is pending or uncertain, disable Finish with an explanation
  until that request is durably resolved. Do not create a second pending payload,
  cancel an uncertain save, or finish at its stale base revision.
- Once eligible, pause autosave and lock editing synchronously on Finish,
  drain local writes, then validate/capture the latest visible committed graph.
  If local persistence or validation fails, unlock for correction without sending.
- Finish validates the current editor graph, samples one client-recorded
  timezone-aware instant, and persists one immutable final PUT with that
  `ended_at` and all unsynced sets. Do not send a preliminary save.
- Keep the editor read-only through payload persistence and while finish is
  pending, including after reload. This avoids accepting newer edits while the
  finish transaction is committing or after the server becomes read-only.
- Show finish pending through request, response loss, reload, reauthentication,
  and local acknowledgement persistence. Retry the exact save ID/content/time.
- Only after the server acknowledgement and its local IndexedDB transaction both
  succeed may the active editable draft be retired and navigation move to the
  finished detail route/placeholder.
- A validation rejection unlocks the editor for correction while preserving the
  final intent; a conflict/deletion/finished response enters paused recovery.
  Correction uses Stage 11c's atomic retirement of definitively rejected work and
  a new save ID for changed content. Never fabricate a new finish time during an
  exact retry; changing an invalid time is an explicit correction.

## Failure handling

- Network/503 retains pending content; offer retry and obey the coordinator's
  bounded foreground policy.
- 409/404 stops automatic save and preserves both local draft and any fetched
  server state. Stage 12b explains the pause but does not yet expose replacement
  or copy controls.
- 422/graph/catalog failures identify correction-required fields/state where the
  API path allows; never echo rejected secret/raw payload data.
- A server success followed by local acknowledgement failure remains syncing/
  storage error, not synced. Exact retry recovers through the latest receipt.

## Verification

Component/coordinator integration tests cover payload construction, one-save
serialization, coalesced newer edits, every status transition, retry ordering,
same/different-account reauthentication, and finish read-only/retirement rules.

Playwright against the real backend covers:

- Edit, local persistence, save, acknowledgement, and revision display.
- Edit while a PUT is delayed; the older response does not replace newer input
  and a subsequent payload uses the acknowledged revision.
- Available-shell offline edit, reload/recovery, reconnect, and sync.
- Response loss after server commit for ordinary save and finish; exact retry
  does not double increment.
- Session expiry, same-account reauthentication, and retained draft.
- Finish with unsynced sets and delayed upload; draft remains until durable
  acknowledgement and then the server detail is finished with the final graph.
- Finish attempted during an ordinary in-flight save is blocked; Finish after
  acknowledgement captures the latest graph. Delayed local writes and clicks or
  keystrokes during finish persistence cannot leave edits outside the final PUT.
- A real two-tab conflict pauses the losing editor with its draft intact.

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

- Conflict recovery actions and repeat-last; both belong to Stage 12c.
- Automatic merge, background sync, unload saves, or cold offline app startup.
- Editing/reopening a finished workout.
- Deleting a server workout from the editor.

## Gate G12b

G12b passes when local editor changes move honestly through local, syncing, and
server-acknowledged states; offline/reload/response-loss/session-expiry paths
preserve and resume exact work; stale responses cannot overwrite newer input;
and one immutable final PUT atomically saves and finishes without retiring the
draft before durable acknowledgement.

Completion evidence and the Stage 12c marker must be recorded in
`IMPLEMENTATION.md` in the Stage 12b branch before merge.

## Completion evidence

Not yet implemented. Record the branch, status/finish behavior, commands/test
counts, response-loss/offline/reauth/browser observations, and Gate G12b
acceptance mapping here before merge.
