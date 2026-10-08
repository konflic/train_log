# Stage 8b - Statistics summary

Status: merged to `master` in
[PR #14](https://github.com/konflic/train_log/pull/14) on 2026-10-08 (`bf5033c`).
Gate G8b passed locally on 2026-10-08; see Completion evidence below.

Working estimate: 1 person-day within Stage 8's 2.5-day post-Stage-6 budget.

This file is the detailed implementation contract for Stage 8b. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Provide the bounded Phase 1 statistics summary needed by Home while preserving
eligibility, missing-data, fixed-offset calendar, and integer-only rules.

References:

- `PLAN.md` section 7, Statistics and Previous Performance.
- `PLAN.md` section 3, Integer-Only Numeric Contract.
- `IMPLEMENTATION.md` Gate G8 and acceptance checks 8-10.

## Fixed product rules

- Statistics include only finished workouts and `done=true` sets.
- Training frequency counts finished workouts with at least one completed set.
- Muscle-group frequency requires a completed set for that group.
- Sum known set volumes while reporting `unknown_load_set_count` and a
  completeness flag.
- If all eligible loads are unknown, total volume is `null`.
- If no sets are eligible, total volume is a known zero.
- Derive load and volume from recorded workout bodyweight, exercise snapshots,
  and set overrides. Current profile and catalog load defaults do not rewrite
  history.
- Apply the caller's current fixed UTC offset to `started_at` before calendar
  grouping. Weeks start on Monday and ranges are half-open.
- Weekly streaks count consecutive weeks with an eligible workout while
  allowing the current week to remain in progress.
- Every average or percentage included in the final contract uses floor
  division and returns `null` when its denominator is zero or unavailable.
- All values must remain within the shared JSON-safe integer range.

Dedicated chart, PR, progression, and bodyweight-stat endpoints remain Phase 3.

## Public contract

Endpoint:

`GET /api/v1/stats/summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

The date bounds are optional inclusive local calendar dates, use the same
validation and supported range as workout history, filter by `started_at`, and
default to all history. As in workout history, `date_from > date_to` is a valid
empty range rather than a 422 error.

Response fields:

- `workout_count`: eligible finished workouts in the selected range.
- `completed_set_count`: eligible sets in the selected range.
- `training_day_count`: distinct local calendar days containing an eligible
  workout.
- `total_volume_kg_reps`: known volume total, zero, or `null` according to the
  fixed missing-data rules.
- `unknown_load_set_count`: eligible sets whose volume is unknown.
- `volume_complete`: true exactly when no eligible set has unknown volume.
- `muscle_group_frequency`: all eight muscle groups as a stable ordered list of
  objects with `muscle_group` and `workout_count`. The order is `chest`, `back`,
  `legs`, `shoulders`, `arms`, `core`, `full_body`, `other`; groups without an
  eligible workout remain present with a zero count.
- `current_week_streak`: current consecutive eligible-week count over full
  history.

No range or UTC-offset echo, average, duration, estimated-1RM, longest-streak,
per-group volume, or per-day/per-week series is included. Home requests a
weekly summary by sending both local dates for the current Monday-through-Sunday
week; dedicated chart and richer metric endpoints remain Phase 3.

## Eligibility and aggregation design

Add `app/services/stats.py` with one owner-scoped read transaction and two data
queries, independent of workout, exercise, or set count:

- Fetch the selected range's completed sets from finished owned workouts,
  joined to the workout's recorded bodyweight/start time, the exercise's
  recorded load snapshot, and the catalog's current muscle group. Distinct
  workout IDs in these rows define the eligible selected workouts.
- Fetch the `started_at` values of all finished owned workouts that have at
  least one completed set, without applying the date filter, for the full-history
  streak.

Aggregate in Python rather than duplicating load arithmetic in SQL:

- Resolve each set's effective bodyweight percentage from override or snapshot.
- Reuse `app.numbers.calculate_set_load` for effective load and volume.
- Count each eligible workout once in total frequency.
- Count an eligible workout once per muscle group that has at least one
  completed set, regardless of how many sets or exercise occurrences it has.
- Emit every muscle group even when its deduplicated workout count is zero.
- Convert the workout start instant to a local date by adding the caller's fixed
  UTC offset.
- Derive the Monday date for local-week identity.
- Sample the current instant once per request for streak calculation; keep the
  clock injectable or patchable for deterministic boundary tests.

A completed set whose derived load is unavailable still establishes workout,
day, group, and streak eligibility. Pre-Stage-8 rows whose individually valid
inputs produce an unsafe derived value follow Stage 8a's compatibility behavior:
count the set, but treat its volume as unknown. A known zero volume remains
known. Sum known volumes with exact Python integers and validate the final sum
against the shared JSON-safe range. If the aggregate itself exceeds that range,
fail with an explicit 500 problem response (`stats_range_exceeded`); do not emit
an imprecise number or overload `null`, which is reserved for an all-unknown
eligible selection.

The existing `exercise_catalog` row supplies muscle group because workout
exercise snapshots do not store it. Referenced catalog rows are protected from
deletion, but an owner edit to a custom entry can reclassify historical
frequency; this follows the current schema and should be documented in the
final response contract rather than hidden.

## Streak contract

An eligible week contains at least one finished workout with at least one
completed set. For the current streak:

- Start from the current local week if it is eligible.
- Otherwise start from the immediately previous week because the current week
  may still be in progress.
- Walk backward through consecutive eligible Monday-start weeks.
- Return zero if neither the current nor previous week is eligible.

Date filters never alter this field. An empty selected range may therefore have
zero selected counts and a nonzero full-history streak. Only a user with no
eligible full-history workouts has an empty-history streak of zero.

## API work

- Add strict explicit schemas in `app/schemas/stats.py`.
- Add `app/api/stats.py` with an authenticated GET route.
- Register the stats router under `/api/v1`.
- Extract the history date query parser and bounds into one small shared API
  helper used by workouts and stats; do not introduce a generic query framework.
- Return explicit response models and the canonical muscle-group order above.
- Reuse `app.services.workouts.local_date_bounds` for the inclusive local-date
  query conversion rather than implementing another boundary calculator.

## Verification

Tests must cover:

- Active workouts and draft sets never contribute.
- A finished workout with no completed sets is ineligible.
- Mixed known and unknown volumes return the known sum, a positive unknown
  count, and an incomplete flag.
- All eligible loads unknown returns `null` volume.
- No eligible sets returns zero volume, zero unknown count, and complete=true.
- Known zero load contributes known zero volume.
- Recorded bodyweight and snapshots survive profile/catalog load-setting edits.
- Date ranges are inclusive local dates but use half-open UTC boundaries.
- A reversed date range returns empty selected metrics while leaving the
  full-history streak unchanged.
- Positive and negative offset day-boundary cases, including supported extreme
  offsets.
- Monday/Sunday week boundaries.
- Empty history, current-week activity, previous-week-only activity, and a gap
  breaking a streak.
- Multiple workouts or groups on one day/week are counted according to the
  finalized frequency definitions.
- Muscle group counts deduplicate workouts within a group.
- All eight groups are present in canonical order, including zero-count groups.
- Other users' workouts never contribute.
- Legacy unsafe derived set values count as unknown volume without losing
  eligibility, and an unsafe aggregate fails explicitly without emitting an
  unsafe JSON integer.
- Bounded query count and one consistent read snapshot during a concurrent WAL
  commit.
- Authentication and explicit response/error schemas through the public API.

## Resolved decisions

The contract questions were resolved on 2026-10-08 by keeping the Phase 1
summary small and making every missing-data and calendar behavior explicit:

1. `date_from` and `date_to` are optional inclusive local dates with an
   all-history default and the existing workout-history validation behavior.
2. The response fields are exactly the eight names in Public contract above.
3. Muscle-group frequency counts eligible workouts, not sets or training days,
   and deduplicates each workout within a group.
4. The response emits all eight groups in canonical enum order, including zero
   counts. Phase 1 does not include per-group volume.
5. `current_week_streak` always uses eligible full history, independent of the
   selected range, and follows the ongoing-current-week rule in Streak contract.
6. Longest streak, averages, percentages, durations, estimated 1RM, and
   per-day/per-week arrays are not part of this endpoint.
7. Historical muscle-group frequency follows the catalog entry's current group
   because workout exercise snapshots do not store muscle group. Referenced
   catalog rows cannot be deleted, but editing a custom entry can reclassify
   historical frequency; the API contract documents this limitation.
8. Unknown or legacy-unsafe per-set volume does not remove eligibility.
   Aggregate overflow is an explicit server error rather than an unsafe number
   or a fabricated missing-data state.
9. A reversed date range mirrors workout history and returns empty selected
   metrics. It does not force the full-history streak to zero.
10. The response does not echo query dates or the current UTC offset. Clients
    already know the requested dates, and all grouping consistently uses the
    authenticated user's current fixed offset.

## Gate G8b

G8b passes when the finalized summary contract follows all eligibility and
missing-data rules, fixed-offset grouping and streak boundaries are correct,
owner scoping and snapshot-based load calculations are tested, and the full
backend suite is green locally and in CI.

Completion evidence, the Gate G8 milestone exit, and the Stage 9 marker must be
recorded in `IMPLEMENTATION.md` in the Stage 8b branch before merge.

## Completion evidence

Recorded on branch `stage-8b-stats-summary` on 2026-10-08. Gate G8b passed
locally; CI re-runs the complete suite on the PR.

- `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
  `pytest -q` (637 tests, +45), and `pip check` all green, and the isolated
  `DATABASE_PATH` migration check (fresh apply plus idempotent re-run) still
  passes. No dependency, migration, or request-body change: the only new
  public surface is `GET /api/v1/stats/summary` plus the
  `StatsSummaryResponse` and `MuscleGroupFrequencyResponse` OpenAPI
  components.
- `app/api/common.py`: the history-date query parser and its 1900..9998
  bounds were extracted unchanged from `app/api/workouts.py` into one shared
  `HistoryDate` annotation used by both workouts and stats; the existing
  history date-filter and rejection tests still pass against it.
- `app/services/stats.py`: one owner-scoped `BEGIN` read transaction with
  exactly two data queries - the selected range's completed sets joined to
  their recorded workout bodyweight, exercise snapshots, and the catalog's
  current muscle group, plus the unfiltered eligible `started_at` values for
  the full-history streak. Aggregation reuses `calculate_set_load` per set
  (override before snapshot percentage), degrades pre-Stage-8 unsafe derived
  values to unknown volume without losing eligibility, range-checks the exact
  aggregate, and derives Monday-start local weeks from the caller's fixed
  offset with an injectable `now` sampled once per request. Instants within
  one extreme offset of the datetime bounds clamp to the representable
  calendar edge instead of failing the read.
- `app/schemas/stats.py`: strict `extra="forbid"` response models;
  `muscle_group_frequency` is pinned to all eight groups in the canonical
  `MuscleGroup` literal order, including zero counts; every count is a
  safe-range nonnegative integer and the total is nullable.
- `app/api/stats.py`: authenticated GET mapped onto the service; an aggregate
  `NumericRangeError` becomes an explicit 500 problem+json with code
  `stats_range_exceeded` instead of an imprecise number or a fabricated
  missing-data null.
- Tests added (+45): `tests/test_stats_service.py` (28 direct service cases)
  covers eligibility (active, draft-only, and graphless workouts excluded),
  the complete missing-data matrix (known/mixed/all-unknown/known-zero),
  override-versus-snapshot percentages, stability across profile and catalog
  load-setting edits, catalog reclassification of muscle-group frequency,
  per-group workout deduplication, inclusive local-date ranges with half-open
  UTC bounds at the supported extreme offsets, reversed ranges,
  datetime-extreme clamping, every streak rule (current week, ongoing
  previous week, gaps, Monday/Sunday boundaries, the offset applied to
  workouts and `now` alike, naive-clock rejection), owner isolation, legacy
  unsafe-set degradation, unsafe-aggregate rejection, the two-query bound,
  and snapshot consistency during a concurrent WAL commit.
  `tests/test_stats_api.py` (17 API cases) covers authentication, the exact
  response shape and OpenAPI contract, a full public create/save/finish flow,
  active-workout exclusion, unknown-volume reporting, date filtering and
  offset grouping through `PATCH /auth/me`, shared-parser rejections,
  reversed ranges, a recent-workout streak, cross-user isolation, and the
  `stats_range_exceeded` problem response.
- Manual observation: a live `uvicorn` smoke on an isolated database ran
  register, login, create, finish, and `GET /stats/summary` (all-history,
  single-day, and reversed ranges) with the documented values; the
  unauthenticated request returned a 401 problem+json.
- **Extends the server half of acceptance checks 8, 9, and 10** to
  statistics: drafts and repeat copies without completed sets earn no
  statistics, every reported value is an exact integer with unknown preserved
  as `null`, and profile/catalog edits never rewrite recorded volume. The
  client halves land in Stages 10 and 13.
