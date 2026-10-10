-- 0007: exercise descriptions and the free-weight/bodyweight catalog expansion.
--
-- Add a nullable `description` column to `exercise_catalog`:
--   * at most 1,000 Unicode codepoints (SQLite `length()` on TEXT counts
--     codepoints), never an empty string; blank input is normalized to NULL
--     by the application layer,
--   * custom entries may create, edit, or explicitly clear their own
--     description; default descriptions are seeded here and immutable
--     through the public API,
--   * existing custom rows migrate with `description = NULL`, and existing
--     catalog rows and historical references remain valid.
--
-- Seed reviewed descriptions for every pre-existing default, then extend the
-- default catalog with a conservative tranche of free-weight and bodyweight
-- exercises whose measurements fit the existing resistance set-and-load
-- model (no timed holds, carries, assisted movements, or cardio).
--
-- bodyweight_percent values remain labeled ESTIMATES (see 0002/0006), not
-- physical constants:
--   * Chin-up = 100: like the pull-up, essentially the whole body is
--     accelerated, so the full bodyweight is a reasonable estimate.
--   * Bodyweight Squat = 70: the shanks and feet (roughly 12-15% of body
--     mass) never rise, and the thighs move only partially, so the moved
--     mass is somewhat above the head-arms-trunk share (~68%); 70 is the
--     rounded conventional estimate.
--   * Close-grip Push-up = 65: hand placement changes the muscle emphasis,
--     not the supported fraction, so the force-platform estimate of the
--     standard push-up (0002) is reused.
-- Split-weight entries with side_count = 2 cover both sides per set with the
-- weight recorded per dumbbell; One-arm Dumbbell Row uses side_count = 1
-- (one side per set) because each arm works independently against one
-- dumbbell.

ALTER TABLE exercise_catalog ADD COLUMN description TEXT
    CHECK (description IS NULL
           OR (length(description) > 0 AND length(description) <= 1000));

UPDATE exercise_catalog SET description = 'A barbell press performed lying on a flat bench, training the chest, shoulders, and triceps. The recorded weight is the total external load on the bar.' WHERE id = 'bench-press';
UPDATE exercise_catalog SET description = 'A standing barbell press from the shoulders to overhead, training the shoulders and triceps. The recorded weight is the total external load on the bar.' WHERE id = 'overhead-press';
UPDATE exercise_catalog SET description = 'A bent-over pull that brings the barbell toward the torso, training the upper and middle back and the elbow flexors. The recorded weight is the total external load on the bar.' WHERE id = 'barbell-row';
UPDATE exercise_catalog SET description = 'A hip-hinge lift of the barbell from the floor to standing, training nearly the whole posterior chain, the legs, and the grip. The recorded weight is the total external load on the bar.' WHERE id = 'deadlift';
UPDATE exercise_catalog SET description = 'A squat with the barbell carried on the upper back, training the thighs, glutes, and trunk support. The recorded weight is the total external load on the bar.' WHERE id = 'back-squat';
UPDATE exercise_catalog SET description = 'A seated machine pull that draws the bar down toward the chest, training the back and elbow flexors. The recorded weight is the machine stack or bar load.' WHERE id = 'lat-pulldown';
UPDATE exercise_catalog SET description = 'A supported machine press that pushes the loaded platform away with the legs, training the thighs and glutes. The recorded weight is the machine load.' WHERE id = 'leg-press';
UPDATE exercise_catalog SET description = 'A bodyweight pull that lifts the body until the chin clears the bar, using an overhand grip and training the back and elbow flexors. The bodyweight contribution is an estimate.' WHERE id = 'pull-up';
UPDATE exercise_catalog SET description = 'A bodyweight press that supports the body on the hands and toes, training the chest, shoulders, and triceps. The recorded bodyweight percentage is a force-platform estimate of the load carried by the hands, not a physical constant.' WHERE id = 'push-up';
UPDATE exercise_catalog SET description = 'A bodyweight movement that supports the body on parallel bars and lowers by bending the elbows, training the triceps and chest. The bodyweight contribution is an estimate.' WHERE id = 'dip';
UPDATE exercise_catalog SET description = 'An elbow-flexion exercise with a dumbbell in each hand, training the biceps. The recorded weight is per dumbbell and one set covers both sides.' WHERE id = 'dumbbell-curl';
UPDATE exercise_catalog SET description = 'A raise of the dumbbells out to the sides until roughly shoulder height, training the lateral shoulder muscles. The recorded weight is per dumbbell and one set covers both sides.' WHERE id = 'dumbbell-lateral-raise';
UPDATE exercise_catalog SET description = 'A short-range trunk curl from lying, training the abdominal muscles. The recorded bodyweight percentage is an estimate of the lifted torso mass.' WHERE id = 'crunch';
UPDATE exercise_catalog SET description = 'A full-range rise from lying to seated, training the hip flexors and abdominal muscles. The recorded bodyweight percentage is an estimate of the lifted torso mass.' WHERE id = 'sit-up';
UPDATE exercise_catalog SET description = 'A leg raise performed hanging from a bar, training the lower abdominals and hip flexors. The recorded bodyweight percentage is an estimate of the lifted leg mass.' WHERE id = 'hanging-leg-raise';
UPDATE exercise_catalog SET description = 'A leg raise performed lying on the back, training the lower abdominals and hip flexors. The recorded bodyweight percentage is an estimate of the lifted leg mass.' WHERE id = 'lying-leg-raise';
UPDATE exercise_catalog SET description = 'A seated trunk rotation, training the oblique abdominal muscles. The recorded bodyweight percentage is a rough convention-based estimate.' WHERE id = 'russian-twist';
UPDATE exercise_catalog SET description = 'A rollout from the knees against a wheel that challenges the whole front core to resist spine extension. The recorded bodyweight percentage is a rough convention-based estimate.' WHERE id = 'ab-wheel-rollout';
UPDATE exercise_catalog SET description = 'A trunk extension from a flexed position, training the spinal erectors and glutes. The recorded bodyweight percentage is an estimate of the moved torso mass.' WHERE id = 'back-extension';
UPDATE exercise_catalog SET description = 'A bench press with a dumbbell in each hand, allowing a larger range of motion and independent sides. The recorded weight is per dumbbell and one set covers both sides.' WHERE id = 'dumbbell-bench-press';
UPDATE exercise_catalog SET description = 'A hip hinge that lowers the bar along the front of the legs with the knees slightly bent, training the hamstrings, glutes, and lower back. The recorded weight is the total external load on the bar.' WHERE id = 'romanian-deadlift';
UPDATE exercise_catalog SET description = 'A split-stance step-down that trains the thighs and glutes on one leg at a time while both feet stay planted per rep. The recorded weight is the total external load.' WHERE id = 'lunge';
UPDATE exercise_catalog SET description = 'A rise onto the toes against a load, training the calf muscles. The recorded weight is the total external load.' WHERE id = 'calf-raise';
UPDATE exercise_catalog SET description = 'A hip extension with the upper back supported on a bench and the load driven through the hips, training the glutes. The recorded weight is the total external load.' WHERE id = 'hip-thrust';
UPDATE exercise_catalog SET description = 'A cable pushdown that extends the elbows against the attachment, training the triceps. The recorded weight is the cable stack load.' WHERE id = 'triceps-pushdown';
UPDATE exercise_catalog SET description = 'A cable pull toward the face with the elbows high, training the rear shoulders and upper back. The recorded weight is the cable stack load.' WHERE id = 'face-pull';

INSERT INTO exercise_catalog (
    id, name, muscle_group, load_type,
    bodyweight_percent, side_count, is_default, description
) VALUES
    ('front-squat', 'Front Squat', 'legs', 'single_weight', NULL, 1, 1, 'A squat with the barbell carried on the front delts, keeping the torso more upright than a back squat and emphasizing the quadriceps. The recorded weight is the total external load on the bar.'),
    ('goblet-squat', 'Goblet Squat', 'legs', 'single_weight', NULL, 1, 1, 'A squat holding one dumbbell or kettlebell in front of the chest, common for learning squat technique. The recorded weight is the total external load.'),
    ('sumo-deadlift', 'Sumo Deadlift', 'legs', 'single_weight', NULL, 1, 1, 'A deadlift with a wide stance and the hands inside the knees, shortening the vertical travel and emphasizing the thighs. The recorded weight is the total external load on the bar.'),
    ('good-morning', 'Good Morning', 'back', 'single_weight', NULL, 1, 1, 'A hip hinge with the barbell carried on the upper back, lowering the trunk toward horizontal over nearly straight legs and training the lower back and hamstrings. The recorded weight is the total external load on the bar.'),
    ('incline-bench-press', 'Incline Bench Press', 'chest', 'single_weight', NULL, 1, 1, 'A barbell bench press on an inclined bench, emphasizing the upper chest and front shoulders. The recorded weight is the total external load on the bar.'),
    ('barbell-curl', 'Barbell Curl', 'arms', 'single_weight', NULL, 1, 1, 'A standing elbow-flexion exercise with a barbell, training the biceps. The recorded weight is the total external load on the bar.'),
    ('lying-triceps-extension', 'Lying Triceps Extension', 'arms', 'single_weight', NULL, 1, 1, 'A lying elbow-flexion and extension of a weight toward the forehead, often called a skull crusher, training the triceps. The recorded weight is the total external load.'),
    ('dumbbell-overhead-press', 'Dumbbell Overhead Press', 'shoulders', 'split_weight', NULL, 2, 1, 'A seated or standing press with a dumbbell in each hand, training the shoulders and triceps. The recorded weight is per dumbbell and one set covers both sides.'),
    ('incline-dumbbell-bench-press', 'Incline Dumbbell Bench Press', 'chest', 'split_weight', NULL, 2, 1, 'A dumbbell bench press on an inclined bench, emphasizing the upper chest. The recorded weight is per dumbbell and one set covers both sides.'),
    ('one-arm-dumbbell-row', 'One-arm Dumbbell Row', 'back', 'split_weight', NULL, 1, 1, 'A single-arm pull with the trunk supported on a bench, training the middle back and elbow flexors. One set covers one side.'),
    ('hammer-curl', 'Hammer Curl', 'arms', 'split_weight', NULL, 2, 1, 'An elbow-flexion exercise with the dumbbells held in a neutral grip, training the biceps, brachialis, and forearms. The recorded weight is per dumbbell and one set covers both sides.'),
    ('dumbbell-romanian-deadlift', 'Dumbbell Romanian Deadlift', 'legs', 'split_weight', NULL, 2, 1, 'A Romanian deadlift with two dumbbells, training the hamstrings and glutes through a hip hinge. The recorded weight is per dumbbell and one set covers both sides.'),
    ('kettlebell-swing', 'Kettlebell Swing', 'full_body', 'single_weight', NULL, 1, 1, 'A ballistic hip hinge that swings one kettlebell to roughly chest height, conditioning the posterior chain. The recorded weight is the single external load.'),
    ('chin-up', 'Chin-up', 'back', 'bodyweight', 100, 1, 1, 'A bodyweight pull with an underhand grip that lifts the body until the chin clears the bar, emphasizing the elbow flexors and back. The bodyweight contribution is an estimate.'),
    ('bodyweight-squat', 'Bodyweight Squat', 'legs', 'bodyweight', 70, 1, 1, 'A squat using bodyweight only, training the thighs and glutes. The recorded bodyweight percentage is an estimate: the lower legs stay planted, so not all body mass travels the full range.'),
    ('close-grip-push-up', 'Close-grip Push-up', 'arms', 'bodyweight', 65, 1, 1, 'A push-up with the hands close together, emphasizing the triceps. The recorded bodyweight percentage is the force-platform estimate used for the standard push-up.');
