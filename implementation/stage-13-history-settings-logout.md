# Stage 13 - History, Settings, and logout

Status: planned. Start after Gate G12 is merged.

Estimate: 2.5 person-days.

This file is the detailed implementation contract for Stage 13. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Complete the Phase 1 user client with finished-workout history and previous
performance, profile/theme settings, and logout that synchronizes or explicitly
discards account-local work without cross-account upload or premature cleanup.

References:

- `PLAN.md` sections 3, 6, 7, and 8.
- `IMPLEMENTATION.md` Gate G13 and acceptance checks 2, 10-12, and 14.
- Stage 8a comparisons, Stage 9 theme module, and Stage 11 account cleanup.

## Scope

- Add `features/history` list/detail routes and `features/settings`.
- Complete Home recent-history navigation into read-only detail.
- Add theme, display name, bodyweight default, UTC offset, and logout controls.
- Preserve metric-only presentation throughout. There is no unit preference or
  imperial conversion.
- Add confirmed revision-checked workout deletion from finished detail and active
  Home/editor actions. This completes Phase 1's deletion feature using Stage 7's
  API; it is not an edit/reopen operation.
- No new dependency is expected.

## History list and detail

- List finished workouts newest first with bounded paging and optional local
  date filters using exact `YYYY-MM-DD` query values. Render loading, empty,
  error/retry, and stable page states.
- Fetch detail through `GET /workouts/{id}` and resolve catalog labels for the
  visible exercise IDs without changing recorded load snapshots. Referenced
  custom entries remain owner-visible; an unavailable label falls back to a
  neutral identifier rather than hiding the exercise.
- Render immutable workout metadata, recorded bodyweight, duration from
  whole-second timestamps, ordered exercises/sets, fixed metric values, and
  completion state. Display instants at the profile's fixed UTC offset, not the
  browser's timezone. Compute totals from recorded inputs with Stage 9 helpers
  (detail has no aggregate-total fields), preserving completeness/null semantics.
  Do not offer edit/reopen.
- Show each exercise's server-selected previous session occurrence and completed
  sets. Pair comparisons by the explicit current/previous IDs returned by the
  API, not array positions.
- Respect `load_compatible`: incompatible or unknown load-based values remain
  unavailable while reps can still be compared. Preserve negative deltas and
  known zero distinctly from `null`.
- If displaying percentages, use Stage 9 BigInt floor division and return
  unavailable for zero/unknown denominator. Do not recalculate server deltas or
  use current profile/catalog defaults for historical totals.

## Workout deletion

- Confirm the identified workout and displayed revision, then send
  `DELETE /workouts/{id}?revision=N`. Quiesce that editor's saves first; resolve
  uncertain PUTs before deleting and explicitly retain or discard local edits.
- An empty 204 confirms deletion. A lost response is resolved by owner-scoped
  GET: 404 establishes absence; an existing workout requires a fresh user decision.
  On 409, refresh and require confirmation again, never silently retry deletion
  at a newer revision. Auth/network failures preserve recovery state.
- Refresh Home/history/statistics after confirmed absence. Keep other drafts
  recoverable under Stage 11c's missing-workout policy; do not clear another tab's
  edits or recreate the deleted workout. Clear only explicitly discarded local
  work after confirmed absence.

## Settings

- Theme controls call the Stage 9 theme module, apply immediately, and persist
  the explicit light/dark choice. Verify the entire routed app in both themes.
- Profile form edits display name and optional default bodyweight with strict
  integer/null behavior matching PATCH semantics. Omitted fields remain
  untouched; an explicit clear sends null.
- Offer fixed UTC offsets in whole-hour steps across the supported -12 through
  +14 hour range, labeled clearly as UTC offsets rather than time zones. If the
  API returns an existing non-hour offset, display that exact current value and
  do not coerce it until the user deliberately selects a supported option.
- After profile success, replace the authenticated public user state and refresh
  calendar-dependent Home/history data. Profile/catalog edits must not rewrite
  recorded workout totals or comparisons.
- Show backend validation/conflict/network errors without losing unsaved form
  input. Settings contain no unit selector.

## Logout contract

Before calling logout, inspect all local work for the current account:

- If clean, call `POST /auth/logout`, then clear that account's IndexedDB records
  and authenticated in-memory state.
- If dirty/pending/conflicted/storage-failed work exists, present explicit
  **Synchronize and log out**, **Discard local work and log out**, and Cancel
  choices. Explain work that cannot currently synchronize.
- Synchronize uses the normal coordinator and same-account authentication. Call
  logout only after every pending/dirty draft is durably acknowledged or its
  discard is explicitly approved, including unselected recovery alternatives. A
  conflict, validation, storage, auth, or network failure returns to recovery
  with every draft intact.
- Discard requires confirmation. Do not delete local records merely on button
  press; retain them if the logout request fails or is cancelled.
- Use Stage 11c's cross-tab writer barrier before inspection and retain it through
  cleanup. A changed draft invalidates the inspected snapshot and requires a new
  decision. Prevent edits/responses from repopulating account data after cleanup.
- A lost logout response may already have revoked the session. Resolve it with
  `GET /auth/me`: 401 establishes logged-out state and permits the already-approved
  cleanup; the same account still authenticated permits explicit logout retry.
  Network/5xx remains uncertain, retains records, and keeps uploads paused. A
  different account result must not be logged out or have its records cleared.
- After an empty 204 logout, atomically clear only the old account's drafts and
  pending records. If local cleanup fails, remain logged out, show a local-data
  cleanup error/retry, and never expose those records to a later account.
- Invalidate coordinator operation identities before changing current user so a
  delayed old-account response cannot update, upload, or clear new-account
  state.

The server cookie remains HttpOnly; frontend code never reads or manually
deletes its value.

## Mobile and accessibility rules

- History/detail/settings remain single-column at phone width with bounded
  desktop reading width, visible headings, 44 CSS pixel controls, and sticky
  actions only where they do not cover content.
- Comparison direction, unknown values, sync/discard consequences, and status
  are conveyed with text rather than color alone.
- Dialogs trap/restore focus appropriately using the platform and existing
  implementation; add a headless dependency only if native/simple semantics
  prove insufficient and review it under the repository dependency rules.

## Verification

Component tests cover history paging/date queries, detail rendering, ID-based
pairing, incompatible/unknown/zero/negative comparisons, floored percentages,
profile PATCH construction, offset handling, theme persistence, and every logout
decision/failure transition, including uncertain logout and new edits after
inspection. Cover deletion confirmation, revision conflict, and absence recovery.

Playwright against the real backend covers:

- Navigate finished history and render previous-session comparison.
- Delete active and finished workouts; stale revisions fail visibly, a lost DELETE
  response resolves by GET, and another tab's local draft remains recoverable.
- Change profile bodyweight and catalog defaults, then prove existing detail
  inputs/totals/comparisons remain based on recorded snapshots.
- Toggle light/dark, navigate, reload, and verify root persistence plus visible
  focus/text/input/status legibility at phone and desktop widths.
- Update display name/bodyweight/offset and verify Home's local week refresh.
- Failed synchronize during logout preserves drafts and session; Cancel does
  nothing; confirmed discard plus successful logout clears only that account.
- Switch accounts with old pending work and a delayed response; no old draft is
  listed/uploaded under the new account and the delayed response changes no new
  state.
- Logout returns an empty 204 and subsequent authenticated reads fail without
  exposing cookie/session data.
- Lose logout's response after revocation, resolve `/auth/me` to 401, and complete
  approved cleanup. Unselected dirty drafts and concurrent edits in another tab
  cannot be silently deleted or written back after cleanup.

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

- Editing/reopening finished workouts, dedicated charts, templates, or bodyweight
  history.
- Imperial units or a unit selector.
- Admin UI, production deployment smoke, service workers, or cold offline start.

## Gate G13

G13 passes when users can review finished history and truthful previous-session
comparisons, update profile and persistent legible themes without rewriting
history, delete workouts with revision checks and recoverable local work, and
log out only after successful synchronization or explicit discard, with
account-local cleanup and delayed responses unable to cross account
boundaries. All frontend checks pass locally and in CI, completing Milestone C.

Completion evidence, the Milestone C exit, and the Stage 14 marker must be
recorded in `IMPLEMENTATION.md` in the Stage 13 branch before merge.

## Completion evidence

Not yet implemented. Record the branch, completed client surface, commands/test
counts, mobile/theme/history/logout/account-switch observations, and Gate G13
acceptance mapping here before merge.
