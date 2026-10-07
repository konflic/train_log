# BaseFit - Implementation Plan (MVP / Phase 1)

Companion to `PLAN.md`. `PLAN.md` defines **what** to build (contracts,
architecture, permanent rules). This file defines **in what order** to build it
so every step is small, testable, and verifiable before the next one starts.

Scope = `PLAN.md` §10 **"Phase 1 - Reliable, usable core"** and its **15
acceptance checks**. Phases 2-3 are out of scope here.

## Implementation status

- **Completed:** Stage 0 was merged to `master` in
  [PR #1](https://github.com/konflic/train_log/pull/1) on 2026-10-06 (`75065b4`).
  Gate G0 passed locally and in GitHub CI: backend lint, format,
  typecheck, and tests; frontend check, lint, unit tests, and production build;
  and Playwright browser smoke tests.
- **Completed:** Stage 1 was merged to `master` in
  [PR #3](https://github.com/konflic/train_log/pull/3) on 2026-10-06 (`4cf9760`).
  Gate G1 passed locally and in GitHub CI:
  - `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
    and `pytest -q` (60 tests) all green.
  - Isolated temporary database: `python migrate.py` applied `0001` + `0002`;
    a second run reported no pending migrations; `python -m app.backup backup`
    then `verify` (integrity_check + foreign_key_check + workout-graph read)
    passed; no WAL sidecars next to the backup file.
  - Tests cover: migrate-from-empty (all tables STRICT, WAL on, seed present,
    `foreign_key_check` clean); re-run no-op; failed migration rolls back
    DDL/data/version record and resumes after fix; migration transaction/PRAGMA
    escape attempts are rejected atomically; unknown recorded version refused;
    STRICT rejects fractional/non-convertible integers, BLOBs in TEXT, and
    impossible/non-canonical timestamps (lossless `1.0`/`"12"`/bool coercion
    documented for Stage 2); FK cascade/restrict; partial unique catalog-name
    indexes per scope; previous → current migration preserves data/indexes/FKs;
    backup while WAL holds committed data → restore → verify + direct graph
    reads; missing/corrupt backup sources fail without leaving an output; held
    write lock past busy timeout → retryable `DatabaseBusyError`, retry succeeds.
- **Completed:** Stage 2 was merged to `master` in
  [PR #4](https://github.com/konflic/train_log/pull/4) on 2026-10-06 (`3ee7e4e`).
  Gate G2 passed locally and in GitHub CI:
  - `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
    `pytest -q` (84 tests), and `pip check` all green.
  - `app/numbers.py` defines safe JSON/SQLite integer guards and documented
    floor-only bodyweight, external-load, effective-load, and volume
    calculations. Zero denominators and unknown inputs propagate as `null`.
  - `app/schemas/common.py` provides strict bounded integer Pydantic types and
    validates draft/completed set requirements without accepting unknown fields.
  - `tests/fixtures/numeric_examples.json` is the language-neutral numeric
    source of truth. Tests exercise every fixture example plus strict rejection
    of fractional, string, boolean, out-of-range, invalid completion, and
    incompatible bodyweight values.
- **Completed:** Stage 3 was merged to `master` in
  [PR #5](https://github.com/konflic/train_log/pull/5) on 2026-10-07 (`413996b`).
  Gate G3 passed locally on 2026-10-06, was reverified on 2026-10-07, and in
  GitHub CI on the PR:
  - `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
    `pytest -q` (190 tests), and `pip check` all green. Frontend
    `check`/`lint`/`test:unit` and the two Playwright E2E smoke tests still pass
    (no earlier gate regressed).
  - Dependency: added the maintained **Argon2id** library `argon2-cffi==25.1.0`
    (pinned in `pyproject.toml` and `constraints.txt`); reviewed the resolved
    tree (`argon2-cffi-bindings`, `cffi`, `pycparser`) and confirmed no local
    reimplementation of password hashing.
  - `app/auth.py`: Argon2id hash/verify; opaque sessions from
    `secrets.token_urlsafe(32)` storing only the SHA-256 hash + owner +
    created/expires; per-request session resolution that rejects **and deletes**
    expired rows; logout deletes the row; unknown-email logins still run one
    verification (dummy hash) so timing does not reveal account existence; a
    bounded in-memory `LoginThrottle` keyed by IP and (IP, email) with an
    injectable clock and a capped key set.
  - `app/schemas/auth.py`: strict Pydantic models (`extra="forbid"`) with email
    normalization (trim + lowercase + conservative format), bounded
    display_name/password and `utc_offset_minutes` (-720..840), and Stage 2
    strict integer bodyweight; `PATCH` distinguishes absent from explicit
    `null` via `model_fields_set`.
  - `app/services/users.py`: owner-scoped SQL; duplicate email surfaces as
    `DuplicateEmailError` from the `UNIQUE` constraint; `update_profile`
    whitelists writable columns and refuses email/role/status.
  - `app/api/auth.py` + `app/middleware/`: `POST /auth/register|login|logout`,
    `GET`/`PATCH /auth/me`. Established the shared API conventions reused by
    later stages: RFC 9457-style `application/problem+json` errors with stable
    `code` + `request_id`, `X-Request-ID` on every response, request-id access
    logging that never includes bodies/cookies/tokens, Origin+JSON CSRF checks
    on every mutating verb under `/api/v1` (GET exempt), and a 256 KiB body-size
    limit (Content-Length precheck + streaming counter); logout returns an empty
    204.
  - Cookies: HttpOnly, SameSite=Strict, `Path=/api/v1`; `Secure` follows
    `COOKIE_SECURE`; `create_app` refuses a non-Secure cookie outside the local
    HTTP `development`/`test` environments.
  - Tests added (+106): register/login/logout happy paths; cookie flags incl.
    Secure toggling; login stores only the token hash; generic identical 401 for
    wrong password vs unknown email; expired-session rejection + row deletion;
    logout revocation + cookie clearing; missing/mismatched Origin → 403 and
    non-JSON → 415 on mutating verbs while GET is exempt; throttling blocks
    after repeated failures, covers the per-IP bound, resets on success, and
    honors window expiry; profile writes affect only the authenticated account;
    strict rejection of unknown/server-controlled fields (role, account_status),
    fractional/string/boolean/out-of-range integers, and malformed emails; no
    password/hash/token appears in any response body or log; request-id and
    problem-document shape; oversized body → 413. Unit-focused review added
    direct coverage of unknown-user timing equalization, user lookup and error
    classification, throttle reset/pruning, email length bounds, and streamed
    body limits. A focused standard-library line trace reports 100% for
    `app.auth`, `app.schemas.auth`, and `app.services.users`, 100% for CSRF
    middleware, and 98% for the auth API module.
  - **Covers acceptance check 12 (CSRF/cookie/logout/no-secrets) and parts of
    6 and 11.**
- **Completed on this branch (PR pending):** Stage 4 - Exercise catalog API.
  Gate G4 passed locally on 2026-10-07; CI re-runs it on the PR:
  - `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
    `pytest -q` (296 tests, +106), and `pip check` all green. No earlier gate
    regressed (the whole Stage 0-3 suite still passes; CI runs it every time).
    No frontend changes, so the frontend/E2E checks are unchanged.
  - Dependency: none added. `app/db.py` registers one small deterministic
    `casefold(text)` SQL function on every connection so caseless search and
    ordering are Unicode-correct; SQLite's built-in `LIKE`, `upper()`/`lower()`,
    and `COLLATE NOCASE` fold ASCII only (verified: `'%жим%'` misses `'Жим'`).
    No new package and no local reimplementation of anything security-sensitive.
  - `app/schemas/exercises.py`: strict `extra="forbid"` create/update/response
    models. Content-only input (`id`/`is_default`/`created_by` are
    server-controlled and rejected); Unicode-aware name trim with codepoint
    bounds; cross-field load rules mirror the DB CHECKs (pure-bodyweight
    requires a percentage; only `split_weight` may be two-sided). `PATCH` is
    partial (explicit `null` clears only `bodyweight_percent`); the API merges it
    with the stored entry and revalidates through the create model, so a partial
    update cannot produce an entry a full create would reject.
  - `app/services/catalog.py`: owner-scoped SQL for list/get/create/update/
    delete. Visibility is `(is_default=1 OR created_by=:viewer)`, so a foreign
    custom is indistinguishable from an unknown id. The partial unique indexes
    are the authoritative race-free duplicate check (`DuplicateNameError`);
    defaults and foreign customs never match the owner-scoped `UPDATE`/`DELETE`
    `WHERE`, so they are immutable/undeletable at the storage layer too; the
    `ON DELETE RESTRICT` FK surfaces as `EntryInUseError`. Search escapes LIKE
    wildcards; listing orders by `casefold(name)` with an `id` tie-break (a
    total order, stable across pages).
  - `app/api/exercises.py`: `GET /exercises` (defaults + caller customs, search
    + muscle/equipment filters, bounded `page`/`pageSize` per PLAN.md §6,
    `total`, stable order), `GET /exercises/{id}`, `POST /exercises`,
    `PATCH /exercises/{id}`, `DELETE /exercises/{id}` (empty 204). Defaults
    immutable → 403 `default_immutable`; foreign/unknown → 404; duplicate name
    within scope → 409 `name_taken`; referenced-entry delete → 409
    `entry_in_use`. Reuses the Stage 3 conventions (problem+json, request id,
    Origin/JSON CSRF on mutating verbs, body-size limit) unchanged.
  - Tests added (+105): `tests/test_catalog_service.py` (direct-SQLite scoping,
    Unicode case-insensitive search with escaped wildcards, filters, casefold
    ordering + id tie-break, pagination bounds, in-scope uniqueness incl. case
    variants and cross-scope reuse, whitelisted owner-scoped updates, snapshot
    preservation, delete guard + freeing on history delete, UTF-8 round-trip)
    and `tests/test_exercises_api.py` (auth on all five verbs, visibility
    scoping across two users, search/filters/pagination, strict rejection of
    unknown/server-controlled and fractional/string/boolean/out-of-range fields,
    merged-PATCH validation, atomic partial updates that preserve interleaved
    unrelated edits, bounded page offsets, default immutability, delete-guard
    409, cross-user 404, unescaped UTF-8 output, and the shared
    problem+json/request-id/CSRF conventions).
  - **Covers parts of acceptance checks 6 and 9.**
- **Next:** Stage 5 - Workout create + read.

---

## Ground rules

- **One stage or lettered substage at a time.** Complete its exit gate before
  starting the next. Stages 6, 11, and 12 have mandatory intermediate gates;
  do not implement their entire scope in one pass. Split further if needed.
- Branches, commits, tags, and pushes follow the user's authorized workflow;
  passing a gate does not by itself authorize a Git operation.
- **A stage is DONE only when:** code + tests + docs are complete, the stage
  automated checks pass locally **and** in CI, any required manual verification
  has recorded evidence, and **no earlier gate regressed** (CI runs the whole
  suite every time).
- Update this file's implementation status within the stage branch. Completion
  evidence and the next-stage marker must be included in that stage's PR before
  merge, not deferred to a separate follow-up PR.
- **Backend stages (1-8) verify with `pytest`/API tests only** - no frontend
  required. **Frontend stages (9-13)** build against a running backend.
  **Stage 14** adds the cross-stack admin surface; **Stage 15** ties everything
  together end-to-end.
- **Single source of numeric truth.** The integer examples in `PLAN.md` §3 live
  in a language-neutral `tests/fixtures/numeric_examples.json` at the repo root,
  read directly by backend and frontend tests without a generator
  (`PLAN.md` §11 "shared example expectations"). Never hardcode them twice.
- **Repo root == project root.** `PLAN.md` §9's `basefit/` maps to this repo;
  create `backend/` and `frontend/` at the root.
- Keep dependencies minimal per `PLAN.md` §2; add one only when it removes real
  work.
- Remote QA follows `PLAN.md` §2 data isolation: production, human QA/beta, and
  automated E2E never share a database. Test reset means replacing a disposable
  database, not bulk-deleting marked rows from a mixed production database.
- Record completion evidence for each gate: implemented scope, commands and
  results, manual observations where relevant, and remaining blockers. Later
  tests in the traceability table are not proof that an earlier gate passed.

## Verification commands (introduced when their implementation exists)

- Backend: `cd backend && ruff check . && ruff format --check . && mypy app migrate.py && pytest -q`
- Migrations (Stage 1): `cd backend && python migrate.py` (honors `DATABASE_PATH`)
- Frontend: `cd frontend && npm run check && npm run lint && npm run test:unit`
- E2E: `cd frontend && npm run test:e2e` (Playwright)
- CI aggregate: all available checks above + `cd frontend && npm run build`.
  From Stage 1, migration checks use an isolated temporary database. E2E owns
  startup/readiness/teardown of its backend and frontend, with isolated data.

Stage 0 introduces backend, frontend, and browser smoke tests that actually
execute; do not mask empty suites with allow-no-tests flags. Feature-specific
checks join CI in their owning stage rather than waiting until Stage 15.

`NN` below = stage number; `GNN` = its exit gate.

---

## Stage summary

| MS | Stage | Deliverable (verifiable increment) | Primary verification | Est. days |
|----|-------|------------------------------------|----------------------|-----------|
| A. Foundation | **0** | Repo scaffold, tooling, CI skeleton, configs | lint/typecheck/test run green on skeleton | 1 |
| A | **1** | DB helper + migration runner + core STRICT schema + seed catalog | migrations, `PRAGMA foreign_key_check`, backup/restore | 2.5 |
| A | **2** | Integer contract: floor helpers + strict Pydantic types + shared examples | unit tests on §3 examples | 1 |
| B. Backend API | **3** | Auth: register/login/logout/me, sessions, cookies, CSRF, throttling | auth API tests | 2 |
| B | **4** | Exercise catalog CRUD + visibility/uniqueness/delete-guard | catalog API tests | 1 |
| B | **5** | Workout create (+fingerprint/retry) + history list + GET graph | workout read/create tests | 1.5 |
| B | **6a–6c** | **PUT bulk-save**: validation → graph persistence → receipt/concurrency/finish | three separate exit gates | 3 |
| B | **7** | DELETE + lifecycle rules (finished read-only, PUT-after-delete) | lifecycle tests | 0.5 |
| B | **8** | Stats summary + inline previous performance + JSON export | stats/prev-perf/export tests | 3.5 |
| C. Frontend | **9** | FE scaffold, theme, router, `api.ts`, BigInt helper | component/unit tests vs backend | 2 |
| C | **10** | Auth + read-only Home + Catalog screens | component + Playwright login/browse | 3 |
| C | **11a–11c** | Local drafts/export → durable create/save → reconnect/conflict/account handling | three separate exit gates | 3 |
| C | **12a–12c** | Local editor → synchronization/finish → repeat-last/conflict UI | three separate exit gates | 4 |
| C | **13** | History/detail + Settings + export UI + logout flow | Playwright settings/theme/export/acct-switch | 2.5 |
| D. Operations | **14** | Minimal admin API/panel + account controls + audit log | admin API/security tests + Playwright | 3 |
| E. Hardening | **15** | Acceptance evidence + production deployment smoke | full CI + deployment/restart checks | 5 |

The table totals **38.5 person-days**, including implementation and verification
within each stage. Reserve **8.5 additional days of contingency**, for a planning
budget of **47 person-days** (about nine to ten five-day working weeks for one
developer).
These are estimates, not gate deadlines; re-estimate after Stages 6c and 11c.
Lettered substages divide their parent's estimate rather than adding effort
again. Milestones: **A** = foundation, **B** = complete tested API, **C** = full
client, **D** = operational administration, **E** = shippable.

---

## Milestone A - Foundation

### Stage 0 - Repo, tooling, CI skeleton
**Purpose:** make every later gate runnable with one command.
**Scope:** `backend/` (`pyproject.toml`, `app/` package stubs per §9, `tests/`),
`frontend/` (`package.json`, `vite.config.ts`, `svelte.config.js`,
`tsconfig.json`, `src/` stubs), root `README.md`, `.github/workflows/ci.yml`,
lint/format/type configs (ruff, mypy strict, eslint, svelte-check, prettier),
`.gitignore` (db/WAL/backups/env out of Git per §5).
**Tasks:**
- Wire backend/frontend checks and browser smoke tests with real minimal cases:
  a backend app smoke request, a frontend render, and a browser shell load.
  Include E2E server startup/readiness/teardown. Migration execution starts in S1.
- CI job: backend lint+type+test, frontend check+lint+test+build, and browser
  smoke tests (build of a trivial app is fine now).
- Pin Python/Node versions; document `DATABASE_PATH`, `APP_ORIGIN`,
  `SESSION_TTL_SECONDS`, `COOKIE_SECURE`, `APP_ENV` (§11) as env, with a
  local-dev default.
**Verification:** backend checks, frontend checks/build, and browser smoke tests
exit 0 with tests collected; CI runs those same checks.
**Gate G0:** fresh clone → documented dependency installation → smoke checks
green locally and in CI. No feature API, migration, or export is required yet.

### Stage 1 - Database foundation and migrations
**Purpose:** correct, versioned, STRICT schema with safe ops. (`PLAN.md` §5)
**Scope (relative to `backend/`):** `app/db.py`, `app/config.py`,
`migrations/*.sql`, `migrate.py`, `app/backup.py`, seed catalog data.
**Tasks:**
- `db.py`: open/use/close on **same thread**, `check_same_thread=True`,
  `PRAGMA foreign_keys=ON`, bounded `busy_timeout`, enable **WAL once** at init,
  `sqlite3.Row`, `BEGIN IMMEDIATE` write helper, timeout → retryable service
  error. Validate linked SQLite runtime ≥ 3.37 at startup (§3).
- Migration runner: numbered SQL, `schema_migrations` table, transactional per
  migration, stop on failure, run explicitly (not per worker).
- `0001` schema: `users, sessions, exercise_catalog, workouts, exercises, sets`
  as **STRICT** tables, `NOT NULL` PKs, all CHECKs, indexes, and the two partial
  unique indexes on catalog names (§5). TEXT UUIDs, canonical UTC timestamps,
  0/1 booleans. Admin role/status fields and the audit table are introduced by
  a later numbered migration in Stage 14.
- `0002` seed catalog: small default set with muscle_group/equipment/load_type/
  `bodyweight_percent` estimates + provenance note (§4).
- `backup.py`: `sqlite3.Connection.backup()` / `VACUUM INTO`; restore verifier
  runs integrity + `foreign_key_check` + a representative workout read.
**Verification:** `pytest` for: migrate from empty; re-run is a no-op; a failed
migration rolls back data/DDL/version recording; STRICT INTEGER columns reject
non-integral values and non-convertible types; FK cascade/restrict behave;
partial unique indexes enforce per-scope name uniqueness; seeded previous
migration → current migration preserves data/indexes/FKs; backup while WAL has
committed data → restore → integrity/foreign-key checks and direct graph reads.
SQLite may losslessly coerce `1.0` or numeric text into INTEGER; rejecting those
API input types belongs to Pydantic checks in Stage 2. Exercise table-rebuild
preservation when an actual schema change requires it, rather than inventing a
production migration solely for a test.
**Gate G1:** migrations idempotent + transactional; `foreign_key_check` clean;
backup/restore verified. **Covers acceptance check 13 (with S15).**

### Stage 2 - Integer-only contract
**Purpose:** one arithmetic/validation core both sides mirror. (`PLAN.md` §3)
**Scope:** `app/numbers.py` (floor helpers, calc order, safe-range checks),
`app/schemas/common.py` (strict int types), root
`tests/fixtures/numeric_examples.json` (the shared example table).
**Tasks:**
- Python floor helper (`//`) + calc order: `bodyweight_load`,
  `external_load` (multiplier = 1 or `side_count`), `effective_load`,
  `set_volume`; `null` propagation when a percentage applies but bodyweight is
  unknown; zero denominator → `null`.
- Strict Pydantic types rejecting float/str/bool in integer fields; ranges
  (completed reps > 0, draft reps/weight may be missing; present weighted weight
  ≥ 0 / bodyweight weight must be `null`; RPE 1..10, percent 1..100, indexes ≥ 0).
  Validate bounds and cross-field completion rules. No silent truncation.
- Safe-integer/range guards before emitting JSON numbers.
- Shared fixture table with §3 examples (81@65%→52; 10×52→520; 12×2×8→192;
  `-100//3 = -34`; zero-denominator→null; null-vs-0 cases).
**Verification:** `pytest` asserts every fixture example + rejection cases.
**Gate G2:** arithmetic + validation match documented examples. **Covers
acceptance check 9 (backend half).**

---

## Milestone B - Backend API (complete, tested without a frontend)

### Stage 3 - Auth and sessions
**Purpose:** secure login + profile, authoritative validation. (`PLAN.md` §11, §6)
**Scope:** `app/auth.py`, `app/api/auth.py`, `app/schemas/auth.py`,
`app/services/users.py`, `app/middleware/` (Origin/CSRF, request-id logging,
size limits), auth throttling.
**Tasks:**
- Argon2id password hashing (maintained lib). Opaque sessions:
  `secrets.token_urlsafe(32)`, store SHA-256 hash + owner + created/expires.
- Cookie: HttpOnly, Secure, SameSite=Strict, `Path=/api/v1`; non-Secure only for
  configured local HTTP dev. Never log/persist the raw token.
- Endpoints: `POST /auth/register|login|logout`, `GET /auth/me`,
   `PATCH /auth/me` (display_name, bodyweight_default_kg, utc_offset_minutes
   bounded to -720..840). Email normalization before store.
- CSRF: mutating browser requests require JSON + exact allowed `Origin`; GET
  side-effect-free; reject mismatch. Bounded login throttling; generic errors;
  request/body size limits. No secrets in any output.
- Per-request session lookup; reject expired; delete row on logout.
- Establish shared API conventions now: RFC 9457-style errors, explicit public
  response schemas, unknown/server-controlled input-field rejection, and empty
  204 responses. Subsequent resource stages reuse and verify these conventions.
**Verification:** `pytest` for register/login/logout happy paths; cookie flags;
expired-session rejection; logout revocation; Origin mismatch/absent rejected on
mutating verbs; throttling triggers; public auth JSON contains no password/hash/
session token; profile reads/writes affect only the authenticated account.
Session cookies are the intended token delivery channel. Export secret exclusion
is verified when export exists in Stage 8.
**Gate G3:** auth solid. **Covers checks 12 (CSRF/cookie/logout/no-secrets) and
part of 6, 11.**

### Stage 4 - Exercise catalog API
**Purpose:** default + owner-private custom entries. (`PLAN.md` §4, §6)
**Scope:** `app/api/exercises.py`, `app/schemas/exercises.py`,
`app/services/catalog.py`.
**Tasks:** `GET /exercises` (defaults + caller customs, search + muscle/equipment
filters, bounded page/pageSize, `total`, stable order w/ id tie-break),
`GET /exercises/{id}` (visibility), `POST /exercises`, `PATCH /exercises/{id}`,
`DELETE /exercises/{id}`. Defaults not editable; customs owner-scoped;
name-unique within scope; referenced entry delete → 409; other-user entry → 404.
**Verification:** `pytest` for scoping/visibility, search+filters+pagination,
uniqueness within scope, default-immutable, delete-guard 409, cross-user 404.
**Gate G4:** catalog CRUD correct + scoped. **Covers part of checks 6, 9.**

### Stage 5 - Workout create + read
**Purpose:** online creation with idempotent retry; history + graph read.
(`PLAN.md` §6, §5)
**Scope:** `app/api/workouts.py` (GET list, POST create, GET one),
`app/schemas/workouts.py`, `app/services/workouts.py` (read side).
**Tasks:**
- `POST /workouts`: client UUID + `started_at`; copy profile bodyweight into
  `workouts.bodyweight_kg` (keep null); revision 0; canonical
  `create_request_hash`. Same ID+fingerprint → existing owned workout; different
  content same ID → 409; never another user's row.
- `GET /workouts`: history with date + active/finished filters, bounded paging,
  stable `(started_at,id)` order.
- `GET /workouts/{id}`: graph via a **fixed small number of queries**
  (no per-set query), recorded load inputs, revision, `last_save_id`. (Previous
  performance is added in Stage 8.)
**Verification:** `pytest` for create; retry returns same row (no dup);
conflicting retry → 409; list filters/order/paging; ownership 404; recorded
bodyweight snapshot unaffected by later profile edits.
**Gate G5:** create/retry idempotent + reads correct. **Covers part of checks
2, 6, 10.**

### Stage 6 - Workout bulk-save (PUT) — the hard core
**Purpose:** one atomic, idempotent, conflict-safe write path. (`PLAN.md` §5, §6)
**Scope:** `app/services/workouts.py` (write side), `PUT /workouts/{id}`.

Implement **6a → 6b → 6c** as separate work increments. Keep incomplete write
services internal until the public PUT contract is complete in 6c.

#### Stage 6a - Graph validation and historical snapshots
- Define full-graph input/output models, graph/text/numeric limits, duplicate-ID
  rejection, parent ownership, catalog visibility, side/load/override rules,
  and draft-versus-completed-set validation.
- New instances copy catalog load settings on first persistence; existing
  instances retain snapshots and cannot change catalog identity through PUT.
  Writable workout bodyweight corrections remain explicit.
- Array order defines dense indexes; client snapshots/owner/timestamp fields
  are rejected. Validation used for writes executes within their transaction.
**Verification:** service/schema tests with owned and foreign graphs, duplicate
IDs, changed catalog defaults, null inputs, invalid sides, and unknown fields.
**Gate G6a:** valid graphs have explicit snapshot decisions; invalid graphs
leave the database unchanged. No public partial PUT endpoint yet.

#### Stage 6b - Atomic graph replacement and reordering
- Implement the transaction-owned persistence operation using 6a validation:
  delete omitted rows, move retained positions to distinct temporary indexes,
  apply dense final positions, and insert new rows.
- Validate all parent/ID relationships before mutations; do not reparent rows
  through upserts. Persist metadata and snapshots with the graph.
**Verification:** real SQLite tests for add/remove/swap/reverse ordering of
exercises and sets, cross-parent IDs, snapshot preservation, and rollback after
an injected failure midway through mutation.
**Gate G6b:** graph replacement is atomic and unique-index-safe. Public receipt,
revision, and finish behavior is introduced only in 6c.

#### Stage 6c - Public save protocol, concurrency, and finish
**Tasks (single `BEGIN IMMEDIATE` transaction, in order):**
1. Auth + load owned workout (PUT never creates).
2. Validate request; fingerprint canonical validated content.
3. `save_id == last_save_id` → require same fingerprint, return saved
   graph/revision without re-applying; different content same id → 409.
4. Else require exact `revision` match; mismatch → 409 + conflict code + current
   revision; change nothing.
5. Validate lifecycle, nested ownership, catalog visibility, and all invariants;
   validate submitted ids belong to this parent or are new/global-unused.
6. Apply the Stage 6b graph replacement: delete omitted rows → move retained to
   distinct temp indexes above old+new ranges → apply final dense indexes →
   insert new rows (never a direct occupied swap).
7. Optional `ended_at` finish (tz-aware, `ended_at >= started_at`, not future);
   increment revision; record `last_save_id`/`last_save_hash`; commit.
8. Return authoritative graph, revision, last save id.
- Finished workouts reject new saves; only an exact accepted-finish retry is
  allowed. A receipt superseded by another accepted save becomes a normal
  revision conflict, not an assumed earlier success.
- Busy timeout → retryable service error; **never** discard client draft.
**Verification:** `pytest` for: add/remove/**reorder** exercises+sets under
unique indexes; atomic save-and-finish; `save_id` retry (no double revision
increment, no dup rows); revision-conflict 409; nested/foreign ids rejected with
no partial write; snapshot load settings immutable via PUT; completed-vs-draft
set validation. Use independent connections to real SQLite files for two
deterministic concurrency cases:
- Two different saves with the same base revision and sufficient lock-wait
  time → one success, one 409, exactly one revision increment.
- A separately held write lock exceeds the busy timeout → retryable service
  error, no partial mutation; retry after releasing the lock succeeds.
Also verify same-save-ID/different-content rejection, superseded receipt
conflicts, and exact finish retry versus a new write to a finished workout.
**Gate G6c / G6:** public bulk-save is atomic, idempotent, and lifecycle-safe;
all 6a/6b checks still pass. **Covers checks 2 (save/finish server half),
4 (server half), 5 (server half), 6, 7.**

### Stage 7 - Delete + lifecycle
**Purpose:** safe deletion and finished-workout rules. (`PLAN.md` §6)
**Scope:** `DELETE /workouts/{id}?revision=N`, lifecycle guards in service.
**Tasks:** DELETE checks revision in its transaction; retain the Stage 6c rule
that finished workouts are read-only except delete + exact finish retry; queued
PUT after delete → 404 (do not recreate); lost delete response resolvable by GET 404.
**Verification:** `pytest` for delete revision match/mismatch; PUT-after-delete
→ 404; finished read-only + exact-finish-retry; GET-after-delete → 404.
**Gate G7:** lifecycle rules enforced. **Covers part of checks 2, 11.**

### Stage 8 - Stats, previous performance, export
**Purpose:** useful comparisons + recoverable data. (`PLAN.md` §7, §6)
**Scope:** `app/services/stats.py`, `app/api/stats.py`,
prev-perf in `GET /workouts/{id}`, `app/api/export.py`.
**Tasks:**
- `GET /stats/summary`: only **finished workouts + `done=true` sets**; volume
  summed with `unknown_load_set_count` + completeness flag (all-unknown → null;
  no eligible → 0); frequency (finished w/ ≥1 completed set) and muscle-group
   frequency; day/week grouping via the user's fixed UTC offset (Monday start,
   half-open ranges); weekly streaks (current week may be ongoing). Floor all
   averages/percentages.
- Inline previous performance in workout GET: most recent strictly-earlier
  finished session per catalog id, all instances in workout order, pair by order
  then completed sets by **side + ordinal**; compare only compatible load
  settings/overrides; unmatched → no delta; bounded queries.
- `GET /export`: versioned JSON of user training data + recorded inputs +
  referenced catalog data; **exclude** auth secrets/session/password.
- Estimated 1RM: weighted-only, no bodyweight contribution; 1 rep → load;
  2..10 → `external_load*(30+reps)//30`; >10 → null.
**Verification:** `pytest` for eligibility; mixed known/unknown loads return the
known sum with `unknown_load_set_count > 0` and an incomplete flag; all-unknown
eligible loads return null; no eligible sets return known 0;
offset grouping + streak edge cases; prev-perf pairing incl. left/right not paired,
negative-delta floor, changed catalog → no fake progress; profile/catalog edits
don't rewrite existing totals; export excludes secrets; 1RM rules.
**Gate G8:** stats/prev-perf/export correct. **Covers checks 8 (server half),
9, 10, 12 (export secrets).**

> **Remote deployment checkpoint:** after this stage we can start testing an
> API deployment on a remote server with private QA access. Run the production
> artifact under a separate QA origin/process and `DATABASE_PATH`; never use the
> production user database. This is an integration environment, not a
> user-facing beta or production release.

> **Milestone B exit:** the full API is complete and green under `pytest` with no
> frontend. This is the contract the client builds against.

---

## Milestone C - Frontend (builds against the live API)

### Stage 9 - Frontend foundation
**Purpose:** runnable client shell that talks to the API. (`PLAN.md` §2, §8)
**Scope:** `frontend/src/main.ts`, `App.svelte`, `api.ts`, `lib/numbers.ts`
(BigInt floor helper), theme module, router (`svelte-spa-router`), Tailwind,
Vite `/api` proxy, bottom-nav layout.
**Tasks:** theme via root CSS class, system pref on first visit (light fallback),
persist explicit choice in localStorage, **apply before first paint**; `api.ts`
fetch helpers + TS types mirroring backend schemas; BigInt floor division with
remainder correction for negatives + safe-range check; import the **shared
numeric examples** and assert parity with backend.
**Verification:** `npm run test:unit` for numbers (same fixtures as S2) +
theme persistence + `api.ts` against a running backend; `npm run check`/lint.
**Gate G9:** fetch helpers authenticate and call the API in the test harness;
arithmetic matches backend. Login screens arrive in Stage 10.
**Covers check 9 (frontend half), part of 14.**

### Stage 10 - Auth, Home, Catalog screens
**Purpose:** login + navigation + browse. (`PLAN.md` §8)
**Scope:** `features/auth`, `features/home`, `features/catalog`, `routes/`.
**Tasks:** Auth (register/login); read-only Home (active workout list, recent
history summaries, weekly summary); Catalog (search, muscle filters,
default/custom labels, create/edit own). Do not expose unfinished workout action
buttons. Draft-safe reauthentication is integrated in 12b, and quick start,
resume, picker integration, and repeat-last arrive in 12a–12c.
Mobile rules: single column, bottom nav, ≥44px targets, visible labels/errors,
keyboard accessible, `inputmode="numeric"` + integer steps.
**Verification:** component tests (Svelte Testing Library) + Playwright:
register→login→browse catalog→create custom→see home history summaries.
**Gate G10:** user can log in, manage catalog, and view home summaries. Full
history/detail navigation is introduced in Stage 13.

### Stage 11 - IndexedDB draft + pending-save layer
**Purpose:** reliable local persistence and recovery. (`PLAN.md` §6)
**Scope:** `frontend/src/db.ts` (`idb`), a small sync/save coordinator.

Implement **11a → 11b → 11c** without requiring the editor UI. Use coordinator
tests for state transitions and a small browser harness for real IndexedDB,
reload, and multiple-tab behavior; integrate user controls in Stage 12.

#### Stage 11a - Local persistence, draft recovery, and export
- Partition by **account ID + workout ID + editor/draft ID**; keep one editor
  per workout per tab. Recover stored drafts explicitly rather than silently
  selecting or overwriting another tab's draft.
- Persist each edit before reporting "locally saved". Surface storage failures
  and do not promise recovery of data actually evicted by the browser.
- Implement a versioned **local-draft export** containing latest edits,
  recorded/provisional load inputs with their status, referenced catalog data,
  and recovery metadata. Exclude credentials. It must work offline or after
  session expiry, without fetching the server's saved copy.
**Verification:** real IndexedDB survives reload; separate tabs retain distinct
drafts; failed writes do not report success; local export contains unsynced
edits and can be downloaded without network/authentication. Use an available
app shell for offline reload tests; cold offline app startup remains Phase 2.
**Gate G11a:** locally acknowledged edits survive reload, draft selection is
explicit, and a versioned local export preserves the latest content.

#### Stage 11b - Durable create requests and immutable pending saves
- Before online POST, persist the create UUID and immutable request locally.
  Retain them until acknowledgement; after an uncertain response resolve the
  original ID/request before allowing a new create. Do not regenerate IDs or
  blindly replay creates when the workout has been deleted elsewhere; starting
  anew requires an explicit user decision. Offline creation remains out of scope.
- Store the latest editable draft separately from at most one immutable
  pending PUT payload (`revision`, `save_id`, content). Persist it before send;
  later edits must not mutate it. Retry its exact content after response loss.
- On success, atomically persist the returned revision/acknowledgement and
  retire the pending payload without overwriting newer local edits. Only then
  prepare a newer save with a new save ID. If acknowledgement persistence fails,
  retain the recoverable pending state and pause advancement.
**Verification:** lose POST/PUT/finish responses **after server commit**, reload,
and recover without duplicate rows, new create IDs, or double increments; crash
after response arrival but before local acknowledgement persistence; edit while
PUT is in flight; export those newer edits; simulate local acknowledgement-write
failure. A deleted uncertain create must not silently reappear.
**Gate G11b:** creation and saves survive uncertain responses and reload; newer
edits remain intact and later saves use only durably acknowledged revisions.

#### Stage 11c - Reconnect, conflict, and account handling
- On relaunch/reconnect authenticate the same account, resume an uncertain save
  first, and fetch current state before other pending work. A newer server
  revision does not silently advance a local draft's base revision.
- Stop automatic saves on conflict and retain the draft. Expose coordinator
  actions for use-server, local export/copy-to-new, and explicit replacement
  using a freshly fetched revision only where lifecycle permits.
- Session expiry pauses uploads without deleting drafts. A 404 after deletion
  retains the draft and requires explicit recovery; PUT never recreates it.
- Guard all queued work and delayed responses by account/draft identity. Logout
  clears account-local data only after the selected sync/export action succeeds
  or discard is explicitly confirmed; failed/cancelled actions preserve data.
**Verification:** two tabs create a stale-revision conflict and both drafts
  survive reload; session expiry/reauthentication, account switching with an
  in-flight request, deleted workout, and failed export/sync during logout.
**Gate G11c / G11:** recovery and account isolation pass coordinator/browser
tests. **Covers checks 1–4 and 11 at the persistence/coordinator layer; full
editor flows are verified in Stage 12.**

### Stage 12 - Active workout editor
**Purpose:** the core logging UX. (`PLAN.md` §8, §6)
**Scope:** `features/workout` (editor, set rows, exercise blocks, sync status),
repeat-last draft copy.

Implement **12a → 12b → 12c** with a user-visible demonstration at each gate.

#### Stage 12a - Locally persistent editor
- Wire quick start to durable online creation and resume to explicit draft
  recovery. Integrate the catalog picker, large integer inputs, add/remove/
  reorder exercises and sets, done flags, and labeled provisional totals.
- Use stable keyed IDs for focus; distinguish local persistence success from
  server acknowledgement. Keep save/finish controls for 12b.
**Verification:** create/load → edit locally → reload → recover every locally
acknowledged edit; add/remove/reorder without focus jumps; local export contains
the current edits; storage failures remain visible.
**Gate G12a:** usable local editor backed by Stage 11 persistence.

#### Stage 12b - Synchronization, reauthentication, and finish
- Connect foreground save/reconnect handling and save/finish controls. Show
  **locally saved / syncing / synced / offline / conflict / finish pending**.
- Preserve the draft through reauthentication. Finish captures the final graph
  and client finish time and remains pending until durable acknowledgement;
  never delete the draft early. Conflicts pause saves pending explicit recovery.
**Verification:** edit→save→finish; offline edit→available-shell reload→reconnect;
response loss after commit; newer edits during in-flight save; session expiry
then reauthentication; finish with unsynced sets and delayed upload.
**Gate G12b:** save/finish and recovery work through the actual editor; no stale
response overwrites input and no unacknowledged finish discards the draft.

#### Stage 12c - Repeat-last and conflict recovery UI
- Repeat-last reads the last finished workout, creates a new empty workout via
  the durable create path, and copies exercises/completed sets with new UUIDs,
  `done=false`, copied reps/weights/side/overrides, and reset RPE. Use current
  bodyweight/catalog defaults; add a blank draft set when none were completed.
  Flag unavailable or now-incompatible catalog settings instead of silently
  producing invalid references/overrides. Persist through normal bulk-save.
- Expose conflict recovery: use-server, local export/copy-to-new, or explicit
  replacement at a fresh revision where lifecycle allows it. Preserve the
  source draft until the selected recovery action has succeeded.
**Verification:** two real tabs conflict and retain recoverable drafts; each
recovery choice works, including failed/cancelled actions and a server-finished
workout; repeat-last creates independent IDs and unfinished sets without changing
historical totals; unavailable/changed catalog entries are handled visibly.
**Gate G12c / G12:** logging, repeat-last, and conflict recovery work end-to-end.
**Covers checks 1, 2, 3, 4, 5, 8, and editor reauthentication from check 11.**

> **Remote deployment checkpoint:** after this stage we can start testing a
> complete core-app deployment on a remote server with QA and invited beta
> testers. Keep access restricted and use a dedicated human-QA/beta database,
> separate from both production and automated E2E data. Stage 15 remains the
> production release gate.

### Stage 13 - History/detail, Settings, export UI
**Purpose:** review + preferences + data recovery. (`PLAN.md` §8)
**Scope:** `features/history`, `features/settings`, export/download.
**Tasks:** History/detail with previous-session comparison (deltas from S8);
Settings (dark/light switch, display name, default bodyweight, UTC offset
picker, JSON export, logout); expose saved-data export and local-draft recovery
as distinct
actions. Logout offers **sync/export/discard** pending changes and clears that
account's local data only after the chosen action succeeds (or explicit discard);
failed/cancelled actions retain drafts. Never upload an old account's draft under
a new user; metric-only labels, no unit selector.
**Verification:** Playwright: view finished workout + comparison; toggle theme →
navigate → reload (persists, legible); change profile/catalog defaults →
existing workout totals unchanged; saved-data and local-draft exports download
valid versioned JSON without secrets; the local export contains newer unsynced
edits; failed sync/export during logout preserves data; switch accounts with a
pending draft → no cross-account upload or delayed-response contamination.
**Gate G13:** full user feature set. **Covers checks 10, 11, 12, 14.**

> **Milestone C exit:** complete client against the live API.

---

## Milestone D - Administration

### Stage 14 - Minimal operational admin panel
**Purpose:** operate accounts safely without impersonation or access to training
data. (`PLAN.md` §4, §6, §8, §11)
**Scope:** numbered admin migration, `app/admin.py` bootstrap CLI,
`app/api/admin.py`, `app/schemas/admin.py`, `app/services/admin.py`, admin route
and components, append-only audit reads/writes.
**Tasks:**
- Add `users.role` (`user|admin`), `users.account_status`
  (`active|disabled`), and `admin_audit_log` through a numbered migration.
  Existing users become active ordinary users. Preserve data/indexes/FKs and
  verify upgrade from the pre-admin schema.
- Add a confirmation-based on-server CLI to grant/revoke admin role. Record CLI
  role changes in the audit log and refuse removal of the last active admin.
  Public registration/profile requests never accept role or status fields.
- Resolve role/status on every authenticated request. Disabled accounts cannot
  log in or continue through an existing session. Admin endpoints require an
  active admin; admin role does not bypass normal workout/catalog ownership.
  Extend `GET /auth/me` with a read-only role for navigation without making role
  or status writable through registration/profile schemas.
- Implement bounded `GET /admin/users` and `GET /admin/audit-log`, plus explicit
  disable, enable, and revoke-sessions actions. Mutations require password
  reauthentication, exact Origin/JSON checks, confirmation, and a bounded
  non-empty reason. Disable + session revocation is one transaction; enable
  never restores sessions. Prevent self-disable and loss of the last active admin.
- Append audit events for successful and rejected authorized admin mutations,
  including actor, target, action, reason, request ID, result, and timestamp.
  Expose no endpoint that updates or deletes audit records.
- Add a role-gated admin screen for user search, status, disable/enable, session
  revocation, and audit history. It has no impersonation, password reset/view,
  workout/content inspection, user export/delete, or default-catalog controls.
**Verification:** migration preserves existing users and defaults them safely;
bootstrap/last-admin guards; non-admin and disabled-session rejection; generic
disabled-login response; atomic disable + revocation; enable requires a fresh
login; self-disable refused; reauthentication/CSRF checks; stable bounded lists;
successful and rejected mutations audited without credentials, tokens, exports,
or workout content. Playwright covers admin login → search → disable/revoke →
blocked target → enable → fresh target login, and verifies ordinary users cannot
open the admin UI or API.
**Gate G14:** minimal administration is authorized, audited, and cannot access
training data or impersonate users. **Covers acceptance check 15.**

> **Milestone D exit:** operators can manage account access without broad data
> privileges or direct database edits.

---

## Milestone E - Hardening

### Stage 15 - Acceptance evidence and production deployment smoke
**Purpose:** prove the 15 acceptance checks and lock them in CI. (`PLAN.md` §10)
**Scope:** acceptance evidence, E2E suite, backend concurrency/migration tests,
production startup/serving configuration, README run/backup/restore/admin docs.
**Tasks:**
- Audit the 15 acceptance checks against tests introduced in their owning stages;
  fill gaps without postponing earlier gates or duplicating every backend test
  as E2E. CI exercises real SQLite concurrency and migration/backup-restore.
- Serve the **built SPA and `/api/v1` under one origin**, using one API process
   and a persistent local-disk database. Configure explicit pre-start migrations
   and production cookie settings. Containers
   remain optional. Document the concrete production startup procedure.
- Add the remote E2E harness: provision a unique disposable SQLite file, run
  migrations, load deterministic fixtures through an on-server command, start
  the production artifact against that file, run tests, stop the process, and
  remove the database and sidecars. Keep human QA/beta on a different database.
  If an HTTP fixture API is demonstrated to be necessary, it must be disabled
  by default, available only in `APP_ENV=qa`, separately authenticated and
  ingress-restricted, and fail closed unless the database is marked disposable.
  Verify production mode has no fixture/reset routes.
- Run a deployment smoke with production build/configuration: load the SPA,
  register/login through the same origin, verify Secure/HttpOnly/SameSite cookie
  behavior over HTTPS, create/save/finish a workout, restart the application,
  and verify the workout remains readable. Against the real production origin,
  use only the public API and one reusable synthetic account; no QA cleanup
  tooling may access the production database. Keep TLS verification enabled.
- Restore a backup to an isolated database and read its graph; verify an upgrade
   from the previous migration preserves data/indexes/FKs. Confirm a non-zero
   user UTC offset groups statistics and displays times as expected.
- Document admin bootstrap, role recovery, account disable/enable, session
  revocation, audit review, and the last-admin safeguards. Keep direct SQL out of
  normal operator procedures.
**Verification:** all automated acceptance checks pass in CI from a fresh clone;
record production smoke results and a mobile/keyboard/light-dark visual check.
Prove an E2E run can be removed by deleting only its disposable database and
that production exposes no fixture/reset routes. Automated assertions supplement
rather than replace a legibility review.
**Gate G15 (ship gate):** all 15 checks have passing evidence, the production
same-origin/restart smoke succeeds, and README documents setup, migrate,
production run, backup/restore, and admin operations. No PWA app-shell cache is
required.

---

## Acceptance-check traceability (PLAN.md §10)

| # | Check | Stages that prove it |
|---|-------|----------------------|
| 1 | Offline edit → reload → reconnect recovers every acked edit | 11a–11c, 12a–12b, 15 |
| 2 | Lost create/save/finish retried: no dup/regen/double-increment/early-delete | 5, 6c, 7, 11b, 12b, 15 |
| 3 | Edit during in-flight save: response can't overwrite newer input | 11b, 12b, 15 |
| 4 | Two tabs: stale saves fail atomically, both drafts recoverable | 6c, 11a, 11c, 12c, 15 |
| 5 | Finish with unsynced sets accepted together | 6c, 12b, 15 |
| 6 | Other user's/nested/catalog ids: no partial write or unauthorized read | 3, 4, 5, 6a–6c, 15 |
| 7 | Reorder/remove/add under unique indexes | 6b, 12a, 15 |
| 8 | Repeat workout: copies don't affect historical totals/PRs | 8, 12c, 15 |
| 9 | Reject fractional/string/bool/out-of-range; floor + negative/unknown cases | 2, 4-8, 9, 15 |
| 10 | Profile/catalog edits don't rewrite recorded totals | 5, 8, 13, 15 |
| 11 | Expire session, switch accounts, retry after delete: preserve/discard safely | 3, 7, 11b–11c, 12b, 13, 15 |
| 12 | CSRF, cookie expiry, logout revocation, no secrets in output/export | 3, 8, 13, 14, 15 |
| 13 | Restore backup + upgrade older schema: data/indexes/FKs valid | 1, 14, 15 |
| 14 | Dark/light persists + legible; metric-only everywhere, no unit selector | 9, 13, 15 |
| 15 | Admin authorization, disable/revoke, safeguards, audit, no training-data access | 14, 15 |

Additional Phase 1 deliverables beyond the numbered checks: versioned local
draft export is proved in 11a/11b and exposed in 12a/13; production same-origin
serving, persistent storage across restart, and UTC-offset handling are proved
in 15. Keep those gates even though they do not have separate acceptance numbers.

## Risk notes (where stages most often slip)

- **S6 reorder-under-unique-indexes** and the save_id receipt: budget the most
  test time here; a direct occupied swap is a known trap (§5).
- **S11 draft/sync protocol:** offline, two-tab, and lost-response ordering are
  subtle; test the coordinator explicitly, not just via UI.
- **S8 offset grouping/streaks + prev-perf pairing:** Monday-start half-open ranges
  and left/right non-pairing are easy to get wrong; cover with fixtures.
- **S14 admin authorization/audit:** disabling accounts and preserving immutable
  evidence must stay atomic without granting access to user training data.
- If any stage's gate is red, **split it** rather than pushing forward.
