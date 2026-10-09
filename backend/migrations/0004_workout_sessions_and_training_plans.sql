-- 0004: explicit workout sessions and reusable training plans.
--
-- Existing workouts predate explicit session types and remain NULL. New API
-- starts always set a type. The partial unique index applies to every explicit
-- session; the service also treats an unfinished legacy workout as active, so
-- an account must reconcile legacy duplicates before starting new work.

CREATE TABLE training_plans (
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (name <> ''),
    notes TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE INDEX idx_training_plans_user_name
    ON training_plans (user_id, name, id);

CREATE TABLE training_plan_exercises (
    id TEXT NOT NULL PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
    catalog_id TEXT NOT NULL REFERENCES exercise_catalog(id) ON DELETE RESTRICT,
    order_index INTEGER NOT NULL CHECK (order_index >= 0),
    notes TEXT,
    UNIQUE (plan_id, order_index)
) STRICT;

CREATE INDEX idx_training_plan_exercises_catalog
    ON training_plan_exercises (catalog_id, plan_id);

CREATE TABLE training_plan_sets (
    id TEXT NOT NULL PRIMARY KEY,
    plan_exercise_id TEXT NOT NULL
        REFERENCES training_plan_exercises(id) ON DELETE CASCADE,
    set_index INTEGER NOT NULL CHECK (set_index >= 0),
    target_reps INTEGER CHECK (target_reps IS NULL OR target_reps >= 0),
    target_weight_kg INTEGER
        CHECK (target_weight_kg IS NULL OR target_weight_kg >= 0),
    side TEXT NOT NULL CHECK (side IN ('left', 'right', 'bilateral')),
    bw_percent_override INTEGER
        CHECK (bw_percent_override IS NULL
               OR bw_percent_override BETWEEN 1 AND 100),
    UNIQUE (plan_exercise_id, set_index)
) STRICT;

ALTER TABLE workouts ADD COLUMN session_type TEXT
    CHECK (session_type IS NULL OR session_type IN ('freestyle', 'from_plan'));
ALTER TABLE workouts ADD COLUMN source_plan_id TEXT
    REFERENCES training_plans(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX uidx_workouts_one_explicit_active
    ON workouts (user_id)
    WHERE ended_at IS NULL AND session_type IS NOT NULL;
