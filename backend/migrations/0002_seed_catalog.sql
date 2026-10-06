-- 0002: small default exercise catalog (PLAN.md §4).
--
-- All rows are global defaults (is_default = 1, created_by NULL) with stable
-- slug ids; user-created customs use UUIDs, so ids cannot collide.
--
-- Provenance: muscle-group/equipment classifications are conventional gym
-- practice, not a taxonomy standard. bodyweight_percent values are labeled
-- ESTIMATES, not universal physical constants:
--   * Pull-up / Dip = 100: essentially the whole body is accelerated, so the
--     full bodyweight is a reasonable estimate (ignoring the small fraction
--     held by the hands/forearms on the bar).
--   * Push-up = 65: force-platform measurements of a standard push-up report
--     roughly 64-66% of bodyweight supported at the hands in the up
--     position; 65 is the rounded midpoint estimate.
-- Split-weight entries (curl, lateral raise) default to side_count = 2: one
-- set covers both sides, weight_kg is per dumbbell (PLAN.md §4).

INSERT INTO exercise_catalog (
    id, name, muscle_group, equipment, load_type,
    bodyweight_percent, side_count, is_default
) VALUES
    ('bench-press', 'Bench Press', 'chest', 'barbell', 'single_weight',
     NULL, 1, 1),
    ('overhead-press', 'Overhead Press', 'shoulders', 'barbell', 'single_weight',
     NULL, 1, 1),
    ('barbell-row', 'Barbell Row', 'back', 'barbell', 'single_weight',
     NULL, 1, 1),
    ('deadlift', 'Deadlift', 'back', 'barbell', 'single_weight',
     NULL, 1, 1),
    ('back-squat', 'Back Squat', 'legs', 'barbell', 'single_weight',
     NULL, 1, 1),
    ('lat-pulldown', 'Lat Pulldown', 'back', 'machine', 'single_weight',
     NULL, 1, 1),
    ('leg-press', 'Leg Press', 'legs', 'machine', 'single_weight',
     NULL, 1, 1),
    ('pull-up', 'Pull-up', 'back', 'bodyweight', 'bodyweight',
     100, 1, 1),
    ('push-up', 'Push-up', 'chest', 'bodyweight', 'bodyweight',
     65, 1, 1),
    ('dip', 'Dip', 'arms', 'bodyweight', 'bodyweight',
     100, 1, 1),
    ('dumbbell-curl', 'Dumbbell Curl', 'arms', 'dumbbell', 'split_weight',
     NULL, 2, 1),
    ('dumbbell-lateral-raise', 'Dumbbell Lateral Raise', 'shoulders', 'dumbbell',
     'split_weight', NULL, 2, 1);
