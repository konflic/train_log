-- 0006: simplify the exercise catalog.
--
-- Drop the `equipment` column: it never influenced load math (that is owned by
-- `load_type`), and the product only needs the bodyweight/weighted load
-- distinction. SQLite removes a dropped column's CHECK constraint with it.
--
-- Rename the `core` muscle group to `abs`. The group list lives in a column
-- CHECK, so the column is rebuilt in place: rename the old column (its CHECK
-- follows it), add a new column carrying the new list, copy every value
-- through the core->abs mapping, then drop the old column. A whole-table
-- rebuild is avoided because it would require disabling foreign keys, which
-- the migration runner deliberately does not offer.
--
-- Extend the default catalog with abs entries and commonly missing staples.
-- bodyweight_percent values remain labeled ESTIMATES (see 0002), not physical
-- constants: crunch/sit-up move roughly half the torso, leg raises lift the
-- legs only, the twist and rollout figures are rough convention.

ALTER TABLE exercise_catalog DROP COLUMN equipment;

ALTER TABLE exercise_catalog RENAME COLUMN muscle_group TO muscle_group_old;
ALTER TABLE exercise_catalog ADD COLUMN muscle_group TEXT NOT NULL DEFAULT 'other'
    CHECK (muscle_group IN ('chest', 'back', 'legs', 'shoulders', 'arms',
                            'abs', 'full_body', 'other'));
UPDATE exercise_catalog
   SET muscle_group = CASE muscle_group_old
                          WHEN 'core' THEN 'abs'
                          ELSE muscle_group_old
                      END;
ALTER TABLE exercise_catalog DROP COLUMN muscle_group_old;

INSERT INTO exercise_catalog (
    id, name, muscle_group, load_type,
    bodyweight_percent, side_count, is_default
) VALUES
    ('crunch', 'Crunch', 'abs', 'bodyweight', 50, 1, 1),
    ('sit-up', 'Sit-up', 'abs', 'bodyweight', 50, 1, 1),
    ('hanging-leg-raise', 'Hanging Leg Raise', 'abs', 'bodyweight', 30, 1, 1),
    ('lying-leg-raise', 'Lying Leg Raise', 'abs', 'bodyweight', 30, 1, 1),
    ('russian-twist', 'Russian Twist', 'abs', 'bodyweight', 20, 1, 1),
    ('ab-wheel-rollout', 'Ab Wheel Rollout', 'abs', 'bodyweight', 40, 1, 1),
    ('back-extension', 'Back Extension', 'back', 'bodyweight', 50, 1, 1),
    ('dumbbell-bench-press', 'Dumbbell Bench Press', 'chest', 'split_weight',
     NULL, 2, 1),
    ('romanian-deadlift', 'Romanian Deadlift', 'legs', 'single_weight',
     NULL, 1, 1),
    ('lunge', 'Lunge', 'legs', 'single_weight', NULL, 1, 1),
    ('calf-raise', 'Calf Raise', 'legs', 'single_weight', NULL, 1, 1),
    ('hip-thrust', 'Hip Thrust', 'legs', 'single_weight', NULL, 1, 1),
    ('triceps-pushdown', 'Triceps Pushdown', 'arms', 'single_weight',
     NULL, 1, 1),
    ('face-pull', 'Face Pull', 'shoulders', 'single_weight', NULL, 1, 1);
