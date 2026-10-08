# BaseFit - Active Implementation Plan (MVP / Phase 1)

Companion to `PLAN.md`. `PLAN.md` defines **what** to build; this file defines
the order, active gates, and completion bookkeeping for the remaining Phase 1
work.

Detailed implementation contracts live under `implementation/`, one file per
mergeable stage or substage. Completed Stage 0-6 details and gate evidence are
preserved in
[`implementation/archive-monolithic-plan-after-stage-06.md`](implementation/archive-monolithic-plan-after-stage-06.md).

Scope = `PLAN.md` section 10, **Phase 1 - Reliable, usable core**. Phases 2-3
remain out of scope.

## Current status

- **Completed baseline:** Stages 0 through 8b are merged to `master`. Stage 8b
  merged in [PR #14](https://github.com/konflic/train_log/pull/14) on
  2026-10-08 (`bf5033c`), completing the backend API and Gate G8. Gate G8b's
  local verification evidence (637 backend tests, +45) is recorded in
  [`implementation/stage-08b-stats-summary.md`](implementation/stage-08b-stats-summary.md).
  Stage 8b introduced no dependency, migration, or request-body change. Its
  new public surface is the authenticated `GET /api/v1/stats/summary` endpoint
  with its two response components; the
  history-date query parser moved unchanged into a shared API helper.
- **Frontend planning:** detailed Stages 9-13 contracts are reviewed against
  `PLAN.md` and the merged backend. Their verification matrices cover tab/account
  isolation, durable recovery, finish ordering, deletion, and logout failures;
  these are implementation requirements, not completed frontend gate evidence.
- **Stage 9-10 delivery:** at the user's request, Stages 9 and 10 plus
  container packaging are delivered in one branch, `stage-9-10-frontend`.
  Both gates passed locally: Gate G9 (shell/theme/API/numeric parity) and
  Gate G10 (register → login → guarded shell, read-only Home, catalog
  browse/create/edit) with evidence in
  [`implementation/stage-09-frontend-foundation.md`](implementation/stage-09-frontend-foundation.md)
  and
  [`implementation/stage-10-auth-home-catalog.md`](implementation/stage-10-auth-home-catalog.md).
  Container packaging (ahead of the Stage 15 production gate, which still
  owns the ship evidence): optional backend `STATIC_DIR` single-origin SPA
  serving (+6 backend tests, 643 total green), multi-stage `Dockerfile`
  (node build → python runtime, non-root, migrations in the entrypoint,
  stdlib healthcheck), `docker-compose.yml` for real-host deployment behind
  a TLS proxy with a persistent volume, `docker-compose.test.yml` with a
  disposable tmpfs database, `docker/smoke.sh` public-API deployment smoke,
  `DEPLOYMENT.md`, and a CI `docker` job. Verified locally: disposable and
  production-topology stacks healthy, smoke green, restart preserves
  sessions/data with a no-op migration run, and the production bundle in
  the image contains no e2e-only hook.
- **Stage 11a delivery:** implemented and reviewed on
  `stage-11a-local-persistence`. Review fixed rapid-edit acknowledgement races,
  missing local-only recovery, shallow record validation, unbounded reads,
  blocked-open handling, and a private npm registry URL. Recovery uses the
  normal session retry state and explicit account-scoped selection; the
  temporary browser harness remains E2E-build-only.
  The earlier 154-unit/19-browser green run predates these fixes. At the user's
  explicit request, checks were **not rerun after review fixes**; Gate G11a
  remains pending validation and CI. Detailed evidence and unrun regression
  cases are recorded in the Stage 11a contract.
- **Next:** confirm Gate G11a and merge this increment before beginning Stage 11b.

## Documentation ownership

- `PLAN.md` is the product contract and wins if documents disagree.
- `IMPLEMENTATION.md` owns active stage order, short status summaries naming
  the exact stage branch, remaining estimates, and acceptance-check
  traceability.
- `implementation/stage-*.md` owns the detailed contract, tasks, test matrix,
  open questions, gate, and detailed completion evidence for one mergeable
  delivery unit.
- `implementation/archive-*.md` is historical evidence, not an active plan.

## Ground rules

- **One stage or lettered substage at a time.** Complete its exit gate before
  starting the next. Stages 8, 11, and 12 have mandatory intermediate gates;
  split another stage if its gate cannot remain small and independently green.
- Branches, commits, tags, pushes, and PRs follow the user's authorized workflow;
  passing a gate does not by itself authorize a Git operation.
- **A stage is DONE only when:** code, tests, and docs are complete; automated
  checks pass locally and in CI; required manual evidence is recorded; and no
  earlier gate regressed.
- Update this file's current status within each stage branch, naming the exact
  branch. Detailed completion evidence belongs in the stage's
  `implementation/stage-*.md` file; both it and the next-stage marker must be
  included in that stage's PR before merge.
- Backend Stages 7-8 verify with backend/API tests and need no frontend. Frontend
  Stages 9-13 build against the completed API. Stage 14 is cross-stack, and
  Stage 15 ties the system together end-to-end.
- Keep the integer examples from `PLAN.md` section 3 in the language-neutral
  `tests/fixtures/numeric_examples.json`; backend and frontend tests read it
  directly without a generator or duplicated literals.
- Keep dependencies minimal per `PLAN.md` section 2. Add one only when it removes
  demonstrated work or risk.
- Remote QA follows `PLAN.md` section 2 data isolation: production, human
  QA/beta, and automated E2E never share a database. Test reset means replacing
  a disposable database, not deleting marked rows from a mixed database.
- Record implemented scope, commands/results, manual observations, and blockers
  for every gate. Later tests are not retroactive proof that an earlier gate
  passed.

## Verification commands

- Backend: `cd backend && ruff check . && ruff format --check . && mypy app migrate.py && pytest -q && pip check`
- Migrations: `cd backend && python migrate.py` with an isolated
  `DATABASE_PATH`.
- Frontend: `cd frontend && npm run check && npm run lint && npm run test:unit`.
- E2E: `cd frontend && npm run test:e2e`.
- CI aggregate: all applicable checks above plus
  `cd frontend && npm run build`.

Feature-specific checks join CI in their owning stage. E2E owns
startup/readiness/teardown and isolated data. Migration checks never use the
development or production database.

## Remaining stage summary

| MS | Stage | Deliverable | Primary verification | Current est. days |
|----|-------|-------------|----------------------|------------------:|
| C. Frontend | **9** | Frontend foundation, theme, router, API and integer helpers | Component/unit tests against backend | 2 |
| C | **10** | Auth, read-only Home, Catalog | Component + Playwright | 2.5 |
| C | **11a-11c** | IndexedDB drafts, durable pending work, recovery/account handling | Three coordinator/browser gates | 3 |
| C | **12a-12c** | Editor, synchronization/finish, repeat/conflict recovery | Three editor/E2E gates | 4 |
| C | **13** | History/detail, Settings, logout | Playwright | 2.5 |
| D. Operations | **14** | Minimal admin API/panel, account controls, audit | Admin API/security + Playwright | 3 |
| E. Hardening | **15** | Acceptance evidence and production deployment smoke | Full CI + deployment/restart checks | 4 |

Remaining implementation and verification total **21 person-days**. Reserve
**5 additional contingency days**, concentrated in Stages 11-12 synchronization,
Stage 13 deletion/logout races, and Stage 15 deployment smoke. Remaining
planning budget: **26 person-days**. Estimates are planning inputs, not gate
deadlines.

---

## Milestone B - Complete backend API

### Stage 7 - Delete and lifecycle

**Status:** merged to `master` in
[PR #12](https://github.com/konflic/train_log/pull/12) on 2026-10-08
(`a5fa210`); Gate G7 passed locally on 2026-10-08.

**Detailed plan and completion evidence:**
[`implementation/stage-07-delete-lifecycle.md`](implementation/stage-07-delete-lifecycle.md).

**Purpose:** add revision-checked, owner-scoped hard deletion and prove the
post-delete lifecycle without weakening Stage 6c's finished-workout and exact
retry rules.

**Gate G7:** exact-revision DELETE returns an empty 204; stale revisions fail
atomically; missing, foreign, and already-deleted rows return 404; GET and PUT
after deletion do not recreate the workout; the complete backend suite passes.

**Acceptance coverage:** parts of checks 2 and 11.

### Stage 8 - Previous performance and statistics

Implement Stage 8 as two sequential mergeable increments. Resolve each detailed
file's open questions before starting that substage.

#### Stage 8a - Inline previous performance

**Status:** merged to `master` in
[PR #13](https://github.com/konflic/train_log/pull/13) on 2026-10-08
(`b13261e`); Gate G8a passed locally on 2026-10-08.

**Detailed plan and completion evidence:**
[`implementation/stage-08a-previous-performance.md`](implementation/stage-08a-previous-performance.md).

Bounded previous-session selection, occurrence and side-aware set pairing,
snapshot-compatible integer comparisons, and estimated 1RM in workout detail
responses.

**Gate G8a:** the additive nullable `previous_performance` member is explicit in
the detail schema; selection uses finished, strictly earlier, owner-scoped
sessions with a completed set for the catalog id under the
`(started_at DESC, id DESC)` total order; occurrences pair in workout order and
completed sets by side and per-side ordinal without ever crossing sides;
recorded snapshots and bodyweights make catalog and profile edits unable to
fabricate progression; GET, POST, an accepted PUT, and an exact retry return
equal detail representations from one transaction snapshot; the query count stays
bounded independently of graph size; the complete backend suite passes.

**Acceptance coverage:** the server half of checks 8, 9, and 10.

#### Stage 8b - Statistics summary

**Status:** merged to `master` in
[PR #14](https://github.com/konflic/train_log/pull/14) on 2026-10-08 (`bf5033c`);
Gate G8b passed locally on 2026-10-08.

**Detailed plan:**
[`implementation/stage-08b-stats-summary.md`](implementation/stage-08b-stats-summary.md).

Eligible workout/set counts, complete or partial volume, fixed-offset calendar
grouping, muscle-group frequency, and weekly streaks.

**Gate G8:** G8a and G8b pass independently; the complete backend suite
remains green; Milestone B exits with the full client-facing API contract.

**Acceptance coverage:** checks 8 (server half), 9, and 10.

> **Remote deployment checkpoint:** after Stage 8, API-only remote testing may
> begin under a private QA origin/process and separate `DATABASE_PATH`. It must
> never use the production user database.

---

## Milestone C - Frontend against the live API

### Stage 9 - Frontend foundation

**Status:** implemented on branch `stage-9-10-frontend` (pending merge); Gate
G9 passed locally on 2026-10-08.

**Detailed plan:**
[`implementation/stage-09-frontend-foundation.md`](implementation/stage-09-frontend-foundation.md).

**Purpose:** runnable client shell that talks to the API. (`PLAN.md` sections 2
and 8)

**Scope:** `frontend/src/main.ts`, `App.svelte`, `api.ts`, `lib/numbers.ts`
(BigInt floor helper), theme module, router (`svelte-spa-router`), Tailwind,
Vite `/api` proxy, and bottom-navigation layout.

**Tasks:** implement theme selection through a root CSS class, use system
preference on first visit (light fallback), persist the explicit choice, and
apply it before first paint. Add fetch helpers and TypeScript types matching the
backend schemas. Implement BigInt floor division with negative-remainder
correction and safe-range checks, reading the shared numeric fixtures directly.

**Verification:** unit tests for numeric parity, theme persistence, and API
helpers against a running backend; frontend check/lint/build remain green.

**Gate G9:** fetch helpers authenticate and call the API in the test harness;
frontend arithmetic matches the backend. Covers check 9 (frontend half) and part
of check 14.

### Stage 10 - Auth, Home, and Catalog screens

**Status:** implemented on branch `stage-9-10-frontend` (pending merge); Gate
G10 passed locally on 2026-10-08.

**Detailed plan:**
[`implementation/stage-10-auth-home-catalog.md`](implementation/stage-10-auth-home-catalog.md).

**Purpose:** login, navigation, and browsing. (`PLAN.md` section 8)

**Scope:** `features/auth`, `features/home`, `features/catalog`, and routes.

**Tasks:** implement register/login, read-only Home (active workout list, recent
history, weekly summary), and Catalog (search, filters, default/custom labels,
create/edit own). Do not expose unfinished workout action buttons. Draft-safe
reauthentication arrives in 12b; quick start, resume, picker integration, and
repeat-last arrive in 12a-12c. Follow mobile touch, label, keyboard, and integer
input rules.

**Verification:** component tests plus Playwright covering register, login,
browse, custom creation, and Home summaries.

**Gate G10:** a user can authenticate, manage the catalog, and view Home
summaries. Full history/detail navigation arrives in Stage 13.

### Stage 11 - IndexedDB draft and pending-save layer

**Purpose:** reliable local persistence and recovery. (`PLAN.md` section 6)

**Scope:** `frontend/src/db.ts` using `idb` plus a small save/sync coordinator.
Implement 11a -> 11b -> 11c without requiring the editor UI. Use coordinator
tests and a browser harness for real IndexedDB, reload, and multiple tabs.

#### Stage 11a - Local persistence and recovery

**Status:** implemented and reviewed on `stage-11a-local-persistence`.
Post-review validation and CI are pending; checks were not rerun at the user's
request. Gate G11a is not yet claimed complete for this revision.

**Detailed plan:**
[`implementation/stage-11a-local-persistence-recovery.md`](implementation/stage-11a-local-persistence-recovery.md).

- Partition by account ID, workout ID, and editor/draft ID; keep one editor per
  workout per tab and require explicit recovery selection.
- Persist every edit before reporting it locally saved; surface storage failures.
**Gate G11a:** locally acknowledged edits survive reload, draft selection is
explicit, and storage failures remain visible.

**Completion evidence:**
[`implementation/stage-11a-local-persistence-recovery.md`](implementation/stage-11a-local-persistence-recovery.md).

#### Stage 11b - Durable create requests and immutable pending saves

**Detailed plan:**
[`implementation/stage-11b-durable-requests-pending-saves.md`](implementation/stage-11b-durable-requests-pending-saves.md).

- Persist the create UUID/request before POST and retain it until acknowledgement.
  Resolve uncertain responses against the original request; never regenerate IDs
  or silently recreate a workout deleted elsewhere.
- Store the editable draft separately from at most one immutable pending PUT.
  Persist before send; retry exact content; never mutate it with later edits.
- On success, atomically persist the returned acknowledgement/revision and retire
  the pending payload without overwriting newer local edits.

**Gate G11b:** create/save/finish survive uncertain responses and reload without
duplicates or double increments; newer edits remain intact.

#### Stage 11c - Reconnect, conflict, and account handling

**Detailed plan:**
[`implementation/stage-11c-reconnect-conflict-account.md`](implementation/stage-11c-reconnect-conflict-account.md).

- Authenticate the same account, resume uncertain work first, and fetch current
  state before later work; never silently advance a local base revision.
- Stop automatic saves on conflict and expose use-server, copy-to-new, and
  explicit replacement actions where lifecycle permits.
- Pause on session expiry, retain drafts after server deletion, and guard queued
  work/responses by account and draft identity.
- Logout clears account-local data only after every unsynchronized draft is
  successfully synced or explicitly approved for discard; unselected recovery
  alternatives and concurrent tab edits cannot be silently cleared.

**Gate G11c / G11:** recovery and account isolation pass coordinator/browser
tests. Covers checks 1-4 and 11 at the persistence layer.

### Stage 12 - Active workout editor

**Purpose:** the core logging experience. (`PLAN.md` sections 6 and 8)

**Scope:** `features/workout`, editor/set/exercise components, sync status, and
repeat-last draft copying. Implement 12a -> 12b -> 12c with a visible
demonstration at each gate.

#### Stage 12a - Locally persistent editor

**Detailed plan:**
[`implementation/stage-12a-locally-persistent-editor.md`](implementation/stage-12a-locally-persistent-editor.md).

Wire quick start and resume through Stage 11 persistence. Add the catalog
picker, large integer inputs, add/remove/reorder, done flags, stable keyed IDs,
and labeled provisional totals. Distinguish local persistence from server
acknowledgement.

**Gate G12a:** a usable local editor survives reload, preserves focus, and
exposes storage failures.

#### Stage 12b - Synchronization, reauthentication, and finish

**Detailed plan:**
[`implementation/stage-12b-sync-reauth-finish.md`](implementation/stage-12b-sync-reauth-finish.md).

Connect foreground save/reconnect and save/finish controls. Show locally saved,
syncing, synced, offline, conflict, and finish-pending states. Preserve drafts
through reauthentication; keep final graph and finish time pending until durable
acknowledgement; never delete a draft early.

**Gate G12b:** save/finish/recovery work through the editor; no stale response
overwrites input and no unacknowledged finish discards a draft.

#### Stage 12c - Repeat-last and conflict recovery UI

**Detailed plan:**
[`implementation/stage-12c-repeat-conflict-recovery.md`](implementation/stage-12c-repeat-conflict-recovery.md).

Repeat the last finished workout through durable create and normal bulk-save,
using new IDs, copied values, `done=false`, reset RPE, current defaults, and
visible handling for unavailable/incompatible entries. Expose each explicit
conflict recovery choice without discarding the source draft prematurely.

**Gate G12c / G12:** logging, repeat-last, and conflict recovery work end-to-end.
Covers checks 1-5, 8, and editor reauthentication from check 11.

> **Remote deployment checkpoint:** after Stage 12, the complete core app may be
> tested with invited QA/beta users on a dedicated human-QA database separate
> from production and automated E2E. Stage 15 remains the production gate.

### Stage 13 - History/detail, Settings, and logout

**Detailed plan:**
[`implementation/stage-13-history-settings-logout.md`](implementation/stage-13-history-settings-logout.md).

**Purpose:** review, preferences, and account-safe logout. (`PLAN.md` section 8)

Implement history/detail with previous-session comparisons; Settings with theme,
profile bodyweight, UTC offset, and logout; confirmed revision-checked deletion
for active and finished workouts. Logout offers sync or discard for
pending changes and clears local data only after synchronization succeeds or
discard is confirmed for all affected work, with cross-tab and uncertain-response
recovery. Keep units metric-only.

**Verification:** Playwright covers detail comparisons, theme persistence and
legibility, historical snapshot stability after profile/catalog edits, failed
logout recovery actions, account switching with pending work, and deletion
conflict/response-loss recovery.

**Gate G13:** full user feature set, including revision-checked deletion. Covers
checks 10-12 and 14 and deletion recovery from check 2.

---

## Milestone D - Administration

### Stage 14 - Minimal operational admin panel

**Purpose:** operate accounts safely without impersonation or access to training
data. (`PLAN.md` sections 4, 6, 8, and 11)

**Scope:** numbered admin migration, bootstrap CLI, admin API/schemas/services,
role-gated UI, and append-only audit log.

**Tasks:**

- Add `users.role`, `users.account_status`, and `admin_audit_log`; preserve all
  existing data and default existing users safely.
- Add confirmation-based role grant/revoke CLI with last-active-admin guards and
  audit records.
- Resolve role/status on every authenticated request; disabled accounts cannot
  log in or keep using sessions; admin role never bypasses resource ownership.
- Add bounded user/audit reads plus disable, enable, and revoke-session actions.
  Mutations require password reauthentication, Origin/JSON checks,
  confirmation, and a bounded nonempty reason.
- Audit successful and rejected authorized mutations without secrets or workout
  content.
- Add the limited admin UI; no impersonation, password controls, workout
  inspection, user deletion, or default-catalog editing.

**Verification:** migration preservation, bootstrap and last-admin guards,
authorization and disabled-session rejection, atomic disable/revocation, fresh
login after enable, reauthentication/CSRF, bounded reads, safe audit content,
and the complete admin Playwright flow.

**Gate G14:** administration is authorized, audited, and cannot access training
data or impersonate users. Covers acceptance check 15.

---

## Milestone E - Hardening

### Stage 15 - Acceptance evidence and production deployment smoke

**Purpose:** prove the 15 acceptance checks and lock them in CI. (`PLAN.md`
section 10)

**Scope:** acceptance evidence, E2E gaps, production same-origin serving,
deployment/restart smoke, isolated remote E2E, and operating documentation.

**Tasks:**

- Audit all acceptance checks against their owning-stage tests and fill real
  gaps without duplicating every backend test as E2E.
- Serve the built SPA and `/api/v1` under one origin with one API process and a
  persistent local-disk SQLite database; run migrations explicitly before start.
- Provision disposable remote E2E databases with deterministic fixtures and
  delete the entire database/sidecars after each run. Production exposes no
  fixture/reset endpoints.
- Smoke HTTPS cookie behavior, register/login, create/save/finish, restart, and
  persistence using the production artifact. Any production-origin smoke uses
  only normal APIs and one reusable synthetic account.
- Restore/verify a backup and prior-schema upgrade; verify nonzero UTC-offset
  grouping/display.
- Document setup, migration, production run, backup/restore, admin bootstrap,
  role recovery, account controls, session revocation, and audit review.

**Verification:** full CI from a fresh clone, production same-origin/restart
smoke, disposable remote-E2E removal, no production fixture routes, and recorded
mobile/keyboard/light-dark visual review.

**Gate G15 (ship gate):** every acceptance check has passing evidence, the
production smoke succeeds, and operating documentation is complete. No PWA
app-shell cache is required.

---

## Acceptance-check traceability

Completed Stage 0-6 evidence referenced below is preserved in the archived
implementation snapshot. Remaining stages must record new evidence in this file
as they merge.

| # | Check | Stages that prove it |
|---|-------|----------------------|
| 1 | Offline edit -> reload -> reconnect recovers every acknowledged edit | 11a-11c, 12a-12b, 15 |
| 2 | Lost create/save/finish retry has no duplicate/regeneration/double increment/early delete | 5, 6c, 7, 11b, 12b, 13, 15 |
| 3 | In-flight save response cannot overwrite newer edits | 11b, 12b, 15 |
| 4 | Two tabs conflict atomically and preserve both drafts | 6c, 11a, 11c, 12c, 15 |
| 5 | Finish accepts unsynced sets atomically | 6c, 12b, 15 |
| 6 | Foreign workout/nested/catalog IDs never leak or partially write | 3-6c, 15 |
| 7 | Reorder/remove/add works under unique indexes | 6b, 12a, 15 |
| 8 | Repeat copies do not affect historical totals/PRs | 8a-8b, 12c, 15 |
| 9 | Strict integers, floor arithmetic, negative/unknown cases | 2, 4-7, 8a-8b, 9, 15 |
| 10 | Profile/catalog edits do not rewrite recorded totals | 5, 8a-8b, 13, 15 |
| 11 | Session expiry/account switch/delete recovery preserves or explicitly discards drafts | 3, 7, 11b-11c, 12b, 13, 15 |
| 12 | CSRF/cookies/logout and secret-free output | 3, 13-15 |
| 13 | Backup restore and older-schema upgrade preserve data/indexes/FKs | 1, 14, 15 |
| 14 | Persistent legible themes and metric-only UX | 9, 13, 15 |
| 15 | Admin authorization, account controls, safeguards, and safe audit | 14, 15 |

Additional Phase 1 deliverables: production same-origin serving, restart
persistence, and UTC-offset handling are proved in Stage 15.

## Active risk notes

- **S10/S13 offset display:** the frontend must use inclusive local-date API
  bounds and the profile's fixed offset, not the browser timezone. Preserve
  Stage 8b's volume-completeness and full-history streak semantics.
- **S11 draft/sync protocol:** offline, multi-tab, response-loss, and
  acknowledgement ordering need coordinator tests, not only UI coverage.
- **S14 authorization/audit:** account disabling and immutable evidence must stay
  atomic without granting training-data access.
- If a gate is red, split the work rather than moving forward.
