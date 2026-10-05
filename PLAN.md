# FitTrack - Fitness Training Tracker

## 1. Overview

FitTrack is a fitness training tracker that lets users log their workouts
(exercises, sets, reps, weights) and view statistics derived from their
training history. The application is built **mobile-first** as a web app now,
but designed API-first so a native mobile app can be added later with no
backend rework.

### Primary Goals

- Let users create and manage training logs quickly (mobile UX is critical).
- Track exercises with sets, reps, and weight per set.
- Provide insightful statistics (volume, frequency, PRs, progression).
- Keep a clean separation between backend (API) and frontend (UI) so a
  future mobile client can consume the same API.

### Non-Goals (for MVP)

- Social features, leaderboards, sharing.
- Nutrition / calorie tracking.
- Real-time coaching or video.
- Paid subscriptions / billing.
- Email verification / password reset (deferred; acceptable for a
  single-user/small MVP — revisit before any public multi-user launch).

---

## 2. High-Level Architecture

```
+-------------------+        +------------------+        +-------------------+
|   Web Frontend    |        |   Backend API    |        |     Database      |
|  (mobile-first)  | <----> |   (REST / JSON)  | <----> | SQLite (MVP) /    |
+-------------------+        +------------------+        | PostgreSQL (prod) |
        |                            |                    +-------------------+
        |                            +---> Auth (JWT)
        |                            +---> Object Storage (optional, later)
        |
   Future: Native mobile app (same API)
```

### Principles

- **API-first**: Every feature is exposed via a versioned REST API
  (`/api/v1/...`). The web frontend is just one client.
- **Stateless backend**: Horizontal scaling friendly.
- **Backend / frontend split**: Separate directories/packages, independent
  deploy pipelines.
- **Mobile-first UI**: Touch targets, bottom navigation, offline-tolerant
  forms (PWA-ready).

---

## 3. Proposed Tech Stack

> Recommendations; can be adjusted before implementation starts.

### Backend

- **Language/Framework**: Python + FastAPI, **synchronous** style (plain `def`
  endpoints; FastAPI runs them in an AnyIO threadpool — first-class, documented
  support). Auto OpenAPI docs, fast iteration. *Alternative*: Node.js +
  Fastify/NestJS.
- **Database**: **switchable** — **SQLite** for MVP/local dev (zero setup,
  file-based), **PostgreSQL** for production. Same app code targets both via a
  thin **sync** DB layer over stdlib `sqlite3` / `psycopg` (v3, sync mode).
  Selected by `DATABASE_URL` (e.g. `sqlite:///./fittrack.db` vs
  `postgresql://user:pass@host/db`). See *Database Portability* below.
  > `psycopg` v3 (not psycopg2) is chosen deliberately: it supports **both**
  > sync and async, so if a future real-time feature ever needs async, the
  > driver isn't a rewrite — it's an escape hatch.
- **Data access**: **raw SQL** — no ORM. Hand-written SQL queries executed via
  the sync drivers behind a small in-house executor that normalizes parameter
  style (`?`/`:name` vs `%s`/`$1`) and returns rows mapped to Pydantic models.
  Schema lives as SQL files; migrations via Alembic in raw-SQL mode
  (`op.execute("...")`). Rationale: shallow schema, analytics-heavy reads,
  switchable-DB — an ORM's relationship/unit-of-work machinery doesn't pay off.
  See *Why no ORM*.
- **Validation**: Pydantic v2 (comes with FastAPI); response/request schemas
  also double as row-shape mappers for query results.
- **Auth**: JWT access + refresh tokens; bcrypt/argon2 password hashing.
- **Testing**: pytest (with a temporary SQLite DB per test, or test Postgres in CI).
- **Containerization**: Docker + docker-compose. MVP backend can run without a
  DB container (SQLite file); compose includes an optional Postgres service
  + adminer for prod/dev-parity when needed.

#### Concurrency model (sync)

- **Request handling**: sync `def` endpoints run in FastAPI's AnyIO threadpool
  (default 40 tokens, tunable via
  `anyio.to_thread.current_default_thread_limiter().total_tokens`). Each
  in-flight request holds one thread + one DB connection for its duration.
- **Scaling**: concurrency ceiling per process ≈ threadpool size. Scale by
  (a) raising the threadpool limit and (b) running multiple worker processes
  (`uvicorn --workers N` or gunicorn+uvicorn workers) behind a load balancer.
  Horizontal scaling is the primary lever — simpler to reason about than async
  tuning.
- **SQLite connections**: not thread-safe by default → use **connection-per-
  request** (open in the sync dependency, `PRAGMA foreign_keys=ON`, `PRAGMA
  journal_mode=WAL`, close after). Connections are cheap; WAL allows concurrent
  readers while writes serialize (single-writer).
- **Postgres connections**: `psycopg` v3 thread-safe connection pool sized to
  workers × threadpool; front with **pgbouncer** in production to cap total
  connections and reuse them.
- **Transactions**: bulk-save is a single sync transaction on one thread —
  no async context-switching mid-transaction. Keep transactions short.
- **Why sync is fine here**: workload is short CRUD transactions + scoped
  aggregate queries (DB-bound, not connection-juggling-bound); no
  WebSockets/SSE/streaming; SQLite makes async fake anyway (aiosqlite =
  sqlite3 in a thread). The threadpool ceiling is lower per process than async,
  but you scale by processes/nodes, and the DB is the real constraint either
  way. See *Decision Log*.

### Frontend

- **Framework**: React + Vite (TypeScript). Mobile-first.
- **UI approach**: Tailwind CSS + headless components (e.g. Radix/Headless UI).
  *Alternative*: React Native Web if we want maximum code reuse with the
  future native app.
- **State/Data**: TanStack Query for server state; lightweight local state
  (Zustand) if needed.
- **Routing**: React Router (or TanStack Router).
- **Forms**: React Hook Form + Zod (shares schemas with backend later).
- **PWA**: service worker + manifest for installable, offline-capable web app.
- **Testing**: Vitest + Playwright (E2E).

### Future Mobile App

- Same REST API, JWT auth.
- Candidate: React Native (reuse TS skills + some logic) or Flutter.
- Offline sync layer needed (queue mutations while offline).

---

## 4. Domain Model

Core entities:

- **User**: account owning workouts.
- **WorkoutTemplate** (optional, for routines): a reusable plan of exercises.
- **Workout**: a single training session (date, duration, notes).
- **Exercise**: an exercise entry within a workout (links to an ExerciseCatalog item).
- **Set**: a single set within an exercise (reps, weight, rpe, done). The meaning of
  `weight` depends on the catalog exercise's `load_type` (see Load Model below).
- **ExerciseCatalog**: library of exercises (name, muscle group, equipment,
  `load_type`, optional `bodyweight_fraction`). Two scopes: **default**
  exercises (seeded, `is_default=true`, no owner — visible to all users) and
  **custom** exercises (`is_default=false`, `created_by=<user>` — visible
  *only* to their owner). A user's effective catalog = defaults + own custom.
- **BodyweightEntry**: track user's bodyweight over time — needed to compute
  effective load for bodyweight-based exercises.

> **Last performance** is not an entity — it's a derived read: the most recent
> *finished* workout that contained a given catalog exercise for the current
> user, plus that exercise instance's sets. Used to prefill new exercise
> instances and to show "vs last time" deltas.

### Entity Relationships

```
User 1--* Workout 1--* Exercise 1--* Set
User 1--* WorkoutTemplate 1--* TemplateExercise 1--* TemplateSet
ExerciseCatalog 1--* Exercise
User 1--* BodyweightEntry
```

### Load Model

Every catalog exercise has a **`load_type`** that determines how the effective
load of a set is computed (and which set fields are meaningful). Bodyweight
participation is captured by an optional **`bodyweight_fraction`** (the share
of bodyweight being moved, e.g. pull-up ~1.0, push-up ~0.65, feet-elevated
push-up ~0.75). This fraction is set on **both** pure-bodyweight exercises and
**weighted-bodyweight** exercises (weighted pull-up, weighted dip), because in
both cases the user's bodyweight contributes to the resistance.

| load_type        | weight field meaning      | Effective load (per rep)                          |
|------------------|---------------------------|---------------------------------------------------|
| `single_weight`  | total external weight     | `weight` (+ `bw * fraction` if fraction set)      |
| `split_weight`   | weight per side (dumbbell) | `weight * side_count` (+ `bw * fraction` if set)   |
| `bodyweight`     | unused (null)             | `bw * fraction`                                   |

Where:
- `weight` = the value logged on the set.
- `bw` = user's bodyweight at the time of the workout: most recent
  `bodyweight_entry` on/before `workout.started_at`, falling back to
  `users.bodyweight_default`. **If both are null, `bw` is unknown** →
  `effective_load` and `set_volume` for bodyweight/weighted-bodyweight sets
  are reported as `null` (excluded from volume sums, never treated as 0), and
  the UI prompts the user to set a bodyweight. Weighted-only sets
  (`single_weight`/`split_weight` with no fraction) still compute normally.
- `fraction` = `COALESCE(set.bw_fraction_override, catalog.bodyweight_fraction)`
  — the per-set override (e.g. feet-elevated push-up logged on a "Push-up"
  entry) wins over the catalog default. Nullable; if null, no bodyweight term.
- `side_count` = catalog field, `1` for unilateral (e.g. single-arm DB row),
  `2` for bilateral (default).

#### Unilateral logging convention (`split_weight`, `side_count=1`)

For one-sided exercises (single-arm DB row, single-leg press), **one set = one
side**. `reps` and `weight` are per side; `effective_load = weight * 1`. If the
user trains both sides, they log two sets (left + right) — the app may offer a
"mirror to other side" quick action. This keeps volume honest (no hidden 2x)
and avoids ambiguity about whether `reps` is per-side or total. Bilateral
exercises (`side_count=2`) log one set covering both sides; `effective_load =
weight * 2`.

#### Categories (summary)

- **Weighted — single weight** (barbell squat, bench press, **weighted pull-up**,
  weighted dip): one external weight value. Weighted pull-up/dip additionally
  carry a `bodyweight_fraction`, so total load = `bw*fraction + weight`.
- **Weighted — split weight** (dumbbell curl, dumbbell press): weight is per
  side; total = `weight * side_count`.
- **Bodyweight** (push-up, pull-up with no added load, air squat): no weight
  field; load = `bw * fraction`. Variations that change leverage are separate
  catalog entries (e.g. "Push-up", "Push-up (feet elevated)").

#### Set volume

`set_volume = reps * effective_load`

Total volume rolls up by workout / exercise / muscle group / week.

---

## 5. Database Schema (Draft)

> Logical draft. Physical types follow the **Database Portability** rules
> below: UUIDs and timestamps are stored as `TEXT` (ISO-8601 UTC) on both
> SQLite and Postgres; `load_type` is `TEXT + CHECK`; NUMERIC for weights;
> FKs with `ON DELETE CASCADE` and `PRAGMA foreign_keys=ON` on SQLite.
> IDs and timestamps are set in the app, not via DB defaults.

```sql
users
  id            UUID PK
  email         TEXT UNIQUE NOT NULL
  password_hash TEXT NOT NULL
  display_name  TEXT
  bodyweight_default NUMERIC(10,2)  -- fallback bw for load calc (kg)
  preferred_unit TEXT NOT NULL DEFAULT 'kg'
                 -- CHECK (preferred_unit IN ('kg','lb')); stored kg, converted in UI
  created_at    TIMESTAMPTZ
  updated_at    TIMESTAMPTZ

exercise_catalog
  id            UUID PK
  name          TEXT NOT NULL
  muscle_group  TEXT NOT NULL
                 -- CHECK enum: chest|back|legs|shoulders|arms|core|full_body|other
  equipment     TEXT NOT NULL
                 -- CHECK enum: barbell|dumbbell|kettlebell|machine|cable|
                 --             bodyweight|band|other
  load_type     TEXT NOT NULL  -- single_weight | split_weight | bodyweight
  bodyweight_fraction NUMERIC(4,3)  -- nullable; share of BW moved (e.g. 1.000, 0.650)
  side_count    SMALLINT DEFAULT 2   -- 1 unilateral, 2 bilateral (for split_weight)
  is_default    BOOLEAN DEFAULT FALSE
  created_by    UUID NULL FK users(id)  -- NULL for defaults; =owner for custom (user-private)
  -- uniqueness: name distinct within a user's visible catalog
  --   (defaults unique globally; custom unique per created_by)
  --   UNIQUE(name) WHERE is_default; UNIQUE(created_by, name) WHERE created_by IS NOT NULL
  -- indexes: index_exercises_by_owner(created_by) WHERE created_by IS NOT NULL

workouts
  id            UUID PK
  user_id       UUID FK users(id)
  name          TEXT
  started_at    TIMESTAMPTZ NOT NULL
  ended_at      TIMESTAMPTZ
  notes         TEXT
  created_at    TIMESTAMPTZ
  updated_at    TIMESTAMPTZ

exercises
  id            UUID PK
  workout_id    UUID FK workouts(id) ON DELETE CASCADE
  catalog_id    UUID FK exercise_catalog(id) ON DELETE RESTRICT  -- protect history; block custom-exercise deletion if referenced
  order_index   INT NOT NULL
  notes         TEXT
  -- UNIQUE(workout_id, order_index); app reindexes on add/remove to keep dense 0..n
  -- index: (catalog_id, workout_id) for "last performance" lookups
  -- (join workouts for started_at ordering; see Last Performance query)

sets
  id            UUID PK
  exercise_id   UUID FK exercises(id) ON DELETE CASCADE
  set_index     INT NOT NULL
  reps          INT
  weight        NUMERIC(10,2)   -- kg; meaning depends on load_type (per-side for split)
  bw_fraction_override NUMERIC(4,3) NULL  -- per-set override of catalog fraction (position change)
  rpe           NUMERIC(3,1)    -- rate of perceived exertion, optional
  done          BOOLEAN DEFAULT FALSE
  created_at    TIMESTAMPTZ
  -- UNIQUE(exercise_id, set_index); app reindexes on add/remove

workout_templates
  id            UUID PK
  user_id       UUID FK users(id)
  name          TEXT

template_exercises
  id            UUID PK
  template_id   UUID FK workout_templates(id) ON DELETE CASCADE
  catalog_id    UUID FK exercise_catalog(id)
  order_index   INT

template_sets
  id            UUID PK
  template_exercise_id UUID FK template_exercises(id) ON DELETE CASCADE
  set_index     INT
  target_reps   INT
  target_weight NUMERIC(10,2)

bodyweight_entries
  id            UUID PK
  user_id       UUID FK users(id)
  weight        NUMERIC(10,2)
  measured_at   TIMESTAMPTZ
```

Notes:
- All money/weight use NUMERIC to avoid float drift.
- UUIDs for IDs (safe to expose, no enumeration); stored as TEXT.
- Timestamps stored as TEXT (ISO-8601 UTC).
- `effective_load` (and thus volume) is computed at read time from
  `load_type` + `bodyweight_fraction` + `bodyweight` — never stored, so
  catalog/fraction corrections retroactively fix historical stats.

### Database Portability (SQLite ↔ PostgreSQL)

The schema and app code must run unchanged on both SQLite (MVP) and PostgreSQL
(prod), with **no ORM** — we own the dialect quirks explicitly.

- **Driver/URL**: single `DATABASE_URL` env var selecting the **sync** driver:
  stdlib `sqlite3` (`sqlite:///./fittrack.db`) or `psycopg` v3 sync
  (`postgresql://user:pass@host/db`). A thin in-house `db` module wraps the
  driver and normalizes parameter style (rewrite `:name` ↔ `?` for sqlite3 ↔
  `%(name)s` for psycopg3) so SQL strings are shared.
- **Parameter style**: write SQL once with named params (e.g. `:user_id`);
  the executor translates to the driver's style. Never interpolate values.
- **UUIDs**: generate `uuid.uuid4()` in the app; persist as **`TEXT`**
  (CHAR(36)) on both engines (Postgres has native UUID, but TEXT keeps one
  storage rule and avoids cast drift). Read back into `uuid.UUID` in mappers.
  No `gen_random_uuid()` / `DEFAULT` in DDL — set IDs in app.
- **Timestamps**: store as **`TEXT` ISO-8601 UTC** (`YYYY-MM-DDTHH:MM:SSZ`)
  on both (SQLite has no native type; keeping TEXT on Postgres too avoids a
  second storage rule). Mappers parse to timezone-aware `datetime`. No
  DB-side `NOW()` defaults — set timestamps in app on insert/update.
- **Enums** (`load_type`): `TEXT` + `CHECK` constraint in DDL; validated by
  Pydantic `Enum` in app. No native Postgres `ENUM` (migration pain, absent
  in SQLite).
- **Foreign keys / cascades**: declared in DDL (`REFERENCES ... ON DELETE
  CASCADE`). SQLite needs `PRAGMA foreign_keys=ON` per connection (set in the
  executor's connect hook). Works on both.
- **No Postgres-only types/features**: avoid `ARRAY`, `JSONB` (use `TEXT`
  holding JSON if ever needed), `INTERVAL`, or generated columns. Partial
  unique indexes (`CREATE UNIQUE INDEX ... WHERE ...`) ARE portable — both
  SQLite and Postgres support them — and are used for catalog name uniqueness
  (see schema). Use portable `RETURNING *` only where both drivers support it
  — **pin SQLite >= 3.35** (RETURNING support) in deps/runtime; if the runtime
  SQLite is older, fall back to insert-then-SELECT-by-id. `psycopg` v3 supports
  RETURNING natively.
- **Booleans/numerics**: `BOOLEAN` + `CHECK` / `NUMERIC` are portable (SQLite
  stores as 0/1 and TEXT). Keep NUMERIC precision explicit.
- **Migrations**: Alembic in **raw-SQL mode** — each migration is
  `op.execute("""...SQL...""")` applied to both engines. No model autogenerate.
  For SQLite's limited `ALTER TABLE`, migrate via the standard
  table-rebuild pattern (create new, copy, drop, rename) — works on both and
  avoids dialect-specific ops.
- **Case sensitivity**: quote nothing; use lowercase snake_case identifiers
  consistently (Postgres folds to lowercase; SQLite is case-insensitive).
- **Concurrency**: SQLite MVP = single-writer; fine for local dev / single
  user / small self-hosted. Use **WAL mode** (concurrent readers, serialized
  writer) and **connection-per-request** (sqlite3 connections aren't thread-safe
  by default; the sync threadpool needs one connection per in-flight request —
  see *Concurrency model*). Postgres for multi-user prod (psycopg3 pool +
  pgbouncer). Keep transactions short; on SQLite use `BEGIN IMMEDIATE` for
  write transactions to avoid `database is locked` under contention.
- **Testing against both**: unit tests run on a temp SQLite file; CI runs the
  suite again against a throwaway Postgres container to catch dialect drift.
- **Backups**: SQLite = copy the file; Postgres = `pg_dump`. Documented per
  environment.

### Why no ORM

Chosen deliberately (see decision log). Reasons:

- Schema is shallow (~8 tables, flat FK graph) — ORM relationship loading and
  unit-of-work machinery don't pay off.
- Analytics path is aggregate SQL (volume, PRs, 1RM, frequency) — clearer and
  faster to write as raw SQL than ORM query DSL.
- ORM lazy-loading N+1 risk sits exactly on the hot path (workout → exercises
  → sets); with raw SQL you write one explicit fetch/JOIN and see the query
  that runs. (Going sync also sidesteps async-ORM footguns like
  `MissingGreenlet` entirely — a bonus, not the main reason.)
- Switchable SQLite↔Postgres: a dialect-aware executor + portable storage
  rules cover the few quirks; no need for a full ORM's dialect layer.
- One representation per shape: SQL table ↔ Pydantic schema (mapper is a
  one-liner), instead of SQL + ORM model + Pydantic.

Trade-off we accept: we hand-write SQL and migrations (no autogenerate). For
this schema size and change rate that's cheap, and the SQL we write is the SQL
that runs.

---

## 6. API Design (REST, v1)

Base path: `/api/v1`

### Auth

| Method | Path                  | Description           |
|--------|-----------------------|-----------------------|
| POST   | /auth/register        | Create account        |
| POST   | /auth/login           | Login, get tokens     |
| POST   | /auth/refresh         | Refresh access token   |
| POST   | /auth/logout          | Revoke refresh token  |
| GET    | /auth/me              | Current user info     |

### Workouts

| Method | Path                  | Description                       |
|--------|-----------------------|-----------------------------------|
| GET    | /workouts             | List (filter by date range, page) |
| POST   | /workouts             | Create workout                    |
| GET    | /workouts/{id}        | Get workout with exercises/sets; each exercise includes an inline `last_performance` object (for "vs last time" hints) |
| PUT    | /workouts/{id}        | **Bulk-save**: upsert the full exercise+set graph in one request (primary write path for the active workout — see Bulk Save below) |
| PATCH  | /workouts/{id}        | Update workout metadata (name, notes, started_at) |
| DELETE | /workouts/{id}        | Delete workout                    |
| POST   | /workouts/{id}/finish | Mark workout as finished (sets `ended_at`) |
| POST   | /workouts/{id}/clone  | Clone this workout into a new active one (exercises+sets copied as not-done drafts) |
| POST   | /workouts/repeat-last | Clone the most recent *finished* workout into a new active one |

> **Bulk Save** (`PUT /workouts/{id}`): the active-workout write path. Body is
> the full graph — exercises (with `catalog_id`, `order_index`, optional `id`
> for existing) each with their sets (`set_index`, `reps`, `weight`,
> `bw_fraction_override`, `rpe`, `done`, optional `id`). The server upserts in
> one transaction: rows with an `id` are updated, rows without are inserted,
> and any existing exercise/set not present in the payload is deleted. This
> replaces per-set round-trips during a session (one request saves the whole
> workout) and is the unit of offline sync. Per-item endpoints below remain
> for targeted edits. Idempotency: client may send an `Idempotency-Key` header
> to make retries safe.

### Exercises (within a workout)

| Method | Path                                          | Description          |
|--------|-----------------------------------------------|----------------------|
| POST   | /workouts/{wid}/exercises                     | Add exercise to workout. Body: `{catalog_id, prefill_from_last?: bool}` — when `prefill_from_last=true`, seed sets from the last session (see note) |
| PATCH  | /workouts/{wid}/exercises/{eid}               | Update exercise (order, notes) |
| DELETE | /workouts/{wid}/exercises/{eid}               | Remove exercise      |

> **Prefill from last session** (`POST /workouts/{wid}/exercises` with
> `{"prefill_from_last": true}`): looks up the caller's most recent *finished*
> workout containing this `catalog_id` (same source as the Last Performance
> endpoint), creates the exercise instance, and seeds it with the **same number
> of sets** as that last instance, copying `reps`/`weight`/`rpe` per set index
> into new, editable (not-done) sets. The user can then change weight, reps,
> add or remove sets. If no prior session exists, the exercise is created with
> one empty set. Note: the bulk-save `PUT` is the usual way to persist edits
> during a session; this endpoint is for adding an exercise mid-workout with
> prefill in one call.

### Sets

| Method | Path                                                              | Description   |
|--------|-------------------------------------------------------------------|---------------|
| POST   | /workouts/{wid}/exercises/{eid}/sets                             | Add set       |
| PATCH  | /workouts/{wid}/exercises/{eid}/sets/{sid}                        | Update set    |
| DELETE | /workouts/{wid}/exercises/{eid}/sets/{sid}                        | Delete set    |

> Per-set endpoints are for targeted edits; the **bulk-save `PUT
> /workouts/{id}`** is the primary write path during an active workout (one
> request for the whole graph, offline-friendly).

### Exercise Catalog

| Method | Path                       | Description                          |
|--------|----------------------------|--------------------------------------|
| GET    | /exercises                 | List visible catalog = defaults + own custom (search, filter muscle) |
| GET    | /exercises/{id}            | Get one (must be visible to caller)  |
| POST   | /exercises                 | Create custom exercise (owner = caller; user-private) |
| PATCH  | /exercises/{id}            | Update own custom exercise (defaults immutable) |
| DELETE | /exercises/{id}            | Delete own custom exercise; blocked (409) if referenced in any workout/template |

> **Visibility rules**: every catalog endpoint enforces that custom
> exercises are only readable/mutable by their owner (`created_by =
> current_user`). Defaults (`is_default=true`) are readable by all and never
> writable/deletable. `GET /exercises` returns the union of defaults and the
> caller's custom exercises.

### Last Performance

| Method | Path                                        | Description                                              |
|--------|---------------------------------------------|----------------------------------------------------------|
| GET    | /exercises/{catalog_id}/last-performance    | Most recent finished workout containing this exercise + that exercise instance's sets (reps, weight, rpe, set_index), ordered by `started_at desc`. Returns 204/empty if none. Used to prefill new exercise instances and to show "vs last time". |
| POST   | /exercises/last-performance                 | **Batch**: body `{catalog_ids: [...]}` → map of `catalog_id` → last-performance (or null). Avoids N round-trips when loading a workout with several exercises. |

> The single-exercise `last_performance` is also embedded inline in
> `GET /workouts/{id}` per exercise, so the active-workout screen gets
> everything in one call; the batch endpoint is for ad-hoc lookups (e.g. the
> exercise picker showing "last: 80x8").

### Templates

| Method | Path                          | Description              |
|--------|-------------------------------|--------------------------|
| GET    | /templates                   | List templates           |
| POST   | /templates                   | Create template          |
| GET    | /templates/{id}              | Get template details     |
| POST   | /templates/{id}/instantiate  | Start a workout from template |

### Statistics

| Method | Path                              | Description                                   |
|--------|-----------------------------------|-----------------------------------------------|
| GET    | /stats/summary                    | Totals: workouts, volume, training days        |
| GET    | /stats/volume?range=...&group=... | Volume over time (per week/month)             |
| GET    | /stats/exercises/{id}             | Per-exercise progression & estimated 1RM      |
| GET    | /stats/personal-records           | Top lifts per exercise                        |
| GET    | /stats/frequency                  | Workouts per week, streaks                    |
| GET    | /stats/bodyweight                 | Bodyweight trend (if entries exist)           |

### Conventions

- All responses are JSON.
- Errors use RFC 9457-style problem details.
- List endpoints support `page`, `pageSize`, and return `total`.
- Auth via `Authorization: Bearer <access_token>`.
- OpenAPI spec auto-generated and served at `/api/v1/docs`.

---

## 7. Statistics to Compute

- **Volume** = sum(reps * effective_load) per workout / per exercise / per
  muscle group / per week. `effective_load` is derived from `load_type` +
  `bodyweight_fraction` + the user's bodyweight at workout time (see Load Model).
- **Training frequency**: workouts per week, per muscle group.
- **Streaks**: consecutive weeks with >=1 workout.
- **Personal records (PRs)**:
  - *Weighted* (`single_weight`/`split_weight`): max weight for a given rep
    count, and max estimated 1RM.
  - *Bodyweight* (`bodyweight` load_type): max reps at bodyweight; estimated
    1RM is **not** shown via Epley on `bw*fraction` (meaningless for high-rep
    bodyweight work). Instead, optionally report "estimated added-weight 1RM"
    only when the user has logged weighted variants of that movement.
- **Estimated 1RM**: Epley formula `1RM = w * (1 + reps/30)`, where `w` is the
  *external* load (`weight`, or `weight*side_count` for split). Applies to
  weighted exercises only. For bodyweight sets, `w` would be `bw*fraction` —
  deliberately excluded from 1RM/weight-PR stats to avoid nonsense numbers.
- **Progression**: weight@reps over time for a given exercise.
- **vs last session**: for each exercise in the active/recent workout, compare
  current set values (reps, weight, effective_load) and total exercise volume
  against the previous session for the same `catalog_id` — surface per-set
  deltas and a total-volume delta so the user sees progress vs last time.
- **Bodyweight trend** (optional).

---

## 8. Frontend Screens (Mobile-First)

1. **Auth**: login / register.
2. **Home / Dashboard**: recent workouts, quick start, weekly summary, and a
   **"Repeat last workout"** action (clones the most recent finished session
   into a new active workout via `POST /workouts/repeat-last`).
3. **Active Workout**:
   - List of exercises with collapsible sets.
   - Big touch-friendly inputs for reps / weight.
   - "Add set", "Add exercise", "Finish workout".
   - **Local persistence**: the in-progress workout is written to **IndexedDB**
     on every change so a refresh, crash, or network drop never loses the
     session. On reconnect/relaunch, the local draft is reconciled with the
     server (last-write-wins per set, or prompt on conflict) and pushed via
     bulk-save.
   - **Bulk-save**: edits are queued locally and synced with a single
     `PUT /workouts/{id}` (debounced / on-finish), not per-set requests.
   - **Add exercise → prefill**: when adding an exercise previously done, the
     app seeds the same number of sets as the last session with last-time
     reps/weight (editable). Each set row also shows a faint "last: 80x8"
     hint for comparison; the user edits weight/reps/set-count live.
   - **Per-set + per-exercise "vs last time" delta** (volume, weight@reps) so
     the user sees progress in-session (data comes inline in the workout GET).
   - Auto-rest-timer between sets (nice-to-have).
4. **Workout History**: list by date, tap to view/edit.
5. **Exercise Catalog / Picker**: search, filter by muscle group.
6. **Templates**: list, create, start from template.
7. **Statistics**: charts (volume trend, PRs, frequency).
8. **Settings**: profile, units (kg/lb), logout.

### Mobile-first UI principles

- Bottom navigation bar (Home, History, Stats, Settings).
- Single-column layouts; large tap targets (>=44px).
- Sticky "Add set" / "Finish" buttons at the bottom.
- Offline-friendly: forms work offline, sync when online (PWA + service worker).
- Numeric keyboards for reps/weight inputs (`inputmode="decimal"`).

---

## 9. Project Structure

```
fit_track/
  PLAN.md
  README.md
  backend/                 # FastAPI service
    app/
      main.py
      api/v1/            # route handlers
      core/              # config, security (JWT, hashing)
      db/                # thin sync executor: driver, param-style normalize, row->Pydantic mappers
      sql/               # *.sql query files (one per resource/feature)
      schemas/           # Pydantic request/response + row mappers
      services/          # business logic (workouts, stats, load model)
      stats/             # aggregate queries + volume/PR/1RM computation
      tests/
    alembic/             # raw-SQL migrations (op.execute)
    pyproject.toml
    Dockerfile
  frontend/                # React + Vite
    src/
      main.tsx
      App.tsx
      pages/
      components/
      features/            # workout, stats, catalog, ...
      api/                 # API client + types
      hooks/
      lib/
    public/                # PWA manifest, icons
    package.json
    vite.config.ts
    Dockerfile
  docker-compose.yml
```

---

## 10. Roadmap / Phases

### Phase 1 - Foundation (lean, usable core)

Goal: a user can register, pick exercises, run an active workout that survives
a refresh, save it in one shot, and repeat their last session. Ship this first.

- Backend: project scaffolding, FastAPI (sync `def` endpoints) + raw SQL
  (sqlite3 / psycopg3) + thin executor + Alembic raw-SQL migrations; **SQLite**
  (local) as default DB, Postgres-ready via `DATABASE_URL`. Pin SQLite >= 3.35.
- Auth: register, login, JWT access + refresh (refresh-token storage strategy
  decided — see Cross-Cutting). Profile includes `bodyweight_default` and
  `preferred_unit` (so bodyweight load is computable from day one).
- **Seed catalog**: a curated list of ~40-60 common exercises spanning all
  muscle groups and the three load types, each with a **researched
  `bodyweight_fraction`** where applicable (e.g. push-up ~0.64, pull-up ~1.0,
  dip ~0.96, feet-elevated push-up ~0.75). Fractions sourced from biomechanics
  literature; documented in a seed file with citations. Getting these wrong
  silently corrupts bodyweight volume, so they're treated as data, not
  throwaway fixtures.
- Exercise catalog API: list visible catalog (defaults + own custom),
  create/edit/delete **user-private** custom exercises; deletion blocked (409)
  when referenced. `muscle_group`/`equipment` are CHECK enums.
- Workouts: create, **bulk-save (`PUT`)**, finish, list, get (with inline
  `last_performance`), delete, **clone**, **repeat-last**.
- Sets/exercises: per-item endpoints for targeted edits; unique
  `(workout_id, order_index)` and `(exercise_id, set_index)` with app-managed
  reindexing.
- Frontend: auth, profile (bodyweight + unit), active workout flow with
  **IndexedDB persistence** + bulk-save sync, **"Repeat last workout"** action,
  history list, exercise picker.

### Phase 1.5 - Progression fast-follow

- **Per-exercise prefill from last session** (`prefill_from_last` on add).
- **Batch last-performance** endpoint + exercise-picker "last: 80x8" hints.
- **Per-set / per-exercise "vs last time" deltas** in the active workout and
  workout detail (volume, weight@reps).

> Rationale: repeat-last already covers the common "same session as last time"
> flow, so the core ships in Phase 1; prefill + deltas are the natural next
> increment for ad-hoc exercise additions and in-session motivation.

### Phase 2 - Polish & Templates

- Workout templates + "start from template".
- Edit existing (finished) workouts.
- **Bodyweight history** (`bodyweight_entries`) — enables bodyweight trend and
  time-accurate `bw` resolution per workout (Phase 1 uses `bodyweight_default`).
- PWA: installable, offline mutation queue around bulk-save, background sync.
- Improved UX: rest timer, keyboard helpers, validation.

### Phase 3 - Statistics

- Summary, volume over time, frequency, PRs, estimated 1RM (weighted only —
  see Stats semantics).
- Charts on the Stats screen.
- Per-exercise progression view.

### Phase 4 - Mobile App

- Native (React Native/Flutter) consuming the same `/api/v1`.
- Offline-first sync (conflict resolution strategy).
- Push notifications (reminders).

### Phase 5 - Extras (later)

- Custom metrics: tempo, rest targets. (RPE is already an optional `sets`
  field from Phase 1 — it just isn't surfaced in stats until here.)
- Exercise images / videos.
- Import/export (CSV, JSON).
- Sharing workouts.

---

## 11. Cross-Cutting Concerns

- **Security**: bcrypt/argon2 hashes, JWT short-lived access + refresh
  rotation, input validation everywhere, rate limiting on auth endpoints.
  - **Token storage (web-now, native-later)**: access token kept **in memory
    only** (not localStorage) to limit XSS exposure. Refresh token delivered
    as an **httpOnly, Secure, SameSite=Strict cookie** on the web client.
    `POST /auth/refresh` accepts the refresh token from **either** the httpOnly
    cookie **or** the request body, so the future native app can store it in
    the OS secure enclave (Keychain/Keystore) and send it in the body while the
    web app relies on the cookie. Refresh rotation: each refresh issues a new
    refresh token and invalidates the old (reuse detection → revoke family).
- **Observability**: structured logging, request IDs, basic metrics.
- **Testing**: backend unit + integration (pytest + test db), frontend unit
  (Vitest) + E2E (Playwright).
- **CI**: lint, typecheck, tests, build on every PR.
- **Config**: environment-based (.env), no secrets in repo. Key vars:
  `DATABASE_URL` (SQLite or Postgres), `JWT_SECRET`, `JWT_ACCESS_TTL`,
  `JWT_REFRESH_TTL`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `APP_ENV`
  (dev/prod/test).
- **i18n**: keep strings externalized from day one (en first).
- **Units**: store kg internally; show lb in UI per `users.preferred_unit`.

---

## 12. Decision Log

Key decisions and their rationale (living record — update as decisions change):

- **Switchable DB: SQLite (MVP) → PostgreSQL (prod)** via a single
  `DATABASE_URL`; one schema, portable storage rules (TEXT UUIDs/timestamps,
  CHECK enums). Avoids a prod-only DB during local dev; CI tests both.
- **Synchronous backend** (plain `def` FastAPI endpoints in a threadpool; sync
  `sqlite3` / `psycopg3`): the workload is short CRUD transactions + scoped
  aggregate queries — DB-bound, not connection-juggling-bound — and there are
  no WebSockets/SSE/streaming needs. SQLite makes async fake anyway (aiosqlite
  = sqlite3 in a thread) and is single-writer regardless. Sync removes async
  coloring from the whole codebase (simpler to read, debug, test). Trade-off:
  lower per-process concurrency ceiling than async, mitigated by tunable
  threadpool size + horizontal scaling (more workers/nodes); the DB is the real
  constraint either way. `psycopg3` (sync+async capable) keeps async as an
  escape hatch if a future real-time feature ever needs it. See *Concurrency
  model*.
- **Raw SQL, no ORM** (§Why no ORM): shallow schema, analytics-heavy reads,
  switchable-DB. An ORM's relationship/unit-of-work machinery doesn't pay off,
  and lazy-loading N+1 risk sits on the hot path (workout → exercises → sets);
  raw SQL writes one explicit fetch. We accept hand-written SQL + raw-SQL
  Alembic migrations.
- **Bulk-save (`PUT /workouts/{id}`) is the primary active-workout write path**
  — one request for the whole exercise+set graph instead of per-set
  round-trips. Critical for mobile UX and offline sync (the bulk-save is the
  unit of queuing/retry; `Idempotency-Key` makes retries safe).
- **"Repeat last workout" before per-exercise prefill**: repeat-last
  (`POST /workouts/repeat-last`) covers the dominant "same session as last
  time" flow and ships in Phase 1; per-exercise prefill + vs-last deltas are a
  Phase 1.5 fast-follow for ad-hoc additions.
- **Custom exercises are user-private**; defaults are global and immutable.
  `exercises.catalog_id` is `ON DELETE RESTRICT` so a custom exercise can't be
  deleted while referenced by history (409 instead of orphaning).
- **`bodyweight_fraction` is researched data, not fixtures** — wrong fractions
  silently corrupt all bodyweight volume/PR stats, so the seed catalog cites
  sources and is maintained deliberately.
- **1RM / weight-PRs are weighted-only**: Epley on `bw*fraction` for high-rep
  bodyweight work is meaningless; bodyweight PRs use max-reps instead.
- **Bodyweight resolution**: time-accurate via `bodyweight_entries` (Phase 2);
  Phase 1 falls back to `users.bodyweight_default`. If both are null, bodyweight
  effective_load/volume is `null` (excluded from sums, never 0) and the UI
  prompts for a bodyweight.
- **Refresh-token storage**: httpOnly cookie on web, request-body for native;
  access token in memory only. Chosen so the same `/auth/refresh` endpoint
  serves both the web MVP and the future native app without redesign.
- **Active-workout local persistence (IndexedDB)**: a refresh/crash/network
  drop must never lose an in-progress session; local draft reconciles with
  server on reconnect.
