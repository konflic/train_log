# Exercise information screen and progress summary

Status: implemented as Stage 13b on the current working tree. Backend and
frontend automated checks are complete; the pre-existing backend mypy error in
`backend/app/api/auth.py:50` remains outside this scope.

Estimate: 8-12 person-days. Research, review, and two original SVG frames for
each default exercise are expected to dominate the implementation time.

This file is the detailed implementation contract for a read-only exercise
information screen, per-exercise progress summary, compact exercise-card
labels, and a larger free-weight/bodyweight default catalog. `PLAN.md` remains
authoritative for product behavior, and `IMPLEMENTATION.md` remains the roadmap
and status record.

## Purpose

Give users optional exercise guidance and personal progress information without
changing the active-workout flow. A user opens the screen from an information
link on an exercise card, reviews the exercise, and returns without starting,
editing, saving, finishing, or otherwise mutating a workout.

The first chart is deliberately narrow: volume for the latest 12 eligible
training sessions. It does not introduce the general Phase 3 statistics suite.

Confirmed product decisions:

- "Best RPM" means best eligible estimated one-repetition maximum (1RM).
- The chart shows the latest 12 eligible training sessions.
- Statistics include only finished workouts and `done=true` sets.
- Default exercises may have guidance and a two-frame animation.
- Custom exercises never have pictures, but may have an optional description.
- No new frontend or backend dependency is expected.
- Cardio remains outside this stage because the current domain has no cardio
  intervals or `tracking_kind`.

## Scope

- Add a hash route at `#/exercises/:id` and a dedicated exercise-information
  route component.
- Add an accessible information link to active-workout exercise cards.
- Add equivalent detail links to catalog and finished-workout exercise cards
  where they improve navigation without changing card actions.
- Add optional catalog descriptions, default guidance, cited sources, and an
  animation manifest.
- Add owner-scoped per-exercise totals and a latest-12-session volume series.
- Replace verbose compact-card load descriptions with body part and coarse
  tracking type only.
- Add semantic exercise component classes alongside the existing Tailwind
  utilities.
- Expand the default catalog with exercises that fit the existing resistance
  set and load model.
- Create original, locally bundled two-frame SVG artwork for every default
  exercise included in the release.
- Update `PLAN.md`, `IMPLEMENTATION.md`, and this stage's completion evidence in
  the implementation branch when the work is scheduled.

## Screen structure

Render the exercise-information route in this order:

1. Back navigation and exercise name.
2. Compact badges such as `Back · Bodyweight` or `Shoulders · Weighted`.
3. Two-frame movement animation for a default exercise.
4. Brief exercise description.
5. A "How to perform" ordered list.
6. A "Form cues" advice list.
7. Source links and a short evidence disclaimer.
8. User-specific statistics.
9. The latest-12-session volume chart.

Load the catalog detail and user statistics independently or in parallel. A
statistics failure must not hide otherwise available exercise guidance, and a
guidance failure must not imply that the user's history is absent. Each failed
read has its own visible retry state.

### Default exercises

- Display a brief description, technique steps, form cues, source links, and
  the two-frame animation.
- Keep precise load semantics available under a small "How weight is logged"
  explanation rather than placing them on compact cards.
- Describe bodyweight contribution percentages as estimates, never universal
  physical constants.

### Custom exercises

- Never render an animation, image element, or empty media placeholder.
- Display the owner's optional description when present.
- Do not fabricate technique instructions, form cues, animation metadata, or
  scientific sources.
- Display personal statistics and the chart under the same eligibility rules as
  defaults.
- Show a neutral description-empty state when no description was provided.

## Navigation and active-workout isolation

Extend `frontend/src/components/ActionIcon.svelte` with an `info` icon. Add a
44 CSS pixel information link on the right side of each exercise header in
`WorkoutEditor.svelte`, with an accessible label such as `About Pull-up`.

The information link must:

- Be a real link to `#/exercises/{catalog_id}`.
- Be separate from the exercise expand/collapse button and drag target.
- Never toggle, reorder, replace, remove, complete, or synchronize an exercise.
- Preserve locally stored input and synchronization state when navigating away
  and returning with browser Back.
- Avoid introducing a workout start, save, or finish request.
- Work for a direct route visit; a direct visit uses Catalog as its fallback
  back destination.

The normal draft persistence rule still applies: an edit must be durably stored
before the UI reports it as locally saved. The information route does not add a
second draft or navigation-state store.

## Compact exercise summaries

Replace verbose summaries such as:

```text
Shoulders · Split weight (per side) · both sides per set
```

with:

```text
Shoulders · Weighted
```

Use one shared frontend helper with these mappings:

| Domain value | Compact label |
|---|---|
| `load_type=bodyweight` | Bodyweight |
| `load_type=single_weight` | Weighted |
| `load_type=split_weight` | Weighted |
| Future `tracking_kind=cardio` | Cardio |

Apply the helper consistently in:

- `frontend/src/features/workout/ExercisePicker.svelte`.
- `frontend/src/features/catalog/CatalogRoute.svelte`.
- The training-plan picker, which already reuses `ExercisePicker`.
- Any new compact exercise-summary component introduced by this stage.

Do not add `tracking_kind` only to display a future Cardio label. Cardio requires
the separately specified interval model in `PLAN.md` and remains deferred.

## Semantic UI classes

Add stable semantic classes alongside, not instead of, the existing Tailwind
utilities. Keep them limited to touched exercise components:

```text
exercise-card
exercise-card__header
exercise-card__summary
exercise-card__info-link
exercise-detail
exercise-detail__animation
exercise-detail__technique
exercise-detail__advice
exercise-stats
exercise-stats__metric
exercise-volume-chart
exercise-volume-chart__bar
```

These names are styling, test, and future design hooks. Do not use this stage to
rename unrelated application classes or replace the project's Tailwind styling.

## Catalog and guidance data

### Migration

Add a numbered migration that introduces nullable `description` on
`exercise_catalog` and inserts the reviewed new defaults.

Description rules:

- Maximum 1,000 Unicode codepoints.
- Trim surrounding Unicode whitespace.
- Normalize blank input to `null`.
- Custom users may create, edit, or explicitly clear descriptions only on their
  own custom entries.
- Default descriptions are immutable through the public API.
- Existing catalog rows and historical references remain valid.
- Existing custom rows migrate with `description=null`.

Test an upgrade from migration 0006 with representative users, custom entries,
plans, workouts, exercises, and sets. Run `PRAGMA foreign_key_check` after the
upgrade.

### Public schemas

Separate the public catalog representation into these concepts:

| Shape | Contents |
|---|---|
| Exercise summary | Existing compact catalog fields |
| Exercise detail | Summary, description, guidance, sources, animation key |
| Exercise statistics | Owner-specific lifetime totals and latest-12 series |

`GET /exercises` stays a bounded summary list and must not carry all technique
text or sources. `GET /exercises/{id}` returns detail. Custom POST/PATCH requests
accept `description`, and their responses return the resulting detail shape.

Recommended detail guidance shape:

```json
{
  "description": "A vertical pulling exercise...",
  "guidance": {
    "technique_steps": ["...", "..."],
    "form_tips": ["...", "..."],
    "animation_key": "pull-up",
    "sources": [
      {
        "title": "Surface electromyographic activation patterns...",
        "url": "https://pubmed.ncbi.nlm.nih.gov/21068680/"
      }
    ]
  }
}
```

For custom exercises, `guidance` is `null`.

### Guidance registry

Keep default guidance in a version-controlled backend content registry keyed by
the stable default catalog ID. Use explicit typed Python data and response
validation; do not add a content-management framework or a JSON parsing layer
only for this fixed launch content.

The registry contains:

- A bounded list of concise technique steps.
- A bounded list of concise form cues.
- An animation key.
- One or more source titles and HTTPS URLs.

Add a consistency test proving that every registry key is a seeded default,
every default expected to have guidance has one registry entry, URLs use HTTPS,
text obeys bounds, and animation keys have both bundled SVG frames.

## Per-exercise statistics

Add the authenticated endpoint:

```text
GET /api/v1/exercises/{id}/stats
```

Recommended response:

```json
{
  "training_count": 8,
  "completed_set_count": 31,
  "total_volume_kg_reps": 24860,
  "unknown_load_set_count": 0,
  "volume_complete": true,
  "best_estimated_1rm_kg": 112,
  "sessions": [
    {
      "workout_id": "00000000-0000-0000-0000-000000000000",
      "started_at": "2026-09-01T10:00:00Z",
      "completed_set_count": 4,
      "volume_kg_reps": 2880,
      "unknown_load_set_count": 0,
      "volume_complete": true
    }
  ]
}
```

### Eligibility and aggregation

- Scope the catalog lookup and every statistics row to the authenticated owner.
- A foreign custom exercise is indistinguishable from an unknown ID.
- Include only finished workouts and `done=true` sets.
- Aggregate repeated occurrences of the catalog exercise in one workout into
  one chart column.
- Calculate load and volume from the workout's recorded bodyweight, exercise
  load snapshot, and set override.
- Never use current profile or catalog load settings to recalculate history.
- Calculate lifetime totals across all eligible history.
- Select the latest 12 eligible workouts under `(started_at DESC, id DESC)`,
  then emit the chart series oldest-to-newest.
- A workout is eligible for this series when it has at least one completed set
  for the requested catalog ID.
- No eligible history returns zero counts, a known zero total, `null` best 1RM,
  and an empty series.

### Volume completeness

Preserve the existing `PLAN.md` null and completeness semantics at both lifetime
and session levels:

- No eligible sets means a known volume of zero.
- All eligible loads unknown means volume `null`.
- Some known and some unknown loads return the known partial sum with
  `volume_complete=false` and a positive `unknown_load_set_count`.
- The UI labels a partial sum as `At least N kg·reps`; it never presents it as a
  complete total.
- Aggregate values must remain within the shared JSON-safe integer range.

Label `total_volume_kg_reps` as **Lifetime volume** in the UI rather than the
ambiguous phrase "current volume."

### Estimated 1RM

Reuse the existing server calculation and eligibility contract:

- One rep uses external load directly.
- Two through ten reps use `external_load * (30 + reps) // 30`.
- Best estimated 1RM is the maximum eligible value across completed sets in
  finished workouts for this catalog ID.
- Pure bodyweight and weighted-bodyweight exercises return `null`.
- Sets over ten reps and sets with unknown required inputs do not contribute.
- The screen renders `Unavailable for this exercise` rather than fabricating a
  bodyweight 1RM.

## Volume chart

Implement an accessible HTML/CSS column chart without adding a chart package.

- Render at most 12 columns.
- Normalize bar heights against the largest known session volume.
- Display the user's fixed-UTC-offset date and exact `kg·reps` value.
- Link a column to the corresponding finished-workout detail when practical.
- Render an all-unknown session as `Unknown`, not zero.
- Render a partial session with distinct visual treatment and the text
  `At least N kg·reps`.
- Keep exact values available in an accessible list or table; hover is not the
  only way to obtain the value.
- Preserve known zero distinctly from missing data.
- Ensure columns remain legible at phone width and do not require horizontal
  page scrolling.

## Two-frame animation

Create two original SVG frames for each default exercise:

```text
frontend/src/assets/exercises/pull-up-start.svg
frontend/src/assets/exercises/pull-up-finish.svg
```

Animation behavior:

- Hold each frame for one second; the complete loop lasts two seconds.
- Toggle frame opacity with a CSS stepped animation rather than JavaScript
  timers or GIF files.
- Include a visible Pause/Play control because the animation loops indefinitely.
- Pause by default under `prefers-reduced-motion` and keep the control usable.
- Keep both frames on the same view box and anatomical/equipment anchors so the
  figure does not jump between states.
- Use transparent backgrounds and a restrained high-contrast palette that is
  legible in both themes.
- Treat the pictures as supplementary; technique text remains understandable
  without them.
- Do not fetch images from third-party origins at runtime.
- Create original artwork rather than copying or tracing published exercise
  illustrations.

The frontend animation manifest maps an API `animation_key` to its two imports.
A build/unit check fails for a missing frame. Custom exercises have no manifest
entry and omit the media section entirely.

## Evidence and content policy

Describe the guidance as **evidence-informed**, not "scientifically proven."
Exercise science does not independently prove every common coaching cue, and
individual anatomy and training context vary.

Content rules:

- Write concise original summaries; do not copy source instructions.
- Prefer systematic reviews, position stands, peer-reviewed biomechanics, and
  reputable professional guidance.
- Distinguish measured findings from conventional coaching cues.
- Avoid medical, pain-treatment, or injury-prevention guarantees.
- Include source title and full URL on the screen.
- Review an exercise's description, technique, advice, sources, and both frames
  as one content unit.
- Label bodyweight percentages and other approximate load assumptions clearly.

Initial research corpus:

- [ACSM resistance-training position stand](https://pubmed.ncbi.nlm.nih.gov/19204579/)
- [Resistance-training prescription systematic review](https://pmc.ncbi.nlm.nih.gov/articles/PMC10579494/)
- [Squat, bench press, and deadlift mechanics under intensity and fatigue](https://pmc.ncbi.nlm.nih.gov/articles/PMC12521083/)
- [Squatting kinematics and kinetics review](https://pubmed.ncbi.nlm.nih.gov/20182386/)
- [Squat depth and joint-loading review](https://pubmed.ncbi.nlm.nih.gov/23821469/)
- [Pull-up and chin-up activation study](https://pubmed.ncbi.nlm.nih.gov/21068680/)
- [Push-up kinetic systematic review](https://pubmed.ncbi.nlm.nih.gov/30284496/)
- [Squat and deadlift comparison](https://pmc.ncbi.nlm.nih.gov/articles/PMC7386153/)

These references are starting points, not automatic support for every exercise
or cue. Each shipped content unit needs an exercise-relevant source review.

## Default catalog expansion

Keep all existing defaults because stored workouts and plans may reference
them. Do not remove cable or machine entries merely to change the application's
focus. Add a conservative tranche of free-weight and bodyweight exercises whose
measurements fit the existing model:

| Exercise | Muscle group | Existing load representation |
|---|---|---|
| Front Squat | Legs | Single weight |
| Goblet Squat | Legs | Single weight |
| Sumo Deadlift | Legs | Single weight |
| Good Morning | Back | Single weight |
| Incline Bench Press | Chest | Single weight |
| Barbell Curl | Arms | Single weight |
| Lying Triceps Extension | Arms | Single weight |
| Dumbbell Overhead Press | Shoulders | Split weight, two weights |
| Incline Dumbbell Bench Press | Chest | Split weight, two weights |
| One-arm Dumbbell Row | Back | Split weight, one side per set |
| Hammer Curl | Arms | Split weight, two weights |
| Dumbbell Romanian Deadlift | Legs | Split weight, two weights |
| Kettlebell Swing | Full body | Single weight |
| Chin-up | Back | Bodyweight, estimated 100% |
| Bodyweight Squat | Legs | Bodyweight, estimate set after review |
| Close-grip Push-up | Arms | Bodyweight, estimate set after review |

Before inserting an exercise, validate its exact name, muscle-group choice,
load type, side count, and any bodyweight percentage as one catalog decision.
Do not seed a value merely to satisfy a database requirement.

Exclude from this stage:

- Timed holds such as planks because the app records repetitions, not duration.
- Carries because the app records neither distance nor duration.
- Assisted movements because assistance is not represented.
- Variable-leverage movements whose effective bodyweight cannot be represented
  honestly by one catalog percentage.
- Unilateral loaded movements that cannot fit the current side and external-load
  semantics.
- Cardio entries, which require the separately designed interval model.

## Delivery sequence

Implement this work through sequential subgates so content and artwork do not
obscure API and calculation review.

### Subgate A - Contract, migration, and backend reads

- Update `PLAN.md` to admit the read-only information screen, custom
  descriptions, per-exercise summary, and one latest-12 chart.
- Preserve the distinction between this bounded chart and Phase 3's advanced
  statistics suite.
- Add the description migration, catalog schema/service changes, guidance
  registry, detail response, statistics endpoint, and backend tests.
- Add the planned default rows only after their load semantics pass review.

Gate A passes when migration preservation, visibility, description CRUD,
guidance consistency, eligibility, volume completeness, estimated 1RM, ordering,
and integer bounds pass the complete backend suite.

### Subgate B - Read-only screen and navigation

- Add frontend API types and helpers.
- Add `ExerciseDetailRoute.svelte`, independent content/stats states, metric
  cards, the accessible chart, and fixed-offset date labels.
- Add information links, compact labels, and semantic classes.
- Add custom description editing to `ExerciseForm.svelte`.
- Prove navigation does not mutate or lose active-workout state.

Gate B passes when component tests and browser tests cover route states,
compact cards, custom descriptions, chart semantics, active-workout isolation,
mobile layout, and both themes.

### Subgate C - Guidance and artwork

- Research and write each default's content in the application's own words.
- Create and review two original SVG frames for every shipped default.
- Complete the manifest and source coverage checks.
- Review reduced-motion and pause behavior.

Gate C passes only when every shipped default expected to have media has both
frames and reviewed guidance; custom entries render no media; no runtime
third-party content request is required.

### Subgate D - Completion evidence

- Run the full backend and frontend gates.
- Record implementation, test counts, migration evidence, mobile/theme review,
  reduced-motion review, and source/artwork coverage here.
- Update `IMPLEMENTATION.md` with the exact branch, status, acceptance mapping,
  and next-stage marker in the same branch.
- Bump the patch version in `frontend/package.json`, `package-lock.json`, and
  `backend/pyproject.toml` as required by the repository workflow.

## Verification matrix

### Backend

- Migration 0006 -> new version preserves data, indexes, and foreign keys.
- Existing custom entries receive `description=null`.
- Description create, update, explicit clear, length bounds, and Unicode
  normalization match between schema and service.
- Defaults remain immutable and customs remain owner-private.
- Default details return validated guidance; customs return `guidance=null`.
- Registry keys, sources, text bounds, and animation keys are complete.
- Active workouts and incomplete sets do not contribute to statistics.
- Repeated occurrences aggregate into one workout/session point.
- The latest-12 selection and `(started_at, id)` tie-break are deterministic.
- Known, partial, all-unknown, zero, and empty volume cases are distinct.
- Estimated 1RM eligibility and maximum selection reuse existing arithmetic.
- Bodyweight/profile/catalog edits do not rewrite historical results.
- Aggregate overflow fails explicitly rather than emitting an imprecise number.
- Unknown and foreign exercise IDs preserve existing 404 privacy behavior.

### Frontend unit and component tests

- Compact cards render only muscle group and coarse type.
- Information links do not invoke card toggles or picker selection.
- Default detail renders description, guidance, sources, and animation.
- Custom detail renders its optional description and no image markup.
- Content and statistics have independent loading, error, and retry states.
- Pause/Play and reduced-motion behavior are visible and keyboard accessible.
- Empty, complete, partial, unknown, and populated statistics render honestly.
- Estimated 1RM `null` renders as unavailable.
- Chart labels expose fixed-offset dates and exact values without hover.
- Browser Back preserves editor values and synchronization state.
- Required semantic exercise classes are present.

### Playwright

- Add Pull-up to an active workout, enter a local value, open its information
  screen, and return without a workout write or data loss.
- Render default animation, technique, advice, and source links.
- Populate more than 12 finished sessions and display exactly the latest 12 in
  oldest-to-newest chart order.
- Prove a bodyweight exercise has no fabricated estimated 1RM.
- Create a custom exercise with a description and prove no media is rendered.
- Check phone and desktop layouts in light and dark themes.
- Check reduced-motion defaults and the Pause/Play control.
- Confirm normal rendering performs no third-party image/content request.

## Verification commands

Backend and migration checks:

```bash
cd backend
ruff check .
ruff format --check .
mypy app migrate.py
pytest -q
pip check
```

Run `python migrate.py` separately with an isolated database created at migration
0006 before applying the new migration. Never use a development, QA, or
production user database for migration tests.

Frontend checks:

```bash
cd frontend
npm run check
npm run lint
npm run test:unit
npm run build
npm run test:e2e
npm ls
npm audit
```

## Acceptance criteria

1. The information icon opens a dedicated exercise screen and causes no workout
   lifecycle or graph mutation.
2. Navigating back preserves locally acknowledged workout input and sync state.
3. Compact catalog/picker cards display only body part and Bodyweight/Weighted;
   no split-weight percentage or side explanation remains on those cards.
4. Every shipped default displays reviewed description, technique, advice,
   sources, and two locally bundled frames.
5. The animation changes frame once per second, can be paused, and respects
   reduced-motion preferences.
6. A custom exercise can store and display an optional description and never
   renders default pictures or fabricated guidance.
7. Completed-set count, lifetime volume, volume completeness, and best estimated
   1RM follow the existing finished-workout/snapshot/integer contracts.
8. Bodyweight and weighted-bodyweight exercises display estimated 1RM as
   unavailable rather than inventing a value.
9. The chart displays at most the latest 12 eligible workouts, one column per
   workout, with repeated exercise occurrences aggregated.
10. Unknown and partial volume are visibly distinct from complete and zero
    volume.
11. New defaults favor basic free-weight and bodyweight training and each one
    fits the current metric and side model without hidden assumptions.
12. Both themes, phone and desktop widths, keyboard operation, source links,
    chart values, and semantic exercise classes pass review.
13. Migration, backend, frontend, production build, and Playwright gates pass,
    and completion evidence is recorded before merge.

## Non-goals

- Cardio recording, cardio catalog entries, pace, distance, heart-rate, or
  calorie calculations.
- User-uploaded photos, videos, or general media storage.
- Custom exercise animations or custom scientific guidance.
- Timed holds, assisted-load tracking, carries, or arbitrary metrics.
- Full-history interactive chart navigation, arbitrary ranges, comparison
  overlays, PR timelines, or the general Phase 3 statistics dashboard.
- Medical diagnosis, rehabilitation advice, or claims that a cue prevents
  injury.
- A chart, animation, content-management, or media dependency.

## Completion evidence

Not yet implemented. Record the assigned stage/branch, schema and API changes,
default catalog count, guidance and animation coverage, commands and test
counts, migration result, mobile/theme/reduced-motion observations, external
request check, blockers, and acceptance mapping here before merge.
