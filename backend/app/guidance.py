"""Reviewed default-exercise guidance content (exercise information screen).

A version-controlled registry keyed by the stable default catalog id. The
content is evidence-informed coaching guidance written in the application's
own words, not copied source instructions; it never makes medical,
pain-treatment, or injury-prevention guarantees. Source links point at the
reviewed research corpus (systematic reviews, position stands, and
peer-reviewed biomechanics) and are displayed on the exercise-information
screen next to a short disclaimer.

The registry is plain typed data with no parsing or content-management layer:
response schemas re-validate every entry's bounds (step/tip counts, text
lengths, HTTPS URLs, animation-key format) at serialization, and a consistency
test proves that every seeded default has an entry and that every animation
key has both bundled SVG frames. Custom exercises never receive guidance;
their detail responses carry `guidance = null`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuidanceSource:
    """One cited source: a descriptive title and its full HTTPS URL."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class ExerciseGuidance:
    """The reviewed guidance bundle for one default exercise."""

    technique_steps: tuple[str, ...]
    form_tips: tuple[str, ...]
    animation_key: str
    sources: tuple[GuidanceSource, ...]


# Reviewed research corpus. Titles are descriptive labels for the cited
# references.
ACSM_STAND = GuidanceSource(
    title="ACSM resistance-training position stand",
    url="https://pubmed.ncbi.nlm.nih.gov/19204579/",
)
PRESCRIPTION_REVIEW = GuidanceSource(
    title="Resistance-training prescription systematic review",
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC10579494/",
)
LIFT_MECHANICS = GuidanceSource(
    title="Squat, bench press, and deadlift mechanics under intensity and fatigue",
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC12521083/",
)
SQUAT_KINEMATICS = GuidanceSource(
    title="Squatting kinematics and kinetics review",
    url="https://pubmed.ncbi.nlm.nih.gov/20182386/",
)
SQUAT_DEPTH = GuidanceSource(
    title="Squat depth and joint-loading review",
    url="https://pubmed.ncbi.nlm.nih.gov/23821469/",
)
PULL_ACTIVATION = GuidanceSource(
    title="Pull-up and chin-up muscle activation study",
    url="https://pubmed.ncbi.nlm.nih.gov/21068680/",
)
PUSHUP_REVIEW = GuidanceSource(
    title="Push-up kinetic systematic review",
    url="https://pubmed.ncbi.nlm.nih.gov/30284496/",
)
SQUAT_DEADLIFT_COMPARISON = GuidanceSource(
    title="Squat and deadlift strength comparison review",
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7386153/",
)

DEFAULT_GUIDANCE: Mapping[str, ExerciseGuidance] = {
    "bench-press": ExerciseGuidance(
        technique_steps=(
            "Lie on a flat bench with your eyes roughly under the bar",
            "Grip the bar slightly wider than shoulder width, brace, and unrack it",
            "Lower the bar under control until it touches your mid-chest",
            "Press the bar up until your elbows are nearly locked",
            "Rerack the bar once the rep is complete",
        ),
        form_tips=(
            "Keep your feet planted and a slight natural arch in your lower back",
            "Tuck your elbows roughly 45 to 75 degrees from your torso",
            "Keep your wrists straight with the bar over your forearms",
        ),
        animation_key="bench-press",
        sources=(LIFT_MECHANICS, ACSM_STAND),
    ),
    "overhead-press": ExerciseGuidance(
        technique_steps=(
            "Stand with your feet about hip-width apart holding the bar at shoulder height",
            "Brace your torso and squeeze your glutes",
            "Press the bar in a vertical path, moving your head slightly back out of the way",
            "Finish with the bar locked out over your mid-foot",
            "Lower the bar under control back to your shoulders",
        ),
        form_tips=(
            "Avoid leaning far back; the torso stays nearly upright",
            "Push your head through at the top rather than pressing the bar forward",
        ),
        animation_key="overhead-press",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "barbell-row": ExerciseGuidance(
        technique_steps=(
            "Hinge forward until your torso is roughly parallel to the floor",
            "Hold the bar with an overhand grip just outside your knees",
            "Pull the bar to your lower ribcage, leading with your elbows",
            "Squeeze your shoulder blades together at the top",
            "Lower the bar under control to full elbow extension",
        ),
        form_tips=(
            "Keep your back flat and the torso angle steady; do not stand up with the bar",
            "Use a controlled tempo rather than bouncing the bar off the floor",
        ),
        animation_key="barbell-row",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "deadlift": ExerciseGuidance(
        technique_steps=(
            "Stand with your mid-foot under the bar",
            "Bend down and grip the bar just outside your legs",
            "Set a flat back with your chest up and the bar close to your shins",
            "Drive through the floor, extending hips and knees together",
            "Stand tall at the top, then lower the bar back along the same path",
        ),
        form_tips=(
            "Keep the bar in contact with your legs throughout the lift",
            "Brace your torso before each rep rather than relaxing at the top",
        ),
        animation_key="deadlift",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "back-squat": ExerciseGuidance(
        technique_steps=(
            "Position the bar on your upper back and unrack with both hands on the bar",
            "Step back and set your feet roughly shoulder-width apart with toes slightly out",
            "Brace your torso, then sit down and back by bending hips and knees together",
            "Descend at least until the hip crease passes the top of the knee",
            "Drive up through the whole foot, extending hips and knees together",
        ),
        form_tips=(
            "Keep your heels planted and your knees tracking over your toes",
            "Maintain a rigid braced torso throughout the rep",
        ),
        animation_key="back-squat",
        sources=(SQUAT_KINEMATICS, SQUAT_DEPTH),
    ),
    "lat-pulldown": ExerciseGuidance(
        technique_steps=(
            "Sit with your thighs secured under the pads",
            "Grip the bar wider than shoulder width",
            "Pull the bar down toward your upper chest, leading with your elbows",
            "Pause briefly, then return the bar under control to full arm extension",
        ),
        form_tips=(
            "Keep your chest up and lean back only slightly",
            "Avoid swinging your torso to move the weight",
        ),
        animation_key="lat-pulldown",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "leg-press": ExerciseGuidance(
        technique_steps=(
            "Sit with your back and hips pressed into the pad",
            "Place your feet shoulder-width apart in the middle of the platform",
            "Release the safety and bend your knees to lower the platform under control",
            "Push through your whole feet to extend your hips and knees",
            "Finish just short of locking your knees out",
        ),
        form_tips=(
            "Do not let your lower back round off the pad at the bottom",
            "Choose a range of motion you can control without bouncing",
        ),
        animation_key="leg-press",
        sources=(ACSM_STAND, SQUAT_KINEMATICS),
    ),
    "pull-up": ExerciseGuidance(
        technique_steps=(
            "Grip the bar with an overhand grip slightly wider than shoulder width",
            "Hang with your arms extended and your shoulders active",
            "Pull your chest toward the bar, leading with your elbows",
            "Continue until your chin clears the bar",
            "Lower under control to full arm extension",
        ),
        form_tips=(
            "Avoid kipping; start each rep from a controlled hang",
            "Keep your ribs down rather than arching hard to clear the bar",
        ),
        animation_key="pull-up",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "push-up": ExerciseGuidance(
        technique_steps=(
            "Set your hands slightly wider than shoulder width with your body straight",
            "Brace your torso and squeeze your glutes",
            "Lower until your chest is close to the floor",
            "Push back up to full elbow extension, keeping one straight line",
        ),
        form_tips=(
            "Keep your elbows roughly 45 degrees from your torso",
            "Do not let your hips sag or pike during the rep",
        ),
        animation_key="push-up",
        sources=(PUSHUP_REVIEW, ACSM_STAND),
    ),
    "dip": ExerciseGuidance(
        technique_steps=(
            "Support yourself on parallel bars with your arms locked out",
            "Lean slightly forward and bend your elbows to lower",
            "Descend until your upper arms are roughly parallel to the floor",
            "Press back up to full elbow extension",
        ),
        form_tips=(
            "Keep the movement controlled; avoid swinging",
            "Stop at a depth you can hold without shoulder discomfort",
        ),
        animation_key="dip",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "dumbbell-curl": ExerciseGuidance(
        technique_steps=(
            "Stand with a dumbbell in each hand, palms facing forward",
            "Keep your elbows close to your sides",
            "Curl the weights up by bending your elbows",
            "Lower under control to nearly full extension",
        ),
        form_tips=(
            "Avoid swinging your torso; reduce the weight if you must",
            "Rotate your palms fully up and pause briefly at the top",
        ),
        animation_key="dumbbell-curl",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "dumbbell-lateral-raise": ExerciseGuidance(
        technique_steps=(
            "Stand with a dumbbell in each hand at your sides",
            "Keep a slight bend in your elbows",
            "Raise the dumbbells out to the sides until your upper arms are roughly horizontal",
            "Lower under control",
        ),
        form_tips=(
            "Lead with your elbows rather than your hands",
            "Use a weight you can lift without swinging your torso",
        ),
        animation_key="dumbbell-lateral-raise",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "crunch": ExerciseGuidance(
        technique_steps=(
            "Lie on your back with your knees bent and feet flat",
            "Place your hands behind your head or across your chest",
            "Curl your shoulder blades off the floor by flexing your trunk",
            "Lower back down under control",
        ),
        form_tips=(
            "Do not pull on your head or neck",
            "Exhale as you curl up and keep the range of motion short",
        ),
        animation_key="crunch",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "sit-up": ExerciseGuidance(
        technique_steps=(
            "Lie on your back with your knees bent and your feet anchored or flat",
            "Cross your arms over your chest or place your hands behind your head",
            "Rise to a seated position by flexing your trunk and hips",
            "Lower back to the floor under control",
        ),
        form_tips=(
            "Avoid pulling on your neck with your hands",
            "Keep the descent slow rather than dropping",
        ),
        animation_key="sit-up",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "hanging-leg-raise": ExerciseGuidance(
        technique_steps=(
            "Hang from a bar with your arms extended and your shoulders active",
            "Keeping your legs straight or slightly bent, raise them forward and up",
            "Continue until your pelvis tilts up",
            "Lower under control without swinging",
        ),
        form_tips=(
            "Start each rep from a still hang",
            "Curl your pelvis rather than only lifting your legs",
        ),
        animation_key="hanging-leg-raise",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "lying-leg-raise": ExerciseGuidance(
        technique_steps=(
            "Lie on your back with your legs extended",
            "Place your hands under your hips or flat at your sides",
            "Raise your legs until they point near vertical",
            "Lower slowly, stopping before your lower back arches off the floor",
        ),
        form_tips=(
            "Keep your lower back in contact with the floor",
            "Bend your knees slightly to shorten the lever if needed",
        ),
        animation_key="lying-leg-raise",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "russian-twist": ExerciseGuidance(
        technique_steps=(
            "Sit with your knees bent and your heels lightly touching the floor",
            "Lean back until your torso is braced and stable",
            "Clasp your hands or hold a weight at your chest",
            "Rotate your torso to one side, then to the other",
        ),
        form_tips=(
            "Rotate from your torso, not just your arms",
            "Keep your chest up and avoid rounding your lower back",
        ),
        animation_key="russian-twist",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "ab-wheel-rollout": ExerciseGuidance(
        technique_steps=(
            "Kneel with your hands on the wheel handles under your shoulders",
            "Brace so your back stays nearly flat",
            "Roll the wheel forward, extending your body as far as you can control",
            "Pull yourself back to the start by bending at your hips and shoulders",
        ),
        form_tips=(
            "Stop the rollout before your lower back sags",
            "Keep your arms straight and your ribs down throughout",
        ),
        animation_key="ab-wheel-rollout",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "back-extension": ExerciseGuidance(
        technique_steps=(
            "Fix your hips on the bench or machine pads with your feet secured",
            "Cross your arms or place your hands behind your head",
            "Lower your torso by bending at your hips",
            "Extend back up until your body forms a straight line",
        ),
        form_tips=(
            "Avoid extending past the straight line",
            "Move slowly; do not swing up",
        ),
        animation_key="back-extension",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "dumbbell-bench-press": ExerciseGuidance(
        technique_steps=(
            "Lie on a flat bench with a dumbbell in each hand at chest level",
            "Press the dumbbells up until your arms are extended",
            "Lower under control until your elbows pass the line of your torso",
            "Press back up, bringing the dumbbells close together at the top",
        ),
        form_tips=(
            "Keep your wrists straight over your elbows",
            "Control the descent; do not let the dumbbells drift wide",
        ),
        animation_key="dumbbell-bench-press",
        sources=(LIFT_MECHANICS, ACSM_STAND),
    ),
    "romanian-deadlift": ExerciseGuidance(
        technique_steps=(
            "Stand holding the bar at hip height with your knees slightly bent",
            "Push your hips back while lowering the bar along your thighs",
            "Keep your back flat and the bar close to your legs",
            "Descend until you feel a strong hamstring stretch, roughly mid-shin",
            "Drive your hips forward to return to standing",
        ),
        form_tips=(
            "Your knees keep a fixed slight bend; this is a hinge, not a squat",
            "Keep your neck neutral with your chest pointing at the floor as you lower",
        ),
        animation_key="romanian-deadlift",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "lunge": ExerciseGuidance(
        technique_steps=(
            "Stand tall holding the load at your sides or on your back",
            "Step one foot forward",
            "Lower until your back knee is just above the floor",
            "Push through your front foot to return to standing",
            "Repeat, alternating legs or completing one side before the other",
        ),
        form_tips=(
            "Keep your front shin roughly vertical and your torso upright",
            "Take a stride long enough that your front knee tracks over your mid-foot",
        ),
        animation_key="lunge",
        sources=(ACSM_STAND, SQUAT_KINEMATICS),
    ),
    "calf-raise": ExerciseGuidance(
        technique_steps=(
            "Place the balls of your feet on a raised edge or machine pad",
            "Let your heels drop into a stretch",
            "Rise onto your toes as high as you can",
            "Lower under control through the full range",
        ),
        form_tips=(
            "Pause briefly at the top and in the stretch",
            "Keep your knees steady; do not bounce",
        ),
        animation_key="calf-raise",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "hip-thrust": ExerciseGuidance(
        technique_steps=(
            "Sit on the floor with your upper back against a bench and the load over your hips",
            "Place your feet so your shins are vertical at the top",
            "Push through your heels and extend your hips to lift the load",
            "Pause with your body in a straight line from shoulders to knees",
            "Lower under control",
        ),
        form_tips=(
            "Keep your chin tucked and your ribs down at the top",
            "Finish with your glutes rather than arching your lower back",
        ),
        animation_key="hip-thrust",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "triceps-pushdown": ExerciseGuidance(
        technique_steps=(
            "Stand facing a cable machine and grip the attachment",
            "Pin your elbows to your sides",
            "Extend your elbows to push the attachment down",
            "Return under control without letting your elbows drift forward",
        ),
        form_tips=(
            "Keep your torso still; only your forearms move",
            "Lean forward only slightly and keep your chest up",
        ),
        animation_key="triceps-pushdown",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "face-pull": ExerciseGuidance(
        technique_steps=(
            "Set a cable at roughly head height and grip the rope or bar",
            "Step back with your arms extended",
            "Pull the attachment toward your face, flaring your elbows high",
            "Pause with your hands beside your head",
            "Return under control",
        ),
        form_tips=(
            "Keep your shoulders down away from your ears at the start",
            "Pull with your upper back rather than your arms alone",
        ),
        animation_key="face-pull",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "front-squat": ExerciseGuidance(
        technique_steps=(
            "Rest the bar on your front shoulders with your fingertips under it",
            "Set your elbows high and your torso upright, then unrack",
            "Step back and brace before descending",
            "Squat down keeping your elbows up and your torso vertical",
            "Drive up through the whole foot",
        ),
        form_tips=(
            "High elbows keep the bar from rolling forward",
            "If wrist mobility limits the grip, cross your arms over the bar",
        ),
        animation_key="front-squat",
        sources=(SQUAT_KINEMATICS, SQUAT_DEPTH),
    ),
    "goblet-squat": ExerciseGuidance(
        technique_steps=(
            "Hold one weight vertically against your chest",
            "Set your feet roughly shoulder-width apart",
            "Brace and squat down between your legs",
            "Descend as deep as you can control with your heels planted",
            "Drive up and squeeze your glutes at the top",
        ),
        form_tips=(
            "Keep your elbows inside your knees at the bottom",
            "Keep your chest tall; the weight should not pull you forward",
        ),
        animation_key="goblet-squat",
        sources=(SQUAT_KINEMATICS, SQUAT_DEPTH),
    ),
    "sumo-deadlift": ExerciseGuidance(
        technique_steps=(
            "Take a wide stance with your toes pointed out",
            "Grip the bar inside your knees with your arms vertical",
            "Push your knees out and set a flat back",
            "Drive the floor away, extending hips and knees together",
            "Stand tall at the top, then lower under control",
        ),
        form_tips=(
            "Keep the bar over your mid-foot throughout",
            "Your hips start lower than in a conventional deadlift",
        ),
        animation_key="sumo-deadlift",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "good-morning": ExerciseGuidance(
        technique_steps=(
            "Carry the bar on your upper back as for a squat",
            "Keep a slight bend in your knees",
            "Hinge at your hips, lowering your torso toward parallel",
            "Keep your back flat and the bar over your mid-foot",
            "Extend your hips to return to standing",
        ),
        form_tips=(
            "Start with light loads; the lower back is the limiter",
            "Move slowly and stop at the depth you can hold flat",
        ),
        animation_key="good-morning",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "incline-bench-press": ExerciseGuidance(
        technique_steps=(
            "Set the bench to a moderate incline",
            "Lie back with your eyes under the bar and grip slightly wider than shoulder width",
            "Unrack and lower the bar to your upper chest",
            "Press up and slightly back until your arms are extended",
            "Rerack once the rep is complete",
        ),
        form_tips=(
            "Keep your shoulder blades pulled back against the bench",
            "Flare your elbows less than on a flat bench",
        ),
        animation_key="incline-bench-press",
        sources=(LIFT_MECHANICS, ACSM_STAND),
    ),
    "barbell-curl": ExerciseGuidance(
        technique_steps=(
            "Stand holding the bar with an underhand shoulder-width grip",
            "Keep your elbows pinned at your sides",
            "Curl the bar up by bending your elbows",
            "Lower under control to full extension",
        ),
        form_tips=(
            "Avoid swinging your hips; the torso stays still",
            "Squeeze at the top rather than resting the bar on your forearms",
        ),
        animation_key="barbell-curl",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "lying-triceps-extension": ExerciseGuidance(
        technique_steps=(
            "Lie on a flat bench holding the weight above your chest",
            "Keep your upper arms vertical and close together",
            "Bend your elbows to lower the weight toward your forehead",
            "Extend your elbows to return to the start",
        ),
        form_tips=(
            "Only your forearms move; your upper arms stay still",
            "Point your elbows slightly back rather than fully vertical",
        ),
        animation_key="lying-triceps-extension",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "dumbbell-overhead-press": ExerciseGuidance(
        technique_steps=(
            "Sit or stand with a dumbbell in each hand at shoulder height, palms forward",
            "Brace your torso",
            "Press the dumbbells overhead until your arms are extended",
            "Lower under control back to shoulder height",
        ),
        form_tips=(
            "Squeeze your glutes to keep the torso tall instead of arching",
            "Bring the dumbbells slightly toward each other at the top",
        ),
        animation_key="dumbbell-overhead-press",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "incline-dumbbell-bench-press": ExerciseGuidance(
        technique_steps=(
            "Set the bench to a moderate incline and lie back with a dumbbell in each hand",
            "Start with the dumbbells at chest level",
            "Press up until your arms are extended",
            "Lower under control to a full stretch",
        ),
        form_tips=(
            "Keep your wrists stacked over your elbows",
            "Control the descent; do not let the dumbbells drift wide",
        ),
        animation_key="incline-dumbbell-bench-press",
        sources=(LIFT_MECHANICS, ACSM_STAND),
    ),
    "one-arm-dumbbell-row": ExerciseGuidance(
        technique_steps=(
            "Place one knee and hand on a bench for support",
            "Hold the dumbbell in the free hand with your arm extended",
            "Keep your back flat and your torso nearly parallel to the floor",
            "Pull the dumbbell to your hip, leading with your elbow",
            "Lower under control to full extension",
        ),
        form_tips=(
            "Avoid rotating your torso to heave the weight",
            "One set covers one side; log each side separately",
        ),
        animation_key="one-arm-dumbbell-row",
        sources=(ACSM_STAND, PRESCRIPTION_REVIEW),
    ),
    "hammer-curl": ExerciseGuidance(
        technique_steps=(
            "Stand with a dumbbell in each hand, palms facing your sides",
            "Keep your elbows at your sides",
            "Curl the weights up while keeping the neutral grip",
            "Lower under control",
        ),
        form_tips=(
            "Keep your wrists neutral throughout",
            "Do not swing; your upper arms stay still",
        ),
        animation_key="hammer-curl",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "dumbbell-romanian-deadlift": ExerciseGuidance(
        technique_steps=(
            "Stand holding two dumbbells in front of your thighs",
            "Keep a slight bend in your knees",
            "Push your hips back and lower the dumbbells along your legs",
            "Descend until you feel a strong hamstring stretch",
            "Drive your hips forward to stand up",
        ),
        form_tips=(
            "Keep the dumbbells close to your legs",
            "Keep your back flat and your neck neutral",
        ),
        animation_key="dumbbell-romanian-deadlift",
        sources=(SQUAT_DEADLIFT_COMPARISON, ACSM_STAND),
    ),
    "kettlebell-swing": ExerciseGuidance(
        technique_steps=(
            "Stand with the kettlebell about one foot in front of you",
            "Hinge and grip the handle with both hands",
            "Hike the bell back between your legs",
            "Snap your hips forward to swing the bell to roughly chest height",
            "Let it fall back into the hinge and repeat",
        ),
        form_tips=(
            "The power comes from your hips, not your arms",
            "Keep your back flat and brace at the top of each swing",
        ),
        animation_key="kettlebell-swing",
        sources=(ACSM_STAND, SQUAT_DEADLIFT_COMPARISON),
    ),
    "chin-up": ExerciseGuidance(
        technique_steps=(
            "Grip the bar with an underhand grip about shoulder width",
            "Hang with your arms extended and your shoulders active",
            "Pull your chest toward the bar, leading with your elbows",
            "Continue until your chin clears the bar",
            "Lower under control to full arm extension",
        ),
        form_tips=(
            "Avoid kipping; start each rep from a controlled hang",
            "Think of pulling your elbows down and slightly forward",
        ),
        animation_key="chin-up",
        sources=(PULL_ACTIVATION, ACSM_STAND),
    ),
    "bodyweight-squat": ExerciseGuidance(
        technique_steps=(
            "Stand with your feet roughly shoulder-width apart, toes slightly out",
            "Brace your torso",
            "Sit down and back, bending your hips and knees together",
            "Descend as deep as you can control with your heels planted",
            "Stand up by pushing through the whole foot",
        ),
        form_tips=(
            "Keep your chest up and your knees tracking over your toes",
            "Use a full range of motion you can control without bouncing",
        ),
        animation_key="bodyweight-squat",
        sources=(SQUAT_KINEMATICS, SQUAT_DEPTH),
    ),
    "close-grip-push-up": ExerciseGuidance(
        technique_steps=(
            "Set your hands close together under your chest",
            "Keep your body in one straight line and brace",
            "Lower until your chest is close to your hands",
            "Push back up to full elbow extension",
        ),
        form_tips=(
            "Keep your elbows close to your torso",
            "If your wrists are uncomfortable, use handles or a slight hand angle",
        ),
        animation_key="close-grip-push-up",
        sources=(PUSHUP_REVIEW, ACSM_STAND),
    ),
}
