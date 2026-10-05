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

---

## 2. High-Level Architecture

```
+-------------------+        +------------------+        +-------------------+
|   Web Frontend    |        |   Backend API    |        |    Database       |
|  (mobile-first)  | <----> |   (REST / JSON)  | <----> |  (PostgreSQL)     |
+-------------------+        +------------------+        +-------------------+
        |                            |
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

- **Language/Framework**: Python + FastAPI (async, auto OpenAPI docs, fast
  iteration) — *alternative*: Node.js + Fastify/NestJS.
- **Database**: **switchable** — **SQLite** for MVP/local dev (zero setup,
  file-based), **PostgreSQL** for production. Same app code targets both via a
  thin async DB layer over `aiosqlite` / `asyncpg`. Selected by `DATABASE_URL`
  (e.g. `sqlite+aiosqlite:///./fittrack.db` vs
  `postgresql+asyncpg://...`). See *Database Portability* below.
- **Data access**: **raw SQL** — no ORM. Hand-written SQL queries executed via
  async drivers (`aiosqlite` for SQLite, `asyncpg` for Postgres) behind a small
  in-house executor that normalizes parameter style (`?`/`:name` vs `$1`) and
  returns rows mapped to Pydantic models. Schema lives as SQL files; migrations
  via Alembic in raw-SQL mode (`op.execute("...")`). Rationale: shallow schema,
  analytics-heavy reads, switchable-DB — an ORM's relationship/unit-of-work
  machinery doesn't pay off and adds async footguns. See *Why no ORM*.
- **Validation**: Pydantic v2 (comes with FastAPI); response/request schemas
  also double as row-shape mappers for query results.
- **Auth**: JWT access + refresh tokens; bcrypt/argon2 password hashing.
- **Testing**: pytest (with a temporary SQLite DB per test, or test Postgres in CI).
- **Containerization**: Docker + docker-compose. MVP backend can run without a
  DB container (SQLite file); compose includes an optional Postgres service
  + adminer for prod/dev-parity when needed.

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
- `bw` = user's bodyweight at the time of the workout (most recent
  `bodyweight_entry` on/before `workout.started_at`, falling back to
  `users.bodyweight_default`).
- `fraction` = the catalog exercise's `bodyweight_fraction` (nullable).
- `side_count` = catalog field, `1` for unilateral (e.g. single-arm DB row,
  logged reps are per side), `2` for bilateral (default).

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
  created_at    TIMESTAMPTZ
  updated_at    TIMESTAMPTZ

exercise_catalog
  id            UUID PK
  name          TEXT NOT NULL
  muscle_group  TEXT        -- chest, back, legs, ...
  equipment     TEXT        -- barbell, dumbbell, bodyweight, ...
  load_type     TEXT NOT NULL  -- single_weight | split_weight | bodyweight
  bodyweight_fraction NUMERIC(4,3)  -- nullable; share of BW moved (e.g. 1.000, 0.650)
  side_count    SMALLINT DEFAULT 2   -- 1 unilateral, 2 bilateral (for split_weight)
  is_default    BOOLEAN DEFAULT FALSE
  created_by    UUID NULL FK users(id)  -- NULL for defaults; =owner for custom (user-private)
  -- uniqueness: name distinct within a user's visible catalog
  --   (defaults unique globally; custom unique per created_by)
  -- indexes: index_exercises_by_owner(created_by) WHERE created_by IS NOT NULL
  --          index_exercises_visible -- none needed; union at query time

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
  order_index   INT
  notes         TEXT
  -- index: (catalog_id, workout_id) for "last performance" lookups
  -- (join workouts for started_at ordering; see Last Performance query)

sets
  id            UUID PK
  exercise_id   UUID FK exercises(id) ON DELETE CASCADE
  set_index     INT
  reps          INT
  weight        NUMERIC(10,2)   -- kg; meaning depends on load_type (per-side for split)
  bw_fraction_override NUMERIC(4,3) NULL  -- per-set override of catalog fraction (position change)
  rpe           NUMERIC(3,1)    -- rate of perceived exertion, optional
  done          BOOLEAN DEFAULT FALSE
  created_at    TIMESTAMPTZ

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

- **Driver/URL**: single `DATABASE_URL` env var selecting the async driver:
  `sqlite+aiosqlite:///./fittrack.db` or `postgresql+asyncpg://...`. A thin
  in-house `db` module wraps the driver and normalizes parameter style
  (rewrite `:name` ↔ `?` ↔ `$1` per dialect) so SQL strings are shared.
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
  holding JSON if ever needed), `INTERVAL`, generated columns, returning
  clauses that differ, partial/unique indexes that aren't portable. Use
  portable `RETURNING *` only where both drivers support it (aiosqlite via
  SQLite 3.35+).
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
  user. Postgres for multi-user prod. Keep transactions short; only use
  `BEGIN IMMEDIATE`-style hints on SQLite (guarded by dialect check) where
  needed.
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
- Async ORM footguns (N+1, `MissingGreenlet` on lazy access) sit exactly on
  the hot path (workout → exercises → sets).
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
| GET    | /workouts/{id}        | Get workout with exercises/sets   |
| PATCH  | /workouts/{id}        | Update workout metadata           |
| DELETE | /workouts/{id}        | Delete workout                    |
| POST   | /workouts/{id}/finish | Mark workout as finished          |

### Exercises (within a workout)

| Method | Path                                          | Description          |
|--------|-----------------------------------------------|----------------------|
| POST   | /workouts/{wid}/exercises?prefill=true        | Add exercise to workout (optionally prefill sets from last session) |
| GET    | /workouts/{wid}/exercises/{eid}/last          | Last session values for this exercise (for live comparison) |
| PATCH  | /workouts/{wid}/exercises/{eid}               | Update exercise      |
| DELETE | /workouts/{wid}/exercises/{eid}               | Remove exercise      |

> **Prefill from last session** (`POST /workouts/{wid}/exercises?prefill=true`):
> looks up the caller's most recent *finished* workout containing this
> `catalog_id` (same as the Last Performance endpoint), creates the exercise
> instance, and seeds it with the **same number of sets** as that last
> instance, copying `reps`/`weight`/`rpe` per set index into new, editable
> (not-done) sets. The user can then change weight, reps, add or remove sets.
> If no prior session exists, the exercise is created with one empty set.

### Sets

| Method | Path                                                              | Description   |
|--------|-------------------------------------------------------------------|---------------|
| POST   | /workouts/{wid}/exercises/{eid}/sets                             | Add set       |
| PATCH  | /workouts/{wid}/exercises/{eid}/sets/{sid}                        | Update set    |
| DELETE | /workouts/{wid}/exercises/{eid}/sets/{sid}                        | Delete set    |

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
- **Personal records (PRs)**: max weight for reps, max estimated 1RM per exercise.
- **Estimated 1RM**: Epley formula `1RM = w * (1 + reps/30)`.
- **Progression**: weight@reps over time for a given exercise.
- **vs last session**: for each exercise in the active/recent workout, compare
  current set values (reps, weight, effective_load) and total exercise volume
  against the previous session for the same `catalog_id` — surface per-set
  deltas and a total-volume delta so the user sees progress vs last time.
- **Bodyweight trend** (optional).

---

## 8. Frontend Screens (Mobile-First)

1. **Auth**: login / register.
2. **Home / Dashboard**: recent workouts, quick start, weekly summary.
3. **Active Workout**:
   - List of exercises with collapsible sets.
   - Big touch-friendly inputs for reps / weight.
   - "Add set", "Add exercise", "Finish workout".
   - **Add exercise → prefill**: when adding an exercise previously done, the
     app seeds the same number of sets as the last session with last-time
     reps/weight (editable). Each set row also shows a faint "last: 80x8"
     hint for comparison; the user edits weight/reps/set-count live.
   - **Per-set + per-exercise "vs last time" delta** (volume, weight@reps) so
     the user sees progress in-session.
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
      db/                # thin async executor: driver, param-style normalize, row->Pydantic mappers
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

### Phase 1 - Foundation (MVP backend + minimal UI)

- Backend: project scaffolding, FastAPI + raw SQL (aiosqlite/asyncpg) + thin
  executor + Alembic raw-SQL migrations; **SQLite** (local) as default DB,
  Postgres-ready via `DATABASE_URL`. Seed catalog with example exercises per
  load type.
- Auth: register, login, JWT, refresh.
- Exercise catalog: seed default exercises, list visible catalog (defaults +
  own custom), create/edit/delete **user-private** custom exercises; block
  deletion when referenced.
- Workouts CRUD: create, add exercises (with **prefill from last session**),
  add/edit/remove sets, finish, list, get, delete.
- Frontend: auth, active workout flow (prefill + per-set "vs last time"
  hints), history list.

### Phase 2 - Polish & Templates

- Workout templates + "start from template".
- Edit existing workouts.
- Bodyweight tracking.
- PWA: installable, offline form queue, background sync.
- Improved UX: rest timer, keyboard helpers, validation.

### Phase 3 - Statistics

- Summary, volume over time, frequency, PRs, estimated 1RM.
- Charts on the Stats screen.
- Per-exercise progression view.

### Phase 4 - Mobile App

- Native (React Native/Flutter) consuming the same `/api/v1`.
- Offline-first sync (conflict resolution strategy).
- Push notifications (reminders).

### Phase 5 - Extras (later)

- Custom metrics (RPE, tempo, rest).
- Exercise images / videos.
- Import/export (CSV, JSON).
- Sharing workouts.

---

## 11. Cross-Cutting Concerns

- **Security**: bcrypt/argon2 hashes, JWT short-lived access + refresh
  rotation, input validation everywhere, rate limiting on auth endpoints.
- **Observability**: structured logging, request IDs, basic metrics.
- **Testing**: backend unit + integration (pytest + test db), frontend unit
  (Vitest) + E2E (Playwright).
- **CI**: lint, typecheck, tests, build on every PR.
- **Config**: environment-based (.env), no secrets in repo. Key vars:
  `DATABASE_URL` (SQLite or Postgres), `JWT_SECRET`, `JWT_ACCESS_TTL`,
  `JWT_REFRESH_TTL`, `APP_ENV` (dev/prod/test).
- **i18n**: keep strings externalized from day one (en first).
- **Units**: store kg internally; show lb in UI per user setting.
