-- Preserve the derived part of the latest authoritative PUT response so an
-- exact save retry can replay it even if eligible history changes meanwhile.
-- At most one bounded snapshot exists per workout; deleting the workout removes
-- it, and receipts created before this migration simply have no snapshot row.
CREATE TABLE workout_save_previous_performance (
    workout_id TEXT NOT NULL PRIMARY KEY
        REFERENCES workouts(id) ON DELETE CASCADE,
    snapshot TEXT NOT NULL
) STRICT;
