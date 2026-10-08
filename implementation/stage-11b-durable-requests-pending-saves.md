# Stage 11b - Durable requests and pending saves

Status: implemented on the current working tree (pending review/merge). Gate
G11b passed locally on 2026-10-08.

Working estimate: part of Stage 11's 3 person-day budget.

This file is the detailed implementation contract for Stage 11b. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Make workout creation and full-state saves recoverable across response loss,
reload, and local acknowledgement failure without regenerating identifiers,
duplicating server work, advancing from an unacknowledged revision, or
overwriting edits made while a request is in flight.

References:

- `PLAN.md` section 6, Creation, bulk-save, finishing, and client persistence.
- `IMPLEMENTATION.md` Gate G11b and acceptance checks 2, 3, 5, and 11.
- Stage 6c's latest-receipt/exact-retry contract and Stage 11a's draft store.

## Scope

- Upgrade the Stage 11a IndexedDB schema with focused `pending_creates` and
  `pending_saves` stores keyed and indexed by account/draft identity.
- Add a small save coordinator with explicit state transitions and injected API
  and storage boundaries for deterministic tests.
- Extend the Stage 11 browser harness to trigger create, save, finish-shaped PUT,
  response loss, reload, edits in flight, and storage failures.
- Continue without the production editor, reconnect/conflict choices,
  reauthentication UI, or logout flow.
- No new dependency is expected.

## Durable create contract

A pending create stores the authenticated account ID, draft ID, workout ID, and
the exact immutable `POST /workouts` request (`id` and `started_at`).
For repeat/recovery, atomically store the prepared copied graph and its new row
IDs alongside that request before POST. They are local draft data, not POST
fields. A create acknowledgement establishes the server base without replacing
that prepared graph with the returned empty graph.

1. Generate the UUID and canonical timezone-aware start instant once.
2. Commit the pending create locally before sending any POST.
3. Reuse the exact ID and request for every deliberate retry. Never generate a
   replacement because a response was lost.
4. A 200 idempotent retry and a 201 first response are both acknowledgements.
   Atomically persist the returned authoritative detail/base revision into the
   draft and retire the pending create.
   If POST retry or GET resolution finds a progressed/finished workout, preserve
   any prepared local graph separately and require explicit recovery before
   uploading it; adopting that revision must not silently overwrite newer work.
5. If the response arrives but that local acknowledgement transaction fails,
   keep the pending create recoverable and stop. A later exact retry resolves
   through the server receipt.
6. After an uncertain result, first perform an owner-scoped GET of the original
   ID. A found workout with the expected ID and immutable `started_at`
   acknowledges creation; mismatch pauses as a create conflict. Use its actual
   revision/lifecycle, not an assumed revision 0: another client may have saved
   or finished it. A 404 is ambiguous because the server has no tombstone; do not
   silently replay or create a different workout.
   Require an explicit later choice to retry the original request or abandon it.
7. A 409 create conflict is terminal for automatic work and preserves the local
   request/draft for explicit recovery.

Creation still requires connectivity. Persisting a request is preparation for a
known online attempt, not a general offline-create queue.

## Immutable pending save contract

At most one pending PUT exists for one draft. It stores account/draft/workout
identity, the draft change number it captured, and the complete immutable API
payload including base `revision`, one generated `save_id`, nullable fields,
array order, IDs, and optional `ended_at`.

- Commit the pending record before sending it. Freeze it by value; later draft
  edits create newer draft versions but never mutate the pending payload.
- Retry only the exact persisted payload after network failure, timeout, reload,
  or uncertain response. A retry never receives a new save ID.
- Do not construct another pending save until the existing one is durably
  acknowledged or moved to an explicit conflict/error state in Stage 11c.
- Treat both a newly accepted PUT and an exact latest-receipt replay as the same
  acknowledgement path.
- In one IndexedDB transaction, persist the returned authoritative revision and
  receipt/base graph, remove the matching pending record, and rebase only draft
  content represented by the acknowledged change number. Preserve fields from
  later local edits unchanged and mark them as needing a future save.
- Refresh read-only authoritative snapshots by exercise ID even when newer edits
  exist. Never restore locally removed rows or overwrite newer writable fields;
  revalidate remaining edits against acknowledged snapshots before the next PUT.
- Guard acknowledgement by account ID, draft ID, workout ID, save ID, and the
  coordinator operation identity. A stale/delayed response cannot update a new
  editor or signed-in account.
- If local acknowledgement persistence fails, leave the pending record in place,
  report the failure, and do not advance the base revision in memory. Its exact
  retry remains safe while it is the server's latest receipt.

A finish is structurally a pending PUT with non-null `ended_at`; Stage 11b proves
its durability but Stage 12b owns editor locking, status, and draft retirement.

## Coordinator states

Keep states explicit and serial per draft, with no generic job queue:

- Draft is locally dirty with no pending request.
- Create/save payload is being persisted.
- Durable payload is ready or in flight.
- Response is received and local acknowledgement is being committed.
- Acknowledged, with either no newer edits or a newer dirty draft.
- Paused after network, HTTP conflict/not-found/auth, or local storage failure.

Only one network create/save operation runs per draft. Network availability is
an input/hint, not proof that a request will succeed. Stage 11c defines automatic
resume ordering and user recovery for paused HTTP outcomes.

## Atomic storage operations

- Add one narrow transaction that acknowledges a create and establishes the
  draft's server base.
- Add one narrow transaction that acknowledges a save, updates the base receipt,
  preserves newer editable content, and deletes exactly the matching pending
  payload.
- Never delete a pending record based only on an in-memory response or update the
  draft revision in a separate transaction.
- Schema upgrades preserve all Stage 11a drafts and indexes. Test upgrading a
  populated previous database version.

## Verification

Coordinator/unit tests cover:

- Pending create/save persistence happens before the network call.
- Lost POST response after commit, reload, GET resolution, and exact retry cause
  no duplicate and use no new UUID.
- Reload between create acknowledgement and copied-graph save preserves the
  prepared graph/IDs; an already advanced or finished create result is not reset.
- A 404 for an uncertain create pauses for an explicit decision and does not
  silently recreate a workout deleted elsewhere.
- Lost PUT and finish responses retry byte-equivalent normalized content with the
  same save ID and cause one revision increment.
- Edits during an in-flight PUT remain in the editable draft after response.
- A catalog change before first save replaces provisional snapshots on success
  without overwriting newer edits; changed load rules trigger revalidation.
- Response arrival followed by acknowledgement-transaction failure leaves the
  exact pending operation recoverable and does not advance local revision.
- Delayed/mismatched responses cannot acknowledge another account, draft,
  workout, save ID, or later coordinator run.
- Upgrade from the populated Stage 11a database preserves drafts.

Playwright against the real backend exercises response interception after the
server commits, page reload, exact recovery, editing during a delayed PUT, and a
finish-shaped pending payload. Assert server rows/revision and IndexedDB records,
not only visible success text.

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

- Automatic retries on arbitrary timers, background sync, or a general durable
  operation queue.
- Automatic conflict resolution, replacement at a fresh revision, account
  switching, logout cleanup, or reauthentication UI.
- Production workout controls or deleting a draft after finish.
- Server changes, additional receipts, or client-generated tombstones.

## Gate G11b

G11b passes when create, save, and finish-shaped requests are durable before
send; uncertain operations retry or resolve only with their original IDs and
content; acknowledgements advance revision and retire pending state atomically;
newer edits survive stale responses; and response/local-write failures remain
recoverable across reload in coordinator and real-browser tests.

Completion evidence and the Stage 11c marker must be recorded in
`IMPLEMENTATION.md` in the Stage 11b branch before merge.

## Completion evidence

Implemented locally on 2026-10-08.

- Upgraded `basefit-drafts` to schema version 2 without changing the existing
  `drafts` store. The new `pending_creates` and `pending_saves` stores use
  account/draft compound keys. The create/draft and acknowledgement/delete
  transitions run in one IndexedDB transaction; only one save may exist for a
  draft.
- Added `PendingDraftRepository` and `DraftSyncCoordinator`. They persist an
  immutable create or save before transport, reuse its original IDs and payload,
  reject a mismatched acknowledgement, retain pending work after a local
  acknowledgement failure, and preserve later editable content while updating
  acknowledged load snapshots and the server base revision. Reconnect ordering
  and conflict choices remain Stage 11c work.
- Extended the E2E-only recovery harness to create, save, and finish a real
  workout through the durable coordinator. The normal production build contains
  no harness route or failure controls.
- Added coordinator tests for persist-before-send, exact receipt retirement,
  newer input during an in-flight save, failed local acknowledgement recovery,
  and preserving the prepared graph after an empty create response. Browser
  coverage verifies durable create, save, finish, server revision, and graph.

### Verification provenance

The complete frontend gate passed locally on 2026-10-08:

```bash
cd frontend
npm run check       # 0 errors, 0 warnings
npm run lint        # clean
npm run test:unit   # 18 files, 173 tests passed
npm run build       # passed; no E2E harness in production dist
npm run test:e2e    # 25 Chromium tests passed
npm ls              # clean exact dependency tree
npm audit           # 0 vulnerabilities
```

Next stage: Stage 11c - reconnect, conflict, and account handling, after this
increment is reviewed and merged.
