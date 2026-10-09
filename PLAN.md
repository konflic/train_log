# BaseFit - Fitness Training Tracker

## 1. Overview

BaseFit is a mobile-first web app for logging resistance workouts: exercises,
sets, reps, and weights. The priority is quick logging, reliable recovery of
in-progress work, and useful comparisons with previous sessions.

The backend exposes a versioned REST API so a native client can be added later.
Implement the web app first; extract shared packages or add infrastructure only
when a second client or a measured deployment need justifies them.

### Primary Goals

- Log a workout quickly on a phone.
- Preserve a local draft through refreshes and temporary network loss.
- Save and finish a workout without losing edits or duplicating sets.
- See completed-set totals and previous performance before elaborate charts.
- Keep implementation explicit: synchronous functions, direct SQL, and few dependencies.

### Permanent Product Rules

- **Metric only** across the UI, API, storage, and future features. No imperial
  units, unit-system preference, or unit selector.
- **Dark/light theme switch in Settings**, available from Phase 1.

### Non-Goals for the MVP

- Social features, sharing, nutrition, coaching, billing, and media storage.
- Fractional weights and fractional RPE. Weights are
  **whole kilograms**; fractional plate increments cannot be represented.
  If finer precision becomes necessary later, reconsider integer grams rather
  than introducing decimal or floating-point domain values.
- Timed holds, distance/cardio, assisted movements, and arbitrary exercise metrics.
- PostgreSQL support, horizontal scaling, database pools, and PgBouncer.
- Automatic conflict merging, background sync, and starting new workouts offline.
- Repeat-last, a native app, and advanced charts.
- Admin impersonation, password viewing/reset, workout inspection/editing, and
  default-catalog management. The Phase 1 admin panel is limited to account
  operations.
- Email verification and password recovery for the initial private/small
  deployment; resolve account recovery before a public multi-user launch.

---

## 2. Architecture and Stack

```text
Mobile-first Svelte SPA --> /api/v1 (FastAPI) --> SQLite file
       |                       |
       +--> IndexedDB draft    +--> Database-backed sessions

One web origin serves the SPA and API. A future native app uses the same API.
```

### Backend

- **Python + FastAPI**, synchronous `def` endpoints and service functions.
- **SQLite + stdlib `sqlite3`**, with explicit parameterized SQL. Use a small
  connection/transaction helper, not a generic executor or repository framework.
- **Pydantic v2** for authoritative request validation and explicit response
  schemas. Keep input, database rows, and public output distinct where their
  fields differ; server-controlled fields are never generic writable row fields.
- **Opaque server-side sessions** using `secrets` for random tokens and
  `hashlib` for token hashes. Use a maintained **Argon2id** password-hashing
  library; do not implement password hashing ourselves.
- **Numbered SQL migrations** and a small stdlib migration command. No ORM,
  SQLAlchemy, Alembic, dialect adapter, or dual-database test suite in the MVP.
- **pytest** with temporary SQLite files for backend tests.

### Frontend

- **Svelte 5 + Vite + TypeScript**, using Svelte's built-in reactivity, keyed
  lists, and `bind:` for the workout editor. Svelte compiles components and ships
  runtime support; it is not a zero-runtime framework.
- **Tailwind CSS** for styling, semantic HTML for simple controls. Add an
  accessible headless component dependency only for controls that need it.
- **Dark/light themes** via a root CSS class and existing styling tools. Use the
  system color preference on first visit (light as fallback), then persist the
  user's explicit Settings choice in localStorage on that device. Apply the
  saved theme before first paint; no theme library or backend preference needed.
- **`svelte-spa-router`** for small hash-based routing without rewrite rules.
- A local **`api.ts`** over browser `fetch` and ordinary TypeScript types.
  No separate shared package, generated-client pipeline, or read-cache library
  until a concrete need appears. OpenAPI remains the backend contract.
- **Handwritten form checks** for immediate feedback; backend validation is
  authoritative. No Zod, form framework, or supposed Python/TS schema sharing.
- **IndexedDB with `idb`** for drafts and pending saves. This small dependency
  avoids handwritten IndexedDB transaction/event plumbing.
- **Vitest + Svelte Testing Library + Playwright** for targeted frontend and
  end-to-end checks. Add a chart or PWA dependency only in its later phase.

### Deployment and concurrency

- Start with one API process and a persistent SQLite file on local disk. Serve
  the SPA and API under one origin; Vite proxies `/api` during development.
  Containers are optional packaging, not a requirement for local development.
- A synchronous service call opens, uses, and closes its connection on the
  **same thread**. Do not open a connection in a FastAPI dependency and assume
  the endpoint and dependency cleanup run on that same thread.
- Keep `check_same_thread=True`; never share a connection between requests.
- Enable WAL once during database initialization. Set `foreign_keys=ON` and a
  bounded busy timeout on every connection. WAL permits concurrent readers but
  still has one writer; more threads do not remove that limit.
- Use short `BEGIN IMMEDIATE` write transactions. A timeout returns a retryable
  service error; it must not discard the client's local draft. WAL and
  `BEGIN IMMEDIATE` do not eliminate all lock contention.
- Add PostgreSQL only when required. That work includes migrations, connection
  budgets, SQL differences, and verification; changing one URL is not a promised
  zero-work database migration.

### Remote QA and test-data isolation

- Test the production build and deployment topology remotely, but never point
  automated tests or fixture/reset tooling at the production user database.
  Environment similarity does not require shared data.
- Run production, long-lived human QA/beta, and automated E2E as separate app
  instances with separate origins, processes, SQLite files, WAL sidecars,
  backup locations, and secrets. They may share one server and the same built
  artifact. Use distinct, explicit `DATABASE_PATH` values; copying production
  data into QA is out of scope unless a separate redaction process is designed.
- Prefer a disposable database per automated remote E2E run. Create it from
  migrations, load only deterministic fixtures needed by that run, start one
  app process against it, then stop the process and delete the whole database
  plus sidecars. Whole-database disposal is safer and simpler than identifying
  and deleting test rows from a mixed database.
- Prefer an on-server fixture command over an HTTP QA API. If remote orchestration
  later proves that an HTTP fixture API is necessary, mount it only when
  `APP_ENV=qa`, keep it disabled by default, require a separate high-entropy CI
  credential and restricted ingress, and make startup fail unless the database
  is explicitly marked disposable. Production mode must never expose fixture,
  reset, bulk-delete, or environment-switching endpoints.
- A smoke test against the actual production origin uses only the normal public
  API and one clearly named synthetic account. Reuse that account and clean up
  its resources through normal owner-scoped behavior; never run a broad QA
  cleanup operation in the production database.

---

## 3. Integer-Only Numeric Contract

All numeric domain inputs, stored measurements, and reported calculations are
integers. Text, timestamps, booleans, and `null` retain their natural API types.
Measurement units are fixed metric units, not a user preference; weight is kg.

| Value | Representation |
|-------|----------------|
| External weight and bodyweight | Whole kg, integer |
| Reps | Integer |
| RPE | Integer from 1 through 10, or `null` |
| Bodyweight contribution | Integer percentage from 1 through 100, or `null` when not applicable |
| Effective load and volume | Integer kg and kg-reps respectively, or `null` when unknown |
| Estimated 1RM, averages, percentage changes | Integers, always rounded down |
| Duration | Integer seconds |

- Reject fractional numeric inputs, numeric strings, and booleans in integer
  fields. Use strict integer validation; do not silently truncate input.
- Store numbers in SQLite `INTEGER` columns with appropriate checks. SQLite
  numeric affinity alone does not enforce exact decimal precision. Use SQLite
  **STRICT tables** (runtime version at least 3.37); validate the actual linked
  SQLite runtime at startup rather than assuming a Python package pins it.
- **Every division floors its result.** Never use nearest rounding, a floating
  intermediate, or truncation toward zero. Python uses `//`; TypeScript uses
  built-in `BigInt` arithmetic with a remainder-based correction for negative
  results (native BigInt division truncates toward zero). This needs only a
  small arithmetic helper, not a numeric dependency. Convert results back to
  JSON numbers only after checking the safe integer range.
- Keep operands and intermediate integer results within JavaScript's safe
  integer range and SQLite's integer range. Validate bounds; do not emit an
  imprecise JSON number or silently overflow.
- State calculation order explicitly and use the same examples in backend and
  frontend checks. Do not round independently at different stages on each side.
- `null` means unknown; `0` means a known zero. They are not interchangeable.

### Calculation order

Use the workout's recorded bodyweight and the exercise instance's recorded
load settings. For a complete weighted-bodyweight set with known bodyweight:

```python
# Compute this only when a bodyweight percentage applies and bodyweight is known.
bodyweight_load = bodyweight_kg * bodyweight_percent // 100

# multiplier is 1 for single_weight and side_count for split_weight.
external_load = weight_kg * multiplier
effective_load = external_load + bodyweight_load
set_volume = reps * effective_load
```

For pure-bodyweight exercises, external load is zero and the null weight field
is not multiplied. If no bodyweight percentage applies, its contribution is zero
without requiring a bodyweight measurement. If a percentage applies but bodyweight
is unknown, effective load and volume are `null`, even when the external load is known.

Examples: 81 kg at 65% gives `81 * 65 // 100 = 52` kg; 10 reps then give
`10 * 52 = 520` kg-reps. Two 12 kg dumbbells for 8 bilateral reps give
`12 * 2 * 8 = 192` kg-reps. For a signed percentage change, `-100 // 3 = -34`;
zero denominators produce `null`, not an exception or fabricated percentage.

---

## 4. Domain Model and History

- **User**: owns workouts and custom exercises; has an optional current
  bodyweight default and a user-chosen fixed UTC offset (whole minutes,
  default 0 = UTC) for calendar-based statistics and local-time display.
- **Session**: an expiring, revocable login stored in the database.
- **WorkoutSession**: explicitly started training with a `freestyle` or
  `from_plan` type, optional source-plan reference, read-only bodyweight
  snapshot, integer revision, and ordered graph. `ended_at=null` means active;
  each account has at most one active explicitly started session.
- **TrainingPlan**: reusable owner-private preparation with a revision and an
  ordered exercise/set target graph. Saving or previewing a plan never creates
  a workout session.
- **ExerciseCatalog**: global default exercises plus owner-private custom ones.
- **Exercise**: a workout entry referencing a catalog ID and storing its load
  settings as a snapshot.
- **Set**: reps, weight, optional RPE, side, optional bodyweight percentage
  override, and whether it was actually completed.
- **AdminAuditEvent**: immutable record of an administrative actor, target,
  action, required reason, request ID, and timestamp. It contains no password,
  session token, or workout content.
- Later: **BodyweightEntry**. Do not create its table or endpoints in Phase 1.

### Load types

| Load type | Meaning of `weight_kg` | External load |
|-----------|------------------------|---------------|
| `single_weight` | Total external weight | `weight_kg` |
| `split_weight` | Weight per dumbbell/side | `weight_kg * side_count` |
| `bodyweight` | Must be `null` | 0 |

An optional `bodyweight_percent` adds the floored bodyweight contribution for
pure-bodyweight and weighted-bodyweight exercises. Pure-bodyweight exercises
require a percentage. A set's integer `bw_percent_override`, when allowed,
replaces the exercise snapshot's percentage. Allow it only on exercises that
already have a bodyweight contribution.

For `split_weight`, `side_count=1` means one set represents one side, with
`side=left` or `right`. Logging both sides requires two sets. With
`side_count=2`, one set covers both sides and `side=bilateral`. Other load types
use `side_count=1` and `side=bilateral` in the MVP. Side-aware comparisons must
not pair a left set with a right set.

### Preserve historical inputs

- At explicit session start, copy the user's current Settings value into
  `workouts.bodyweight_kg`; keep `null` if unknown. The snapshot is read-only;
  later Settings changes apply only to newly started sessions.
- When first persisting an exercise instance, copy `load_type`,
  `bodyweight_percent`, and `side_count` from its visible catalog entry. The
  client displays catalog-based provisional calculations until acknowledged.
- Existing exercise snapshots are read-only through normal bulk-save, and an
  existing exercise ID cannot be reassigned to a different catalog entry.
  Catalog edits apply to new instances, not to recorded history.
- Derive effective load and totals on read from these recorded inputs. Changing
  today's profile bodyweight or a catalog default must not rewrite old totals.
- When bodyweight history is added, resolve the latest measurement on/before a
  new workout's start, with profile default as fallback, then record the result.
  Later measurement edits do not automatically recalculate existing workouts.
- A small seed catalog is sufficient. Label bodyweight percentages as estimates;
  include provenance where available. Exhaustive biomechanics research is not
  a launch dependency, and these estimates are not universal physical constants.

### Validation and ownership

- Every workout lookup and write is scoped to its owner. UUIDs do not replace
  authorization. Return 404 for another user's resource.
- Submitted exercise and set IDs must belong to the specified parent or be new,
  globally unused IDs. Never move another parent's rows through an upsert.
- Catalog references must be global defaults or the caller's own custom entries.
- Draft sets may have missing reps/weight. A completed set requires positive
  reps and, for weighted exercises, nonnegative weight. Pure-bodyweight sets
  require `weight_kg=null`; missing bodyweight is allowed but yields unknown load.
- Present bodyweight must be positive. RPE is 1 through 10. Percentages are
  1 through 100, indexes are nonnegative, and `ended_at >= started_at`.
- Bound text lengths, graph sizes, page sizes, and numeric inputs. Reject
  duplicate IDs/indexes and unknown or server-controlled request fields.
- Default catalog entries have no owner; custom entries require one. Defaults
  are not user-editable. Referenced catalog entries cannot be deleted (409).
- Names are unique within the default scope and within each user's custom scope.
  A custom name may match a default name; distinguish them by ID and a custom
  label rather than adding cross-scope uniqueness machinery.

### Minimal administration

- Users have an explicit `user|admin` role and `active|disabled` account status.
  Public registration always creates an active ordinary user. Roles are never
  accepted from public profile or registration input.
- Bootstrap and change admin roles through an on-server CLI with an explicit
  target and confirmation. Do not expose role grants in the Phase 1 panel, and
  never allow removal of the last active admin.
- Every admin API request requires an authenticated active admin; authorization
  is checked server-side on every request. Non-admin users receive 403 without
  any admin data. Disabling an account and revoking all its sessions is one
  transaction; disabled accounts cannot log in or use an existing session.
  Re-enabling an account does not restore old sessions.
- The panel supports bounded user search/list, account disable/enable, session
  revocation, and bounded audit-log reads. Mutations require reauthentication,
  an explicit confirmation, and a non-empty bounded reason. Prevent an admin
  from disabling itself and prevent operations that would leave no active admin.
- `GET /auth/me` exposes the caller's role as a read-only field so the client can
  hide or show admin navigation; role and status remain server-controlled and
  are never accepted by registration or profile updates.
- Record successful and rejected mutations attempted by an authorized admin in
  an append-only audit log without secrets or user workout content. There is no
  API to update/delete audit records. Keep stable ordering and an ID tie-breaker
  for audit pagination.
- Admins cannot impersonate users, read or edit workouts, view/reset passwords,
  delete users, or edit the default exercise catalog in Phase 1. QA fixture/reset
  tooling is separate and is never an admin feature.

---

## 5. Database Schema and Operations

Logical schema below; expand into explicit SQLite DDL during implementation.
Use `TEXT` UUIDs and canonical UTC timestamps (`YYYY-MM-DDTHH:MM:SSZ`),
`INTEGER` numbers, and checked 0/1 integers for stored booleans. Required fields
are `NOT NULL`, including primary keys. All tables are STRICT.

```text
users
  id TEXT PK
  email TEXT UNIQUE NOT NULL           # documented normalization before storage
  password_hash TEXT NOT NULL
  role TEXT NOT NULL                   # user|admin; default user; admin migration
  account_status TEXT NOT NULL         # active|disabled; default active; admin migration
  display_name TEXT
  bodyweight_default_kg INTEGER        # null or > 0
  utc_offset_minutes INTEGER NOT NULL  # fixed offset, default 0 (UTC); -720..840
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

sessions
  token_hash TEXT PK                   # SHA-256 of a random high-entropy token
  user_id TEXT NOT NULL FK users(id) ON DELETE CASCADE
  created_at TEXT NOT NULL
  expires_at TEXT NOT NULL
  # index: expires_at; logout deletes the row

admin_audit_log                         # added by the admin migration
  id TEXT PK
  actor TEXT NOT NULL                  # user:<uuid> or bootstrap CLI identity
  target_user_id TEXT NOT NULL         # retained as text for durable audit history
  action TEXT NOT NULL                 # role_grant|role_revoke|disable|enable|revoke_sessions
  result TEXT NOT NULL                 # succeeded|rejected
  reason TEXT NOT NULL
  request_id TEXT NOT NULL
  created_at TEXT NOT NULL
  # indexes: (created_at, id), (target_user_id, created_at, id)

exercise_catalog
  id TEXT PK
  name TEXT NOT NULL
  muscle_group TEXT NOT NULL           # chest|back|legs|shoulders|arms|core|full_body|other
  equipment TEXT NOT NULL              # barbell|dumbbell|kettlebell|machine|cable|bodyweight|band|other
  load_type TEXT NOT NULL              # single_weight|split_weight|bodyweight
  bodyweight_percent INTEGER          # null or 1..100; required for bodyweight
  side_count INTEGER NOT NULL          # 1 or 2 for split_weight; otherwise 1
  is_default INTEGER NOT NULL          # 0 or 1
  created_by TEXT FK users(id)
  # CHECK: default with null owner OR custom with non-null owner
  # unique indexes: name WHERE is_default=1; (created_by, name) WHERE is_default=0

workouts
  id TEXT PK                          # client-generated UUID
  user_id TEXT NOT NULL FK users(id) ON DELETE CASCADE
  name TEXT
  started_at TEXT NOT NULL
  ended_at TEXT
  notes TEXT
  bodyweight_kg INTEGER                # recorded input, not a live profile lookup
  session_type TEXT                   # null for legacy; freestyle|from_plan for new starts
  source_plan_id TEXT FK training_plans(id) ON DELETE SET NULL
  revision INTEGER NOT NULL            # starts at 0, increments per accepted save
  create_request_hash TEXT NOT NULL    # immutable fingerprint for create retries
  last_save_id TEXT                    # last accepted save UUID
  last_save_hash TEXT                  # fingerprint of that validated request
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL
  # indexes: (user_id, started_at, id); unique explicit active session per user

training_plans
  id TEXT PK
  user_id TEXT NOT NULL FK users(id) ON DELETE CASCADE
  name TEXT NOT NULL
  notes TEXT
  revision INTEGER NOT NULL
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

training_plan_exercises
  id TEXT PK
  plan_id TEXT NOT NULL FK training_plans(id) ON DELETE CASCADE
  catalog_id TEXT NOT NULL FK exercise_catalog(id) ON DELETE RESTRICT
  order_index INTEGER NOT NULL
  notes TEXT

training_plan_sets
  id TEXT PK
  plan_exercise_id TEXT NOT NULL FK training_plan_exercises(id) ON DELETE CASCADE
  set_index INTEGER NOT NULL
  target_reps INTEGER
  target_weight_kg INTEGER
  side TEXT NOT NULL
  bw_percent_override INTEGER

workout_save_previous_performance
  workout_id TEXT PK FK workouts(id) ON DELETE CASCADE
  snapshot TEXT NOT NULL                 # latest PUT's bounded derived-history receipt

exercises
  id TEXT PK                          # client-generated UUID
  workout_id TEXT NOT NULL FK workouts(id) ON DELETE CASCADE
  catalog_id TEXT NOT NULL FK exercise_catalog(id) ON DELETE RESTRICT
  order_index INTEGER NOT NULL
  notes TEXT
  load_type TEXT NOT NULL              # snapshot, same rules as catalog
  bodyweight_percent INTEGER          # snapshot
  side_count INTEGER NOT NULL          # snapshot
  # UNIQUE(workout_id, order_index); index: (catalog_id, workout_id)

sets
  id TEXT PK                          # client-generated UUID
  exercise_id TEXT NOT NULL FK exercises(id) ON DELETE CASCADE
  set_index INTEGER NOT NULL
  reps INTEGER
  weight_kg INTEGER
  bw_percent_override INTEGER
  rpe INTEGER
  side TEXT NOT NULL                   # left|right|bilateral
  done INTEGER NOT NULL                # 0 or 1; default 0
  # UNIQUE(exercise_id, set_index)
```

### Direct SQL and transactions

- Use `sqlite3` named parameters directly. Never interpolate values into SQL.
  Keep resource-specific queries with their service; move a long query to a
  `.sql` file only when that improves readability.
- Fetch a workout graph with a small, fixed number of queries, not one query
  per set. Use `sqlite3.Row` and explicit response construction.
- Full-graph saves validate ownership and IDs before mutating any child row.
  Revision check, upserts, deletions, ordering, and finish are one transaction.
- To reorder under unique indexes, delete omitted rows, move retained rows to
  distinct temporary indexes above both the old and new ranges, then apply final
  dense indexes and insert new rows. Keep every step within the same transaction.
  A direct swap of two occupied unique positions is not safe.

### Migrations, backups, and deployment

- Run numbered SQL migrations explicitly before serving requests; record
  applied versions in `schema_migrations`. Apply each supported migration
  transactionally and stop on failure. Do not run migrations from every worker.
- SQLite table rebuilds must preserve data, indexes, and foreign keys. Test
  upgrades from the previous schema and run `PRAGMA foreign_key_check`.
  Handle any required foreign-key PRAGMA changes outside the transaction.
- Back up a running database with `sqlite3.Connection.backup()` or
  `VACUUM INTO`, not an ordinary copy of the main file while WAL is active.
- Verify a restored backup with integrity/foreign-key checks and representative
  workout reads. Back up before destructive schema migrations.
- Persist the database outside an ephemeral container filesystem. Keep database
  files, WAL files, backups, tokens, and environment secrets out of Git.

---

## 6. API and Save Protocol

Base path: `/api/v1`. JSON request/response schemas come from Pydantic/OpenAPI.
Use RFC 9457-style errors; 204 responses have no body. Lists use bounded `page`
and `pageSize`, return `total`, and have stable ordering with an ID tie-breaker.

### Phase 1 endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | /auth/register | Create account |
| POST | /auth/login | Create session and set cookie |
| POST | /auth/logout | Delete current session and clear cookie |
| GET | /auth/me | Current public profile |
| PATCH | /auth/me | Update display name, default bodyweight, UTC offset |
| GET | /workouts | History; date and active/finished filters |
| POST | /workouts | Explicitly start a freestyle or plan-derived session |
| GET | /workouts/{id} | Graph, recorded load inputs, revision, last save ID, and previous performance |
| PUT | /workouts/{id} | Full-graph save, including metadata and optional finish |
| DELETE | /workouts/{id}?revision=N | Delete only at the expected revision |
| GET | /exercises | Defaults plus caller's custom entries; search and filters |
| GET | /exercises/{id} | Visible catalog entry |
| POST | /exercises | Create owner-private custom entry |
| PATCH | /exercises/{id} | Edit own custom entry for future instances |
| DELETE | /exercises/{id} | Delete own unreferenced entry |
| GET | /training-plans | List the caller's reusable plans |
| POST | /training-plans | Create an owner-private plan |
| GET | /training-plans/{id} | Read an owned plan and target graph |
| PUT | /training-plans/{id} | Revision-checked full-plan update |
| DELETE | /training-plans/{id} | Revision-checked plan deletion |
| GET | /stats/summary | Basic eligible workout/set counts and volume |
| GET | /admin/users | Bounded user search/list with account metadata only |
| POST | /admin/users/{id}/disable | Disable an account and revoke its sessions atomically |
| POST | /admin/users/{id}/enable | Re-enable an account without restoring sessions |
| POST | /admin/users/{id}/revoke-sessions | Revoke all sessions for an account |
| GET | /admin/audit-log | Bounded immutable administrative audit history |

There are no separate workout metadata PATCH, finish, per-exercise, or per-set
write endpoints. A workout's graph is small enough to save together.

### Creation

- Creation requires a client-generated UUID, `started_at`, and session type.
  A plan-derived start also requires the owned plan ID and expected revision.
  The server records bodyweight from Settings and returns revision 0. Creation
  requires connectivity in the MVP. Persist the immutable create request locally
  until acknowledged.
- Fingerprint the validated create request using a canonical representation.
  Retrying the same ID and fingerprint returns the existing owned workout;
  different content for that ID returns 409. Never return another user's row.
- Resolve an exact retry before checking for another active session. A different
  start is rejected when the account already has an unfinished session, including
  under concurrent requests from another tab or device.
- Plan start validates ownership, revision, and catalog visibility and copies the
  graph atomically with independent IDs, incomplete sets, and unset actual RPE.
  Later plan edits or deletion cannot alter the copied session.

### Bulk-save contract

`PUT /workouts/{id}` includes:

- `revision`: the revision the client edited.
- `save_id`: a fresh UUID for this immutable save attempt, reused on its retries.
- All writable workout metadata and `ended_at`. Recorded `bodyweight_kg`, session
  origin, and load snapshots are server-controlled.
- The complete ordered exercise/set graph. Every row has a client-generated ID;
  omitted existing rows are deleted. Array order determines dense stored indexes.
  Load snapshots, owner IDs, and server timestamps are not writable fields.

Server processing, within one write transaction:

1. Authenticate and load the owned workout; PUT never creates a missing workout.
2. Validate the request and fingerprint its canonical validated content.
3. If `save_id` equals `last_save_id`, require the same fingerprint and return
   the saved graph/revision and its stored derived-history snapshot without
   applying it again. Different content with the same ID returns 409.
4. Otherwise require an exact revision match. A mismatch returns 409 with a
   conflict code/current revision and changes nothing.
5. Validate lifecycle, nested ownership, catalog visibility, arithmetic bounds,
   and all invariants; save the graph and metadata atomically, increment the
   revision, and record `last_save_id`/`last_save_hash` plus the bounded latest
   previous-performance snapshot in the same commit.
6. Return the authoritative graph, revision, and last save ID.

Only the last accepted save receipt is retained, for the lifetime of that
revision. If another client has since saved, an older retry becomes a normal
conflict; do not claim an unprovable success or silently replay old content.
This bounded receipt avoids a generic idempotency service or operation log.

### Finishing and lifecycle

- To finish, send the final full graph with `ended_at` set to the client-recorded
  finish time. Validate timezone-aware timestamps, `ended_at >= started_at`, and
  no future finish time. This records workout duration even if upload is delayed.
- Saving the final sets and marking finished are atomic. The UI displays
  **finish pending** until acknowledged; it never deletes the draft early.
- Finished workouts are read-only in Phase 1 except deletion and exact retry of
  the accepted finish. Later history editing uses the same revisioned PUT;
  reopening is deferred.
- DELETE checks revision in its transaction. A lost delete response can be
  resolved by GET returning 404. A queued PUT after deletion returns 404 and
  retains the local draft rather than recreating the workout automatically.
- After an uncertain create response, resolve the original ID before issuing
  another create. Creation is not an indefinitely replayed offline operation;
  a workout deleted elsewhere requires an explicit user decision to start anew.

### Client persistence and conflict handling

- Partition IndexedDB by account ID, workout ID, and a unique editor/draft ID.
  Separate tabs must not overwrite each other's local drafts. Resume an
  unambiguous active session automatically and keep one editor per workout within
  a tab; show recovery choices only for genuine alternatives or conflicts.
  Persist each edit before displaying it as locally saved. Handle storage
  failures visibly; browser storage eviction is possible, so local persistence
  is not a universal backup.
- Keep the latest editable draft and, separately, at most one immutable in-flight
  payload per draft (`revision`, `save_id`, content). Later edits remain local
  while that payload is being saved. Do not overwrite newer edits with an older
  response. Other tabs/devices are independent clients governed by revisions.
- On a lost response, retry that exact payload. On success, persist the returned
  revision and acknowledgement, then submit newer edits with a new save ID.
- On reconnect/relaunch, authenticate the same account, resume an uncertain save
  first, and fetch current state before sending other pending work. Do not
  advance a draft's base revision just because a newer server revision exists.
- On conflict, stop automatic saves and retain the local draft. Offer to use
  the server copy, copy the local draft into a new workout, or explicitly replace
  the server copy using a newly fetched revision where lifecycle permits. No
  automatic merging or per-set last-write-wins. Copy-to-new cannot bypass the
  one-active-session rule.
- Sync runs while the app is open, on edits and reconnection. Phase 1 can continue
  an already loaded workout offline and recover drafts after relaunch when the
  app loads. Cold-starting the entire app without a network requires the later
  PWA app-shell cache. Background sync is deferred.
- Expired sessions pause upload without deleting drafts. On logout, offer to
  sync or discard pending changes, then clear that account's local data; never
  upload an old account's draft under a newly logged-in user.

---

## 7. Statistics and Previous Performance

### Eligibility and missing data

- Historical stats include only **finished workouts and `done=true` sets**.
  Prefilled and unfinished sets do not earn volume or PRs.
- Training frequency counts finished workouts with at least one completed set;
  muscle-group frequency requires a completed set for that group.
- Active-workout completed-set totals are provisional and labeled separately.
- Sum known volumes while exposing `unknown_load_set_count` and a completeness
  flag. If all eligible loads are unknown, total volume is `null`; no eligible
  sets means a known total of 0. Never present a partial sum as a complete total.
- Store instants in canonical UTC. Group training days/weeks by applying the
  user's fixed UTC offset, with Monday as week start and explicit half-open
  date ranges. No `zoneinfo`/tzdata dependency; a fixed offset does not track
  DST, so daylight-saving users' day boundaries shift by one hour seasonally
  (accepted tradeoff, see §12). Streaks count consecutive weeks with an
  eligible workout, allowing the current week to still be ongoing.

### Previous performance

- Without a current workout, select the most recent finished session with
  completed sets for that catalog ID, ordered by `(started_at, id)` descending.
- For a viewed workout, exclude itself and require a strictly earlier
  `started_at`. Use the same ID tie-breaker among candidate sessions.
- If the catalog exercise appears more than once in that session, return all
  its instances in workout order. Pair occurrences in order, then completed
  sets by side and ordinal; unmatched sets have no comparison delta.
- Compare load-based values only when the recorded load settings and per-set
  overrides are compatible. A catalog change must not imply fake progress.
- Inline previous performance in workout GET using bounded queries. In the
  progression phase add `GET /exercises/{id}/last-performance` (200 with `null`
  when absent) for local prefill; copying results creates new draft IDs and
  resets completion/RPE. A batch read is optional only if measured demand warrants it.

### Metrics

- **Volume**: integer `reps * effective_load`, aggregated by workout, exercise,
  muscle group, and calendar period, with the completeness rules above.
- **PRs**: maximum logged external weight at a given rep count for weighted
  exercises; maximum reps for pure-bodyweight exercises. Keep side and load
  settings comparable. Estimated loads are not universal cross-exercise scores.
- **Estimated 1RM**: only weighted exercises with no bodyweight contribution.
  For one rep, use external load directly. For 2 through 10 reps, use
  `external_load * (30 + reps) // 30`; above 10 reps return `null`. No estimated
  1RM for pure-bodyweight, weighted-bodyweight, or assisted movements.
- **Progression**: weight at reps, completed-set totals, and previous-session
  deltas. Calculate all displayed averages/percentages with floor division;
  show `null` when the comparison or denominator is unavailable.
- **Duration**: completed workout's elapsed whole seconds. Derive it from
  integer-second timestamps, not floating-point duration arithmetic.

---

## 8. Frontend Screens

1. **Auth**: register/login; reauthenticate without losing a draft.
2. **Home**: recent history, active-session information, and a basic weekly
   summary. It has no start-workout action.
3. **Session chooser**: opens from the center navigation action only when no
   active session exists; explicitly starts freestyle or opens plan selection.
4. **Training plans**: list, create, view, edit, delete, and explicitly start an
   independent session from a selected plan.
5. **Active workout**: large integer inputs, add/remove/reorder exercises and
   sets locally, mark done, show provisional totals, save, and finish.
   Distinguish locally saved, syncing, synced, offline, conflict, and finish
   pending. Preserve focus through stable keyed IDs.
6. **History/detail**: finished workouts and previous-session comparison;
   editing finished workouts comes later.
7. **Catalog/picker**: search, muscle filters, default/custom labels, and
   creation/editing of own custom entries.
8. **Settings**: dark/light theme switch, display name, the only bodyweight
   input, training-plan access, UTC offset picker (hour steps, e.g. −3 h … +3 h),
   and logout. Units are always metric, with no unit selector.
9. **Admin**: role-gated user search, account status, disable/enable, session
   revocation, and audit history. Require reason/confirmation for mutations;
   expose no workout content, impersonation, or password controls.
10. Later: dedicated statistics charts.

Mobile rules: single-column layouts, bottom navigation, touch targets of at
least 44 CSS pixels, visible labels/errors, keyboard accessibility, and sticky
primary actions. Use `inputmode="numeric"` and integer steps for measurement
inputs; browser controls supplement, not replace, strict API validation.
Both themes must keep text, inputs, focus indicators, and status colors legible.

---

## 9. Project Structure

```text
basefit/
  PLAN.md
  README.md
  backend/
    app/
      main.py
      config.py
      db.py                 # connection/transaction helper
      auth.py               # sessions and password verification
      api/                  # versioned routes
      schemas/              # explicit request/response models
      services/             # resource-specific SQL and business logic
    migrations/             # numbered SQLite SQL files
    migrate.py              # small stdlib migration command
    tests/
    pyproject.toml
  frontend/
    src/
      main.ts
      App.svelte
      api.ts                # fetch helpers and local API types
      routes/
      components/
      features/
      db.ts                 # idb drafts and one pending save per editor draft
    package.json
    vite.config.ts
    svelte.config.js
    tsconfig.json
```

Create modules as their features arrive. Avoid a second stats service hierarchy,
generic repositories, shared workspaces, plugin systems, and speculative wrappers.

---

## 10. Roadmap and Acceptance

### Phase 1 - Reliable, usable core

- Synchronous FastAPI, direct SQLite SQL, integer-only contract, migrations,
  backup/restore procedure, and the minimal session-based authentication.
- Profile updates, a small estimated seed catalog, and private custom entries.
- Dark/light theme switch in Settings, remembered locally across reloads.
  Fixed metric labels throughout; no configurable unit system.
- Online creation, local workout editing, IndexedDB persistence, revision checks,
  bounded save receipts, atomic save-and-finish, history, and deletion.
- Explicit freestyle/plan session starts, reusable training plans, and one active
  session per account across tabs and devices. Merely opening screens starts
  nothing; the center action resumes the active session and Home has no starter.
- Record bodyweight/load inputs from day one. Show basic completed-set totals,
  summary stats, and inline previous performance.
- Minimal audited administration: securely bootstrap admins, search users,
  disable/enable accounts, revoke sessions, and review admin actions without
  impersonation or access to workout content.
- Remote QA uses the production artifact with isolated databases as defined in
  §2. Automated E2E data is disposable without querying or deleting real-user rows.

### Phase 1 acceptance checks

1. Edit a loaded workout offline, reload with the app available, reconnect,
   and recover every locally acknowledged edit.
2. Open the chooser and browse/edit plans without creating a workout; explicitly
   start freestyle or from a plan. Concurrent starts and lost start responses
   produce exactly one active session and preserve the original request identity.
3. Edit while a save is in flight: its response cannot overwrite newer input.
4. Edit in two tabs: stale saves fail atomically and both drafts remain recoverable.
5. Finish with unsynced sets: final graph and finish are accepted together.
6. Submit another user's workout, nested IDs, or catalog entry: no partial write
   or unauthorized read. UUID guessing does not bypass ownership checks.
7. Reorder/remove/add exercises and sets under unique indexes successfully.
8. Recover a conflict through use-server, permitted copy-to-new, or explicit
   replacement without silently merging or prematurely deleting local work;
   copy-to-new cannot create a second active session.
9. Reject fractional, string, boolean, and out-of-range integer inputs; verify
   floor arithmetic, negative deltas, unknown loads, and the calculation examples.
10. Bodyweight is entered only in Settings and copied as a read-only start-time
    snapshot. Plan graph copies use independent IDs and remain unchanged after
    source edits/deletion; profile/catalog changes do not rewrite recorded totals.
11. Expire a session, switch accounts, and retry after deletion: preserve or
    explicitly discard drafts without cross-account uploads or silent recreation.
12. Verify CSRF protection, cookie expiry, logout revocation, and exclusion of
    session/password data from API output.
13. Restore a backup and upgrade an older schema: data, indexes, and foreign keys
    remain valid. No requirement for PostgreSQL tests in this phase.
14. Switch between dark and light in Settings, navigate, and reload: the chosen
    theme persists and controls remain legible. Verify metric units throughout
    the UI, API, and storage, with no unit selector or imperial option.
15. Verify non-admins cannot access admin data/actions; disabling an account
    atomically revokes its sessions and blocks login; enabling it restores only
    login eligibility; self/last-admin safeguards hold; successful and rejected
    mutations are audited without secrets or workout content.

### Phase 2 - Progression and usability

- Repeat the latest finished workout through the existing create/save paths,
  using independent graph IDs and unfinished copied sets.
- Per-exercise last-performance read and local prefill; side-aware set/exercise
  deltas, simple progression views, and optional rest timer.
- Edit finished workouts with the same save/revision protocol; no new per-set API.
- Optional installable PWA and app-shell caching; foreground reconnect remains
  the sync mechanism. Show quota/storage failures rather than promising no loss.

### Phase 3 - Bodyweight history and charts

- Bodyweight-entry list/create/update/delete (`GET/POST /bodyweight-entries`,
  `PATCH/DELETE /bodyweight-entries/{id}`), with integer kg and measurement time.
  Entries affect newly resolved snapshots; existing workout snapshots remain
  immutable.
- Dedicated volume, frequency, PR, exercise-progression, and bodyweight stats
  endpoints/charts. Reuse the eligibility and integer arithmetic contracts.

### Later, when justified

- Native app: same API, opaque session delivered to OS secure storage and sent
  in an authorization header; define native issuance when implementing that client.
- PostgreSQL migration and deployment scaling based on real usage.
- Offline creation, background sync, multi-device automatic merging, and shared
  client packages only when the simple foreground workflow is insufficient.
- Import, finer integer-based metric precision, new exercise metrics, media,
  sharing, and notifications as separate product decisions. Metric-only remains
  a permanent constraint.

---

## 11. Authentication and Cross-Cutting Rules

### Simple sessions

- Generate a high-entropy random token with `secrets.token_urlsafe(32)` on login.
  Store only its SHA-256 hash, owner, creation time, and absolute expiry.
  Passwords use Argon2id; fast hashing is only for random session tokens.
- Send the token in an **HttpOnly, Secure, SameSite=Strict** cookie, scoped to
  `/api/v1`. Never put it in localStorage, IndexedDB, URLs, or application logs.
  Allow non-Secure cookies only for explicitly configured local HTTP development.
- Look up the session on each authenticated request, reject expired sessions,
  and delete the row on logout. Use a configurable fixed lifetime; expiry
  requires login. No JWT library, refresh endpoint, rotation family, or Redis.
- For every mutating browser request, including login/register/logout, require
  JSON plus an exact allowed `Origin`. Reject absent/mismatched origins in the
  browser MVP. Keep GET side-effect-free and do not enable cross-origin
  credentialed access. SameSite is an additional defense, not the whole CSRF policy.
- Reject unexpected auth fields/transports. A future native bearer-token mode
  must deliberately define issuance and CSRF exemption rather than weakening
  the cookie-authenticated browser checks.
- Apply bounded auth throttling for the single-process deployment, generic
  login errors, and request/body size limits. Keep credentials out of all output.
- Resolve the current user role and account status during each authenticated
  request. Disabled users and stale sessions fail closed. Admin mutations also
  require password reauthentication and use the same Origin/JSON protections;
  an admin role never bypasses ordinary resource ownership checks.

### Operations and verification

- Configuration: `DATABASE_PATH`, `SESSION_TTL_SECONDS`, `APP_ORIGIN`,
  `COOKIE_SECURE`, and `APP_ENV`. No database-selection adapter or JWT settings.
- Log request IDs and failures; add metrics infrastructure only when needed.
- CI: lint, typecheck, backend/frontend checks, and production frontend build.
  Exercise real SQLite transactions for concurrency and migration cases.
- Backend validation is authoritative. Maintain a small set of shared example
  expectations for integer arithmetic and API behavior, not a schema-sharing framework.
- Keep UI strings easy to find and English-first; add a translation framework
  only when supporting another language.

---

## 12. Decision Log

- **Integer-only, always floor**: whole kg, integer RPE, integer bodyweight
  percentages, explicit calculation order. No fractional measurements in the
  MVP; unknown values remain `null`.
- **Metric only, permanently**: fixed metric units across clients, API, and
  storage; no imperial support or user-selectable unit system.
- **UTC storage + fixed user UTC offset**: every stored instant is canonical
  UTC; the user picks a fixed offset (integer minutes, default 0) in Settings
  for display and calendar grouping. Removes zoneinfo/tzdata deployment
  requirements; DST shifts are not tracked and move affected users' day
  boundaries by one hour seasonally (accepted for the MVP).
- **Dark/light switch in Settings**: available in Phase 1, persisted per device,
  and implemented with existing styling tools rather than another dependency.
- **SQLite-first, direct SQL**: stdlib connections and small helpers are enough.
  Defer PostgreSQL, pooling, dialect rewriting, ORM, and migration dependencies.
- **Synchronous service owns its connection**: keeps the transaction on one
  thread without relying on FastAPI dependency scheduling.
- **One graph write path**: metadata, exercises, sets, and finish share a single
  atomic PUT. Prefill is a local draft operation, not an extra write API.
- **Revision + last-save receipt**: prevent stale overwrites and recover a lost
  response without building an operation log or automatic merge engine.
- **Explicit sessions and reusable plans**: opening screens has no training side
  effects; one account has one active session, while plans remain reusable
  preparation copied atomically into independent session graphs.
- **Recorded inputs preserve history**: the Settings bodyweight snapshot and load
  settings belong to the recorded workout/instance and are read-only; current
  defaults only affect new records.
- **Opaque database sessions**: one table and a cookie are enough for web login,
  expiry, and logout; introduce native transport when the native client exists.
- **Draft persistence before background sync**: keep recovery reliable while the
  app is open; define offline limits and surface conflicts rather than hiding them.
- **Progress feedback early**: completed-set totals and previous performance
  matter before elaborate charts.
- **Svelte without speculative packages**: built-in reactivity, local fetch
  helpers, and a small IndexedDB wrapper; dependencies must remove actual work.
- **Minimal, non-impersonating administration**: operational account controls
  require explicit roles, reauthentication, confirmation, and immutable audit
  records. Admin status does not grant access to workouts or passwords.

---

## 13. Future Development

- Reconsider user-controlled data export after the MVP when there is demonstrated
  demand for portability or offline recovery. Design server-saved-data and local-
  draft exports together with explicit versioning, ownership boundaries, secret
  exclusion, consistency and size limits, and a separate decision about import.
