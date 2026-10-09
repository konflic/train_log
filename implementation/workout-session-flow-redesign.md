# Workout Session Flow Redesign

**Status:** implemented on branch `workout-session-flow-redesign`; combined
Stages 12d-12g gate passed locally on 2026-10-09.

**Placement:** delivered before the remaining Stage 13 work as combined Stages
12d-12g.

## 1. Goal and product rules

Make an explicitly started `WorkoutSession` the central training object. A
`TrainingPlan` is reusable preparation; local recovery data is an implementation
detail of a started session rather than a normal navigation destination.

- Opening a screen never starts a workout.
- An account can have at most one active workout session across tabs and devices.
- A session starts only through **Freestyle session** or **Start session** on a
  selected plan.
- Navigating away, returning, or refreshing resumes the same session.
- Finishing saves the final exercises and sets and the finish time atomically.
- The center navigation button opens the active session when one exists and
  shows a green glow throughout the app.
- Home has no start-workout button.
- The user enters bodyweight only in Settings. Sessions automatically record
  that saved value when they start.

### Documentation integration

`PLAN.md` and `IMPLEMENTATION.md` now adopt explicit sessions, Phase 1 training
plans, immutable Settings-derived bodyweight snapshots, and routine resume in
place of quick start and normal draft selection.

The existing Phase 3 template proposal becomes `TrainingPlan`; do not implement
a second overlapping template system. Each delivery stage must record its
completion evidence and next-stage marker in its own stage PR, following the
repository workflow.

## 2. Current behavior and causes

The inspected implementation explains both reported draft problems:

- `frontend/src/features/workout/WorkoutRoute.svelte`: `openCurrent()` redirects
  to `/workouts/new` when no active workout exists. Route setup immediately calls
  `quickStart()`, creating a workout and local draft merely by opening the center
  route.
- The same route's `recover()` calls `createRecoveryDraft()`, which assigns a new
  draft ID. Normal route teardown releases the editor association, so returning
  leads back to draft selection.
- `frontend/src/db.ts`: `createRecoveryDraft()` copies the source while retaining
  the original record, allowing repeated recovery to accumulate alternatives.
- `frontend/src/features/workout/OfflineRecovery.svelte` also clones a selected
  draft and must be included in the recovery redesign.
- `frontend/src/features/home/HomeRoute.svelte` contains the Home quick-start
  action that must be removed.
- `frontend/src/features/workout/WorkoutEditor.svelte` allows recorded bodyweight
  entry, although the backend already copies profile bodyweight at creation.

Fixing only labels or hiding the draft list would leave the lifecycle problems
in place. Start, resume, local ownership, and backend enforcement must agree.

## 3. Main user flow

```text
Center button
|
+-- Active session exists
|   +-- Open that session directly
|
+-- No active session
    +-- Choose session type
        |
        +-- Freestyle session
        |   +-- Start session -> open empty session editor
        |
        +-- Plan session
            +-- Training plans
                +-- No plans -> offer Create plan
                +-- Select plan -> preview -> Start session
```

Selecting **Freestyle session** is the explicit start action; no additional
start button is required. Selecting **Plan session** only opens plan selection.
Creating, saving, selecting, or previewing a plan does not start a session.

### Center navigation state

| State | Appearance | Action |
|-------|------------|--------|
| No active session | Normal | Open session-type chooser |
| Active session | Green glow | Resume the existing session |
| Start request unresolved | Pending indicator | Resolve the same start request |
| Finish awaiting acknowledgement | Pending indicator | Open the finishing session |

- Active state belongs to the authenticated app shell, not the mounted workout
  route. The glow remains visible on Home, Catalog, History, and Settings.
- Provide an accessible label such as **Resume active session**; color must not
  be the only indication of state. Keep both themes and focus states legible.
- Revalidate state on authentication, relevant session mutations, and returning
  to the app. Cross-tab notifications may trigger refresh; the server remains
  authoritative across devices.
- A failed status check is not proof that no session exists. Resume a known
  locally available session or show a retry state rather than starting another.
- An unresolved start or finish blocks another local start until its outcome is
  resolved. Do not regenerate request IDs to escape an uncertain response.

### Home

Remove **Quick start workout**. Keep recent history and weekly summary. An
active-session summary may remain informational; the center button provides the
consistent session entry point.

## 4. Domain model

### WorkoutSession

Use the existing workout storage and revisioned save protocol as the foundation.
The logical model is:

```text
WorkoutSession
  id
  user_id
  type: freestyle | from_plan
  source_plan_id: optional
  name
  started_at
  ended_at: optional
  bodyweight_kg: read-only snapshot from Settings
  revision
  exercises[]
    sets[]
```

- `started_at` is recorded only after an explicit start action.
- `ended_at = null` means active; a finished session is read-only under the
  existing lifecycle rules.
- Both session types share the same editor, persistence, and finish behavior.
- A plan-based session may add or remove exercises and sets during training.
- Starting from a plan creates independent exercise/set IDs and initially
  incomplete sets. Actual RPE is initially unset.
- The copied graph is session-owned. Editing or deleting the source plan cannot
  change an active or historical session.
- Preserve the session name and graph if the source plan is deleted; an optional
  source reference must not cascade deletion into sessions.
- The existing `/workouts` API and `workouts` table can represent this model; a
  physical rename is not required. Distinguish `WorkoutSession` from existing
  authentication sessions in code and documentation.

### TrainingPlan

```text
TrainingPlan
  id
  user_id
  name
  notes
  revision
  exercises[]
    catalog_id
    notes
    sets[]
      target_reps
      target_weight_kg
      side
      optional bodyweight-percentage override
```

Plans contain preparation, not recorded performance. They have no session timer,
completion flags, actual RPE, or recorded user bodyweight. Target values follow
the existing metric-only integer contract and exercise load rules.

Provide a dedicated **Training plans** screen with:

- List, create, view, edit, and delete.
- Ordered exercises and sets selected from the visible exercise catalog.
- Explicit save and clear handling of unsaved form changes.
- Empty-state **Create plan** action.
- Plan preview with **Start session**.

Make plan management accessible from Settings as well as the session chooser,
so it remains reachable while a session is active. Saving a plan never starts
training or contributes to workout history/statistics.

User-created plans are sufficient for the initial delivery. Predefined plans
can be added once their contents and ownership/editing rules are selected.

## 5. Settings-only bodyweight

1. The user enters **Bodyweight (kg)** in Settings.
2. Starting either session type reads the saved profile value on the server.
3. The session records that value as a read-only snapshot.
4. Remove the workout editor's bodyweight input and associated raw-input logic.
5. Later Settings changes apply to newly started sessions, not existing session
   snapshots or historical calculations.

If bodyweight is unset, retain `null` and offer a Settings link where relevant.
Do not substitute zero or fabricate load-dependent totals. Bodyweight remains
optional under the existing missing-data rules.

Enforce this rule in the API: ordinary workout saves cannot change recorded
bodyweight. New sessions created through any recovery action also obtain their
own snapshot from Settings rather than copying another session's bodyweight.
The request-schema transition must account for existing immutable pending saves
and accepted retry receipts; see migration requirements below.

## 6. Persistence and recovery

Retain durable local edits, revision checks, account isolation, and exact-request
retries. Replace routine draft selection with session resume.

- **Before start:** opening the chooser or browsing plans creates no workout or
  workout recovery record. Unsaved plan form state is separate from sessions.
- **On explicit start:** persist the immutable start request before sending it,
  so an uncertain response can be resolved using the same ID.
- **During training:** persist edits against the existing session.
- **On navigation:** reuse the same document-local editor identity rather than
  cloning its data. Scope editor ownership beyond route mount/unmount.
- **On reload:** resume an unambiguous persisted session copy automatically,
  resolving pending operations before issuing newer requests.
- **On genuine conflict:** ask which changes to keep only when versions really
  diverge or authoritative lifecycle changes require a decision.

Cross-tab ownership must prevent two tabs from overwriting the same local
record. Reclaim a persisted editor only when safe; preserve independent edits
from concurrent tabs using the existing revision/conflict protections. Recovery
alternatives must not accumulate merely through navigation or repeated resume.

Update online recovery, offline recovery, finish acknowledgement, logout, and
account-switch handling together. A finished session's local state is retired
only after durable acknowledgement; unresolved edits are never silently merged
or deleted.

**Copy local work to new workout** must obey the one-active-session rule. It
cannot create a second active session as a conflict-recovery shortcut. Retain
the source work until the selected recovery action succeeds.

Starting a new session still requires connectivity. Continuing an already loaded
session offline retains the existing foreground synchronization behavior.

## 7. Backend implementation

### Explicit and atomic session start

Extend the existing create operation with session type and, for planned starts,
the selected plan ID and revision. In one write transaction:

1. Resolve an exact retry of an existing start request before applying the
   one-active-session check for new requests.
2. Reject a different start if the account already has an active session.
3. Validate ownership, plan revision, catalog visibility, and graph constraints.
4. Read bodyweight from Settings.
5. Create the session and, when applicable, its independently identified plan
   graph with recorded load settings.
6. Return the authoritative session graph.

A failed planned start must not leave an empty session or partially copied graph.
An exact start retry must resolve the existing session even if the source plan
has subsequently changed or been deleted; do not instantiate the plan again.

Enforce one active session per account with a database uniqueness constraint,
after legacy data is reconciled, plus a classified API conflict. Double-clicks
and simultaneous starts from different devices must not create two sessions.
The client resolves an existing active session through an owner-scoped read.

### Training plan API and storage

```text
GET    /training-plans
POST   /training-plans
GET    /training-plans/{id}
PUT    /training-plans/{id}
DELETE /training-plans/{id}
```

- Add numbered migrations for plan, plan-exercise, and plan-set storage and
  session-origin metadata.
- Use owner-scoped access, bounded pagination and graph sizes, explicit schemas,
  parameterized SQL, and short transactions.
- Protect updates and deletion with revision checks.
- Apply existing strict integer, ordering, side, catalog-visibility, and load
  validation rules to plan targets.
- Protect catalog entries referenced by plans from deletion.
- Plan deletion removes only the plan graph, preserving instantiated sessions.
- Reuse existing libraries and focused helpers; no new dependency is expected.

## 8. Delivery stages and verification gates

These stage labels were delivered together on the redesign branch.

| Stage | Scope | Exit gate |
|-------|-------|-----------|
| **12d - Lifecycle contract and backend** | Update product contract and active stage order; session type; single-active enforcement; Settings-derived bodyweight; migration procedure | Concurrent starts, exact retries, ownership, migration, and bodyweight invariants pass |
| **12e - Start/resume navigation** | Session chooser, explicit freestyle start, persistent active-session state, green indicator, remove Home start button, stable local recovery identity | Repeated navigation and reload create no extra sessions or recovery copies |
| **12f - Training plans** | Plan storage/API, management screen, editor, preview, atomic start-from-plan | Create/edit/delete/start flow works; session remains independent of plan |
| **12g - Upgrade and regression gate** | Legacy server/local data, offline/conflict flows, account switching, visual and accessibility checks | Relevant backend/frontend checks, production build, migration tests, and E2E pass |

Keep intermediate stages coherent: expose the Plan session destination with its
working management/start flow in Stage 12f rather than shipping a broken action.
Run each stage's relevant checks before proceeding and record actual evidence;
planned tests are not completion evidence.

### Main code areas

- `backend/app/schemas/workouts.py`, `backend/app/services/workouts.py`, and
  `backend/app/api/workouts.py`: explicit start, single-active invariant,
  session-origin metadata, and read-only bodyweight.
- `backend/migrations/`: schema upgrades and constraints.
- New resource-specific training-plan schemas, service, routes, and tests using
  existing backend conventions.
- `frontend/src/App.svelte`: shell-level active-session state and center action.
- `frontend/src/features/home/HomeRoute.svelte`: remove quick start.
- `frontend/src/features/workout/`: start/resume routing, editor, synchronization,
  offline recovery, and snapshot handling.
- `frontend/src/features/drafts/` and `frontend/src/db.ts`: durable identity,
  pending requests, ownership, and safe upgrade behavior.
- `frontend/src/routes/SettingsRoute.svelte`: bodyweight wording and plan access.
- `frontend/src/api.ts` and new training-plan feature components: API types and
  plan management.
- Existing auth/logout, model, persistence, and browser tests: update changed
  lifecycle assumptions while preserving meaningful recovery coverage.

## 9. Existing-data migration and rollout

Legacy data may already violate the proposed single-active-session rule. Design
and verify reconciliation before installing the unique constraint.

- Preserve completed workouts and their recorded inputs.
- Detect accounts with multiple unfinished workouts. Do not silently finish
  them, delete them, or select the newest while hiding the others.
- Provide an explicit reconciliation procedure so users can resolve legacy
  unfinished sessions before the constraint becomes mandatory. Finalize this
  procedure and deployment ordering in Stage 12d; a unique-index migration alone
  is insufficient.
- Preserve meaningful unsynchronized local edits and distinct pending requests.
- Reconcile equivalent recovery copies only when doing so loses no distinct
  edits, receipts, or pending work. Empty appearance alone is not proof that a
  record is disposable.
- Define how old pending create/save payloads and accepted retry fingerprints
  survive the new schema/API contract. Never rewrite immutable pending payloads
  and then claim they are exact retries.
- Verify that older tabs cannot bypass new session invariants or write a
  per-session bodyweight override.
- Exercise upgrades using isolated SQLite and browser-storage fixtures, including
  foreign-key/integrity checks and preservation of recoverable local work.

Roll out migration 0004 with this reconciliation procedure:

1. Back up and verify the database before deploying the new application.
2. Inventory legacy conflicts with a read-only query:

   ```sql
   SELECT user_id, COUNT(*) AS active_count
   FROM workouts
   WHERE ended_at IS NULL
   GROUP BY user_id
   HAVING COUNT(*) > 1;
   ```

3. Do not mutate workout content with administrative SQL. Notify each affected
   owner and have them finish or revision-delete unwanted sessions through the
   owner-scoped workout API. Keep all rows and local recovery data until that
   choice is acknowledged.
4. Migration 0004 preserves legacy rows with `session_type = NULL` and installs
   the unique index for all new explicit sessions. The service counts unfinished
   legacy rows when deciding whether a new start is allowed, so an affected
   account cannot add another session while reconciliation is pending.
5. Re-run the inventory until every account has at most one unfinished row, then
   deploy normally. Do not run an older application version alongside the new
   version because it does not enforce the explicit-start protocol.

Migration implementation is included in this delivery. Production data cleanup
and deployment remain explicit operator actions.

## 10. Acceptance tests

1. Center -> Home -> center returns to the chooser; zero workouts and workout
   recovery records are created.
2. Browse, create, edit, and preview a plan without starting; zero sessions are
   created and no workout statistics change.
3. Start freestyle, navigate repeatedly, and return; the session ID and local
   editor identity remain the same.
4. Reload an active session; it resumes without routine draft selection.
5. Repeated online/offline resume does not accumulate recovery copies.
6. Double-click start or start simultaneously in two tabs/devices; exactly one
   active session exists.
7. Lose a start response; retry resolves the original session without generating
   another workout or graph.
8. Start from a plan; the graph is independent, all sets are initially incomplete,
   and actual RPE is unset.
9. Change or delete the source plan after start; active and historical session
   data remains unchanged. Exact start retries do not recopy the plan.
10. Reject an inaccessible or stale plan at start without a partially created
    session.
11. Finish with unsaved changes; final graph and finish are accepted together,
    and local recovery state is retired only after acknowledgement.
12. Center state remains correct across navigation, refresh, pending operations,
    and another tab/device finishing the session after revalidation.
13. Bodyweight is editable only in Settings. Both start modes automatically obtain
    its saved value, and ordinary workout saves cannot override it.
14. Changing Settings bodyweight leaves existing session snapshots unchanged;
    unset bodyweight stays unknown rather than becoming zero.
15. Offline recovery, conflicting edits, authentication expiry, logout, and account
    switching preserve edits without cross-account uploads or silent merges.
16. Recovery copy-to-new cannot bypass single-active enforcement.
17. Upgrade fixtures with multiple unfinished workouts, duplicate local copies,
    and pending requests preserve data and reach the new invariants through the
    documented reconciliation procedure.
18. Home has no start-workout button; the center action and plan screens are
    keyboard-accessible, have suitable touch targets, and are legible in both
    themes.

Run the relevant verification commands owned by `IMPLEMENTATION.md`; include
backend transaction/migration tests, frontend component/coordinator tests, and
Playwright coverage for the actual navigation regressions. Do not substitute
only mocked UI tests for concurrency or storage-upgrade verification.

## 11. Additional recommendation requiring a product decision

Provide a confirmed **Discard session** action for accidental starts, using the
existing revision-checked deletion behavior. This lets the user exit an empty
or abandoned session without recording it as a completed workout. Confirm this
addition before treating it as required scope; preserve uncertain-delete and
local-edit recovery semantics if adopted.

## 12. Completion evidence

- Backend: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
  `pytest -q`, and `pip check` pass; 649 tests.
- Frontend: `npm run check`, `npm run lint`, `npm run test:unit`, and
  `npm run build` pass; 21 files and 196 unit tests.
- Browser: `npm run test:e2e` passes with 40 Chromium tests, including chooser
  no-side-effect behavior, plan creation/start, navigation resume, reload,
  offline recovery, multi-tab conflicts, and active-session copy prevention.
- No dependency was added.
- Next stage: Stage 13 history/detail, remaining Settings work, deletion, and
  logout.
