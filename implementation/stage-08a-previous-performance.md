# Stage 8a - Inline previous performance

Status: implemented on branch `stage-8a-previous-performance` (PR pending). Gate
G8a passed locally on 2026-10-08; see Completion evidence below.

Working estimate: 1 person-day within Stage 8's 2.5-day post-Stage-6 budget.

This file is the detailed implementation contract for Stage 8a. `PLAN.md`
remains authoritative for product behavior, and `IMPLEMENTATION.md` remains the
roadmap and status record.

## Purpose

Add bounded, owner-scoped previous-performance data to workout detail reads so
the client can display meaningful prior-session comparisons without a separate
per-exercise request.

References:

- `PLAN.md` section 7, Previous performance and Metrics.
- `PLAN.md` section 3 for integer arithmetic and floor division.
- `IMPLEMENTATION.md` Gate G8 and acceptance checks 8-10.

## Fixed product rules

- For a viewed workout, exclude that workout and consider only finished
  workouts with a strictly earlier `started_at`.
- For each catalog ID in the viewed graph, select the most recent candidate
  session ordered by `(started_at, id)` descending that has at least one
  completed set for that catalog ID.
- If the catalog exercise occurs multiple times in that session, return all
  occurrences in workout order.
- Pair current and previous occurrences by occurrence order.
- Within a paired occurrence, pair completed sets by side and ordinal within
  that side. Never pair left with right.
- Unmatched sets have no comparison delta.
- Compare load-based values only when the recorded exercise snapshots and the
  effective per-set bodyweight percentages are compatible. A later catalog edit
  must not fabricate progression.
- Derive values from recorded workout bodyweight and recorded exercise
  snapshots, never current profile or catalog load defaults.
- Use floor division for every division, preserve unknown as `null`, and keep
  every emitted integer in the shared safe range.
- Keep the query count bounded independently of graph size.

The Phase 2 `GET /exercises/{id}/last-performance` endpoint and local prefill
behavior are not part of this stage.

## Response contract

`previous_performance` is an additive, required, nullable member of each workout
exercise response. It is `null` when no eligible previous session occurrence
pairs with that exercise, and it is read-only: the bulk-save schema still
rejects it as unknown input. GET, POST, an accepted PUT, and an exact PUT retry
all carry it, because one graph-read path builds every detail response.

```text
ExerciseNodeResponse.previous_performance: PreviousPerformanceResponse | null

PreviousPerformanceResponse
  workout_id            selected previous session id
  started_at            its recorded start
  bodyweight_kg         its recorded bodyweight (null = unknown)
  exercise_id           the paired previous occurrence id
  order_index           that occurrence's position in the previous workout
  load_type             its recorded snapshot
  bodyweight_percent    its recorded snapshot
  side_count            its recorded snapshot
  sets[]                every completed set of that occurrence, in set order
  pairs[]               only the matched comparisons, in current set order

PreviousSetResponse
  id, set_index, side
  reps, weight_kg, bw_percent_override      recorded inputs
  values: SetValuesResponse                 derived from that session's inputs

PreviousSetPairResponse
  current_set_id, previous_set_id           both echoed, so positions are never
                                            the only alignment information
  load_compatible                           false = recorded load settings differ
  current, previous, delta: SetValuesResponse

SetValuesResponse
  reps, external_load_kg, effective_load_kg, volume_kg_reps, estimated_1rm_kg
```

Every `SetValuesResponse` member is a nullable integer; `null` means unknown,
inapplicable, or incompatible, and `0` remains a known zero. Absolute deltas are
`current - previous` and are `null` when either side is unknown. Percentage
changes stay a client display calculation over the shared BigInt floor helper,
so no percentage member exists in the API.

A previous occurrence's `sets` list is always complete, including for an active
viewed workout whose own sets are still drafts; `pairs` is then empty, so "last
time" is visible before anything is completed.

## Compatibility rules

Two paired sets have compatible load semantics when all of these match:

- Recorded `load_type`.
- Recorded `side_count`.
- Set side, already guaranteed by side-aware pairing.
- Effective bodyweight percentage, where a set override replaces the recorded
  exercise percentage.

Different recorded bodyweights remain comparable when those settings match;
the resulting effective-load difference is based on historical recorded input.
When the settings are incompatible, `load_compatible` is `false`, the pair still
reports a reps delta, and all load-based values are `null` on `current`,
`previous`, and `delta`. The previous occurrence's own `sets` values stay fully
reported, because they are facts about that session rather than a comparison.

## Estimated 1RM rules

External load only, for weighted exercises with no bodyweight contribution:

- One rep: the external load.
- Two through ten reps: `external_load * (30 + reps) // 30`.
- More than ten reps: `null`.
- Pure-bodyweight or weighted-bodyweight exercise: `null`.

It is exposed inside previous performance only - on the previous occurrence's
completed sets and on both sides of a compatible pair - and never on current
sets or in statistics. Stage 8b decides independently whether summary statistics
need it.

## Query and service design

Base graph reads stay owner-scoped and consistent on one read transaction.
Previous performance adds at most three data queries, independent of graph size:

1. `_select_previous_sessions`: one windowed query returning exactly one winner
   per distinct current catalog ID, including the previous workout's recorded
   bodyweight. `ROW_NUMBER() OVER (PARTITION BY catalog_id ORDER BY
   started_at DESC, id DESC)` over the owner-scoped, finished, strictly earlier
   candidates that hold a completed set for that catalog ID keeps the row count
   bounded by the graph rather than by the training history.
2. `_select_previous_occurrences`: all matching previous exercise occurrences
   with their recorded snapshots in `(workout_id, order_index)` order.
3. The same helper's second query: completed sets for those occurrences in
   `set_index` order.

Occurrence and side-aware set pairing happen in Python. `_set_values` reuses
`app.numbers.calculate_set_load`; the only new arithmetic helpers are
`recorded_external_load`, `estimated_one_rep_max`, and `integer_delta`.

The authoritative PUT response has the same detail shape as GET. That contract is
preserved by assembling previous performance inside `_read_workout_graph`, on the
same transaction snapshot used for the response, rather than returning a
different schema or racing a second read after commit. A finished save therefore
reports the history that existed at its own commit, and never selects itself.
The latest save's bounded previous-performance tuple is stored in
`workout_save_previous_performance` with the existing receipt, so an exact retry
replays the acknowledged detail even if a backdated session is finished or old
history is deleted between attempts. Ordinary GET remains a live history view.

## Implementation work

- Added `SetValuesResponse`, `PreviousSetResponse`, `PreviousSetPairResponse`,
  and `PreviousPerformanceResponse` to `app/schemas/workouts.py`, plus the
  additive `ExerciseNodeResponse.previous_performance` member.
- Added immutable internal records `PreviousSession`, `SetValues`,
  `PreviousSet`, `PreviousSetPair`, and `ExercisePreviousPerformance`, and
  extended `WorkoutGraph` with a tuple parallel to `exercises`.
- Extended the connection-bound workout graph read; no per-set or per-exercise
  query was introduced, and `_row_to_set`/`_row_to_exercise` are now shared by
  the base and previous-performance reads.
- Added migration `0003_save_previous_performance_receipt.sql`, which stores at
  most one internal derived-history snapshot per workout and cascades on delete.
  New saves validate all derived arithmetic before mutation; legacy rows whose
  combinations exceed the safe range remain readable with null load metrics.
- GET, POST, and PUT response conversion remain one path; `_detail_response`
  zips the graph with its previous performance using `strict=True`, so any
  misalignment fails loudly instead of dropping a comparison.
- The language-neutral numeric fixtures are unchanged: estimated 1RM and the
  deltas are server-only values, and the client-side percentage rule is already
  covered by the shared `floor_division` examples.
- Updated the OpenAPI-focused response tests and the fixed-query-count test.

## Verification

Tests cover:

- No previous eligible workout returns `null` previous performance.
- Active and finished viewed workouts use only strictly earlier sessions.
- The viewed workout is excluded and equal `started_at` candidates are excluded.
- Candidate ordering uses the workout ID tie-breaker, and the newest
  `started_at` wins over it.
- A candidate without completed sets for the catalog ID is skipped, and
  completed sets for another catalog ID do not select a session.
- Each catalog ID selects its own previous session.
- Multiple catalog occurrences pair in order, with extra current or previous
  occurrences unmatched.
- Completed sets pair by per-side ordinal and never cross left/right/bilateral.
- Draft sets neither contribute historical performance nor consume ordinals.
- Snapshot or override incompatibility cannot produce load progression, while a
  reps delta survives; compatible settings compare across different recorded
  bodyweights.
- Catalog and profile edits do not alter recorded historical calculations, and
  each session's own recorded bodyweight drives its values.
- Unknown bodyweight propagates `null` effective load and volume; known zero
  remains zero.
- Estimated 1RM eligibility and rep boundaries, in `app.numbers` and end to end.
- Foreign workout data never enters candidate selection and never leaks an id.
- Query count stays at the documented bound (3 with an empty graph, 4 with no
  eligible session, 6 regardless of graph size).
- PUT, the finishing save, and the subsequent GET return equal detail
  representations; an exact PUT retry remains equal after eligible history
  changes between attempts.
- Unsafe derived arithmetic is rejected atomically, while pre-Stage-8 persisted
  rows with unsafe combinations remain readable without emitting unsafe values.
- A repeated workout containing copied `done=false` sets does not affect the
  selected historical performance, while a finished repeat with completed sets
  becomes the next history.
- `previous_performance` submitted as save input is rejected.

Percentage changes are not part of the API, so no server percentage test exists;
the shared floor-division fixtures already fix the client rule.

Run the complete backend gate:

```bash
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app migrate.py
.venv/bin/pytest -q
.venv/bin/pip check
```

## Non-goals

- `GET /exercises/{id}/last-performance`, batch reads, and local prefill
  (Phase 2).
- Percentage deltas, PRs, streaks, calendar grouping, and any summary statistic
  (Stage 8b).
- Export of previous performance (Stage 8c).
- Any client-side rendering of comparisons (Stages 12-13).

## Resolved decisions

The five open questions were resolved on 2026-10-08 by adopting every proposed
default:

1. The server returns previous values and absolute integer deltas; the client
   computes display percentages with the shared BigInt floor helper.
2. Estimated 1RM is exposed only inside paired previous performance, never on
   current sets and not in statistics.
3. Active-workout responses include the previous occurrence's complete
   completed-set list, so "last time" is visible before any current set is done.
4. Incompatible load settings still allow a reps-only comparison; every
   load-based comparison value is `null` and `load_compatible` says why.
5. Member names are fixed in Response contract above. Pairings are an ordered
   list in current set order, each entry echoing `current_set_id` and
   `previous_set_id`, so alignment never depends on array positions alone.

## Gate G8a

G8a passes when the finalized response contract is additive and explicit,
selection and pairing follow the product rules, historical snapshots prevent
fake progression, GET and PUT detail responses remain consistent, the query
count is bounded, and the complete backend suite is green locally and in CI.

Completion evidence and the Stage 8b marker must be recorded in
`IMPLEMENTATION.md` in the Stage 8a branch before merge.

## Completion evidence

Recorded on branch `stage-8a-previous-performance` on 2026-10-08. Gate G8a
passed locally; CI re-runs the complete suite on the PR.

- `backend`: `ruff check .`, `ruff format --check .`, `mypy app migrate.py`,
  `pytest -q` (592 tests, +82), and `pip check` all green, and the isolated
  migration + backup/verify check still passes. No dependency or request body
  changed: migration `0003_save_previous_performance_receipt.sql` adds one
  internal, cascading latest-receipt table; the only new public surface is the
  additive nullable `previous_performance` member of the workout detail exercise
  shape plus its four OpenAPI components. All Stage 5-7
  read/save/finish/retry/delete checks still pass. Existing coverage now also
  checks the additive detail member, the documented query bound (3 graph queries
  plus at most 3 previous-performance queries), migration upgrade, and receipt
  cascade on delete.
- `app/numbers.py`: `recorded_external_load` separates the external-load
  resolution (zero for pure bodyweight, unknown for a weighted set without a
  recorded weight) and is now the single source used by `effective_load`;
  `estimated_one_rep_max` implements the documented rep boundaries with floor
  division; `integer_delta` subtracts while preserving unknown; `SetLoad` and
  `calculate_set_load` now report all four derived values for one set.
- `app/services/workouts.py`: `_read_previous_performance` runs inside the
  existing graph read, so GET, POST, and an accepted PUT return one
  snapshot-consistent detail; the latest receipt replays that derived tuple on
  an exact retry. `_select_previous_sessions` is one
  windowed owner-scoped query bounded by the number of distinct catalog IDs;
  `_select_previous_occurrences` adds the occurrence and completed-set queries.
  `_pair_sets` matches completed sets by side and per-side ordinal and never
  crosses sides; `_exercise_previous_performance` derives every value from the
  recorded bodyweights and immutable snapshots, and `_without_load_values`
  reduces an incompatible pair to reps only. Save validation rejects unsafe
  derived arithmetic before mutation, while legacy unsafe combinations degrade
  load metrics to null instead of breaking detail reads.
- `app/schemas/workouts.py`: `SetValuesResponse`, `PreviousSetResponse`,
  `PreviousSetPairResponse`, and `PreviousPerformanceResponse`, all
  `extra="forbid"`, with `ExerciseNodeResponse.previous_performance` as a
  required nullable member. The save schemas are untouched, so submitting the
  new member remains a 422.
- `app/api/workouts.py`: one conversion path shared by GET, POST, and PUT;
  `_detail_response` zips the graph with its previous performance using
  `strict=True`.
- Tests added (+82): `tests/test_workout_previous_performance_service.py` (41
  direct service cases) covers candidate eligibility and ordering, per-catalog
  selection, occurrence and side-aware set pairing, draft exclusion, all four
  incompatibility kinds, historical stability against profile/catalog edits,
  unknown-versus-zero propagation, 1RM boundaries, repeat-last history, owner
  isolation, safe-range legacy fallback, and the query bound at 1, 6, and 12
  exercises.
  `tests/test_workout_previous_performance_api.py` (13 API cases) covers the
  exact response shape, active-view "last time", GET/PUT/retry/finish equality,
  cross-user isolation without id leaks, recorded-bodyweight handling, the
  public repeat-last flow, retry stability across intervening history,
  safe-range rejection, read-only enforcement, and the OpenAPI description.
  `tests/test_numbers.py` (+27 cases) covers `recorded_external_load`,
  `estimated_one_rep_max`, `integer_delta`, unsafe operands, and the extended
  `calculate_set_load`; one save-validation regression covers cross-field
  derived overflow, and migration coverage includes the bounded receipt table.
- **Covers the server half of acceptance checks 8, 9, and 10**: copied
  `done=false` repeat sets and unfinished drafts earn no history, every
  reported value is an exact floored integer with unknown preserved, and
  profile/catalog edits never rewrite a recorded calculation. The client halves
  land in Stages 12-13.
