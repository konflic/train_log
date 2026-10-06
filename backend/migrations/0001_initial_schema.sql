-- 0001: initial schema (PLAN.md §5).
--
-- Conventions: TEXT UUID primary keys; canonical UTC timestamps
-- (YYYY-MM-DDTHH:MM:SSZ, enforced with a GLOB CHECK); INTEGER for every
-- measurement; 0/1 INTEGER booleans; all tables STRICT so SQLite rejects
-- values that cannot be stored losslessly in the declared column type.
--
-- Migration files must not contain transaction control (BEGIN/COMMIT) or
-- PRAGMA statements; the runner wraps each file in its own transaction and
-- every connection enables foreign keys itself.

CREATE TABLE users (
    id TEXT NOT NULL PRIMARY KEY,
    -- Normalized (trimmed, lowercased) by the application before storage.
    email TEXT NOT NULL UNIQUE CHECK (email <> ''),
    password_hash TEXT NOT NULL CHECK (password_hash <> ''),
    display_name TEXT,
    bodyweight_default_kg INTEGER
        CHECK (bodyweight_default_kg IS NULL OR bodyweight_default_kg > 0),
    -- Fixed UTC offset chosen in Settings, in whole minutes; 0 = UTC.
    -- Bounds cover every real-world offset (-12:00 .. +14:00). No DST.
    utc_offset_minutes INTEGER NOT NULL DEFAULT 0
        CHECK (utc_offset_minutes >= -720 AND utc_offset_minutes <= 840),
    created_at TEXT NOT NULL
        CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    updated_at TEXT NOT NULL
        CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
) STRICT;

CREATE TABLE sessions (
    -- SHA-256 hex digest of an opaque random token; the raw token is never
    -- stored or logged.
    token_hash TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
        CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    expires_at TEXT NOT NULL
        CHECK (expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK (expires_at > created_at)
) STRICT;

CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

CREATE TABLE exercise_catalog (
    -- Global defaults use stable slug ids; user customs use UUIDs, so the
    -- scopes cannot collide.
    id TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL CHECK (name <> ''),
    muscle_group TEXT NOT NULL
        CHECK (muscle_group IN ('chest', 'back', 'legs', 'shoulders', 'arms',
                                'core', 'full_body', 'other')),
    equipment TEXT NOT NULL
        CHECK (equipment IN ('barbell', 'dumbbell', 'kettlebell', 'machine',
                             'cable', 'bodyweight', 'band', 'other')),
    load_type TEXT NOT NULL
        CHECK (load_type IN ('single_weight', 'split_weight', 'bodyweight')),
    -- Bodyweight contribution percentage; required for pure-bodyweight
    -- exercises, optional otherwise. Labeled estimates, not constants.
    bodyweight_percent INTEGER
        CHECK (bodyweight_percent IS NULL
               OR (bodyweight_percent >= 1 AND bodyweight_percent <= 100)),
    side_count INTEGER NOT NULL CHECK (side_count IN (1, 2)),
    is_default INTEGER NOT NULL CHECK (is_default IN (0, 1)),
    created_by TEXT REFERENCES users(id) ON DELETE CASCADE,
    CHECK (load_type <> 'bodyweight' OR bodyweight_percent IS NOT NULL),
    CHECK (load_type = 'split_weight' OR side_count = 1),
    -- Defaults have no owner; custom entries require one.
    CHECK ((is_default = 1 AND created_by IS NULL)
           OR (is_default = 0 AND created_by IS NOT NULL))
) STRICT;

-- Names are unique within the default scope and within each owner's custom
-- scope; a custom name may match a default name (PLAN.md §4).
CREATE UNIQUE INDEX uidx_exercise_catalog_default_name
    ON exercise_catalog (name) WHERE is_default = 1;
CREATE UNIQUE INDEX uidx_exercise_catalog_owner_name
    ON exercise_catalog (created_by, name) WHERE is_default = 0;

CREATE TABLE workouts (
    -- Client-generated UUID.
    id TEXT NOT NULL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    started_at TEXT NOT NULL
        CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    -- NULL means active; a finished workout is read-only except delete and
    -- exact finish retry (PLAN.md §6).
    ended_at TEXT
        CHECK (ended_at IS NULL
               OR ended_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    notes TEXT,
    -- Recorded input copied from the profile at creation (or explicitly
    -- corrected via bulk-save); never a live profile lookup.
    bodyweight_kg INTEGER
        CHECK (bodyweight_kg IS NULL OR bodyweight_kg > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    -- Immutable fingerprint of the validated create request; identifies
    -- retried creates (PLAN.md §6).
    create_request_hash TEXT NOT NULL CHECK (create_request_hash <> ''),
    -- Receipt of the last accepted save: both columns NULL or both set.
    last_save_id TEXT,
    last_save_hash TEXT,
    created_at TEXT NOT NULL
        CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    updated_at TEXT NOT NULL
        CHECK (updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK ((last_save_id IS NULL) = (last_save_hash IS NULL))
) STRICT;

CREATE INDEX idx_workouts_user_started ON workouts (user_id, started_at, id);

CREATE TABLE exercises (
    -- Client-generated UUID.
    id TEXT NOT NULL PRIMARY KEY,
    workout_id TEXT NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    -- RESTRICT: catalog entries referenced by history cannot be deleted.
    catalog_id TEXT NOT NULL REFERENCES exercise_catalog(id) ON DELETE RESTRICT,
    order_index INTEGER NOT NULL CHECK (order_index >= 0),
    notes TEXT,
    -- Snapshot of the catalog load settings copied when the instance is
    -- first persisted; catalog edits never rewrite recorded history.
    load_type TEXT NOT NULL
        CHECK (load_type IN ('single_weight', 'split_weight', 'bodyweight')),
    bodyweight_percent INTEGER
        CHECK (bodyweight_percent IS NULL
               OR (bodyweight_percent >= 1 AND bodyweight_percent <= 100)),
    side_count INTEGER NOT NULL CHECK (side_count IN (1, 2)),
    CHECK (load_type <> 'bodyweight' OR bodyweight_percent IS NOT NULL),
    CHECK (load_type = 'split_weight' OR side_count = 1),
    UNIQUE (workout_id, order_index)
) STRICT;

CREATE INDEX idx_exercises_catalog_workout ON exercises (catalog_id, workout_id);

CREATE TABLE sets (
    -- Client-generated UUID.
    id TEXT NOT NULL PRIMARY KEY,
    exercise_id TEXT NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    set_index INTEGER NOT NULL CHECK (set_index >= 0),
    -- Draft sets may omit reps/weight; a completed set requires positive
    -- reps. weight_kg must be NULL for bodyweight-load exercises; that
    -- cross-table rule is enforced by the write services (PLAN.md §4).
    reps INTEGER CHECK (reps IS NULL OR reps >= 0),
    weight_kg INTEGER CHECK (weight_kg IS NULL OR weight_kg >= 0),
    bw_percent_override INTEGER
        CHECK (bw_percent_override IS NULL
               OR (bw_percent_override >= 1 AND bw_percent_override <= 100)),
    rpe INTEGER CHECK (rpe IS NULL OR (rpe >= 1 AND rpe <= 10)),
    side TEXT NOT NULL CHECK (side IN ('left', 'right', 'bilateral')),
    done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1)),
    CHECK (done = 0 OR (reps IS NOT NULL AND reps > 0)),
    UNIQUE (exercise_id, set_index)
) STRICT;
