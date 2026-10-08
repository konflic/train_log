# Stage 11c - Reconnect, conflict, and account handling

Status: in progress. Gate G11b merged in PR #17 on 2026-10-08.

Working estimate: part of Stage 11's 3 person-day budget.

This file is the detailed implementation contract for Stage 11c. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Complete the headless persistence/coordinator layer with deterministic reconnect
ordering, conflict and deletion recovery actions, session-expiry pauses, and
strict account isolation before the production editor depends on it.

References:

- `PLAN.md` section 6, Client persistence and conflict handling.
- `IMPLEMENTATION.md` Gate G11c/G11 and acceptance checks 1-4 and 11.
- Stage 7 deletion semantics and Stage 11a-11b persistence contracts.

## Scope

- Extend the save coordinator with startup/reconnect, authentication pause, HTTP
  conflict/not-found handling, and explicit recovery commands.
- Add the minimal persisted metadata needed to resume a paused state after
  reload; do not add a generic event log.
- Extend the browser harness for two-tab conflicts, session expiry,
  reauthentication, deletion, account switching, delayed responses, and logout
  preparation/cleanup decisions.
- Stage 12c owns the polished recovery UI; Stage 11c exposes testable coordinator
  commands and plain harness controls.
- No new dependency is expected.

## Resume ordering

For each selected draft on startup, reload, or reconnect:

1. Resolve the current authenticated user through `GET /auth/me`. If unavailable,
   remain in Stage 11a's local-only recovery mode; do not block local edits or
   claim authentication from cached account context.
2. Refuse to process when that user ID differs from the draft/pending operation's
   account ID. Never relabel persisted work for the current account.
3. Resume one durable uncertain create or pending save before constructing or
   sending later work for that draft.
4. Once no uncertain operation remains, fetch the owner-scoped current workout.
5. Compare server identity/revision/lifecycle to the draft's durably acknowledged
   base. A newer revision is information, not permission to advance the local
   base or upload local content.
6. Continue automatic foreground save only when the server state matches the
   acknowledged base and no paused conflict/deletion/auth condition remains.

Serialize this sequence per draft. Separate drafts may progress independently,
but account changes invalidate all queued callbacks through operation identity
checks.

## Failure classification

- Network/503: retain exact pending work and pause until explicit retry or a
  foreground reconnect signal. Respect `Retry-After` without an unbounded retry
  loop.
- 401: enter authentication-required, retain every local record, and send
  nothing until the same account is authenticated.
- `revision_conflict` or `save_id_conflict`: stop automatic saves, retain the
  draft and pending evidence, and fetch the server copy for a recovery decision.
- `workout_finished`: retain the draft; replacement is unavailable because
  finished workouts are read-only.
- `revision_exhausted`: stop automatic saves; replacement cannot succeed even
  while active. Offer use-server or copy-to-new, not a repeated same-workout PUT.
- 404 after create uncertainty or for an existing workout: retain the draft and
  require explicit deleted/missing recovery. PUT never recreates it.
- `graph_conflict`, `catalog_unavailable`, and 422: retain the draft and expose a
  correction-required state. They are not network retries.
- After a definitive rejected save, preserve its evidence until a corrected
  draft and retirement of that rejected pending record commit atomically. The
  corrected payload gets a new save ID; never mutate the old payload. An
  uncertain network/5xx outcome cannot use this path to bypass exact recovery.
- 413 requires reducing the payload; 403/415 and unknown HTTP errors pause with
  a visible error. Treat ambiguous server/transport failures as uncertain work,
  retaining exact content; honor 429/503 retry hints without a retry loop.
- Local storage failure: pause all state advancement for that draft even when
  the server may have accepted a request.

## Explicit recovery commands

Every command is account/draft scoped and leaves the source recoverable until
its replacement state is durably committed:

- **Use server:** persist the fetched server detail as the selected draft/base,
  then retire the superseded pending/local version. Require confirmation because
  local edits are discarded.
- **Copy local to new:** preserve the source, prepare a new draft with new
  workout/exercise/set IDs, and hand it to the durable create path. Only after
  the complete copied graph is durable and its initial save is acknowledged may
  the old recovery state be retired. Stage 12c implements graph-copy details and
  user-facing validation.
- **Replace server:** only for an active, still-owned workout. Fetch immediately,
  require explicit confirmation of the displayed fresh revision, create a new
  immutable save payload from the retained local graph at that revision with a
  new save ID, and submit through the normal durable path. A second conflict
  returns to paused state; never loop or merge automatically.
- **Deleted/missing workout:** allow confirmed local discard or copy-to-new;
  there is no server version to use. Reusing the old workout ID/create request
  is a separately confirmed action only for an
  uncertain create, never an automatic PUT-to-POST conversion.

## Account and logout preparation

- Every queued request, storage operation, response handler, and recovery command
  carries account and draft identity and rechecks it before mutation.
- Authenticating a different account pauses old-account work. It never uploads,
  lists, or clears that account's drafts through the new account context.
- Cookies are shared across same-origin tabs. Coordinate login/logout account
  transitions across tabs, pause upload scheduling before changing the session,
  and invalidate stale account context on foreground return. Recheck `/auth/me`
  before resuming; an in-memory user or a separate browser context test alone
  does not establish same-account safety.
- Expose `inspectAccountWork(accountId)` so Stage 13 can determine clean, dirty,
  pending, conflict, and storage-failed drafts before logout.
- Expose two explicit logout preparations: synchronize selected account work to
  completion, or confirm discard. Actual logout UI/API sequencing arrives in
  Stage 13.
- Account-local deletion is one bounded IndexedDB transaction over drafts and
  pending stores. Every unsynchronized draft, including unselected recovery
  alternatives, must be synchronized or explicitly approved for discard before
  account-wide cleanup. A successful selected save alone does not authorize
  deleting the rest. Stage 13 owns logout confirmation before actual cleanup.
- Quiesce account writers across tabs for logout preparation and recheck the
  inspected change numbers transactionally before cleanup. Invalidate old writer
  identities in durable account state so late writes or suspended tabs cannot
  repopulate cleared records. If work changes after inspection, ask again rather
  than clearing unseen edits; failed/cancelled preparation preserves records.

## Verification

Coordinator/unit tests cover the complete transition matrix, including:

- Pending-first then GET ordering after reload/reconnect.
- Newer server revision never silently changes the draft base.
- 401 pause and same-account resume; different-account login cannot resume work.
- Every stable PUT failure classification and allowed recovery commands.
- Use-server, copy-to-new preparation, and one-shot explicit replacement,
  including failed/cancelled storage/network steps.
- Delayed response after account switch or draft replacement is ignored.
- Logout synchronization/discard preparation and atomic account-local cleanup.
- Corrected 422/graph/catalog payloads use a new save ID; revision exhaustion and
  unclassified HTTP failures never enter an automatic retry loop.

Playwright against the real backend covers two real tabs saving from one base
revision, one success and one conflict, both drafts surviving reload, each
headless recovery action, session expiry then same-account authentication,
server deletion, and switching accounts while a response is delayed. Assert no
cross-account request and no silent recreation.

Use pages in the same browser context for cookie-sharing/account-switch cases;
include logout while another tab edits and a suspended writer resumes afterward.

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

- Automatic merge, per-set last-write-wins, server locks, or cross-tab leader
  election.
- Timed/background retry daemons or cold offline application startup.
- Production editor/status/recovery presentation and actual logout controls.
- Uploading any draft under a different authenticated account.

## Gate G11c / G11

G11c and parent Gate G11 pass when pending-first recovery ordering is
deterministic, conflicts and deletion stop automatic work without losing drafts,
all recovery commands are explicit and durable, session expiry preserves state,
and queued work/responses/cleanup cannot cross account or draft boundaries in
coordinator and real-browser tests.

Completion evidence and the Stage 12a marker must be recorded in
`IMPLEMENTATION.md` in the Stage 11c branch before merge.

## Completion evidence

The current working tree adds account-guarded coordinator resume ordering,
classified paused recovery states, explicit use-server and replacement
preparation commands, atomic local adoption of a server copy, and stale-response
protection after an account transition. Targeted coordinator tests cover
pending-first create recovery, exact pending-save retry, account mismatch,
conflict classification, use-server persistence, and delayed account-switch
responses.

Gate G11c is not yet claimed. Add the required real-browser two-tab,
session-expiry, deletion, and logout-preparation observations plus the finalized
branch and command evidence before merge.
