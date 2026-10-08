# Stage 8a - Inline previous performance

Status: draft; implementation is blocked on the decisions in Open questions.

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

## Proposed response design

The current proposal is an additive `previous_performance` member on each
workout exercise response. It would identify the selected previous workout,
carry the paired previous occurrence and completed-set values, and expose
server-computed comparison values aligned to current sets.

Proposed server-computed values for each compatible pair:

- Previous and current reps, external load, effective load, volume, and
  estimated 1RM where applicable.
- Absolute integer deltas for those values.
- `null` for an unknown, inapplicable, incompatible, or unmatched value.

Percentage changes are proposed as a client display calculation using the
shared BigInt floor helper. If percentages become part of the API, their exact
fields and denominator rules must instead be fixed here and tested on the
server.

This response design is not final until the open questions are resolved.

## Compatibility proposal

Two paired sets have compatible load semantics when all of these match:

- Recorded `load_type`.
- Recorded `side_count`.
- Set side, already guaranteed by side-aware pairing.
- Effective bodyweight percentage, where a set override replaces the recorded
  exercise percentage.

Different recorded bodyweights remain comparable when those settings match;
the resulting effective-load difference is based on historical recorded input.
The proposed behavior still reports a reps delta for a paired set when load
settings are incompatible, while all load-based values remain `null`.

## Estimated 1RM proposal

Use external load only for weighted exercises with no bodyweight contribution:

- One rep: external load.
- Two through ten reps: `external_load * (30 + reps) // 30`.
- More than ten reps: `null`.
- Pure-bodyweight or weighted-bodyweight exercise: `null`.

The public placement of this value remains an open question.

## Query and service plan

Keep base graph reads owner-scoped and consistent on one read transaction.
Target three additional data queries, independent of graph size:

1. Find the selected previous workout for every distinct current catalog ID,
   including previous workout bodyweight. Use the documented order and require
   a completed set for that catalog ID.
2. Fetch all matching previous exercise occurrences with their recorded
   snapshots in workout order.
3. Fetch completed sets for those occurrences in exercise/set order.

Assemble occurrence and side-aware set pairings in Python. Reuse
`app.numbers.calculate_set_load` and add only the small estimated-1RM and delta
helpers that the finalized response actually requires.

The authoritative PUT response currently has the same detail shape as GET.
Preserve that contract: after an accepted save or exact retry, attach previous
performance using the same transaction snapshot used for the response rather
than returning a different schema or racing a second read after commit.

## Implementation work

After the response decisions are resolved:

- Add explicit previous-performance response schemas in
  `app/schemas/workouts.py`.
- Add immutable internal records for selected previous workouts, occurrences,
  paired sets, and calculated comparisons only where they clarify assembly.
- Extend the connection-bound workout graph read without introducing per-set or
  per-exercise queries.
- Keep GET and PUT response conversion in one path.
- Extend language-neutral numeric fixtures only for calculations the frontend
  must independently reproduce; do not duplicate server-only expectations.
- Update OpenAPI-focused response tests and the existing fixed-query-count test.

## Verification

Tests must cover:

- No previous eligible workout returns `null` previous performance.
- Active and finished viewed workouts use only strictly earlier sessions.
- The viewed workout is excluded and equal `started_at` candidates are excluded.
- Candidate ordering uses the workout ID tie-breaker.
- A candidate without completed sets for the catalog ID is skipped.
- Multiple catalog occurrences pair in order, with extra current or previous
  occurrences unmatched.
- Completed sets pair by per-side ordinal and never cross left/right/bilateral.
- Draft sets do not contribute historical performance.
- Snapshot or override incompatibility cannot produce load progression.
- Catalog/profile edits do not alter recorded historical calculations.
- Unknown bodyweight propagates `null` effective load and volume.
- Known zero remains zero rather than unknown.
- Estimated 1RM eligibility and rep boundaries.
- Negative percentage results use floor division if percentages are included.
- Foreign workout data never enters candidate selection.
- Query count remains fixed at the documented bound.
- PUT and subsequent GET return equal detail representations.
- A repeated workout containing copied `done=false` sets does not affect the
  selected historical performance.

## Open questions

1. Does the API return server-computed paired deltas, or raw previous data for
   the SPA to pair and calculate? Proposed default: server-computed previous
   values and absolute deltas; client-computed display percentages.
2. Where is estimated 1RM exposed: only in paired previous performance, on every
   current set, or in statistics too? Proposed default: paired previous
   performance only.
3. Should active-workout responses include the previous occurrence's complete
   completed-set list so "last time" is visible before current sets are done?
   Proposed default: yes.
4. When load settings are incompatible, is a reps-only comparison allowed?
   Proposed default: yes; all load-based comparisons are `null`.
5. Confirm the exact JSON member names and whether pairings are aligned to
   current set IDs or returned as an ordered list.

## Gate G8a

G8a passes when the finalized response contract is additive and explicit,
selection and pairing follow the product rules, historical snapshots prevent
fake progression, GET and PUT detail responses remain consistent, the query
count is bounded, and the complete backend suite is green locally and in CI.

Completion evidence and the Stage 8b marker must be recorded in
`IMPLEMENTATION.md` in the Stage 8a branch before merge.
