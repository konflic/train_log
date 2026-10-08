# Stage 8b - Statistics summary

Status: draft; implementation is blocked on the response decisions in Open
questions.

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

## Proposed public contract

Proposed endpoint:

`GET /api/v1/stats/summary?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

The date bounds are optional inclusive local calendar dates, use the same
validation and supported range as workout history, and default to all history.

Proposed response fields:

- `workout_count`: eligible finished workouts in the selected range.
- `completed_set_count`: eligible sets in the selected range.
- `training_day_count`: distinct local calendar days containing an eligible
  workout.
- `total_volume_kg_reps`: known volume total, zero, or `null` according to the
  fixed missing-data rules.
- `unknown_load_set_count`: eligible sets whose volume is unknown.
- `volume_complete`: true exactly when no eligible set has unknown volume.
- `muscle_group_frequency`: stable list or explicit object of muscle groups and
  eligible workout counts per group.
- `current_week_streak`: current consecutive eligible-week count over full
  history.

The exact response shape is not final until the open questions are resolved.

## Eligibility and aggregation design

Add `app/services/stats.py` with one owner-scoped read transaction. Prefer a
small fixed number of queries that fetch:

- Eligible finished workouts and their recorded bodyweight/start time.
- Their completed sets joined to exercise snapshots and catalog muscle groups.

Aggregate in Python rather than duplicating load arithmetic in SQL:

- Resolve each set's effective bodyweight percentage from override or snapshot.
- Reuse `app.numbers.calculate_set_load` for effective load and volume.
- Count each eligible workout once in total frequency.
- Count an eligible workout once per muscle group that has at least one
  completed set, regardless of how many sets or exercise occurrences it has.
- Convert the workout start instant to a local date by adding the caller's fixed
  UTC offset.
- Derive the Monday date for local-week identity.
- Sample the current instant once per request for streak calculation; keep the
  clock injectable or patchable for deterministic boundary tests.

The existing `exercise_catalog` row supplies muscle group because workout
exercise snapshots do not store it. Referenced catalog rows are protected from
deletion, but an owner edit to a custom entry can reclassify historical
frequency; this follows the current schema and should be documented in the
final response contract rather than hidden.

## Streak proposal

An eligible week contains at least one finished workout with at least one
completed set. For the current streak:

- Start from the current local week if it is eligible.
- Otherwise start from the immediately previous week because the current week
  may still be in progress.
- Walk backward through consecutive eligible Monday-start weeks.
- Return zero if neither the current nor previous week is eligible.

This interpretation requires confirmation in Open questions.

## API work

- Add strict explicit schemas in `app/schemas/stats.py`.
- Add `app/api/stats.py` with an authenticated GET route.
- Register the stats router under `/api/v1`.
- Reuse the history date parser or extract only the small shared parser if doing
  so removes duplication without creating a generic query framework.
- Return explicit response models and stable ordering for muscle groups.

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
- Positive and negative offset day-boundary cases, including supported extreme
  offsets.
- Monday/Sunday week boundaries.
- Empty history, current-week activity, previous-week-only activity, and a gap
  breaking a streak.
- Multiple workouts or groups on one day/week are counted according to the
  finalized frequency definitions.
- Muscle group counts deduplicate workouts within a group.
- Other users' workouts never contribute.
- Every included average/percentage floors negative and positive values and
  handles zero denominators, if such fields are approved.
- Bounded query count and one consistent read snapshot during a concurrent WAL
  commit.
- Authentication and explicit response/error schemas through the public API.

## Open questions

1. Confirm optional `date_from`/`date_to` local-date filters and all-history
   defaults.
2. Confirm the proposed response fields and names.
3. Is muscle-group frequency a count of eligible workouts per group, as
   proposed, or a count of training days or completed sets?
4. Should Phase 1 also return volume per muscle group, or frequency only?
5. Is `current_week_streak` always calculated over full history even when a
   date range filters the other summary values? Proposed default: yes.
6. Is the proposed ongoing-current-week streak rule correct?
7. Is longest weekly streak required in Phase 1? Proposed default: no.
8. Are any averages required, such as floored volume per eligible workout or
   training day? Proposed default: no.
9. Should the endpoint return per-day or per-week arrays? Proposed default: no;
   those belong to Phase 3 chart endpoints.
10. Is historical muscle-group frequency allowed to follow the current catalog
    classification, given the schema does not snapshot muscle group? Proposed
    default: yes for Phase 1.

## Gate G8b

G8b passes when the finalized summary contract follows all eligibility and
missing-data rules, fixed-offset grouping and streak boundaries are correct,
owner scoping and snapshot-based load calculations are tested, and the full
backend suite is green locally and in CI.

Completion evidence and the Stage 8c marker must be recorded in
`IMPLEMENTATION.md` in the Stage 8b branch before merge.
